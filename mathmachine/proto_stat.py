#!/usr/bin/env python3
# proto_stat.py v0.4 — статистика протокола звуковой машины
# Понимает протоколы и однозадачные (v0.3.1), и многозадачные (v0.4.0, поле tid).

import sys, json
from collections import Counter

if len(sys.argv) < 2:
    sys.stderr.write("использование: python proto_stat.py FILE.jsonl\n")
    sys.exit(2)

cnt = Counter()
max_depth = 0
spawn_cids, result_cids = set(), set()
tids = set()

with open(sys.argv[1], encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        cnt[r["op"]] += 1
        max_depth = max(max_depth, r.get("depth", 0))
        if r["op"] == "SPAWN":
            spawn_cids.add(r["cid"])
        elif r["op"] == "RESULT":
            result_cids.add(r["cid"])
        if "tid" in r:
            tids.add(r["tid"])

print("гистограмма опкодов:")
for op in sorted(cnt):
    print(f"  {op:<8} {cnt[op]}")

calls, rets = cnt.get("CALL", 0), cnt.get("RET", 0)
spawns, results = cnt.get("SPAWN", 0), cnt.get("RESULT", 0)
awaits = cnt.get("AWAIT", 0)

print()
if spawns or results:
    print(f"CALL + SPAWN = RET: {calls} + {spawns} = {rets}  "
          f"равенство: {calls + spawns == rets}")
    print(f"SPAWN = RESULT: {spawns} = {results}  "
          f"равенство: {spawns == results}")
    print(f"SPAWN/RESULT парны по cid: {spawn_cids == result_cids}")
    print(f"AWAIT = 2*SPAWN: {awaits} = {2 * spawns}  "
          f"равенство: {awaits == 2 * spawns}")
else:
    print(f"CALL = {calls}  RET = {rets}  равенство: {calls == rets}")
print(f"AWAIT = {awaits}  HALT = {cnt.get('HALT', 0)}")
print(f"max depth = {max_depth}")
if tids:
    print(f"уникальных tid = {len(tids)}")
