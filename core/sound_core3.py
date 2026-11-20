# sound_core3.py - v1.0
# Оригинал v0.3 + FIX-1..FIX-5 + Trio Bridge + STRUCT/TRIOREC1/TRIOREC2 + кодогенератор + vec-поля
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
    def vec(xs): return Value(ValueType.VEC, list(xs))
    @staticmethod
    def clo(fn, env): return Value(ValueType.CLOSURE, (fn, env))
    @staticmethod
    def err(code): return Value(ValueType.ERR, code)
    @staticmethod
    def struct(name, fields, lossy=None):
        return Value(ValueType.STRUCT, (name, list(fields), dict(lossy or {})))
    def canon(self):
        return canon_val(self)

JOURNAL = []

def _canon_float(x):
    # FIX-5: канон — 13 hex-цифр мантиссы, знак порядка обязателен
    if math.isnan(x):
        return "nan"
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
    return sign + "0x" + int_part + "." + frac + "p" + exp

def canon_val(v):
    if v.t == ValueType.INT:
        return str(v.v)
    if v.t == ValueType.FLOAT:
        return _canon_float(v.v)
    if v.t == ValueType.BOOL:
        return "true" if v.v else "false"
    if v.t == ValueType.VEC:
        def el(x):
            if isinstance(x, Value):
                return canon_val(x)
            if isinstance(x, bool):
                return "true" if x else "false"
            if isinstance(x, int):
                return str(x)
            if isinstance(x, float):
                return _canon_float(x)
            return "?"
        if v.v and isinstance(v.v[0], list):
            return "[" + ";".join(",".join(el(x) for x in row) for row in v.v) + "]"
        return "[" + ",".join(el(x) for x in v.v) + "]"
    if v.t == ValueType.STRUCT:
        name, fields, lossy = v.v
        parts = " ".join(n + "=" + canon_val(val) for n, val in fields)
        return "{" + name + (" " + parts if parts else "") + "}"
    if v.t == ValueType.CLOSURE:
        return "<closure>"
    if v.t == ValueType.ERR:
        return "Err(" + str(v.v) + ")"
    return "?"

_PI = float.fromhex("0x1.921fb54442d18p+1")

def struct_eq(a, b):
    if a.t == ValueType.ERR or b.t == ValueType.ERR:
        return Value.err("PropError")
    if a.t != ValueType.STRUCT or b.t != ValueType.STRUCT:
        return Value.err("PropError")
    return Value.b(canon_val(a) == canon_val(b))

def widen(v):
    # FIX-4: R-INT1 с журналированием потери точности
    if v.t == ValueType.INT:
        x = float(v.v)
        lossy = abs(v.v) > 2**53
        JOURNAL.append("widen " + str(v.v) + " -> " + _canon_float(x) + (" lossy=TRUE" if lossy else ""))
        return Value.f(x)
    if v.t == ValueType.FLOAT:
        return v
    return Value.err("TypeMismatch")

def narrow(v):
    # FIX-2: math.modf возвращает (frac, i)
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
                return walk(body, params + ps)
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

# ============ Trio Bridge ============
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
    raise NodeError("TypeError", "input: unsupported SoundValue/type combo")

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
    # OPEN-гейт: subprocess.run(["octave", "--no-gui", "--quiet", ...])
    raise NodeError("ProcessError", "real octave backend not wired yet (OPEN gate)")

def run_node(spec, inputs, backend, workdir="."):
    files = {}
    for io in spec["inputs"]:
        name = io["name"]
        if name not in inputs:
            return None, ("ShapeError", "missing input")
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
            return None, ("ProcessError", "backend did not produce output")
        payload = results[name]
        if payload["dtype"] != io.get("dtype", "Float64"):
            return None, ("TypeError", "output dtype mismatch")
        outs = from_triomat_value(payload)
        flat = ([x for row in outs.v for x in row] if outs.v and isinstance(outs.v[0], list)
                else outs.v if isinstance(outs.v, list) else [outs.v])
        JOURNAL.extend("OUT " + name + "[" + str(i) + "] = " + _canon_float(x) for i, x in enumerate(flat))
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

