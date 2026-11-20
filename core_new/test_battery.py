#!/usr/bin/env python3
# test_battery.py — самопроверка пакета Sound + TRIOMAT v0.2
# Каждый чек помечен ярлыком и соответствует разделу документации.
# Запуск:  python3 test_battery.py
# Ожидаемый вывод в конце: ALL PASS (NN/NN)

import math
import trio_bridge as tb
import sound_core3 as C
import sound_front as F
import sound_reader as SR

_FAILS = []
def ck(label, cond):
    if not cond:
        _FAILS.append(label)
    print(("PASS " if cond else "FAIL ") + label)

# ============ 1. Мост: формат TRIOMAT1 ============
import numpy as np

# -- T1 roundtrip C-порядок --
m = np.array([[1., 2.], [3., 4.]])
r = tb.read_matrix(tb.write_matrix(m))
ck("T1  roundtrip C", r.ok and np.array_equal(r.v, m) and r.v.flags["C_CONTIGUOUS"])

# -- T2 вариант Б: F- и C-источники дают одинаковый файл --
a = np.asfortranarray([[1., 2.], [3., 4.]])
b = np.ascontiguousarray([[1., 2.], [3., 4.]])
ck("T2  вариант Б", tb.pack_octave(a) == tb.write_matrix(b))

# -- T3 unpack_octave восстанавливает значения и F-хранилище --
r = tb.unpack_octave(tb.pack_octave(a))
ck("T3  unpack F", r.ok and np.array_equal(r.v, a) and r.v.flags["F_CONTIGUOUS"])

# -- T4 канон float --
ck("T4a canon 3.0",    tb.canon_float(3.0)  == "0x1.8000000000000p+1")
ck("T4b canon -2.25",  tb.canon_float(-2.25) == "-0x1.2000000000000p+1")
ck("T4c canon 0",      tb.canon_float(0.0)   == "0x0.0p+0")
ck("T4d canon -0.0",   tb.canon_float(-0.0)  == "-0x0.0p+0")
ck("T4e canon inf",    tb.canon_float(float("inf")) == "inf")
ck("T4f canon nan",    tb.canon_float(float("nan")) == "nan")

# -- T5 R-INT1: Lossy с 2^53-1 включительно, Err за Int64 --
ck("T5a INT1 lossy on 2^53-1", tb.int_check(2**53 - 1).lossy)
ck("T5b INT1 ok below",        not tb.int_check(2**52).lossy and tb.int_check(2**52).ok)
ck("T5c INT1 err beyond int64", (not tb.int_check(2**63).ok) and tb.int_check(2**63).code == "IntRangeOverflow")

# -- T6 R-INT3: неинтегральный float -> Lossy --
r = tb.to_int_exact(1.5)
ck("T6  INT3", r.lossy and r.n == 2)
ck("T6b INT3 integral", tb.to_int_exact(4.0).ok and not tb.to_int_exact(4.0).lossy)

# -- T7 Bool по сырым байтам --
_bh = b'{"dtype":"Bool","shape":[1]}'
bad = tb.MAGIC + len(_bh).to_bytes(4, "little") + _bh + bytes([2])
ck("T7  bool raw bytes", (not tb.read_matrix(bad).ok) and tb.read_matrix(bad).code == "TypeMismatch")

# -- T8 повреждённые файлы --
good = tb.write_matrix(np.array([1.0, 2.0]))
ck("T8a short file",     tb.read_matrix(good[:5]).code == "MalformedHeader")
ck("T8b bad magic",      tb.read_matrix(b"XXXXXXXX" + good[8:]).code == "MalformedHeader")
ck("T8c truncated hdr",  tb.read_matrix(good[:11]).code == "MalformedHeader")
hdr_len = int.from_bytes(good[8:12], "little")
_h2 = b'{"dtype":"Complex64","shape":[2]}'
bad_dt = good[:8] + len(_h2).to_bytes(4, "little") + _h2 + good[12+hdr_len:]
ck("T8d unknown dtype",  tb.read_matrix(bad_dt).code == "MalformedDtype")
ck("T8e payload size",   tb.read_matrix(good[:-1]).code == "MalformedPayload")

