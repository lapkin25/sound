#!/usr/bin/env python3
# run_sound.py v0.4.0 — исполнитель звуковой машины с многозадачностью
#
# Надстройка над v0.3.1: старые программы исполняются в точности как
# раньше (регресс проверен сравнением протоколов инструкция в инструкцию).
# Новое (кодировка — из pr2sound.py v0.5.0, fmt не меняется):
#   SPAWN [fn, n] — снять n аргументов со стека родителя, создать задачу
#     (tid = свежий cid, почтовый ящик пуст), положить tid на стек
#     родителя. Родитель остаётся готовым.
#   AWAIT — peek-семантика: пока потомок не готов, tid на вершине стека
#     не снимается, задача паркуется (waiting), pc не сдвигается.
#     Готов — tid снимается, значение потомка кладётся на стек.
#     Запись протокола: успех args=[tid, 1], парковка args=[tid, 0].
#   RESULT — внутренняя точка доставки: терминальный RET потомка
#     (опустошивший его фреймы) переводит потомка на синтетический
#     RESULT; тот кладёт V в почтовый ящик потомка (у самого потомка!),
#     будит родителя и снимает потомка с планировщика. RESULT парен
#     SPAWN по cid.
#   Планировщик: на каждом шаге исполняется одна инструкция задачи с
#     минимальным tid среди готовых; готовых нет при живых ждущих —
#     явный ДЕДЛОК с перечнем tid.
# В запись протокола добавлено поле tid — какая задача исполняла;
# старый proto_stat.py это поле просто не заметит.
#
# Вход: .sound.json от pr2sound.py (проверяется поле fmt == "sound-v0.3").
# Флаги: --protocol FILE (записать .sound.jsonl), --limit N (лимит шагов).
# Вывод: value, steps (= записей протокола), sha256 источника.

import sys, json, argparse

FMT = "sound-v0.3"

class MachineError(Exception):
    pass