# ============ Структуры ============
class RecordType:
    def __init__(self, name, fields, invariants=None):
        self.name = name
        self.fields = list(fields)
        self.invariants = dict(invariants or {})
    def construct(self, args):
        extra = set(args) - {f[0] for f in self.fields}
        if extra:
            return Value.err("UnknownField:" + ",".join(sorted(extra)))
        checked = []
        lossy = {}
        for fname, kind in self.fields:
            if fname not in args:
                return Value.err("MissingField:" + fname)
            v = args[fname]
            if isinstance(v, bool):
                pass  # bool не числовой аргумент — упадёт на проверке типа ниже
            elif isinstance(v, int):
                v = Value.i(v)
            elif isinstance(v, float):
                v = Value.f(v)
            if kind == "float":
                if v.t == ValueType.INT:
                    lossy_f = abs(v.v) > 2**53
                    if lossy_f:
                        lossy[fname] = True
                    JOURNAL.append("STRUCT " + self.name + "." + fname + " <- int " + str(v.v) + " -> " + _canon_float(float(v.v)) + (" lossy=TRUE" if lossy_f else ""))
                    v = Value.f(float(v.v))
                elif v.t == ValueType.FLOAT:
                    pass
                else:
                    return Value.err("TypeError:" + fname)
            elif kind == "int":
                if v.t != ValueType.INT:
                    return Value.err("TypeError:" + fname)
            elif kind in ("vec", "vec:float"):
                if v.t != ValueType.VEC:
                    return Value.err("TypeError:" + fname)
                cnt = [0]
                def chk(el):
                    lossy_f = False
                    if isinstance(el, Value):
                        if el.t == ValueType.INT:
                            lossy_f = abs(el.v) > 2**53
                            num = el.v
                        elif el.t == ValueType.FLOAT:
                            num = el.v
                        else:
                            return False
                    elif isinstance(el, bool) or not isinstance(el, (int, float)):
                        return False
                    else:
                        lossy_f = isinstance(el, int) and abs(el) > 2**53
                        num = el
                    if lossy_f:
                        lossy[fname] = True
                        JOURNAL.append("STRUCT " + self.name + "." + fname + "[" + str(cnt[0]) + "] <- int " + str(num) + " -> " + _canon_float(float(num)) + " lossy=TRUE")
                    cnt[0] += 1
                    return True
                if not all(chk(x) for x in _iter_vec(v.v)):
                    return Value.err("TypeError:" + fname)
            elif kind.startswith("ref:"):
                refname = kind[4:]
                if v.t != ValueType.STRUCT or v.v[0] != refname:
                    return Value.err("TypeError:" + fname)
                for p in v.v[2]:
                    lossy[fname + "." + p] = True
            else:
                return Value.err("TypeError:" + fname)
            inv = self.invariants.get(fname)
            if inv is not None:
                val = v.v
                if "min" in inv and val < inv["min"]:
                    return Value.err("InvariantViolation:" + fname)
                if "max" in inv and val > inv["max"]:
                    return Value.err("InvariantViolation:" + fname)
            checked.append((fname, v))
        return Value.struct(self.name, checked, lossy)

def _iter_vec(els):
    for x in els:
        if isinstance(x, list):
            for y in _iter_vec(x):
                yield y
        else:
            yield x

class SumType:
    def __init__(self, name, variants):
        self.name = name
        self.variants = {}
        for vt in variants:
            fs = vt.get("fields", [])
            norm = [(f["name"], f["type"]) if isinstance(f, dict) else f for f in fs]
            self.variants[vt["name"]] = norm
    def construct(self, tag, args):
        if tag not in self.variants:
            return Value.err("UnknownVariant:" + tag)
        fields = self.variants[tag]
        extra = set(args) - {f[0] for f in fields}
        if extra:
            return Value.err("UnknownField:" + ",".join(sorted(extra)))
        checked = []
        lossy = {}
        for fname, kind in fields:
            if fname not in args:
                return Value.err("MissingField:" + fname)
            v = args[fname]
            if isinstance(v, bool):
                pass
            elif isinstance(v, int):
                v = Value.i(v)
            elif isinstance(v, float):
                v = Value.f(v)
            if kind == "float":
                if v.t == ValueType.INT:
                    if abs(v.v) > 2**53:
                        lossy[fname] = True
                    v = Value.f(float(v.v))
                elif v.t == ValueType.FLOAT:
                    pass
                else:
                    return Value.err("TypeError:" + fname)
            else:
                return Value.err("TypeError:" + fname)
            checked.append((fname, v))
        return Value.struct(tag, checked, lossy)

RECORD_REGISTRY = {}

