# executor.py - исполнитель графа Sound
# Живая партитура - через единый sound_engine (локальный синтезатор удалён).
# Журнал 3.8 не тронут: он верифицирован Octave-эталоном (9/9) и не несёт звука.
import math, struct
from sound_engine import make_event, SoundEngine, describe

def canon(x):
    if math.isnan(x):
        return 'nan'
    if math.isinf(x):
        return 'inf' if x > 0 else '-inf'
    return x.hex()                       # 0x1.<13 hex>p(+|-)e, знак нуля включён

def bits2double(hs):
    return struct.unpack('>d', bytes.fromhex(hs))[0]

def padname(nm, pad):
    return nm + ' ' * max(0, pad - len(nm))

def fdiv(a, b):
    if b == 0:                               # IEEE: без исключения
        if a == 0:
            return float('nan')
        return math.copysign(float('inf'), math.copysign(1.0, a) * math.copysign(1.0, b))
    return a / b

IEEE_OP = {'+': lambda a, b: a + b, '-': lambda a, b: a - b,
           '*': lambda a, b: a * b, '/': fdiv}
CMP_OP = {'>=': lambda a, b: a >= b, '<=': lambda a, b: a <= b,
          '>': lambda a, b: a > b, '<': lambda a, b: a < b,
          '==': lambda a, b: a == b, '!=': lambda a, b: a != b,
          '+': IEEE_OP['+'], '-': IEEE_OP['-'], '*': IEEE_OP['*'], '/': fdiv}

def eval_silent(tree, fenv):
    if isinstance(tree, str):
        return fenv[tree]
    if isinstance(tree, (int, float)):
        return float(tree)
    op = tree[0]
    a = eval_silent(tree[1], fenv)
    if op == 'neg':
        return -a
    return CMP_OP[op](a, eval_silent(tree[2], fenv))

def eval_j(tree, env, facts, journal, pad, counter):
    if isinstance(tree, str):
        return (env[tree] if tree in env else facts[tree]), counter, journal
    if isinstance(tree, (int, float)):
        return float(tree), counter, journal
    op = tree[0]
    lv, counter, journal = eval_j(tree[1], env, facts, journal, pad, counter)
    if op == 'neg':
        v = -lv
    else:
        rv, counter, journal = eval_j(tree[2], env, facts, journal, pad, counter)
        v = IEEE_OP[op](lv, rv)
    nm = 't%d' % counter
    journal.append('bind %s = Float64 %s' % (padname(nm, pad), canon(v)))
    return v, counter + 1, journal

def exec_rule(rname, r, facts, args):
    # 1) инвариант первым, молча; нарушение -> одна строка err (п. 3.8)
    env = {}
    for p in r['params']:
        a = args[p]
        env[p] = bits2double(a['hex_bits']) if isinstance(a, dict) else float(a)
    if r.get('inv') is not None:
        fenv = dict(facts); fenv.update(env)
        okv = eval_silent(r['inv'], fenv)
        if not (okv == 1.0):                 # NaN == 1 -> False -> DomainError
            return ['err DomainError %s: invariant' % rname], None
    # 2) бинды параметров, имена добиты до max(2, самый длинный параметр)
    pad = max([2] + [len(p) for p in r['params']])
    journal = ['bind %s = Float64 %s' % (padname(p, pad), canon(env[p]))
               for p in r['params']]
    # 3) тело: пост-порядок, t-бинд после каждого операционного узла
    val, _, journal = eval_j(r['tree'], env, facts, journal, pad, 0)
    # 4) строка результата
    journal.append('result  = Float64 %s' % canon(val))
    return journal, val

class Executor:
    """Исполняет граф: чистые узлы - деревьями с журналом 3.8,
    провода - проверкой унисона по каноническим строкам."""
    def __init__(self, graph, profile='live'):
        self.g, self.profile = graph, profile
        self.eng = SoundEngine()
        self.journals, self.values = {}, {}
        self.node_errors = 0

    def run(self, args_by_node):
        for nm, r in self.g['rules'].items():
            rt = r.get('runtime', 'python')
            if nm not in args_by_node:
                self.eng.add('config_error', node=nm)
                print(describe(self.eng.events[-1]))
                self.journals[nm] = ['err ConfigError %s: no args' % nm]
                self.node_errors += 1
                continue
            self.eng.add('node_start', node=nm, runtime=rt)
            print(describe(self.eng.events[-1], self.profile))
            journal, val = exec_rule(nm, r, self.g['facts'], args_by_node[nm])
            self.journals[nm] = journal
            self.values[nm] = val
            if val is None:
                self.eng.add('node_error', node=nm)
                print(describe(self.eng.events[-1]))
                self.node_errors += 1
            else:
                self.eng.add('node_finish', node=nm, runtime=rt)
                print(describe(self.eng.events[-1], self.profile))
        for w in self.g['wires']:                # провод = проверка унисона
            a, b = w['src'], w['tgt']
            if (a in self.values and b in self.values
                    and self.values[a] is not None and self.values[b] is not None
                    and canon(self.values[a]) != canon(self.values[b])):
                self.eng.add('edge_error')
                print(describe(self.eng.events[-1]))
                self.journals[b].append('err WireMismatch %s <-> %s (Float64)' % (a, b))
        if self.node_errors == 0:
            self.eng.add('success')
            print(describe(self.eng.events[-1]))
        return self

    def render_to(self, path):
        # WAV пишется только в конце прогона - живая партитура уже отзвучала
        return self.eng.render_to(path, self.profile)

if __name__ == '__main__':
    import json
    from sound_compiler import parse_spec
    S = json.load(open('fixtures_stage2.json'))
    specs = {'legacy': parse_spec(S['spec_source']),
             'v02': parse_spec(S['spec_source_v02'])}

    def value_ok(val, expect):
        if val is None:
            return expect is None
        if isinstance(expect, str):
            return canon(val) == expect
        if isinstance(expect, dict):
            return canon(val) == canon(bits2double(expect['hex_bits']))
        return canon(val) == canon(float(expect))

    npass = nfail = 0
    fails = []
    for v in S['journal_vectors']:
        r = specs[v['spec']]['rules'].get(v['rule'], S['rules'][v['rule']])
        journal, val = exec_rule(v['rule'], r, specs[v['spec']]['facts'], v['args'])
        ok = journal == v['expect_log'] and value_ok(val, v['expect_value'])
        if ok:
            npass += 1
            print('PASS %s' % v['name'])
        else:
            nfail += 1
            fails.append(v['name'])
            print('FAIL %s' % v['name'])
            for k in range(max(len(journal), len(v['expect_log']))):
                a = journal[k] if k < len(journal) else ''
                b = v['expect_log'][k] if k < len(v['expect_log']) else ''
                if a != b:
                    print('  line %d: got  %s' % (k + 1, a))
                    print('  line %d: want %s' % (k + 1, b))
    print()
    print('FAILURES: %d -> %s' % (nfail, ', '.join(fails)) if nfail else
          'ALL PASS (%d/%d)' % (npass, npass))
