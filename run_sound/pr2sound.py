#!/usr/bin/env python3
# pr2sound.py — транслятор .pr в звуковую программу (v0.1).
# Реализует spec_pr2sound_v0.1.md (принятые решения):
#   - унарное кодирование чисел на лентах;
#   - полное раскрытие атомов plus/mul (вариант A);
#   - pi разрешается при аллокации лент (0 команд, зеркально прямой метрике);
#   - prec — цикл с внутренней лентой-счётчиком j, счётчик — первый аргумент;
#   - CP реализован как макрос над S/D (источник сохраняется).
#
# Команды звуковой программы: Z, S, D, JZ, JMP, LAB, CALL, RET.
# Метрика: шаг = действие с лентой (Z/S/D) или единица переноса (CP,
# передача аргументов CALL и возврат результата). JZ/JMP/LAB/RET бесплатны.
#
# Использование:
#   python pr2sound.py program.pr                 # сводка трансляции
#   python pr2sound.py program.pr -o prog.sound.json

import json, sys
import run_pr

class CompileError(Exception): pass

class Compiler:
    def __init__(self, defs):
        self.defs = defs
        self.subs = {}
        self._building = set()
        self._tid = 0
        self._lid = 0

    def alloc(self):
        self._tid += 1
        return f"t{self._tid}"

    def label(self):
        self._lid += 1
        return f"L{self._lid}"

    # dst := src, src сохраняется. Раскрытие CP: 2 + 3n + 2n машинных шагов.
    def emit_copy(self, code, src, dst):
        if src == dst:
            return
        tmp = self.alloc()
        code.append(["Z", dst])
        code.append(["Z", tmp])
        l1, l2, l3 = self.label(), self.label(), self.label()
        code.append(["LAB", l1])
        code.append(["JZ", src, l2])
        code.append(["D", src]); code.append(["S", tmp]); code.append(["S", dst])
        code.append(["JMP", l1])
        code.append(["LAB", l2])
        code.append(["JZ", tmp, l3])
        code.append(["D", tmp]); code.append(["S", src])
        code.append(["JMP", l2])
        code.append(["LAB", l3])

    def call_name(self, nm, env, code):
        # Зеркалим run_pr.Runner: узел name разрешается в builtin, если есть,
        # иначе в def. Ключи builtin: prefixed, чтобы не сталкиваться с def.
        if nm in ("plus", "mul"):
            self._builtin_for(nm, len(env))  # гарантируем оттяжку атома
            r = self.alloc()
            code.append(["CALL", f"builtin:{nm}/{len(env)}", list(env), r])
            return r
        if nm not in self.defs:
            raise CompileError(f"неизвестное имя {nm!r}")
        self.sub_for(nm, len(env))          # гарантируем оттяжку определения
        r = self.alloc()
        code.append(["CALL", f"{nm}/{len(env)}", list(env), r])
        return r

    def compile_expr(self, t, env, code):
        k = t[0]
        if k == "z":
            r = self.alloc(); code.append(["Z", r]); return r
        if k == "s":
            if len(t) > 1:
                v = self.compile_expr(t[1], env, code)
            else:
                if not env:
                    raise CompileError("s: нужна 1 лента")
                v = env[0]
            r = self.alloc(); self.emit_copy(code, v, r)
            code.append(["S", r]); return r
        if k == "pi":
            _, kk, i = t
            if len(env) != kk:
                raise CompileError(f"pi({kk},{i}): контекст из {len(env)} лент")
            return env[i - 1]
        if k == "comp":
            _, f, gs = t
            tgs = [self.compile_expr(g, env, code) for g in gs]
            return self.apply_fn(f, tgs, code)
        if k == "prec":
            if len(env) < 1:
                raise CompileError("prec: нужен счётчик")
            return self.apply_prec(t[1], t[2], env, code)
        if k == "name":
            return self.call_name(t[1], env, code)
        raise CompileError(f"неизвестный узел {k!r}")

    def apply_fn(self, f, tgs, code):
        k = f[0]
        if k == "z":
            r = self.alloc(); code.append(["Z", r]); return r
        if k == "s":
            if len(f) > 1:
                base = self.compile_expr(f[1], tgs, code)
            else:
                if len(tgs) != 1:
                    raise CompileError(f"s: арность 1, получено {len(tgs)}")
                base = tgs[0]
            r = self.alloc(); self.emit_copy(code, base, r)
            code.append(["S", r]); return r
        if k == "pi":
            kk, i = f[1], f[2]
            if len(tgs) != kk:
                raise CompileError(f"pi({kk},{i}): контекст из {len(tgs)} лент")
            return tgs[i - 1]
        if k == "comp":
            tgs2 = [self.compile_expr(g, tgs, code) for g in f[2]]
            return self.apply_fn(f[1], tgs2, code)
        if k == "prec":
            return self.apply_prec(f[1], f[2], tgs, code)
        if k == "name":
            return self.call_name(f[1], tgs, code)
        raise CompileError(f"неизвестный узел {k!r}")

    def apply_prec(self, g, h, env, code):
        # v := g(0, rest); j := 0; rem := n;
        # пока rem != 0: v := h(j, v, rest); j := j+1; rem := rem-1
        z0 = self.alloc(); code.append(["Z", z0])
        v = self.compile_expr(g, [z0] + env[1:], code)
        va = self.alloc()
        self.emit_copy(code, v, va)          # v может быть алиасом входной ленты
        rem = self.alloc()
        self.emit_copy(code, env[0], rem)
        j = self.alloc(); code.append(["Z", j])
        l1, l2 = self.label(), self.label()
        code.append(["LAB", l1])
        code.append(["JZ", rem, l2])
        v2 = self.compile_expr(h, [j, va] + env[1:], code)
        self.emit_copy(code, v2, va)         # emit_copy сам пропустит случай v2 == va
        code.append(["S", j])
        code.append(["D", rem])
        code.append(["JMP", l1])
        code.append(["LAB", l2])
        return va

    # Атомы словаря v0.6, полное раскрытие (вариант A спецификации).
    def atom_plus(self):
        code = []
        r = "out"
        self.emit_copy(code, "in0", r)
        tb = self.alloc()
        self.emit_copy(code, "in1", tb)
        l1, l2 = self.label(), self.label()
        code.append(["LAB", l1]); code.append(["JZ", tb, l2])
        code.append(["D", tb]); code.append(["S", r]); code.append(["JMP", l1])
        code.append(["LAB", l2])
        return {"ins": 2, "out": r, "code": code}

    def atom_mul(self):
        code = []
        r = "out"; code.append(["Z", r])
        ta = self.alloc(); self.emit_copy(code, "in0", ta)
        tb = self.alloc(); self.emit_copy(code, "in1", tb)
        l1, l3, l2, l4 = self.label(), self.label(), self.label(), self.label()
        code.append(["LAB", l1]); code.append(["JZ", tb, l3])
        code.append(["D", tb])
        t = self.alloc(); self.emit_copy(code, ta, t)
        code.append(["LAB", l2]); code.append(["JZ", t, l4])
        code.append(["D", t]); code.append(["S", r]); code.append(["JMP", l2])
        code.append(["LAB", l4]); code.append(["JMP", l1])
        code.append(["LAB", l3])
        return {"ins": 2, "out": r, "code": code}

    def _builtin_for(self, name, arity):
        # Атомы словаря резолвятся раньше def — как в Runner: узлы name
        # всегда идут в builtin, а тело def исполняется только через entry.
        key = f"builtin:{name}/{arity}"
        if key in self.subs:
            return self.subs[key]
        s = self.atom_plus() if name == "plus" else self.atom_mul()
        s["name"] = key
        self.subs[key] = s
        return s

    def sub_for(self, name, arity):
        key = f"{name}/{arity}"
        if key in self.subs:
            return self.subs[key]
        if key in self._building:
            raise CompileError(f"рекурсивная ссылка на {key}")
        self._building.add(key)
        if name not in self.defs:
            raise CompileError(f"неизвестное имя {name!r}")
        env = [f"in{i}" for i in range(arity)]
        code = []
        out = self.compile_expr(self.defs[name], env, code)
        s = {"ins": arity, "out": out, "code": code}
        s["name"] = key
        self.subs[key] = s
        self._building.discard(key)
        return s

    def compile_entry(self, name, args_n):
        if name not in self.defs:
            raise CompileError(f"entry: имя {name!r} не определено")
        self.sub_for(name, args_n)
        target = f"{name}/{args_n}"
        code = [["CALL", target, [f"in{i}" for i in range(args_n)], "out"]]
        self.subs["__entry__"] = {"name": "__entry__", "ins": args_n, "out": "out", "code": code}
        return {"v": "0.1",
                "entry": {"name": "__entry__", "ins": args_n, "target": f"{name}/{args_n}"},
                "subs": self.subs}