def registry_fingerprint():
    parts = []
    for name, t in RECORD_REGISTRY.items():
        if isinstance(t, RecordType):
            fs = ".".join(fn + ":" + k for fn, k in t.fields)
            inv = ""
            if t.invariants:
                inv = "|inv:" + ",".join(sorted(t.invariants))
            parts.append(name + "(" + fs + ")" + inv)
        elif isinstance(t, SumType):
            vs = "|".join(vn + "(" + ",".join(fn + ":" + k for fn, k in fs) + ")" for vn, fs in t.variants.items())
            parts.append(name + "[" + vs + "]")
    return ";".join(parts)

# ============ TRIOREC1/2 ============
MAX_DEPTH = 64

def _raw_token(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, Value):
        if x.t == ValueType.INT:
            return _canon_float(float(x.v))
        if x.t == ValueType.FLOAT:
            return _canon_float(x.v)
        return None
    if isinstance(x, int):
        return _canon_float(float(x))
    if isinstance(x, float):
        return _canon_float(x)
    return None

def _parse_token(tok):
    if tok == "nan": return Value.f(float("nan"))
    if tok == "inf": return Value.f(math.inf)
    if tok == "-inf": return Value.f(-math.inf)
    try:
        return Value.i(int(tok))
    except ValueError:
        pass
    try:
        return Value.f(float.fromhex(tok))
    except (ValueError, OverflowError):
        return None

def _value_token(v, kind):
    if kind == "float":
        if v.t == ValueType.FLOAT: return _canon_float(v.v)
        if v.t == ValueType.INT: return _canon_float(float(v.v))
        return None
    if kind == "int":
        if v.t == ValueType.INT: return str(v.v)
        return None
    return None

def serialize_record(sv):
    if not isinstance(sv, Value) or sv.t == ValueType.ERR or sv.t != ValueType.STRUCT:
        return Value.err("SerializeError")
    name, fields, lossy = sv.v
    rt = RECORD_REGISTRY.get(name)
    if rt is None or not isinstance(rt, RecordType):
        return Value.err("UnknownType:" + name)
    if [f[0] for f in fields] != [f[0] for f in rt.fields]:
        return Value.err("FieldMismatch")
    if any(k.startswith("ref:") or k in ("vec", "vec:float") for _, k in rt.fields):
        return Value.err("SerializeError")
    fmap = dict(fields)
    lines = [json.dumps({"format": "TRIOREC1", "version": 1, "type": name,
                         "fields": [[fn, k] for fn, k in rt.fields],
                         "lossy": sorted(lossy)}, separators=(",", ":"))]
    for fname, kind in rt.fields:
        tok = _value_token(fmap[fname], kind)
        if tok is None:
            return Value.err("SerializeError")
        lines.append(tok)
    return "\n".join(lines)

def load_record(text, registry=None):
    registry = registry if registry is not None else RECORD_REGISTRY
    lines = [l for l in text.split("\n") if l.strip() != ""]
    try:
        header = json.loads(lines[0])
    except Exception:
        return Value.err("FieldMismatch")
    if header.get("format") != "TRIOREC1":
        return Value.err("FieldMismatch")
    name = header.get("type")
    rt = registry.get(name)
    if rt is None or not isinstance(rt, RecordType):
        return Value.err("UnknownType:" + str(name))
    if header.get("fields") != [[f[0], k] for f, k in rt.fields]:
        return Value.err("FieldMismatch")
    if any(k.startswith("ref:") or k in ("vec", "vec:float") for _, k in rt.fields):
        return Value.err("SerializeError")
    idx = 1
    fields = []
    lossy = {}
    for fname, kind in rt.fields:
        if idx >= len(lines):
            return Value.err("FieldMismatch")
        pv = _parse_token(lines[idx])
        idx += 1
        if pv is None:
            return Value.err("FieldMismatch")
        if kind == "float" and pv.t != ValueType.FLOAT:
            return Value.err("FieldMismatch")
        if kind == "int" and pv.t != ValueType.INT:
            return Value.err("FieldMismatch")
        fields.append((fname, pv))
    for p in header.get("lossy", []):
        lossy[p] = True
    return Value.struct(name, fields, lossy)

