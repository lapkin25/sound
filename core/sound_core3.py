# sound_core3.py — v1.0
# Ядро SCore v0.3 + FIX-1..FIX-5 + Trio Bridge + STRUCT/STR
# + TRIOREC1/TRIOREC2 (vec-поля) + кодогенератор TRIOMODEL1 + TRIOBOOK1
# Реализованная батарея: пин pi + T06..T19 (12 из 89)
from enum import IntEnum
import math
import json
import os
import re

_PI = float.fromhex("0x1.921fb54442d18p+1")   # pi зафиксирована битами, не рантаймом

class ValueType(IntEnum):
    INT = 0
    FLOAT = 1
    BOOL = 2
    VEC = 3
    CLOSURE = 4
    ERR = 5
    STRUCT = 6
    STR = 7

class Value:
    __slots__ = ("t", "v")
    def __init__(self, t, v):
        self.t = t
        self.v = v

    @staticmethod
    def i(x): return Value(ValueType.INT, int(x))
    @staticmethod
    def f(x): return Value(ValueType.FLOAT, float(x))
    @staticmethod
    def b(x): return Value(ValueType.BOOL, bool(x))
    @staticmethod
    def vec(xs): return Value(ValueType.VEC, list(xs))
    @staticmethod
    def clo(fn, env): return Value(ValueType.CLOSURE, (fn, env))
    @staticmethod
    def err(code): return Value(ValueType.ERR, code)
    @staticmethod
    def struct(name, fields, lossy=None):
        return Value(ValueType.STRUCT, (name, list(fields), dict(lossy or {})))
    @staticmethod
    def s(text): return Value(ValueType.STR, str(text))

    def canon(self):
        return canon_val(self)

# --- канон -------------------------------------------------------------

JOURNAL = []

def _canon_float(x):
    # Канон: мантисса добита до 13 hex-цифр, знак порядка обязателен.
    if math.isnan(x):
        return "nan"                 # TODO(v-next): payload NaN
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    if x == 0.0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    h = float(x).hex()
    sign = ""
    if h.startswith("-"):
        sign, h = "-", h[1:]
    if h.startswith("0x"):
        h = h[2:]
    mant, exp = h.split("p")
    int_part, _, frac = mant.partition(".")
    frac = (frac + "0" * 13)[:13]
    return f"{sign}0x{int_part}.{frac}p{exp}"

def _parse_canon_float(s):
    if s == "nan": return math.nan
    if s == "inf": return math.inf
    if s == "-inf": return -math.inf
    if s == "0.0": return 0.0
    if s == "-0.0": return -0.0
    return float.fromhex(s)

def _norm_scalar(x):
    if isinstance(x, Value):
        return x
    if isinstance(x, bool):
        return Value.b(x)
    if isinstance(x, int):
        return Value.i(x)
    if isinstance(x, float):
        return Value.f(x)
    if isinstance(x, str):
        return Value.s(x)
    return Value.err("TypeError")

def _norm_vec(x):
    # Принимает и плоский вектор, и матрицу (со стражем рваных строк).
    if isinstance(x, Value):
        return x if x.t == ValueType.VEC else Value.err("TypeError")
    if isinstance(x, list):
        if x and isinstance(x[0], (list, tuple)):
            width = len(x[0])
            for r in x:
                if not isinstance(r, (list, tuple)) or len(r) != width:
                    return Value.err("ShapeError")
            return Value.vec([_norm_vec(list(r)) for r in x])
        return Value.vec([_norm_scalar(e) for e in x])
    return Value.err("TypeError")

def canon_val(v):
    if not isinstance(v, Value):
        v = _norm_scalar(v)
    if v.t == ValueType.INT: return str(v.v)
    if v.t == ValueType.FLOAT: return _canon_float(v.v)
    if v.t == ValueType.BOOL: return "true" if v.v else "false"
    if v.t == ValueType.STR: return json.dumps(v.v, ensure_ascii=False)
    if v.t == ValueType.VEC:
        return "[" + ",".join(canon_val(e) for e in v.v) + "]"
    if v.t == ValueType.STRUCT:
        name, fields, lossy = v.v
        parts = [f"{fn}={canon_val(fv)}" for fn, fv in fields]
        s = "{" + name + (" " + " ".join(parts) if parts else "")
        if lossy:
            s += " lossy=[" + ",".join(sorted(k for k, on in lossy.items() if on)) + "]"
        return s + "}"
    if v.t == ValueType.CLOSURE: return "<closure>"
    if v.t == ValueType.ERR: return f"Err({v.v})"
    return "?"

def widen(v):
    # R-INT1: неограниченное целое -> double, только если |v| <= 2^53.
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
    if a.t == ValueType.FLOAT and b.t == ValueType.FLOAT:  # FIX-3
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
    if a.t == ValueType.STRUCT or b.t == ValueType.STRUCT:
        return struct_eq(a, b)
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
        acc = step_fn(acc, x if isinstance(x, Value) else Value.f(x))
    return acc

def static_check(term, env_names):
    def walk(node, params):
        if isinstance(node, tuple):
            tag = node[0]
            if tag == "let":
                _, name, body, nxt = node
                return walk(body, params + [name]) and walk(nxt, params + [name])
            elif tag == "var":
                _, name = node
                return name in params
            elif tag == "app":
                _, f, x = node
                return walk(f, params) and walk(x, params)
            elif tag == "if":
                _, c, t, e = node
                return walk(c, params) and walk(t, params) and walk(e, params)
            elif tag == "fun":
                _, ps, body = node
                if len(set(ps)) != len(ps):
                    return False
                return walk(body, params + list(ps))
            elif tag == "vec":
                _, elems = node
                return all(walk(e, params) for e in elems)
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

# --- структуры: рекорды и сум-типы --------------------------------------

MAX_DEPTH = 64
RECORD_REGISTRY = {}

def register_type(t):
    RECORD_REGISTRY[t.name] = t