def compile_program(defs, entry_name, entry_args_n):
    return Compiler(defs).compile_entry(entry_name, entry_args_n)

def program_stats(prog):
    tapes = len({t for s in prog["subs"].values()
                 for ins in s["code"] if ins[0] in ("Z", "S", "D", "JZ") for t in ([ins[1]] if ins[0] != "JZ" else [ins[1]])})
    cmds = sum(len(s["code"]) for s in prog["subs"].values())
    return len(prog["subs"]), cmds

class MachineError(Exception): pass

class Machine:
    def __init__(self, prog, max_steps=2_000_000, log_limit=1_000_000):
        self.subs = prog["subs"]
        self.entry = prog["entry"]
        self.max_steps = max_steps
        self.log_limit = log_limit
        self.idx = {}
        for key, s in self.subs.items():
            idx = {}
            for i, ins in enumerate(s["code"]):
                if ins[0] == "LAB":
                    idx[ins[1]] = i
            self.idx[key] = idx

    def run(self, args):
        entry = self.subs[self.entry["name"]]
        if len(args) != entry["ins"]:
            raise MachineError(f"entry: ожидалось {entry['ins']} аргументов, получено {len(args)}")
        steps = 0
        log = []
        frames = [{"sub": self.entry["name"],
                   "tapes": {f"in{i}": a for i, a in enumerate(args)},
                   "pc": 0, "out": None}]
        while frames:
            if steps > self.max_steps:
                raise MachineError("лимит шагов превышен (стена унарного кодирования?)")
            fr = frames[-1]
            sub = self.subs[fr["sub"]]
            if fr["pc"] >= len(sub["code"]):
                val = fr["tapes"].get(sub["out"], 0)
                frames.pop()
                if frames:
                    ci, outname = fr["out"]
                    cf = frames[ci]
                    if val:
                        steps += val
                        if len(log) < self.log_limit:
                            log.append({"n": steps, "op": "CP", "units": val,
                                        "sub": cf["sub"], "tapes": {outname: val}})
                    cf["tapes"][outname] = val
                else:
                    return val, steps, log
                continue
            ins = sub["code"][fr["pc"]]
            pc = fr["pc"]
            fr["pc"] += 1
            op = ins[0]
            if op == "LAB":
                continue
            if op == "JMP":
                fr["pc"] = self.idx[fr["sub"]][ins[1]]
                continue
            if op == "JZ":
                if fr["tapes"].get(ins[1], 0) == 0:
                    fr["pc"] = self.idx[fr["sub"]][ins[2]]
                continue
            if op == "Z":
                fr["tapes"][ins[1]] = 0
                steps += 1
                if len(log) < self.log_limit:
                    log.append({"n": steps, "op": "Z", "sub": fr["sub"], "pc": pc, "tapes": {ins[1]: 0}})
                continue
            if op == "S":
                v = fr["tapes"].get(ins[1], 0) + 1
                fr["tapes"][ins[1]] = v
                steps += 1
                if len(log) < self.log_limit:
                    log.append({"n": steps, "op": "S", "sub": fr["sub"], "pc": pc, "tapes": {ins[1]: v}})
                continue
            if op == "D":
                v = fr["tapes"].get(ins[1], 0)
                if v == 0:
                    raise MachineError("D: декремент нулевой ленты")
                fr["tapes"][ins[1]] = v - 1
                steps += 1
                if len(log) < self.log_limit:
                    log.append({"n": steps, "op": "D", "sub": fr["sub"], "pc": pc, "tapes": {ins[1]: v - 1}})
                continue
            if op == "CALL":
                _, subname, argtapes, out = ins
                callee = self.subs[subname]
                if len(argtapes) != callee["ins"]:
                    raise MachineError(f"CALL {subname}: арность {callee['ins']}, передано {len(argtapes)}")
                argvals = [fr["tapes"].get(t, 0) for t in argtapes]
                fr2 = {"sub": subname, "tapes": {}, "pc": 0, "out": (len(frames) - 1, out)}
                for i, val in enumerate(argvals):
                    if val:
                        steps += val
                        if len(log) < self.log_limit:
                            log.append({"n": steps, "op": "CP", "units": val, "sub": subname,
                                        "tapes": {f"in{i}": val}})
                        fr2["tapes"][f"in{i}"] = val
                frames.append(fr2)
                continue
            raise MachineError(f"неизвестная команда {op!r}")
        raise MachineError("звуковая программа завершилась без результата")

def main(argv):
    outfile = None
    files = []
    j = 0
    while j < len(argv):
        if argv[j] == "-o":
            if j + 1 >= len(argv):
                print("error: -o: укажите имя файла"); return 2
            outfile = argv[j + 1]; j += 1
        else:
            files.append(argv[j])
        j += 1
    if not files:
        print("usage: python pr2sound.py program.pr [-o prog.sound.json]"); return 2
    try:
        defs, entry = run_pr.parse_program(open(files[0], encoding="utf-8").read())
        name, eargs = run_pr.entry_override(entry, argv)
        if name not in defs:
            raise CompileError(f"entry: имя {name!r} не определено")
        prog = compile_program(defs, name, len(eargs))
    except (run_pr.PrError, CompileError) as e:
        print(f"error: {e}"); return 1
    nsubs, ncmds = program_stats(prog)
    nsubs_all = len(prog["subs"])
    print(f"translating: {name}({', '.join(map(str, eargs))}) -> {name}/{len(eargs)}")
    print(f"subs: {nsubs_all} (включая plus/2, mul/2, __entry__), commands: {ncmds}")
    if outfile:
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(prog, f, ensure_ascii=False, indent=1)
        print(f"program: {outfile}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