def serialize_vec_payload(val):
    if val.t != ValueType.VEC:
        return None
    rows = val.v
    if rows and isinstance(rows[0], list):
        c = len(rows[0])
        for r in rows:
            if not isinstance(r, list) or len(r) != c:
                return None
        for x in _iter_vec(rows):
            if _raw_token(x) is None:
                return None
        shape = [len(rows), c]
        vals = [x for r in rows for x in r]
    else:
        for x in rows:
            if _raw_token(x) is None:
                return None
        shape = [len(rows)]
        vals = list(rows)
    out = ["[" + ",".join(str(s) for s in shape) + "]"]
    out.extend(_raw_token(x) for x in vals)
    return out

def serialize_record2(sv):
    if not isinstance(sv, Value) or sv.t == ValueType.ERR or sv.t != ValueType.STRUCT:
        return Value.err("SerializeError")
    return _ser2(sv, 0)

def _ser2(sv, depth):
    if depth > MAX_DEPTH:
        return Value.err("CycleDetected")
    name, fields, lossy = sv.v
    rt = RECORD_REGISTRY.get(name)
    if rt is None or not isinstance(rt, RecordType):
        return Value.err("UnknownType:" + name)
    if [f[0] for f in fields] != [f[0] for f in rt.fields]:
        return Value.err("FieldMismatch")
    fmap = dict(fields)
    lines = [json.dumps({"format": "TRIOREC2", "version": 2, "type": name,
                         "fields": [[fn, k] for fn, k in rt.fields],
                         "lossy": sorted(lossy)}, separators=(",", ":"))]
    for fname, kind in rt.fields:
        val = fmap[fname]
        if kind.startswith("ref:"):
            if val.t != ValueType.STRUCT:
                return Value.err("SerializeError")
            lines.append("@begin " + fname + ":" + val.v[0])
            sub = _ser2(val, depth + 1)
            if not isinstance(sub, str):
                return sub
            lines.append(sub)
            lines.append("@end " + fname)
        elif kind in ("vec", "vec:float"):
            payload = serialize_vec_payload(val)
            if payload is None:
                return Value.err("SerializeError")
            lines.extend(payload)
        else:
            tok = _value_token(val, kind)
            if tok is None:
                return Value.err("SerializeError")
            lines.append(tok)
    return "\n".join(lines)

def load_record2(text, registry=None):
    registry = registry if registry is not None else RECORD_REGISTRY
    lines = [l for l in text.split("\n") if l.strip() != ""]
    res = _read_block2(lines, 0, 1, registry)
    return res[0]

def _read_block2(lines, idx, depth, registry):
    if depth > MAX_DEPTH:
        return Value.err("CycleDetected"), idx
    if idx >= len(lines):
        return Value.err("FieldMismatch"), idx
    try:
        header = json.loads(lines[idx])
    except Exception:
        return Value.err("FieldMismatch"), idx
    if header.get("format") != "TRIOREC2":
        return Value.err("FieldMismatch"), idx
    name = header.get("type")
    rt = registry.get(name)
    if rt is None or not isinstance(rt, RecordType):
        return Value.err("UnknownType:" + str(name)), idx
    if header.get("fields") != [[f[0], k] for f, k in rt.fields]:
        return Value.err("FieldMismatch"), idx
    idx += 1
    fields = []
    lossy = {}
    for fname, kind in rt.fields:
        val, idx, err = _read_field2(lines, idx, fname, kind, depth, registry)
        if err:
            return Value.err(err), idx
        fields.append((fname, val))
    for p in header.get("lossy", []):
        lossy[p] = True
    return Value.struct(name, fields, lossy), idx

