# test_stage2.py - etalon check for stage 2 (journal + static + grammar merge)
import json as J
import sound_stage2 as S

fx = J.loads(open('fixtures_stage2.json').read())
specs = {'legacy': S.parse_spec(fx['spec_source']),
         'v02':    S.parse_spec(fx['spec_source_v02'])}
npass = 0

for v in fx['journal_vectors']:
    spec = specs[v.get('spec', 'legacy')]
    args = {k: (S.struct.unpack('>d', bytes.fromhex(m['hex_bits']))[0]
                if isinstance(m, dict) else float(m))
            for k, m in v['args'].items()}
    val, log = S.run_rule(spec, v['rule'], args)
    ok = log == v['expect_log']
    ev = v['expect_value']
    ok = ok and (val is None if ev is None else (
        S.canon(val) == ev if isinstance(ev, str) else S.canon(val) == S.canon(ev)))
    print('PASS' if ok else 'FAIL', v['name'])
    if not ok:
        for a, b in zip(log, v['expect_log']):
            if a != b: print('   got  ', a, '\n   want ', b)
    npass += 1 if ok else 0

for v in fx['static_vectors']:
    ok = S.static_checks(S.parse_spec(v['spec'])) == v['expect']
    print('PASS' if ok else 'FAIL', v['name'])
    npass += 1 if ok else 0

# grammar merge: legacy vs v02 must yield identical trees and identical logs
legacy, v02 = specs['legacy'], specs['v02']
for rule in fx['merge_rules']:
    ok = legacy['rules'][rule]['body'] == v02['rules'][rule]['body']
    if legacy['rules'][rule]['invariant'] is not None:
        ok = ok and legacy['rules'][rule]['invariant'] == v02['rules'][rule]['invariant']
    print('PASS' if ok else 'FAIL', 'MERGE tree ' + rule)
    npass += 1 if ok else 0

for v in fx['journal_vectors']:
    if v['spec'] != 'legacy': continue
    args = {k: (S.struct.unpack('>d', bytes.fromhex(m['hex_bits']))[0]
                if isinstance(m, dict) else float(m))
            for k, m in v['args'].items()}
    val, log = S.run_rule(v02, v['rule'], args)
    ok = log == v['expect_log']
    print('PASS' if ok else 'FAIL', 'MERGE journal ' + v['name'])
    npass += 1 if ok else 0

total = len(fx['journal_vectors']) + len(fx['static_vectors']) + \
        len(fx['merge_rules']) + sum(1 for v in fx['journal_vectors'] if v['spec'] == 'legacy')
print('ALL PASS (%d/%d)' % (npass, total) if npass == total else 'FAILED (%d/%d)' % (npass, total))