def _widen_vec(nv):
    # R-INT1 на элементах vec: флаг теряется нельзя (урок T13).
    lossy = [False]
    def conv(e):
        if e.t == ValueType.FLOAT:
            return Value.f(e.v)
        if e.t == ValueType.INT:
            x = float(e.v)
            l = abs(e.v) > 2**53
            if l: lossy[0] = True
            JOURNAL.append(f"STRUCT vec elem <- int {e.v} -> {_canon_float(x)}" + (" lossy=TRUE" if l else ""))
            return Value.f(x)
        return None
    if nv.v and isinstance(nv.v[0], Value) and nv.v[0].t == ValueType.VEC:
        rows = []
        for row in nv.v:
            if row.t != ValueType.VEC:
                return None, lossy[0]
            r = [conv(e) for e in row.v]
            if any(e is None for e in r):
                return None, lossy[0]
            rows.append(Value.vec(r))
        return Value.vec(rows), lossy[0]
    vals = [conv(e) for e in nv.v]
    if any(e is None for e in vals):
        return None, lossy[0]
    return Value.vec(vals), lossy[0]

class RecordType:
    def __init__(self, name, fields, invariants=None):
        self.name = name
        self.fields = []
        for f in fields:
            if isinstance(f, dict):
                self.fields.append((f["name"], f["type"]))
            else:
                self.fields.append(tuple(f))
        self.invariants = list(invariants or [])

    def construct(self, args):
        if not isinstance(args, dict):
            args = {}
        names = [fn for fn, _ in self.fields]
        extra = set(args) - set(names)
        if extra:
            return Value.err("UnknownField:" + ",".join(sorted(extra)))
        checked = []
        lossy = {}
        for fname, kind in self.fields:
            if fname not in args:
                return Value.err("MissingField:" + fname)
            raw_in = args[fname]
            raw = _norm_vec(raw_in) if kind == "vec" else _norm_scalar(raw_in)
            if kind == "float":
                if raw.t == ValueType.INT:
                    x = float(raw.v)
                    l = abs(raw.v) > 2**53
                    if l: lossy[fname] = True
                    JOURNAL.append(f"STRUCT {self.name}.{fname} <- int {raw.v} -> {_canon_float(x)}" + (" lossy=TRUE" if l else ""))
                    checked.append((fname, Value.f(x)))
                elif raw.t == ValueType.FLOAT:
                    checked.append((fname, raw))
                else:
                    return Value.err("TypeError:" + fname)
            elif kind == "int":
                if raw.t != ValueType.INT:
                    return Value.err("TypeError:" + fname)
                checked.append((fname, raw))
            elif kind == "vec":
                nv = raw
                if nv.t != ValueType.VEC:
                    return Value.err("TypeError:" + fname)
                wv, l = _widen_vec(nv)
                if wv is None:
                    return Value.err("TypeError:" + fname)
                if l: lossy[fname] = True
                checked.append((fname, wv))
            elif kind.startswith("ref:"):
                target = kind[4:]
                if raw.t != ValueType.STRUCT or raw.v[0] != target:
                    return Value.err("TypeError:" + fname)
                checked.append((fname, raw))
            else:
                return Value.err("TypeError:" + fname)
        for inv in self.invariants:
            fname = inv["field"]
            val = None
            for fn, fv in checked:
                if fn == fname:
                    val = fv
                    break
            if val is None or val.t not in (ValueType.INT, ValueType.FLOAT):
                return Value.err("InvariantViolation:" + fname)
            num = float(val.v)
            if "min" in inv and num < inv["min"]:
                return Value.err("InvariantViolation:" + fname)
            if "max" in inv and num > inv["max"]:
                return Value.err("InvariantViolation:" + fname)
        return Value(ValueType.STRUCT, (self.name, checked, lossy))

class SumType:
    def __init__(self, name, variants):
        # Поля из спеки приходят словарями, при прямой регистрации — кортежами.
        # Нормализатор принимает обе формы (урок двойной нормализации).
        self.name = name
        self.variants = {}
        for var in variants:
            if isinstance(var, dict):
                self.variants[var["name"]] = [(f["name"], f["type"]) for f in var.get("fields", [])]
            else:
                self.variants[var[0]] = [tuple(f) for f in var[1]]

    def construct(self, vname, args):
        if vname not in self.variants:
            return Value.err("UnknownVariant:" + vname)
        sub = RecordType(f"{self.name}.{vname}", self.variants[vname])
        return sub.construct(args)

def struct_eq(a, b):
    # Побитовое равенство по канону: различает -0.0 и 0.0, чего не делает IEEE ==.
    if a.t == ValueType.ERR or b.t == ValueType.ERR:
        return Value.err("PropError")
    if a.t != b.t:
        return Value.b(False)
    return Value.b(canon_val(a) == canon_val(b))

# --- сериализация TRIOREC1 ---------------------------------------------

def _rec_header(fmt, ver, name, fields, lossy_fields):
    return json.dumps({"format": fmt, "version": ver, "type": name,
                       "fields": [list(f) for f in fields], "lossy": list(lossy_fields)},
                      separators=(",", ":"), ensure_ascii=False)

def _lossy_fields(lossy):
    return sorted(k for k, on in lossy.items() if on)

def serialize_record(rec):
    if rec.t != ValueType.STRUCT:
        return Value.err("SerializeError")
    name, fields, lossy = rec.v
    rt = RECORD_REGISTRY.get(name)
    if rt is None:
        return Value.err("UnknownType:" + name)
    if [fn for fn, _ in rt.fields] != [fn for fn, _ in fields]:
        return Value.err("FieldMismatch")
    fmap = dict(fields)
    lines = [_rec_header("TRIOREC1", 1, name, rt.fields, _lossy_fields(lossy))]
    for fname, kind in rt.fields:
        v = fmap[fname]
        if kind == "float":
            if v.t != ValueType.FLOAT: return Value.err("SerializeError")
            lines.append(_canon_float(v.v))
        elif kind == "int":
            if v.t != ValueType.INT: return Value.err("SerializeError")
            lines.append(str(v.v))
        else:
            return Value.err("SerializeError")   # vec и ref — только в TRIOREC2
    return "\n".join(lines)

