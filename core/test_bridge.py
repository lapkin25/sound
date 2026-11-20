"""test_bridge.py — прогон чек-листа TTB-Spec v0.1, раздел 8."""
import numpy as np
from trio_bridge import (
    MType, OK, Lossy, Err, TrioError,
    unify, check_widening, export_to_octave, import_from_octave,
    write_matrix, read_matrix, exception_to_trio,
)

results = []
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))

# T1: R-INT2 / R-INT3 — граница 2^53
r = export_to_octave(np.array([2**53 - 1, 2**53], dtype=np.int64), MType("Int64", (2,)))
check("R-INT2: 2^53-1 и 2^53 -> Lossy(repr)", isinstance(r, Lossy) and r.delta == "repr")
r = export_to_octave(np.array([2**53 + 1], dtype=np.int64), MType("Int64", (1,)))
check("R-INT2: 2^53+1 -> Err(IntRangeOverflow)",
      isinstance(r, Err) and r.error is TrioError.IntRangeOverflow)
r = import_from_octave(np.array([3.5], dtype=np.float64), MType("Int64", (1,)))
check("R-INT3: 3.5 -> Err(FractionalInt)",
      isinstance(r, Err) and r.error is TrioError.FractionalInt)
r = import_from_octave(np.array([42.0], dtype=np.float64), MType("Int64", (1,)))
check("R-INT3: 42.0 -> OK(Int64)", isinstance(r, OK) and r.value.dtype == np.int64)
r = import_from_octave(np.array([float(2**53 + 1)], dtype=np.float64), MType("Int64", (1,)))
check("R-INT3: double(2^53+1) -> OK как 2^53 (IEEE-скругление)",
      isinstance(r, OK) and r.value[0] == 2**53)

# T2: R-MAT1 — layout и понижение view
a = np.arange(12, dtype=np.float64).reshape(3, 4)
r = export_to_octave(a, MType("Float64", (3, 4)), mode="view")
check("R-MAT1: view 3x4 -> понижение до copy",
      isinstance(r, OK) and any("R-MAT1" in w for w in r.warnings))
r = export_to_octave(np.ascontiguousarray(a[0:1, :]), MType("Float64", (1, 4)), mode="view")
check("R-MAT1: view 1xN (contiguous) -> без понижения", isinstance(r, OK) and not r.warnings)
write_matrix("row.bin", a, order="C")
b, layout = read_matrix("row.bin")
check("Roundtrip C: layout=0, значения идентичны", layout == 0 and np.array_equal(b, a))
oct_side = np.asfortranarray(a)
write_matrix("col.bin", oct_side, order="F")
c, layout2 = read_matrix("col.bin")
check("Roundtrip F: layout=1, значения идентичны", layout2 == 1 and np.array_equal(c, oct_side))
check("Roundtrip: C- и F-байтовые порядки различаются (layout учтён)",
      not np.array_equal(b.tobytes(order="C"), c.tobytes(order="F")))

# T3: R-OPT1 / R-NAN
r = import_from_octave(np.array([[1.0, np.nan], [3.0, 4.0]]), MType("Float64", (2, 2)))
check("R-OPT1: NaN вне домена -> Err(NaNAsMissing)",
      isinstance(r, Err) and r.error is TrioError.NaNAsMissing)
r = import_from_octave(np.array([[1.0, np.nan], [3.0, 4.0]]),
                       MType("Float64", (2, 2), domain="nan"))
check("R-NAN: NaN в nan_domain -> OK", isinstance(r, OK))
r = import_from_octave(np.empty((0, 0)), MType("Float64", (0, 0)))
check("R-OPT1: пустая 0x0 = Optional.empty -> OK", isinstance(r, OK))

# T4: R-DIM5 / R-DIM6 / R-DIM3
env = unify(("?", "C"), (512, 512))
check("R-DIM5: \'?\' фиксируется значением 512", isinstance(env, OK) and env.value["?0"] == 512)
check("R-DIM3: DimVar R!=R отклоняется",
      isinstance(unify(("R", "R"), (512, 256)), Err))
r = check_widening(MType("Float64", (512, 512)), MType("Float64", ("?", "?")))
check("R-DIM6: ослабление без generalize -> Err", isinstance(r, Err))
check("R-DIM6: сужение ? -> 512 допустимо",
      isinstance(check_widening(MType("Float64", ("?", "?")),
                                MType("Float64", (512, 512))), OK))

# T5: R-FLT1, R-ERR1/2
r = import_from_octave(np.array([[1.1, 2.2]], dtype=np.float64), MType("Float32", (1, 2)))
check("R-FLT1: double->float32 -> Lossy(precision)", isinstance(r, Lossy))
r = import_from_octave(np.array([[1.5]], dtype=np.float32), MType("Float64", (1, 1)))
check("R-FLT1: float32->float64 -> OK (расширение)",
      isinstance(r, OK) and r.value.dtype == np.float64)
check("R-ERR2: TypeError -> TypeMismatch", exception_to_trio(TypeError()) is TrioError.TypeMismatch)
check("R-ERR2: IndexError -> ShapeError", exception_to_trio(IndexError()) is TrioError.ShapeError)
check("R-ERR2: KeyError -> MissingField", exception_to_trio(KeyError()) is TrioError.MissingField)
check("R-ERR2: MemoryError -> ResourceLost", exception_to_trio(MemoryError()) is TrioError.ResourceLost)
class WeirdError(Exception): pass
check("R-ERR2: неизвестное исключение -> ResourceLost", exception_to_trio(WeirdError()) is TrioError.ResourceLost)

print(f"{'TEST':60} {'RES':5}")
print("-" * 67)
for name, ok, _ in results:
    print(f"{name:60} {'PASS' if ok else 'FAIL':5}")
failed = sum(1 for _, ok, _ in results if not ok)
print("-" * 67)
print(f"TOTAL: {len(results)}, FAILED: {failed}")
