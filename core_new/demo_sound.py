# demo_sound.py
import numpy as np
import trio_bridge as tb
import sound_core3 as C
import sound_front as F
import sound_reader as SR

# --- мост: сериализация и канон ---
m = np.array([[1., 2.], [3., 4.]])
print(tb.read_matrix(tb.write_matrix(m)))   # OK(array([[1., 2.], [3., 4.]]))
print(tb.canon_float(3.0))                  # 0x1.8000000000000p+1
print(tb.canon_float(-2.25))                # -0x1.2000000000000p+1
print(tb.int_check(2**53 - 1))              # Lossy(n=9007199254740991)
print(tb.int_check(2**63))                  # Err(IntRangeOverflow, '...')
print(tb.to_int_exact(1.5))                 # Lossy(n=2)
print(tb.aggregate([tb.Lossy(1), tb.Err("Timeout")]))  # Err(Timeout)

# --- ядро: арифметика, журнал, замыкания ---
r = C.Run()
val = C.run(["let", "x", ["lit", 2], ["+", ["sym", "x"], ["lit", 3]]], r)
print(val.j())   # Int64 5
print(r.log)     # ['bind x = Int64 2', 'bind t0 = Int64 5', 'result Int64 5']

print(C.run(["/", ["lit", 1.0], ["lit", 0.0]]).j())    # Float64 inf
print(C.run(["/", ["lit", -1.0], ["lit", 0.0]]).j())   # Float64 -inf
print(C.run(["/", ["lit", 0.0], ["lit", 0.0]]).code)   # NaNOutsideDomain
print(C.run(["/", ["lit", 3], ["lit", 0]]).code)       # DivisionByZero
INF = float("inf")
print(C.run(["-", ["lit", INF], ["lit", INF]]).code)   # NaNOutsideDomain
print(C.run(["/", ["lit", -3], ["lit", 2]]).v)         # -1 (усечение к нулю)

C.register_fn("add", ["a", "b"], ["+", ["sym", "a"], ["sym", "b"]])
g = C.call_fn(C._mk_clo("add", C.REGISTRY), [C.VInt(100)], C.Run())
print(C.call_fn(g, [C.VInt(5)], C.Run()).v)            # 105 — частичное применение

# --- фронтенд: спека, roundtrip, статические проверки ---
SPEC = (
    "spec mixer ;\n"
    "fact gain 2 ;\n"
    "wire src -> scaled ;\n"
    "rule scaled x = x * gain ;\n"
    "pure rule trim x: Matrix[2,2] = x * 0.5 invariant x >= 0 ;\n"
)
sp = F.parse_spec(SPEC)
print(F.roundtrip(SPEC))      # True
print(F.serialize(sp))        # см. вывод ниже
print(F.static_checks(sp))    # [] — спека корректна

# --- ридер: сквозной прогон ---
res = SR.read_file(tb.write_matrix(np.array([0.5, -1.25, 2.0])))
for name, rr in res: print(name, rr)
print(SR.summary(res))        # OK()
