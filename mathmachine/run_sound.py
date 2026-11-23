#!/usr/bin/env python3
# run_sound.py v0.3 — исполнитель звуковой машины + протокол шагов
# Формат программы: см. шапку pr2sound.py.
# Схема записи протокола (MM-1.4, черновик до живой сверки):
#   {"i": шаг, "op": имя, "args": [...], "state": {"V": ...},
#    "depth": глубина вызова, "cid": id инстанции, "pc": индекс инструкции}
#   depth и cid вычисляются ПОСЛЕ исполнения CALL: все записи одной инстанции,
#   включая её RET, несут одинаковые depth и cid. main — depth 0, cid 0.
import sys, json, argparse

def execute(prog, max_steps=10_000_000):
    fns = prog["fns"]
    frames = [{"ret_pc": None, "fn": None, "R": {}, "cid": 0}]
    stack = []
    V = 0
    cid = 0
    cur, cur_name = prog["main"], "main"
    pc = 0
    records = []
    while True:
        if pc >= len(cur):
            raise RuntimeError("кончился код без HALT")
        instr = cur[pc]
        op, args = instr["op"], instr.get("args", [])
        nxt = pc + 1
        if op == 'LOADI':
            V = args[0]
        elif op == 'LOADA':
            V = frames[-1]["R"]["a%d" % args[0]]
        elif op == 'LOADR':
            V = frames[-1]["R"][args[0]]
        elif op == 'STORER':
            frames[-1]["R"][args[0]] = V
        elif op == 'PUSH':
            stack.append(V)
        elif op == 'ADD':
            b = stack.pop(); a = stack.pop(); V = a + b
        elif op == 'SUB':
            b = stack.pop(); a = stack.pop(); V = a - b
        elif op == 'MUL':
            b = stack.pop(); a = stack.pop(); V = a * b
        elif op == 'EQ':
            b = stack.pop(); a = stack.pop(); V = 1 if a == b else 0
        elif op == 'JZ':
            if V == 0:
                nxt = args[0]        # метки уже разрешены компилятором в индексы
        elif op == 'JMP':
            nxt = args[0]
        elif op == 'CALL':
            fnname, nargs = args[0], int(args[1])
            vals = [stack.pop() for _ in range(nargs)][::-1]
            cid += 1
            frames.append({"ret_pc": pc + 1, "fn": cur_name,
                           "R": {"a%d" % j: v for j, v in enumerate(vals)},
                           "cid": cid})
            records.append({"i": len(records), "op": op, "args": args,
                            "state": {"V": V}, "depth": len(frames) - 1,
                            "cid": cid, "pc": pc})
            cur, cur_name, pc = fns[fnname]["code"], fnname, 0
            if len(records) > max_steps:
                raise RuntimeError("предел шагов исчерпан")
            continue
        elif op == 'RET':
            v = V
            records.append({"i": len(records), "op": op, "args": args,
                            "state": {"V": v}, "depth": len(frames) - 1,
                            "cid": frames[-1]["cid"], "pc": pc})
            fr = frames.pop()
            cur_name = fr["fn"]
            cur = fns[cur_name]["code"] if cur_name in fns else prog["main"]
            pc = fr["ret_pc"]
            V = v
            if len(records) > max_steps:
                raise RuntimeError("предел шагов исчерпан")
            continue
        elif op == 'HALT':
            records.append({"i": len(records), "op": op, "args": args,
                            "state": {"V": V}, "depth": len(frames) - 1,
                            "cid": frames[-1]["cid"], "pc": pc})
            return V, records
        else:
            raise RuntimeError("неизвестная инструкция: %r" % op)
        records.append({"i": len(records), "op": op, "args": args,
                        "state": {"V": V}, "depth": len(frames) - 1,
                        "cid": frames[-1]["cid"], "pc": pc})
        pc = nxt
        if len(records) > max_steps:
            raise RuntimeError("предел шагов исчерпан")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prog")
    ap.add_argument("--protocol", default=None)
    ap.add_argument("--limit", type=int, default=10_000_000)
    a = ap.parse_args()
    prog = json.load(open(a.prog, encoding='utf-8'))
    if prog.get("spec") != "mm-sound-v0.3":
        raise RuntimeError("не та спецификация: %r" % prog.get("spec"))
    value, records = execute(prog, a.limit)
    print("value=%d" % value)
    print("steps=%d" % len(records))
    print("sha256=%s" % prog["src_sha256"])
    if a.protocol:
        with open(a.protocol, 'w', encoding='utf-8') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("protocol=%s (%d records)" % (a.protocol, len(records)))

if __name__ == '__main__':
    main()
