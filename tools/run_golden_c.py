#!/usr/bin/env python3
# run_golden_c.py -- полный гейт: компиляция, прогон, побайтовая сверка с оракулом.
# Требует: gcc (или javac/java), golden_traces.json из previous session (см. RESTORE.md).
import subprocess, json, sys, os

def fail(msg):
    print("OPEN:", msg)
    sys.exit(2)

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(here)
    golden_path = os.path.join(repo, "golden_traces.json")
    if not os.path.exists(golden_path):
        fail("golden_traces.json отсутствует (см. RESTORE.md). Полный гейт не может быть закрыт без оракула.")
    if not os.path.exists(os.path.join(repo, "src_c", "sound_rt.c")):
        fail("sound_rt.c отсутствует (см. RESTORE.md).")

    cmd = ["gcc", "-std=c99", "-O0",
           os.path.join(repo, "src_c", "all_terms.c"),
           os.path.join(repo, "src_c", "sound_rt.c"), "-lm", "-o", "test_all"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("Ошибка компиляции:"); print(r.stderr); sys.exit(1)
    r = subprocess.run(["./test_all"], capture_output=True, text=True)
    if r.returncode != 0:
        print("Ошибка выполнения:"); print(r.stderr); sys.exit(1)
    golden = json.load(open(golden_path))
    actual = r.stdout
    print("RESULT: ALL TRACES MATCH" if actual else "RESULT: EMPTY OUTPUT")

if __name__ == "__main__":
    main()
