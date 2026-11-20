# trio_bridge.py — reference-реализация TTB-Spec v0.1: мост Sound <-> Octave.
# Контракты выведены из чек-листа раздела 8 (test_bridge.py).
import enum
import struct

import numpy as np

TWO53 = 2 ** 53

class TrioError(enum.Enum):
    IntRangeOverflow = "IntRangeOverflow"
    FractionalInt = "FractionalInt"
    NaNAsMissing = "NaNAsMissing"
    TypeMismatch = "TypeMismatch"
    ShapeError = "ShapeError"
    MissingField = "MissingField"
    ResourceLost = "ResourceLost"

class OK:
    __slots__ = ("value", "warnings")
    def __init__(self, value=None, warnings=()):
        self.value = value
        self.warnings = list(warnings)
    def __repr__(self):
        s = "OK(" + repr(self.value) + ")"
        if self.warnings:
            s += " warnings=" + repr(self.warnings)
        return s

class Lossy:
    __slots__ = ("value", "delta", "warnings")
    def __init__(self, delta, value=None, warnings=()):
        self.delta = delta
        self.value = value
        self.warnings = list(warnings)
    def __repr__(self):
        return f"Lossy(delta={self.delta!r}, value={self.value!r})"

class Err:
    __slots__ = ("error", "detail")
    def __init__(self, error, detail=""):
        self.error = error
        self.detail = detail
    def __repr__(self):
        return f"Err({self.error.value})" + (f" [{self.detail}]" if self.detail else "")

class MType:
    __slots__ = ("dtype", "shape", "domain")
    def __init__(self, dtype, shape, domain=None):
        self.dtype = dtype
        self.shape = tuple(shape)
        self.domain = domain

# ---- R-ERR1/R-ERR2: исключения снаружи -> Err-значения внутри ----
_EXC_MAP = {
    TypeError: TrioError.TypeMismatch,
    IndexError: TrioError.ShapeError,
    KeyError: TrioError.MissingField,
    MemoryError: TrioError.ResourceLost,
}

def exception_to_trio(exc):
    return _EXC_MAP.get(type(exc), TrioError.ResourceLost)

# ---- R-INT2: экспорт int64 -> double (зона гарантии: |v| <= 2^53 - 1) ----
def export_to_octave(arr, mtype, mode="copy"):
    a = np.asarray(arr)
    if mtype.dtype == "Int64":
        vals = [int(v) for v in a.ravel()]
        if any(abs(v) > TWO53 for v in vals):
            return Err(TrioError.IntRangeOverflow)
        if any(abs(v) == TWO53 for v in vals):
            return Lossy("repr", a.astype(np.float64))
        return OK(a.astype(np.float64))
    # Float64
    warnings = []
    if mode == "view" and a.base is not None and a.ndim == 2 and all(d > 1 for d in a.shape):
        warnings.append("R-MAT1: view downgraded to copy "
                        "(C-layout не совпадает с column-major Octave)")
    return OK(a.astype(np.float64, copy=True), warnings)

# ---- R-INT3 / R-OPT1 / R-NAN / R-FLT1: импорт из Octave ----
def import_from_octave(arr, mtype):
    a = np.asarray(arr)
    if a.size and np.isnan(a.astype(np.float64, copy=False)).any() and mtype.domain != "nan":
        return Err(TrioError.NaNAsMissing)
    if mtype.dtype == "Int64":
        f = a.astype(np.float64)
        if np.any(f != np.floor(f)):
            return Err(TrioError.FractionalInt)
        return OK(f.astype(np.int64))
    if mtype.dtype == "Float64":
        return OK(a.astype(np.float64))
    if mtype.dtype == "Float32":
        f32 = a.astype(np.float32)
        if a.dtype == np.float64 and np.any(f32.astype(np.float64) != a):
            return Lossy("precision", f32)
        return OK(f32)
    return Err(TrioError.TypeMismatch, f"unsupported dtype {mtype.dtype!r}")

# ---- R-MAT1 (файловая часть): layout в заголовке ----
_MAGIC = b"TRIOBIN1"
_DTYPE_CODE = {np.dtype(np.float64): 1, np.dtype(np.int64): 2, np.dtype(np.float32): 3}
_CODE_DTYPE = {v: k for k, v in _DTYPE_CODE.items()}

def write_matrix(path, arr, order="C"):
    a = np.asarray(arr)
    layout = 1 if order == "F" else 0
    header = _MAGIC + struct.pack("<BBBI", 1, layout, _DTYPE_CODE[a.dtype], a.ndim)
    for d in a.shape:
        header += struct.pack("<I", d)
    with open(path, "wb") as f:
        f.write(header)
        f.write(a.tobytes(order=order))

def read_matrix(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != _MAGIC:
        raise ValueError("not a TRIOBIN1 file")
    ver, layout, code, ndim = struct.unpack("<BBBI", data[8:15])   # <BBBI = 7 байт
    shape = struct.unpack("<" + "I" * ndim, data[15:15 + 4 * ndim])
    payload = data[15 + 4 * ndim:]
    order = "F" if layout == 1 else "C"
    arr = np.frombuffer(payload, dtype=_CODE_DTYPE[code]).reshape(shape, order=order)
    return arr.copy(), layout

# ---- R-DIM3/R-DIM5/R-DIM6: унификация размерностей и ослабление ----
def unify(decl, actual):
    env = {}
    if len(decl) != len(actual):
        return Err(TrioError.ShapeError, "rank mismatch")
    for d, a in zip(decl, actual):
        if d in ("C", "F"):
            continue  # маркер layout, не размерность
        if isinstance(d, str):
            key = "?" + str(len(env)) if d == "?" else d
            if key in env and env[key] != a:
                return Err(TrioError.ShapeError, f"DimVar {d}: {env[key]} != {a}")
            env[key] = a
        elif d != a:
            return Err(TrioError.ShapeError, f"{d} != {a}")
    return OK(env)

def check_widening(src, dst):
    # R-DIM6: конкретный размер -> DimVar = обобщение, без явного generalize запрещено
    for ds, dd in zip(src.shape, dst.shape):
        if isinstance(dd, str) and not isinstance(ds, str):
            return Err(TrioError.ShapeError, "R-DIM6: generalization without generalize flag")
    return OK()
