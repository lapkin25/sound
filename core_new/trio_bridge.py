# trio_bridge.py — TRIOMAT1 bridge v0.2
# Формат файла: MAGIC(8) | hlen(4, LE) | компактный JSON-заголовок | payload
# Вариант Б: layout не хранится; payload всегда канонический C-порядок логических значений.
import json, struct, math
import numpy as np

MAGIC = b"TRIOMAT1"

CODES = {
    "MalformedHeader","MalformedDtype","MalformedPayload","MalformedShape",
    "UnknownCode","IntRangeOverflow","TypeMismatch","UnknownName","UnknownSymbol",
    "DivisionByZero","NaNOutsideDomain","DomainError","ResourceLost","ResourceBusy",
    "AccessDenied","PermissionDenied","Timeout","Cancelled","InternalError",
}

class R:
    __slots__ = ("ok","lossy","v","n","note","code","detail")
    def __init__(self, ok=True, lossy=False, v=None, n=0, note="", code=None, detail=""):
        self.ok=ok; self.lossy=lossy; self.v=v; self.n=n; self.note=note
        self.code=code; self.detail=detail
    def __repr__(self):
        if not self.ok:  return f"Err({self.code}" + (f", {self.detail!r}" if self.detail else "") + ")"
        if self.lossy:   return f"Lossy(n={self.n}" + (f", {self.note!r}" if self.note else "") + ")"
        return f"OK({self.v!r})" if self.v is not None else "OK()"

def OK(v=None):  return R(ok=True,  lossy=False, v=v)
def Lossy(n=0, note="", v=None): return R(ok=True, lossy=True, n=n, note=note, v=v)
def Err(code, detail=""):
    assert code in CODES, f"unknown code {code!r}"
    return R(ok=False, code=code, detail=detail)

# --- таблица типов ---
_DTYPE_SIZE = {"Bool":1,"Int8":1,"Int16":2,"Int32":4,"Int64":8,"UInt8":1,
               "Float16":2,"Float32":4,"Float64":8}
_DT2NP = {"Bool":np.bool_,"Int8":np.int8,"Int16":np.int16,"Int32":np.int32,
          "Int64":np.int64,"UInt8":np.uint8,"Float16":np.float16,
          "Float32":np.float32,"Float64":np.float64}
if hasattr(np, "float128"):
    _DTYPE_SIZE["Float128"] = 16; _DT2NP["Float128"] = np.float128
_NP2DT = {np.dtype(v): k for k, v in _DT2NP.items()}

INT53 = 2**53
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1

# --- канон float: строчные нибблы, 13 цифр, экспонента e-1 (это даёт float.hex()) ---
def canon_float(x):
    x = float(x)
    if math.isnan(x): return "nan"
    if math.isinf(x): return "inf" if x > 0 else "-inf"
    if x == 0.0:
        return "-0x0.0p+0" if math.copysign(1.0, x) < 0 else "0x0.0p+0"
    return x.hex()  # '0x1.8000000000000p+1', '-0x1.2000000000000p+1' и т.п.

# --- R-INT1: целое -> Int64. Lossy уже на 2^53-1 включительно; за int64 -> Err ---
def int_check(n):
    n = int(n)
    if n < INT64_MIN or n > INT64_MAX:
        return Err("IntRangeOverflow", str(n))
    if abs(n) >= INT53 - 1:
        return Lossy(n=n)
    return OK(n)

# --- R-INT3: неинтегральный float -> Lossy с округлением; NaN/inf/переполнение -> Err ---
def to_int_exact(x):
    x = float(x)
    if math.isnan(x): return Err("NaNOutsideDomain")
    if math.isinf(x): return Err("IntRangeOverflow")
    if x < INT64_MIN or x > INT64_MAX: return Err("IntRangeOverflow")
    r = int(np.rint(x))
    if x != math.floor(x) or abs(x) >= INT53 - 1:
        return Lossy(n=r)
    return OK(r)

def _dims_norm(x):
    out = []
    def go(e):
        if isinstance(e, str):
            s = e.strip()
            if s.startswith("Matrix"): s = s[len("Matrix"):]
            for p in s.replace(",", " ").replace("[", " ").replace("]", " ").split():
                if p in ("C", "F"): continue
                out.append(int(p) if p.isdigit() else p)
        elif isinstance(e, (list, tuple)):
            for i in e: go(i)
        elif isinstance(e, int):
            out.append(e)
    go(x)
    return out

def dims_match(a, b): return _dims_norm(a) == _dims_norm(b)
def unify(a, b):      return _dims_norm(a) == _dims_norm(b)

def _payload_c(arr):
    return np.ascontiguousarray(arr).tobytes()   # вариант Б: C-порядок всегда

def _hdr(dtype, shape, order="C"):
    d = {"dtype": dtype, "shape": list(shape)}
    if order != "C": d["order"] = order
    return json.dumps(d, separators=(",", ":")).encode()

def _wrap(arr, order="C"):
    a = np.asfortranarray(arr) if order == "F" else np.ascontiguousarray(arr)
    dt = _NP2DT.get(np.dtype(a.dtype))
    if dt is None: return Err("TypeMismatch", f"dtype {a.dtype}")
    h = _hdr(dt, a.shape, order)
    return MAGIC + struct.pack("<I", len(h)) + h + a.tobytes(order=order)

def write_matrix(arr):  return _wrap(arr, "C")
def pack_octave(arr):   return _wrap(arr, "F")

def _parse(data, want_order="C"):
    data = bytes(data)
    if len(data) < 12: return Err("MalformedHeader", "short file")
    if data[:8] != MAGIC: return Err("MalformedHeader", "bad magic")
    hlen = struct.unpack("<I", data[8:12])[0]
    if 12 + hlen > len(data): return Err("MalformedHeader", "truncated header")
    try:
        hdr = json.loads(data[12:12 + hlen])
    except Exception:
        return Err("MalformedHeader", "bad json")
    if not isinstance(hdr, dict) or "dtype" not in hdr or "shape" not in hdr:
        return Err("MalformedHeader", "no dtype/shape")
    dt = hdr["dtype"]
    if dt not in _DT2NP: return Err("MalformedDtype", dt)
    shape = hdr["shape"]
    if not isinstance(shape, list) or any((not isinstance(s, int)) or s < 0 for s in shape):
        return Err("MalformedShape")
    payload = data[12 + hlen:]
    n = 1
    for s in shape: n *= s
    if len(payload) != n * _DTYPE_SIZE[dt]:
        return Err("MalformedPayload")
    if dt == "Bool" and any(b not in (0, 1) for b in payload):
        return Err("TypeMismatch", "bool bytes")
    a = np.frombuffer(payload, dtype=_DT2NP[dt])
    a = a.reshape(shape, order=want_order) if shape else a
    return OK(a)

def read_matrix(data):   return _parse(data, "C")
def unpack_octave(data): return _parse(data, "F")

# --- R-ERR2: Err доминирует над Lossy; пустой агрегат -> ResourceLost ---
def aggregate(rs):
    if not rs: return Err("ResourceLost", "nothing to aggregate")
    for r in rs:
        if not r.ok: return r
    ls = [r for r in rs if r.lossy]
    if ls:
        return Lossy(n=sum(l.n for l in ls), note="; ".join(l.note for l in ls if l.note))
    return OK()

def worst(a, b):
    if not a.ok: return a
    if not b.ok: return b
    if a.lossy:  return a
    if b.lossy:  return b
    return a
