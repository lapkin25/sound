# sound_stage2.py - Sound v0.2 etalon:
# unified spec parser (spec/fact/wire/rule/invariant) that SUBSUMES the
# stage-1 compiler grammar and the stage-2 pure-rule grammar, rule runner
# with byte-exact journal (par. 3.8), static checks SC-002 / SC-060.
#
# Grammar layers (decision record: sound_spec_v0.2.md):
#   CORE (conformance-proven): facts with values, pure rules as expressions,
#   wires between pure nodes, per-rule invariants, Float64 journal.
#   EXT (compiler-only): typed signatures, opaque rules without bodies,
#   wire ports/modes/handles, requires-clauses. The etalon parses CORE and
#   rejects EXT nodes loudly; the compiler parses the superset.
#
# canon (6.4): Python float.hex emits exactly "0x1.<13 hex>p(+|-)e" for
# finite nonzero doubles, incl. denormals "0x0.<13 hex>p-1022".
import math, re, struct

_TOK = re.compile(r'\d+\.\d+|\d+|[A-Za-z_]\w*|->|>=|<=|==|!=|[-+*/()<>:,=.]+')

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

def _split_params(toks, stmt):
    # params inside ( ... ): p | p : T, comma-separated
    groups, cur = [], []
    for tk in toks:
        if tk == ',': groups.append(cur); cur = []
        else: cur.append(tk)
    groups.append(cur)
    out = []
    for g in groups:
        if not g: raise ValueError('empty param in: ' + stmt)
        if len(g) == 1: out.append((g[0], 'Float64'))
        elif len(g) == 3 and g[1] == ':': out.append((g[0], g[2]))
        else: raise ValueError('bad param: ' + stmt)
    return out

def _parse_rule_stmt(spec, t, stmt):
    # legacy: pure rule NAME PARAM = body ;  (invariant may trail the body)
    if t[0] == 'pure' and t[1] == 'rule':
        rname, param = t[2], t[3]
        if t[4] != '=': raise ValueError('bad rule: ' + stmt)
        body_toks = t[5:]
        inv = None
        if 'invariant' in body_toks:
            i = body_toks.index('invariant')
            inv = parse_expr(body_toks[i + 1:])
            body_toks = body_toks[:i]
        spec['rules'][rname] = {'param': param, 'params': [param],
                                'body': parse_expr(body_toks), 'invariant': inv}
        spec['order'].append(rname)
        return
    # v0.2: rule NAME ( p [: T], ... ) [-> T] [invariant expr] = body
    rname = t[1]; i = 2
    if i < len(t) and t[i] == '(':
        j = t.index(')', i)
        params = _split_params(t[i + 1:j], stmt)
        rest = t[j + 1:]
    else:
        params = [(t[i], 'Float64')]
        rest = t[i + 1:]
    ret = 'Float64'
    if rest[:1] == ['->']:
        ret = rest[1]; rest = rest[2:]
    inv = None
    if rest[:1] == ['invariant']:
        eq = rest.index('=')          # invariant expr has no bare '='
        inv = parse_expr(rest[1:eq])
        rest = rest[eq:]
    if not rest or rest[0] != '=':
        raise ValueError('rule without body is outside the v0.2 core: ' + stmt)
    body = parse_expr(rest[1:])
    spec['rules'][rname] = {'param': params[0][0],
                            'params': [p for p, _ in params],
                            'param_types': {p: ty for p, ty in params},
                            'ret': ret, 'body': body, 'invariant': inv}
    spec['order'].append(rname)

def _bare(nm):
    return nm.split('.')[0]

def _parse_wire(spec, t, stmt):
    # legacy: wire SRC -> DST : DTYPE
    if len(t) > 2 and t[2] == '->':
        if len(t) != 6 or t[4] != ':': raise ValueError('bad wire: ' + stmt)
        spec['wires'].append({'src': t[1], 'dst': t[3], 'dtype': t[5]})
        return
    # v0.2: wire DST[.port] = SRC[.port] [as mode] [handle Err]
    eq = t.index('=')
    dtoks, rest = t[1:eq], t[eq + 1:]
    if len(dtoks) == 1: dst = dtoks[0]
    elif len(dtoks) == 3 and dtoks[1] == '.': dst = dtoks[0] + '.' + dtoks[2]
    else: raise ValueError('bad wire: ' + stmt)
    src = rest[0]; i = 1
    if i < len(rest) and rest[i] == '.':
        src = src + '.' + rest[i + 1]; i += 2
    mode = 'copy'; handle = None
    if i < len(rest) and rest[i] == 'as':
        mode = rest[i + 1]; i += 2
    if i < len(rest) and rest[i] == 'handle':
        handle = rest[i + 1]; i += 2
    if i != len(rest): raise ValueError('bad wire: ' + stmt)
    spec['wires'].append({'src': _bare(src), 'dst': _bare(dst),
                          'dtype': 'Float64', 'mode': mode, 'handle': handle})

