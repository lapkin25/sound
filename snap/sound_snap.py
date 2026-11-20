
# sound_snap.py — WL-слой над Sound со снапшотами Save/Restore.
# Имена по битам, функции как AST, журнал линейный и append-only.
import re, json, hashlib, struct

TOKEN = re.compile(r'''
    (?P<ws>\s+)
  | (?P<num>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
  | (?P<str>"[^"]*")
  | (?P<name>[A-Za-z_]\w*)
  | (?P<op>:=|==|!=|<=|>=|[+\-*/=;,{}()\[\]<>_])
''', re.X)

def tokenize(src):
    toks, i = [], 0
    while i < len(src):
        m = TOKEN.match(src, i)
        if not m: raise SyntaxError(f"lexer: {src[i:i+12]!r}")
        i = m.end()
        k = m.lastgroup
        if k == 'ws': continue
        if k == 'num':  toks.append(('num', float(m.group())))
        elif k == 'str': toks.append(('str', m.group()[1:-1]))
        elif k == 'name':
            t = m.group()
            if t.endswith('_'):
                toks.append(('name', t[:-1])); toks.append(('op', '_'))
            else:
                toks.append(('name', t))
        else: toks.append(('op', m.group()))
    toks.append(('end', ''))
    return toks

CMP_OPS = {'<': lambda a,b: a<b, '<=': lambda a,b: a<=b,
           '>': lambda a,b: a>b,  '>=': lambda a,b: a>=b,
           '==': lambda a,b: a==b,'!=': lambda a,b: a!=b}
ARITH = {'+': lambda a,b: a+b, '-': lambda a,b: a-b,
         '*': lambda a,b: a*b, '/': lambda a,b: a/b}

class Parser:
    def __init__(self, toks): self.t = toks; self.i = 0
    def peek(self): return self.t[self.i]
    def take(self): tok = self.t[self.i]; self.i += 1; return tok
    def expect(self, ch):
        k, v = self.take()
        if k != 'op' or v != ch: raise SyntaxError(f"ожидаю {ch!r}, получено {v!r}")
    def program(self):
        stmts = []
        while self.peek()[0] != 'end':
            stmts.append(self.stmt())
            if self.peek() == ('op', ';'): self.take()
            elif self.peek()[0] != 'end': raise SyntaxError(f"ожидаю ';', получено {self.peek()[1]!r}")
        return stmts
    def stmt(self):
        save = self.i
        k, v = self.take()
        if k == 'name':
            if self.peek() == ('op', '['):
                self.take()
                args = self.args()
                self.expect(']')
                if self.peek() == ('op', ':='):
                    self.take()
                    body = self.expr()
                    for a in args:
                        if a[0] != 'pat': raise SyntaxError("параметры должны быть вида x_")
                    return ('func', v, [a[1] for a in args], body)
                self.i = save
            if self.peek() == ('op', '='):
                self.take()
                return ('set', v, self.expr())
        self.i = save
        return ('expr', self.expr())
    def args(self):
        items = []
        if self.peek() != ('op', ']'):
            items.append(self.expr())
            while self.peek() == ('op', ','): self.take(); items.append(self.expr())
        return items
    def expr(self):
        l = self.term()
        if self.peek() in (('op','+'), ('op','-')):
            op = self.take()[1]
            r = self.expr()
            return ('bin', op, l, r)
        if self.peek()[0] == 'op' and self.peek()[1] in CMP_OPS:
            op = self.take()[1]
            r = self.term()
            return ('cmp', op, l, r)
        return l
    def term(self):
        l = self.factor()
        if self.peek() in (('op','*'), ('op','/')):
            op = self.take()[1]
            r = self.term()
            return ('bin', op, l, r)
        return l
    def factor(self):
        if self.peek() == ('op','-'):
            self.take(); return ('neg', self.factor())
        return self.atom()
    def atom(self):
        k, v = self.peek()
        if k == 'num': self.take(); return ('num', v)
        if k == 'str': self.take(); return ('str', v)
        if k == 'op' and v == '(': self.take(); e = self.expr(); self.expect(')'); return e
        if k == 'op' and v == '{':
            self.take(); items = self.args_list('}'); return ('list', items)
        if k == 'name':
            self.take()
            if self.peek() == ('op','_'): self.take(); return ('pat', v)
            if self.peek() == ('op','['):
                self.take(); args = self.args_list(']'); return ('call', v, args)
            return ('ref', v)
        raise SyntaxError(f"неожиданный токен {v!r}")
    def args_list(self, close):
        items = []
        if self.peek() != ('op', close):
            items.append(self.expr())
            while self.peek() == ('op', ','): self.take(); items.append(self.expr())
        self.expect(close)
        return items

def h(x):
    return '0x%016x' % struct.unpack('<Q', struct.pack('<d', x))[0]

def to_json(x):
    if isinstance(x, tuple): return [to_json(e) for e in x]
    if isinstance(x, list):  return [to_json(e) for e in x]
    return x
def from_json(x):
    if isinstance(x, list): return tuple(from_json(e) for e in x)
    return x

