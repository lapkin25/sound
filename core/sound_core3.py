# sound_core3.py — v0.8 (кодогенератор моделей)
# Оригинал v0.3 + FIX-1..FIX-5 + Trio Bridge (T13) + структурные типы (T14)
# + TRIOREC1 (T15) + кодогенератор моделей из JSON-спеки (T16)
from enum import IntEnum
import math, json, os

_PI = float.fromhex("0x1.921fb54442d18p+1")   # pi зафиксирована битами, не рантаймом

class ValueType(IntEnum):
    INT = 0
    FLOAT = 1
    BOOL = 2
    VEC = 3
    CLOSURE = 4
    ERR = 5
    STRUCT = 6

VT = ValueType

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
        return Value(ValueType.STRUCT, (name, fields, lossy or []))

    def canon(self):
        if self.t == ValueType.INT:
            return str(self.v)
        if self.t == ValueType.FLOAT:
            return _canon_float(self.v)
        if self.t == ValueType.BOOL:
            return "true" if self.v else "false"
        if self.t == ValueType.VEC:
            return "[" + ",".join(str(x) for x in self.v) + "]"
        if self.t == ValueType.CLOSURE:
            return "<closure>"
        if self.t == ValueType.ERR:
            return f"Err({self.v})"
        if self.t == ValueType.STRUCT:
            return canon_val(self)
        return "?"

# Канонический журнал: входы, выходы, флаги. Всё, что течёт через мост, обязано здесь быть.
JOURNAL = []

def _canon_float(x):
    # Канон: мантисса добита до 13 hex-цифр, знак порядка обязателен.
    if math.isnan(x):
        return "nan"                # TODO(v0.9): payload NaN
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

def _parse_canon(s):
    if s == "inf": return math.inf
    if s == "-inf": return -math.inf
    if s == "nan": return math.nan
    try:
        return float(s)             # десятичные токены: 0.0, -0.0
    except ValueError:
        return float.fromhex(s)     # канонический hex

def widen(v):
    # R-INT1: неограниченное целое -> double; за границей 2^53 — флаг lossy в журнал.
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

# Лексический захват: снимок окружения
def make_closure(fn, env_snapshot):
    return Value.clo(fn, env_snapshot)

def apply_closure(v, arg):
    if v.t == ValueType.ERR: return v
    if v.t != ValueType.CLOSURE:
        return Value.err("ApplyOnNonClosure")
    fn, env = v.v
    return fn(env, arg)

# reduce: явный аккумулятор, шаги видны в trace
def reduce_vec(vec_val, acc_val, step_fn):
    if vec_val.t == ValueType.ERR: return vec_val
    if acc_val.t == ValueType.ERR: return acc_val
    acc = acc_val
    for x in vec_val.v:
        acc = step_fn(acc, Value.f(x))
    return acc

# Статические проверки (SC-коды)
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
                return (walk(node[1], params) and walk(node[2], params)
                        and walk(node[3], params))
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
# Trio Bridge: узлы
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
    if v.t in (VT.INT, VT.FLOAT) and dtype == "Float64":
        if v.t == VT.INT:
            lossy = abs(v.v) > 2**53
            x = float(v.v)
        else:
            lossy, x = False, float(v.v)
        JOURNAL.append(f"IN {name}[] = {_canon_float(x)}" + (" lossy=TRUE" if lossy else ""))
        return {"dtype": dtype, "shape": [], "values": [x], "lossy": lossy}
    if v.t == VT.INT and dtype == "Int64":
        JOURNAL.append(f"IN {name}[] = {int(v.v)}")
        return {"dtype": dtype, "shape": [], "values": [int(v.v)], "lossy": False}
    if v.t == VT.VEC:
        if v.v and isinstance(v.v[0], list):
            r, c = len(v.v), len(v.v[0])
            vals = [float(x) for row in v.v for x in row]
            JOURNAL.append(f"IN {name} [{r},{c}] = " + " ".join(_canon_float(x) for x in vals))
            return {"dtype": "Float64", "shape": [r, c], "values": vals, "lossy": False}
        vals = [float(x) for x in v.v]
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
    # OPEN-гейт: subprocess.run(["octave", "--no-gui", "--quiet", ...], cwd=workdir)
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
            return None, ("TypeError", f'output "{name}": wrong dtype')
        outs = from_triomat_value(payload)
        flat = ([x for row in outs.v for x in row] if outs.v and isinstance(outs.v[0], list)
                else outs.v if isinstance(outs.v, list) else [outs.v])
        JOURNAL.extend(f"OUT {name}[{i}] = {_canon_float(x)}" for i, x in enumerate(flat))
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

