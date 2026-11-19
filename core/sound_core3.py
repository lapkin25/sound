# sound_core3.py — v0.5
# Оригинал v0.3 + FIX-1..FIX-5 + Trio Bridge + T12/T13
from enum import IntEnum
import math

class ValueType(IntEnum):
    INT = 0
    FLOAT = 1
    BOOL = 2
    VEC = 3
    CLOSURE = 4
    ERR = 5

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
        return "?"

# Канонический журнал: входы, выходы, флаги. Всё, что течёт через мост, обязано здесь быть.
JOURNAL = []

def _canon_float(x):
    # Канон: мантисса добита до 13 hex-цифр, знак порядка обязателен.
    # float.hex() даёт минимальную мантиссу ('0x1.4p+3') — добиваем сами.
    if math.isnan(x):
        return "nan"                # TODO(v0.6): payload NaN
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
    mant, exp = h.split("p")        # exp всегда со знаком в float.hex()
    int_part, _, frac = mant.partition(".")
    frac = (frac + "0" * 13)[:13]
    return f"{sign}0x{int_part}.{frac}p{exp}"

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
        # IEEE: inf / -inf / nan
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
    # env — это dict: name -> Value (снимок на момент создания замыкания)
    return fn(env, arg)

# reduce: явный аккумулятор, шаги видны в trace
def reduce_vec(vec_val, acc_val, step_fn):
    if vec_val.t == ValueType.ERR: return vec_val
    if acc_val.t == ValueType.ERR: return acc_val
    xs = vec_val.v
    acc = acc_val
    for x in xs:
        acc = step_fn(acc, Value.f(x))  # x как float для шага
    return acc

# Статические проверки (SC-коды)
def static_check(term, env_names):
    # SC-002: все имена определены
    def walk(node, params):
        if isinstance(node, tuple):
            tag = node[0]
            if tag == "let":
                _, name, body, nxt = node
                new_params = params + [name]
                if name in params:
                    pass  # легальное теневание
                return walk(body, new_params) and walk(nxt, new_params)
            elif tag == "var":
                _, name = node
                return name in params  # SC-002
            elif tag == "app":
                _, f, x = node
                return walk(f, params) and walk(x, params)
            elif tag == "if":
                _, c, t, e = node
                return walk(c, params) and walk(t, params) and walk(e, params)
            elif tag == "fun":
                _, ps, body = node
                if len(set(ps)) != len(ps):
                    return False  # SC-060: дубли параметров
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

# ============================================================
# Trio Bridge: узлы. Точки склейки — диспетчер и маппинг значений.
# ============================================================
import json
import os

class NodeError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(f"Err({code}): {message}")

NODE_SPECS = {}

def load_manifest(path=None):
    # Спеки узлов подхватываются из nodes/manifest.json, если он есть рядом
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
        if v.v and isinstance(v.v[0], list):
            r, c = len(v.v), len(v.v[0])
            vals = [float(x) for row in v.v for x in row]
            JOURNAL.append(f"IN {name} [{r},{c}] = " +
                           " ".join(_canon_float(x) for x in vals))
            return {"dtype": "Float64", "shape": [r, c], "values": vals, "lossy": False}
        vals = [float(x) for x in v.v]
        JOURNAL.append(f"IN {name} [{len(vals)}] = " +
                       " ".join(_canon_float(x) for x in vals))
        return {"dtype": "Float64", "shape": [len(vals)], "values": vals, "lossy": False}
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
    # Эмуляция той же арифметики, что в run_mat_mul_scalar_octave.m.
    # Тот же протокол ошибок, что у настоящего бэкенда.
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
    # План: записать входы в <name>.triomat, запустить
    #   subprocess.run(["octave", "--no-gui", "--quiet", f"run_{spec['name']}.m"], cwd=workdir)
    # прочитать выходы из TRIOMAT1. Закрывается на целевой машине.
    raise NodeError("ProcessError", "real octave backend not wired yet (OPEN gate)")

def run_node(spec, inputs, backend, workdir="."):
    # Возвращает (outputs | None, err | None). Ошибки — как значения.
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
            return None, ("TypeError",
                          f'output "{name}": dtype={payload["dtype"]}, expected {io["dtype"]}')
        outs = from_triomat_value(payload)
        flat = ([x for row in outs.v for x in row] if outs.v and isinstance(outs.v[0], list)
                else outs.v if isinstance(outs.v, list) else [outs.v])
        JOURNAL.extend(f"OUT {name}[{i}] = {_canon_float(x)}" for i, x in enumerate(flat))
        outputs[name] = outs
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
# Батарея тестов (89 в полной версии; здесь — 5 реализованных)
# ============================================================
def run_battery():
    tests_passed = 0
    tests_total = 89

    # T06: лексический захват
    # FIX-1: замыкание вызывается штатным apply_closure, а не f.v[1](env, ...)
    def mk_f(env_snap):
        def fn(clo_env, y):
            x1 = clo_env["x1"]  # снимок на момент создания замыкания
            return add(x1, y)
        return Value.clo(fn, env_snap)  # FIX-1: снимок живёт в замыкании
    env1 = {"x1": Value.i(105), "f": mk_f({"x1": Value.i(1)})}
    res = apply_closure(env1["f"], Value.i(5))
    if res.canon() == "6":
        tests_passed += 1

    # T07: reduce с шагами
    def step(acc, x):
        return add(acc, x)
    vec = Value.vec([1.0, 2.0, 3.0, 4.0])
    r = reduce_vec(vec, Value.i(0), step)
    if r.canon() == "0x1.4000000000000p+3":  # 10.0
        tests_passed += 1

    # T11: narrow с ошибкой (теперь по смыслу, а не случайно — см. FIX-2)
    r = narrow(Value.f(3.5))
    if r.canon() == "Err(PrecisionLoss)":
        tests_passed += 1

    # T12: R-INT1 ties-to-even на границе 2^53
    # 2^53      -> точно, lossy=FALSE
    # 2^53 + 2  -> за границей, но точно; lossy=TRUE
    # 2^53 + 3  -> ровно посередине между 2^53+2 и 2^53+4:
    #              ties-to-even поднимает к чётной мантиссе (...2).
    #              Обрубание (старый BigInteger->double в C#) дало бы (...1).
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

    # T13: мост узлов — рабочий путь, путь ошибки, R-INT1 на входе узла
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
    ok13 = (r.t == ValueType.VEC and r.v == [[2.0, 4.0], [6.0, 8.0]]
            and "OUT B[3] = 0x1.0000000000000p+3" in JOURNAL)

    # Путь ошибки: вектор вместо скаляра. Ошибка — значение,
    # журнал входа A сохранён до сбоя.
    JOURNAL.clear()
    r2 = eval_node_call("mat_mul_scalar_octave",
                        [Value.vec([[1.0, 2.0], [3.0, 4.0]]), Value.vec([1.0])])
    ok13 = ok13 and r2.t == ValueType.ERR and r2.v == "ShapeError"
    ok13 = ok13 and any(e.startswith("IN A [2,2]") for e in JOURNAL)

    # R-INT1 на входе узла: флаг lossy обязан быть виден в журнале
    JOURNAL.clear()
    eval_node_call("mat_mul_scalar_octave",
                   [Value.vec([[1.0]]), Value.i(2**53 + 1)])
    ok13 = ok13 and any(e.startswith("IN k[] =") and "lossy=TRUE" in e for e in JOURNAL)
    if ok13:
        tests_passed += 1

    print(f"Battery: {tests_passed}/{tests_total}")
    return tests_passed == tests_total

if __name__ == "__main__":
    ok = run_battery()
    print("OK" if ok else "FAIL")