def load_record(text, registry=None):
    lines = text.split("\n")
    try:
        head = json.loads(lines[0])
    except Exception:
        return Value.err("BadFormat")
    if head.get("format") != "TRIOREC1" or head.get("version") != 1:
        return Value.err("BadFormat")
    name = head.get("type")
    rt = (registry or RECORD_REGISTRY).get(name)
    if rt is None:
        return Value.err("UnknownType:" + name)
    if head.get("fields") != [list(f) for f in rt.fields]:
        return Value.err("FieldMismatch")
    payload = lines[1:]
    if len(payload) != len(rt.fields):
        return Value.err("FieldMismatch")
    lossy_hdr = head.get("lossy", [])
    lossy = {fn: False for fn, _ in rt.fields}
    fields = []
    for (fname, kind), tok in zip(rt.fields, payload):
        if fname in lossy_hdr:
            lossy[fname] = True
        if kind == "float":
            try:
                fields.append((fname, Value.f(_parse_canon_float(tok))))
            except Exception:
                return Value.err("FieldMismatch")
        elif kind == "int":
            try:
                fields.append((fname, Value.i(int(tok))))
            except Exception:
                return Value.err("FieldMismatch")
        else:
            return Value.err("FieldMismatch")
    return Value(ValueType.STRUCT, (name, fields, {k: v for k, v in lossy.items() if v}))

# --- сериализация TRIOREC2: вложенные рекорды, ref, vec ----------------

def _vec_field_payload(v):
    # returns (shape_str, [канонические токены]) или None
    rows = v.v
    if rows and isinstance(rows[0], Value) and rows[0].t == ValueType.VEC:
        r = len(rows)
        c = len(rows[0].v)
        for row in rows:
            if row.t != ValueType.VEC or len(row.v) != c:
                return None
            for e in row.v:
                if e.t != ValueType.FLOAT:
                    return None
        toks = [_canon_float(e.v) for row in rows for e in row.v]
        return f"[{r},{c}]", toks
    for e in rows:
        if e.t != ValueType.FLOAT:
            return None
    return f"[{len(rows)}]", [_canon_float(e.v) for e in rows]

def serialize_record2(rec, depth=0):
    if depth > MAX_DEPTH:
        return Value.err("CycleDetected")
    if rec.t != ValueType.STRUCT:
        return Value.err("SerializeError")
    name, fields, lossy = rec.v
    rt = RECORD_REGISTRY.get(name)
    if rt is None:
        return Value.err("UnknownType:" + name)
    if [fn for fn, _ in rt.fields] != [fn for fn, _ in fields]:
        return Value.err("FieldMismatch")
    fmap = dict(fields)
    lossy_paths = list(_lossy_fields(lossy))
    blocks = []
    for fname, kind in rt.fields:
        v = fmap[fname]
        if kind == "vec":
            sh = _vec_field_payload(v)
            if sh is None:
                return Value.err("SerializeError")
            shape, toks = sh
            blocks.append(["@vec " + fname + " " + shape] + toks)
        elif kind.startswith("ref:"):
            target = kind[4:]
            if v.t != ValueType.STRUCT or v.v[0] != target:
                return Value.err("TypeError:" + fname)
            inner = serialize_record2(v, depth + 1)
            if isinstance(inner, Value):
                return inner   # ошибка вложенной сериализации — как значение
            sub_head = json.loads(inner.split("\n", 1)[0])
            for lf in sub_head.get("lossy", []):
                lossy_paths.append(fname + "." + lf)
            blocks.append(["@begin " + fname + ":" + target] + inner.split("\n") + ["@end " + fname])
        elif kind == "float":
            if v.t != ValueType.FLOAT: return Value.err("SerializeError")
            blocks.append([_canon_float(v.v)])
        elif kind == "int":
            if v.t != ValueType.INT: return Value.err("SerializeError")
            blocks.append([str(v.v)])
        else:
            return Value.err("SerializeError")
    lines = [_rec_header("TRIOREC2", 2, name, rt.fields, lossy_paths)]
    for bl in blocks:
        lines.extend(bl)
    return "\n".join(lines)

def load_record2(text, registry=None, depth=0):
    if depth > MAX_DEPTH:
        return Value.err("CycleDetected")
    lines = text.split("\n")
    try:
        head = json.loads(lines[0])
    except Exception:
        return Value.err("BadFormat")
    if head.get("format") != "TRIOREC2" or head.get("version") != 2:
        return Value.err("BadFormat")
    name = head.get("type")
    rt = (registry or RECORD_REGISTRY).get(name)
    if rt is None or not isinstance(rt, RecordType):
        return Value.err("UnknownType:" + str(name))
    if head.get("fields") != [list(f) for f in rt.fields]:
        return Value.err("FieldMismatch")
    lossy_hdr = head.get("lossy", [])
    lossy = {fn: False for fn, _ in rt.fields}
    fields = []
    i = 1
    for fname, kind in rt.fields:
        if fname in lossy_hdr:
            lossy[fname] = True
        if kind == "vec":
            m = re.match(r"@vec (\S+) (\[\d+(?:,\d+)*\])$", lines[i]) if i < len(lines) else None
            if not m:
                return Value.err("FieldMismatch")
            shape = [int(d) for d in m.group(2).strip("[]").split(",")]
            i += 1
            n = 1
            for d in shape:
                n *= d
            toks = lines[i:i + n]
            if len(toks) != n:
                return Value.err("FieldMismatch")
            i += n
            try:
                nums = [_parse_canon_float(t) for t in toks]
            except Exception:
                return Value.err("FieldMismatch")
            if len(shape) == 1:
                fv = Value.vec([Value.f(x) for x in nums])
            else:
                r, c = shape
                fv = Value.vec([Value.vec([Value.f(nums[a * c + b]) for b in range(c)]) for a in range(r)])
            fields.append((fname, fv))
        elif kind.startswith("ref:"):
            if i >= len(lines) or not lines[i].startswith("@begin "):
                return Value.err("FieldMismatch")
            tag = lines[i][7:]
            bname, _, btype = tag.partition(":")
            if bname != fname:
                return Value.err("FieldMismatch")
            if btype != kind[4:]:
                return Value.err("UnknownType:" + btype)
            # вложенные блоки: подсчёт глубины, а не первый встретившийся @end
            depth2 = 1
            j = i + 1
            while j < len(lines):
                if lines[j].startswith("@begin "):
                    depth2 += 1
                elif lines[j].startswith("@end "):
                    depth2 -= 1
                    if depth2 == 0:
                        break
                j += 1
            if depth2 != 0:
                return Value.err("BadFormat")
            sub = load_record2("\n".join(lines[i + 1:j]), registry, depth + 1)
            if sub.t != ValueType.STRUCT:
                return sub
            if sub.v[0] != kind[4:]:
                return Value.err("FieldMismatch")
            fields.append((fname, sub))
            i = j + 1
        elif kind == "float":
            if i >= len(lines): return Value.err("FieldMismatch")
            try:
                fields.append((fname, Value.f(_parse_canon_float(lines[i]))))
            except Exception:
                return Value.err("FieldMismatch")
            i += 1
        elif kind == "int":
            if i >= len(lines): return Value.err("FieldMismatch")
            try:
                fields.append((fname, Value.i(int(lines[i]))))
            except Exception:
                return Value.err("FieldMismatch")
            i += 1
        else:
            return Value.err("FieldMismatch")
    return Value(ValueType.STRUCT, (name, fields, {k: v for k, v in lossy.items() if v}))