def _read_field2(lines, idx, fname, kind, depth, registry):
    if kind.startswith("ref:"):
        if idx >= len(lines) or not lines[idx].startswith("@begin "):
            return None, idx, "FieldMismatch"
        tag = lines[idx][len("@begin "):]
        if ":" not in tag:
            return None, idx, "FieldMismatch"
        fieldname, typename = tag.split(":", 1)
        if fieldname != fname:
            return None, idx, "FieldMismatch"
        idx += 1
        blk, idx = _read_block2(lines, idx, depth + 1, registry)
        if blk.t == ValueType.ERR:
            return blk, idx, None
        if blk.v[0] != typename:
            return Value.err("UnknownType:" + typename), idx, None
        if idx >= len(lines) or lines[idx] != "@end " + fname:
            return None, idx, "FieldMismatch"
        idx += 1
        return blk, idx, None
    if kind in ("vec", "vec:float"):
        if idx >= len(lines):
            return None, idx, "FieldMismatch"
        tok = lines[idx]
        idx += 1
        if not (tok.startswith("[") and tok.endswith("]")):
            return None, idx, "FieldMismatch"
        dims = [int(s) for s in tok[1:-1].split(",")]
        if not dims or any(d < 0 for d in dims) or len(dims) > 2:
            return None, idx, "FieldMismatch"
        n = dims[0] * dims[1] if len(dims) == 2 else dims[0]
        vals = []
        for _ in range(n):
            if idx >= len(lines):
                return None, idx, "FieldMismatch"
            pv = _parse_token(lines[idx])
            if pv is None or pv.t != ValueType.FLOAT:
                return None, idx, "FieldMismatch"
            idx += 1
            vals.append(pv.v)
        if len(dims) == 2:
            return Value.vec([vals[i * dims[1]:(i + 1) * dims[1]] for i in range(dims[0])]), idx, None
        return Value.vec(vals), idx, None
    if idx >= len(lines):
        return None, idx, "FieldMismatch"
    pv = _parse_token(lines[idx])
    idx += 1
    if pv is None:
        return None, idx, "FieldMismatch"
    if kind == "float" and pv.t != ValueType.FLOAT:
        return None, idx, "FieldMismatch"
    if kind == "int" and pv.t != ValueType.INT:
        return None, idx, "FieldMismatch"
    return pv, idx, None

# ============ Кодогенератор ============
def generate_model(spec):
    if not isinstance(spec, dict) or spec.get("format") != "TRIOMODEL1":
        return Value.err("SpecError")
    for t in spec.get("types", []):
        kind = t.get("kind")
        if kind == "record":
            fields = [(f["name"], "vec" if f["type"] in ("vec", "vec:float") else f["type"])
                      for f in t.get("fields", [])]
            for _, ft in fields:
                if ft not in ("int", "float", "vec") and not str(ft).startswith("ref:"):
                    return Value.err("SpecError")
            inv = {}
            for iv in t.get("invariants", []):
                inv[iv["field"]] = dict((k, v) for k, v in iv.items() if k != "field")
            rt = RecordType(t["name"], fields, inv)
            RECORD_REGISTRY[rt.name] = rt
        elif kind == "sum":
            st = SumType(t["name"], t.get("variants", []))
            RECORD_REGISTRY[st.name] = st
        else:
            return Value.err("SpecError")
    return Value.i(len(spec.get("types", [])))

def match_area(shape):
    if shape.t == ValueType.ERR:
        return shape
    name, fields, lossy = shape.v
    fmap = dict(fields)
    if name == "Circle":
        r = fmap["r"].v
        return Value.f(r * r * _PI)
    if name == "Rect":
        w, h = fmap["w"].v, fmap["h"].v
        return Value.f(w * h)
    return Value.err("UnknownVariant:" + name)

