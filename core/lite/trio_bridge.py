"""trio_bridge.py — референсный Python-бридж Trio Type Bridge Spec v0.1.

Реализует правила конверсии из спеки:
  R-INT1..3  — граница 2^53 для Int64, дробные к Int64 не проходят
  R-FLT1..3  — расширение точное (OK), сужение — Lossy(precision)
  R-BOOL     — числа к Bool не приводятся (NoCoercion)
  R-STR      — UTF-8, суррогаты -> EncodingFault
  R-MAT1     — view только при совпадении layout и непрерывности памяти,
               иначе понижение до copy с предупреждением
  R-DIM5/6   — '?' и DimVar фиксируются первым значением; ослабление
               только через явный generalize()
  R-DIM7     — несходящиеся размеры дают ShapeError на границе
  R-OPT1     — NaN как отсутствие запрещён вне домена; сентинелы ловятся
  R-NAN      — домен "nan" легализует NaN/Inf
  R-ERR1/2   — закрытая таблица перевода исключений; неизвестные ->
               ResourceLost с trusted=False

Формат TRIOMAT (общий с trio_bridge.m и TrioBridge.java):
  байты 0..7   magic b"TRIOMAT\x01"
  байт  8      version = 1
  байт  9      layout: 0 = row-major, 1 = column-major
  байт 10      dtype: 0 = Float64, 1 = Float32, 2 = Int64, 3 = Bool
  байт 11      ndim
  далее        ndim x u64 (big-endian) — размеры
  далее        payload в объявленном dtype (little-endian) и layout-порядке
"""

from __future__ import annotations

import math
import struct
import warnings

import numpy as np

__all__ = [
    "TrioError", "OK", "Lossy", "Err", "MType", "OctavePayload",
    "convert_scalar", "export_to_octave", "from_octave",
    "write_matrix", "read_matrix", "translate_exception",
]

TRIOMAT_MAGIC = b"TRIOMAT\x01"
TRIOMAT_VERSION = 1

_LAYOUT_ROW, _LAYOUT_COL = 0, 1
_DTYPE_CODES = {"Float64": 0, "Float32": 1, "Int64": 2, "Bool": 3}
_CODE_DTYPE = {v: k for k, v in _DTYPE_CODES.items()}
_NUMPY_DTYPE = {
    "Float64": np.float64, "Float32": np.float32,
    "Int64": np.int64, "Bool": np.bool_,
}
# payload формата TRIOMAT — little-endian: контракт платформонезависим
_LE_DTYPE = {
    "Float64": "<f8", "Float32": "<f4", "Int64": "<i8", "Bool": "|b1",
}
_INT64_LIMIT = 2 ** 53  # R-INT2/R-INT3: граница точного представления

_HEADER_FMT = ">8sBBBB"  # magic, version, layout, dtype, ndim
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class TrioWarning(UserWarning):
    pass


def _warn(message: str) -> None:
    warnings.warn(message, TrioWarning, stacklevel=3)


# --------------------------------------------------------------------------
# Ошибки (R-ERR1/2) и результаты конверсии
# --------------------------------------------------------------------------

class TrioError(Exception):
    """Закрытое перечисление ошибок Trio. trusted=False => узел недоверенный."""

    def __init__(self, variant: str, message: str = "", trusted: bool = True):
        self.variant = variant
        self.message = message
        self.trusted = trusted
        super().__init__(f"{variant}: {message}" if message else variant)

    def __repr__(self) -> str:
        return f"TrioError({self.variant!r}, {self.message!r}, trusted={self.trusted})"


class OK:
    """Точная или согласованная конверсия."""

    __slots__ = ("value", "meta")

    def __init__(self, value, meta=()):
        self.value = value
        self.meta = tuple(meta)  # R-TRACE: цепочка происхождения

    def __repr__(self) -> str:
        return f"OK({self.value!r})"


