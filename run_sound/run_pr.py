#!/usr/bin/env python3
# run_pr.py — исполнитель файлов .pr (v0.3), прямая дорога.
# Схемы: z, s, pi(k,i), comp[f, ...], prec[g, h].
# Атомы словаря v0.6 (пока чисто-значимые): plus, mul.
#
# Изменения v0.3 (закрытие открытого вопроса №6, асимметрия builtin/def):
#   * def ЗАПРЕЩЕНО объявлять имена, занятые атомами словаря (plus, mul)
#     и схемами (z, s, pi, comp, prec). Раньше `def mul = ...` компилировался,
#     но внутренние узлы `name mul` резолвились в атом словаря — тело def
#     исполнялось только как entry ("одно имя — две программы").
#   * вычислитель переписан на явный стек кадров (вопрос №4): глубина стека
#     Python не зависит от вложенности программ.
#   * z — семейство Z_n: возвращает 0 на любой арности (вопрос №3, решение
#     по канону примитивно-рекурсивных функций; строгая арность ломает
#     базу prec для mul).
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

# имена, которые нельзя объявлять через def: атомы словаря + схемы + ключевые слова
RESERVED = {"z", "s", "pi", "comp", "prec", "plus", "mul", "def", "entry"}

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
            if nm in RESERVED:
                raise PrError(f"def: имя {nm!r} зарезервировано "
                              f"(атом словаря или схема); переопределение запрещено (v0.3)")
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

class Frame:
    __slots__ = ("node", "args", "stage", "waiting", "vals", "f_pushed",
                 "n", "rest", "v", "j", "phase")
    def __init__(self, node, args):
        self.node = node
        self.args = args
        self.stage = 0        # comp: индекс следующего потомка; name: 0=до тела, 1=после
        self.waiting = False  # родитель ждёт значение завершившегося потомка
        self.vals = []
        self.f_pushed = False # comp: кадр f уже отправлен
        self.n = None         # prec: счётчик
        self.rest = None      # prec: остальные аргументы
        self.v = None         # prec: текущее значение
        self.j = 0            # prec: индекс итерации
        self.phase = 0        # prec: 1 = вернулся g, 2 = вернулся h

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

    def call(self, root, args):
        """Итеративный вычислитель: явный стек кадров, ни одного рекурсивного
        вызова Python. Семантика и порядок шагов/трассы идентичны v0.1."""
        stack = [Frame(root, args)]
        ret = 0
        while stack:
            fr = stack[-1]
            t = fr.node
            k = t[0]
            if k == "z":
                self.steps += 1
                stack.pop()
                ret = 0
            elif k == "s":
                if len(t) > 1:                      # s(expr) — сахар
                    if fr.waiting:
                        self.steps += 1
                        stack.pop()
                        ret = ret + 1
                    else:
                        stack.append(Frame(t[1], fr.args))
                        fr.waiting = True
                else:
                    self.check(1, fr.args, "s")
                    self.steps += 1
                    stack.pop()
                    ret = fr.args[0] + 1
            elif k == "pi":
                self.check(t[1], fr.args, f"pi({t[1]},{t[2]})")
                stack.pop()
                ret = fr.args[t[2] - 1]
            elif k == "comp":
                _, f, gs = t
                if fr.f_pushed:
                    stack.pop()                     # ret уже содержит значение f
                else:
                    if fr.waiting:
                        fr.vals.append(ret)
                        fr.waiting = False
                    if fr.stage < len(gs):
                        stack.append(Frame(gs[fr.stage], fr.args))
                        fr.stage += 1
                        fr.waiting = True
                    else:
                        stack.append(Frame(f, tuple(fr.vals)))
                        fr.f_pushed = True
                        fr.waiting = True
            elif k == "prec":
                if len(fr.args) < 1:
                    raise PrError("prec: нужен хотя бы счётчик n")
                if fr.n is None:
                    fr.n = fr.args[0]
                    fr.rest = tuple(fr.args[1:])
                    if fr.n < 0:
                        raise PrError("prec: отрицательная глубина рекурсии")
                    # конвенция (по каноническому тексту demo_pradd):
                    # g применяется к (n, x) при n=0: add(0,y) = pi(2,2)(0, y) = y
                    stack.append(Frame(t[1], (0,) + fr.rest))
                    fr.waiting = True
                    fr.phase = 1
                elif fr.waiting:
                    fr.waiting = False
                    if fr.phase == 1:
                        fr.v = ret
                        fr.j = 0
                        fr.phase = 2
                    else:
                        fr.v = ret
                        fr.j += 1
                    if fr.j < fr.n:
                        stack.append(Frame(t[2], (fr.j, fr.v) + fr.rest))
                        fr.waiting = True
                    else:
                        stack.pop()
                        ret = fr.v
            elif k == "name":
                nm = t[1]
                if nm in self.builtins:
                    ar, fn = self.builtins[nm]
                    self.check(ar, fr.args, nm)
                    self.steps += 1
                    r = fn(fr.args)
                    self.trace.append(f"  {nm}({', '.join(map(str, fr.args))}) = {r}")
                    stack.pop()
                    ret = r
                elif nm in self.defs:
                    if fr.stage == 0:
                        self.trace.append(f"  {nm}({', '.join(map(str, fr.args))}) ...")
                        fr.stage = 1
                        stack.append(Frame(self.defs[nm], fr.args))
                    else:
                        self.steps += 1
                        self.trace.append(f"    = {ret}")
                        stack.pop()
                else:
                    raise PrError(f"неизвестное имя: {nm!r}")
            else:
                raise PrError(f"неизвестный узел {k!r}")
        return ret

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
