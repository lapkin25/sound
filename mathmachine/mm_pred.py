#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mm_pred.py — интерпретатор предикатного языка MM-P v0.2.

Проверяет инварианты над протоколом звуковой машины (.sound.jsonl).
Схема записи протокола:
    op      — 'CALL' | 'RET' | 'HALT' | арифметика ('ADD','SUB','MUL',...)
    args    — список аргументов инструкции
    state.V — аккумулятор на момент записи
    depth   — глубина стека вызовов
    cid     — монотонный номер вызова (CALL/RET-парность по cid)
    pc      — индекс инструкции

Использование:
    python mm_pred.py pred.mmx protocol.jsonl
    python mm_pred.py --selftest

Язык MM-P v0.2 (s-выражения):

  предикаты
    (forall v P)              — по всем записям
    (forall [a b] P)          — по соседним парам
    (exists v P)              — существует свидетель
    (exists1 v P)             — существует ровно один
    (bind r (where G) B)      — связать с первой ПОСЛЕДУЮЩЕЙ записью, где G;
                                нет совпадения -> FAILED со свидетелем-CALL
    (and P ...) (or P ...) (not P) (implies P Q)
    (= t u) (!= t u) (< t u) (<= t u) (> t u) (>= t u)
    (before a b) (after a b)  — позиции записей (свойство носителя)
    true  false

  термы
    42  "CALL"  s  s.op  s.state.V  s.depth  s.cid  s.pc
    (count v (where G))       — сколько записей удовлетворяют G
    (sum v t (where G))       — сумма t по записям, где G

  семантика — трёхзначная (Клини), полный скан:
    VERIFIED / FAILED (со свидетелем) / UNKNOWN (unknown_count > 0) / UNSUPPORTED
  Агрегаты тотальны: ошибка внутри тянет UNSUPPORTED (D-MM1.5-3).
  bind — поиск: ошибки guard до совпадения подавляются со счётчиком (D-MM1.5-4).
  Свидетель рождается в точке провала и поднимается наверх нетронутым.
  Вердикт не зависит от порядка записей (Клини с полным сканом).