# -- T9 unify: срез Matrix/C/F, сравнение размерностей --
ck("T9a unify Matrix tag", tb.unify("Matrix[2,3]", [2, 3]))
ck("T9b unify C/F",        tb.unify("Matrix[2,3]C", "Matrix[2,3]F"))
ck("T9c unify mismatch",   not tb.unify([2, 3], [3, 2]))

# -- T10 R-ERR2: агрегация --
ck("T10a err dominates", tb.aggregate([tb.Lossy(1), tb.Err("Timeout")]).code == "Timeout")
ck("T10b empty -> lost", tb.aggregate([]).code == "ResourceLost")
ck("T10c lossy sums",    tb.aggregate([tb.Lossy(2), tb.Lossy(3)]).lossy)

# ============ 2. Ядро: арифметика, журнал, замыкания ============

# -- T11 арифметика и приоритеты --
ck("T11a int add",  C.run(["+", ["lit", 2], ["lit", 3]]).v == 5)
ck("T11b int div",  C.run(["/", ["lit", 3], ["lit", 2]]).v == 1)
ck("T11c int div trunc", C.run(["/", ["lit", -3], ["lit", 2]]).v == -1)
ck("T11d cmp",      C.run(["<", ["lit", 2], ["lit", 3]]).j() == "Bool true")

# -- T12 IEEE-деление --
ck("T12a 1/0 -> +inf", C.run(["/", ["lit", 1.0], ["lit", 0.0]]).j() == "Float64 inf")
ck("T12b -1/0 -> -inf", C.run(["/", ["lit", -1.0], ["lit", 0.0]]).j() == "Float64 -inf")
ck("T12c 0/0 -> NaN OutsideDomain", C.run(["/", ["lit", 0.0], ["lit", 0.0]]).code == "NaNOutsideDomain")
INF = float("inf")
ck("T12d inf-inf",  C.run(["-", ["lit", INF], ["lit", INF]]).code == "NaNOutsideDomain")
ck("T12e inf*0",    C.run(["*", ["lit", INF], ["lit", 0.0]]).code == "NaNOutsideDomain")

# -- T13 целочисленное деление на ноль и переполнение --
ck("T13a div by zero", C.run(["/", ["lit", 1], ["lit", 0]]).code == "DivisionByZero")
ck("T13b overflow",    C.run(["+", ["lit", tb.INT64_MAX], ["lit", 1]]).code == "IntRangeOverflow")

# -- T14 журнал: bind с '=', result без '=', детерминизм --
r1 = C.Run()
C.run(["let", "x", ["lit", 2], ["+", ["sym", "x"], ["lit", 3]]], r1)
ck("T14a journal", r1.log == ["bind x = Int64 2", "bind t0 = Int64 5", "result Int64 5"])
r2 = C.Run()
C.run(["let", "x", ["lit", 2], ["+", ["sym", "x"], ["lit", 3]]], r2)
ck("T14b deterministic", r1.log == r2.log)
ck("T14c no '=' in result", all(not l.startswith("result ") or " = " not in l for l in r1.log))

# -- T15 let и if --
ck("T15a let",  C.run(["let", "x", ["lit", 2], ["*", ["sym", "x"], ["lit", 10]]]).v == 20)
ck("T15b if t", C.run(["if", ["lit", True], ["lit", 1], ["lit", 2]]).v == 1)
ck("T15c if f", C.run(["if", ["lit", False], ["lit", 1], ["lit", 2]]).v == 2)

# -- T16 замыкания и частичное применение --
C.REGISTRY.clear()
C.register_fn("add", ["a", "b"], ["+", ["sym", "a"], ["sym", "b"]])
g = C.call_fn(C._mk_clo("add", C.REGISTRY), [C.VInt(100)], C.Run())
ck("T16a partial apply", C.call_fn(g, [C.VInt(5)], C.Run()).v == 105)
C.register_fn("mk", ["x"], ["let", "y", ["sym", "x"], ["+", ["sym", "y"], ["lit", 2]]])
f = C._mk_clo("mk", C.REGISTRY)
ck("T16b closure", C.call_fn(f, [C.VInt(10)], C.Run()).v == 12)
ck("T16c unknown name", C.run(["sym", "nope"]).code == "UnknownName")

