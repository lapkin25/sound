# sound_compiler.py - компилятор Sound v0.2
# Лексер/парсер: каноническая фигурная форма + легаси-алиасы (spec X;, pure rule,
# обе формы fact и wire). Статика SC-002/SC-060. Партитура-репетиция строится
# через единый sound_engine: локальный синтезатор компилятора удалён.
import re
from sound_engine import make_event, SoundEngine

KEYWORDS = ('spec', 'fact', 'rule', 'pure', 'wire', 'invariant')

class SpecError(Exception):
    pass

_TOKEN_RE = re.compile(
    r'(?P<num>\d+\.\d+|\d+)'
    r'|(?P<name>[A-Za-z_]\w*)'
    r'|(?P<arrow>->)'
    r'|(?P<cmp>>=|<=|==|!=)'
    r'|(?P<sym>[{}():;,=+*/<>-])'
    r'|(?P<ws>\s+)')

def tokenize(text):
    toks, i, n = [], 0, len(text)
    while i < n:
        m = _TOKEN_RE.match(text, i)
        if not m:
            raise SpecError('lexical error at %r' % text[i:i + 10])
        i = m.end()
        if m.lastgroup != 'ws':
            toks.append((m.lastgroup, m.group()))
    toks.append(('eof', ''))
    return toks

class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0
    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else ('eof', '')
    def at(self, val):
        knd, v = self.peek()
        return v == val and knd in ('name', 'sym', 'cmp', 'arrow')
    def eat(self, kind=None, val=None):
        knd, v = self.peek()
        if kind and knd != kind:
            raise SpecError('expected %s, got %s %r' % (kind, knd, v))
        if val and v != val:
            raise SpecError('expected %r, got %r' % (val, v))
        self.i += 1
        return v

# --- выражения: правостороннее свёртывание цепочек (контракт эталона) ---
def _chain(op, parts):
    node = parts[-1]
    for x in reversed(parts[:-1]):
        node = [op, x, node]
    return node

def parse_expr(p, stop=()):
    parts, op = [parse_add(p, stop)], None
    while p.peek()[0] == 'cmp':
        op = p.eat('cmp'); parts.append(parse_add(p, stop))
    return _chain(op, parts) if op else parts[0]

def parse_add(p, stop):
    parts, op = [parse_mul(p, stop)], None
    while p.peek() == ('sym', '+') or p.peek() == ('sym', '-'):
        op = p.eat('sym'); parts.append(parse_mul(p, stop))
    return _chain(op, parts) if op else parts[0]

def parse_mul(p, stop):
    parts, op = [parse_unary(p, stop)], None
    while p.peek() == ('sym', '*') or p.peek() == ('sym', '/'):
        op = p.eat('sym'); parts.append(parse_unary(p, stop))
    return _chain(op, parts) if op else parts[0]

def parse_unary(p, stop):
    if p.peek() == ('sym', '-'):
        p.eat('sym')
        return ['neg', parse_unary(p, stop)]
    return parse_primary(p, stop)

def parse_primary(p, stop):
    knd, v = p.peek()
    if knd == 'num':
        p.eat('num'); return float(v)
    if knd == 'name':
        if v in KEYWORDS:
            raise SpecError('unexpected keyword %r' % v)
        p.eat('name'); return v
    if p.peek() == ('sym', '('):
        p.eat('sym', '(')
        e = parse_expr(p, stop + (')',))
        p.eat('sym', ')')
        return e
    raise SpecError('unexpected token %r in expression' % v)