"""

import copy
import json
import operator
import sys


class MMError(Exception):
    """Читаемая ошибка языка или файла."""


class UnknownVal(Exception):
    """Значение терма не определено на этой записи (идёт в unknown_count)."""


class Unsupported(Exception):
    """Конструкция не применима к протоколу (агрегаты тотальны)."""


# ------------------------------------------------------------------ лексер

def lex(src):
    toks, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in ' \t\r\n\ufeff':
            i += 1
        elif c in '#;':
            while i < n and src[i] != '\n':
                i += 1
        elif c in '()[]':
            toks.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            buf = []
            while j < n and src[j] != '"':
                buf.append(src[j])
                j += 1
            if j >= n:
                raise MMError('незакрытый строковый литерал')
            toks.append(('str', ''.join(buf)))
            i = j + 1
        else:
            j = i
            while j < n and src[j] not in ' \t\r\n()[]#"':
                j += 1
            w = src[i:j]
            i = j
            try:
                toks.append(('num', int(w)))
            except ValueError:
                toks.append(('sym', w))
    return toks


def parse(src):
    toks = lex(src)
    pos = 0

    def rd():
        nonlocal pos
        if pos >= len(toks):
            raise MMError('неожиданный конец текста')
        t = toks[pos]
        if t in ('(', '['):
            close = ')' if t == '(' else ']'
            pos += 1
            items = []
            while True:
                if pos >= len(toks):
                    raise MMError('незакрытая скобка')
                if toks[pos] == close:
                    pos += 1
                    break
                items.append(rd())
            return ('expr', items)
        if t in (')', ']'):
            raise MMError('лишняя закрывающая скобка')
        pos += 1
        return t

    e = rd()
    if pos != len(toks):
        raise MMError('лишний текст после основного выражения')
    return e


# ------------------------------------------------------------------ движок

_CMP = {
    '=': operator.eq,
    '!=': operator.ne,
    '<': operator.lt,
    '<=': operator.le,
    '>': operator.gt,
    '>=': operator.ge,
}


class Engine:
    def __init__(self, records):
        self.rec = records
        for i, r in enumerate(records):
            r['_i'] = i
        self.unknown_count = 0
        self.witness = None
        self.no_stamp = 0

    # ---------- термы ----------

    def term(self, t, env):
        k, v = t
        if k == 'num' or k == 'str':
            return v
        if k == 'sym':
            if v == 'true':
                return True
            if v == 'false':
                return False
            parts = v.split('.')
            if parts[0] not in env:
                raise UnknownVal('нет переменной %r' % parts[0])
            x = env[parts[0]]
            for f in parts[1:]:
                if isinstance(x, dict) and f in x:
                    x = x[f]
                else:
                    raise UnknownVal('нет поля %r' % v)
            return x
        head = v[0]
        if head[0] == 'sym' and head[1] in ('count', 'sum'):
            return self._aggregate(v, env)
        raise MMError('не терм: %r' % (t,))

    def _aggregate(self, v, env):
        head = v[0][1]
        if head == 'count':
            if len(v) != 3:
                raise MMError('(count v (where G)) — три элемента')
            var, t, clause = v[1][1], None, v[2]
        else:
            if len(v) != 4:
                raise MMError('(sum v t (where G)) — четыре элемента')
            var, t, clause = v[1][1], v[2], v[3]
        if not (clause[0] == 'expr' and len(clause[1]) == 2
                and clause[1][0] == ('sym', 'where')):
            raise MMError('агрегат требует (where G)')
        G = clause[1][1]
        total = 0
        for r in self.rec:
            sub = dict(env)
            sub[var] = r
            g = self._safe(G, sub)
            if g is None:
                raise Unsupported('агрегат по неопределённому guard')
            if g is not True:
                continue
            if head == 'count':
                total += 1
            else:
                try:
                    total += self.term(t, sub)
                except UnknownVal:
                    raise Unsupported('агрегат по неопределённому терму')
                except TypeError:
                    raise Unsupported('агрегат по нечисловому терму')
        return total

    # ---------- предикаты ----------

    def _safe(self, p, env):
        try:
            return self.pred(p, env)
        except UnknownVal:
            self.unknown_count += 1
            return None

    def _fail_witness(self, env):
        if self.no_stamp == 0 and self.witness is None:
            self.witness = env.get('__cur')

    def pred(self, p, env):
        k, v = p
        if k == 'sym':
            if v == 'true':
                return True
            if v == 'false':
                return False
            raise MMError('не предикат: символ %r' % v)
        if k != 'expr' or not v:
            raise MMError('не предикат: %r' % (p,))
        head = v[0]
        if head[0] != 'sym':
            raise MMError('не предикат: голова не символ: %r' % (head,))
        h = head[1]

        if h in ('and', 'or'):
            if not v[1:]:
                raise MMError('(%s) без аргументов' % h)
            if h == 'and':
                x = True
                for q in v[1:]:
                    y = self._safe(q, env)
                    if y is False:
                        return False
                    if y is None:
                        x = None
                return x
            x = False
            for q in v[1:]:
                y = self._safe(q, env)
                if y is True:
                    return True
                if y is None:
                    x = None
            return x

        if h == 'not':
            if len(v) != 2:
                raise MMError('(not P) — один аргумент')
            x = self._safe(v[1], env)
            return None if x is None else (not x)

        if h == 'implies':
            if len(v) != 3:
                raise MMError('(implies P Q) — два аргумента')
            # антецедент импликации — не точка опровержения: не штампуем
            self.no_stamp += 1
            try:
                x = self._safe(v[1], env)
            finally:
                self.no_stamp -= 1
            if x is False:
                return True
            if x is None:
                y = self._safe(v[2], env)
                return True if y is True else None
            return self._safe(v[2], env)

        if h in _CMP:
            if len(v) != 3:
                raise MMError('(%s t u) — ровно два аргумента' % h)
            try:
                a = self.term(v[1], env)
                b = self.term(v[2], env)
            except UnknownVal:
                self.unknown_count += 1
                return None
            try:
                res = _CMP[h](a, b)
            except TypeError:
                self.unknown_count += 1
                return None
            if res is False:
                self._fail_witness(env)
            return res

        if h in ('before', 'after'):
            if len(v) != 3:
                raise MMError('(%s a b) — ровно два аргумента' % h)
            if v[1][0] != 'sym' or v[2][0] != 'sym':
                raise MMError('%s берёт имена переменных' % h)
            a, b = env.get(v[1][1]), env.get(v[2][1])
            if a is None or b is None:
                self.unknown_count += 1
                return None
            res = (a['_i'] < b['_i']) if h == 'before' else (a['_i'] > b['_i'])
            if res is False:
                self._fail_witness(env)
            return res

        if h in ('forall', 'exists', 'exists1'):
            if len(v) != 3:
                for q in v[1:]:
                    if (isinstance(q, tuple) and q[0] == 'expr' and q[1]
                            and q[1][0] == ('sym', 'where')):
                        raise MMError(
                            '%s не принимает (where ...): похоже, файл старого '
                            'синтаксиса. Новый язык: (exists1 v P), а для '
                            'CALL/RET-пары — (bind r (where G) B)' % h)
                raise MMError('%s требует (v P) или ([a b] P)' % h)
            return self._quant(h, v[1], v[2], env)

        if h == 'bind':
            if len(v) != 4:
                raise MMError('(bind r (where G) B) — три аргумента')
            name = v[1][1]
            clause = v[2]
            if not (clause[0] == 'expr' and len(clause[1]) == 2
                    and clause[1][0] == ('sym', 'where')):
                raise MMError('bind требует вторым аргументом (where G)')
            return self._bind(name, clause[1][1], v[3], env)

        raise MMError('неизвестный предикат: %r' % h)

    @staticmethod
    def _seq(rec, names):
        if len(names) == 1:
            return ((r,) for r in rec)
        return ((rec[i], rec[i + 1]) for i in range(len(rec) - 1))

    def _quant(self, h, binder, body, env):
        if binder[0] == 'sym':
            names = [binder[1]]
        elif binder[0] == 'expr' and len(binder[1]) == 2:
            names = [binder[1][0][1], binder[1][1][1]]
        else:
            raise MMError('связывание — переменная или пара [a b]')
        any_unk = False
        trues = 0
        for combo in self._seq(self.rec, names):
            sub = dict(env)
            for nm, r in zip(names, combo):
                sub[nm] = r
            sub['__cur'] = combo[0]
            if h == 'exists1':
                self.no_stamp += 1
            try:
                x = self.pred(body, sub)
            except UnknownVal:
                x = None
            finally:
                if h == 'exists1':
                    self.no_stamp -= 1
            if h == 'forall':
                if x is False:
                    return False
                if x is None:
                    any_unk = True
            elif h == 'exists':
                if x is True:
                    return True
                if x is None:
                    any_unk = True
            else:  # exists1
                if x is True:
                    trues += 1
                    if trues >= 2 and self.witness is None:
                        self.witness = combo[0]
                elif x is None:
                    any_unk = True
        if h == 'forall':
            return None if any_unk else True
        if h == 'exists':
            return None if any_unk else False
        if trues == 1:
            return True
        if trues >= 2:
            return False
        return None if any_unk else False

    def _bind(self, name, G, B, env):
        cur = env.get('__cur')
        start = (cur['_i'] + 1) if cur is not None else 0
        for r in self.rec[start:]:
            sub = dict(env)
            sub[name] = r
            # guard bind'а — не точка опровержения: не штампуем
            self.no_stamp += 1
            try:
                g = self._safe(G, sub)
            finally:
                self.no_stamp -= 1
            if g is True:
                sub2 = dict(sub)
                sub2['__cur'] = r
                return self._safe(B, sub2)
        if self.witness is None:
            self.witness = cur
        return False

    def run(self, formula):
        try:
            x = self.pred(formula, {})
        except Unsupported as e:
            return {'verdict': 'UNSUPPORTED', 'reason': str(e),
                    'unknown_count': self.unknown_count}
        except UnknownVal:
            self.unknown_count += 1
            return {'verdict': 'UNKNOWN', 'unknown_count': self.unknown_count}
        if x is True:
            return {'verdict': 'VERIFIED', 'unknown_count': self.unknown_count}
        if x is False:
            return {'verdict': 'FAILED', 'witness': self.witness,
                    'unknown_count': self.unknown_count}
        return {'verdict': 'UNKNOWN', 'unknown_count': self.unknown_count}


# ---------------------------------------------------------------- самотест

def _r(op, V, depth, args=None, cid=0, pc=0):
    return {'op': op, 'args': args if args is not None else [],
            'state': {'V': V}, 'depth': depth, 'cid': cid, 'pc': pc}


def _mut(recs, i, **kw):
    recs = copy.deepcopy(recs)
    for k, val in kw.items():
        if '.' in k:
            outer, inner = k.split('.')
            recs[i][outer][inner] = val
        else:
            recs[i][k] = val
    return recs


def _clean():
    return [
        _r('CALL', 0, 1, args=[1], cid=1, pc=10),
        _r('CALL', 0, 2, args=[0], cid=2, pc=14),
        _r('MUL', 2, 2, cid=2, pc=20),
        _r('RET', 2, 2, args=[2], cid=2, pc=15),
        _r('ADD', 2, 1, cid=1, pc=18),
        _r('RET', 2, 1, args=[2], cid=1, pc=11),
        _r('HALT', 2, 0, args=[2], cid=0, pc=25),
    ]


F = {
    'nonneg': '(forall s (>= s.state.V 0))',
    'all_call': '(forall s (= s.op "CALL"))',
    'exists_halt': '(exists s (= s.op "HALT"))',
    'exists1_halt': '(exists1 h (= h.op "HALT"))',
    'pair_depth': '(forall [a b] (implies (= b.op "RET") (>= a.depth b.depth)))',
    'pair_V': '(forall [a b] (implies (= b.op "RET") (>= a.state.V b.state.V)))',
    'bind_pair': ('(forall c (implies (= c.op "CALL")'
                  ' (bind r (where (and (= r.op "RET") (= r.depth c.depth)))'
                  ' (= r.cid c.cid))))'),
    'count_eq': ('(= (count r (where (= r.op "RET")))'
                 ' (count r (where (= r.op "CALL"))))'),
    'sum_ret': '(= (sum r r.state.V (where (= r.op "RET"))) 4)',
    'sum_ret_bad': '(= (sum r r.state.V (where (= r.op "RET"))) 3)',
    'between': ('(forall c (implies (= c.op "CALL")'
                ' (bind r (where (and (= r.op "RET") (= r.depth c.depth)))'
                ' (forall x (implies (and (before c x) (before x r)'
                ' (= x.depth c.depth)) (>= x.state.V c.state.V))))))'),
    'before_pairs': '(forall [a b] (before a b))',
    'after_pairs': '(forall [a b] (after a b))',
    'implies_nonneg': '(forall c (implies (= c.op "CALL") (>= c.state.V 0)))',
    'bind_noguard': ('(forall c (implies (= c.op "CALL")'
                     ' (bind r (where (= r.nope c.depth)) (= r.cid c.cid))))'),
    'sum_str': '(= (sum r r.op (where (= r.op "RET"))) 0)',
}


def selftest():
    clean = _clean()
    empty = []
    no_ret2 = clean[:3] + clean[4:]        # убран RET глубины 2
    few_rets = clean[:5] + clean[6:]       # убран один RET — счёт расходится
    two_halts = clean + [_r('HALT', 2, 0, cid=9, pc=30)]
    badV2 = _mut(clean, 2, **{'state.V': -1})   # провал аккумулятора внутри цикла
    badV5 = _mut(clean, 5, **{'state.V': 5})    # RET выше, чем всё до него
    call_neg = _mut(clean, 0, **{'state.V': -1})  # CALL с отрицательным входом
    missing_state = copy.deepcopy(clean)
    del missing_state[2]['state']

    cases = [
        ('nonneg_clean',   clean,         F['nonneg'],         'VERIFIED',    None, 0),
        ('nonneg_bad',     badV2,         F['nonneg'],         'FAILED',      2,    0),
        ('vacuous_empty',  empty,         F['nonneg'],         'VERIFIED',    None, 0),
        ('forall_call',    clean,         F['all_call'],       'FAILED',      2,    0),
        ('exists_halt',    clean,         F['exists_halt'],    'VERIFIED',    None, 0),
        ('exists_empty',   empty,         F['exists_halt'],    'FAILED',      None, 0),
        ('exists1_halt',   clean,         F['exists1_halt'],   'VERIFIED',    None, 0),
        ('exists1_two',    two_halts,     F['exists1_halt'],   'FAILED',      7,    0),
        ('pair_depth',     clean,         F['pair_depth'],     'VERIFIED',    None, 0),
        ('pair_V_bad',     badV5,         F['pair_V'],         'FAILED',      4,    0),
        ('bind_clean',     clean,         F['bind_pair'],      'VERIFIED',    None, 0),
        ('bind_missing',   no_ret2,       F['bind_pair'],      'FAILED',      1,    0),
        ('count_eq',       clean,         F['count_eq'],       'VERIFIED',    None, 0),
        ('count_bad',      few_rets,      F['count_eq'],       'FAILED',      None, 0),
        ('sum_ret',        clean,         F['sum_ret'],        'VERIFIED',    None, 0),
        ('sum_ret_bad',    clean,         F['sum_ret_bad'],    'FAILED',      None, 0),
        ('between',        clean,         F['between'],        'VERIFIED',    None, 0),
        ('between_bad',    badV2,         F['between'],        'FAILED',      2,    0),
        ('before_pairs',   clean,         F['before_pairs'],   'VERIFIED',    None, 0),
        ('after_pairs',    clean,         F['after_pairs'],    'FAILED',      0,    0),
        ('implies_bad',    call_neg,      F['implies_nonneg'], 'FAILED',      0,    0),
        ('unknown_field',  missing_state, F['nonneg'],         'UNKNOWN',     None, 1),
        ('bind_noguard',   clean,         F['bind_noguard'],   'FAILED',      0,    1),
        ('sum_str',        clean,         F['sum_str'],        'UNSUPPORTED', None, 0),
    ]

    ok = 0
    for name, recs, src, exp, wit, unk_min in cases:
        eng = Engine(copy.deepcopy(recs))
        res = eng.run(parse(src))
        good = res['verdict'] == exp
        if good and wit is not None:
            w = res.get('witness')
            good = w is not None and w.get('_i') == wit
        if good and unk_min:
            good = res.get('unknown_count', 0) >= unk_min
        if good:
            ok += 1
            print('  PASS  %s' % name)
        else:
            print('  FAIL  %s: ожидалось %s, получено %r' % (name, exp, res))
    print('Самотест: %d из %d' % (ok, len(cases)))
    return ok == len(cases)


# ---------------------------------------------------------------- CLI

def main():
    argv = sys.argv[1:]
    if '--selftest' in argv:
        sys.exit(0 if selftest() else 1)
    if len(argv) < 2:
        print('Использование:')
        print('  python mm_pred.py pred.mmx protocol.jsonl')
        print('  python mm_pred.py --selftest')
        sys.exit(2)
    try:
        with open(argv[0], encoding='utf-8-sig') as f:
            src = f.read()
    except OSError as e:
        print('Не могу открыть предикат: %s' % e)
        sys.exit(2)
    recs = []
    try:
        with open(argv[1], encoding='utf-8-sig') as f:
            for ln, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    recs.append(json.loads(line))
                except ValueError as e:
                    print('Протокол, строка %d: не JSON: %s' % (ln, e))
                    sys.exit(2)
    except OSError as e:
        print('Не могу открыть протокол: %s' % e)
        sys.exit(2)
    try:
        formula = parse(src)
    except MMError as e:
        print('Ошибка в предикате: %s' % e)
        sys.exit(2)
    eng = Engine(recs)
    try:
        res = eng.run(formula)
    except MMError as e:
        print('Ошибка в предикате: %s' % e)
        sys.exit(2)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res['verdict'] == 'VERIFIED' else 1)


if __name__ == '__main__':
    main()
