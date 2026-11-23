#!/usr/bin/env python3
# run_pr.py — исполнитель файлов .pr (v0.1 draft), прямая дорога.
# Схемы: z, s, pi(k,i), comp[f, ...], prec[g, h].
# Атомы словаря v0.6 (пока чисто-значимые): plus, mul.
#
# Метрика шагов — прямая: применение схемы или атома словаря = 1 шаг,
# pi — свободное переименование (0 шагов). Эта метрика НЕ совпадает с
# машинными шагами звука-слоя; сопоставление дорог — по значению и через
# pr2sound.py (звуковая дорога). Прямая дорога — независимая проверка.
#
# Использование:
#   python run_pr.py program.pr                 # исполнить entry
#   python run_pr.py program.pr --trace         # трасса вызовов
#   python run_pr.py program.pr --entry f(3)    # другой entry
#   python run_pr.py program.pr --check 120     # сверка ожидаемого значения

import sys, re

class PrError(Exception): pass

TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<com>\#[^\n]*)
  | (?P<num>\d+)
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op>[()\[\],=])
""", re.X)

def lex(src):
    out, pos = [], 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise PrError(f"лексер: нераспознанный фрагмент {src[pos:pos+12]!r}")
        pos = m.end()
        if m.lastgroup in ("ws", "com"):
            continue
        out.append(m.group().strip())
    return out

def parse_program(src):
    toks = lex(src)
    n = len(toks)
    i = 0
    defs, entry = {}, None

    def peek():
        return toks[i] if i < n else None

    def take():
        nonlocal i
        if i >= n:
            raise PrError("неожиданный конец входа")
        t = toks[i]; i += 1
        return t

    def expect(t):
        got = take()
        if got != t:
            raise PrError(f"ожидалось {t!r}, получено {got!r}")

    def expr():
        tok = peek()
        if tok is None:
            raise PrError("конец входа внутри выражения")
        if tok == "z":
            take(); return ("z",)
        if tok == "s":
            take()
            if peek() == "(":                    # s(expr) — сахар
                take(); e = expr(); expect(")")
                return ("s", e)
            return ("s",)
        if tok == "pi":
            take(); expect("(")
            try:
                k = int(take()); expect(","); idx = int(take())
            except ValueError:
                raise PrError("pi: индексы должны быть целыми")
            expect(")")
            if k < 1 or idx < 1 or idx > k:
                raise PrError(f"pi({k},{idx}): 1 <= i <= k нарушено")
            return ("pi", k, idx)
        if tok == "comp":
            take(); expect("[")
            f = expr(); gs = []
            while peek() == ",":
                take(); gs.append(expr())
            expect("]")
            return ("comp", f, tuple(gs))
        if tok == "prec":
            take(); expect("[")
            g = expr(); expect(","); h = expr(); expect("]")
            return ("prec", g, h)
        if tok == "(":
            take(); e = expr(); expect(")")
            return e
        if re.fullmatch(r"[A-Za-z_]\w*", tok):
            take(); return ("name", tok)
        raise PrError(f"неожиданный токен {tok!r} в выражении")

    while i < n:
        tok = take()
        if tok == "def":
            nm = take()
            if not re.fullmatch(r"[A-Za-z_]\w*", nm):
                raise PrError(f"def: некорректное имя {nm!r}")
            if nm in defs:
                raise PrError(f"def: повторное имя {nm!r}")
            expect("=")
            defs[nm] = expr()
        elif tok == "entry":
            nm = take()
            if not re.fullmatch(r"[A-Za-z_]\w*", nm):
                raise PrError(f"entry: некорректное имя {nm!r}")
            expect("(")
            args = []
            while True:
                try:
                    args.append(int(take()))
                except ValueError:
                    raise PrError("entry: аргументы — целые неотрицательные")
                if peek() == ",":
                    take()
                else:
                    break
            expect(")")
            entry = (nm, tuple(args))
        else:
            raise PrError(f"ожидалось def/entry, получено {tok!r}")

    return defs, entry

class Runner:
    def __init__(self, defs):
        self.defs = defs
        self.builtins = {
            "plus": (2, lambda a: a[0] + a[1]),
            "mul":  (2, lambda a: a[0] * a[1]),
        }
        self.steps = 0
        self.trace = []

    def check(self, need, args, who):
        if len(args) != need:
            raise PrError(f"{who}: арность {need}, получено {len(args)} {list(args)}")

    def call(self, t, args):
        k = t[0]
        if k == "z":
            self.steps += 1
            return 0
        if k == "s":
            if len(t) > 1:                          # s(expr) — сахар
                base = self.call(t[1], args)
                self.steps += 1
                return base + 1
            self.check(1, args, "s")
            self.steps += 1
            return args[0] + 1
        if k == "pi":
            self.check(t[1], args, f"pi({t[1]},{t[2]})")
            return args[t[2] - 1]
        if k == "comp":
            _, f, gs = t
            vals = [self.call(g, args) for g in gs]
            return self.call(f, tuple(vals))
        if k == "prec":
            if len(args) < 1:
                raise PrError("prec: нужен хотя бы счётчик n")
            n, rest = args[0], tuple(args[1:])
            if n < 0:
                raise PrError("prec: отрицательная глубина рекурсии")
            # конвенция (по каноническому тексту demo_pradd):
            # g применяется к (n, x) при n=0: add(0,y) = pi(2,2)(0, y) = y
            v = self.call(t[1], (0,) + rest)
            for j in range(n):
                v = self.call(t[2], (j, v) + rest)
            return v
        if k == "name":
            nm = t[1]
            if nm in self.builtins:
                ar, fn = self.builtins[nm]
                self.check(ar, args, nm)
                self.steps += 1
                r = fn(args)
                self.trace.append(f"  {nm}({', '.join(map(str, args))}) = {r}")
                return r
            if nm in self.defs:
                self.trace.append(f"  {nm}({', '.join(map(str, args))}) ...")
                r = self.call(self.defs[nm], args)
                self.steps += 1
                self.trace.append(f"    = {r}")
                return r
            raise PrError(f"неизвестное имя: {nm!r}")
        raise PrError(f"неизвестный узел {k!r}")

def entry_override(src_entry, argv):
    for j, a in enumerate(argv):
        if a == "--entry":
            if j + 1 >= len(argv):
                raise PrError("--entry: укажите f(аргументы)")
            m = re.fullmatch(r"([A-Za-z_]\w*)\((\s*\d+(?:\s*,\s*\d+)*)\s*\)", argv[j+1])
            if not m:
                raise PrError("--entry: формат f(3) или f(3,5)")
            return m.group(1), tuple(int(x) for x in m.group(2).split(","))
    return src_entry

def main(argv):
    flags = {"--trace": False, "--check": None}
    files = []
    j = 0
    while j < len(argv):
        a = argv[j]
        if a == "--trace":
            flags["--trace"] = True
        elif a == "--check":
            flags["--check"] = int(argv[j+1]); j += 1
        else:
            files.append(a)
        j += 1
    if not files:
        print("usage: python run_pr.py program.pr [--trace] [--entry f(3)] [--check N]")
        return 2
    defs, entry = parse_program(open(files[0], encoding="utf-8").read())
    name, eargs = entry_override(entry, argv)
    if name not in defs:
        raise PrError(f"entry: имя {name!r} не определено")

    run = Runner(defs)
    val = run.call(defs[name], eargs)

    print(f"defs: {len(defs)} ({', '.join(defs)})   builtins: plus, mul")
    print(f"entry: {name}({', '.join(map(str, eargs))})")
    if flags["--trace"]:
        print("--- trace ---")
        for line in run.trace:
            print(line)
        print("---")
    print(f"result: {val}")
    print(f"steps: {run.steps} (прямая метрика: применения схем и атомов)")
    if flags["--check"] is not None:
        ok = val == flags["--check"]
        print(f"check: OK" if ok else f"check: FAIL — ожидалось {flags['--check']}")
        return 0 if ok else 1
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except PrError as e:
        print(f"error: {e}")
        sys.exit(1)