def _parse_fact(spec, t, stmt):
    # fact NAME = VALUE [: TYPE]      (VALUE: plain decimal, opt. minus)
    if t[2] != '=': raise ValueError('bad fact: ' + stmt)
    i = 3; neg = False
    if t[i] == '-': neg = True; i += 1
    val = float(t[i]); i += 1
    typ = 'Float64'
    if i < len(t) and t[i] == ':':
        typ = t[i + 1]; i += 2
    if i != len(t): raise ValueError('bad fact: ' + stmt)
    spec['facts'][t[1]] = -val if neg else val
    spec['fact_types'][t[1]] = typ

def parse_spec(src):
    # canonical v0.2 header: spec NAME { statements }  (braces, no nesting);
    # legacy alias: spec NAME; as a statement. Both are accepted everywhere.
    m = re.search(r'spec\s+(\w+)\s*\{', src)
    if m:
        if re.search(r'spec\s+\w+\s*\{[^}]*\{', src):
            raise ValueError('nested spec blocks are not supported in v0.2')
        name, body = m.group(1), src[m.end():src.rfind('}')]
    else:
        name, body = None, src
    spec = {'name': name, 'facts': {}, 'fact_types': {}, 'wires': [],
            'rules': {}, 'order': [], 'invariants': []}
    for stmt in body.split(';'):
        stmt = stmt.strip()
        if not stmt: continue
        t = tokenize(stmt)
        if not t: continue
        if t[0] == 'spec':
            if len(t) != 2: raise ValueError('bad spec header: ' + stmt)
            spec['name'] = t[1]
        elif t[0] == 'fact':
            _parse_fact(spec, t, stmt)
        elif t[0] == 'rule' or (len(t) > 1 and t[0] == 'pure' and t[1] == 'rule'):
            _parse_rule_stmt(spec, t, stmt)
        elif t[0] == 'wire':
            _parse_wire(spec, t, stmt)
        elif t[0] == 'invariant':
            spec['invariants'].append(parse_expr(t[1:]))
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
# then param binds (declaration order); then t0, t1, ... in post-order
# (left, right, op); literals and direct t-names emit no bind; final
# "result  = Float64 <canon>"; name field padded to max(2, longest name).
def run_rule(spec, rname, args):
    rule = spec['rules'][rname]
    vals = {}
    for k, mv in args.items():
        if isinstance(mv, dict):
            vals[k] = struct.unpack('>d', bytes.fromhex(mv['hex_bits']))[0]
        else:
            vals[k] = float(mv)
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

# SC-002: unknown identifier (not a param, not a fact) in a rule body,
# an invariant, or a top-level invariant;
# SC-060: wire target is not a declared rule; fixed order 002 -> 060.
# SC-061 is reserved and unreachable from the grammar.
def static_checks(spec):
    errs = []
    facts = set(spec['facts'])
    for rname in spec['order']:
        r = spec['rules'][rname]
        known = facts | set(r.get('params', [r['param']]))
        used = []
        _leaves(r['body'], used)
        if r['invariant'] is not None: _leaves(r['invariant'], used)
        for n in used:
            if n not in known:
                errs.append('SC-002: unknown name %s in rule %s' % (n, rname))
    for iv in spec['invariants']:
        used = []
        _leaves(iv, used)
        for n in used:
            if n not in facts:
                errs.append('SC-002: unknown name %s in invariant' % n)
    for wire in spec['wires']:
        if _bare(wire['dst']) not in spec['rules']:
            errs.append('SC-060: wire target %s is not a declared rule' % _bare(wire['dst']))
    return errs