# ============================================================
# Структурные типы: рекорды и сум-типы (T14)
# ============================================================
RECORD_REGISTRY = {}

def canon_val(v):
    if v.t == VT.STRUCT:
        name, fields, _ = v.v
        body = " ".join(f"{fn}={canon_val(fv)}" for fn, fv in fields)
        return "{" + f"{name} {body}" + "}"
    if v.t == VT.VEC:
        return "[" + ",".join(canon_val(x) if isinstance(x, Value) else _canon_float(x)
                              for x in v.v) + "]"
    return v.canon()

def struct_eq(a, b):
    # Равенство ПОБИТОВОЕ по канону: -0.0 и 0.0 различаются.
    if a.t != b.t:
        return Value.b(False)
    if a.t == VT.STRUCT:
        (n1, f1, _), (n2, f2, _) = a.v, b.v
        if n1 != n2 or len(f1) != len(f2):
            return Value.b(False)
        for (na, va), (nb, vb) in zip(f1, f2):
            if na != nb:
                return Value.b(False)
            if canon_val(va) != canon_val(vb):
                return Value.b(False)
        return Value.b(True)
    return Value.b(a.canon() == b.canon())

class RecordType:
    def __init__(self, name, fields, invariants=None):
        self.name = name
        self.fields = fields                # [(fname, kind)] — порядок из определения = канон
        self.invariants = invariants or []

    def construct(self, args):
        extra = set(args) - {f[0] for f in self.fields}
        if extra:
            return Value.err("UnknownField:" + ",".join(sorted(extra)))
        checked, lossy = [], []
        for fname, kind in self.fields:
            if fname not in args:
                return Value.err("MissingField:" + fname)
            v = args[fname]
            if kind == "float":
                if v.t == VT.INT:
                    # R-INT1 в поле рекорда: журналируется, флаг не теряется (урок T13)
                    lossy_flag = abs(v.v) > 2**53
                    x = float(v.v)
                    JOURNAL.append(f"STRUCT {self.name}.{fname} <- int {v.v} -> {_canon_float(x)}"
                                   + (" lossy=TRUE" if lossy_flag else ""))
                    v = Value.f(x)
                    if lossy_flag:
                        lossy.append(fname)
                elif v.t != VT.FLOAT:
                    return Value.err("TypeError:" + fname)
            elif kind == "int":
                if v.t != VT.INT:
                    return Value.err("TypeError:" + fname)
            elif kind == "bool":
                if v.t != VT.BOOL:
                    return Value.err("TypeError:" + fname)
            elif kind == "vec":
                if v.t != VT.VEC:
                    return Value.err("TypeError:" + fname)
            checked.append((fname, v))
        # Инварианты — предикаты из спеки, ошибки как значения
        d = dict(checked)
        for inv in self.invariants:
            fname = inv.get("field")
            val = d.get(fname)
            if val is None:
                continue
            if val.t not in (VT.INT, VT.FLOAT):
                return Value.err("TypeError:" + fname)
            x = float(val.v)
            if "min" in inv and x < float(inv["min"]):
                return Value.err("InvariantViolation:" + fname)
            if "max" in inv and x > float(inv["max"]):
                return Value.err("InvariantViolation:" + fname)
        return Value(VT.STRUCT, (self.name, checked, lossy))

class SumType:
    def __init__(self, name, variants):
        self.name = name
        self.variants = variants            # [(tag, [(fname, kind)])]

    def construct(self, tag, args):
        for t, fields in self.variants:
            if t == tag:
                rt = RecordType(f"{self.name}.{tag}", fields)
                r = rt.construct(args)
                if r.t == VT.STRUCT:
                    _, checked, lossy = r.v
                    return Value(VT.STRUCT, (f"{self.name}.{tag}", checked, lossy))
                return r
        return Value.err("UnknownVariant:" + tag)

