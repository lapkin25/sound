#!/usr/bin/env python3
# run_sound.py — звуковая дорога (v0.1): компиляция pr2sound-ом, исполнение
# звуковой программы с протоколом JSONL и сверка с прямой дорогой.
#
# Три уровня сверки (по spec_pr2sound_v0.1.md, раздел 7):
#   1. значение звуковой дороги == значению прямой дороги (run_pr.Runner);
#   2. детерминизм: два независимых прогона дают идентичные протоколы;
#   3. --check N: сверка с ожидаемым значением.
#
# Использование:
#   python run_sound.py program.pr
#   python run_sound.py program.pr --entry f(3)
#   python run_sound.py program.pr --check 120
#   python run_sound.py program.pr --protocol p.jsonl
#   python run_sound.py program.pr --limit 2000000

import sys, json
import run_pr, pr2sound

def main(argv):
    flags = {"--check": None, "--protocol": None, "--limit": None}
    files, j = [], 0
    while j < len(argv):
        a = argv[j]
        if a in flags:
            if j + 1 >= len(argv):
                print(f"error: {a}: нужно значение"); return 2
            flags[a] = argv[j + 1]; j += 1
        else:
            files.append(a)
        j += 1
    if not files:
        print("usage: python run_sound.py program.pr [--entry f(3)] [--check N] [--protocol p.jsonl] [--limit N]")
        return 2
    try:
        src = open(files[0], encoding="utf-8").read()
        defs, entry = run_pr.parse_program(src)
        name, eargs = run_pr.entry_override(entry, argv)
        if name not in defs:
            raise run_pr.PrError(f"entry: имя {name!r} не определено")

        # Дорога 1: прямая.
        runner = run_pr.Runner(defs)
        dval = runner.call(defs[name], eargs)

        # Дорога 2: звуковая (два независимых прогона).
        prog = pr2sound.compile_program(defs, name, len(eargs))
        lim = int(flags["--limit"]) if flags["--limit"] else 2_000_000
        m1 = pr2sound.Machine(prog, max_steps=lim)
        v1, s1, log1 = m1.run(eargs)
        m2 = pr2sound.Machine(prog, max_steps=lim)
        v2, s2, log2 = m2.run(eargs)
    except (run_pr.PrError, pr2sound.CompileError, pr2sound.MachineError) as e:
        print(f"error: {e}")
        return 1

    nsubs = len(prog["subs"])
    print(f"defs: {len(defs)} ({', '.join(defs)})   builtins: plus, mul")
    print(f"entry: {name}({', '.join(map(str, eargs))})")
    print(f"direct: result {dval}, steps {runner.steps} (прямая метрика)")
    print(f"sound:  result {v1}, steps {s1} (машинная метрика, унарное кодирование)")
    print(f"program: subs {nsubs}, commands {sum(len(s['code']) for s in prog['subs'].values())}")
    det = (log1 == log2) and (v1 == v2) and (s1 == s2)
    agree = (v1 == dval)
    print(f"determinism: {'OK' if det else 'FAIL'}")
    print(f"roads agree: {'OK' if agree else f'FAIL — direct {dval} != sound {v1}'}")
    rc = 0 if (det and agree) else 1
    if flags["--check"] is not None:
        c = int(flags["--check"])
        okc = (v1 == c)
        print(f"check: {'OK' if okc else f'FAIL — ожидалось {c}'}")
        rc = 0 if (rc == 0 and okc) else 1
    if flags["--protocol"]:
        with open(flags["--protocol"], "w", encoding="utf-8") as f:
            for rec in log1:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"protocol: {flags['--protocol']} ({len(log1)} записей)")
    return rc

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