class Session:
    def __init__(self):
        self.env = {}
        self.journal = []
        self._tid = 0
    def fingerprint(self):
        return hashlib.sha256('\n'.join(self.journal).encode()).hexdigest()
    def bind(self, op, *vals):
        self._tid += 1
        r = ARITH[op](*vals)
        self.journal.append(f"t{self._tid} {op}({','.join(h(v) for v in vals)}) -> {h(r)}")
        return r
    def bind_cmp(self, op, a, b):
        self._tid += 1
        r = 1.0 if CMP_OPS[op](a, b) else 0.0
        self.journal.append(f"t{self._tid} {op}({h(a)},{h(b)}) -> {h(r)}")
        return r
    def bind_neg(self, a):
        self._tid += 1
        r = -a
        self.journal.append(f"t{self._tid} neg({h(a)}) -> {h(r)}")
        return r
    def run(self, src):
        out = []
        for st in Parser(tokenize(src)).program():
            if st[0] == 'set':
                v = self.eval(st[2], self.env)
                self.env[st[1]] = v
                out.append((st[1], v))
            elif st[0] == 'func':
                self.env[st[1]] = st
            else:
                v = self.eval(st[1], self.env)
                out.append(('echo', v))
        return out
    def eval(self, a, env):
        t = a[0]
        if t == 'num': return a[1]
        if t == 'str': return a[1]
        if t == 'ref':
            v = env.get(a[1])
            if v is None: raise NameError(f"имя {a[1]} не задано")
            if isinstance(v, float): return v
            if v[0] == 'thunk': return self.eval(v[1], v[2])
            return v
        if t == 'bin':
            l = self.eval(a[2], env); r = self.eval(a[3], env)
            return self.bind(a[1], l, r)
        if t == 'neg': return self.bind_neg(self.eval(a[1], env))
        if t == 'cmp':
            l = self.eval(a[2], env); r = self.eval(a[3], env)
            return self.bind_cmp(a[1], l, r)
        if t == 'list':
            return [self.eval(e, env) for e in a[1]]
        if t == 'call':
            name, args = a[1], a[2]
            if name in ('Nest','NestList','Fold','FoldList','Table','If','Save','Restore'):
                return self.builtin(name, args, env)
            v = env.get(name)
            if v is not None and isinstance(v, tuple) and v[0] == 'func':
                return self.apply(v, args, env)
            raise NameError(f"неизвестная функция {name}")
        raise SyntaxError(f"неизвестный узел {t}")
    def apply(self, fn, arg_asts, env):
        _, _, params, body = fn
        fenv = {}
        for p, ast in zip(params, arg_asts):
            fenv[p] = ('thunk', ast, env)
        return self.eval(body, fenv)
    def get_func(self, ast, env):
        if ast[0] == 'ref':
            v = env.get(ast[1])
            if isinstance(v, tuple) and v[0] == 'func': return v
        raise ValueError("первый аргумент должен быть именем функции")
    def builtin(self, name, args, env):
        if name == 'If':
            c = self.eval(args[0], env)
            return self.eval(args[1] if c != 0.0 else args[2], env)
        if name in ('Nest','NestList'):
            fn = self.get_func(args[0], env)
            x = self.eval(args[1], env)
            n = int(self.eval(args[2], env))
            hist = [x] if name == 'NestList' else None
            for _ in range(n):
                x = self.apply(fn, [('num', x)], env)
                if hist is not None: hist.append(x)
            return hist if hist is not None else x
        if name in ('Fold','FoldList'):
            fn = self.get_func(args[0], env)
            acc = self.eval(args[1], env)
            lst = self.eval(args[2], env)
            hist = [acc] if name == 'FoldList' else None
            for v in lst:
                acc = self.apply(fn, [('num', acc), ('num', v)], env)
                if hist is not None: hist.append(acc)
            return hist if hist is not None else acc
        if name == 'Table':
            expr_ast = args[0]
            spec = args[1]
            if spec[0] != 'list' or len(spec[1]) != 2 or spec[1][0][0] != 'ref':
                raise SyntaxError("Table[expr, {var, n}]")
            var = spec[1][0][1]; n = int(self.eval(spec[1][1], env))
            out = []
            for k in range(n):
                out.append(self.eval(expr_ast, {**env, var: ('thunk', ('num', float(k)), env)}))
            return out
        if name == 'Save':
            file = args[0][1]
            names = {}
            for k, v in self.env.items():
                if isinstance(v, float): names[k] = h(v)
                elif isinstance(v, tuple) and v[0] == 'func':
                    names[k] = {"func": {"params": v[2], "body": to_json(v[3])}}
                else: raise TypeError(f"имя {k}: несохраняемое значение")
            data = {"names": names, "journal_len": len(self.journal),
                    "fingerprint": self.fingerprint()}
            with open(file, 'w') as f: json.dump(data, f, indent=1)
            print(f"[SAVE] {file}: имена {len(names)}, журнал {len(self.journal)} биндов")
            return 0.0
        if name == 'Restore':
            file = args[0][1]
            with open(file) as f: data = json.load(f)
            n = data["journal_len"]
            if len(self.journal) < n: raise ValueError("журнал короче снапшота")
            self.journal = self.journal[:n]
            self._tid = n
            got = self.fingerprint()
            if got != data["fingerprint"]:
                raise ValueError("отпечаток журнала не совпал — журнал разошёлся с хвостом")
            env2 = {}
            for k, v in data["names"].items():
                if isinstance(v, str):
                    env2[k] = struct.unpack('<d', struct.pack('<Q', int(v, 16)))[0]
                elif isinstance(v, dict) and 'func' in v:
                    env2[k] = ('func', k, v['func']['params'], from_json(v['func']['body']))
            self.env = env2
            print(f"[RESTORE] {file}: журнал усечён до {n}, отпечаток OK")
            return 0.0
        raise SyntaxError(f"неизвестный builtin {name}")
