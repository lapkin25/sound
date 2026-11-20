import re

KEYWORDS = {'spec', 'in', 'invariant'}

OP_TOKENS = ['==', '!=', '<=', '>=', '->',
             '+', '-', '*', '/', '%', '<', '>',
             '?', ':', '=', ';', '(', ')', '[', ']', ',']

_OP_ALT = '|'.join(re.escape(t) for t in OP_TOKENS)

TOKEN_RE = re.compile(
    '(?P<ws>\\s+)'
    '|(?P<num>\\d+\\.\\d+|\\d+)'
    '|(?P<id>[A-Za-z_][A-Za-z_0-9]*)'
    '|(?P<str>"(?:[^"\\\\]|\\\\.)*")'
    '|(?P<op>' + _OP_ALT + ')'
)

def lex(text):
    toks, i = [], 0
    while i < len(text):
        m = TOKEN_RE.match(text, i)
        if not m: raise ValueError('bad char %r at %d' % (text[i], i))
        i = m.end()
        if m.lastgroup == 'ws': continue
        kind = {'num':'num','id':'id','str':'str','op':'op'}[m.lastgroup]
        v = m.group()
        if kind == 'id' and v in KEYWORDS: kind = 'kw'
        if kind == 'num': v = float(v) if '.' in v else int(v)
        toks.append((kind, v))
    toks.append(('eof',''))
    return toks

class P:
    def __init__(self, toks): self.t = toks; self.i = 0
    def peek(self, k=0): return self.t[min(self.i+k, len(self.t)-1)]
    def next(self): tok = self.t[self.i]; self.i += 1; return tok
    def eat(self, kind, v=None):
        k, val = self.next()
        if k != kind or (v is not None and val != v):
            raise ValueError('expected %s %r, got %s %r' % (kind, v, k, val))
        return val
    def at(self, kind, v=None):
        k, val = self.peek()
        return k == kind and (v is None or val == v)

def parse_type(p):
    name = p.eat('id')
    if name == 'Matrix' and p.at('op','['):
        p.next(); dims = []
        while not p.at('op',']'):
            k, v = p.next()
            if k == 'num': dims.append(int(v))
            elif k == 'op' and v == ',': continue
            else: raise ValueError('bad dim %s %r' % (k, v))
        p.eat('op',']')
        marker = ''
        if p.at('id') and p.peek()[1] in ('C','F'): marker = p.next()[1]
        return ('Matrix', dims, marker)
    return ('Name', name)

def parse_atom(p):
    k, v = p.peek()
    if k in ('num','str'): p.next(); return ['lit', v]
    if k in ('id','kw'): p.next(); return ['sym', v]
    if k == 'op' and v == '(':
        p.next(); e = parse_expr(p); p.eat('op',')'); return e
    raise ValueError('bad atom %s %r' % (k, v))

def parse_expr(p):
    left = parse_atom(p)
    while True:
        k, v = p.peek()
        if k == 'op' and v in ('+','-','*','/','%','==','!=','<','>','<=','>=','?'):
            p.next()
            right = parse_atom(p)
            left = [v, left, right]
        else: break
    return left

def parse_params(p):
    out = []
    while p.at('id'):
        name = p.next()[1]
        ty = None
        if p.at('op',':'): p.next(); ty = parse_type(p)
        out.append((name, ty))
    return out

def parse_rule(p, toks):
    KINDS = ('rule','fact','wire')
    MODS = ('pure','safe')
    head_ids = []
    while toks.at('id') and toks.peek()[1] in KINDS + MODS:
        head_ids.append(toks.next()[1])
    mods = sorted({v for v in head_ids if v in MODS})
    name = toks.next()[1]
    params = parse_params(toks)
    toks.eat('op','=')
    body = []
    while True:
        k, v = toks.peek()
        if k == 'eof' or (k == 'kw' and v == 'invariant') or (k == 'op' and v == ';'): break
        body.append(toks.next())
    body = _toks_to_expr(body) if body else None
    inv = None
    if toks.at('kw') and toks.peek()[1] == 'invariant':
        toks.next()
        inv = []
        while True:
            k, v = toks.peek()
            if k == 'eof' or (k == 'op' and v == ';'): break
            inv.append(toks.next())
        inv = _toks_to_expr(inv) if inv else None
    if toks.at('op',';'): toks.next()
    return ('rule', name, params, body, inv, sorted(mods))

def _toks_to_expr(toks):
    items = []
    for k, v in toks:
        if k in ('num','str'): items.append(['lit', v])
        elif k in ('id','kw'): items.append(['sym', v])
        else: items.append(v)
    return _fold(items)

def _fold(items):
    depth = 0
    for prio_ops in (['==','!=','<','>','<=','>=','?'], ['+','-'], ['*','/','%']):
        depth = 0
        for i, it in enumerate(items):
            if isinstance(it, list): continue
            if isinstance(it, str) and it in prio_ops and depth == 0:
                return [it, _fold(items[:i]), _fold(items[i+1:])]
            depth += (it=='(') - (it==')')
    if len(items) == 1: return items[0]
    if items[0] == '(' and items[-1] == ')': return _fold(items[1:-1])
    return items[0] if items else None

