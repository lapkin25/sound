# sound_snap2.py
# Полуимперативный слой над Sound: WL-жанр, журнал t-binds, снапшоты Save/Restore.
# Зависимости: только стандартная библиотека Python 3.
#
# Запуск:  python3 sound_snap2.py
# Эффект:  создаёт snap_A.json и snap_B.json (сценарий реплея) и печатает проверки.
# После успешного прогона запустите в Octave:  octave --eval replay_octave
#
# Лексер собран без экранированных скобок в шаблоне: пару  при копировании
# из чата легко теряет рендерер. Одиночные символы операций ловит catch-all \S,
# а проверяет их обычная строка _OPS — скобкам в ней съедаться нечего.

import re, json, hashlib, struct, math

# ---------- канонизация: биты IEEE-754 big-endian, ровно 16 hex-цифр ----------

def canon_bits(v):
    if isinstance(v, list):
        # канон списка: длина, разделитель, поэлементные hex
        return '%d|%s' % (len(v), ','.join(canon_bits(x) for x in v))
    return struct.pack('>d', float(v)).hex()

def bits2val(hs):
    if '|' in hs:
        n, rest = hs.split('|', 1)
        return [bits2val(x) for x in rest.split(',')] if rest else []
    return struct.unpack('>d', bytes.fromhex(hs))[0]

def canon_hex(v):
    return '0x' + canon_bits(v)

# ---------- лексер ----------

_OPS = set('+-*/=<>{}()[],') | {':=', '==', '!=', '<=', '>='}

_TOK = re.compile(
    r'\s*(?:(?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)'
    r'|(?P<id>[A-Za-z_]\w*)'
    r'|(?P<op>:=|==|!=|<=|>=|\S))')

def lex(src):
    toks, i = [], 0
    while i < len(src):
        m = _TOK.match(src, i)
        if not m:
            if src[i].isspace():
                i += 1
                continue
            raise SyntaxError('нечитаемый символ %r на позиции %d' % (src[i], i))
        i = m.end()
        if m.lastgroup == 'num':
            toks.append(('NUM', m.group('num')))
        elif m.lastgroup == 'id':
            w = m.group('id')
            # хвостовое подчёркивание расщепляем: f[x_] -> IDENT f, [, IDENT x, PAT, ]
            if w.endswith('_'):
                toks.append(('IDENT', w[:-1]))
                toks.append(('PAT', '_'))
            else:
                toks.append(('IDENT', w))
        else:
            s = m.group('op')
            if s not in _OPS:
                raise SyntaxError('нечитаемый символ %r на позиции %d' % (s, i - len(s)))
            toks.append(('OP', s))
    toks.append(('END', ''))
    return toks

def _selfcheck():
    # защита от испорченного копипаста: если при переносе потерялись скобки
    # или слеши, модуль скажет об этом сразу и по-человечески
    try:
        toks = lex('Nest[step, x, 10]')
    except SyntaxError as e:
        raise RuntimeError('файл повреждён при копировании: лексер не читает программу (%s). '
                           'Перекопируйте блок "лексер" из исходного сообщения целиком.' % e)
    if toks[1] != ('OP', '[') or toks[7] != ('OP', ']'):
        raise RuntimeError('файл повреждён при копировании: лексер не распознаёт скобки. '
                           'Перекопируйте блок "лексер" из исходного сообщения целиком.')

_selfcheck()

# ---------- парсер: право-ассоциативность наследована от Sound ----------

