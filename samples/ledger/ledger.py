# ledger.py - регистры Sound-учёта: дерево версий снапшотов поверх sound_snap2.py
# Запуск: python3 ledger.py   (в папке с sound_snap2.py)
# Эффект: печатает проверки; снапшоты версий сохраняются в reg_*.json
#
# Жанр: регистр = сессия над снапшотом; проведение документа = продолжение
# программы; версия = commit снапшота с родителем; отклонённая инвариантом
# проводка версий не порождает вовсе.

import json, os, copy, tempfile
from sound_snap2 import Session, SoundError, canon_bits


def wire(label, a, b):
    ha, hb = canon_bits(a), canon_bits(b)
    ok = ha == hb
    print('  провод [%s]: %s vs %s -> %s' % (label, ha, hb,
                                             'совпали' if ok else 'ДИССОНАНС 150 Гц'))
    return ok


class Register:
    """Дерево версий регистра. Каждый commit - снапшот с родителем и отпечатком.
    Отклонённая проводка версии не порождает: недопустимой ветви нет не потому,
    что её спрятали, а потому, что она никогда не существовала."""

    def __init__(self, session, name='R'):
        self.s = session
        self.name = name
        self.versions = {}
        self.current = None
        self.counter = 0

    def commit(self, label):
        self.counter += 1
        vid = '%s-V%d' % (self.name, self.counter)
        snap = self.s.snapshot()
        # глубокая копия функций: снапшот обязан жить своей жизнью,
        # а не ссылаться на живое окружение сессии
        snap['funcs'] = copy.deepcopy(snap['funcs'])
        snap['fingerprint'] = self.s.fingerprint(snap)
        self.versions[vid] = {'parent': self.current, 'snap': snap, 'label': label}
        self.current = vid
        return vid

    def checkout(self, vid):
        if vid not in self.versions:
            raise KeyError('нет версии %s' % vid)
        self._restore_dict(self.versions[vid]['snap'])
        self.current = vid

    def _restore_dict(self, snap):
        fd, p = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(snap, f, ensure_ascii=False)
            self.s.restore(p)
        finally:
            os.unlink(p)

    def save_all(self, prefix='reg'):
        for vid, v in self.versions.items():
            with open('%s_%s.json' % (prefix, vid), 'w', encoding='utf-8') as f:
                json.dump(v['snap'], f, ensure_ascii=False, indent=1)

    def tree(self):
        rows = []
        for vid in sorted(self.versions, key=lambda v: int(v.rsplit('V', 1)[1])):
            v = self.versions[vid]
            rows.append('%s <- %s | %s' % (vid, v['parent'] or 'корень', v['label']))
        return rows

    def lineage(self, vid):
        out = []
        while vid is not None:
            out.append(vid)
            vid = self.versions[vid]['parent']
        return out[::-1]

    def chain_ok(self, vid):
        """Журнал каждого потомка продолжает журнал предка посимвольно:
        вся история регистра - один непрерывный след, разрезанный на версии."""
        lin = self.lineage(vid)
        for a, b in zip(lin, lin[1:]):
            ja = self.versions[a]['snap']['journal']
            jb = self.versions[b]['snap']['journal']
            if jb[:len(ja)] != ja:
                return False
        return True


def try_post(reg, amt):
    """Проводка: инвариант-шлюз считается в чистой черновой сессии, чтобы
    отклонённая проводка не оставляла следа в журнале регистра."""
    s = reg.s
    g = Session()
    g.funcs = dict(s.funcs)
    g.execute('balance = %r' % s.env['balance'])
    allowed = g.execute('allowed[balance, %r]' % amt) == 1.0
    if not allowed:
        print('  проводка -%r: ЗАБЛОКИРОВАНА инвариантом -> ветки нет (версий в дереве: %d)'
              % (amt, len(reg.versions)))
        return None, False
    s.execute('balance = withdraw[balance, %r]' % amt)
    vid = reg.commit('проводка -%r' % amt)
    print('  проводка -%r: допущена -> %s (остаток 0x%s)'
          % (amt, vid, canon_bits(s.env['balance'])))
    return vid, True


