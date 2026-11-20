# mult.py - умножение столбиком: свёртка столбцов через Part, перенос через FoldList
# Запуск: python3 mult.py   (в папке с sound_snap2.py)
#
# Жанр: столбец k - это сумма a[i]*b[k-i] по всем i. Внутренний Fold несёт
# упакованный аккумулятор acc = k*100000 + sum (оба целые, сумма < 100000 -
# упаковка точна); k извлекается Quotient'ом, цифры - Part'ом.
# Внешний FoldList тащит s_k = colsum(k) + carry(k-1); цифра = Mod[s,10].
# Провода: значение цифр против скалярного p = n*m и против независимого
# графа decompose(p); саботаж одного разряда обязан зазвенеть.

from sound_snap2 import Session, canon_bits

PRELUDE = '''
mul10[x_] := x * 10.0
ident[x_] := x
dig_a[i_] := Mod[Quotient[n, Nest[mul10, 1.0, i]], 10.0]
dig_m[i_] := Mod[Quotient[m, Nest[mul10, 1.0, i]], 10.0]
gv[i_, k_] := If[If[k - i >= 0.0, If[k - i < 5.0, 1.0, 0.0], 0.0] == 1.0, Part[digs_a, i] * Part[digs_b, k - i], 0.0]
ifun[acc_, i_] := acc + gv[i, Quotient[acc, 100000.0]]
colfun[acc_, k_] := Mod[Fold[ifun, k * 100000.0 + Quotient[acc, 10.0], I], 100000.0]
dfun[k_] := Mod[Part[sl, k + 1.0], 10.0]
pvf[k_] := Part[digs_prod, k] * Nest[mul10, 1.0, k]
pdig[k_] := Mod[Quotient[p, Nest[mul10, 1.0, k]], 10.0]
eqf[k_] := Part[digs_prod, k] == Part[digs_ref, k]
badf[k_] := Part[digs_bad, k] == Part[digs_ref, k]
corf[k_] := If[k == 3.0, 9.0, Part[digs_prod, k]]
add2[x_, y_] := x + y
umul[a_, x_] := a * x
'''

def show(s, name):
    v = s.env[name]
    if isinstance(v, float):
        return '<СКАЛЯР %r - здесь ждали список!>' % v
    return '{%s}' % ', '.join('%g' % x for x in v)

def scenario():
    print('== Умножение столбиком: свёртка + перенос, провода и саботаж ==')
    s = Session()
    s.execute('n = 5202.0')
    s.execute('m = 6997.0')
    s.execute('p = n * m')
    for st in PRELUDE.strip().splitlines():
        s.execute(st.strip())

    s.execute('I = Table[ident, 5.0]')
    s.execute('K = Table[ident, 10.0]')
    s.execute('digs_a = Table[dig_a, 5.0]')
    s.execute('digs_b = Table[dig_m, 5.0]')
    print('  digs_a = %s   (младший разряд первым)' % show(s, 'digs_a'))
    print('  digs_b = %s' % show(s, 'digs_b'))

    s.execute('sl = FoldList[colfun, 0.0, K]')
    print('  столбцы s_k (colsum + carry): %s' % show(s, 'sl'))

    s.execute('digs_prod = Table[dfun, 10.0]')
    print('  digs_prod = %s' % show(s, 'digs_prod'))

    # провод 1: значение цифр против скалярного произведения
    s.execute('val = Fold[add2, 0.0, Table[pvf, 10.0]]')
    ok2 = canon_bits(s.env['val']) == canon_bits(s.env['p'])
    print('  провод [значение против скалярного p = %r]: %s'
          % (s.env['p'], 'сошлись' if ok2 else 'ДИССОНАНС'))

    # провод 2: цифры против независимого графа decompose(p)
    s.execute('digs_ref = Table[pdig, 10.0]')
    s.execute('eqs = Table[eqf, 10.0]')
    s.execute('allok = Fold[umul, 1.0, eqs]')
    ok1 = (s.env['allok'] == 1.0)
    print('  провод [digs_prod против decompose(p)]: %s'
          % ('сошлись' if ok1 else 'ДИССОНАНС'))

    # саботаж: разряд 3: 8 -> 9
    s.execute('digs_bad = Table[corf, 10.0]')
    s.execute('eqbad = Table[badf, 10.0]')
    s.execute('badok = Fold[umul, 1.0, eqbad]')
    sab = (s.env['badok'] == 0.0)
    print('  саботаж: разряд 3: 8 -> 9 -> %s'
          % ('провод зазвенел' if sab else 'ПОДДЕЛКА ПРОШЛА'))

    print('  журнал: %d строк' % len(s.journal))
    return ok2 and ok1 and sab

if __name__ == '__main__':
    ok = scenario()
    print('---')
    print('ALL PASS' if ok else 'FAILED')
