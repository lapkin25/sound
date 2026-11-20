# accounting.py - двойная запись поверх регистров Sound-учёта
# Запуск: python3 accounting.py   (в папке с sound_snap2.py и ledger.py)
#
# Жанр: документ = вектор фактов [(счёт, дельта), ...]; дельта > 0 - дебет,
# < 0 - кредит. Документ проводится в чистой черновой сессии, инвариант
# сохранения суммы и провод Fold-графа решают его судьбу до касания журнала.
# Несбалансированный документ версии не порождает.

import json, tempfile, os
from sound_snap2 import Session, canon_bits
from ledger import Register, wire, replay_check

ACCOUNTS = ['cash', 'goods', 'bank']


def doc2stmts(doc):
    return ['%s = %s + %r' % (a, a, d) for a, d in doc]


def show(reg):
    s = reg.s
    print('  остатки: ' + ', '.join('%s=%r (0x%s)' % (a, s.env[a], canon_bits(s.env[a]))
                                    for a in ACCOUNTS))


def post_document(reg, doc, label):
    """Проводка документа: черновая сессия, инвариант суммы, провод против Fold.
    Документ либо проводится целиком, либо не существует вовсе."""
    s = reg.s
    draft = Session()
    draft.funcs = dict(s.funcs)
    draft.env = dict(s.env)
    stmts = doc2stmts(doc)
    for st in stmts:
        draft.execute(st)
    before = sum(s.env[a] for a in ACCOUNTS)
    after = sum(draft.env[a] for a in ACCOUNTS)
    lst = '{' + ', '.join(ACCOUNTS) + '}'
    folded = draft.execute('Fold[add2, 0.0, %s]' % lst)
    ok_save = canon_bits(before) == canon_bits(after)
    ok_wire = canon_bits(folded) == canon_bits(after)
    tag = 'сошлись' if (ok_save and ok_wire) else 'ДИССОНАНС 150 Гц'
    print('  [%s] сумма до 0x%s, после 0x%s, Fold 0x%s -> %s'
          % (label, canon_bits(before), canon_bits(after), canon_bits(folded), tag))
    if not (ok_save and ok_wire):
        print('    документ ОТКЛОНЁН: несбалансирован, версии не будет')
        return None
    for st in stmts:
        s.execute(st)
    vid = reg.commit(label)
    show(reg)
    return vid


def scenario():
    print('== Двойная запись: документы, инвариант суммы, ветвление ==')
    s = Session()
    for a, v in [('cash', 1000.0), ('goods', 0.0), ('bank', 0.0)]:
        s.execute('%s = %r' % (a, v))
    s.execute('add2[x_, y_] := x + y')
    reg = Register(s, 'гл')
    V0 = reg.commit('открытие: cash 1000.0, goods 0.0, bank 0.0')
    show(reg)

    doc1 = [('goods', 400.0), ('cash', -400.0)]
    V1 = post_document(reg, doc1, 'покупка товара: debit goods +400, credit cash -400')

    doc2 = [('bank', 300.0), ('goods', -300.0)]
    V2 = post_document(reg, doc2, 'продажа товара: debit bank +300, credit goods -300')

    # саботаж: дебет 400 против кредита 250 - сумма обязана зазвенеть
    post_document(reg, [('goods', 400.0), ('cash', -250.0)],
                  'саботаж: дебет 400 против кредита 250')

    # ветвление из той же точки V0: альтернативная закупка
    reg.checkout(V0)
    doc3 = [('goods', 500.0), ('cash', -500.0)]
    V3 = post_document(reg, doc3, 'ветка B: альтернативная закупка 500')

    print('  дерево версий:')
    for row in reg.tree():
        print('    ' + row)

    ok1 = replay_check(reg, V0, V1, doc2stmts(doc1))
    ok2 = replay_check(reg, V0, V2, doc2stmts(doc1) + doc2stmts(doc2))
    ok3 = replay_check(reg, V0, V3, doc2stmts(doc3))
    print('  аудит-реплей V1: журнал %s, last %s' % ok1)
    print('  аудит-реплей V2 (два документа): журнал %s, last %s' % ok2)
    print('  аудит-реплей V3 (ветка B): журнал %s, last %s' % ok3)
    ok_chain = reg.chain_ok(V2)
    print('  префикс-непрерывность цепочки V0->V1->V2: %s' % ok_chain)

    # провода учёт против расчётов: остаток каждого счёта против Fold по потокам
    reg.checkout(V2)
    s.execute('apply2[x_, y_] := x + y')
    cash_fold = s.execute('Fold[apply2, 1000.0, {-400.0}]')
    ok_w1 = wire('cash: остаток против Fold потоков', s.env['cash'], cash_fold)
    bank_fold = s.execute('Fold[apply2, 0.0, {300.0}]')
    ok_w2 = wire('bank: остаток против Fold потоков', s.env['bank'], bank_fold)
    goods_fold = s.execute('Fold[apply2, 0.0, {400.0, -300.0}]')
    ok_w3 = wire('goods: остаток против Fold потоков', s.env['goods'], goods_fold)

    # ветви разошлись честно: cash в V2 и V3 различны по битам
    cashV2 = reg.versions[V2]['snap']['names']['cash']
    cashV3 = reg.versions[V3]['snap']['names']['cash']
    diverged = cashV2 != cashV3
    print('  расхождение ветвей: cash V2 = %s против cash V3 = %s -> %s'
          % (cashV2, cashV3, 'ветви разошлись' if diverged else 'ветви совпали?!'))

    # тампер-тест: одна испорченная строка журнала обязана взорвать отпечаток
    bad = json.loads(json.dumps(reg.versions[V1]['snap']))
    bad['journal'][-1] += ' x'
    fd, p = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(bad, f, ensure_ascii=False)
        probe = Session()
        try:
            probe.restore(p)
            tamper_ok = False
        except Exception:
            tamper_ok = True
    finally:
        os.unlink(p)
    print('  тампер-тест: подделка строки журнала -> %s'
          % ('отпечаток поднял ошибку' if tamper_ok else 'ПОДДЕЛКА ПРОШЛА НЕЗАМЕТНО'))

    return (ok1 == (True, True) and ok2 == (True, True) and ok3 == (True, True)
            and ok_chain and ok_w1 and ok_w2 and ok_w3 and diverged and tamper_ok)


if __name__ == '__main__':
    ok = scenario()
    print('---')
    print('ALL PASS' if ok else 'FAILED')