# --- кодогенератор TRIOMODEL1 ------------------------------------------

def registry_fingerprint():
    parts = []
    for name, t in RECORD_REGISTRY.items():
        if isinstance(t, RecordType):
            parts.append(t.name + "(" + ".".join(f"{fn}:{k}" for fn, k in t.fields) + ")")
        elif isinstance(t, SumType):
            vs = "|".join(vn + "(" + ".".join(f"{fn}:{k}" for fn, k in fs) + ")"
                          for vn, fs in t.variants.items())
            parts.append(t.name + "[" + vs + "]")
    return ";".join(parts)

def generate_model(spec):
    if not isinstance(spec, dict) or spec.get("format") != "TRIOMODEL1":
        return Value.err("SpecError")
    made = []
    for t in spec.get("types", []):
        kind = t.get("kind")
        if kind == "record":
            rt = RecordType(t["name"], t["fields"], t.get("invariants"))
            register_type(rt)
            made.append(rt)
        elif kind == "sum":
            st = SumType(t["name"], t["variants"])
            register_type(st)
            made.append(st)
        else:
            return Value.err("SpecError")
    return ";".join(
        (m.name + "(" + ".".join(f"{fn}:{k}" for fn, k in m.fields) + ")") if isinstance(m, RecordType)
        else (m.name + "[" + "|".join(vn + "(" + ".".join(f"{fn}:{k}" for fn, k in fs) + ")"
                                      for vn, fs in m.variants.items()) + "]")
        for m in made)

# --- Trio Bridge -------------------------------------------------------

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
    if v.t in (ValueType.INT, ValueType.FLOAT) and dtype == "Float64":
        if v.t == ValueType.INT:
            lossy = abs(v.v) > 2**53
            x = float(v.v)
        else:
            lossy, x = False, float(v.v)
        JOURNAL.append(f"IN {name}[] = {_canon_float(x)}" + (" lossy=TRUE" if lossy else ""))
        return {"dtype": dtype, "shape": [], "values": [x], "lossy": lossy}
    if v.t == ValueType.INT and dtype == "Int64":
        JOURNAL.append(f"IN {name}[] = {int(v.v)}")
        return {"dtype": dtype, "shape": [], "values": [int(v.v)], "lossy": False}
    if v.t == ValueType.VEC:
        def fl(x):
            return float(x.v) if isinstance(x, Value) else float(x)
        if v.v and ((isinstance(v.v[0], list)) or (isinstance(v.v[0], Value) and v.v[0].t == ValueType.VEC)):
            rows = []
            for row in v.v:
                rr = row.v if isinstance(row, Value) else row
                rows.append([fl(x) for x in rr])
            r, c = len(rows), len(rows[0])
            vals = [x for row in rows for x in row]
            JOURNAL.append(f"IN {name} [{r},{c}] = " + " ".join(_canon_float(x) for x in vals))
            return {"dtype": "Float64", "shape": [r, c], "values": vals, "lossy": False}
        vals = [fl(x) for x in v.v]
        JOURNAL.append(f"IN {name} [{len(vals)}] = " + " ".join(_canon_float(x) for x in vals))
        return {"dtype": "Float64", "shape": [len(vals)], "values": vals, "lossy": False}
    raise NodeError("TypeError", f'input "{name}": unsupported SoundValue/type combo')

def from_triomat_value(payload):
    shape, values = payload["shape"], payload["values"]
    if shape == []:
        return Value.f(values[0])
    if len(shape) == 1:
        return Value.vec(values)
    r, c = shape
    return Value.vec([values[i * c:(i + 1) * c] for i in range(r)])

def octave_backend_emulated(spec, files, workdir="."):
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
    # OPEN-гейт: требует установленный Octave. План: TRIOMAT1 <-> subprocess.
    raise NodeError("ProcessError", "real octave backend not wired yet (OPEN gate)")

