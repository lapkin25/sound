# sound_core3.py — v1.0
# v0.3 + FIX-1..FIX-5 + Trio Bridge + STRUCT/TRIOREC1/TRIOREC2 + codegen + vec-поля
from enum import IntEnum
import math
import json
import os

class ValueType(IntEnum):
    INT = 0
    FLOAT = 1
    BOOL = 2
    VEC = 3
    CLOSURE = 4
    ERR = 5
    STRUCT = 6

# Канонический журнал: входы, выходы, флаги. Всё, что течёт через мост, обязано здесь быть.
JOURNAL = []

_PI = float.fromhex("0x1.921fb54442d18p+1")  # π зафиксирована битами, не рантаймом

def _canon_float(x):
    # Канон: мантисса добита до 13 hex-цифр, знак порядка обязателен.
    if math.isnan(x):
        return "nan"                # TODO: payload NaN
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    if x == 0.0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    h = float(x).hex()              # '0x1.4p+3' или '-0x1.4p+3'
    sign = ""
    if h.startswith("-"):
        sign, h = "-", h[1:]
    if h.startswith("0x"):
        h = h[2:]
    mant, exp = h.split("p")
    int_part, _, frac = mant.partition(".")
    frac = (frac + "0" * 13)[:13]
    return f"{sign}0x{int_part}.{frac}p{exp}"

def _parse_canon_float(raw):
    s = raw.strip()
    if s == "inf": return math.inf
    if s == "-inf": return -math.inf
    if s == "nan": return math.nan
    if s in ("0.0", "-0.0"): return float(s)
    if s.startswith(("0x", "-0x", "+0x")):
        try:
            return float.fromhex(s)
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None

class Value:
    __slots__ = ("t", "v")
    def __init__(self, t, v):
        self.t = t
        self.v = v

    @staticmethod
    def i(x): return Value(ValueType.INT, x)
    @staticmethod
    def f(x): return Value(ValueType.FLOAT, x)
    @staticmethod
    def b(x): return Value(ValueType.BOOL, bool(x))
    @staticmethod
    def vec(xs): return Value(ValueType.VEC, xs)
    @staticmethod
    def clo(fn, env): return Value(ValueType.CLOSURE, (fn, env))
    @staticmethod
    def err(code): return Value(ValueType.ERR, code)
    @staticmethod
    def struct(name, fields, lossy=None):
        return Value(ValueType.STRUCT, (name, list(fields), dict(lossy or {})))

    def canon(self):
        return canon_val(self)

def _canon_raw(x):
    if isinstance(x, list):
        return "[" + ",".join(_canon_raw(e) for e in x) + "]"
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    return _canon_float(float(x))

def canon_val(v):
    t = v.t
    if t == ValueType.INT: return str(v.v)
    if t == ValueType.FLOAT: return _canon_float(v.v)
    if t == ValueType.BOOL: return "true" if v.v else "false"
    if t == ValueType.VEC: return _canon_raw(v.v)
    if t == ValueType.STRUCT:
        name, fields, _lossy = v.v
        inner = " ".join(f"{fn}={canon_val(fv)}" for fn, fv in fields)
        return "{" + f"{name} {inner}" + "}"
    if t == ValueType.CLOSURE: return "<closure>"
    if t == ValueType.ERR: return f"Err({v.v})"
    return "?"

def widen(v):
    # R-INT1: неограниченное целое -> double, только если |v| <= 2^53.
    # За границей — конверсия с ties-to-even и флаг lossy в журнал.
    if v.t == ValueType.INT:
        x = float(v.v)
        lossy = abs(v.v) > 2**53
        JOURNAL.append(f"widen {v.v} -> {_canon_float(x)}" + (" lossy=TRUE" if lossy else ""))
        return Value.f(x)
    if v.t == ValueType.FLOAT:
        return v
    return Value.err("TypeMismatch")

def narrow(v):
    # FIX-2: math.modf возвращает (frac, i), а не (i, frac)
    if v.t == ValueType.FLOAT:
        frac, i = math.modf(v.v)
        if frac == 0.0:
            return Value.i(int(i))
        return Value.err("PrecisionLoss")
    return Value.err("TypeMismatch")

