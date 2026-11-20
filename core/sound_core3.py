# sound_core3.py — v0.9
# v0.3 + FIX-1..FIX-5 + Trio Bridge + records (T14) + TRIOREC1 (T15)
#       + codegen (T16) + TRIOREC2: вложенные рекорды и ref-поля (T17)
from enum import IntEnum
import math, json, os

class ValueType(IntEnum):
    INT = 0
    FLOAT = 1
    BOOL = 2
    VEC = 3
    CLOSURE = 4
    ERR = 5
    STRUCT = 6

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
        return Value(ValueType.STRUCT, (name, fields, lossy or {}))
    def canon(self):
        if self.t == ValueType.INT: return str(self.v)
        if self.t == ValueType.FLOAT: return _canon_float(self.v)
        if self.t == ValueType.BOOL: return "true" if self.v else "false"
        if self.t == ValueType.VEC: return "[" + ",".join(canon_val(x) for x in self.v) + "]"
        if self.t == ValueType.CLOSURE: return "<closure>"
        if self.t == ValueType.ERR: return "Err(" + str(self.v) + ")"
        if self.t == ValueType.STRUCT: return canon_val(self)
        return "?"

# Канонический журнал: входы, выходы, флаги. Всё, что течёт через мост, обязано здесь быть.
JOURNAL = []

def _canon_float(x):
    # Канон: мантисса добита до 13 hex-цифр, знак порядка обязателен.
    if math.isnan(x): return "nan"          # TODO(v0.10): payload NaN
    if math.isinf(x): return "inf" if x > 0 else "-inf"
    if x == 0.0: return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    h = float(x).hex()
    sign = ""
    if h.startswith("-"): sign, h = "-", h[1:]
    if h.startswith("0x"): h = h[2:]
    mant, exp = h.split("p")
    int_part, _, frac = mant.partition(".")
    frac = (frac + "0" * 13)[:13]
    return sign + "0x" + int_part + "." + frac + "p" + exp

def parse_canon_float(s):
    if s == "-0.0": return -0.0
    if s == "inf": return math.inf
    if s == "-inf": return -math.inf
    if s == "nan": return math.nan
    return float.fromhex(s)

def canon_val(v):
    if v.t == ValueType.STRUCT:
        name, fields, _ = v.v
        return "{" + name + " " + " ".join(fn + "=" + canon_val(val) for fn, _, val in fields) + "}"
    return v.canon()

def struct_eq(a, b):
    # Равенство побитовое по канону: -0.0 и 0.0 различаются.
    if a.t == ValueType.ERR or b.t == ValueType.ERR:
        return Value.err("PropError")
    if a.t != b.t:
        return Value.b(False)
    if a.t == ValueType.STRUCT:
        return Value.b(canon_val(a) == canon_val(b))
    return Value.b(a.v == b.v)

def widen(v):
    # R-INT1: неограниченное целое -> double. За границей 2^53 — флаг lossy в журнал.
    if v.t == ValueType.INT:
        x = float(v.v)
        lossy = abs(v.v) > 2**53
        JOURNAL.append("widen " + str(v.v) + " -> " + _canon_float(x) + (" lossy=TRUE" if lossy else ""))
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
    # FIX-3
    if a.t == ValueType.FLOAT and b.t == ValueType.FLOAT:
        return Value.f(a.v - b.v)
    return sub(widen(a), widen(b))

