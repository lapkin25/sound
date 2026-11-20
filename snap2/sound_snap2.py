
# sound_snap2.py - версия с патчами: списковый канон, двухступенчатый ref,
# журналируемые fold/table/foldlist, bits2val.
import re, json, hashlib, struct, math

def canon_bits(v):
    if isinstance(v, list):
        return '%d|%s' % (len(v), ','.join(canon_bits(x) for x in v))
    return struct.pack('>d', float(v)).hex()

def bits2val(hs):
    if '|' in hs:
        n, rest = hs.split('|', 1)
        return [bits2val(x) for x in rest.split(',')] if rest else []
    return struct.unpack('>d', bytes.fromhex(hs))[0]

def canon_hex(v):
    return '0x' + canon_bits(v)

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
            if w.endswith('_'):
                toks.append(('IDENT', w[:-1])); toks.append(('PAT', '_'))
            else:
                toks.append(('IDENT', w))
        else:
            s = m.group('op')
            if s not in _OPS:
                raise SyntaxError('нечитаемый символ %r на позиции %d' % (s, i - len(s)))
            toks.append(('OP', s))
    toks.append(('END', ''))
    return toks

class Parser:
    def __init__(self, toks):
        self.t = toks; self.i = 0
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
                self.eat(); continue
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
                    self.eat(); items.append(self.parse_expr())
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
                        self.eat(); args.append(self.parse_expr())
                self.eat('OP', ']')
                return ('call', t[1], args)
            return ('ref', t[1])
        raise SyntaxError('неожиданный токен %r' % (t,))

def parse(src):
    return Parser(lex(src)).parse_program()

class SoundError(Exception):
    pass

class Session:
    def __init__(self):
        self.env = {}; self.funcs = {}; self.journal = []; self.n = 0
        self.last = None

    def jline(self, fmt):
        self.n += 1
        self.journal.append(fmt % self.n)

    def bind(self, op, args, result):
        self.n += 1
        self.journal.append('t%d %s(%s) -> %s' % (self.n, op,
                            ','.join(canon_bits(a) for a in args), canon_bits(result)))
        return result

    def setname(self, name, val):
        self.jline('t%%d set(%s) -> %s' % (name, canon_bits(val)))
        self.env[name] = val
        return val

    def eval(self, node, env):
        k = node[0]
        if k == 'const':
            return node[1]
        if isinstance(node, (tuple, list)) and k == 'ref':
            name = node[1]
            if name in env:
                return env[name]
            if name in self.env:
                return self.env[name]
            raise SoundError('имя %s не задано' % name)
        if k == 'neg':
            v = self.eval(node[1], env)
            return self.bind('neg', [v], -v)
        if k == 'op':
            l = self.eval(node[2], env); r = self.eval(node[3], env)
            op = node[1]
            if op == '+': return self.bind('+', [l, r], l + r)
            if op == '-': return self.bind('-', [l, r], l - r)
            if op == '*': return self.bind('*', [l, r], l * r)
            if op == '/': return self.bind('/', [l, r], l / r)
        if k == 'cmp':
            l = self.eval(node[2], env); r = self.eval(node[3], env)
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
        if name == 'Fold':
            f = args[0]
            v0 = self.eval(args[1], env)
            lst = self.eval(args[2], env)
            fname = f[1] if isinstance(f, (tuple, list)) else '?'
            v = v0
            for item in lst:
                v = self.apply_fn(f, [v, item], env)
            self.jline('t%%d fold(%s,%s,%s) -> %s'
                       % (fname, canon_bits(v0), canon_bits(lst), canon_bits(v)))
            return v
        if name == 'Table':
            f = args[0]
            n = self.eval(args[1], env)
            fname = f[1] if isinstance(f, (tuple, list)) else '?'
            if isinstance(n, list):
                out = [self.apply_fn(f, [x], env) for x in n]
            else:
                if n != int(n) or n < 0:
                    raise SoundError('Table: счётчик должен быть целым неотрицательным, получено %r' % (n,))
                out = [self.apply_fn(f, [float(k)], env) for k in range(int(n))]
            self.jline('t%%d table(%s,%s) -> %s' % (fname, canon_bits(n), canon_bits(out)))
            return out
        if name == 'Mod':
            a = self.eval(args[0], env); b = self.eval(args[1], env)
            if b == 0.0:
                raise SoundError('Mod: деление на ноль')
            q = math.floor(a / b)
            while q * b > a:
                q -= 1.0
            while (q + 1.0) * b <= a:
                q += 1.0
            r = a - q * b
            self.jline('t%%d mod(%s,%s) -> %s' % (canon_bits(a), canon_bits(b), canon_bits(r)))
            return r
        if name == 'Quotient':
            a = self.eval(args[0], env); b = self.eval(args[1], env)
            if b == 0.0:
                raise SoundError('Quotient: деление на ноль')
            q = math.floor(a / b)
            while q * b > a:
                q -= 1.0
            while (q + 1.0) * b <= a:
                q += 1.0
            self.jline('t%%d quotient(%s,%s) -> %s' % (canon_bits(a), canon_bits(b), canon_bits(q)))
            return q
        if name == 'Part':
            lst = self.eval(args[0], env); i = self.eval(args[1], env)
            if not isinstance(lst, list):
                raise SoundError('Part: первый аргумент должен быть списком, получено %r' % (lst,))
            k = int(i)
            if not (0 <= k < len(lst)):
                raise SoundError('Part: индекс %d вне списка длины %d' % (k, len(lst)))
            r = lst[k]
            self.jline('t%%d part(%s,%s) -> %s' % (canon_bits(lst), canon_bits(i), canon_bits(r)))
            return r
        if name == 'FoldList':
            f = args[0]
            acc = self.eval(args[1], env)
            lst = self.eval(args[2], env)
            if not isinstance(lst, list):
                raise SoundError('FoldList: третий аргумент должен быть списком, получено %r' % (lst,))
            fname = f[1] if isinstance(f, (tuple, list)) else '?'
            out = [acc]
            for x in lst:
                acc = self.apply_fn(f, [acc, x], env)
                out.append(acc)
            self.jline('t%%d foldlist(%s,%s,%s) -> %s'
                       % (fname, canon_bits(acc), canon_bits(lst), canon_bits(out)))
            return out
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
