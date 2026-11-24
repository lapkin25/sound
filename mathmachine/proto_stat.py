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
print("CALL =", call, " RET =", ret, " равенство:", call == ret)
print("SPAWN =", ops.get("SPAWN", 0), " RESULT =", ops.get("RESULT", 0))
print("AWAIT =", ops.get("AWAIT", 0), " HALT =", ops.get("HALT", 0))
print("max depth =", max_depth)
