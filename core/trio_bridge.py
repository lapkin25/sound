
# trio_bridge.py — reference-реализация TTB-Spec v0.1, приведённая к канону TRIOMAT1
import struct, json
import numpy as np
from enum import Enum

LIM = 2**53  # граница точного представления int в double

TrioError = Enum("TrioError", {
    # закрытый набор — TTB-Spec v0.1, раздел 7
    "TypeMismatch": "TypeMismatch",
    "ShapeError": "ShapeError",
    "DomainError": "DomainError",
    "IntRangeOverflow": "IntRangeOverflow",
    "FractionalInt": "FractionalInt",
    "NoCoercion": "NoCoercion",
    "EncodingFault": "EncodingFault",
    "NaNAsMissing": "NaNAsMissing",
    "SentinelDetected": "SentinelDetected",
    "LayoutMismatch": "LayoutMismatch",
    "MissingField": "MissingField",
    "HeterogeneousMatrix": "HeterogeneousMatrix",
    "NullPointer": "NullPointer",
    "UnsupportedStreaming": "UnsupportedStreaming",
    "ResourceLost": "ResourceLost",
    "UndefinedBridge": "UndefinedBridge",
    # транспортные коды TRIOMAT1 (вне закрытого набора — см. отчёт сверки)
    "MalformedHeader": "MalformedHeader",
    "TypeError": "TypeError",
    "BoolPayload": "BoolPayload",
})

class OK:
    def __init__(self, value=None, warnings=None):
        self.value = value
        self.warnings = list(warnings or [])

class Lossy:
    def __init__(self, tag, value=None, warnings=None):
        self.tag = tag
        self.value = value
        self.warnings = list(warnings or [])

class Err:
    def __init__(self, error, warnings=None):
        self.error = error
        self.warnings = list(warnings or [])

class MType:
    def __init__(self, name, shape, domain="strict"):
        self.name = name
        self.shape = tuple(shape)
        self.domain = domain

# Заглавные однобуквенные C/F — layout-маркеры (интерпретация, в спеке не описана)
def _marker(x):
    return isinstance(x, str) and x in ("C", "F")

def _dimvar(x):
    return isinstance(x, str) and x != "?" and not _marker(x)

# R-DIM3/5/6/7: унификация DimVar по имени, "?" фиксируется первым значением
def unify(a, b):
    a, b = list(a), list(b)
    if len(a) != len(b):
        return Err(TrioError.ShapeError)
    env, qn = {}, 0
    for x, y in zip(a, b):
        if _marker(x) or _marker(y):
            continue
        if x == "?" and isinstance(y, int):
            env["?%d" % qn] = y; qn += 1; continue
        if y == "?" and isinstance(x, int):
            env["?%d" % qn] = x; qn += 1; continue
        if isinstance(x, int) and isinstance(y, int):
            if x != y:
                return Err(TrioError.ShapeError)
            continue
        if _dimvar(x) and _dimvar(y):
            if x != y:
                return Err(TrioError.ShapeError)
            continue
        if isinstance(x, int) and _dimvar(y):
            if env.get(y, x) != x:
                return Err(TrioError.ShapeError)
            env[y] = x; continue
        if isinstance(y, int) and _dimvar(x):
            if env.get(x, y) != y:
                return Err(TrioError.ShapeError)
            env[x] = y; continue
        return Err(TrioError.ShapeError)
    return OK(env)

def check_widening(a, b):
    if len(a.shape) != len(b.shape):
        return Err(TrioError.ShapeError)
    for x, y in zip(a.shape, b.shape):
        if y == "?" and x != "?":
            return Err(TrioError.ShapeError)  # R-DIM6: ослабление только через generalize
    if a.name == "Float64" and b.name == "Float32":
        return Lossy("precision")  # R-FLT3
    if a.name != b.name:
        return Err(TrioError.TypeMismatch)
    return OK(None)

def _int_outcome(v):
    n = abs(v)
    if n > LIM:
        return Err(TrioError.IntRangeOverflow)
    if n == LIM:
        return Lossy("repr")  # граничная конвенция: ровно 2^53 — Lossy
    return None

def export_to_octave(arr, mtype, mode="copy"):
    a = np.asarray(arr)
    if mtype.name == "Int64" and a.dtype.kind in "iu":
        outs = [_int_outcome(int(v)) for v in a.ravel()]
        if any(isinstance(o, Err) for o in outs):
            return Err(TrioError.IntRangeOverflow)
        if any(isinstance(o, Lossy) for o in outs):
            return Lossy("repr", value=a)
    r = OK(a)
    if mode == "view":
        # R-MAT1: view — только при совпадении layout (принимающая сторона Octave — F)
        # и непрерывности; иначе понижение до copy с диагностикой SC-011 ModeDowngrade
        contiguous = a.flags.c_contiguous or a.flags.f_contiguous
        invariant = (a.ndim == 1) or (min(a.shape) == 1)
        if not (contiguous and (invariant or a.flags.f_contiguous)):
            r = OK(np.asfortranarray(a),
                   warnings=["SC-011 ModeDowngrade (R-MAT1): view -> copy (layout mismatch)"])
    return r

