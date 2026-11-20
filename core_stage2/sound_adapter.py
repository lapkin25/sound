# sound_adapter.py - adapter: compiler graph -> executable plan (stage "link")

import math, struct
from dataclasses import dataclass

def canon(x):
    return float(x).hex()

def bits2double(hs):
    return struct.unpack('>d', bytes.fromhex(hs))[0]

def padname(nm, pad):
    return nm.ljust(pad)

def _ieee_div(a, b):
    if b == 0:
        if a != a or a == 0:
            return float('nan')
        return math.inf if (a > 0) == (math.copysign(1.0, b) > 0) else -math.inf
    return a / b

_BIN = {'+': lambda a, b: a + b,
        '-': lambda a, b: a - b,
        '*': lambda a, b: a * b,
        '/': _ieee_div}
_CMP = {'>=': lambda a, b: a >= b,
        '<=': lambda a, b: a <= b,
        '>':  lambda a, b: a > b,
        '<':  lambda a, b: a < b,
        '==': lambda a, b: a == b,
        '!=': lambda a, b: a != b}

def eval_j(tree, env, facts, journal, pad, counter):
    if isinstance(tree, str):
        if tree in env:
            return env[tree], counter
        if tree in facts:
            return facts[tree], counter
        raise NameError('unknown name %s' % tree)
    if isinstance(tree, (int, float)) and not isinstance(tree, bool):
        return float(tree), counter
    op = tree[0]
    lv, counter = eval_j(tree[1], env, facts, journal, pad, counter)
    if op == 'neg':
        v = -lv
    else:
        rv, counter = eval_j(tree[2], env, facts, journal, pad, counter)
        v = _BIN[op](lv, rv)
    journal.append('bind %s = Float64 %s' % (padname('t%d' % counter, pad), canon(v)))
    return v, counter + 1

def eval_silent(tree, fenv):
    if isinstance(tree, str):
        return fenv[tree]
    if isinstance(tree, (int, float)) and not isinstance(tree, bool):
        return float(tree)
    op = tree[0]
    a = eval_silent(tree[1], fenv)
    if op == 'neg':
        return -a
    b = eval_silent(tree[2], fenv)
    if op in _BIN:
        return _BIN[op](a, b)
    return _CMP[op](a, b)

@dataclass
class Node:
    name: str
    kind: str          # 'pure' | 'opaque'
    params: list
    tree: object = None
    inv: object = None
    ret: str = 'Float64'
    runtime: str = 'python'
    protocol: str = None

@dataclass
class Plan:
    facts: dict
    nodes: list
    wires: list        # (src, dst, type) - unification pairs

def build_plan(spec):
    facts = {k: float(v) for k, v in spec.get('facts', {}).items()}
    nodes = []
    for name, r in spec.get('rules', {}).items():
        params = r.get('params') or [r.get('param')]
        nodes.append(Node(name, r.get('kind', 'pure'), list(params),
                          tree=r.get('tree'), inv=r.get('inv'),
                          ret=r.get('ret', 'Float64'),
                          runtime=r.get('runtime', 'python'),
                          protocol=r.get('protocol')))
    wires = []
    for w in spec.get('wires', []):
        if isinstance(w, dict):
            wires.append((w['src'], w['dst'], w.get('type', 'Float64')))
        else:
            wires.append((w[0], w[1], w[2] if len(w) > 2 else 'Float64'))
    known = {n.name for n in nodes}
    for s, d, t in wires:
        if s not in known or d not in known:
            raise NameError('wire target is not a declared rule: %s/%s' % (s, d))
    return Plan(facts, nodes, wires)

RUNTIME_FREQ = {'python': 440.0, 'java': 523.25, 'octave': 659.25}

class Sound:
    def __init__(self, enabled=True):
        self.enabled = enabled
    def emit(self, kind, node=None, runtime=None):
        if not self.enabled:
            return
        if kind == 'start':
            print('[SOUND] start %s %s @ %.2f Hz' % (runtime, node, RUNTIME_FREQ[runtime]))
        elif kind == 'finish':
            print('[SOUND] finish %s @ %.2f Hz' % (node, RUNTIME_FREQ[runtime] * 1.2))
        elif kind == 'error_node':
            print('[SOUND] error %s @ 110.0 Hz' % node)
        elif kind == 'error_edge':
            print('[SOUND] error edge @ 150.0 Hz')
        elif kind == 'success':
            print('[SOUND] success @ 880.0 Hz')

class Executor:
    def __init__(self, plan, sound=None):
        self.plan = plan
        self.sound = sound or Sound(enabled=False)
        self.results = {}
        self.journals = {}

    def run_rule(self, name, args):
        node = self._node(name)
        if node.kind == 'opaque':
            self.sound.emit('error_node', node=name)
            raise NotImplementedError(
                'opaque node %s: protocol %r not linked yet' % (name, node.protocol))
        self.sound.emit('start', node=node.name, runtime=node.runtime)
        journal, val = run_pure_node(node, args, self.plan.facts)
        if journal and journal[0].startswith('err '):
            self.sound.emit('error_node', node=node.name)
        else:
            self.sound.emit('finish', node=node.name, runtime=node.runtime)
        self.journals[name] = journal
        self.results[name] = val
        return journal, val

    def run(self, args_by_rule):
        for node in self.plan.nodes:
            if node.name in args_by_rule:
                self.run_rule(node.name, args_by_rule[node.name])
        for s, d, t in self.plan.wires:
            vs, vd = self.results.get(s), self.results.get(d)
            if s in self.results and d in self.results:
                if vs is None or vd is None or canon(vs) != canon(vd):
                    self.journals[d].append('err WireMismatch %s <-> %s (%s)' % (d, s, t))
                    self.sound.emit('error_edge')
                else:
                    print('[WIRE] %s <-> %s: unison ok' % (d, s))
        self.sound.emit('success')
        return self.journals, self.results

    def _node(self, name):
        for n in self.plan.nodes:
            if n.name == name:
                return n
        raise KeyError('unknown node %s' % name)

def run_pure_node(node, args, facts):
    env = {}
    for p in node.params:
        a = args[p]
        env[p] = bits2double(a['hex_bits']) if isinstance(a, dict) else float(a)
    if node.inv is not None:
        fenv = dict(facts)
        fenv.update(env)
        okv = eval_silent(node.inv, fenv)
        if not (okv == 1):
            return ['err DomainError %s: invariant' % node.name], None
    pad = max([2] + [len(p) for p in node.params])
    journal = []
    for p in node.params:
        journal.append('bind %s = Float64 %s' % (padname(p, pad), canon(env[p])))
    val, _ = eval_j(node.tree, env, facts, journal, pad, 0)
    journal.append('result  = Float64 %s' % canon(val))
    return journal, val

def value_ok(val, expect):
    if isinstance(expect, str):
        return canon(val) == expect
    if isinstance(expect, dict):
        return canon(val) == canon(bits2double(expect['hex_bits']))
    if expect is None:
        return val is None
    return canon(val) == canon(float(expect))