# ============ Батарея ============
def run_battery():
    tests_passed = 0
    tests_total = 89

    # T06: лексический захват (FIX-1)
    def mk_f(env_snap):
        def fn(clo_env, y):
            x1 = clo_env["x1"]
            return add(x1, y)
        return Value.clo(fn, env_snap)
    env1 = {"x1": Value.i(105), "f": mk_f({"x1": Value.i(1)})}
    res = apply_closure(env1["f"], Value.i(5))
    if res.canon() == "6":
        tests_passed += 1

    # T07: reduce с шагами
    def step(acc, x):
        return add(acc, x)
    vec = Value.vec([1.0, 2.0, 3.0, 4.0])
    r = reduce_vec(vec, Value.i(0), step)
    if r.canon() == "0x1.4000000000000p+3":
        tests_passed += 1

    # T11: narrow
    if narrow(Value.f(3.5)).canon() == "Err(PrecisionLoss)":
        tests_passed += 1

    # T12: R-INT1 ties-to-even на границе 2^53
    ok12 = True
    cases = ((2**53, "0x1.0000000000000p+53", False),
             (2**53 + 2, "0x1.0000000000001p+53", True),
             (2**53 + 3, "0x1.0000000000002p+53", True))
    for x, want, want_lossy in cases:
        JOURNAL.clear()
        w = widen(Value.i(x))
        if w.t != ValueType.FLOAT or _canon_float(w.v) != want:
            ok12 = False
            break
        entry = next((e for e in JOURNAL if e.startswith("widen")), "")
        if ("lossy=TRUE" in entry) != want_lossy:
            ok12 = False
            break
    if ok12:
        tests_passed += 1

    # T13: мост узлов
    if "mat_mul_scalar_octave" not in NODE_SPECS:
        NODE_SPECS["mat_mul_scalar_octave"] = {
            "name": "mat_mul_scalar_octave", "backend": "octave",
            "inputs": [{"name": "A", "type": "matrix", "dtype": "Float64"},
                       {"name": "k", "type": "scalar", "dtype": "Float64"}],
            "outputs": [{"name": "B", "type": "matrix", "dtype": "Float64"}],
        }
    JOURNAL.clear()
    r13 = eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.f(2.0)])
    ok13 = (r13.t == ValueType.VEC and r13.v == [[2.0, 4.0], [6.0, 8.0]]
            and "OUT B[3] = 0x1.0000000000000p+3" in JOURNAL)
    JOURNAL.clear()
    r13b = eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.vec([1.0])])
    ok13 = ok13 and r13b.t == ValueType.ERR and r13b.v == "ShapeError"
    ok13 = ok13 and any(e.startswith("IN A [2,2]") for e in JOURNAL)
    JOURNAL.clear()
    eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0]]), Value.i(2**53 + 1)])
    ok13 = ok13 and any(e.startswith("IN k[] =") and "lossy=TRUE" in e for e in JOURNAL)
    if ok13:
        tests_passed += 1

    # Реестр: Point и Shape
    if "Point" not in RECORD_REGISTRY:
        RECORD_REGISTRY["Point"] = RecordType("Point", [("x", "float"), ("y", "float")])
    if "Shape" not in RECORD_REGISTRY:
        RECORD_REGISTRY["Shape"] = SumType("Shape", [
            {"name": "Circle", "fields": [("r", "float")]},
            {"name": "Rect", "fields": [("w", "float"), ("h", "float")]},
        ])

    # T14: рекорды и сум-типы
    ok14 = True
    if _canon_float(_PI) != "0x1.921fb54442d18p+1":
        ok14 = False
    PT = RECORD_REGISTRY["Point"]
    if not struct_eq(PT.construct({"x": 1.5, "y": 2}), PT.construct({"x": 1.5, "y": 2})).v:
        ok14 = False
    if struct_eq(PT.construct({"x": 0.0, "y": 0.0}), PT.construct({"x": -0.0, "y": 0.0})).v:
        ok14 = False
    if PT.construct({"x": 1.5, "y": 2, "z": 3}).canon() != "Err(UnknownField:z)":
        ok14 = False
    if PT.construct({"x": 1.5}).canon() != "Err(MissingField:y)":
        ok14 = False
    if PT.construct({"x": Value.vec([1.0]), "y": 2}).canon() != "Err(TypeError:x)":
        ok14 = False
    JOURNAL.clear()
    pr = PT.construct({"x": 2**53 + 3, "y": 1.0})
    if not any(e.startswith("STRUCT Point.x <- int") and "lossy=TRUE" in e for e in JOURNAL):
        ok14 = False
    if pr.t != ValueType.STRUCT or pr.v[2].get("x") is not True:
        ok14 = False
    SH = RECORD_REGISTRY["Shape"]
    if match_area(SH.construct("Circle", {"r": 2})).canon() != "0x1.921fb54442d18p+3":
        ok14 = False
    if match_area(SH.construct("Rect", {"w": 2.0, "h": 2.0})).canon() != "0x1.8000000000000p+2":
        ok14 = False
    if SH.construct("Triangle", {"x": 1.0}).canon() != "Err(UnknownVariant:Triangle)":
        ok14 = False
    if ok14:
        tests_passed += 1

    # T15: TRIOREC1
    ok15 = True
    p15 = PT.construct({"x": 1.5, "y": 2.0})
    s15 = serialize_record(p15)
    if not (isinstance(s15, str) and s15.startswith('{"format":"TRIOREC1"') and '"type":"Point"' in s15):
        ok15 = False
    l15 = load_record(s15)
    if l15.t != ValueType.STRUCT or not struct_eq(l15, p15).v:
        ok15 = False
    if serialize_record(p15) != s15:
        ok15 = False
    s15n = serialize_record(PT.construct({"x": -0.0, "y": 0.0}))
    if not (isinstance(s15n, str) and "-0.0\n" in s15n):
        ok15 = False
    l15n = load_record(s15n)
    if not struct_eq(l15n, PT.construct({"x": -0.0, "y": 0.0})).v:
        ok15 = False
    if struct_eq(l15n, PT.construct({"x": 0.0, "y": 0.0})).v:
        ok15 = False
    JOURNAL.clear()
    s15l = serialize_record(PT.construct({"x": 2**53 + 3, "y": 1.0}))
    if not (isinstance(s15l, str) and '"lossy":["x"]' in s15l):
        ok15 = False
    l15l = load_record(s15l)
    if l15l.t != ValueType.STRUCT or l15l.v[2].get("x") is not True:
        ok15 = False
    if serialize_record(Value.err("X")).t != ValueType.ERR:
        ok15 = False
    fake15 = Value.struct("Point", [("a", Value.f(1.0)), ("b", Value.f(2.0))], {})
    if serialize_record(fake15).canon() != "Err(FieldMismatch)":
        ok15 = False
    if load_record(s15.replace('"type":"Point"', '"type":"Triangle"', 1)).canon() != "Err(UnknownType:Triangle)":
        ok15 = False
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
    generate_model(spec16)
    fp1 = registry_fingerprint()
    generate_model(spec16)
    fp2 = registry_fingerprint()
    ok16 = fp1 == fp2
    DOL = RECORD_REGISTRY["Dolphin"]
    if DOL.construct({"id": 7, "score": 0.98}).canon() != "{Dolphin id=7 score=0x1.f5c28f5c28f5cp-1}":
        ok16 = False
    if DOL.construct({"id": 7, "score": 150.0}).canon() != "Err(InvariantViolation:score)":
        ok16 = False
    if DOL.construct({"id": 7, "score": 100.0}).t != ValueType.STRUCT:
        ok16 = False
    JOURNAL.clear()
    pc = RECORD_REGISTRY["Pod"].construct({"capacity": 2**53 + 3})
    if not any(e.startswith("STRUCT Pod.capacity <-") and "lossy=TRUE" in e for e in JOURNAL):
        ok16 = False
    if pc.t != ValueType.STRUCT or pc.v[2].get("capacity") is not True:
        ok16 = False
    if DOL.construct({"score": 0.98}).canon() != "Err(MissingField:id)":
        ok16 = False
    if DOL.construct({"id": 7, "score": 0.98, "extra": 1}).canon() != "Err(UnknownField:extra)":
        ok16 = False
    SHg = RECORD_REGISTRY["Shape"]
    if match_area(SHg.construct("Circle", {"r": 2})).canon() != "0x1.921fb54442d18p+3":
        ok16 = False
    if SHg.construct("Triangle", {"x": 1.0}).canon() != "Err(UnknownVariant:Triangle)":
        ok16 = False
    d16 = DOL.construct({"id": 7, "score": 0.98})
    s16 = serialize_record(d16)
    if isinstance(s16, str):
        l16 = load_record(s16)
        if l16.t != ValueType.STRUCT or not struct_eq(l16, d16).v:
            ok16 = False
        if serialize_record(d16) != s16:
            ok16 = False
    else:
        ok16 = False
    if generate_model({"format": "TRIOMODEL1", "types": [{"kind": "weird", "name": "X", "fields": []}]}).canon() != "Err(SpecError)":
        ok16 = False
    if ok16:
        tests_passed += 1

    # T17: TRIOREC2 (вложенные рекорды и ref)
    spec17 = {"format": "TRIOMODEL1", "types": [
        {"kind": "record", "name": "Pod2", "fields": [{"name": "capacity", "type": "float"}]},
        {"kind": "record", "name": "Dolphin2",
         "fields": [{"name": "id", "type": "int"}, {"name": "score", "type": "float"},
                    {"name": "pod", "type": "ref:Pod2"}]},
    ]}
    generate_model(spec17)
    Pod2T = RECORD_REGISTRY["Pod2"]
    Dol2T = RECORD_REGISTRY["Dolphin2"]
    ok17 = True
    JOURNAL.clear()
    pod17 = Pod2T.construct({"capacity": 2**53 + 3})
    dol17 = Dol2T.construct({"id": 7, "score": 0.98, "pod": pod17})
    s17 = serialize_record2(dol17)
    if not (isinstance(s17, str) and '"lossy":["pod.capacity"]' in s17 and '"lossy":["capacity"]' in s17):
        ok17 = False
    if not any(e.startswith("STRUCT Pod2.capacity <-") and "lossy=TRUE" in e for e in JOURNAL):
        ok17 = False
    l17 = load_record2(s17)
    if l17.t != ValueType.STRUCT or not struct_eq(l17, dol17).v:
        ok17 = False
    if serialize_record2(dol17) != s17:
        ok17 = False
    if Dol2T.construct({"id": 7, "score": 0.98, "pod": PT.construct({"x": 1.0, "y": 2.0})}).canon() != "Err(TypeError:pod)":
        ok17 = False
    if load_record2(s17.replace('"type":"Pod2"', '"type":"Ghost"', 1)).canon() != "Err(UnknownType:Ghost)":
        ok17 = False
    if Pod2T.construct({"capacity": Value.vec([1.0])}).canon() != "Err(TypeError:capacity)":
        ok17 = False
    spec_chain = {"format": "TRIOMODEL1", "types": [
        {"kind": "record", "name": "Chain", "fields": [{"name": "next", "type": "ref:Chain"}]}]}
    generate_model(spec_chain)
    hdr = json.dumps({"format": "TRIOREC2", "version": 2, "type": "Chain",
                      "fields": [["next", "ref:Chain"]], "lossy": []}, separators=(",", ":"))
    cyc = hdr + "\n" + "\n".join(["@begin next:Chain", hdr] * 65)
    if load_record2(cyc).canon() != "Err(CycleDetected)":
        ok17 = False
    if serialize_record(dol17).t != ValueType.ERR:
        ok17 = False
    if ok17:
        tests_passed += 1

    # T18: vec-поля в TRIOREC2
    ok18 = True
    spec18 = {"format": "TRIOMODEL1", "types": [
        {"kind": "record", "name": "Pod3",
         "fields": [{"name": "observations", "type": "vec:float"}]}]}
    generate_model(spec18)
    P3 = RECORD_REGISTRY["Pod3"]
    r18a = P3.construct({"observations": Value.vec([1.0, 2.0, 3.0])})
    s18a = serialize_record2(r18a)
    if not (isinstance(s18a, str) and '"fields":[["observations","vec"]]' in s18a and "\n[3]\n" in s18a):
        ok18 = False
    l18a = load_record2(s18a)
    if l18a.t != ValueType.STRUCT or not struct_eq(l18a, r18a).v:
        ok18 = False
    if serialize_record2(r18a) != s18a:
        ok18 = False
    r18b = P3.construct({"observations": Value.vec([[1.0, 2.0], [3.0, 4.0]])})
    s18b = serialize_record2(r18b)
    if not (isinstance(s18b, str) and "\n[2,2]\n" in s18b):
        ok18 = False
    if not struct_eq(load_record2(s18b), r18b).v:
        ok18 = False
    JOURNAL.clear()
    r18c = P3.construct({"observations": Value.vec([1, 2**53 + 3])})
    if r18c.t != ValueType.STRUCT or r18c.v[2].get("observations") is not True:
        ok18 = False
    if not any(e.startswith("STRUCT Pod3.observations[1] <- int") and "lossy=TRUE" in e for e in JOURNAL):
        ok18 = False
    s18c = serialize_record2(r18c)
    if not (isinstance(s18c, str) and '"lossy":["observations"]' in s18c):
        ok18 = False
    l18c = load_record2(s18c)
    if l18c.t != ValueType.STRUCT or "observations" not in l18c.v[2]:
        ok18 = False
    r18d = P3.construct({"observations": Value.vec([])})
    s18d = serialize_record2(r18d)
    if not (isinstance(s18d, str) and "\n[0]" in s18d):
        ok18 = False
    if not struct_eq(load_record2(s18d), r18d).v:
        ok18 = False
    fake18 = Value.struct("Pod3", [("observations", Value.vec([Value.struct("Pod3", [], {})]))], {})
    se = serialize_record2(fake18)
    if not (isinstance(se, Value) and se.t == ValueType.ERR):
        ok18 = False
    bad = '{"format":"TRIOREC2","version":2,"type":"Pod3","fields":[["observations","vec"]],"lossy":[]}\n[3]\n0x1.0000000000000p+0\n0x1.0000000000000p+1'
    if load_record2(bad).canon() != "Err(FieldMismatch)":
        ok18 = False
    if serialize_record(r18a).t != ValueType.ERR:
        ok18 = False
    if P3.construct({"observations": Value.f(1.0)}).canon() != "Err(TypeError:observations)":
        ok18 = False
    if ok18:
        tests_passed += 1

    print("Battery: " + str(tests_passed) + "/" + str(tests_total))
    return tests_passed == tests_total

if __name__ == "__main__":
    ok = run_battery()
    print("OK" if ok else "FAIL")