def run_node(spec, inputs, backend, workdir="."):
    files = {}
    for io in spec["inputs"]:
        name = io["name"]
        if name not in inputs:
            return None, ("ShapeError", f'missing input "{name}"')
        try:
            files[name] = to_triomat_value(inputs[name], io.get("dtype", "Float64"), name)
        except NodeError as e:
            return None, (e.code, e.message)
    try:
        results = backend(spec, files, workdir)
    except NodeError as e:
        return None, (e.code, e.message)
    outputs = {}
    for io in spec["outputs"]:
        name = io["name"]
        if name not in results:
            return None, ("ProcessError", f'backend did not produce "{name}"')
        payload = results[name]
        if payload["dtype"] != io.get("dtype", "Float64"):
            return None, ("TypeError", f'output "{name}": dtype={payload["dtype"]}, expected {io["dtype"]}')
        outs = from_triomat_value(payload)
        flat = ([x for row in outs.v for x in row] if outs.v and isinstance(outs.v[0], list)
                else outs.v if isinstance(outs.v, list) else [outs.v])
        JOURNAL.extend(f"OUT {name}[{k}] = {_canon_float(x)}" for k, x in enumerate(flat))
        outputs[name] = outs
    return outputs, None

def eval_node_call(name, args, backend=None):
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

# --- TRIOBOOK1: единый артефакт ----------------------------------------

SECTIONS = ["program", "models", "nodes", "journal", "golden"]

def make_book(program_terms, models_spec, nodes_spec, journal_lines, golden_lines):
    return Value.struct("TRIOBOOK", [
        ("program", Value.vec(list(program_terms))),
        ("models", Value.s(models_spec)),
        ("nodes", Value.s(nodes_spec)),
        ("journal", Value.vec([Value.s(l) for l in journal_lines])),
        ("golden", Value.vec([Value.s(l) for l in golden_lines])),
    ])

def serialize_book(book):
    if book.t != ValueType.STRUCT or book.v[0] != "TRIOBOOK":
        return Value.err("SerializeError")
    if [f[0] for f in book.v[1]] != SECTIONS:
        return Value.err("FieldMismatch")
    fmap = dict(book.v[1])
    counts = {}
    payload = {}
    for sec in SECTIONS:
        v = fmap[sec]
        if sec == "program":
            if v.t != ValueType.VEC: return Value.err("FieldMismatch")
            lines = [canon_val(t) for t in v.v]
        elif sec in ("models", "nodes"):
            if v.t != ValueType.STR: return Value.err("FieldMismatch")
            lines = v.v.split("\n")
        else:
            if v.t != ValueType.VEC: return Value.err("FieldMismatch")
            lines = [canon_val(e) for e in v.v]
        counts[sec] = len(lines)
        payload[sec] = lines
    head = json.dumps({"format": "TRIOBOOK1", "version": 1, "sections": SECTIONS,
                       "counts": counts}, separators=(",", ":"), ensure_ascii=False)
    out = [head]
    for sec in SECTIONS:
        out.append(f"@begin {sec}")
        out.extend(payload[sec])
        out.append(f"@end {sec}")
    return "\n".join(out)

def _parse_term(s, pos=0):
    while pos < len(s) and s[pos] in " \t":
        pos += 1
    if pos >= len(s):
        return None, pos
    c = s[pos]
    if c == "{":
        end = pos + 1
        while end < len(s) and s[end] not in " }":
            end += 1
        tag = s[pos + 1:end]
        pos = end
        fields = []
        while True:
            while pos < len(s) and s[pos] in " \t":
                pos += 1
            if pos >= len(s):
                return None, pos
            if s[pos] == "}":
                pos += 1
                break
            eq = s.find("=", pos)
            if eq < 0:
                return None, pos
            key = s[pos:eq]
            val, pos = _parse_term(s, eq + 1)
            if val is None:
                return None, pos
            fields.append((key, val))
        return Value.struct(tag, fields), pos
    if c == '"':
        j = pos + 1
        while j < len(s):
            if s[j] == "\\":
                j += 2
                continue
            if s[j] == '"':
                break
            j += 1
        if j >= len(s):
            return None, pos
        try:
            text = json.loads(s[pos:j + 1])
        except Exception:
            return None, pos
        return Value.s(text), j + 1
    if c == "[":
        pos += 1
        elems = []
        while True:
            while pos < len(s) and s[pos] in " \t":
                pos += 1
            if pos >= len(s):
                return None, pos
            if s[pos] == "]":
                pos += 1
                break
            if s[pos] == ",":
                pos += 1
                continue
            val, pos = _parse_term(s, pos)
            if val is None:
                return None, pos
            elems.append(val)
        return Value.vec(elems), pos
    m = re.match(r"-?\d+", s[pos:])
    if m:
        return Value.i(int(m.group(0))), pos + m.end()
    return None, pos

def load_book(text):
    lines = text.split("\n")
    try:
        head = json.loads(lines[0])
    except Exception:
        return Value.err("BadFormat")
    if head.get("format") != "TRIOBOOK1" or head.get("version") != 1:
        return Value.err("BadFormat")
    if head.get("sections") != SECTIONS:
        return Value.err("BadFormat")
    sections = {}
    order = []
    cur = None
    buf = []
    for ln in lines[1:]:
        if ln.startswith("@begin "):
            if cur is not None:
                return Value.err("BadFormat")
            cur = ln[7:].strip()
            buf = []
        elif ln.startswith("@end "):
            if ln[5:].strip() != cur:
                return Value.err("BadFormat")
            sections[cur] = buf
            order.append(cur)
            cur = None
        else:
            if cur is None:
                return Value.err("BadFormat")
            buf.append(ln)
    if order != SECTIONS:
        return Value.err("BadFormat")
    counts = head.get("counts", {})
    for sec in SECTIONS:
        if counts.get(sec) != len(sections[sec]):
            return Value.err("BadFormat")
    prog = []
    for l in sections["program"]:
        t, _ = _parse_term(l)
        if t is None:
            return Value.err("BadFormat")
        prog.append(t)
    def str_list(sec):
        out = []
        for l in sections[sec]:
            t, _ = _parse_term(l)
            if t is None or t.t != ValueType.STR:
                return None
            out.append(t)
        return out
    jr = str_list("journal")
    gl = str_list("golden")
    if jr is None or gl is None:
        return Value.err("BadFormat")
    return Value.struct("TRIOBOOK", [
        ("program", Value.vec(prog)),
        ("models", Value.s("\n".join(sections["models"]))),
        ("nodes", Value.s("\n".join(sections["nodes"]))),
        ("journal", Value.vec(jr)),
        ("golden", Value.vec(gl)),
    ])