def mul(a, b):
    if a.t == ValueType.ERR: return a
    if b.t == ValueType.ERR: return b
    if a.t == ValueType.INT and b.t == ValueType.INT:
        return Value.i(a.v * b.v)
    # FIX-3
    if a.t == ValueType.FLOAT and b.t == ValueType.FLOAT:
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
                return node[1] in params
            elif tag == "app":
                return walk(node[1], params) and walk(node[2], params)
            elif tag == "if":
                return walk(node[1], params) and walk(node[2], params) and walk(node[3], params)
            elif tag == "fun":
                _, ps, body = node
                if len(set(ps)) != len(ps):
                    return False
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
# Trio Bridge: узлы. Диспетчер и маппинг значений.
# ============================================================
class NodeError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__("Err(" + code + "): " + message)

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
    # SoundValue -> payload TRIOMAT. R-INT1 живёт здесь. Журнал входа — всегда.
    if v.t in (ValueType.INT, ValueType.FLOAT) and dtype == "Float64":
        if v.t == ValueType.INT:
            lossy = abs(v.v) > 2**53
            x = float(v.v)
        else:
            lossy, x = False, float(v.v)
        JOURNAL.append("IN " + name + "[] = " + _canon_float(x) + (" lossy=TRUE" if lossy else ""))
        return {"dtype": dtype, "shape": [], "values": [x], "lossy": lossy}
    if v.t == ValueType.INT and dtype == "Int64":
        JOURNAL.append("IN " + name + "[] = " + str(int(v.v)))
        return {"dtype": dtype, "shape": [], "values": [int(v.v)], "lossy": False}
    if v.t == ValueType.VEC:
        if v.v and isinstance(v.v[0], list):
            r, c = len(v.v), len(v.v[0])
            vals = [float(x) for row in v.v for x in row]
            JOURNAL.append("IN " + name + " [" + str(r) + "," + str(c) + "] = " + " ".join(_canon_float(x) for x in vals))
            return {"dtype": "Float64", "shape": [r, c], "values": vals, "lossy": False}
        vals = [float(x) for x in v.v]
        JOURNAL.append("IN " + name + " [" + str(len(vals)) + "] = " + " ".join(_canon_float(x) for x in vals))
        return {"dtype": "Float64", "shape": [len(vals)], "values": vals, "lossy": False}
    raise NodeError("TypeError", 'input "' + name + '": unsupported SoundValue/type combo')

def from_triomat_value(payload):
    shape, values = payload["shape"], payload["values"]
    if shape == []:
        return Value.f(values[0])
    if len(shape) == 1:
        return Value.vec(values)
    r, c = shape
    return Value.vec([values[i * c:(i + 1) * c] for i in range(r)])

def octave_backend_emulated(spec, files, workdir="."):
    # Эмуляция той же арифметики, что в run_mat_mul_scalar_octave.m.
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
    raise NodeError("ProcessError", "real octave backend not wired yet (OPEN gate)")

def run_node(spec, inputs, backend, workdir="."):
    files = {}
    for io in spec["inputs"]:
        name = io["name"]
        if name not in inputs:
            return None, ("ShapeError", 'missing input "' + name + '"')
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
            return None, ("ProcessError", 'backend did not produce "' + name + '"')
        payload = results[name]
        if payload["dtype"] != io.get("dtype", "Float64"):
            return None, ("TypeError", 'output "' + name + '": dtype=' + payload["dtype"] + ", expected " + io["dtype"])
        outs = from_triomat_value(payload)
        flat = ([x for row in outs.v for x in row] if outs.v and isinstance(outs.v[0], list)
                else outs.v if isinstance(outs.v, list) else [outs.v])
        JOURNAL.extend("OUT " + name + "[" + str(i) + "] = " + _canon_float(x) for i, x in enumerate(flat))
        outputs[name] = outs
    return outputs, None

def eval_node_call(name, args, backend=None):
    # Ошибка приходит как Err(code) — как положено в SCore.
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
# Модели данных: рекорды и сум-типы (T14, T16)
# ============================================================
RECORD_REGISTRY = {}