def replay_check(reg, base_vid, vid, statements):
    """Аудит: свежая сессия продолжает снапшот предка теми же стейтментами
    и сверяется с версией потомка - журнал посимвольно, last по битам."""
    base = reg.versions[base_vid]['snap']
    target = reg.versions[vid]['snap']
    fresh = Session()
    fd, p = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(base, f, ensure_ascii=False)
        fresh.restore(p)
        for st in statements:
            fresh.execute(st)
    finally:
        os.unlink(p)
    k = len(base['journal'])
    okj = target['journal'][k:] == fresh.journal[k:]
    okl = canon_bits(fresh.last) == target['last']
    return okj, okl


def scenario():
    print('== Регистр «касса»: дерево версий, инвариант, аудит ==')
    s = Session()
    s.execute('balance = 1000.0')
    s.execute('allowed[x_, amt_] := amt <= x')
    s.execute('withdraw[x_, amt_] := x - amt')
    reg = Register(s, 'касса')
    V0 = reg.commit('открытие: остаток 1000.0')
    print('  %s: остаток 0x%s, журнал %d' % (V0, canon_bits(s.env['balance']), len(s.journal)))

    vidA, _ = try_post(reg, 300.0)
    reg.checkout(V0)                 # возврат в точку ветвления
    try_post(reg, 1200.0)            # инвариант отклоняет: ветки не будет
    vidB, _ = try_post(reg, 400.0)   # из той же точки V0 - параллельная ветвь

    reg.checkout(vidA)
    vidA2, _ = try_post(reg, 200.0)  # цепочка V0 -> VA -> VA2

    print('  дерево версий:')
    for row in reg.tree():
        print('    ' + row)

    okA1 = replay_check(reg, V0, vidA, ['balance = withdraw[balance, 300.0]'])
    okB1 = replay_check(reg, V0, vidB, ['balance = withdraw[balance, 400.0]'])
    okA2 = replay_check(reg, vidA, vidA2, ['balance = withdraw[balance, 200.0]'])
    print('  аудит-реплей ветки A: журнал %s, last %s' % okA1)
    print('  аудит-реплей ветки B: журнал %s, last %s' % okB1)
    print('  аудит-реплей A2 (цепочка из двух шагов): журнал %s, last %s' % okA2)

    ok_chain_A = reg.chain_ok(vidA2)
    ok_chain_B = reg.chain_ok(vidB)
    print('  префикс-непрерывность цепочек: A2 %s, B %s' % (ok_chain_A, ok_chain_B))

    # провод-сверка: прямой остаток против независимого графа (Fold по проводкам)
    reg.checkout(vidA2)
    s.execute('apply[acc_, amt_] := acc - amt')
    folded = s.execute('Fold[apply, 1000.0, {300.0, 200.0}]')
    ok_w1 = wire('ветка A2: прямой остаток против Fold по проводкам', s.env['balance'], folded)

    reg.checkout(vidB)
    s.execute('apply[acc_, amt_] := acc - amt')
    foldedB = s.execute('Fold[apply, 1000.0, {400.0}]')
    ok_w2 = wire('ветка B: прямой остаток против Fold по проводкам', s.env['balance'], foldedB)

    balA = reg.versions[vidA2]['snap']['names']['balance']
    balB = reg.versions[vidB]['snap']['names']['balance']
    diverged = balA != balB
    print('  расхождение ветвей: A2 остаток %s, B остаток %s -> %s'
          % (balA, balB, 'ветви разошлись' if diverged else 'ветви совпали?!'))

    reg.save_all()
    print('  снапшоты версий записаны в reg_*.json')

    # тампер-тест: одна изменённая строка журнала обязана взорвать отпечаток
    bad = json.loads(json.dumps(reg.versions[vidA]['snap']))
    bad['journal'][-1] += ' x'
    fd, p = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(bad, f, ensure_ascii=False)
        probe = Session()
        try:
            probe.restore(p)
            tamper_ok = False
        except SoundError:
            tamper_ok = True
    finally:
        os.unlink(p)
    print('  тампер-тест: подделка строки журнала -> %s'
          % ('отпечаток поднял ошибку' if tamper_ok else 'ПОДДЕЛКА ПРОШЛА НЕЗАМЕТНО'))

    return (okA1 == (True, True) and okB1 == (True, True) and okA2 == (True, True)
            and ok_chain_A and ok_chain_B and ok_w1 and ok_w2
            and diverged and tamper_ok)


if __name__ == '__main__':
    ok = scenario()
    print('---')
    print('ALL PASS' if ok else 'FAILED')
