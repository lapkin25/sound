#!/usr/bin/env python3
# proto_stat.py — гистограмма опкодов и структурные инварианты протокола .sound.jsonl
# Запуск: python proto_stat.py isqrt.sound.jsonl
import sys, json, collections

path = sys.argv[1]
ops = collections.Counter()
max_depth = -1
call = ret = 0
with open(path, encoding="utf-8") as fh:
    for line in fh:
        r = json.loads(line)
        ops[r["op"]] += 1
        d = r.get("depth")
        if isinstance(d, int) and d > max_depth:
            max_depth = d
        if r["op"] == "CALL":
            call += 1
        if r["op"] == "RET":
            ret += 1

print("гистограмма опкодов:")
for op, c in sorted(ops.items()):
    print(f"  {op:8s} {c}")

calls = cnt.get("CALL", 0); rets = cnt.get("RET", 0)
spawns = cnt.get("SPAWN", 0); results = cnt.get("RESULT", 0)
awaits = cnt.get("AWAIT", 0)

if spawns or results:
    print(f"CALL + SPAWN = RET: {calls} + {spawns} = {rets}  "
          f"равенство: {calls + spawns == rets}")
    print(f"SPAWN = RESULT: {spawns} = {results}  "
          f"равенство: {spawns == results}")
    print(f"AWAIT = 2*SPAWN: {awaits} = {2 * spawns}  "
          f"равенство: {awaits == 2 * spawns}")
else:
    print(f"CALL = {calls}  RET = {rets}  равенство: {calls == rets}")