def add(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    if a.t == ValueType.INT and b.t == ValueType.INT:
        return Value.i(a.v + b.v)
    # FIX-3: базовая ветка FLOAT-FLOAT — без неё рекурсия не завершается
    if a.t == ValueType.FLOAT and b.t == ValueType.FLOAT:
        return Value.f(a.v + b.v)
    return add(widen(a), widen(b))

def sub(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    if a.t == ValueType.INT and b.t == ValueType.INT:
        return Value.i(a.v - b.v)
    if a.t == ValueType.FLOAT and b.t == ValueType.FLOAT:  # FIX-3
        return Value.f(a.v - b.v)
    return sub(widen(a), widen(b))

def mul(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    if a.t == ValueType.INT and b.t == ValueType.INT:
        return Value.i(a.v * b.v)
    if a.t == ValueType.FLOAT and b.t == ValueType.FLOAT:  # FIX-3
        return Value.f(a.v * b.v)
    return mul(widen(a), widen(b))

def div(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    av = float(a.v) if a.t == ValueType.INT else a.v
    bv = float(b.v) if b.t == ValueType.INT else b.v
    if bv == 0.0:
        if av > 0: return Value.f(math.inf)
        if av < 0: return Value.f(-math.inf)
        return Value.f(math.nan)
    return Value.f(av / bv)

def eq(a, b):
    if a.t == ValueType.ERR or b.t == ValueType.ERR:
        return Value.err("PropError")
    if a.t != b.t:
        return Value.b(False)
    return Value.b(a.v == b.v)

def lt(a, b):
    if a.t == ValueType.ERR or b.t == ValueType.ERR:
        return Value.err("PropError")
    av = float(a.v) if a.t == ValueType.INT else a.v
    bv = float(b.v) if b.t == ValueType.INT else b.v
    return Value.b(av < bv)

def and_(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    return Value.b(bool(a.v) and bool(b.v))

def or_(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    return Value.b(bool(a.v) or bool(b.v))

def not_(v):
    if v.t == ValueType.ERR: return v
    return Value.b(not bool(v.v))

def make_closure(fn, env_snapshot):
    return Value.clo(fn, env_snapshot)

def apply_closure(v, arg):
    if v.t == ValueType.ERR: return v
    if v.t != ValueType.CLOSURE:
        return Value.err("ApplyOnNonClosure")
    fn, env = v.v
    return fn(env, arg)

def reduce_vec(vec_val, acc_val, step_fn):
    if vec_val.t == ValueType.ERR: return vec_val
    if acc_val.t == ValueType.ERR: return acc_val
    acc = acc_val
    for x in vec_val.v:
        acc = step_fn(acc, Value.f(x))
    return acc

def static_check(term, env_names):
    def walk(node, params):
        if isinstance(node, tuple):
            tag = node[0]
            if tag == "let":
                _, name, body, nxt = node
                return walk(body, params + [name]) and walk(nxt, params + [name])
            elif tag == "var":
                return node[1] in params  # SC-002
            elif tag == "app":
                return walk(node[1], params) and walk(node[2], params)
            elif tag == "if":
                return walk(node[1], params) and walk(node[2], params) and walk(node[3], params)
            elif tag == "fun":
                _, ps, body = node
                if len(set(ps)) != len(ps):
                    return False  # SC-060
                return walk(body, params + ps)
            elif tag == "vec":
                return all(walk(e, params) for e in node[1])
            else:
                for child in node[1:]:
                    if isinstance(child, list):
                        if not all(walk(c, params) for c in child):
                            return False
                    elif isinstance(child, tuple):
                        if not walk(child, params):
                            return False
                return True
        return True
    return walk(term, [])

# ============================================================
# Конструктор моделей: рекорды, сум-типы, сериализация
# ============================================================
RECORD_REGISTRY = {}

def _norm_value(x):
    if isinstance(x, Value):
        return x
    if isinstance(x, bool):
        return Value.b(x)
    if isinstance(x, int):
        return Value.i(x)
    if isinstance(x, float):
        return Value.f(x)
    if isinstance(x, (list, tuple)):
        return Value.vec(list(x))
    return Value.err("TypeError")

def _norm_vec_elements(xs):
    def go(x):
        if isinstance(x, bool):
            return None, True
        if isinstance(x, int):
            return float(x), abs(x) > 2**53
        if isinstance(x, float):
            return float(x), False
        if isinstance(x, list):
            vals, lossy = [], False
            for e in x:
                ev, el = go(e)
                if ev is None: return None, True
                lossy = lossy or el
                vals.append(ev)
            return vals, lossy
        return None, True
    return go(list(xs))

def _norm_fields(fs):
    out = []
    for f in fs:
        if isinstance(f, dict):
            out.append((f["name"], f["type"]))
        elif isinstance(f, (tuple, list)):
            out.append((f[0], f[1]))
    return out

class RecordType:
    def __init__(self, name, fields, invariants=None):
        self.name = name
        self.fields = list(fields)          # [(fname, kind)] — порядок есть канон
        self.invariants = invariants or []

    def construct(self, args):
        if not isinstance(args, dict):
            return Value.err("TypeError")
        extra = set(args) - {f[0] for f in self.fields}
        if extra:
            return Value.err("UnknownField:" + ",".join(sorted(extra)))
        checked = []
        lossy = {}
        for fname, kind in self.fields:
            if fname not in args:
                return Value.err("MissingField:" + fname)
            raw = args[fname]
            if kind == "float":
                v = _norm_value(raw)
                if v.t == ValueType.INT:
                    x = float(v.v)
                    l = abs(v.v) > 2**53
                    if l:
                        lossy[fname] = True
                        JOURNAL.append(f"STRUCT {self.name}.{fname} <- int {v.v} -> {_canon_float(x)} lossy=TRUE")
                    checked.append((fname, Value.f(x)))
                elif v.t == ValueType.FLOAT:
                    checked.append((fname, v))
                else:
                    return Value.err("TypeError:" + fname)
            elif kind == "int":
                v = _norm_value(raw)
                if v.t != ValueType.INT:
                    return Value.err("TypeError:" + fname)
                checked.append((fname, v))
            elif kind == "vec":
                if isinstance(raw, Value) and raw.t == ValueType.VEC:
                    raw_list = raw.v
                elif isinstance(raw, (list, tuple)):
                    raw_list = list(raw)
                else:
                    return Value.err("TypeError:" + fname)
                vals, l = _norm_vec_elements(raw_list)
                if vals is None:
                    return Value.err("TypeError:" + fname)
                if l:
                    lossy[fname] = True
                    JOURNAL.append(f"STRUCT {self.name}.{fname} <- vec element(s) beyond 2^53 lossy=TRUE")
                checked.append((fname, Value.vec(vals)))
            elif isinstance(kind, str) and kind.startswith("ref:"):
                v = _norm_value(raw)
                if v.t != ValueType.STRUCT:
                    return Value.err("TypeError:" + fname)
                if v.v[0] != kind[4:]:
                    return Value.err("TypeError:" + fname)
                checked.append((fname, v))
            else:
                return Value.err("TypeError:" + fname)
        # Инварианты предметной области — отсекают значение до конверсии типов
        for inv in self.invariants:
            fv = dict(checked).get(inv["field"])
            if fv is None:
                return Value.err("InvariantViolation:" + inv["field"])
            if inv.get("min") is not None and fv.v < inv["min"]:
                return Value.err("InvariantViolation:" + inv["field"])
            if inv.get("max") is not None and fv.v > inv["max"]:
                return Value.err("InvariantViolation:" + inv["field"])
        return Value.struct(self.name, checked, lossy)

class SumType:
    def __init__(self, name, variants):
        self.name = name
        self.variants = []
        for v in variants:
            if isinstance(v, dict):
                self.variants.append((v["name"], _norm_fields(v.get("fields", []))))
            elif isinstance(v, (tuple, list)):
                self.variants.append((v[0], _norm_fields(v[1])))

    def construct(self, variant, args):
        if variant not in {v[0] for v in self.variants}:
            return Value.err("UnknownVariant:" + variant)
        fs = next(v[1] for v in self.variants if v[0] == variant)
        return RecordType(variant, fs).construct(args)

def struct_eq(a, b):
    if a.t == ValueType.ERR or b.t == ValueType.ERR:
        return Value.err("PropError")
    if a.t != b.t:
        return Value.b(False)
    if a.t == ValueType.CLOSURE:
        return Value.b(a.v is b.v)
    return Value.b(canon_val(a) == canon_val(b))

def match_area(s):
    name, fields, _ = s.v
    d = dict(fields)
    if name == "Circle":
        return mul(Value.f(_PI), mul(d["r"], d["r"]))
    if name == "Rect":
        return mul(d["w"], d["h"])
    return Value.err("UnknownVariant:" + name)

# ---------- TRIOREC1: плоский рекорд ----------

def serialize_record(rec, registry):
    if rec.t != ValueType.STRUCT:
        return Value.err("SerializeError")
    name, fields, lossy = rec.v
    rt = registry.get(name)
    if rt is None:
        return Value.err("UnknownType:" + name)
    if not isinstance(rt, RecordType):
        return Value.err("SerializeError")   # сум-вариант как top-level не сериализуется
    if [f[0] for f in fields] != [f[0] for f in rt.fields]:
        return Value.err("FieldMismatch")
    lines = [json.dumps({"format": "TRIOREC1", "version": 1, "type": name,
                         "fields": [[fn, kd] for fn, kd in rt.fields],
                         "lossy": sorted(lossy.keys())},
                        separators=(",", ":"))]
    for fname, fv in fields:
        if fv.t == ValueType.INT:
            lines.append(str(fv.v))
        elif fv.t == ValueType.FLOAT:
            lines.append(_canon_float(fv.v))
        else:
            return Value.err("SerializeError")   # vec и вложенные рекорды — только в TRIOREC2
    return "\n".join(lines)

def load_record1(text, registry):
    lines = text.strip().split("\n")
    if not lines:
        return Value.err("BadFormat")
    try:
        header = json.loads(lines[0])
    except ValueError:
        return Value.err("BadFormat")
    if not isinstance(header, dict) or header.get("format") != "TRIOREC1" or header.get("version") != 1:
        return Value.err("BadFormat")
    name = header.get("type")
    rt = registry.get(name)
    if rt is None:
        return Value.err("UnknownType:" + str(name))
    if not isinstance(rt, RecordType):
        return Value.err("FieldMismatch")
    if [tuple(f) for f in header.get("fields", [])] != rt.fields:
        return Value.err("FieldMismatch")
    vals = lines[1:]
    if len(vals) != len(rt.fields):
        return Value.err("FieldMismatch")
    args = {}
    for (fname, kind), raw in zip(rt.fields, vals):
        if kind == "int":
            try:
                args[fname] = int(raw.strip())
            except ValueError:
                return Value.err("FieldMismatch")
        elif kind == "float":
            x = _parse_canon_float(raw)
            if x is None:
                return Value.err("FieldMismatch")
            args[fname] = x
        else:
            return Value.err("FieldMismatch")
    r = rt.construct(args)
    if r.t == ValueType.STRUCT:
        n2, f2, l2 = r.v
        merged = dict(l2)
        for path in header.get("lossy", []):
            merged[path] = True
        r = Value(ValueType.STRUCT, (n2, f2, merged))
    return r

# ---------- TRIOREC2: вложенные рекорды и vec-поля ----------

MAX_DEPTH = 64

def _vec_shape(xs):
    if not xs:
        return [0]
    if isinstance(xs[0], list):
        c = len(xs[0])
        if any(not isinstance(row, list) or len(row) != c for row in xs):
            return None
        return [len(xs), c]
    return [len(xs)]

def _vec_flat(xs):
    out = []
    def go(x):
        if isinstance(x, list):
            for e in x:
                go(e)
        else:
            out.append(x)
    go(xs)
    return out

def _serialize_vec_field(fv, fname):
    shape = _vec_shape(fv.v)
    if shape is None:
        return Value.err("SerializeError")
    flat = _vec_flat(fv.v)
    lines = ["@vec " + fname + " [" + ",".join(str(d) for d in shape) + "]"]
    lines.extend(_canon_float(x) for x in flat)
    return lines

def _collect_lossy(rec):
    # пути флагов потерь только из вложенных рекордов (свои ключи уже в карте)
    out = set()
    for fn, fv in rec.v[1]:
        if fv.t == ValueType.STRUCT:
            out |= {fn + "." + k for k in fv.v[2]}
            out |= {fn + "." + k for k in _collect_lossy(fv)}
    return out

def serialize_record2(rec, registry, depth=0):
    if depth > MAX_DEPTH:
        return Value.err("CycleDetected")
    if rec.t != ValueType.STRUCT:
        return Value.err("SerializeError")
    name, fields, lossy = rec.v
    rt = registry.get(name)
    if rt is None:
        return Value.err("UnknownType:" + name)
    if not isinstance(rt, RecordType):
        return Value.err("SerializeError")
    if [f[0] for f in fields] != [f[0] for f in rt.fields]:
        return Value.err("FieldMismatch")
    kinds = dict(rt.fields)
    body = []
    agg = set(lossy.keys())
    for fname, fv in fields:
        kind = kinds[fname]
        if fv.t == ValueType.INT:
            body.append(str(fv.v))
        elif fv.t == ValueType.FLOAT:
            body.append(_canon_float(fv.v))
        elif fv.t == ValueType.VEC:
            rows = _serialize_vec_field(fv, fname)
            if isinstance(rows, Value) and rows.t == ValueType.ERR:
                return rows
            body.extend(rows)
        elif fv.t == ValueType.STRUCT:
            if not (isinstance(kind, str) and kind.startswith("ref:")):
                return Value.err("SerializeError")
            if fv.v[0] != kind[4:]:
                return Value.err("TypeError:" + fname)
            block = serialize_record2(fv, registry, depth + 1)
            if isinstance(block, Value) and block.t == ValueType.ERR:
                return block
            # вложенный блок несёт полный TRIOREC2 со своим заголовком
            body.append("@begin " + fname + ":" + fv.v[0])
            body.extend(block.split("\n"))
            body.append("@end " + fname)
            agg |= {fname + "." + k for k in fv.v[2]}
            agg |= {fname + "." + k for k in _collect_lossy(fv)}
        else:
            return Value.err("SerializeError")
    header = {"format": "TRIOREC2", "version": 2, "type": name,
              "fields": [[fn, kd] for fn, kd in rt.fields],
              "lossy": sorted(agg)}
    return json.dumps(header, separators=(",", ":")) + "\n" + "\n".join(body)

def load_record2(text, registry, depth=0):
    if depth > MAX_DEPTH:
        return Value.err("CycleDetected")
    lines = text.strip().split("\n")
    if not lines:
        return Value.err("BadFormat")
    try:
        header = json.loads(lines[0])
    except ValueError:
        return Value.err("BadFormat")
    if not isinstance(header, dict) or header.get("format") != "TRIOREC2" or header.get("version") != 2:
        return Value.err("BadFormat")
    name = header.get("type")
    rt = registry.get(name)
    if rt is None:
        return Value.err("UnknownType:" + str(name))
    if not isinstance(rt, RecordType):
        return Value.err("FieldMismatch")
    if [tuple(f) for f in header.get("fields", [])] != rt.fields:
        return Value.err("FieldMismatch")
    hdr_lossy = set(header.get("lossy", []))
    body = lines[1:]
    args = {}
    i = 0
    for fname, kind in rt.fields:
        if kind == "vec":
            if i >= len(body) or not body[i].startswith("@vec "):
                return Value.err("FieldMismatch")
            parts = body[i].split()
            if len(parts) < 3 or parts[1] != fname:
                return Value.err("FieldMismatch")
            try:
                shape = json.loads(parts[2])
            except ValueError:
                return Value.err("FieldMismatch")
            n = 1
            for d in shape:
                n *= d
            vals_raw = body[i + 1:i + 1 + n]
            if len(vals_raw) != n:
                return Value.err("FieldMismatch")
            vals = []
            for rv in vals_raw:
                x = _parse_canon_float(rv)
                if x is None:
                    return Value.err("FieldMismatch")
                vals.append(x)
            if shape == [0]:
                args[fname] = []
            elif len(shape) == 1:
                args[fname] = vals
            elif len(shape) == 2:
                r_, c_ = shape
                args[fname] = [vals[j * c_:(j + 1) * c_] for j in range(r_)]
            else:
                return Value.err("FieldMismatch")
            i += 1 + n
        elif isinstance(kind, str) and kind.startswith("ref:"):
            if i >= len(body) or not body[i].startswith("@begin "):
                return Value.err("FieldMismatch")
            spec = body[i][len("@begin "):]
            if ":" not in spec:
                return Value.err("FieldMismatch")
            fntag, subname = spec.split(":", 1)
            if fntag != fname:
                return Value.err("FieldMismatch")
            endline = "@end " + fname
            j = i + 1
            depth_count = 0
            block = []
            found = False
            while j < len(body):
                s = body[j]
                if s.startswith("@begin "):
                    depth_count += 1
                    block.append(s)
                elif s.startswith("@end "):
                    if depth_count == 0 and s == endline:
                        found = True
                        break
                    depth_count -= 1
                    block.append(s)
                else:
                    block.append(s)
                j += 1
            if not found:
                return Value.err("FieldMismatch")
            sub = load_record2("\n".join(block), registry, depth + 1)
            if sub.t == ValueType.ERR:
                return sub
            if sub.v[0] != subname:
                return Value.err("FieldMismatch")
            args[fname] = sub
            i = j + 1
        elif kind == "int":
            if i >= len(body):
                return Value.err("FieldMismatch")
            try:
                args[fname] = int(body[i].strip())
            except ValueError:
                return Value.err("FieldMismatch")
            i += 1
        elif kind == "float":
            if i >= len(body):
                return Value.err("FieldMismatch")
            x = _parse_canon_float(body[i])
            if x is None:
                return Value.err("FieldMismatch")
            args[fname] = x
            i += 1
        else:
            return Value.err("FieldMismatch")
    if i != len(body):
        return Value.err("FieldMismatch")
    r = rt.construct(args)
    if r.t == ValueType.STRUCT:
        n2, f2, l2 = r.v
        merged = dict(l2)
        for path in hdr_lossy:
            merged[path] = True
        r = Value(ValueType.STRUCT, (n2, f2, merged))
    return r

# ---------- Кодогенератор моделей ----------

def generate_model(spec):
    if not isinstance(spec, dict) or spec.get("format") != "TRIOMODEL1":
        return Value.err("SpecError")
    out = []
    for t in spec.get("types", []):
        kind = t.get("kind")
        if kind == "record":
            fields = [(f["name"], f["type"]) for f in t.get("fields", [])]
            invs = [{"field": iv["field"], "min": iv.get("min"), "max": iv.get("max")}
                    for iv in t.get("invariants", [])]
            rt = RecordType(t["name"], fields, invs)
            RECORD_REGISTRY[t["name"]] = rt
            out.append(rt)
        elif kind == "sum":
            st = SumType(t["name"], t.get("variants", []))
            RECORD_REGISTRY[t["name"]] = st
            out.append(st)
        else:
            return Value.err("SpecError")
    return Value.vec(out)

def registry_fingerprint():
    parts = []
    for name in sorted(RECORD_REGISTRY):
        rt = RECORD_REGISTRY[name]
        if isinstance(rt, RecordType):
            parts.append(name + "(" + ".".join(fn + ":" + kd for fn, kd in rt.fields) + ")")
        else:
            parts.append(name + "[" + "|".join(
                vn + "(" + ".".join(fn + ":" + kd for fn, kd in fs) + ")"
                for vn, fs in rt.variants) + "]")
    return ";".join(parts)

# ============================================================
# Trio Bridge: узлы. Точки склейки — диспетчер и маппинг значений.
# ============================================================
class NodeError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"Err({code}): {message}")

NODE_SPECS = {}

def load_manifest(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes", "manifest.json")
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        data = json.load(f)
    for n in data.get("nodes", []):
        NODE_SPECS[n["name"]] = n
    return len(NODE_SPECS)

def to_triomat_value(v, dtype="Float64", name="?"):
    """SoundValue -> payload TRIOMAT. R-INT1 живёт здесь. Журнал входа — всегда."""
    if not isinstance(v, Value):
        if isinstance(v, bool): v = Value.b(v)
        elif isinstance(v, int): v = Value.i(v)
        elif isinstance(v, float): v = Value.f(v)
        elif isinstance(v, (list, tuple)): v = Value.vec(list(v))
    if v.t == ValueType.VEC:
        xs = v.v
        if xs and isinstance(xs[0], list):
            r, c = len(xs), len(xs[0])
            vals = [float(x) for row in xs for x in row]
            JOURNAL.append(f"IN {name} [{r},{c}] = " + " ".join(_canon_float(x) for x in vals))
            return {"dtype": "Float64", "shape": [r, c], "values": vals, "lossy": False}
        vals = [float(x) for x in xs]
        JOURNAL.append(f"IN {name} [{len(vals)}] = " + " ".join(_canon_float(x) for x in vals))
        return {"dtype": "Float64", "shape": [len(vals)], "values": vals, "lossy": False}
    if v.t in (ValueType.INT, ValueType.FLOAT) and dtype == "Float64":
        if v.t == ValueType.INT:
            lossy = abs(v.v) > 2**53
            x = float(v.v)
        else:
            lossy, x = False, v.v
        JOURNAL.append(f"IN {name}[] = {_canon_float(x)}" + (" lossy=TRUE" if lossy else ""))
        return {"dtype": dtype, "shape": [], "values": [x], "lossy": lossy}
    if v.t == ValueType.INT and dtype == "Int64":
        JOURNAL.append(f"IN {name}[] = {int(v.v)}")
        return {"dtype": dtype, "shape": [], "values": [int(v.v)], "lossy": False}
    raise NodeError("TypeError", f'input "{name}": unsupported SoundValue/type combo')

def from_triomat_value(payload):
    """shape [] -> скаляр, [n] -> вектор, [r,c] -> матрица (row-major)."""
    shape, values = payload["shape"], payload["values"]
    if shape == []:
        return Value.f(values[0])
    if len(shape) == 1:
        return Value.vec(values)
    r, c = shape
    return Value.vec([values[i * c:(i + 1) * c] for i in range(r)])

def octave_backend_emulated(spec, files, workdir="."):
    # Эмуляция той же арифметики, что в run_mat_mul_scalar_octave.m
    if spec["name"] != "mat_mul_scalar_octave":
        raise NodeError("ProcessError", "unknown node for emulated backend")
    A, k = files["A"], files["k"]
    if not (isinstance(A["shape"], list) and len(A["shape"]) == 2):
        raise NodeError("ShapeError", 'input "A" must be a matrix')
    if k["shape"] != []:
        raise NodeError("ShapeError", 'input "k" must be a scalar')
    r, c = A["shape"]
    B = [x * k["values"][0] for x in A["values"]]
    return {"B": {"dtype": "Float64", "shape": [r, c], "values": B, "lossy": False}}

def octave_backend_real(spec, files, workdir="."):
    # OPEN-гейт: требует установленный Octave.
    # subprocess.run(["octave", "--no-gui", "--quiet", f"run_{spec['name']}.m"], cwd=workdir)
    raise NodeError("ProcessError", "real octave backend not wired yet (OPEN gate)")

def run_node(spec, inputs, backend, workdir="."):
    files = {}
    for io in spec["inputs"]:
        nm = io["name"]
        if nm not in inputs:
            return None, ("ShapeError", f'missing input "{nm}"')
        try:
            files[nm] = to_triomat_value(inputs[nm], io.get("dtype", "Float64"), nm)
        except NodeError as e:
            return None, (e.code, e.message)
    try:
        results = backend(spec, files, workdir)
    except NodeError as e:
        return None, (e.code, e.message)
    outputs = {}
    for io in spec["outputs"]:
        nm = io["name"]
        if nm not in results:
            return None, ("ProcessError", f'backend did not produce "{nm}"')
        payload = results[nm]
        if payload["dtype"] != io.get("dtype", "Float64"):
            return None, ("TypeError", f'output "{nm}": dtype={payload["dtype"]}, expected {io["dtype"]}')
        outs = from_triomat_value(payload)
        if outs.v and isinstance(outs.v[0], list):
            flat = [x for row in outs.v for x in row]
        elif isinstance(outs.v, list):
            flat = outs.v
        else:
            flat = [outs.v]
        JOURNAL.extend(f"OUT {nm}[{j}] = {_canon_float(x)}" for j, x in enumerate(flat))
        outputs[nm] = outs
    return outputs, None

def eval_node_call(name, args, backend=None):
    """Диспетчер узловых вызовов. Ошибка приходит как Err(code) — как положено в SCore."""
    spec = NODE_SPECS.get(name)
    if spec is None:
        return Value.err("NodeNotFound")
    outputs, err = run_node(
        spec,
        {io["name"]: a for io, a in zip(spec["inputs"], args)},
        backend or octave_backend_emulated,
    )
    if err:
        return Value.err(err[0])
    if len(outputs) == 1:
        return next(iter(outputs.values()))
    return Value.vec([outputs[io["name"]] for io in spec["outputs"]])

# ============================================================
# Батарея тестов (89 в полной версии; здесь — 10 реализованных)
# ============================================================
def run_battery():
    tests_passed = 0
    tests_total = 89

    # Пин π: канон должен совпасть бит-в-бит
    if _canon_float(_PI) == "0x1.921fb54442d18p+1":
        tests_passed += 1

    # T06: лексический захват
    def mk_f(env_snap):
        def fn(clo_env, y):
            return add(clo_env["x1"], y)  # снимок на момент создания замыкания
        return Value.clo(fn, env_snap)
    env1 = {"x1": Value.i(105), "f": mk_f({"x1": Value.i(1)})}
    res = apply_closure(env1["f"], Value.i(5))
    if res.canon() == "6":
        tests_passed += 1

    # T07: reduce с шагами
    def step(acc, x):
        return add(acc, x)
    r = reduce_vec(Value.vec([1.0, 2.0, 3.0, 4.0]), Value.i(0), step)
    if r.canon() == "0x1.4000000000000p+3":
        tests_passed += 1

    # T11: narrow
    if narrow(Value.f(3.5)).canon().startswith("Err(PrecisionLoss") and narrow(Value.f(3.0)).canon() == "3":
        tests_passed += 1

    # T12: R-INT1 ties-to-even на границе 2^53
    cases = ((2**53,     "0x1.0000000000000p+53", False),
             (2**53 + 2, "0x1.0000000000001p+53", True),
             (2**53 + 3, "0x1.0000000000002p+53", True))
    for x, want, want_lossy in cases:
        JOURNAL.clear()
        w = widen(Value.i(x))
        if w.t != ValueType.FLOAT or _canon_float(w.v) != want:
            break
        entry = next((e for e in JOURNAL if e.startswith("widen")), "")
        if ("lossy=TRUE" in entry) != want_lossy:
            break
    else:
        tests_passed += 1

    # T13: мост узлов
    NODE_SPECS["mat_mul_scalar_octave"] = {
        "name": "mat_mul_scalar_octave", "backend": "octave",
        "inputs": [{"name": "A", "type": "matrix", "dtype": "Float64"},
                   {"name": "k", "type": "scalar", "dtype": "Float64"}],
        "outputs": [{"name": "B", "type": "matrix", "dtype": "Float64"}],
    }
    JOURNAL.clear()
    r13 = eval_node_call("mat_mul_scalar_octave",
                         [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.f(2.0)])
    ok13 = (r13.t == ValueType.VEC and r13.v == [[2.0, 4.0], [6.0, 8.0]]
            and "OUT B[3] = 0x1.0000000000000p+3" in JOURNAL)
    JOURNAL.clear()
    r13e = eval_node_call("mat_mul_scalar_octave",
                          [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.vec([1.0])])
    ok13 = ok13 and r13e.t == ValueType.ERR and r13e.v == "ShapeError"
    ok13 = ok13 and any(e.startswith("IN A [2,2]") for e in JOURNAL)
    JOURNAL.clear()
    eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0]]), Value.i(2**53 + 1)])
    ok13 = ok13 and any(e.startswith("IN k[] =") and "lossy=TRUE" in e for e in JOURNAL)
    if ok13:
        tests_passed += 1

    # T14: STRUCT — рекорды, сум-типы, побитовое равенство
    RECORD_REGISTRY["Point"] = RecordType("Point", [("x", "float"), ("y", "float")])
    RECORD_REGISTRY["Shape"] = SumType("Shape", [
        ("Circle", [("r", "float")]),
        ("Rect", [("w", "float"), ("h", "float")]),
    ])
    pt = RECORD_REGISTRY["Point"].construct({"x": 1.5, "y": 2})
    ok14 = pt.t == ValueType.STRUCT
    ok14 = ok14 and canon_val(pt) == "{Point x=0x1.8000000000000p+0 y=0x1.0000000000000p+1}"
    ok14 = ok14 and struct_eq(pt, RECORD_REGISTRY["Point"].construct({"x": 1.5, "y": 2})).v is True
    p0 = RECORD_REGISTRY["Point"].construct({"x": 0.0, "y": 0.0})
    pm = RECORD_REGISTRY["Point"].construct({"x": -0.0, "y": 0.0})
    ok14 = ok14 and struct_eq(p0, pm).v is False
    ok14 = ok14 and RECORD_REGISTRY["Point"].construct({"x": 1.5, "y": 2, "z": 9}).canon() == "Err(UnknownField:z)"
    ok14 = ok14 and RECORD_REGISTRY["Point"].construct({"x": 1.5}).canon() == "Err(MissingField:y)"
    ok14 = ok14 and RECORD_REGISTRY["Point"].construct({"x": "s", "y": 2}).canon() == "Err(TypeError:x)"
    JOURNAL.clear()
    pd = RECORD_REGISTRY["Point"].construct({"x": 2**53 + 1, "y": 0})
    ok14 = ok14 and pd.t == ValueType.STRUCT and pd.v[2].get("x") is True
    ok14 = ok14 and any(e.startswith("STRUCT Point.x") and "lossy=TRUE" in e for e in JOURNAL)
    a1 = match_area(RECORD_REGISTRY["Shape"].construct("Circle", {"r": 2}))
    ok14 = ok14 and a1.t == ValueType.FLOAT and _canon_float(a1.v) == "0x1.921fb54442d18p+3"
    a2 = match_area(RECORD_REGISTRY["Shape"].construct("Rect", {"w": 2, "h": 3}))
    ok14 = ok14 and a2.t == ValueType.FLOAT and _canon_float(a2.v) == "0x1.8000000000000p+2"
    ok14 = ok14 and RECORD_REGISTRY["Shape"].construct("Triangle", {"r": 1}).canon() == "Err(UnknownVariant:Triangle)"
    if ok14:
        tests_passed += 1

    # T15: TRIOREC1 — roundtrip, детерминизм, -0.0, флаги
    rec_p = RECORD_REGISTRY["Point"].construct({"x": 1.5, "y": 2.0})
    s1 = serialize_record(rec_p, RECORD_REGISTRY)
    ok15 = isinstance(s1, str) and s1.startswith('{"format":"TRIOREC1"')
    ok15 = ok15 and s1 == serialize_record(RECORD_REGISTRY["Point"].construct({"x": 1.5, "y": 2.0}), RECORD_REGISTRY)
    r15 = load_record1(s1, RECORD_REGISTRY)
    ok15 = ok15 and r15.t == ValueType.STRUCT and struct_eq(r15, rec_p).v is True
    rec_m = RECORD_REGISTRY["Point"].construct({"x": -0.0, "y": 0.0})
    r15b = load_record1(serialize_record(rec_m, RECORD_REGISTRY), RECORD_REGISTRY)
    ok15 = ok15 and r15b.t == ValueType.STRUCT and struct_eq(r15b, rec_m).v is True
    ok15 = ok15 and struct_eq(r15b, rec_p).v is False
    rec_l = RECORD_REGISTRY["Point"].construct({"x": 2**53 + 3, "y": 0})
    s15l = serialize_record(rec_l, RECORD_REGISTRY)
    ok15 = ok15 and isinstance(s15l, str) and '"lossy":["x"]' in s15l
    r15c = load_record1(s15l, RECORD_REGISTRY)
    ok15 = ok15 and r15c.t == ValueType.STRUCT and r15c.v[2].get("x") is True
    ok15 = ok15 and load_record1(
        '{"format":"TRIOREC1","version":1,"type":"Triangle","fields":[],"lossy":[]}',
        RECORD_REGISTRY).canon() == "Err(UnknownType:Triangle)"
    ok15 = ok15 and load_record1("{}", RECORD_REGISTRY).canon() == "Err(BadFormat)"
    errser = serialize_record(Value.err("X"), RECORD_REGISTRY)
    ok15 = ok15 and errser.t == ValueType.ERR and errser.canon() == "Err(SerializeError)"
    if ok15:
        tests_passed += 1

    # T16: кодогенератор
    spec16 = {"format": "TRIOMODEL1", "types": [
        {"kind": "record", "name": "Dolphin",
         "fields": [{"name": "id", "type": "int"}, {"name": "score", "type": "float"}],
         "invariants": [{"field": "score", "min": 0.0, "max": 100.0}]},
        {"kind": "record", "name": "Pod", "fields": [{"name": "capacity", "type": "float"}]},
        {"kind": "sum", "name": "Shape",
         "variants": [{"name": "Circle", "fields": [{"name": "r", "type": "float"}]},
                      {"name": "Rect", "fields": [{"name": "w", "type": "float"},
                                                  {"name": "h", "type": "float"}]}]},
    ]}
    RECORD_REGISTRY.clear()
    gen = generate_model(spec16)
    ok16 = gen.t == ValueType.VEC and len(gen.v) == 3
    fp1 = registry_fingerprint()
    RECORD_REGISTRY.clear()
    generate_model(spec16)
    ok16 = ok16 and registry_fingerprint() == fp1
    ok16 = ok16 and fp1 == "Dolphin(id:int.score:float);Pod(capacity:float);Shape[Circle(r:float)|Rect(w:float.h:float)]"
    d16 = RECORD_REGISTRY["Dolphin"].construct({"id": 7, "score": 0.98})
    ok16 = ok16 and canon_val(d16) == "{Dolphin id=7 score=0x1.f5c28f5c28f5cp-1}"
    ok16 = ok16 and RECORD_REGISTRY["Dolphin"].construct({"id": 7, "score": 150.0}).canon() == "Err(InvariantViolation:score)"
    ok16 = ok16 and RECORD_REGISTRY["Dolphin"].construct({"id": 7, "score": 100.0}).t == ValueType.STRUCT
    JOURNAL.clear()
    pc16 = RECORD_REGISTRY["Pod"].construct({"capacity": 2**53 + 3})
    ok16 = ok16 and pc16.t == ValueType.STRUCT and pc16.v[2].get("capacity") is True
    ok16 = ok16 and any("lossy=TRUE" in e for e in JOURNAL)
    ok16 = ok16 and RECORD_REGISTRY["Dolphin"].construct({"id": 7}).canon() == "Err(MissingField:score)"
    ok16 = ok16 and RECORD_REGISTRY["Dolphin"].construct({"id": 7, "score": 1.0, "junk": 1}).canon() == "Err(UnknownField:junk)"
    ok16 = ok16 and RECORD_REGISTRY["Dolphin"].construct({"id": "x", "score": 1.0}).canon() == "Err(TypeError:id)"
    ok16 = ok16 and generate_model({"format": "TRIOMODEL1", "types": [{"kind": "wat", "name": "X"}]}).canon() == "Err(SpecError)"
    a16 = match_area(RECORD_REGISTRY["Shape"].construct("Circle", {"r": 2}))
    ok16 = ok16 and a16.t == ValueType.FLOAT and _canon_float(a16.v) == "0x1.921fb54442d18p+3"
    a16r = match_area(RECORD_REGISTRY["Shape"].construct("Rect", {"w": 2, "h": 3}))
    ok16 = ok16 and a16r.t == ValueType.FLOAT and _canon_float(a16r.v) == "0x1.8000000000000p+2"
    ok16 = ok16 and RECORD_REGISTRY["Shape"].construct("Triangle", {"r": 1}).canon() == "Err(UnknownVariant:Triangle)"
    ok16 = ok16 and serialize_record2(d16, RECORD_REGISTRY) == serialize_record2(
        RECORD_REGISTRY["Dolphin"].construct({"id": 7, "score": 0.98}), RECORD_REGISTRY)
    r16rt = load_record2(serialize_record2(d16, RECORD_REGISTRY), RECORD_REGISTRY)
    ok16 = ok16 and r16rt.t == ValueType.STRUCT and struct_eq(r16rt, d16).v is True
    if ok16:
        tests_passed += 1

    # T17: TRIOREC2 — вложенные рекорды и ref
    RECORD_REGISTRY["Dolphin2"] = RecordType("Dolphin2", [("id", "int"), ("score", "float"), ("pod", "ref:Pod2")])
    RECORD_REGISTRY["Pod2"] = RecordType("Pod2", [("capacity", "float")])
    RECORD_REGISTRY["Chain"] = RecordType("Chain", [("next", "ref:Chain")])
    pod17 = RECORD_REGISTRY["Pod2"].construct({"capacity": 20.0})
    dol = RECORD_REGISTRY["Dolphin2"].construct({"id": 7, "score": 0.98, "pod": pod17})
    s17 = serialize_record2(dol, RECORD_REGISTRY)
    ok17 = isinstance(s17, str) and "@begin pod:Pod2" in s17 and "@end pod" in s17
    r17 = load_record2(s17, RECORD_REGISTRY)
    ok17 = ok17 and r17.t == ValueType.STRUCT and struct_eq(r17, dol).v is True
    s17b = serialize_record2(RECORD_REGISTRY["Dolphin2"].construct(
        {"id": 7, "score": 0.98, "pod": pod17}), RECORD_REGISTRY)
    ok17 = ok17 and s17 == s17b
    JOURNAL.clear()
    podL = RECORD_REGISTRY["Pod2"].construct({"capacity": 2**53 + 3})
    dolL = RECORD_REGISTRY["Dolphin2"].construct({"id": 7, "score": 0.98, "pod": podL})
    s17L = serialize_record2(dolL, RECORD_REGISTRY)
    ok17 = ok17 and isinstance(s17L, str) and '"lossy":["pod.capacity"]' in s17L.split("\n")[0]
    nested = next((l for l in s17L.split("\n")
                   if l.startswith('{"format":"TRIOREC2"') and '"type":"Pod2"' in l), "")
    ok17 = ok17 and '"lossy":["capacity"]' in nested
    r17L = load_record2(s17L, RECORD_REGISTRY)
    ok17 = ok17 and r17L.t == ValueType.STRUCT and r17L.v[2].get("pod.capacity") is True
    wrong = RECORD_REGISTRY["Dolphin2"].construct(
        {"id": 7, "score": 0.98, "pod": RECORD_REGISTRY["Shape"].construct("Circle", {"r": 1})})
    ok17 = ok17 and wrong.t == ValueType.ERR and wrong.canon() == "Err(TypeError:pod)"
    tam = s17.replace('"type":"Pod2"', '"type":"Ghost"', 1)
    ok17 = ok17 and load_record2(tam, RECORD_REGISTRY).canon() == "Err(UnknownType:Ghost)"
    ser17 = serialize_record(dol, RECORD_REGISTRY)
    ok17 = ok17 and ser17.t == ValueType.ERR and ser17.canon() == "Err(SerializeError)"
    cyc = Value(ValueType.STRUCT, ("Chain", [("next", None)], {}))
    cyc.v[1][0] = ("next", cyc)   # цикл создаётся только прямой мутацией — конструктор ацикличен
    cyser = serialize_record2(cyc, RECORD_REGISTRY)
    ok17 = ok17 and cyser.t == ValueType.ERR and cyser.canon() == "Err(CycleDetected)"
    if ok17:
        tests_passed += 1

    # T18: vec-поля в TRIOREC2
    RECORD_REGISTRY["Pod3"] = RecordType("Pod3", [("observations", "vec"), ("vals", "vec")])
    RECORD_REGISTRY["MatDemo"] = RecordType("MatDemo", [("m", "vec")])
    RECORD_REGISTRY["VecDemo"] = RecordType("VecDemo", [("xs", "vec")])
    p3 = RECORD_REGISTRY["Pod3"].construct({"observations": [1, 2, 3], "vals": [1, 2**53 + 3]})
    ok18 = p3.t == ValueType.STRUCT and p3.v[2].get("vals") is True
    ok18 = ok18 and canon_val(p3.v[1][0][1]) == "[0x1.0000000000000p+0,0x1.0000000000000p+1,0x1.8000000000000p+1]"
    s18 = serialize_record2(p3, RECORD_REGISTRY)
    ok18 = ok18 and isinstance(s18, str) and "@vec observations [3]" in s18 and "@vec vals [2]" in s18
    ok18 = ok18 and '"lossy":["vals"]' in s18.split("\n")[0]
    r18 = load_record2(s18, RECORD_REGISTRY)
    ok18 = ok18 and r18.t == ValueType.STRUCT and struct_eq(r18, p3).v is True
    ok18 = ok18 and r18.v[2].get("vals") is True
    mat = RECORD_REGISTRY["MatDemo"].construct({"m": [[1, 2], [3, 4]]})
    s18m = serialize_record2(mat, RECORD_REGISTRY)
    ok18 = ok18 and isinstance(s18m, str) and "@vec m [2,2]" in s18m
    r18m = load_record2(s18m, RECORD_REGISTRY)
    ok18 = ok18 and r18m.t == ValueType.STRUCT and struct_eq(r18m, mat).v is True
    emp = RECORD_REGISTRY["VecDemo"].construct({"xs": []})
    s18e = serialize_record2(emp, RECORD_REGISTRY)
    ok18 = ok18 and isinstance(s18e, str) and "@vec xs [0]" in s18e
    r18e = load_record2(s18e, RECORD_REGISTRY)
    ok18 = ok18 and r18e.t == ValueType.STRUCT and struct_eq(r18e, emp).v is True
    bad18 = s18.replace("@vec vals [2]", "@vec vals [3]")
    ok18 = ok18 and load_record2(bad18, RECORD_REGISTRY).canon() == "Err(FieldMismatch)"
    ser18 = serialize_record(p3, RECORD_REGISTRY)
    ok18 = ok18 and ser18.t == ValueType.ERR and ser18.canon() == "Err(SerializeError)"
    ok18 = ok18 and s18 == serialize_record2(RECORD_REGISTRY["Pod3"].construct(
        {"observations": [1, 2, 3], "vals": [1, 2**53 + 3]}), RECORD_REGISTRY)
    if ok18:
        tests_passed += 1

    print(f"Battery: {tests_passed}/{tests_total}")
    return tests_passed == tests_total

if __name__ == "__main__":
    ok = run_battery()
    print("OK" if ok else "FAIL")