# -- T17 widen_lossy --
v, l = C.widen_lossy(C.VInt(3), C.VFloat(0.5))
ck("T17a widen to float", isinstance(v, C.VFloat) and not l)
v, l = C.widen_lossy(C.VInt(2**53 - 1), C.VFloat(0.5))
ck("T17b widen lossy at 2^53-1", isinstance(v, C.VFloat) and l)

# ============ 3. Фронтенд: парсер, сериализация, проверки ============

SPEC = (
    "spec mixer ;\n"
    "fact gain 2 ;\n"
    "wire src -> scaled ;\n"
    "rule scaled x = x * gain ;\n"
    "pure rule trim x: Matrix[2,2] = x * 0.5 invariant x >= 0 ;\n"
)

# -- T18 разбор и roundtrip --
sp = F.parse_spec(SPEC)
ck("T18a spec name", sp[1] == "mixer")
ck("T18b item count", len(sp[2]) == 4)
ck("T18c roundtrip",  F.roundtrip(SPEC))
ck("T18d serialize order", F.serialize(sp).splitlines()[1] == "fact gain 2 ;")

# -- T19 модификаторы в обоих порядках --
ck("T19a pure",  F.parse_spec("spec s ; pure rule r x = x ;")[2][0][5] == ["pure"])
ck("T19b safe pure", F.parse_spec("spec s ; safe pure rule r x = x ;")[2][0][5] == ["pure", "safe"])

# -- T20 параметры: пробел, тип, Matrix --
r3 = F.parse_spec("spec s ; rule f x y: Int64 = x ;")[2][0]
ck("T20a params space", [p[0] for p in r3[2]] == ["x", "y"])
ck("T20b param type",   r3[2][1][1] == ("Name", "Int64"))
r4 = F.parse_spec("spec s ; rule m p: Matrix[2,2]C = p ;")[2][0]
ck("T20c Matrix type",  r4[2][0][1] == ("Matrix", [2, 2], "C"))

# -- T21 лексер: ?, скобки, kw --
kinds = [k for k, _ in F.lex("a ? (invariant) ;")]
ck("T21a lexer tokens", kinds == ["id", "op", "op", "kw", "op", "op", "eof"])
lexed = F.lex("in")
ck("T21b kw 'in'", lexed[0] == ("kw", "in"))
ck("T21c num 1.5", F.lex("1.5")[0] == ("num", 1.5))

# -- T22 статические проверки и порядок --
ck("T22a clean spec", F.static_checks(sp) == [])
ck("T22b SC-060",     F.static_checks(F.parse_spec("spec s ; wire A -> B ;")) == ["SC-060"])
ck("T22c SC-002",     F.static_checks(F.parse_spec("spec s ; rule r x = q + 1 ;")) == ["SC-002"])

# ============ 4. Ридер: 9 проверок ============

# -- T23 полный файл: все 9 зелёные --
res = SR.read_file(tb.write_matrix(np.array([0.5, -1.25, 2.0])))
ck("T23a nine checks", len(res) == 9)
ck("T23b all ok", all(r.ok for _, r in res))
ck("T23c summary", SR.summary(res).ok and not SR.summary(res).lossy)

# -- T24 пустой файл --
res = SR.read_file(b"")
ck("T24a stopped early", len(res) == 1)
ck("T24b resource lost", res[0][1].code == "ResourceLost")

# -- T25 мусор вместо magic --
res = SR.read_file(b"XY" * 10)
ck("T25 header frame", res[-1][1].code == "MalformedHeader")

# -- T26 неверный размер payload --
data = bytearray(tb.write_matrix(np.array([1.0, 2.0])))
res = SR.read_file(bytes(data[:-1]))
ck("T26 payload size", res[-1][1].code == "MalformedPayload")

# ============ Итог ============
print()
if _FAILS:
    print("FAILURES: %d -> %s" % (len(_FAILS), ", ".join(_FAILS)))
    raise SystemExit(1)
total = 0
with open(__file__) as f:
    total = sum(1 for line in f if line.lstrip().startswith('ck("'))
print("ALL PASS (%d/%d)" % (total, total))