# --- батарея: пин pi + T06..T19 ----------------------------------------

def run_battery():
    passed = 0
    total = 89

    # Пин pi: константа зафиксирована битами, не рантаймом
    if _PI == math.pi:
        passed += 1

    # T06: лексический захват (FIX-1)
    def mk_f(env_snap):
        def fn(clo_env, y):
            return add(clo_env["x1"], y)
        return Value.clo(fn, env_snap)
    env1 = {"x1": Value.i(105), "f": mk_f({"x1": Value.i(1)})}
    if apply_closure(env1["f"], Value.i(5)).canon() == "6":
        passed += 1

    # T07: reduce с шагами
    def step(acc, x):
        return add(acc, x)
    r = reduce_vec(Value.vec([1.0, 2.0, 3.0, 4.0]), Value.i(0), step)
    if r.canon() == "0x1.4000000000000p+3":
        passed += 1

    # T11: narrow с ошибкой (FIX-2)
    if narrow(Value.f(3.5)).canon() == "Err(PrecisionLoss)":
        passed += 1

    # T12: R-INT1 ties-to-even на границе 2^53
    cases = ((2**53,     "0x1.0000000000000p+53", False),
             (2**53 + 2, "0x1.0000000000001p+53", True),
             (2**53 + 3, "0x1.0000000000002p+53", True))
    ok = True
    for x, want, want_lossy in cases:
        JOURNAL.clear()
        w = widen(Value.i(x))
        entry = next((e for e in JOURNAL if e.startswith("widen")), "")
        if w.t != ValueType.FLOAT or _canon_float(w.v) != want or ("lossy=TRUE" in entry) != want_lossy:
            ok = False
    if ok:
        passed += 1

    # T13: мост узлов
    if "mat_mul_scalar_octave" not in NODE_SPECS:
        NODE_SPECS["mat_mul_scalar_octave"] = {
            "name": "mat_mul_scalar_octave",
            "backend": "octave",
            "inputs": [
                {"name": "A", "type": "matrix", "dtype": "Float64"},
                {"name": "k", "type": "scalar", "dtype": "Float64"},
            ],
            "outputs": [{"name": "B", "type": "matrix", "dtype": "Float64"}],
        }
    ok = True
    JOURNAL.clear()
    r = eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.f(2.0)])
    ok = ok and r.t == ValueType.VEC and r.v == [[2.0, 4.0], [6.0, 8.0]]
    ok = ok and "OUT B[3] = 0x1.0000000000000p+3" in JOURNAL
    JOURNAL.clear()
    r2 = eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.vec([1.0])])
    ok = ok and r2.t == ValueType.ERR and r2.v == "ShapeError"
    ok = ok and any(e.startswith("IN A [2,2]") for e in JOURNAL)
    JOURNAL.clear()
    eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0]]), Value.i(2**53 + 1)])
    ok = ok and any(e.startswith("IN k[] =") and "lossy=TRUE" in e for e in JOURNAL)
    if ok:
        passed += 1

    # T14: STRUCT — рекорды, сум-типы, побитовое равенство
    PT = RecordType("Point", [("x", "float"), ("y", "float")])
    register_type(PT)
    SHAPE = SumType("Shape", [("Circle", [("r", "float")]), ("Rect", [("w", "float"), ("h", "float")])])
    def match_area(v):
        if v.t == ValueType.STRUCT:
            fields = dict(v.v[1])
            if v.v[0] == "Shape.Circle":
                return Value.f(_PI * fields["r"].v * fields["r"].v)
            if v.v[0] == "Shape.Rect":
                return Value.f(fields["w"].v * fields["h"].v)
        return Value.err("NoMatch")
    def t14_run():
        f = []
        p1 = PT.construct({"x": 1.5, "y": 2.0})
        p2 = PT.construct({"x": 1.5, "y": 2.0})
        f.append(p1.t == ValueType.STRUCT)
        f.append(canon_val(p1) == "{Point x=0x1.8000000000000p+0 y=0x1.0000000000000p+1}")
        f.append(struct_eq(p1, p2).v is True)
        pn = PT.construct({"x": -0.0, "y": 1.0})
        pp = PT.construct({"x": 0.0, "y": 1.0})
        f.append(struct_eq(pn, pp).v is False)
        f.append(PT.construct({"x": 1.0, "y": 2.0, "z": 3.0}).canon() == "Err(UnknownField:z)")
        f.append(PT.construct({"x": 1.0}).canon() == "Err(MissingField:y)")
        f.append(PT.construct({"x": Value.s("a"), "y": 2}).canon() == "Err(TypeError:x)")
        JOURNAL.clear()
        pb = PT.construct({"x": 2**53 + 1, "y": 1.0})
        f.append(pb.t == ValueType.STRUCT and pb.v[2].get("x") is True)
        f.append(any(e.startswith("STRUCT Point.x") and "lossy=TRUE" in e for e in JOURNAL))
        c = SHAPE.construct("Circle", {"r": 2})
        rc = SHAPE.construct("Rect", {"w": 2, "h": 3})
        f.append(c.t == ValueType.STRUCT and match_area(c).canon() == "0x1.921fb54442d18p+3")
        f.append(rc.t == ValueType.STRUCT and match_area(rc).canon() == "0x1.8000000000000p+2")
        f.append(SHAPE.construct("Triangle", {"r": 1}).canon() == "Err(UnknownVariant:Triangle)")
        run1 = [canon_val(x) for x in (p1, pn, c, rc)]
        p3 = PT.construct({"x": 1.5, "y": 2.0})
        run2 = [canon_val(x) for x in (p3, PT.construct({"x": -0.0, "y": 1.0}),
                                       SHAPE.construct("Circle", {"r": 2}),
                                       SHAPE.construct("Rect", {"w": 2, "h": 3}))]
        f.append(run1 == run2)
        return all(f)
    if t14_run():
        passed += 1

    # T15: TRIOREC1
    def t15_run():
        f = []
        p = PT.construct({"x": 1.5, "y": 2.0})
        txt = serialize_record(p)
        if isinstance(txt, Value):
            return False
        f.append(serialize_record(p) == txt)
        loaded = load_record(txt)
        f.append(loaded.t == ValueType.STRUCT and struct_eq(loaded, p).v is True)
        pn = PT.construct({"x": -0.0, "y": 1.0})
        t_n = serialize_record(pn)
        if isinstance(t_n, Value):
            return False
        f.append("-0.0" in t_n)
        ln = load_record(t_n)
        f.append(ln.t == ValueType.STRUCT and struct_eq(ln, pn).v is True
                 and struct_eq(ln, PT.construct({"x": 0.0, "y": 1.0})).v is False)
        JOURNAL.clear()
        pl = PT.construct({"x": 2**53 + 3, "y": 1.0})
        f.append(pl.v[2].get("x") is True)
        t_l = serialize_record(pl)
        if isinstance(t_l, Value):
            return False
        f.append('"lossy":["x"]' in t_l)
        ll = load_record(t_l)
        f.append(ll.t == ValueType.STRUCT and ll.v[2].get("x") is True and struct_eq(ll, pl).v is True)
        bad = json.dumps({"format": "TRIOREC1", "version": 1, "type": "Triangle",
                          "fields": [], "lossy": []}, separators=(",", ":"))
        f.append(load_record(bad).canon() == "Err(UnknownType:Triangle)")
        f.append(serialize_record(Value.err("X")).canon() == "Err(SerializeError)")
        mm = json.dumps({"format": "TRIOREC1", "version": 1, "type": "Point",
                         "fields": [["x", "float"]], "lossy": []}, separators=(",", ":")) + "\n0x1.0000000000000p+0"
        f.append(load_record(mm).canon() == "Err(FieldMismatch)")
        return all(f)
    if t15_run():
        passed += 1

    # T16: кодогенератор TRIOMODEL1
    def t16_run():
        f = []
        spec = {"format": "TRIOMODEL1", "types": [
            {"kind": "record", "name": "Dolphin",
             "fields": [{"name": "id", "type": "int"}, {"name": "score", "type": "float"}],
             "invariants": [{"field": "score", "min": 0.0, "max": 100.0}]},
            {"kind": "record", "name": "Pod", "fields": [{"name": "capacity", "type": "float"}]},
            {"kind": "sum", "name": "Shape2",
             "variants": [{"name": "Circle", "fields": [{"name": "r", "type": "float"}]},
                          {"name": "Rect", "fields": [{"name": "w", "type": "float"}, {"name": "h", "type": "float"}]}]},
        ]}
        fp1 = generate_model(spec)
        fp2 = generate_model(spec)
        if isinstance(fp1, Value) or isinstance(fp2, Value):
            return False
        f.append(fp1 == fp2)
        f.append("Dolphin(id:int.score:float)" in fp1)
        f.append("Pod(capacity:float)" in fp1)
        f.append("Shape2[Circle(r:float)|Rect(w:float.h:float)]" in fp1)
        DT = RECORD_REGISTRY["Dolphin"]
        d = DT.construct({"id": 7, "score": 0.98})
        f.append(canon_val(d) == "{Dolphin id=7 score=0x1.f5c28f5c28f5cp-1}")
        f.append(DT.construct({"id": 7, "score": 150}).canon() == "Err(InvariantViolation:score)")
        f.append(DT.construct({"id": 7, "score": 100.0}).t == ValueType.STRUCT)
        JOURNAL.clear()
        POD = RECORD_REGISTRY["Pod"]
        pod = POD.construct({"capacity": 2**53 + 3})
        f.append(pod.v[2].get("capacity") is True)
        f.append(any(e.startswith("STRUCT Pod.capacity") and "lossy=TRUE" in e for e in JOURNAL))
        f.append(DT.construct({"id": 7}).canon() == "Err(MissingField:score)")
        f.append(DT.construct({"id": 7, "score": 1.0, "extra": 1}).canon() == "Err(UnknownField:extra)")
        f.append(DT.construct({"id": Value.s("x"), "score": 1.0}).canon() == "Err(TypeError:id)")
        S2 = RECORD_REGISTRY["Shape2"]
        c = S2.construct("Circle", {"r": 2})
        f.append(c.t == ValueType.STRUCT)
        f.append(S2.construct("Triangle", {"r": 1}).canon() == "Err(UnknownVariant:Triangle)")
        t = serialize_record(d)
        if isinstance(t, Value):
            return False
        ld = load_record(t)
        f.append(ld.t == ValueType.STRUCT and struct_eq(ld, d).v is True)
        tp = serialize_record(pod)
        if isinstance(tp, Value):
            return False
        f.append('"lossy":["capacity"]' in tp)
        lp = load_record(tp)
        f.append(lp.v[2].get("capacity") is True and struct_eq(lp, pod).v is True)
        f.append(generate_model({"format": "TRIOMODEL1", "types": [{"kind": "weird", "name": "X"}]}).canon() == "Err(SpecError)")
        return all(f)
    if t16_run():
        passed += 1

    # T17: TRIOREC2 — вложенные рекорды, ref, страж глубины
    D2 = RecordType("Dolphin2", [("id", "int"), ("score", "float"), ("pod", "ref:Pod2")])
    P2 = RecordType("Pod2", [("capacity", "float")])
    register_type(D2); register_type(P2)
    def t17_run():
        f = []
        pod = P2.construct({"capacity": 20.0})
        dol = D2.construct({"id": 7, "score": 0.98, "pod": pod})
        t = serialize_record2(dol)
        if isinstance(t, Value):
            return False
        f.append("@begin pod:Pod2" in t)
        f.append('"format":"TRIOREC2","version":2,"type":"Pod2"' in t)
        f.append(serialize_record2(dol) == t)
        ld = load_record2(t)
        f.append(ld.t == ValueType.STRUCT and struct_eq(ld, dol).v is True)
        JOURNAL.clear()
        pod_l = P2.construct({"capacity": 2**53 + 3})
        dol_l = D2.construct({"id": 7, "score": 0.98, "pod": pod_l})
        t2 = serialize_record2(dol_l)
        if isinstance(t2, Value):
            return False
        f.append('"lossy":["pod.capacity"]' in t2)
        f.append('"lossy":["capacity"]' in t2)
        ll = load_record2(t2)
        f.append(ll.t == ValueType.STRUCT and struct_eq(ll, dol_l).v is True)
        bad = Value.struct("Dolphin2", [("id", Value.i(7)), ("score", Value.f(0.98)),
                                        ("pod", PT.construct({"x": 1.0, "y": 2.0}))])
        f.append(serialize_record2(bad).canon() == "Err(TypeError:pod)")
        t3 = serialize_record2(dol)
        if isinstance(t3, Value):
            return False
        f.append(load_record2(t3.replace('"type":"Pod2"', '"type":"Ghost"')).canon() == "Err(UnknownType:Ghost)")
        f.append(serialize_record(dol).canon() == "Err(SerializeError)")
        CH = RecordType("Chain", [("next", "ref:Chain")])
        register_type(CH)
        chain_text = _rec_header("TRIOREC2", 2, "Chain", CH.fields, [])
        for _ in range(70):
            chain_text = _rec_header("TRIOREC2", 2, "Chain", CH.fields, []) + "\n@begin next:Chain\n" + chain_text + "\n@end next"
        f.append(load_record2(chain_text).canon() == "Err(CycleDetected)")
        return all(f)
    if t17_run():
        passed += 1

    # T18: vec-поля в TRIOREC2
    P3 = RecordType("Pod3", [("observations", "vec")])
    MAT = RecordType("Mat", [("m", "vec")])
    XS = RecordType("Xs", [("xs", "vec")])
    register_type(P3); register_type(MAT); register_type(XS)
    def t18_run():
        f = []
        p3 = P3.construct({"observations": [1.0, 2.0, 3.0]})
        t = serialize_record2(p3)
        if isinstance(t, Value):
            return False
        f.append("@vec observations [3]" in t)
        f.append(serialize_record2(p3) == t)
        ld = load_record2(t)
        f.append(ld.t == ValueType.STRUCT and struct_eq(ld, p3).v is True)
        m = MAT.construct({"m": [[1.0, 2.0], [3.0, 4.0]]})
        tm = serialize_record2(m)
        if isinstance(tm, Value):
            return False
        f.append("@vec m [2,2]" in tm)
        lm = load_record2(tm)
        f.append(lm.t == ValueType.STRUCT and struct_eq(lm, m).v is True)
        JOURNAL.clear()
        pv = P3.construct({"observations": [1.0, 2**53 + 3]})
        f.append(pv.v[2].get("observations") is True)
        f.append(any(e.startswith("STRUCT vec elem") and "lossy=TRUE" in e for e in JOURNAL))
        tv = serialize_record2(pv)
        if isinstance(tv, Value):
            return False
        f.append('"lossy":["observations"]' in tv)
        lv = load_record2(tv)
        f.append(lv.v[2].get("observations") is True and struct_eq(lv, pv).v is True)
        xs = XS.construct({"xs": []})
        tx = serialize_record2(xs)
        if isinstance(tx, Value):
            return False
        f.append("@vec xs [0]" in tx)
        lx = load_record2(tx)
        f.append(lx.t == ValueType.STRUCT and struct_eq(lx, xs).v is True)
        t_mm = serialize_record2(m)
        if isinstance(t_mm, Value):
            return False
        f.append(load_record2("\n".join(t_mm.split("\n")[:-1])).canon() == "Err(FieldMismatch)")
        f.append(serialize_record(m).canon() == "Err(SerializeError)")
        return all(f)
    if t18_run():
        passed += 1

    # T19: TRIOBOOK1 — единый артефакт
    def t19_run():
        f = []
        t1 = Value.struct("call_node", [("name", Value.s("mat_mul_scalar_octave")), ("args", Value.vec([Value.s("A"), Value.s("k")]))])
        t2 = Value.struct("call_node", [("name", Value.s("other_node")), ("args", Value.vec([Value.s("A"), Value.s("k")]))])
        f.append(struct_eq(t1, t2).v is False)
        f.append(struct_eq(t1, t1).v is True)
        prog = [Value.struct("let", [
            ("name", Value.s("B")),
            ("body", t1),
            ("next", Value.struct("var", [("name", Value.s("B"))]))])]
        JOURNAL.clear()
        res = eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.f(2.0)])
        if res.t == ValueType.ERR:
            return False
        journal_lines = list(JOURNAL)
        golden_lines = [l for l in journal_lines if l.startswith("OUT ")]
        models_spec = json.dumps({"format": "TRIOMODEL1", "types": [{"kind": "record", "name": "Point",
            "fields": [{"name": "x", "type": "float"}, {"name": "y", "type": "float"}]}]},
            separators=(",", ":"))
        nodes_spec = json.dumps({"nodes": [NODE_SPECS["mat_mul_scalar_octave"]]}, separators=(",", ":"))
        book1 = make_book(prog, models_spec, nodes_spec, journal_lines, golden_lines)
        b1 = serialize_book(book1)
        if isinstance(b1, Value):
            return False
        book2 = make_book(prog, models_spec, nodes_spec, journal_lines, golden_lines)
        f.append(serialize_book(book2) == b1)
        lb = load_book(b1)
        f.append(lb.t == ValueType.STRUCT and struct_eq(lb, book1).v is True)
        lb2 = load_book(serialize_book(lb))
        f.append(lb2.t == ValueType.STRUCT and struct_eq(lb2, book1).v is True)
        f.append('"counts"' in b1.split("\n")[0])
        f.append(load_book(b1.replace('"counts"', '"count"')).canon() == "Err(BadFormat)")
        return all(f)
    if t19_run():
        passed += 1

    print(f"Battery: {passed}/{total}")
    return passed == total

if __name__ == "__main__":
    ok = run_battery()
    print("OK" if ok else "FAIL")