class Lossy:
    """Конверсия с объявленной потерей. Lossy не является ошибкой."""

    __slots__ = ("value", "delta", "meta")

    def __init__(self, value, delta: str, meta=()):
        self.value = value
        self.delta = delta     # "repr" | "precision" | "dropped_fields"
        self.meta = tuple(meta)

    def __repr__(self) -> str:
        return f"Lossy({self.value!r}, delta={self.delta!r})"


class Err:
    """Ошибка конверсии."""

    __slots__ = ("error",)

    def __init__(self, error: TrioError):
        self.error = error

    def __repr__(self) -> str:
        return f"Err({self.error!r})"


# --------------------------------------------------------------------------
# Типы: MType — Matrix[T, R, C] с измерениями-типами
# --------------------------------------------------------------------------

class MType:
    """dtype + dims; элемент dims: int > 0, '?' или символическая переменная."""

    def __init__(self, dtype: str, dims=()):
        if dtype not in _DTYPE_CODES:
            raise ValueError(f"неизвестный dtype: {dtype!r}")
        for d in dims:
            if not ((isinstance(d, int) and not isinstance(d, bool) and d > 0)
                    or isinstance(d, str)):
                raise ValueError(f"некорректная размерность: {d!r}")
        self.dtype = dtype
        self.dims = tuple(dims)

    def is_fully_known(self) -> bool:
        return all(isinstance(d, int) for d in self.dims)

    def check(self, shape):
        """R-DIM5/R-DIM7: унификация фактической формы с объявленными размерами."""
        shape = tuple(shape)
        if len(shape) != len(self.dims):
            return Err(TrioError(
                "ShapeError", f"ранг {len(shape)} != {len(self.dims)}"))
        bound = []
        for declared, actual in zip(self.dims, shape):
            if isinstance(declared, int):
                if declared != actual:
                    return Err(TrioError(
                        "ShapeError",
                        f"размер {actual} != объявленного {declared}"))
                bound.append(declared)
            else:
                bound.append(actual)  # R-DIM5: фиксация первым значением
        return OK(MType(self.dtype, bound))

    def generalize(self, index: int) -> "MType":
        """R-DIM6: явное обобщение — единственный путь от размера к '?'."""
        dims = list(self.dims)
        dims[index] = "?"
        return MType(self.dtype, dims)

    def __repr__(self) -> str:
        dims = ", ".join("?" if isinstance(d, str) else str(d) for d in self.dims)
        return f"MType({self.dtype}, [{dims}])"


# --------------------------------------------------------------------------
# Внутренние проверки
# --------------------------------------------------------------------------

def _check_nan(arr, domain: str):
    """R-OPT1/R-NAN: NaN вне домена — это отсутствие, а не число."""
    if not np.issubdtype(arr.dtype, np.floating):
        return None
    work = arr.astype(np.float64, copy=False)
    if domain != "nan":
        if np.isnan(work).any():
            return Err(TrioError(
                "NaNAsMissing", "NaN вне домена nan (R-OPT1)"))
        if not np.isfinite(work).all():
            return Err(TrioError(
                "DomainViolation", "Inf вне домена nan"))
    return None


def _check_sentinel(arr, sentinel):
    if sentinel is None:
        return None
    if np.any(np.asarray(arr, dtype=np.float64) == np.float64(sentinel)):
        return Err(TrioError(
            "SentinelDetected", f"значение-сентинел {sentinel} на границе"))
    return None


# --------------------------------------------------------------------------
# Конверсии: ядро -> Octave-представление и обратно
# --------------------------------------------------------------------------

