# sound_stage2.py - Sound v0.2, stage 2 etalon:
# spec parser (spec/fact/wire/pure rule/invariant), rule runner with
# byte-exact journal (par. 3.8), static checks SC-002 / SC-060.
# canon (6.4): Python float.hex emits exactly "0x1.<13 hex>p(+|-)e" for
# finite nonzero doubles, incl. denormals "0x0.<13 hex>p-1022".
import math, re

_TOK = re.compile(r'\d+\.\d+|\d+|[A-Za-z_]\w*|->|>=|<=|==|!=|[-+*/()<>:,=]')

def tokenize(s):
    s = re.sub(r'#[^\n]*', ' ', s)
    return _TOK.findall(s)

def parse_expr(toks):
    pos = [0]
    def peek(): return toks[pos[0]] if pos[0] < len(toks) else None
    def take(): t = toks[pos[0]]; pos[0] += 1; return t
    # all levels right-associative (par. 2.6)
    def cmp_():
        node = addsub()
        if peek() in ('>=', '<=', '==', '!=', '>', '<'):
            op = take()
            return {'op': op, 'l': node, 'r': cmp_()}
        return node
    def addsub():
        node = muldiv()
        if peek() in ('+', '-'):
            op = take()
            return {'op': op, 'l': node, 'r': addsub()}
        return node
    def muldiv():
        node = unary()
        if peek() in ('*', '/'):
            op = take()
            return {'op': op, 'l': node, 'r': muldiv()}
        return node
    def unary():
        if peek() == '-':
            take()
            return {'op': 'neg', 'l': unary()}
        return atom()
    def atom():
        t = peek()
        if t is None: raise ValueError('unexpected end of expression')
        if t == '(':
            take(); node = cmp_()
            if take() != ')': raise ValueError('missing )')
            return node
        if re.match(r'^\d', t):
            take(); return {'num': float(t)}
        if re.match(r'^[A-Za-z_]', t):
            take(); return {'name': t}
        raise ValueError('bad atom: %r' % t)
    node = cmp_()
    if pos[0] != len(toks): raise ValueError('trailing tokens in expression')
    return node

def parse_spec(src):
    spec = {'name': None, 'facts': {}, 'wires': [], 'rules': {}, 'order': []}
    for stmt in src.split(';'):
        stmt = stmt.strip()
        if not stmt: continue
        t = tokenize(stmt)
        if not t: continue
        if t[0] == 'spec':
            spec['name'] = t[1]
        elif t[0] == 'fact':
            spec['facts'][t[1]] = float(t[2])
        elif t[0] == 'wire':
            if t[2] != '->' or t[4] != ':': raise ValueError('bad wire: ' + stmt)
            spec['wires'].append({'src': t[1], 'dst': t[3],
                                  'dtype': ''.join(t[5:])})
        elif t[0] == 'pure' and t[1] == 'rule':
            rname, param = t[2], t[3]
            if t[4] != '=': raise ValueError('bad rule: ' + stmt)
            body_toks = t[5:]
            inv = None
            if 'invariant' in body_toks:
                i = body_toks.index('invariant')
                inv = parse_expr(body_toks[i + 1:])
                body_toks = body_toks[:i]
            spec['rules'][rname] = {'param': param, 'body': parse_expr(body_toks),
                                    'invariant': inv}
            spec['order'].append(rname)
        else:
            raise ValueError('bad statement: ' + stmt)
    return spec

def _ieee_div(a, b):
    # IEEE semantics with a banned-NaN wrapper: x/0.0 -> signed inf, 0.0/0.0 -> nan
    if b == 0.0:
        if a == 0.0 or (isinstance(a, float) and math.isnan(a)):
            return float('nan')
        return math.copysign(float('inf'), a) * math.copysign(1.0, b)
    return a / b

def apply_op(op, a, b):
    if op == '+': return a + b
    if op == '-': return a - b
    if op == '*': return a * b
    if op == '/': return _ieee_div(a, b)
    if op == '>': return a > b
    if op == '<': return a < b
    if op == '>=': return a >= b
    if op == '<=': return a <= b
    if op == '==': return a == b
    if op == '!=': return a != b
    raise ValueError('bad op: ' + op)

def canon(x):
    if math.isnan(x): return 'nan'
    if math.isinf(x): return 'inf' if x > 0 else '-inf'
    if x == 0.0:
        return '-0x0.0p+0' if math.copysign(1.0, x) < 0 else '0x0.0p+0'
    return float.hex(x)

def internal_count(node):
    if 'op' not in node: return 0
    c = 1 + internal_count(node['l'])
    if 'r' in node: c += internal_count(node['r'])
    return c

def eval_silent(node, vals, facts):
    if 'num' in node: return node['num']
    if 'name' in node:
        n = node['name']
        if n in vals: return vals[n]
        if n in facts: return facts[n]
        raise ValueError('unknown name: ' + n)
    a = eval_silent(node['l'], vals, facts)
    b = eval_silent(node['r'], vals, facts) if 'r' in node else None
    return -a if node['op'] == 'neg' else apply_op(node['op'], a, b)

def _bind(w, name, v):
    return 'bind %-*s = Float64 %s' % (w, name, canon(v))

# journal (3.8): invariant first, silently; on violation -> one-line err log;
# then param binds; then t0, t1, ... in post-order (left, right, op);
# literals and direct t-names emit no bind; final "result  = Float64 <canon>";
# name field padded to max(2, longest name in the log).
def run_rule(spec, rname, args):
    rule = spec['rules'][rname]
    vals = {}
    for k, mv in args.items():
        vals[k] = float('nan') if isinstance(mv, dict) else float(mv)
    if rule['invariant'] is not None:
        if not eval_silent(rule['invariant'], vals, spec['facts']):
            return None, ['err DomainError %s: invariant' % rname]
    w = 2
    for n in list(vals) + ['t%d' % i for i in range(internal_count(rule['body']))]:
        w = max(w, len(n))
    log = [_bind(w, k, v) for k, v in vals.items()]
    cnt = [0]
    def ev(node):
        if 'num' in node: return node['num']
        if 'name' in node:
            n = node['name']
            return vals[n] if n in vals else spec['facts'][n]
        a = ev(node['l'])
        b = ev(node['r']) if 'r' in node else None
        v = -a if node['op'] == 'neg' else apply_op(node['op'], a, b)
        nm = 't%d' % cnt[0]; cnt[0] += 1
        log.append(_bind(w, nm, v))
        return v
    v = ev(rule['body'])
    log.append('result  = Float64 %s' % canon(v))
    return v, log

def _leaves(node, out):
    if 'num' in node: return
    if 'name' in node: out.append(node['name']); return
    _leaves(node['l'], out)
    if 'r' in node: _leaves(node['r'], out)

# SC-002: unknown identifier in a rule body (not its param, not a fact);
# SC-060: wire target is not a declared rule; fixed order 002 -> 060.
# SC-061 is reserved and unreachable from the grammar.
def static_checks(spec):
    errs = []
    facts = set(spec['facts'])
    for rname in spec['order']:
        r = spec['rules'][rname]
        known = facts | {r['param']}
        used = []
        _leaves(r['body'], used)
        if r['invariant'] is not None: _leaves(r['invariant'], used)
        for n in used:
            if n not in known:
                errs.append('SC-002: unknown name %s in rule %s' % (n, rname))
    for wire in spec['wires']:
        if wire['dst'] not in spec['rules']:
            errs.append('SC-060: wire target %s is not a declared rule' % wire['dst'])
    return errs