def import_from_octave(arr, mtype):
    a = np.asarray(arr)
    if a.dtype == np.bool_ and mtype.name != "Bool":
        return Err(TrioError.UndefinedBridge)  # R-BOOL
    if mtype.name == "Bool" and a.dtype.kind in "iuf":
        return Err(TrioError.UndefinedBridge)  # R-BOOL
    if a.size == 0:
        return OK(a)  # конвенция: пустая матрица = Optional.empty (R-OPT1, интерпретация)
    if mtype.domain != "nan" and a.dtype.kind == "f":
        if np.isnan(a).any():
            return Err(TrioError.NaNAsMissing)  # R-NAN, strict
        if np.isinf(a).any():
            return Err(TrioError.DomainError)   # R-NAN, strict
    if mtype.name == "Int64":
        # R-INT2: Float64 -> Int64
        if a.dtype.kind == "f":
            if not np.all(a == np.floor(a)):
                return Err(TrioError.FractionalInt)
            m = max(abs(int(v)) for v in a.ravel())
            if m > LIM:
                return Err(TrioError.IntRangeOverflow)
            return OK(a.astype(np.int64))
        if a.dtype.kind in "iu":
            m = max(abs(int(v)) for v in a.ravel())
            if m > LIM:
                return Err(TrioError.IntRangeOverflow)
            return OK(a.astype(np.int64))
        return Err(TrioError.TypeMismatch)
    if mtype.name == "Float64":
        return OK(a.astype(np.float64))  # R-FLT1/2: точное расширение
    if mtype.name == "Float32":
        if a.dtype == np.float64:
            return Lossy("precision", value=a.astype(np.float32))  # R-FLT3
        return OK(a.astype(np.float32))
    return Err(TrioError.NoCoercion)

# таблица маппинга исключений — не в спеке, только дефолт R-ERR2
_EXC_MAP = {
    TypeError: TrioError.TypeMismatch,
    IndexError: TrioError.ShapeError,
    KeyError: TrioError.MissingField,
    MemoryError: TrioError.ResourceLost,
}

def exception_to_trio(e):
    for k, v in _EXC_MAP.items():
        if isinstance(e, k):
            return v
    return TrioError.ResourceLost  # R-ERR2: непереводимое исключение -> ResourceLost

_NPD = {"Float64": "<f8", "Int64": "<i8", "Bool": np.bool_}

def _np_dt(name):
    return _NPD[name]

def write_matrix(path, arr, order="C"):
    # канон TRIOMAT1: [u32 LE: длина заголовка][заголовок JSON][payload C-порядок]
    a = np.asarray(arr)
    if a.dtype == np.float64: name = "Float64"
    elif a.dtype == np.int64: name = "Int64"
    elif a.dtype == np.bool_: name = "Bool"
    else: return Err(TrioError.TypeError)
    if any(d < 0 for d in a.shape):
        return Err(TrioError.ShapeError)
    header = json.dumps(
        {"magic": "TRIOMAT1", "dtype": name,
         "shape": [int(d) for d in a.shape],
         "flags": {"stub": False, "lossy": False, "trusted": True}},
        separators=(",", ":")).encode("utf-8")
    # параметр order принят для совместимости теста, но канон пишет payload
    # всегда в C-порядке: F-массив транскодируется, данные не теряются
    payload = a.astype(_np_dt(name)).tobytes(order="C")
    with open(path, "wb") as f:
        f.write(struct.pack("<I", len(header)))
        f.write(header)
        f.write(payload)
    return OK(None)

def read_matrix(path):
    data = open(path, "rb").read()
    if len(data) < 4:
        return Err(TrioError.MalformedHeader)
    (hlen,) = struct.unpack("<I", data[:4])
    if 4 + hlen > len(data):
        return Err(TrioError.ShapeError)
    try:
        h = json.loads(data[4:4 + hlen].decode("utf-8"))
    except Exception:
        return Err(TrioError.MalformedHeader)
    if h.get("magic") != "TRIOMAT1":
        return Err(TrioError.MalformedHeader)
    if h.get("dtype") not in _NPD:
        return Err(TrioError.TypeError)
    shape = h.get("shape")
    if (not isinstance(shape, list) or
            any((not isinstance(d, int)) or d < 0 for d in shape)):
        return Err(TrioError.ShapeError)
    n = 1
    for d in shape:
        n *= d
    nbytes = n if h["dtype"] == "Bool" else n * 8
    payload = data[4 + hlen:]
    if len(payload) != nbytes:
        return Err(TrioError.ShapeError)  # обрезанный payload / лишние байты
    if h["dtype"] == "Bool" and any(b not in (0, 1) for b in payload):
        return Err(TrioError.BoolPayload)
    arr = np.frombuffer(payload, dtype=_np_dt(h["dtype"])).reshape(shape).copy()
    # канон хранит payload только в C-порядке; поля layout в формате нет
    return (arr, 0)