def _to_octave(arr, target: str, domain: str):
    """Ядро -> представление Octave. Возвращает OK/Lossy/Err."""
    if arr.dtype == object or arr.dtype.kind in "USV":
        return Err(TrioError(
            "HeterogeneousMatrix", "строки/объекты в матрице не поддерживаются"))

    err = _check_nan(arr, domain)
    if err:
        return err

    if target == "Bool":
        if arr.dtype == np.bool_:
            return OK(arr)
        f = arr.astype(np.float64)
        if np.all((f == 0) | (f == 1)):
            return OK(f.astype(np.bool_))
        return Err(TrioError("TypeMismatch", "Bool: значения должны быть 0/1"))

    if target == "Int64":
        if arr.dtype == np.int64:
            # R-INT2: проверка диапазона в исходном (целочисленном) домене
            if not bool((np.abs(arr) <= _INT64_LIMIT).all()):
                return Err(TrioError(
                    "IntRangeOverflow", "R-INT2: |v| > 2^53"))
            # TRIOMAT хранит объявленный dtype (int64); Lossy(repr)
            # возникает на стороне Octave при загрузке в double
            return OK(arr)
        if np.issubdtype(arr.dtype, np.floating):
            f = arr.astype(np.float64)
            if not bool(np.all(f == np.floor(f))):
                return Err(TrioError("FractionalInt", "R-INT3: дробное значение"))
            if not bool((np.abs(f) <= _INT64_LIMIT).all()):
                return Err(TrioError("IntRangeOverflow", "R-INT2: |v| > 2^53"))
            return Lossy(f, "repr")
        return Err(TrioError("TypeMismatch",
                             f"Int64: несовместимый dtype {arr.dtype}"))

    if target == "Float64":
        if arr.dtype == np.float64:
            return OK(arr)
        if arr.dtype == np.float32:
            # R-FLT1 (уточнение спеки): расширение точное -> OK, с трассой origin
            return OK(arr.astype(np.float64), meta=(("origin", "F32"),))
        if arr.dtype == np.int64:
            return Lossy(arr.astype(np.float64), "repr")
        return Err(TrioError("TypeMismatch",
                             f"Float64: несовместимый dtype {arr.dtype}"))

    if target == "Float32":
        if arr.dtype == np.float32:
            return OK(arr)
        if arr.dtype in (np.float64, np.int64):
            return Lossy(arr.astype(np.float32), "precision")
        return Err(TrioError("TypeMismatch",
                             f"Float32: несовместимый dtype {arr.dtype}"))

    return Err(TrioError("UndefinedBridge", f"тип {target} не описан"))


class OctavePayload:
    """Матрица в семантике Octave: dtype-пейлоад, layout, режим передачи."""

    def __init__(self, payload, mtype: MType, layout: str, mode: str):
        self.payload = payload   # np.ndarray; для mode="view" — ссылка на буфер
        self.mtype = mtype
        self.layout = layout     # "row" | "col"
        self.mode = mode         # "view" | "copy"


def export_to_octave(arr, mtype: MType, mode: str = "copy", domain: str = "strict",
                     sentinel=None):
    """Ядро -> Octave-сторона. OK(OctavePayload) | Lossy(OctavePayload) | Err."""
    if mode not in ("copy", "view"):
        raise ValueError("mode: 'copy' | 'view'")
    arr = np.asarray(arr)

    check = mtype.check(arr.shape)
    if isinstance(check, Err):
        return check
    bound = check.value

    err = _check_sentinel(arr, sentinel)
    if err:
        return err

    conv = _to_octave(arr, mtype.dtype, domain)
    if isinstance(conv, Err):
        return conv

    layout = None
    if mode == "view":
        if arr.flags["C_CONTIGUOUS"]:
            layout = "row"
        elif arr.flags["F_CONTIGUOUS"]:
            layout = "col"
        else:
            _warn("R-MAT1: непрерывность памяти не совпадает с layout — "
                  "view понижен до copy")
            mode = "copy"
    if mode == "copy":
        layout = layout or "row"

    wrapped = OctavePayload(conv.value, bound, layout=layout, mode=mode)
    if isinstance(conv, Lossy):
        return Lossy(wrapped, conv.delta, meta=conv.meta)
    return OK(wrapped, meta=conv.meta)