class RecordType:
    def __init__(self, name, fields, invariants=None):
        self.name = name
        self.fields = [(f["name"], f["type"]) for f in fields] if fields and isinstance(fields[0], dict) else list(fields)
        self.invariants = invariants or []
    def construct(self, args):
        names = [f[0] for f in self.fields]
        extra = set(args) - set(names)
        if extra:
            return Value.err("UnknownField:" + ",".join(sorted(extra)))
        checked, lossy, by_name = [], {}, {}
        for fname, kind in self.fields:
            if fname not in args:
                return Value.err("MissingField:" + fname)
            v = args[fname]
            if v.t == ValueType.ERR:
                return v
            if kind == "float":
                if v.t == ValueType.INT:
                    if abs(v.v) > 2**53:
                        lossy[fname] = True
                        JOURNAL.append("STRUCT " + self.name + "." + fname + " <- int " + str(v.v)
                                       + " -> " + _canon_float(float(v.v)) + " lossy=TRUE")
                    v = Value.f(float(v.v))
                elif v.t != ValueType.FLOAT:
                    return Value.err("TypeError:" + fname)
            elif kind == "int":
                if v.t != ValueType.INT:
                    return Value.err("TypeError:" + fname)
            elif kind == "vec":
                if v.t != ValueType.VEC:
                    return Value.err("TypeError:" + fname)
            elif kind.startswith("ref:"):
                target = kind[4:]
                if v.t != ValueType.STRUCT or v.v[0] != target:
                    return Value.err("TypeError:" + fname)
            else:
                return Value.err("TypeError:" + fname)
            checked.append((fname, kind, v))
            by_name[fname] = v
        for inv in self.invariants:
            field = inv["field"]
            val = by_name.get(field)
            if val is None or val.t != ValueType.FLOAT:
                return Value.err("InvariantViolation:" + field)
            if "min" in inv and val.v < inv["min"]:
                return Value.err("InvariantViolation:" + field)
            if "max" in inv and val.v > inv["max"]:
                return Value.err("InvariantViolation:" + field)
        return Value.struct(self.name, checked, lossy)

class SumType:
    def __init__(self, name, variants):
        self.name = name
        self.order = [v["name"] for v in variants]
        self.variants = {v["name"]: [(f["name"], f["type"]) for f in v["fields"]] for v in variants}
    def construct(self, vname, args):
        if vname not in self.variants:
            return Value.err("UnknownVariant:" + vname)
        rt = RecordType(vname, [{"name": fn, "type": ft} for fn, ft in self.variants[vname]])
        return rt.construct(args)
    def fingerprint(self):
        parts = []
        for vname in self.order:
            fl = self.variants[vname]
            parts.append(vname + "(" + ".".join(fn + ":" + ft for fn, ft in fl) + ")")
        return self.name + "[" + "|".join(parts) + "]"

def type_fingerprint(name):
    t = RECORD_REGISTRY.get(name)
    if t is None:
        return Value.err("UnknownType:" + name)
    if isinstance(t, SumType):
        return t.fingerprint()
    return t.name + "(" + ".".join(fn + ":" + ft for fn, ft in t.fields) + ")"

def generate_model(spec):
    # Кодогенератор: спека -> конструкторы в реестре. Одинаковая спека -> одинаковый реестр.
    if spec.get("format") != "TRIOMODEL1":
        return Value.err("SpecError")
    made = {}
    for t in spec.get("types", []):
        kind = t.get("kind")
        if kind == "record":
            for f in t["fields"]:
                k = f["type"]
                if k not in ("int", "float", "vec") and not (k.startswith("ref:") and len(k) > 4):
                    return Value.err("SpecError")
            rt = RecordType(t["name"], t["fields"], t.get("invariants"))
            RECORD_REGISTRY[rt.name] = rt
            made[rt.name] = rt
        elif kind == "sum":
            st = SumType(t["name"], t["variants"])
            RECORD_REGISTRY[st.name] = st
            made[st.name] = st
        else:
            return Value.err("SpecError")
    return made

# ============================================================
# TRIOREC1: плоские рекорды. Вложенные и ref — только TRIOREC2.
# ============================================================
def serialize_record(v):
    if v.t == ValueType.ERR: return Value.err("SerializeError")
    if v.t != ValueType.STRUCT: return Value.err("SerializeError")
    name, fields, lossy = v.v
    reg = RECORD_REGISTRY.get(name)
    if reg is None: return Value.err("UnknownType:" + name)
    if not isinstance(reg, RecordType): return Value.err("FieldMismatch")
    if [(f[0], f[1]) for f in fields] != [(f[0], f[1]) for f in reg.fields]:
        return Value.err("FieldMismatch")
    for fname, kind, val in fields:
        if kind.startswith("ref:") or val.t == ValueType.STRUCT:
            return Value.err("SerializeError")
    header = {"format": "TRIOREC1", "version": 1, "type": name,
              "fields": [[f[0], f[1]] for f in fields],
              "lossy": [k for k, flag in (lossy or {}).items() if flag]}
    lines = [json.dumps(header, separators=(",", ":"))]
    for fname, kind, val in fields:
        if kind == "float": lines.append(_canon_float(val.v))
        elif kind == "int": lines.append(str(val.v))
        else: return Value.err("SerializeError")
    return "\n".join(lines)

