
# while_core.py — машина while v0.7 draft (Class B: per-case сертификат)
# Машина не содержит собственного цикла: исполнение = проверенный реплей.
import re, sys

LIB = {
    'plus':  lambda a: a[0] + a[1],
    'mul':   lambda a: a[0] * a[1],
    'monus': lambda a: max(0, a[0] - a[1]),
    'eq':    lambda a: 1 if a[0] == a[1] else 0,
    'pred':  lambda a: max(0, a[0] - 1),
    'div10': lambda a: a[0] // 10,
    'mod10': lambda a: a[0] % 10,
    'rev':   lambda a: int(str(a[0])[::-1]),   # библиотечный, развертка в demo_prpalstep.pr
}

def tokenize(s):
    return re.findall(r"[A-Za-z_][A-Za-z_0-9]*|\d+|[\[\](),=]", s)

def parse_scheme(s):
    toks = tokenize(s); pos = [0]
    def peek(): return toks[pos[0]] if pos[0] < len(toks) else None
    def take():
        t = peek(); pos[0] += 1; return t
    def expect(t):
        got = take()
        assert got == t, "expected %r, got %r" % (t, got)
    def term():
        name = take()
        if name == 'comp':
            expect('['); head = term(); gs = []
            while peek() == ',':
                take(); gs.append(term())
            expect(']'); return ('comp', head, gs)
        if name == 'prec':
            expect('['); g = term(); expect(','); h = term(); expect(']')
            return ('prec', g, h)
        if name == 'z' and peek() != '(':
            return ('z',)
        if peek() != '(':
            return ('ref', name)   # голое имя внутри comp: атом, арность в точке вызова
        if peek() == '(':
            take(); args = []
            if peek() != ')':
                args.append(int(take()))
                while peek() == ',':
                    take(); args.append(int(take()))
            expect(')')
            if name == 'pi':
                return ('pi', args[0], args[1])
            return ('atom', name, len(args))
        raise ValueError("unexpected token %r" % name)
    t = term()
    assert pos[0] == len(toks), "trailing tokens: %r" % toks[pos[0]:]
    return t

def zero(): return {'z': 0, 's': 0, 'atom': 0, 'prec': 0}

def ev(sc, args, ctr):
    tag = sc[0]
    if tag == 'z':
        ctr['z'] += 1; return 0
    if tag == 's':
        ctr['s'] += 1; return ev(sc[1], args, ctr) + 1
    if tag == 'pi':
        assert len(args) == sc[1], "arity of pi: %d vs %d" % (len(args), sc[1])
        return args[sc[2] - 1]
    if tag == 'comp':
        vals = [ev(g, args, ctr) for g in sc[2]]
        head = sc[1]
        if head[0] == 'ref':                 # головной атом без скобок
            ctr['atom'] += 1
            return LIB[head[1]](vals)
        return ev(head, vals, ctr)
    if tag == 'prec':
        n = args[0]; rest = list(args[1:]); ctr['prec'] += 1
        cur = ev(sc[1], [0] + rest, ctr)            # v0.1.1: g(0, x)
        for i in range(n):
            cur = ev(sc[2], [i, cur] + rest, ctr)   # h(n, prev, x)
        return cur
    if tag == 'ref':
        ctr['atom'] += 1
        return LIB[sc[1]](list(args))
    if tag == 'atom':
        ctr['atom'] += 1
        assert len(args) == sc[2], "arity of %s" % sc[1]
        return LIB[sc[1]](list(args))
    raise ValueError("bad scheme %r" % (sc,))

def metric(c): return c['z'] + c['s'] + c['atom']

def parse_while(text):
    prog = {'step': None, 'stop': None, 'entry': None, 'until': None, 'cert': None}
    for raw in text.splitlines():
        line = raw.split('#')[0].strip()
        if not line: continue
        if line.startswith('step '):
            name, rhs = line[5:].split('=', 1)
            prog['step'] = (name.strip(), parse_scheme(rhs.strip()))
        elif line.startswith('stop '):
            name, rhs = line[5:].split('=', 1)
            prog['stop'] = (name.strip(), parse_scheme(rhs.strip()))
        elif line.startswith('entry '):
            m = re.match(r'entry\s+([A-Za-z_]\w*)\(([^)]*)\)', line)
            prog['entry'] = (m.group(1),
                             [int(x) for x in m.group(2).replace(' ', '').split(',') if x])
        elif line.startswith('until '):
            prog['until'] = line[6:].strip()
        elif line.startswith('cert '):
            prog['cert'] = [int(x) for x in line[5:].split()]
        else:
            raise ValueError("unknown line: %r" % line)
    return prog

def refusal_record(prog, why, name='?'):
    ename, args = prog['entry']
    return ("REFUSAL R-TERM-NOT-CERTIFIED\n"
            "program: %s\nentry: %s(%d)\nreason: %s\n"
            "paths: (1) supply per-case certificate (Class B),\n"
            "       (2) await Class A measure semantics (v0.7.1),\n"
            "       (3) accept refusal" % (name, ename, args[0], why))

def run_while_file(path):
    prog = parse_while(open(path).read())
    name = path
    sname, step = prog['step']
    pname, stop = prog['stop']
    ename, args = prog['entry']
    assert ename == sname and prog['until'] == pname
    x0 = args[0]

    if prog['cert'] is None:
        return ('REFUSAL',
                refusal_record(prog,
                    "while-loop termination not certified (Class B); "
                    "no per-case trace supplied", name))

    cert = prog['cert']
    issues = []
    if x0 != cert[0]:
        issues.append("R-ENTRY-MISMATCH: entry %d, certificate starts at %d" % (x0, cert[0]))
    k = len(cert) - 1
    journal = []; total = 0
    for i in range(k):
        c1 = zero(); got = ev(step, [cert[i]], c1)
        c2 = zero(); p   = ev(stop, [cert[i]], c2)
        if got != cert[i + 1]:
            issues.append("transition %d: f(%d) = %d, certified %d" % (i, cert[i], got, cert[i + 1]))
        if p != 0:
            issues.append("stop predicate true at certified intermediate %d" % cert[i])
        total += metric(c1) + metric(c2)
        journal.append((i, cert[i], got, metric(c1), p))
    c3 = zero(); pf = ev(stop, [cert[-1]], c3)
    if pf != 1:
        issues.append("final certified value %d does not satisfy stop predicate" % cert[-1])
    total += metric(c3)

    if issues:
        return ('REJECT', "REJECT R-CERT-BROKEN\nprogram: %s\n" % name +
                "\n".join(issues))

    lines = []
    for (i, x, got, m, p) in journal:
        lines.append("trans %d: f(%d) = %-6d metric %d   pal(%d) = 0" % (i, x, got, m, x))
    lines.append("final: pal(%d) = 1" % cert[-1])
    lines.append("ACCEPT out = %d, k = %d, verifier atoms = %d" % (cert[-1], k, total))
    return ('ACCEPT', "\n".join(lines))

def main():
    status, report = run_while_file(sys.argv[1])
    print(report)
    sys.exit(0 if status == 'ACCEPT' else 2)

if __name__ == '__main__':
    main()