def match_area(v):
    # Явная диспетчеризация по тегу — вместо виртуальных таблиц
    if v.t == VT.STRUCT:
        name, fields, _ = v.v
        d = dict(fields)
        if name == "Shape.Circle":
            return mul(Value.f(_PI), mul(d["r"], d["r"]))
        if name == "Shape.Rect":
            return mul(d["w"], d["h"])
        return Value.err("UnknownVariant:" + name.split(".")[-1])
    return Value.err("TypeError")

# ============================================================
# TRIOREC1: сериализация рекордов (T15)
# ============================================================
def serialize_record(v):
    if v.t != VT.STRUCT:
        return None, ("SerializeError", "only structures can be serialized")
    name, fields, lossy = v.v
    rt = RECORD_REGISTRY.get(name)
    if rt is None:
        return None, ("UnknownType:" + name, "type not in registry")
    if not isinstance(rt, RecordType):
        return None, ("SerializeError", "sum type variants serialize under their RecordType")
    if [fn for fn, _ in fields] != [fn for fn, _ in rt.fields]:
        return None, ("FieldMismatch", f"{name}: fields differ from spec")
    header = {"format": "TRIOREC1", "version": 1, "type": name,
              "fields": [[fn, k] for fn, k in rt.fields], "lossy": sorted(lossy)}
    lines = [json.dumps(header, separators=(",", ":"))]
    for fn, fv in fields:
        if fv.t == VT.ERR:
            return None, ("SerializeError", f"field {fn} holds an error")
        if fv.t in (VT.STRUCT, VT.VEC):
            return None, (f"SerializeError", f"field {fn}: nested payload needs TRIOREC2 (OPEN gate)")
        lines.append(fv.canon())
    return "\n".join(lines), None

def load_record(text):
    try:
        lines = text.strip().split("\n")
        header = json.loads(lines[0])
    except Exception:
        return None, ("FormatError", "invalid TRIOREC1 header")
    if header.get("format") != "TRIOREC1" or header.get("version") != 1:
        return None, ("FormatError", "expected TRIOREC1 version 1")
    rt = RECORD_REGISTRY.get(header.get("type"))
    if rt is None:
        return None, ("UnknownType:" + str(header.get("type")), "type not in registry")
    if [fn for fn, _ in rt.fields] != [fn for fn, _ in header.get("fields", [])]:
        return None, ("FieldMismatch", "header fields differ from registry")
    vals = lines[1:]
    if len(vals) != len(rt.fields):
        return None, ("FieldMismatch", "payload arity differs from header")
    lossy_set = set(header.get("lossy", []))
    if not lossy_set <= {fn for fn, _ in rt.fields}:
        return None, ("FieldMismatch", "lossy flag for unknown field")
    checked = []
    for (fn, kind), raw in zip(rt.fields, vals):
        try:
            if kind == "float":
                fv = Value.f(_parse_canon(raw))
            elif kind == "int":
                fv = Value.i(int(raw))
            elif kind == "bool":
                fv = Value.b(raw == "true")
            else:
                return None, ("SerializeError", f"field kind {kind} needs TRIOREC2")
        except ValueError:
            return None, ("FormatError", f"bad canon value for field {fn}")
        checked.append((fn, fv))
    return Value(VT.STRUCT, (header["type"], checked, sorted(lossy_set))), None

# ============================================================
# Кодогенератор моделей предметных областей (T16)
# ============================================================
def generate_model(manifest):
    """JSON-спека -> RecordType/SumType, зарегистрированные в реестре.
    Порядок полей из спеки = канонический порядок сериализации.
    Инварианты из спеки становятся проверками конструктора."""
    if not isinstance(manifest, dict) or "types" not in manifest:
        return None, ("SpecError", 'expected {"types": [...]}')
    for t in manifest["types"]:
        kind = t.get("kind", "record")
        name = t.get("name")
        if not name:
            return None, ("SpecError", "type without name")
        if kind == "record":
            fields = [(f["name"], f.get("type", "float")) for f in t.get("fields", [])]
            rt = RecordType(name, fields, t.get("invariants", []))
        elif kind == "sum":
            variants = [(v["name"],
                         [(f["name"], f.get("type", "float")) for f in v.get("fields", [])])
                        for v in t.get("variants", [])]
            rt = SumType(name, variants)
        else:
            return None, ("SpecError", f"unknown kind: {kind}")
        RECORD_REGISTRY[name] = rt
    return len(RECORD_REGISTRY), None