# --- операторы ---
def parse_stmt(p, facts, rules, wires):
    knd, v = p.peek()
    if knd != 'name':
        raise SpecError('unexpected token %r' % v)
    if v == 'fact':
        p.eat('name', 'fact')
        nm = p.eat('name'); p.eat('sym', '=')
        num = float(p.eat('num'))
        if p.at(':'):
            p.eat('sym', ':'); p.eat('name')   # тип факта
        p.eat('sym', ';')
        facts[nm] = num
    elif v in ('rule', 'pure'):
        if v == 'pure':
            p.eat('name', 'pure')
        p.eat('name', 'rule')
        nm = p.eat('name')
        params, types = [], {}
        if p.at('('):
            p.eat('sym', '(')
            while not p.at(')'):
                pn = p.eat('name')
                params.append(pn)
                if p.at(':'):
                    p.eat('sym', ':'); types[pn] = p.eat('name')
                if p.at(','):
                    p.eat('sym', ',')
            p.eat('sym', ')')
        else:
            params.append(p.eat('name'))       # легаси: один параметр
        ret = None
        if p.at('->'):
            p.eat('arrow'); ret = p.eat('name')
        inv = None
        if p.at('invariant'):                  # форма v0.2: инвариант до знака =
            p.eat('name', 'invariant')
            inv = parse_expr(p, stop=('=',))
        p.eat('sym', '=')
        tree = parse_expr(p)
        if inv is None and p.at('invariant'):  # легаси: инвариант после тела
            p.eat('name', 'invariant')
            inv = parse_expr(p)
        p.eat('sym', ';')
        rules[nm] = {'params': params, 'param_types': types,
                     'ret': ret, 'inv': inv, 'tree': tree}
    elif v == 'wire':
        p.eat('name', 'wire')
        a = p.eat('name')
        if p.at('->'):
            p.eat('arrow'); b = p.eat('name')
            if p.at(':'):
                p.eat('sym', ':'); p.eat('name')
            p.eat('sym', ';')
            wires.append({'src': a, 'tgt': b})
        elif p.at('='):
            p.eat('sym', '='); b = p.eat('name')
            p.eat('sym', ';')
            wires.append({'src': b, 'tgt': a})  # wire A = B  <=>  B -> A
        else:
            raise SpecError('bad wire after %r' % a)
    else:
        raise SpecError('unexpected statement %r' % v)

def parse_spec(text):
    p = Parser(tokenize(text))
    p.eat('name', 'spec')
    name = p.eat('name')
    facts, rules, wires = {}, {}, []
    if p.peek() == ('sym', '{'):
        p.eat('sym', '{')
        while p.peek() != ('sym', '}'):
            parse_stmt(p, facts, rules, wires)
        p.eat('sym', '}')
    else:
        p.eat('sym', ';')                          # легаси-алиас: spec X;
        while p.peek()[0] != 'eof':
            parse_stmt(p, facts, rules, wires)
    return {'name': name, 'facts': facts, 'rules': rules, 'wires': wires}

# --- статические проверки ---
def leaves(tree):
    if isinstance(tree, str):
        return [tree]
    if isinstance(tree, (int, float)):
        return []
    out = []
    for x in tree[1:]:
        out.extend(leaves(x))
    return out

def static_checks(spec):
    errs = []
    for nm, r in spec['rules'].items():
        for t in (r['tree'], r['inv']):
            if t is None:
                continue
            for leaf in leaves(t):
                if leaf not in r['params'] and leaf not in spec['facts']:
                    errs.append('SC-002: unknown name %s in rule %s' % (leaf, nm))
    for w in spec['wires']:
        if w['tgt'] not in spec['rules']:
            errs.append('SC-060: wire target %s is not a declared rule' % w['tgt'])
    return errs

# --- партитура-репетиция: теперь через единый движок ---
def build_score(spec, profile='rehearsal', path='score.wav'):
    eng = SoundEngine()
    for nm in spec['facts']:
        eng.add('node_start', node=nm, runtime='fact')
    for nm, r in spec['rules'].items():            # топологический порядок = порядок объявления
        eng.add('node_start', node=nm, runtime=r.get('runtime', 'python'))
    if any(r['inv'] is not None for r in spec['rules'].values()):
        eng.add('invariant_ok')
    eng.render_to(path, profile)
    return eng

if __name__ == '__main__':
    import json
    S = json.load(open('fixtures_stage2.json'))
    legacy = parse_spec(S['spec_source'])
    v02 = parse_spec(S['spec_source_v02'])
    # кросс-чек грамматики: деревья обеих форм обязаны совпасть с эталонными
    ok = True
    for spec, tag in ((legacy, 'legacy'), (v02, 'v02')):
        for nm, r in spec['rules'].items():
            want = S['rules'][nm]['tree']
            good = r['tree'] == want
            ok &= good
            print('%-8s %-13s tree %s' % (tag, nm, 'MATCH' if good else 'MISMATCH'))
    print('grammar unity:', 'OK' if ok else 'FAIL')
    for sv in S['static_vectors']:
        got = static_checks(parse_spec(sv['spec']))
        good = got == sv['expect']
        print('%s: %s' % (sv['name'], 'PASS' if good else 'FAIL %r vs %r' % (got, sv['expect'])))
