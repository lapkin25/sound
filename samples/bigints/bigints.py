# bigints.py - длинная арифметика: разряды как списки, сложение с переносом
# Запуск: python3 bigints.py   (в папке с sound_snap2.py)
#
# Жанр: длинное число - список цифр, младший разряд первым (индекс = вес).
# Сложение: пары разрядов пакуются в один дабл (d1*100+d2 - обе цифры < 100,
# значит упаковка и распаковка точны), FoldList тащит аккумулятор
# acc = carry*10 + digit - перенос и разряд едут в одном значении.
# Провода: длинная сумма против независимого графа DigitList[ns],
# значение против скаляра; саботаж одного разряда обязан зазвенеть.

from sound_snap2 import Session, canon_bits

W = 5  # ширина сетки: n, m < 10^4, сумма < 10^5

PRELUDE = '''
mul10[x_] := x * 10.0
dig[i_]  := Mod[Quotient[n, Nest[mul10, 1.0, i]], 10.0]
digm[i_] := Mod[Quotient[m, Nest[mul10, 1.0, i]], 10.0]
prf[i_]  := Part[digs_a, i] * 100.0 + Part[digs_b, i]
s1[acc_, p_] := Quotient[acc, 10.0] + Quotient[p, 100.0] + Mod[p, 100.0]
addcarry[acc_, p_] := Quotient[s1[acc, p], 10.0] * 10.0 + Mod[s1[acc, p], 10.0]
dfun[i_] := Mod[Part[cc, i + 1.0], 10.0]
pvf[i_]  := Part[digs_sum, i] * Nest[mul10, 1.0, i]
refd[i_] := Mod[Quotient[ns, Nest[mul10, 1.0, i]], 10.0]
eqf[i_]  := Part[digs_sum, i] == Part[digs_ref, i]
badf[i_] := Part[digs_bad, i] == Part[digs_ref, i]
corf[i_] := If[i == 2.0, 3.0, Part[digs_sum, i]]
add2[x_, y_] := x + y
umul[a_, x_] := a * x
'''


def show(s, name):
    return '{%s}' % ', '.join('%g' % v for v in s.env[name])


def scenario():
    print('== Длинная арифметика: разряды, Mod/Quotient, сложение с переносом ==')
    s = Session()
    s.execute('n = 5202.0')
    s.execute('m = 6997.0')
    s.execute('ns = n + m')
    for st in PRELUDE.strip().splitlines():
        s.execute(st.strip())

    s.execute('digs_a = Table[dig, %r]' % W)
    s.execute('digs_b = Table[digm, %r]' % W)
    print('  digs_a = %s   (младший разряд первым)' % show(s, 'digs_a'))
    print('  digs_b = %s' % show(s, 'digs_b'))

    s.execute('prs = Table[prf, %r]' % W)
    ok_pairs = all(s.env['prs'][i] == s.env['digs_a'][i] * 100.0 + s.env['digs_b'][i]
                   for i in range(W))
    print('  пары d1*100+d2 = %s -> %s'
          % (show(s, 'prs'), 'сошились' if ok_pairs else 'ДИССОНАНС'))

    s.execute('cc = FoldList[addcarry, 0.0, prs]')
    print('  FoldList (acc = carry*10 + digit): %s' % show(s, 'cc'))

    s.execute('digs_sum = Table[dfun, %r]' % W)
    print('  digs_sum = %s' % show(s, 'digs_sum'))

    # провод 1: длинное сложение против независимого графа - канонического
    # разложения скалярной суммы
    s.execute('digs_ref = Table[refd, %r]' % W)
    s.execute('eqs = Table[eqf, %r]' % W)
    s.execute('allok = Fold[umul, 1.0, eqs]')
    ok1 = (s.env['allok'] == 1.0)
    print('  провод [digs_sum против DigitList[ns]]: %s'
          % ('сошлись' if ok1 else 'ДИССОНАНС'))

    # провод 2: значение цифр против скалярного ns
    s.execute('val = Fold[add2, 0.0, Table[pvf, %r]]' % W)
    ok2 = canon_bits(s.env['val']) == canon_bits(s.env['ns'])
    print('  провод [значение против скалярного ns = %r]: %s'
          % (s.env['ns'], 'сошлись' if ok2 else 'ДИССОНАНС'))

    # саботаж: один разряд подменён - провод обязан зазвенеть
    s.execute('digs_bad = Table[corf, %r]' % W)
    s.execute('eqbad = Table[badf, %r]' % W)
    s.execute('badok = Fold[umul, 1.0, eqbad]')
    sab = (s.env['badok'] == 0.0)
    print('  саботаж: разряд 2: 1 -> 3 -> %s' % ('провод зазвенел' if sab else 'ПОДДЕЛКА ПРОШЛА'))

    return ok_pairs and ok1 and ok2 and sab


if __name__ == '__main__':
    ok = scenario()
    print('---')
    print('ALL PASS' if ok else 'FAILED')