def load_record(text):
    lines = text.split("\n")
    try:
        header = json.loads(lines[0])
    except Exception:
        return Value.err("SerializeError")
    if header.get("format") != "TRIOREC1": return Value.err("SerializeError")
    reg = RECORD_REGISTRY.get(header.get("type"))
    if reg is None: return Value.err("UnknownType:" + str(header.get("type")))
    if not isinstance(reg, RecordType): return Value.err("FieldMismatch")
    want = [[f[0], f[1]] for f in reg.fields]
    if header.get("fields") != want: return Value.err("FieldMismatch")
    fields, lossy = [], {}
    for i, (fname, kind) in enumerate(want):
        if 1 + i >= len(lines): return Value.err("FieldMismatch")
        s = lines[1 + i]
        try:
            if kind == "float":
                fields.append((fname, kind, Value.f(parse_canon_float(s))))
            elif kind == "int":
                fields.append((fname, kind, Value.i(int(s))))
            else:
                return Value.err("SerializeError")
        except Exception:
            return Value.err("FieldMismatch")
    for lp in header.get("lossy", []):
        lossy[lp] = True
    return Value.struct(header["type"], fields, lossy)

# ============================================================
# TRIOREC2: вложенные рекорды и ref-поля. Ацикличны по построению,
# глубина ограничена — защита от чужих данных.
# ============================================================
MAX_DEPTH = 64

def _lossy_paths(v, prefix=""):
    # Пути флагов потери: "pod.capacity" — для агрегации в заголовке верхнего уровня.
    name, fields, lossy = v.v
    out = []
    for fname, kind, val in fields:
        p = prefix + fname
        if (lossy or {}).get(fname):
            out.append(p)
        if kind.startswith("ref:") and val.t == ValueType.STRUCT:
            out.extend(_lossy_paths(val, p + "."))
    return out

def _serialize2_body(v, depth):
    if depth > MAX_DEPTH:
        return "ERR:CycleDetected"
    name, fields, lossy = v.v
    header = {"format": "TRIOREC2", "version": 2, "type": name,
              "fields": [[f[0], f[1]] for f in fields],
              "lossy": _lossy_paths(v)}
    lines = [json.dumps(header, separators=(",", ":"))]
    for fname, kind, val in fields:
        if kind.startswith("ref:"):
            lines.append("@begin " + fname + ":" + kind[4:])
            sub = _serialize2_body(val, depth + 1)
            if sub.startswith("ERR:"):
                return sub
            lines.append(sub)
            lines.append("@end " + fname)
        elif kind == "float":
            lines.append(_canon_float(val.v))
        elif kind == "int":
            lines.append(str(val.v))
        else:
            return "ERR:SerializeError"
    return "\n".join(lines)

def serialize_record2(v):
    if v.t == ValueType.ERR: return Value.err("SerializeError")
    if v.t != ValueType.STRUCT: return Value.err("SerializeError")
    name = v.v[0]
    reg = RECORD_REGISTRY.get(name)
    if reg is None: return Value.err("UnknownType:" + name)
    if not isinstance(reg, RecordType): return Value.err("FieldMismatch")
    if [(f[0], f[1]) for f in v.v[1]] != [(f[0], f[1]) for f in reg.fields]:
        return Value.err("FieldMismatch")
    body = _serialize2_body(v, 0)
    if body == "ERR:CycleDetected": return Value.err("CycleDetected")
    if body is None or body.startswith("ERR:"): return Value.err("SerializeError")
    return body