class Parser:
    def __init__(self, toks):
        self.t = toks
        self.i = 0
    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]
    def eat(self, tag=None, val=None):
        tg, vl = self.peek()
        if tag is not None and tg != tag:
            raise SyntaxError('ждал %s, получил %r' % (tag, (tg, vl)))
        if val is not None and vl != val:
            raise SyntaxError('ждал %r, получил %r' % (val, (tg, vl)))
        self.i += 1
        return vl

    def parse_program(self):
        stmts = []
        while self.peek()[0] != 'END':
            stmts.append(self.parse_stmt())
        return stmts

    def parse_stmt(self):
        save = self.i
        try:
            return self.parse_funcdef()
        except SyntaxError:
            self.i = save
        name = self.eat('IDENT')
        if self.peek() == ('OP', '='):
            self.eat()
            return ('assign', name, self.parse_expr())
        if self.peek() == ('OP', '['):
            self.i = save
            return ('expr', self.parse_expr())
        return ('expr', self.parse_expr())

    def parse_funcdef(self):
        name = self.eat('IDENT')
        self.eat('OP', '[')
        params = []
        while True:
            params.append(self.eat('IDENT'))
            self.eat('PAT')
            if self.peek() == ('OP', ','):
                self.eat()
                continue
            break
        self.eat('OP', ']')
        self.eat('OP', ':=')
        return ('funcdef', name, params, self.parse_expr())

    def parse_expr(self):
        l = self.parse_add()
        if self.peek()[0] == 'OP' and self.peek()[1] in ('<', '<=', '>', '>=', '==', '!='):
            c = self.eat()
            return ('cmp', c, l, self.parse_add())
        return l

    def parse_add(self):
        l = self.parse_term()
        if self.peek()[0] == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.eat()
            return ('op', op, l, self.parse_add())
        return l

    def parse_term(self):
        l = self.parse_factor()
        if self.peek()[0] == 'OP' and self.peek()[1] in ('*', '/'):
            op = self.eat()
            return ('op', op, l, self.parse_term())
        return l

    def parse_factor(self):
        t = self.peek()
        if t == ('OP', '-'):
            self.eat()
            return ('neg', self.parse_factor())
        if t == ('OP', '('):
            self.eat()
            e = self.parse_expr()
            self.eat('OP', ')')
            return e
        if t == ('OP', '{'):
            self.eat()
            items = []
            if self.peek() != ('OP', '}'):
                items.append(self.parse_expr())
                while self.peek() == ('OP', ','):
                    self.eat()
                    items.append(self.parse_expr())
            self.eat('OP', '}')
            return ('list', items)
        if t[0] == 'NUM':
            self.eat()
            return ('const', float(t[1]))
        if t[0] == 'IDENT':
            self.eat()
            if self.peek() == ('OP', '['):
                self.eat()
                args = []
                if self.peek() != ('OP', ']'):
                    args.append(self.parse_expr())
                    while self.peek() == ('OP', ','):
                        self.eat()
                        args.append(self.parse_expr())
                self.eat('OP', ']')
                return ('call', t[1], args)
            return ('ref', t[1])
        raise SyntaxError('неожиданный токен %r' % (t,))

def parse(src):
    return Parser(lex(src)).parse_program()

# ---------- сессия: чистое ядро + линейный журнал ----------

class SoundError(Exception):
    pass