def registry_canon():
    """Отпечаток реестра: одинаковые спеки -> одинаковый отпечаток (golden для кодогена)."""
    parts = []
    for name in sorted(RECORD_REGISTRY):
        rt = RECORD_REGISTRY[name]
        if isinstance(rt, RecordType):
            fs = ".".join(f"{fn}:{k}" for fn, k in rt.fields)
            parts.append(f"{name}({fs})")
        else:
            vs = "|".join(f"{tag}({'.'.join(f'{fn}:{k}' for fn, k in f)})"
                          for tag, f in rt.variants)
            parts.append(f"{name}[{vs}]")
    return "|".join(parts)

# ============================================================
# Батарея (89 в полной версии; здесь — 8 реализованных)
# ============================================================
def run_battery():
    tests_passed = 0
    tests_total = 89

    # T06: лексический захват (FIX-1)
    def mk_f(env_snap):
        def fn(clo_env, y):
            return add(clo_env["x1"], y)   # снимок на момент создания замыкания
        return Value.clo(fn, env_snap)
    env1 = {"x1": Value.i(105), "f": mk_f({"x1": Value.i(1)})}
    res = apply_closure(env1["f"], Value.i(5))
    if res.canon() == "6":
        tests_passed += 1

    # T07: reduce с шагами
    def step(acc, x):
        return add(acc, x)
    r = reduce_vec(Value.vec([1.0, 2.0, 3.0, 4.0]), Value.i(0), step)
    if r.canon() == "0x1.4000000000000p+3":  # 10.0
        tests_passed += 1

    # T11: narrow с ошибкой (FIX-2)
    if narrow(Value.f(3.5)).canon() == "Err(PrecisionLoss)":
        tests_passed += 1

    # T12: R-INT1 ties-to-even на границе 2^53
    cases = ((2**53,     "0x1.0000000000000p+53", False),
             (2**53 + 2, "0x1.0000000000001p+53", True),
             (2**53 + 3, "0x1.0000000000002p+53", True))
    for x, want, want_lossy in cases:
        JOURNAL.clear()
        w = widen(Value.i(x))
        if w.t != VT.FLOAT or _canon_float(w.v) != want:
            break
        entry = next((e for e in JOURNAL if e.startswith("widen")), "")
        if ("lossy=TRUE" in entry) != want_lossy:
            break
    else:
        tests_passed += 1

    # T13: мост узлов — рабочий путь, путь ошибки, R-INT1 на входе
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
    JOURNAL.clear()
    r = eval_node_call("mat_mul_scalar_octave",
                       [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.f(2.0)])
    ok13 = (r.t == VT.VEC and r.v == [[2.0, 4.0], [6.0, 8.0]]
            and "OUT B[3] = 0x1.0000000000000p+3" in JOURNAL)
    JOURNAL.clear()
    r2 = eval_node_call("mat_mul_scalar_octave",
                        [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.vec([1.0])])
    ok13 = ok13 and r2.t == VT.ERR and r2.v == "ShapeError"
    ok13 = ok13 and any(e.startswith("IN A [2,2]") for e in JOURNAL)
    JOURNAL.clear()
    eval_node_call("mat_mul_scalar_octave", [Value.vec([[1.0]]), Value.i(2**53 + 1)])
    ok13 = ok13 and any(e.startswith("IN k[] =") and "lossy=TRUE" in e for e in JOURNAL)
    if ok13:
        tests_passed += 1

    # T14: рекорды, сум-типы, побитовое равенство
    P = RecordType("Point", [("x", "float"), ("y", "float")])
    p1 = P.construct({"x": Value.f(1.5), "y": Value.i(2)})
    ok14 = p1.t == VT.STRUCT
    ok14 = ok14 and canon_val(p1) == "{Point x=0x1.8000000000000p+0 y=0x1.0000000000000p+1}"
    p2 = P.construct({"y": Value.i(2), "x": Value.f(1.5)})   # порядок аргументов не важен
    ok14 = ok14 and struct_eq(p1, p2).canon() == "true"
    pa = P.construct({"x": Value.f(-0.0), "y": Value.f(0.0)})
    pb = P.construct({"x": Value.f(0.0), "y": Value.f(0.0)})
    ok14 = ok14 and struct_eq(pa, pb).canon() == "false"     # -0.0 != 0.0 побитово
    ok14 = ok14 and P.construct({"x": Value.f(1.0), "y": Value.i(2), "z": Value.i(3)}).canon() == "Err(UnknownField:z)"
    ok14 = ok14 and P.construct({"x": Value.f(1.0)}).canon() == "Err(MissingField:y)"
    ok14 = ok14 and P.construct({"x": Value.b(True), "y": Value.i(2)}).canon() == "Err(TypeError:x)"
    JOURNAL.clear()
    pc = P.construct({"x": Value.i(2**53 + 1), "y": Value.f(0.0)})
    ok14 = ok14 and pc.v[2] == ["x"]
    ok14 = ok14 and any(e.startswith("STRUCT Point.x") and "lossy=TRUE" in e for e in JOURNAL)
    Shape = SumType("Shape", [("Circle", [("r", "float")]),
                              ("Rect", [("w", "float"), ("h", "float")])])
    cir = Shape.construct("Circle", {"r": Value.f(2.0)})
    ok14 = ok14 and match_area(cir).canon() == "0x1.921fb54442d18p+3"
    rec = Shape.construct("Rect", {"w": Value.f(3.0), "h": Value.f(2.0)})
    ok14 = ok14 and match_area(rec).canon() == "0x1.8000000000000p+2"
    tri = Shape.construct("Triangle", {"r": Value.f(1.0)})
    ok14 = ok14 and tri.canon() == "Err(UnknownVariant:Triangle)"
    ok14 = ok14 and _PI.hex() == "0x1.921fb54442d18p+1"      # пин pi
    ok14 = ok14 and canon_val(p1) == canon_val(P.construct({"x": Value.f(1.5), "y": Value.i(2)}))
    if ok14:
        tests_passed += 1

    # T15: TRIOREC1
    RECORD_REGISTRY["Point"] = RecordType("Point", [("x", "float"), ("y", "float")])
    p1 = Value.struct("Point", [("x", Value.f(1.5)), ("y", Value.f(2.0))])
    s1, e1 = serialize_record(p1)
    ok15 = e1 is None
    l1, e2 = load_record(s1)
    ok15 = ok15 and e2 is None and struct_eq(l1, p1).canon() == "true"
    s2, _ = serialize_record(p1)
    ok15 = ok15 and s2 == s1                                  # детерминизм файлов
    pm = Value.struct("Point", [("x", Value.f(-0.0)), ("y", Value.f(0.0))])
    sm, em = serialize_record(pm)
    ok15 = ok15 and em is None and "-0.0\n" in sm             # минус ноль едет как есть
    lmp, em2 = load_record(sm)
    ok15 = ok15 and em2 is None and struct_eq(lmp, pm).canon() == "true"
    ok15 = ok15 and struct_eq(lmp, Value.struct("Point", [("x", Value.f(0.0)), ("y", Value.f(0.0))])).canon() == "false"
    pl = RECORD_REGISTRY["Point"].construct({"x": Value.i(2**53 + 3), "y": Value.f(0.0)})
    sl, el = serialize_record(pl)
    ok15 = ok15 and el is None and '"lossy":["x"]' in sl
    ll, el2 = load_record(sl)
    ok15 = ok15 and el2 is None and ll.v[2] == ["x"]          # флаг возвращается из файла
    tri_s = Value.struct("Triangle", [("a", Value.f(1.0))])
    ok15 = ok15 and serialize_record(tri_s)[1][0] == "UnknownType:Triangle"
    ok15 = ok15 and serialize_record(Value.i(1))[1][0] == "SerializeError"
    bad = Value.struct("Point", [("x", Value.f(1.0))])
    ok15 = ok15 and serialize_record(bad)[1][0] == "FieldMismatch"
    if ok15:
        tests_passed += 1

    # T16: кодогенератор моделей из JSON-спеки
    def dolphin_spec():
        return {
            "format": "TRIOMODEL1",
            "types": [
                {"kind": "record", "name": "Dolphin",
                 "fields": [{"name": "id", "type": "int"},
                            {"name": "score", "type": "float"}],
                 "invariants": [{"field": "score", "min": 0.0, "max": 100.0}]},
                {"kind": "record", "name": "Pod",
                 "fields": [{"name": "capacity", "type": "float"}]},
                {"kind": "sum", "name": "Shape",
                 "variants": [
                     {"name": "Circle", "fields": [{"name": "r", "type": "float"}]},
                     {"name": "Rect", "fields": [{"name": "w", "type": "float"},
                                                 {"name": "h", "type": "float"}]},
                 ]},
            ],
        }

    generate_model(dolphin_spec())
    canon_a = registry_canon()
    generate_model(dolphin_spec())
    ok16 = canon_a == registry_canon()                        # два прогона — идентичный реестр
    ok16 = ok16 and "Dolphin(id:int.score:float)" in canon_a
    ok16 = ok16 and "Shape[Circle(r:float)|Rect(w:float.h:float)]" in canon_a

    D = RECORD_REGISTRY["Dolphin"]
    d1 = D.construct({"id": Value.i(7), "score": Value.f(0.98)})
    ok16 = ok16 and d1.t == VT.STRUCT
    ok16 = ok16 and canon_val(d1) == "{Dolphin id=7 score=%s}" % _canon_float(0.98)
    # инвариант из спеки -> ошибка как значение
    ok16 = ok16 and D.construct({"id": Value.i(7), "score": Value.f(150.0)}).canon() == "Err(InvariantViolation:score)"
    ok16 = ok16 and D.construct({"id": Value.i(7), "score": Value.f(100.0)}).t == VT.STRUCT  # граница включена
    # R-INT1 на поле сгенерированного типа без инвариантов
    # (у Dolphin.score стоит инвариант max=100 — модель честно отсекает 2^53+3 ДО потери точности)
    JOURNAL.clear()
    Pod = RECORD_REGISTRY["Pod"]
    d3 = Pod.construct({"capacity": Value.i(2**53 + 3)})
    ok16 = ok16 and d3.t == VT.STRUCT and d3.v[2] == ["capacity"]
    ok16 = ok16 and any(e.startswith("STRUCT Pod.capacity") and "lossy=TRUE" in e for e in JOURNAL)
    ok16 = ok16 and "Pod(capacity:float)" in canon_a
    # Err-пути конструктора
    ok16 = ok16 and D.construct({"id": Value.i(1)}).canon() == "Err(MissingField:score)"
    ok16 = ok16 and D.construct({"id": Value.i(1), "score": Value.f(1.0), "w": Value.i(2)}).canon() == "Err(UnknownField:w)"
    ok16 = ok16 and D.construct({"id": Value.f(1.5), "score": Value.f(1.0)}).canon() == "Err(TypeError:id)"
    # сум-тип из спеки + диспетчеризация
    S = RECORD_REGISTRY["Shape"]
    c1 = S.construct("Circle", {"r": Value.f(2.0)})
    ok16 = ok16 and canon_val(c1) == "{Shape.Circle r=0x1.0000000000000p+1}"
    ok16 = ok16 and S.construct("Triangle", {"r": Value.f(1.0)}).canon() == "Err(UnknownVariant:Triangle)"
    ok16 = ok16 and match_area(c1).canon() == "0x1.921fb54442d18p+3"
    # roundtrip сгенерированного типа + lossy персистится
    sd, ed = serialize_record(d3)
    ok16 = ok16 and ed is None and '"lossy":["capacity"]' in sd
    ld, ed2 = load_record(sd)
    ok16 = ok16 and ed2 is None and struct_eq(ld, d3).canon() == "true"
    sd2, _ = serialize_record(d3)
    ok16 = ok16 and sd2 == sd                                 # детерминизм кодогена
    if ok16:
        tests_passed += 1

    print(f"Battery: {tests_passed}/{tests_total}")
    return tests_passed == tests_total

if __name__ == "__main__":
    ok = run_battery()
    print("OK" if ok else "FAIL")