def load_record2(text):
    lines = text.split("\n")
    idx = [0]
    def parse_block():
        try:
            header = json.loads(lines[idx[0]])
        except Exception:
            return ("ERR", "SerializeError")
        idx[0] += 1
        if header.get("format") != "TRIOREC2":
            return ("ERR", "SerializeError")
        tname = header.get("type")
        reg = RECORD_REGISTRY.get(tname)
        if reg is None: return ("ERR", "UnknownType:" + str(tname))
        if not isinstance(reg, RecordType): return ("ERR", "FieldMismatch")
        want = [[f[0], f[1]] for f in reg.fields]
        if header.get("fields") != want: return ("ERR", "FieldMismatch")
        fields, lossy = [], {}
        for fname, kind in want:
            if idx[0] >= len(lines): return ("ERR", "FieldMismatch")
            s = lines[idx[0]]
            if kind.startswith("ref:"):
                if s != "@begin " + fname + ":" + kind[4:]:
                    return ("ERR", "FieldMismatch")
                idx[0] += 1
                sub = parse_block()
                if isinstance(sub, tuple): return sub
                if idx[0] >= len(lines) or lines[idx[0]] != "@end " + fname:
                    return ("ERR", "FieldMismatch")
                idx[0] += 1
                fields.append((fname, kind, sub))
            elif kind == "float":
                try:
                    fields.append((fname, kind, Value.f(parse_canon_float(s))))
                except Exception:
                    return ("ERR", "FieldMismatch")
                idx[0] += 1
            elif kind == "int":
                try:
                    fields.append((fname, kind, Value.i(int(s))))
                except Exception:
                    return ("ERR", "FieldMismatch")
                idx[0] += 1
            else:
                return ("ERR", "FieldMismatch")
        # plain-имена потери — свои; пути с точками — агрегаты, они живут во вложенных заголовках
        for lp in header.get("lossy", []):
            if "." not in lp:
                lossy[lp] = True
        return Value.struct(tname, fields, lossy)
    res = parse_block()
    if isinstance(res, tuple):
        return Value.err(res[1])
    if idx[0] != len(lines):
        return Value.err("FieldMismatch")
    return res

