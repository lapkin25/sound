# verify_projectile.py - перекрёстная проверка узла Octave на эталоне Python
import numpy as np, trio_bridge as tb, sound_front as F

# 1) статика спеки: SC-060 не срабатывает - приёмник объявлен
sp = F.parse_spec(open('projectile.sound').read())
print('static:', F.static_checks(sp) or '[]')

# 2) байт-в-байт: файл Octave совпадает с эталоном моста (T2-аналог)
oct_bytes = open('projectile_sin2a_45.tri', 'rb').read()
ref_bytes = tb.write_matrix(np.array([1.0]))
print('sin2a bytes equal:', oct_bytes == ref_bytes)

oct_R = open('projectile_range_45.tri', 'rb').read()
r = tb.read_matrix(oct_R)
print('R parsed:', r)
print('R canon:', tb.canon_float(r.v[0]))

# 3) журнал: побайтное сравнение с эталонным
ref_log = [
    'bind s  = Float64 0x1.0000000000000p+0',
    'bind t0 = Float64 0x1.3880000000000p+9',
    'bind t1 = Float64 0x1.a1887b2c1a188p-4',
    'bind t2 = Float64 0x1.fdaf1a5b55dafp+5',
    'result  = Float64 0x1.fdaf1a5b55dafp+5',
]
oct_log = open('projectile_journal.txt').read().splitlines()
print('journal equal:', oct_log == ref_log)
