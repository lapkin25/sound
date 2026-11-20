# report.py - оборотно-сальдовая ведомость как чистый граф поверх снапшота
# Запуск: python3 report.py   (в папке с sound_snap2.py, ledger.py, accounting.py)
#
# Жанр: отчёт не трогает журнал. Он вычисляется из документов (векторов фактов)
# в чистой сессии и сверяется проводами с регистром: сальдо конечное =
# (сальдо начальное + дебетовый оборот) + кредитовый оборот, бит-в-бит.
# Отдельный стресс показывает: агрегатный граф группирует обороты иначе, чем
# регистровый - на переассоциационных данных (0.1-потоки) провод обязан звенеть.
# Это не баг, а честность провода: для дробных сумм ведомость обязана считаться
# каноническим графом регистра, а провод остаётся стражем равенства графов.

from sound_snap2 import Session, canon_bits
from ledger import Register, wire
from accounting import ACCOUNTS, post_document


def fold(r, name, acc0, items):
    if not items:
        return acc0
    lst = '{' + ', '.join(repr(x) for x in items) + '}'
    return r.execute('Fold[%s, %r, %s]' % (name, acc0, lst))


def build_report(reg, opening_vid, docs, closing_vid, accounts):
    reg.checkout(opening_vid)
    opening = dict((a, reg.s.env.get(a, 0.0)) for a in accounts)
    reg.checkout(closing_vid)
    actual = dict((a, reg.s.env.get(a, 0.0)) for a in accounts)
    r = Session()
    r.funcs = dict(reg.s.funcs)
    flows = dict((a, [d for _, doc in docs for acc, d in doc if acc == a]) for a in accounts)
    rows = []
    ok_all = True
    for a in accounts:
        deb = fold(r, 'add2', 0.0, [d for d in flows[a] if d > 0])
        cred = fold(r, 'add2', 0.0, [d for d in flows[a] if d < 0])
        closing = r.execute('clos_%s = (%r + %r) + %r' % (a, opening[a], deb, cred))
        ok = canon_bits(closing) == canon_bits(actual[a])
        ok_all = ok_all and ok
        rows.append((a, opening[a], deb, cred, closing, ok))
    return rows, ok_all


def print_table(rows):
    print('  %-7s|%13s|%9s|%10s|%13s|%11s'
          % ('счёт', 'сальдо нач.', 'дебет', 'кредит', 'сальдо кон.', 'сверка'))
    for a, o, deb, cred, cl, ok in rows:
        print('  %-7s|%13.2f|%9.2f|%10.2f|%13.2f|%11s'
              % (a, o, deb, cred, cl, 'сошлись' if ok else 'ДИССОНАНС'))


def scenario():
    print('== Оборотно-сальдовая ведомость: чистый граф над снапшотом ==')
    s = Session()
    for a, v in [('cash', 1000.0), ('goods', 0.0), ('bank', 0.0)]:
        s.execute('%s = %r' % (a, v))
    s.execute('add2[x_, y_] := x + y')
    reg = Register(s, 'гл')
    V0 = reg.commit('открытие: cash 1000.0, goods 0.0, bank 0.0')

    docs = [
        ('покупка товара', [('goods', 400.0), ('cash', -400.0)]),
        ('продажа товара', [('bank', 300.0), ('goods', -300.0)]),
    ]
    chain = [V0]
    for label, doc in docs:
        chain.append(post_document(reg, doc, label))
    V2 = chain[-1]

    print('  ведомость по цепочке %s -> %s -> %s:' % (V0, chain[1], V2))
    rows, ok_rows = build_report(reg, V0, docs, V2, ACCOUNTS)
    print_table(rows)

    # итог по оборотам: сумма всех дебетов = сумме всех кредитов
    # (инвариант двойной записи на уровне всего отчёта)
    all_deltas = [d for _, doc in docs for _, d in doc]
    rr = Session()
    rr.funcs = dict(reg.s.funcs)
    deb_tot = fold(rr, 'add2', 0.0, [d for d in all_deltas if d > 0])
    cred_tot = fold(rr, 'add2', 0.0, [d for d in all_deltas if d < 0])
    ok_bal = wire('итог: сумма дебетов против суммы кредитов', deb_tot, -cred_tot)

    # стресс: 0.1-потоки. Регистр применяет документы последовательно,
    # отчёт группирует обороты - графы различны, провод обязан звенеть.
    print('  стресс: 0.1-потоки - агрегатный граф против регистрового')
    s2 = Session()
    s2.execute('cash = 0.0')
    s2.execute('X = 0.0')
    s2.execute('add2[x_, y_] := x + y')
    reg2 = Register(s2, 'стресс')
    U0 = reg2.commit('открытие: cash 0.0, X 0.0')
    stress_docs = [
        ('д1', [('X', 0.1), ('cash', -0.1)]),
        ('д2', [('X', -0.1), ('cash', 0.1)]),
        ('д3', [('X', 0.2), ('cash', -0.2)]),
    ]
    for label, doc in stress_docs:
        for a, d in doc:
            reg2.s.execute('%s = %s + %r' % (a, a, d))
        reg2.commit(label)
    rows2, ok2 = build_report(reg2, U0, stress_docs, reg2.current, ['X', 'cash'])
    print_table(rows2)
    for a, o, deb, cred, cl, ok in rows2:
        if not ok:
            print('    %s: граф 0x%s против регистра 0x%s' %
                  (a, canon_bits(cl), canon_bits(reg2.s.env[a])))
    print('  вердикт: ДИССОНАНС здесь ожидаем и честен. Агрегатный граф группирует')
    print('  обороты иначе, чем регистровый, и на 0.1-потоках это даёт соседний ulp.')
    print('  Жанр требует канонического графа: для дробных сумм ведомость считается')
    print('  тем же графом, что регистр, а провод остаётся стражем равенства графов.')
    stressed = not ok2

    return ok_rows and ok_bal and stressed


if __name__ == '__main__':
    ok = scenario()
    print('---')
    print('ALL PASS' if ok else 'FAILED')