class Session:
    def __init__(self):
        self.env = {}
        self.funcs = {}
        self.journal = []
        self.n = 0
        self.last = None

    def bind(self, op, args, result):
        self.n += 1
        line = 't%d %s(%s) -> %s' % (self.n, op,
                                     ','.join(canon_bits(a) for a in args),
                                     canon_bits(result))
        self.journal.append(line)
        return result

    def setname(self, name, val):
        self.n += 1
        self.journal.append('t%d set(%s) -> %s' % (self.n, name, canon_bits(val)))
        self.env[name] = val
        return val

    def eval(self, node, env):
        k = node[0]
        if k == 'const':
            return node[1]
        if isinstance(node, (tuple, list)) and node[0] == 'ref':
            name = node[1]
            if name in env:            # параметры вызова - первый эшелон
                return env[name]
            if name in self.env:       # среда сессии - запасной спуск
                return self.env[name]
            raise SoundError('имя %s не задано' % name)
        if k == 'neg':
           v = self.eval(node[1], env)
           return self.bind('neg', [v], -v)
        if k == 'op':
            l = self.eval(node[2], env)
            r = self.eval(node[3], env)
            op = node[1]
            if op == '+': return self.bind('+', [l, r], l + r)
            if op == '-': return self.bind('-', [l, r], l - r)
            if op == '*': return self.bind('*', [l, r], l * r)
            if op == '/': return self.bind('/', [l, r], l / r)
        if k == 'cmp':
            l = self.eval(node[2], env)
            r = self.eval(node[3], env)
            c = node[1]
            ok = (l < r if c == '<' else l <= r if c == '<=' else
                  l > r if c == '>' else l >= r if c == '>=' else
                  l == r if c == '==' else l != r)
            return self.bind(c, [l, r], 1.0 if ok else 0.0)
        if k == 'list':
            return [self.eval(x, env) for x in node[1]]
        if k == 'call':
            name, args = node[1], node[2]
            if name in self.funcs:
                f = self.funcs[name]
                vals = [self.eval(a, env) for a in args]
                if len(vals) != len(f['params']):
                    raise SoundError('арность %s: ждал %d, получил %d' %
                                     (name, len(f['params']), len(vals)))
                return self.eval(f['body'], dict(zip(f['params'], vals)))
            return self.builtin(name, args, env)
        raise SoundError('неизвестный узел %r' % (k,))

    def apply_fn(self, fast, vals, env):
        # ленивое применение: AST функции проходит без вычисления
        if fast[0] in ('ref', 'call'):
            fname = fast[1]
        else:
            raise SoundError('первый аргумент должен быть функцией, а не значением')
        return self.eval(('call', fname, [('const', v) for v in vals]), env)

    def builtin(self, name, args, env):
        if name == 'If':
            cond = self.eval(args[0], env)
            return self.eval(args[1] if cond != 0.0 else args[2], env)
        if name == 'Nest':
            f = args[0]
            x = self.eval(args[1], env)
            n = int(self.eval(args[2], env))
            for _ in range(n):
                x = self.apply_fn(f, [x], env)
            return x
        if name == 'NestList':
            f = args[0]
            x = self.eval(args[1], env)
            n = int(self.eval(args[2], env))
            out = [x]
            for _ in range(n):
                x = self.apply_fn(f, [x], env)
                out.append(x)
            return out
        if name in ('Fold'):
            f = args[0]
            v = self.eval(args[1], env)
            lst = self.eval(args[2], env)
            out = [v]
            for item in lst:
                v = self.apply_fn(f, [v, item], env)
                out.append(v)
            return v if name == 'Fold' else out
        elif name == 'Table':
           f = args[0]
           n = self.eval(args[1], env)
           if isinstance(n, list):
               # Table[f, список] - отображение по элементам (удобная надстройка)
               out = [self.apply_fn(f, [x], env) for x in n]
           else:
               # Table[f, n] - генерация: n вызовов с индексами 0.0 .. n-1.0
               if n != int(n) or n < 0:
                   raise SoundError('Table: счётчик должен быть целым неотрицательным, получено %r' % (n,))
               out = [self.apply_fn(f, [float(k)], env) for k in range(int(n))]
           fname = f[1] if f[0] in ('ref', 'call') else '?'
           self.journal.append('t%d table(%s,%s) -> %s'
                               % (self.n, fname, canon_bits(n), canon_bits(out)))
           self.n += 1
           return out
        elif name == 'Mod':
           a = self.eval(args[0], env)
           b = self.eval(args[1], env)
           if b == 0.0:
               raise SoundError('Mod: деление на ноль')
           q = math.floor(a / b)
           while q * b > a:              # страховка округления частного
               q -= 1.0
           while (q + 1.0) * b <= a:
               q += 1.0
           r = a - q * b                 # точно: целые < 2^53
           self.n += 1
           self.journal.append('t%d mod(%s,%s) -> %s'
                               % (self.n, canon_bits(a), canon_bits(b), canon_bits(r)))
           self.last = r
           return r

        elif name == 'Quotient':
           a = self.eval(args[0], env)
           b = self.eval(args[1], env)
           if b == 0.0:
               raise SoundError('Quotient: деление на ноль')
           q = math.floor(a / b)
           while q * b > a:
               q -= 1.0
           while (q + 1.0) * b <= a:
               q += 1.0
           self.n += 1
           self.journal.append('t%d quotient(%s,%s) -> %s'
                               % (self.n, canon_bits(a), canon_bits(b), canon_bits(q)))
           self.last = q
           return q

        elif name == 'Part':
           lst = self.eval(args[0], env)
           i = self.eval(args[1], env)
           if not isinstance(lst, list):
               raise SoundError('Part: первый аргумент должен быть списком, получено %r' % (lst,))
           k = int(i)
           if not (0 <= k < len(lst)):
               raise SoundError('Part: индекс %d вне списка длины %d' % (k, len(lst)))
           r = lst[k]
           self.n += 1
           self.journal.append('t%d part(%s,%s) -> %s'
                               % (self.n, canon_bits(lst), canon_bits(i), canon_bits(r)))
           self.last = r
           return r

        elif name == 'FoldList':
           f = args[0]
           acc = self.eval(args[1], env)
           lst = self.eval(args[2], env)
           if not isinstance(lst, list):
               raise SoundError('FoldList: третий аргумент должен быть списком, получено %r' % (lst,))
           out = [acc]
           for x in lst:
               acc = self.apply_fn(f, [acc, x], env)
               out.append(acc)
           self.n += 1
           self.journal.append('t%d foldlist(%s,%s) -> %s'
                               % (self.n, canon_bits(acc), canon_bits(lst), canon_bits(out)))
           self.last = out
           return out

        else:
           raise SoundError('неизвестная функция %s' % name)

    def execute(self, src):
        for st in parse(src):
            if st[0] == 'funcdef':
                self.funcs[st[1]] = {'params': st[2], 'body': st[3]}
                self.last = None
            elif st[0] == 'assign':
                self.last = self.setname(st[1], self.eval(st[2], self.env))
            else:
                self.last = self.eval(st[1], self.env)
        return self.last