def from_octave(arr, target: str, domain: str = "strict", sentinel=None):
    """Octave-сторона -> ядро (R-INT3, R-FLT1/2/3, R-BOOL, R-OPT1/R-NAN)."""
    arr = np.asarray(arr)
    err = _check_nan(arr, domain)
    if err:
        return err
    err = _check_sentinel(arr, sentinel)
    if err:
        return err
    f = arr.astype(np.float64)

    if target == "Float64":
        return OK(f, meta=(("origin", "OCT"),))
    if target == "Float32":
        return Lossy(f.astype(np.float32), "precision")
    if target == "Int64":
        if not bool(np.all(f == np.floor(f))):
            return Err(TrioError("FractionalInt", "R-INT3: дробное значение"))
        # R-INT3: проверка в float-домене здесь корректна: порог 2^53 точно
        # представим в double, дробные отсечены до сравнения
        if not bool((np.abs(f) <= _INT64_LIMIT).all()):
            return Err(TrioError("IntRangeOverflow", "R-INT3: |v| > 2^53"))
        return OK(f.astype(np.int64), meta=(("origin", "OCT"),))
    if target == "Bool":
        if np.all((f == 0) | (f == 1)):
            return OK(f.astype(np.bool_))
        return Err(TrioError("TypeMismatch", "Bool: значения должны быть 0/1"))
    return Err(TrioError("UndefinedBridge", f"тип {target} не описан"))


def convert_scalar(value, target: str, domain: str = "strict"):
    """Скалярные правила R-INT1..3, R-FLT1..3, R-BOOL, R-STR."""
    if target == "Int64":
        if isinstance(value, bool):
            return Err(TrioError("NoCoercion",
                                 "Bool к Int64 через границу не приводится"))
        if isinstance(value, int):
            if abs(value) > _INT64_LIMIT:
                return Err(TrioError("IntRangeOverflow", "R-INT2: |v| > 2^53"))
            return Lossy(float(value), "repr")
        if isinstance(value, float):
            if math.isnan(value) and domain != "nan":
                return Err(TrioError("NaNAsMissing", "R-OPT1"))
            if not value.is_integer():
                return Err(TrioError("FractionalInt", "R-INT3: дробное значение"))
            if abs(value) > _INT64_LIMIT:
                return Err(TrioError("IntRangeOverflow", "R-INT3: |v| > 2^53"))
            return OK(int(value))
        return Err(TrioError("TypeMismatch", f"Int64: {type(value).__name__}"))

    if target == "Float64":
        if isinstance(value, bool):
            return Err(TrioError("NoCoercion", "Bool к числу не приводится"))
        if isinstance(value, (int, float)):
            v = float(value)
            if math.isnan(v) and domain != "nan":
                return Err(TrioError("NaNAsMissing", "R-OPT1"))
            return OK(v)
        if isinstance(value, (np.floating, np.integer)):
            return OK(float(value),
                      meta=(("origin",
                             "F32" if value.dtype == np.float32 else "SRC"),))
        return Err(TrioError("TypeMismatch", f"Float64: {type(value).__name__}"))

    if target == "Float32":
        if isinstance(value, bool):
            return Err(TrioError("NoCoercion", "Bool к числу не приводится"))
        if isinstance(value, (int, float, np.floating, np.integer)):
            return Lossy(np.float32(value), "precision")
        return Err(TrioError("TypeMismatch", f"Float32: {type(value).__name__}"))

    if target == "Bool":
        if isinstance(value, bool):
            return OK(value)
        # R-BOOL: числа к Bool не приводятся
        return Err(TrioError("NoCoercion", "R-BOOL: числа к Bool не приводятся"))

    if target == "String":
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                return Err(TrioError("EncodingFault", "R-STR: суррогатный кодпоинт"))
            return OK(value)
        return Err(TrioError("TypeMismatch", f"String: {type(value).__name__}"))

    return Err(TrioError("UndefinedBridge", f"тип {target} не описан"))


# --------------------------------------------------------------------------
# Формат TRIOMAT: диск на границе Octave <-> JVM <-> Python
# --------------------------------------------------------------------------

