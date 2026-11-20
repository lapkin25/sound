import numpy as np, trio_bridge as tb, sound_core3 as C, sound_front as F, sound_reader as SR

m = np.array([[1.,2.],[3.,4.]])
print(tb.read_matrix(tb.write_matrix(m)))            # OK(array)
print(tb.canon_float(3.0))                            # 0x1.8000000000000p+1
print(C.run(["/", ["lit",1.0], ["lit",0.0]]).v)       # inf
print(C.run(["/", ["lit",1], ["lit",0]]).code)        # DivisionByZero
C.register_fn("add2", ["a","b"], ["+",["sym","a"],["sym","b"]])
g = C.call_fn(C._mk_clo("add2", C.REGISTRY), [C.VInt(100)], C.Run())
print(C.call_fn(g, [C.VInt(5)], C.Run()).v)           # 105
sp = F.parse_spec("spec s1 ;\nwire A -> B ;\npure rule scale x = x * 2 invariant x > 0 ;\n")
print(F.roundtrip(F.serialize(sp)))                   # True