# ---------- снапшоты: значения по битам, функции как AST, отпечаток цепочкой ----------

    def snapshot(self):
        return {
            'version': 'wl-snap-1',
            'names': dict((k, canon_bits(v)) for k, v in self.env.items()),
            'funcs': self.funcs,
            'journal': list(self.journal),
            'last': None if self.last is None else canon_bits(self.last),
        }

    def fingerprint(self, snap):
        fp = '0' * 64
        for line in snap['journal']:
            fp = hashlib.sha256((fp + line).encode()).hexdigest()
        return fp

    def save(self, path):
        snap = self.snapshot()
        snap['fingerprint'] = self.fingerprint(snap)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
        return snap

    def restore(self, path):
        with open(path, encoding='utf-8') as f:
            snap = json.load(f)
        if self.fingerprint(snap) != snap.get('fingerprint'):
            raise SoundError('отпечаток снапшота не сошёлся — журнал искажён')
        self.env = dict((k, bits2val(v)) for k, v in snap['names'].items())
        self.funcs = snap['funcs']
        self.journal = list(snap['journal'])
        self.n = len(self.journal)
        self.last = None if snap['last'] is None else bits2val(snap['last'])
        return snap

# ---------- сценарий: Ньютон, снапшоты, саботаж, реплей ----------

def scenario():
    s = Session()
    s.execute('x = 2.0')
    s.execute('step[x_] := (x + 2.0/x)/2.0')
    r10 = s.execute('Nest[step, x, 10]')
    A = s.save('snap_A.json')
    print('A: Nest 10 = 0x%s | журнал %d' % (canon_bits(r10), len(A['journal'])))
    r25a = s.execute('Nest[step, x, 15]')
    B = s.save('snap_B.json')
    print('B: Nest 15 = 0x%s | журнал %d' % (canon_bits(r25a), len(B['journal'])))
    s.execute('x = 1e30')
    print('саботаж: x = 0x%s | журнал вырос до %d, снапшоты не тронуты' %
          (canon_bits(s.env['x']), len(s.journal)))
    s.restore('snap_A.json')
    print('restore A: отпечаток совпал, x = 0x%s' % canon_bits(s.env['x']))
    r25b = s.execute('Nest[step, x, 15]')
    k = len(A['journal'])
    okj = B['journal'][k:] == s.journal[k:]
    okl = canon_bits(r25b) == B['last']
    print('реплей: журнал байт-в-байт: %s (%d строк), last: %s' %
          (okj, len(s.journal) - k, okl))
    import math
    b = r10
    print('фикс.точка: (b + 2/b)/2 == b по битам: %s' % ((b + 2.0 / b) / 2.0 == b))
    print('math.sqrt(2) = 0x%s | итерация = 0x%s' %
          (canon_bits(math.sqrt(2.0)), canon_bits(b)))
    return okj and okl

if __name__ == '__main__':
    ok = scenario()
    print('ALL PASS' if ok else 'FAILED')
