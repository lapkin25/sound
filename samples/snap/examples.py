# examples.py — рабочие примеры поверх sound_snap2.py
# Запуск: python3 examples.py   (в папке, где лежит sound_snap2.py)
# Снапшот snap_R.json создаётся примером 2 (мини-учёт).
# Примечание: голое выражение должно начинаться с имени (предел грамматики),
# поэтому константные выражения пишутся через присваивание — это честно
# отражается в журнале строкой set(...).

import math
from sound_snap2 import Session, canon_bits

def wire(label, a, b):
    ha, hb = canon_bits(a), canon_bits(b)
    ok = ha == hb
    tag = 'совпали' if ok else 'ДИССОНАНС 150 Гц'
    print('  провод [%s]: %s vs %s -> %s' % (label, ha, hb, tag))
    return ok

# ------------------------------------------------------------------
# Пример 1. Вклад: три года по 5%, один Fold, эталонное сравнение
# ------------------------------------------------------------------
def demo_deposit():
    print('== Пример 1. Вклад: 1000.0 под 5 процентов, три года ==')
    s = Session()
    s.execute('grow[acc_, r_] := acc * (1.0 + r)')
    total = s.execute('Fold[grow, 1000.0, {0.05, 0.05, 0.05}]')
    print('  итог Fold: 0x%s = %r | журнал %d биндов' % (canon_bits(total), total, len(s.journal)))
    # эталон теми же операциями, тем же порядком: ((1000*1.05)*1.05)*1.05
    ref = 1000.0
    for _ in range(3):
        ref = ref * (1.0 + 0.05)
    print('  эталон   : 0x%s = %r' % (canon_bits(ref), ref))
    ok1 = wire('Fold против эталона', total, ref)
    # а вот наивная запись 1000.0*1.05**3 — другой граф, другие округления:
    naive = 1000.0 * 1.05**3
    print('  1000.0*1.05**3: 0x%s = %r' % (canon_bits(naive), naive))
    wire('наивная запись', total, naive)
    print('  вердикт: граф «как написано» совпадает с эталоном бит-в-бит,'
          ' а перегруппировка даёт соседний ulp — запрет реассоциации в действии')
    return ok1

# ------------------------------------------------------------------
# Пример 2. Мини-учёт: инвариант остатка и откат недопустимой проводки
# ------------------------------------------------------------------
def demo_ledger():
    print('== Пример 2. Мини-учёт: проводки с инвариантом ==')
    s = Session()
    s.execute('balance = 1000.0')
    s.execute('allowed[x_, amt_] := amt <= x')
    s.execute('withdraw[x_, amt_] := x - amt')
    R = s.save('snap_R.json')
    print('  снимок R: остаток 0x%s, журнал %d биндов' %
          (R['names']['balance'], len(R['journal'])))

    plan = [300.0, 200.0, 600.0]   # третья проводка валит инвариант
    blocked_at = None
    for i, amt in enumerate(plan):
        gate = s.execute('allowed[balance, %r]' % amt)
        if gate == 1.0:
            s.execute('balance = withdraw[balance, %r]' % amt)
            print('  проводка -%r: допущена, остаток 0x%s' % (amt, canon_bits(s.env['balance'])))
        else:
            blocked_at = i
            print('  проводка -%r: ЗАБЛОКИРОВАНА инвариантом (amt > x)' % amt)
            break

    # демонстрация отката: применяем нарушителя наивно, видим минус, откатываем
    s.execute('balance = withdraw[balance, 600.0]')
    print('  наивная проводка: остаток 0x%s = %r -> нарушение инварианта' %
          (canon_bits(s.env['balance']), s.env['balance']))
    s.restore('snap_R.json')
    print('  restore R: остаток 0x%s, отпечаток журнала сошёлся' %
          canon_bits(s.env['balance']))
    return blocked_at == 2 and s.env['balance'] == 1000.0

# ------------------------------------------------------------------
# Пример 3. Два графа, один итог: провод-сверка
# ------------------------------------------------------------------
def demo_wires():
    print('== Пример 3. Провода: сверка независимых графов ==')
    s = Session()
    s.execute('add[x_, y_] := x + y')
    a = s.execute('Fold[add, 0.0, {1.0, 2.0, 3.0, 4.0, 5.0}]')  # цикл сложения
    b = s.execute('g = 5.0 * 6.0 / 2.0')                        # формула Гаусса
    print('  цикл: %r | формула: %r' % (a, b))
    ok1 = wire('сумма 1..5: цикл против формулы', a, b)

    # расходящийся провод — учебный саботажник: 0.1 + 0.2 против 0.3
    c = s.execute('c = 0.1 + 0.2')
    d = s.execute('d = 0.3')
    print('  0.1 + 0.2 = %r | 0.3 = %r' % (c, d))
    ok2 = not wire('классика IEEE: 0.1+0.2 против 0.3', c, d)
    print('  вердикт: провод честен в обе стороны — сходящиеся графы молчат,'
          ' расходящиеся звенят')
    return ok1 and ok2

if __name__ == '__main__':
    r1 = demo_deposit()
    r2 = demo_ledger()
    r3 = demo_wires()
    print('---')
    print('ALL PASS' if (r1 and r2 and r3) else 'FAILED')
