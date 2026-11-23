#!/usr/bin/env python3
# run_sound.py v0.3.1 — исполнитель звуковой машины
#
# Вход: .sound.json от pr2sound.py (проверяется поле fmt == "sound-v0.3").
# Флаги: --protocol FILE (записать .sound.jsonl), --limit N (лимит шагов).
# Вывод: value, steps (= записей протокола), sha256 источника.
#
# Машина: аккумулятор V, стек значений, стек фреймов.
# CALL: cid += 1, новый фрейм (ret, args, depth+1, cid).
# RET:  V = pop(), возврат в caller, push(V) в стек caller'а.
# Запись протокола — по одной на исполненную инструкцию.

import sys, json, argparse

class MachineError(Exception):
    pass

FMT = "sound-v0.3"

def execute(prog, limit):
    starts = {}
    code_all = list(prog["main"]["code"])
    for name, f in prog["fns"].items():
        starts[name] = len(code_all)
        code_all.extend(f["code"])
    code_all.append(["HALT", None])  # страховка от выхода за программу

    pc, V, depth, cid = 0, 0, 0, 0
    stack, frames, records = [], [], []
    locals_now = []

    def pop():
        if not stack:
            raise MachineError(f"стек пуст на pc={pc} (op={code_all[pc][0]})")
        return stack.pop()

    step = 0
    while True:
        if step >= limit:
            raise MachineError(f"лимит {limit} инструкций исчерпан на pc={pc}")
        if pc >= len(code_all):
            raise MachineError(f"pc={pc} за пределами программы")
        op, arg = code_all[pc]

        if op == "HALT":
            records.append({"pc": pc, "op": "HALT", "args": [],
                            "state": {"V": V}, "depth": depth, "cid": cid})
            break
        elif op == "PUSH":
            stack.append(arg)
        elif op == "LOAD":
            if arg >= len(locals_now):
                raise MachineError(f"LOAD {arg} вне слотов на pc={pc} (слотов {len(locals_now)})")
            stack.append(locals_now[arg])
        elif op == "STORE":
            v = pop()
            while len(locals_now) <= arg:
                locals_now.append(None)
            locals_now[arg] = v
        elif op == "ADD":
            b = pop(); a = pop(); V = a + b; stack.append(V)
        elif op == "SUB":
            b = pop(); a = pop(); V = a - b; stack.append(V)
        elif op == "MUL":
            b = pop(); a = pop(); V = a * b; stack.append(V)
        elif op == "JZ":
            v = pop()
            records.append({"pc": pc, "op": "JZ", "args": [v],
                            "state": {"V": V}, "depth": depth, "cid": cid})
            pc = arg if v == 0 else pc + 1
            step += 1
            continue
        elif op == "JMP":
            records.append({"pc": pc, "op": "JMP", "args": [],
                            "state": {"V": V}, "depth": depth, "cid": cid})
            pc = arg
            step += 1
            continue
        elif op == "CALL":
            name, n = arg
            args = stack[-n:] if n else []
            if n:
                del stack[-n:]
            cid += 1
            frames.append({"ret": pc + 1, "locals": list(args),
                           "depth": depth + 1, "cid": cid, "fn": name})
            depth += 1
            locals_now = frames[-1]["locals"]
            records.append({"pc": pc, "op": "CALL", "args": list(args),
                            "state": {"V": V}, "depth": depth, "cid": cid})
            pc = starts[name]
            step += 1
            continue
        elif op == "RET":
            v = pop()
            if not frames:
                raise MachineError("RET вне вызова")
            frame = frames.pop()
            V = v
            records.append({"pc": pc, "op": "RET", "args": [v],
                            "state": {"V": V}, "depth": frame["depth"], "cid": frame["cid"]})
            depth = frame["depth"] - 1
            locals_now = frames[-1]["locals"] if frames else []
            pc = frame["ret"]
            stack.append(V)
            step += 1
            continue
        else:
            raise MachineError(f"неизвестная инструкция {op!r} на pc={pc}")

        records.append({"pc": pc, "op": op, "args": [],
                        "state": {"V": V}, "depth": depth, "cid": cid})
        pc += 1
        step += 1
    return V, records

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--protocol", default=None)
    ap.add_argument("--limit", type=int, default=10_000_000)
    a = ap.parse_args()

    prog = json.load(open(a.file, encoding="utf-8"))
    if prog.get("fmt") != FMT:
        sys.stderr.write(
            f"СТАРЫЙ ИЛИ НЕЗНАКОМЫЙ ФОРМАТ {a.file} (fmt={prog.get('fmt')!r}).\n"
            f"Исполнитель ждёт fmt={FMT!r}. Файл создан другой версией pr2sound —\n"
            f"перегенерируйте: python pr2sound.py fact.pr fact.sound.json\n")
        sys.exit(2)

    try:
        value, records = execute(prog, a.limit)
    except MachineError as e:
        sys.stderr.write(f"МАШИНА ОСТАНОВЛЕНА: {e}\n")
        sys.exit(1)

    print(f"value={value}")
    print(f"steps={len(records)}")
    print(f"sha256={prog.get('src_sha256')}")
    if a.protocol:
        with open(a.protocol, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"protocol={a.protocol} ({len(records)} записей)")

if __name__ == "__main__":
    main()