def write_matrix(path, arr, mtype: MType, mode: str = "copy",
                 domain: str = "strict", sentinel=None):
    """Пишет TRIOMAT-файл. Возвращает результат export_to_octave."""
    result = export_to_octave(arr, mtype, mode=mode, domain=domain,
                              sentinel=sentinel)
    if isinstance(result, Err):
        return result
    p = result.value.payload
    layout = result.value.layout
    order = "C" if layout == "row" else "F"
    data = (np.asarray(p, order=order)
            .astype(_LE_DTYPE[mtype.dtype], copy=False)
            .tobytes(order=order))
    ndim = len(result.value.mtype.dims)
    header = struct.pack(
        _HEADER_FMT, TRIOMAT_MAGIC, TRIOMAT_VERSION,
        _LAYOUT_ROW if layout == "row" else _LAYOUT_COL,
        _DTYPE_CODES[mtype.dtype], ndim)
    dims = struct.pack(f">{ndim}Q",
                       *[int(d) for d in result.value.mtype.dims])
    with open(path, "wb") as fh:
        fh.write(header + dims + data)
    return result


def read_matrix(path, target: str = None, domain: str = "strict"):
    """Читает TRIOMAT-файл, нормализует к row-major ядру; типизация по target."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) < _HEADER_SIZE:
        return Err(TrioError("ShapeError", "файл короче заголовка"))
    magic, version, layout_code, dtype_code, ndim = struct.unpack_from(
        _HEADER_FMT, blob, 0)
    if magic != TRIOMAT_MAGIC:
        return Err(TrioError("UndefinedBridge", "не TRIOMAT-файл"))
    if version != TRIOMAT_VERSION:
        return Err(TrioError("UndefinedBridge", f"версия {version}"))
    if layout_code not in (_LAYOUT_ROW, _LAYOUT_COL):
        return Err(TrioError("LayoutMismatch", f"layout={layout_code}"))
    dtype_name = _CODE_DTYPE.get(dtype_code)
    if dtype_name is None:
        return Err(TrioError("UndefinedBridge", f"dtype-код {dtype_code}"))
    dims = struct.unpack_from(f">{ndim}Q", blob, _HEADER_SIZE)
    count = math.prod(dims) if dims else 0
    itemsize = np.dtype(_LE_DTYPE[dtype_name]).itemsize
    need = _HEADER_SIZE + 8 * ndim + count * itemsize
    if len(blob) != need:
        return Err(TrioError("ShapeError", "размер payload не совпадает с заголовком"))

    raw = np.frombuffer(blob, dtype=_LE_DTYPE[dtype_name], count=count,
                        offset=_HEADER_SIZE + 8 * ndim)
    order = "C" if layout_code == _LAYOUT_ROW else "F"
    arr = raw.reshape(dims, order=order) if dims else raw.reshape(())
    # ядро Trio — row-major: col-major payload переводим в C-порядок
    kernel_arr = np.ascontiguousarray(arr)  # col-major -> C-порядок, без транспонирования

    if target is None:
        return OK(kernel_arr)
    return from_octave(kernel_arr, target, domain=domain)


# --------------------------------------------------------------------------
# Перевод исключений (R-ERR1/2)
# --------------------------------------------------------------------------

_EXCEPTION_MAP = {
    "TypeError": "TypeMismatch",
    "ValueError": "DomainError",
    "IndexError": "ShapeError",
    "KeyError": "MissingField",
    "AttributeError": "MissingField",
    "ZeroDivisionError": "DomainError",
    # JVM-имена — для симметрии с TrioBridge.java
    "ClassCastException": "TypeMismatch",
    "ArrayIndexOutOfBoundsException": "ShapeError",
    "NullPointerException": "NullPointer",
}


def translate_exception(exc: BaseException) -> TrioError:
    """Закрытая таблица: неизвестное исключение -> ResourceLost, trusted=False."""
    variant = _EXCEPTION_MAP.get(type(exc).__name__)
    if variant is not None:
        return TrioError(variant, str(exc), trusted=True)
    return TrioError("ResourceLost", f"{type(exc).__name__}: {exc}", trusted=False)


def octave_error_to_trio(text: str) -> TrioError:
    """Octave error("...") -> DomainError с текстом."""
    return TrioError("DomainError", text)