# ============================================================
# Батарея тестов (89 в полной версии; здесь — 9 реализованных)
# ============================================================
def run_battery():
    tests_passed = 0
    tests_total = 89

    # T06: лексический захват (FIX-1: замыкание через apply_closure)
    def mk_f(env_snap):
        def fn(clo_env, y):
            return add(clo_env["x1"], y)
        return Value.clo(fn, env_snap)
    env1 = {"x1": Value.i(105), "f": mk_f({"x1": Value.i(1)})}
    if apply_closure(env1["f"], Value.i(5)).canon() == "6":
        tests_passed += 1

    # T07: reduce с шагами
    def step(acc, x):
        return add(acc, x)
    r = reduce_vec(Value.vec([1.0, 2.0, 3.0, 4.0]), Value.i(0), step)
    if r.canon() == "0x1.4000000000000p+3":
        tests_passed += 1

    # T11: narrow с ошибкой (FIX-2: теперь по смыслу, а не случайно)
    if narrow(Value.f(3.5)).canon() == "Err(PrecisionLoss)":
        tests_passed += 1

    # T12: R-INT1 ties-to-even на границе 2^53
    # 2^53+3 лежит ровно посередине между 2^53+2 и 2^53+4: ties-to-even
    # поднимает к чётной мантиссе (...2). Обрубание дало бы (...1).
    cases = ((2**53, "0x1.0000000000000p+53", False),
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

    # T13: мост узлов — рабочий путь, путь ошибки, R-INT1 на входе узла
    NODE_SPECS.setdefault("mat_mul_scalar_octave", {
        "name": "mat_mul_scalar_octave", "backend": "octave",
        "inputs": [{"name": "A", "type": "matrix", "dtype": "Float64"},
                   {"name": "k", "type": "scalar", "dtype": "Float64"}],
        "outputs": [{"name": "B", "type": "matrix", "dtype": "Float64"}]})
    JOURNAL.clear()
    r = eval_node_call("mat_mul_scalar_octave",
                       [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.f(2.0)])
    ok13 = (r.t == ValueType.VEC and r.v == [[2.0, 4.0], [6.0, 8.0]]
            and "OUT B[3] = 0x1.0000000000000p+3" in JOURNAL)
    JOURNAL.clear()
    r2 = eval_node_call("mat_mul_scalar_octave",
                        [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.vec([1.0])])
    ok13 = ok13 and r2.t == ValueType.ERR and r2.v == "ShapeError"
    ok13 = ok13 and any(e.startswith("IN A [2,2]") for e in JOURNAL)
    JOURNAL.clear()
    eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0]]), Value.i(2**53 + 1)])
    ok13 = ok13 and any(e.startswith("IN k[] =") and "lossy=TRUE" in e for e in JOURNAL)
    if ok13:
        tests_passed += 1

    # T14: рекорды и сум-типы
    RECORD_REGISTRY["Point"] = RecordType("Point", [{"name": "x", "type": "float"},
                                                     {"name": "y", "type": "float"}])
    RECORD_REGISTRY["Shape"] = SumType("Shape", [
        {"name": "Circle", "fields": [{"name": "r", "type": "float"}]},
        {"name": "Rect", "fields": [{"name": "w", "type": "float"},
                                    {"name": "h", "type": "float"}]}])
    p1 = RECORD_REGISTRY["Point"].construct({"x": Value.f(1.5), "y": Value.i(2)})
    ok14 = p1.t == ValueType.STRUCT and canon_val(p1) == "{Point x=0x1.8000000000000p+0 y=0x1.0000000000000p+1}"
    p2 = RECORD_REGISTRY["Point"].construct({"x": Value.f(1.5), "y": Value.i(2)})
    ok14 = ok14 and struct_eq(p1, p2).v is True
    pn = RECORD_REGISTRY["Point"].construct({"x": Value.f(-0.0), "y": Value.f(0.0)})
    ok14 = ok14 and struct_eq(pn, RECORD_REGISTRY["Point"].construct({"x": Value.f(0.0), "y": Value.f(0.0)})).v is False
    ok14 = ok14 and RECORD_REGISTRY["Point"].construct({"x": Value.f(1.0), "z": Value.f(2.0)}).v == "UnknownField:z"
    ok14 = ok14 and RECORD_REGISTRY["Point"].construct({"x": Value.f(1.0)}).v == "MissingField:y"
    ok14 = ok14 and RECORD_REGISTRY["Point"].construct({"x": Value.vec([1.0]), "y": Value.f(2.0)}).v == "TypeError:x"
    JOURNAL.clear()
    RECORD_REGISTRY["Point"].construct({"x": Value.i(2**53 + 1), "y": Value.f(0.0)})
    ok14 = ok14 and any(e.startswith("STRUCT Point.x <- int ") and "lossy=TRUE" in e for e in JOURNAL)
    _PI = float.fromhex("0x1.921fb54442d18p+1")
    circ = RECORD_REGISTRY["Shape"].construct("Circle", {"r": Value.f(2.0)})
    area_c = mul(Value.f(_PI), mul(circ.v[1][0][2], circ.v[1][0][2]))
    ok14 = ok14 and _canon_float(area_c.v) == "0x1.921fb54442d18p+3"
    rect = RECORD_REGISTRY["Shape"].construct("Rect", {"w": Value.f(2.0), "h": Value.f(3.0)})
    area_r = mul(rect.v[1][0][2], rect.v[1][1][2])
    ok14 = ok14 and _canon_float(area_r.v) == "0x1.8000000000000p+2"
    ok14 = ok14 and RECORD_REGISTRY["Shape"].construct("Triangle", {}).v == "UnknownVariant:Triangle"
    def match_area(sval):
        name = sval.v[0]
        d = {f[0]: f[2] for f in sval.v[1]}
        if name == "Circle":
            return mul(Value.f(_PI), mul(d["r"], d["r"]))
        if name == "Rect":
            return mul(d["w"], d["h"])
        return Value.err("UnknownVariant:" + name)
    ok14 = ok14 and _canon_float(match_area(circ).v) == "0x1.921fb54442d18p+3"
    ok14 = ok14 and canon_val(circ) == canon_val(RECORD_REGISTRY["Shape"].construct("Circle", {"r": Value.f(2.0)}))
    if ok14:
        tests_passed += 1

    # T15: TRIOREC1 — roundtrip, детерминизм, lossy, ошибки
    p = RECORD_REGISTRY["Point"].construct({"x": Value.f(1.5), "y": Value.f(2.0)})
    txt = serialize_record(p)
    ok15 = not isinstance(txt, Value) and '"format":"TRIOREC1"' in txt
    back = load_record(txt)
    ok15 = ok15 and struct_eq(p, back).v is True
    txt2 = serialize_record(RECORD_REGISTRY["Point"].construct({"x": Value.f(1.5), "y": Value.f(2.0)}))
    ok15 = ok15 and txt == txt2
    pm = RECORD_REGISTRY["Point"].construct({"x": Value.f(-0.0), "y": Value.f(1.0)})
    backm = load_record(serialize_record(pm))
    ok15 = ok15 and struct_eq(backm, RECORD_REGISTRY["Point"].construct({"x": Value.f(0.0), "y": Value.f(1.0)})).v is False
    pl = RECORD_REGISTRY["Point"].construct({"x": Value.i(2**53 + 3), "y": Value.f(0.0)})
    txtl = serialize_record(pl)
    ok15 = ok15 and '"lossy":["x"]' in txtl
    ok15 = ok15 and (load_record(txtl).v[2].get("x") is True)
    ok15 = ok15 and load_record(txt.replace("Point", "Ghost")).v == "UnknownType:Ghost"
    ok15 = ok15 and serialize_record(Value.err("X")).v == "SerializeError"
    if ok15:
        tests_passed += 1

    # T16: кодогенератор моделей
    spec = {"format": "TRIOMODEL1", "types": [
        {"kind": "record", "name": "Dolphin",
         "fields": [{"name": "id", "type": "int"}, {"name": "score", "type": "float"}],
         "invariants": [{"field": "score", "min": 0.0, "max": 100.0}]},
        {"kind": "record", "name": "Pod", "fields": [{"name": "capacity", "type": "float"}]},
        {"kind": "sum", "name": "Shape2",
         "variants": [{"name": "Circle", "fields": [{"name": "r", "type": "float"}]},
                      {"name": "Rect", "fields": [{"name": "w", "type": "float"},
                                                  {"name": "h", "type": "float"}]}]}]}
    g1 = generate_model(spec)
    g2 = generate_model(spec)
    fp1 = [type_fingerprint(n) for n in ("Dolphin", "Pod", "Shape2")]
    fp2 = [type_fingerprint(n) for n in ("Dolphin", "Pod", "Shape2")]
    ok16 = fp1 == fp2 and fp1[0] == "Dolphin(id:int.score:float)"
    ok16 = ok16 and fp1[2] == "Shape2[Circle(r:float)|Rect(w:float.h:float)]"
    d = g1["Dolphin"].construct({"id": Value.i(7), "score": Value.f(0.98)})
    ok16 = ok16 and canon_val(d) == "{Dolphin id=7 score=0x1.f5c28f5c28f5cp-1}"
    ok16 = ok16 and g1["Dolphin"].construct({"id": Value.i(1), "score": Value.f(150.0)}).v == "InvariantViolation:score"
    ok16 = ok16 and g1["Dolphin"].construct({"id": Value.i(1), "score": Value.f(100.0)}).t == ValueType.STRUCT
    ok16 = ok16 and g1["Dolphin"].construct({"id": Value.i(1), "score": Value.f(-0.5)}).v == "InvariantViolation:score"
    JOURNAL.clear()
    g1["Pod"].construct({"capacity": Value.i(2**53 + 3)})
    ok16 = ok16 and any(e.startswith("STRUCT Pod.capacity <- int ") and "lossy=TRUE" in e for e in JOURNAL)
    ok16 = ok16 and g1["Dolphin"].construct({"id": Value.i(1)}).v == "MissingField:score"
    ok16 = ok16 and g1["Dolphin"].construct({"id": Value.i(1), "score": Value.f(1.0), "x": Value.f(1.0)}).v == "UnknownField:x"
    ok16 = ok16 and g1["Dolphin"].construct({"id": Value.f(1.0), "score": Value.f(1.0)}).v == "TypeError:id"
    ok16 = ok16 and generate_model({"format": "TRIOMODEL1", "types": [{"kind": "weird", "name": "X"}]}).v == "SpecError"
    if ok16:
        tests_passed += 1

    # T17: TRIOREC2 — вложенные рекорды, ref-поля, глубина, агрегация lossy
    gen = generate_model({"format": "TRIOMODEL1", "types": [
        {"kind": "record", "name": "Pod2", "fields": [{"name": "capacity", "type": "float"}]},
        {"kind": "record", "name": "Dolphin2", "fields": [
            {"name": "id", "type": "int"}, {"name": "score", "type": "float"},
            {"name": "pod", "type": "ref:Pod2"}]}]})
    ok17 = isinstance(gen, dict) and "Dolphin2" in gen
    pod = gen["Pod2"].construct({"capacity": Value.f(20.0)})
    dol = gen["Dolphin2"].construct({"id": Value.i(7), "score": Value.f(0.98), "pod": pod})
    ok17 = ok17 and dol.t == ValueType.STRUCT
    txt = serialize_record2(dol)
    ok17 = ok17 and not isinstance(txt, Value)
    ok17 = ok17 and "@begin pod:Pod2" in txt and '"format":"TRIOREC2"' in txt
    back = load_record2(txt)
    ok17 = ok17 and back.t != ValueType.ERR and struct_eq(dol, back).v is True
    txt_b = serialize_record2(gen["Dolphin2"].construct({"id": Value.i(7), "score": Value.f(0.98), "pod": pod}))
    ok17 = ok17 and txt == txt_b  # детерминизм сериализации
    # lossy из вложенного рекорда агрегируется в заголовок верхнего уровня
    podl = gen["Pod2"].construct({"capacity": Value.i(2**53 + 3)})
    doll = gen["Dolphin2"].construct({"id": Value.i(1), "score": Value.f(0.5), "pod": podl})
    txtl = serialize_record2(doll)
    ok17 = ok17 and not isinstance(txtl, Value) and '"lossy":["pod.capacity"]' in txtl
    ok17 = ok17 and '"lossy":["capacity"]' in txtl  # вложенный блок несёт свой флаг
    backl = load_record2(txtl)
    ok17 = ok17 and backl.t != ValueType.ERR and backl.v[2].get("pod") is None and struct_eq(doll, backl).v is True
    # ref с чужим типом -> TypeError
    pt = RECORD_REGISTRY["Point"].construct({"x": Value.f(1.0), "y": Value.f(2.0)})
    rbad = gen["Dolphin2"].construct({"id": Value.i(1), "score": Value.f(0.5), "pod": pt})
    ok17 = ok17 and rbad.v == "TypeError:pod"
    # неизвестный тип во вложенном блоке при загрузке
    # подменяем тип только во вложенном заголовке: поле ref:Pod2 в верхнем — валидно,
    # и FileMismatch должен наступить позже, а UnknownType:Ghost — внутри вложенного блока
    ok17 = ok17 and load_record2(txt.replace('"type":"Pod2"', '"type":"Ghost"')).v == "UnknownType:Ghost"
    # TRIOREC1 честно отказывается от ref-полей
    ok17 = ok17 and serialize_record(dol).v == "SerializeError"
    # глубинный страж (белый ящик): защита от чужих зацикленных данных
    ok17 = ok17 and _serialize2_body(dol, 200) == "ERR:CycleDetected"
    if ok17:
        tests_passed += 1

    print("Battery: " + str(tests_passed) + "/" + str(tests_total))
    return tests_passed == tests_total

if __name__ == "__main__":
    ok = run_battery()
    print("OK" if ok else "FAIL")
