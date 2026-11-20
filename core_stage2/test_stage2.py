# test_stage2.py - etalon check for stage 2 (journal + static)
import json as J
import sound_stage2 as S

fx = J.loads(open('fixtures_stage2.json').read())
spec = S.parse_spec(fx['spec_source'])
npass = 0

for v in fx['journal_vectors']:
    args = {k: (float.fromhex('nan') if isinstance(m, dict) else float(m))
            for k, m in v['args'].items()}
    val, log = S.run_rule(spec, v['rule'], args)
    ok = log == v['expect_log']
    ok = ok and (val is None if v['expect_value'] is None
                 else S.canon(val) == S.canon(v['expect_value']))
    print('PASS' if ok else 'FAIL', v['name'])
    npass += 1 if ok else 0

for v in fx['static_vectors']:
    ok = S.static_checks(S.parse_spec(v['spec'])) == v['expect']
    print('PASS' if ok else 'FAIL', v['name'])
    npass += 1 if ok else 0

print('ALL PASS (%d/11)' % npass if npass == 11 else 'FAILED (%d/11)' % npass)