def execute(prog, limit):
    starts = {}
    code_all = list(prog["main"]["code"])
    for name, f in prog["fns"].items():
        starts[name] = len(code_all)
        code_all.extend(f["code"])
    code_all.append(["HALT", None])          # страховка от выхода за программу
    RESULT_PC = len(code_all)
    code_all.append(["RESULT", None])        # синтетическая точка доставки

    records = []
    tasks = {}
    ready = [0]                              # главная задача: tid = 0
    cid = 0
    value = None

    def spawn_task(fn, args, parent):
        nonlocal cid
        cid += 1
        t = {"tid": cid, "pc": starts[fn], "V": 0, "stack": [],
             "frames": [{"ret": None, "locals": list(args), "depth": 1,
                         "cid": cid, "fn": fn}],
             "locals_now": list(args), "depth": 1,
             "state": "ready", "mb": None, "parent": parent, "cid0": cid}
        tasks[cid] = t
        ready.append(cid)
        return t

    # главная задача: tid = 0, parent нет
    tasks[0] = {"tid": 0, "pc": 0, "V": 0, "stack": [], "frames": [],
                "locals_now": [], "depth": 0, "state": "ready",
                "mb": None, "parent": None, "cid0": 0}

    def rec(tid, pc, o, args, V, depth, rcid):
        records.append({"pc": pc, "op": o, "args": args,
                        "state": {"V": V}, "depth": depth,
                        "cid": rcid, "tid": tid})

    while True:
        if len(records) >= limit:
            raise MachineError(f"лимит {limit} инструкций исчерпан")
        if not ready:
            waiting = sorted(t["tid"] for t in tasks.values()
                             if t["state"] == "waiting")
            if waiting:
                raise MachineError("ДЕДЛОК: готовых задач нет; ждут задачи: "
                                   + ", ".join(map(str, waiting)))
            break
        tid = min(ready)
        ready.remove(tid)
        t = tasks[tid]
        pc, V, depth = t["pc"], t["V"], t["depth"]
        stack, frames, locals_now = t["stack"], t["frames"], t["locals_now"]
        if pc >= len(code_all):
            raise MachineError(f"pc={pc} за пределами программы (tid={tid})")
        op, arg = code_all[pc]
        # как в v0.3.1: в обычных записях cid — глобальный последний
        # созданный вызов, а не cid текущего фрейма
        cur_cid = cid

        if op == "HALT":
            rec(tid, pc, "HALT", [], V, depth, cur_cid)
            t["state"] = "finished"
            value = V
            break

        elif op == "RESULT":
            t["mb"] = V
            rec(tid, pc, "RESULT", [], V, 0, t["cid0"])
            t["state"] = "finished"
            parent = tasks.get(t["parent"])
            if parent is not None and parent["state"] == "waiting":
                parent["state"] = "ready"
                ready.append(parent["tid"])
            continue

        elif op == "PUSH":
            stack.append(arg)
            t["pc"] = pc + 1
            rec(tid, pc, "PUSH", [], V, depth, cur_cid)

        elif op == "LOAD":
            if arg >= len(locals_now):
                raise MachineError(f"LOAD {arg} вне слотов на pc={pc} "
                                   f"(слотов {len(locals_now)}, tid={tid})")
            stack.append(locals_now[arg])
            t["pc"] = pc + 1
            rec(tid, pc, "LOAD", [], V, depth, cur_cid)

        elif op == "STORE":
            if not stack:
                raise MachineError(f"стек пуст на pc={pc} (op=STORE, tid={tid})")
            v = stack.pop()
            while len(locals_now) <= arg:
                locals_now.append(None)
            locals_now[arg] = v
            t["pc"] = pc + 1
            rec(tid, pc, "STORE", [], V, depth, cur_cid)

        elif op == "ADD" or op == "SUB" or op == "MUL":
            if len(stack) < 2:
                raise MachineError(f"стек пуст на pc={pc} (op={op}, tid={tid})")
            b = stack.pop(); a = stack.pop()
            V = a + b if op == "ADD" else (a - b if op == "SUB" else a * b)
            stack.append(V)
            t["V"] = V; t["pc"] = pc + 1
            rec(tid, pc, op, [], V, depth, cur_cid)

        elif op == "JZ":
            if not stack:
                raise MachineError(f"стек пуст на pc={pc} (op=JZ, tid={tid})")
            v = stack.pop()
            rec(tid, pc, "JZ", [v], V, depth, cur_cid)
            t["pc"] = arg if v == 0 else pc + 1

        elif op == "JMP":
            rec(tid, pc, "JMP", [], V, depth, cur_cid)
            t["pc"] = arg

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
            rec(tid, pc, "CALL", list(args), V, depth, cid)
            t["pc"] = starts[name]
            t["V"] = V; t["stack"] = stack; t["frames"] = frames
            t["locals_now"] = locals_now; t["depth"] = depth

        elif op == "RET":
            if not stack:
                raise MachineError(f"RET: стек пуст (tid={tid}, pc={pc})")
            v = stack.pop()
            if not frames:
                raise MachineError(f"RET вне вызова (tid={tid}, pc={pc})")
            frame = frames.pop()
            V = v
            if frame["ret"] is None:
                # терминальный RET spawned-задачи (у точки входа нет адреса
                # возврата): задача уходит на доставку (RESULT)
                rec(tid, pc, "RET", [v], V, frame["depth"], frame["cid"])
                t["V"] = V; t["stack"] = stack; t["frames"] = frames
                t["depth"] = 0; t["pc"] = RESULT_PC
            else:
                depth = frame["depth"] - 1
                locals_now = frames[-1]["locals"] if frames else []
                stack.append(V)
                rec(tid, pc, "RET", [v], V, frame["depth"], frame["cid"])
                t["pc"] = frame["ret"]
                t["V"] = V; t["stack"] = stack; t["frames"] = frames
                t["locals_now"] = locals_now; t["depth"] = depth

        elif op == "SPAWN":
            fn, n = arg
            args = stack[-n:] if n else []
            if n:
                del stack[-n:]
            child = spawn_task(fn, args, tid)
            stack.append(child["tid"])
            rec(tid, pc, "SPAWN", list(args), V, depth, child["tid"])
            t["pc"] = pc + 1
            t["V"] = V; t["stack"] = stack; t["frames"] = frames; t["depth"] = depth

        elif op == "AWAIT":
            if not stack:
                raise MachineError(f"AWAIT: стек пуст (tid={tid}, pc={pc})")
            ctid = stack[-1]
            child = tasks.get(ctid)
            if child is None:
                raise MachineError(f"AWAIT: задачи {ctid} не существует")
            if child["state"] == "finished" and child["mb"] is not None:
                stack.pop()
                stack.append(child["mb"])
                rec(tid, pc, "AWAIT", [ctid, 1], V, depth, cur_cid)
                t["pc"] = pc + 1
            else:
                rec(tid, pc, "AWAIT", [ctid, 0], V, depth, cur_cid)
                t["state"] = "waiting"       # pc не сдвигается
            t["stack"] = stack; t["V"] = V; t["frames"] = frames; t["depth"] = depth

        else:
            raise MachineError(f"неизвестная инструкция {op!r} на pc={pc} (tid={tid})")

        # задача, не изменившая состояние (waiting/finished), остаётся готовой
        if t["state"] == "ready":
            ready.append(tid)

    return value, records


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