def parse_fact(p):
    while p.at('id') and p.peek()[1] in ('fact','wire','rule','pure','safe'): p.next()
    name = p.next()[1]
    args = []
    if p.at('op',':'): p.next()
    while not p.at('op',';') and not p.at('eof'):
        k, v = p.next()
        if k in ('num','str'): args.append(('lit', v))
        elif k in ('id','kw'): args.append(('ref', v))
        else: args.append(('op', v))
    if p.at('op',';'): p.next()
    return ('fact', name, args)

def parse_wire(p):
    while p.at('id') and p.peek()[1] in ('fact','wire','rule','pure','safe'): p.next()
    name = p.next()[1]
    p.eat('op','->')
    dst = p.next()[1]
    ty = None
    if p.at('op',':'): p.next(); ty = parse_type(p)
    if p.at('op',';'): p.next()
    return ('wire', name, dst, ty)

def parse_spec(text):
    toks = P(lex(text))
    toks.eat('kw','spec')
    name = toks.next()[1]
    if toks.at('op',';'): toks.next()
    MODS = {'rule','fact','wire','pure','safe'}
    items = []
    while not toks.at('eof'):
        k, v = toks.peek()
        if k != 'id': raise ValueError('unexpected %s %r' % (k, v))
        kind = None
        j = toks.i
        j2 = j
        while j2 < len(toks.t) and toks.t[j2] != ('op',';') and toks.t[j2][0] != 'eof':
            if toks.t[j2] == ('op','='): kind = 'rule'; break
            if toks.t[j2] == ('op','->'): kind = 'wire'; break
            j2 += 1
        if kind == 'fact': items.append(parse_fact(toks))
        elif kind == 'wire': items.append(parse_wire(toks))
        elif kind == 'rule': items.append(parse_rule(toks, toks))
        else: items.append(parse_fact(toks))
    return ('spec', name, items)

def _body_syms(e, acc):
    if not isinstance(e, list): return acc
    if e and e[0] == 'sym': acc.append(e[1]); return acc
    for x in e:
        if isinstance(x, list): _body_syms(x, acc)
    return acc

def static_checks(spec):
    _, name, items = spec
    facts = {it[1] for it in items if it[0]=='fact'}
    rules = {it[1] for it in items if it[0]=='rule'}
    known = facts | rules
    errors = {'SC-002': None, 'SC-061': None, 'SC-060': None}
    for it in items:
        if it[0] != 'rule': continue
        _, rname, params, body, inv, _ = it
        bound = {pn for pn, _ in params}
        for e in (body, inv):
            for s in _body_syms(e, []):
                if s not in bound and s not in known and errors['SC-002'] is None:
                    errors['SC-002'] = '%s: unknown %s' % (rname, s)
    for it in items:
        if it[0] != 'wire': continue
        _, w, dst, ty = it
        if dst not in known and errors['SC-060'] is None:
            errors['SC-060'] = 'wire %s: unknown %s' % (w, dst)
    return [c for c in ('SC-002','SC-061','SC-060') if errors[c]]

def _ty_str(ty):
    if ty is None: return ''
    if ty[0] == 'Name': return ty[1]
    return 'Matrix[' + ','.join(str(d) for d in ty[1]) + ']' + ty[2]

def _fact_arg(a):
    if a[0] == 'lit':
        v = a[1]
        return v if isinstance(v, str) and v.startswith('"') else str(v)
    if a[0] == 'ref': return a[1]
    return a[1]

def _expr_str(e):
    if e is None: return ''
    if isinstance(e, list):
        if e and e[0] == 'lit':
            v = e[1]
            return v if isinstance(v, str) and v.startswith('"') else str(v)
        if e and e[0] == 'sym': return e[1]
        if len(e) == 3 and isinstance(e[0], str) and e[0] in ('+','-','*','/','%','==','!=','<','>','<=','>=','?'):
            return '%s %s %s' % (_expr_str(e[1]), e[0], _expr_str(e[2]))
        return ' '.join(_expr_str(x) for x in e)
    return str(e)

def serialize(spec):
    _, name, items = spec
    order = {'fact':0, 'wire':1, 'rule':2}
    items = sorted(items, key=lambda it: (order[it[0]], it[1]))
    out = ['spec %s ;' % name]
    for it in items:
        if it[0] == 'fact':
            args = ' '.join(_fact_arg(x) for x in it[2])
            out.append('fact %s %s ;' % (it[1], args))
        elif it[0] == 'wire':
            t = (' : ' + _ty_str(it[3])) if it[3] else ''
            out.append('wire %s -> %s%s ;' % (it[1], it[2], t))
        else:
            mods = ' '.join(it[5])
            prefix = (mods + ' ') if mods else ''
            params = ' '.join(p if t is None else ('%s: %s' % (p, _ty_str(t))) for p, t in it[2])
            body = _expr_str(it[3])
            inv = (' invariant ' + _expr_str(it[4])) if it[4] else ''
            out.append(('%srule %s %s = %s%s ;' % (prefix, it[1], params, body, inv)).strip())
    return '\n'.join(out)

def roundtrip(text):
    s = serialize(parse_spec(text))
    return serialize(parse_spec(s)) == s
