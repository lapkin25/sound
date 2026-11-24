#!/usr/bin/env python3
# pr2sound.py v0.4.0 — компилятор PR → звуковая машина
#
# Вход: .pr-программа (формат как в run_pr.py).
# Выход: .sound.json — программа звуковой машины:
#   {"fmt": "sound-v0.3", "src_sha256": ..., "entry": имя,
#    "fns": {имя: {"params": [...], "slots": [...], "code": [...]}},
#    "main": {"code": [...]}}
# Исполнитель (run_sound.py) проверяет поле fmt — файлы другого формата
# отвергаются с явным сообщением (защита от огрызков прошлых версий).
#
# Инструкции (кодировка: [op, arg]; arg=None, где не нужен):
#   PUSH n            — положить константу
#   LOAD i / STORE i  — слот текущего фрейма
#   ADD / SUB / MUL   — b=pop(); a=pop(); V=a op b; push(V)
#   CALL [fn, nargs]  — снять nargs аргументов, новый фрейм
#   RET               — вернуть V со стека
#   JZ метка / JMP метка — условный/безусловный переход по индексу
#   HALT
# Протокол записи: {"pc", "op", "args", "state": {"V": ...}, "depth", "cid"}
# CALL/RET парны по cid (монотонный номер вызова); depth — вложенность.
#
# v0.3.2: семантический барьер до кодогенерации (свободные имена, entry).
# v0.4.0: лямбда-лифтинг. Свободные имена тела prec-шага поднимаются в
#   дополнительные аргументы вызова: на prec-месте перед CALL добавляются
#   LOAD, шаг компилируется с расширенным списком параметров. Машина
#   (run_sound) не меняется. Барьер переформулирован: свободное имя шага
#   разрешено, если оно видно на месте вызова — в параметрах вызывающего
#   или в его собственных поднятых именах. Лифтинг одноуровневый:
#   цепочки шагов с транзитивными свободными именами — открытый вопрос MM-3.

import sys, hashlib, re

# ---------- нормализация и хеш (та же конвенция, что в run_pr.py) ----------

def normalize(text):
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())

def sha256_of(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()

# ---------- разбор (копия run_pr.py — файлы самодостаточны) ----------

DEF_RE = re.compile(r"^def\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*=\s*(.+)$")
ENTRY_RE = re.compile(r"^entry\s+([A-Za-z_]\w*)\s*\(([^()]*)\)\s*$")

def tokenize(s):
    toks = []
    i = 0
    while i < len(s):
        c = s[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < len(s) and s[j].isdigit():
                j += 1
            toks.append(("num", int(s[i:j]))); i = j
        elif c.isalpha() or c == "_":
            j = i
            while j < len(s) and (s[j].isalnum() or s[j] == "_"):
                j += 1
            toks.append(("name", s[i:j])); i = j
        elif c in "+-*(),":
            toks.append(("op", c)); i += 1
        else:
            raise SyntaxError(f"неожиданный символ {c!r} в {s!r}")
    toks.append(("end", None))
    return toks

class Parser:
    def __init__(self, toks):
        self.toks = toks; self.i = 0
    def peek(self):
        return self.toks[self.i]
    def next(self):
        t = self.toks[self.i]; self.i += 1; return t
    def expect(self, kind, val):
        t = self.next()
        if t != (kind, val):
            raise SyntaxError(f"ожидалось {val!r}, найдено {t!r}")
    def expr(self):
        node = self.term()
        while self.peek() == ("op", "+") or self.peek() == ("op", "-"):
            op = self.next()[1]
            node = ("bin", op, node, self.term())
        return node
    def term(self):
        node = self.atom()
        while self.peek() == ("op", "*"):
            self.next()
            node = ("bin", "*", node, self.atom())
        return node
    def atom(self):
        t = self.next()
        if t == ("op", "("):
            e = self.expr()
            self.expect("op", ")")
            return e
        if t[0] == "num":
            return ("num", t[1])
        if t[0] == "name":
            if self.peek() == ("op", "("):
                self.next()
                args = [self.expr()]
                while self.peek() == ("op", ","):
                    self.next()
                    args.append(self.expr())
                self.expect("op", ")")
                if t[1] == "prec":
                    if len(args) != 3:
                        raise SyntaxError("prec принимает 3 аргумента: prec(c, g, h)")
                    if args[2][0] != "var":
                        raise SyntaxError("шаг prec задаётся именем функции")
                    return ("prec", args[0], args[1], args[2])
                if t[1] == "ifz":
                    if len(args) != 3:
                        raise SyntaxError("ifz принимает 3 аргумента: ifz(c, тогда, иначе)")
                    return ("ifz", args[0], args[1], args[2])
                return ("call", t[1], args)
            return ("var", t[1])
        raise SyntaxError(f"неожиданный токен {t!r}")

def parse_expr(s):
    p = Parser(tokenize(s))
    node = p.expr()
    if p.peek() != ("end", None):
        raise SyntaxError(f"хвост выражения не разобран: {p.peek()!r}")
    return node

def parse_program(text):
    fns = {}
    entry = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        m = DEF_RE.match(line)
        if m:
            fns[m.group(1)] = {
                "params": [p.strip() for p in m.group(2).split(",") if p.strip()],
                "body": parse_expr(m.group(3)),
            }
            continue
        m = ENTRY_RE.match(line)
        if m:
            toks = tokenize(m.group(2))
            args = []
            if toks[0] != ("end", None):
                p = Parser(toks)
                args.append(p.expr())
                while p.peek() == ("op", ","):
                    p.next()
                    args.append(p.expr())
            entry = {"name": m.group(1), "args": args}
            continue
        raise SyntaxError(f"строка не разобрана: {line!r}")
    if entry is None:
        raise SyntaxError("нет строки entry")
    return fns, entry

# ---------- анализ свободных имён и prec-шагов (v0.3.2 / v0.4.0) ----------

def collect_vars(node, out=None):
    """Переменные узла AST. Ссылка на функцию-шаг prec не считается."""
    if out is None:
        out = set()
    k = node[0]
    if k == "var":
        out.add(node[1])
    elif k == "bin":
        collect_vars(node[2], out); collect_vars(node[3], out)
    elif k == "call":
        for a in node[2]:
            collect_vars(a, out)
    elif k == "prec":
        collect_vars(node[1], out)
        collect_vars(node[2], out)
        # node[3] — ("var", имя функции-шага): имя функции, не переменная
    elif k == "ifz":
        collect_vars(node[1], out); collect_vars(node[2], out); collect_vars(node[3], out)
    return out

def prec_steps(node, out):
    """Имена prec-шагов, встречающихся в узле, в порядке обхода."""
    k = node[0]
    if k == "prec":
        out.append(node[3][1])
        prec_steps(node[1], out); prec_steps(node[2], out)
    elif k == "bin":
        prec_steps(node[2], out); prec_steps(node[3], out)
    elif k == "ifz":
        prec_steps(node[1], out); prec_steps(node[2], out); prec_steps(node[3], out)
    elif k == "call":
        for a in node[2]:
            prec_steps(a, out)

# ---------- компиляция ----------

class FnCompiler:
    def __init__(self, name, params, lift=None):
        self.name = name
        self.lift = lift or {}
        self.slots = {}
        self.code = []
        for p in params:
            self.slot(p)
    def slot(self, nm):
        if nm not in self.slots:
            self.slots[nm] = len(self.slots)
        return self.slots[nm]
    def temp(self, hint):
        nm = hint + str(len(self.slots))
        self.slot(nm)
        return nm
    def emit(self, op, arg=None):
        self.code.append([op, arg])
    def compile_expr(self, node):
        k = node[0]
        if k == "num":
            self.emit("PUSH", node[1])
        elif k == "var":
            self.emit("LOAD", self.slot(node[1]))
        elif k == "bin":
            self.compile_expr(node[2])
            self.compile_expr(node[3])
            self.emit({"+" : "ADD", "-": "SUB", "*": "MUL"}[node[1]])
        elif k == "call":
            name, argnodes = node[1], node[2]
            if name == "succ":
                if len(argnodes) != 1:
                    raise SyntaxError("succ принимает 1 аргумент")
                self.compile_expr(argnodes[0])
                self.emit("PUSH", 1)
                self.emit("ADD")
            else:
                if name not in KNOWN_FNS:
                    raise NameError(f"функция {name} не определена")
                for aexpr in argnodes:
                    self.compile_expr(aexpr)
                self.emit("CALL", [name, len(argnodes)])
        elif k == "prec":
            self.compile_prec(node)
        elif k == "ifz":
            self.compile_ifz(node)
        else:
            raise RuntimeError(f"неизвестный узел {k}")
    def compile_prec(self, node):
        c_expr, g_expr, h_ref = node[1], node[2], node[3][1]
        if h_ref not in KNOWN_FNS:
            raise NameError(f"функция шага {h_ref} не определена")
        N = self.temp("N"); C = self.temp("C"); ACC = self.temp("ACC")
        self.compile_expr(c_expr)
        self.emit("STORE", self.slots[N])
        self.compile_expr(g_expr)
        self.emit("STORE", self.slots[ACC])
        self.emit("PUSH", 0)
        self.emit("STORE", self.slots[C])         # i = 0
        l1 = len(self.code)                       # начало цикла
        self.emit("LOAD", self.slots[N])
        self.emit("LOAD", self.slots[C])
        self.emit("SUB")                          # N-C >= 0: V не падает в минус
        jz_idx = len(self.code)
        self.emit("JZ")                           # C-N == 0 -> l2; патчить
        self.emit("LOAD", self.slots[C])          # arg0 = i (0..N-1)
        self.emit("LOAD", self.slots[ACC])        # arg1 = acc
        # v0.4.0: поднятые имена шага — дополнительные аргументы CALL
        extra = self.lift.get(h_ref, [])
        for nm in extra:
            self.emit("LOAD", self.slots[nm])     # nm виден — барьер проверил
        self.emit("CALL", [h_ref, 2 + len(extra)])
        self.emit("STORE", self.slots[ACC])
        self.emit("LOAD", self.slots[C])
        self.emit("PUSH", 1)
        self.emit("ADD")
        self.emit("STORE", self.slots[C])
        self.emit("JMP", l1)
        l2 = len(self.code)
        self.code[jz_idx][1] = l2
        self.emit("LOAD", self.slots[ACC])        # результат — на стек
    def compile_ifz(self, node):
        cond, then_e, else_e = node[1], node[2], node[3]
        self.compile_expr(cond)
        jz_idx = len(self.code)
        self.emit("JZ")
        self.compile_expr(else_e)
        jmp_idx = len(self.code)
        self.emit("JMP")
        l_then = len(self.code)
        self.compile_expr(then_e)
        self.code[jz_idx][1] = l_then
        self.code[jmp_idx][1] = len(self.code)

KNOWN_FNS = set()

def build_lift_map(fns):
    """Для каждого prec-шага — объединение свободных имён его тела
    по всем местам вызова. Один и тот же шаг может зваться из разных
    функций: лифтинг обязан покрыть худший случай."""
    lift = {}
    for f in fns.values():
        steps = []
        prec_steps(f["body"], steps)
        for s in steps:
            if s not in fns:
                raise NameError(f"функция шага {s} не определена")
            for nm in sorted(collect_vars(fns[s]["body"]) - set(fns[s]["params"])):
                cur = lift.setdefault(s, [])
                if nm not in cur:
                    cur.append(nm)
    return lift

def compile_program(text):
    fns, entry = parse_program(normalize(text))
    KNOWN_FNS.update(fns.keys())
    lift = build_lift_map(fns)
    # --- семантический барьер v0.4.0 (до кодогенерации) ---
    for name, f in fns.items():
        fv = collect_vars(f["body"]) - set(f["params"]) - set(lift.get(name, []))
        if fv:
            raise NameError(
                f"свободные имена в теле {name}: {sorted(fv)} — "
                f"не доступны в области функции (параметры: {', '.join(f['params'])}; "
                f"поднятые: {', '.join(lift.get(name, [])) or '—'})")
        steps = []
        prec_steps(f["body"], steps)
        visible = set(f["params"]) | set(lift.get(name, []))
        for s in steps:
            missing = [nm for nm in lift.get(s, []) if nm not in visible]
            if missing:
                raise NameError(
                    f"шаг {s} требует поднятые имена {missing}, "
                    f"не видимые в области {name}")
    if entry["name"] not in fns:
        raise NameError(f"entry указывает на неопределённую функцию {entry['name']}")
    for aexpr in entry["args"]:
        fv = collect_vars(aexpr)
        if fv:
            raise NameError(f"аргументы entry — только литералы, найдены имена: {sorted(fv)}")
    prog = {
        "fmt": "sound-v0.3",
        "src_sha256": sha256_of(text),
        "entry": entry["name"],
        "fns": {},
    }
    for name, f in fns.items():
        params = f["params"] + lift.get(name, [])   # v0.4.0: поднятые — в хвост
        comp = FnCompiler(name, params, lift)
        comp.compile_expr(f["body"])
        if not comp.code or comp.code[-1][0] != "RET":
            comp.emit("RET")
        slots = [None] * len(comp.slots)
        for nm, idx in comp.slots.items():
            slots[idx] = nm
        prog["fns"][name] = {
            "params": params,
            "slots": slots,
            "code": comp.code,
        }
    comp = FnCompiler("main", [], lift)
    for aexpr in entry["args"]:
        comp.compile_expr(aexpr)
    comp.emit("CALL", [entry["name"], len(entry["args"])])
    comp.emit("HALT")
    prog["main"] = {"code": comp.code}
    # метки компилировались в локальных координатах функции,
    # исполняются в глобальных — перебазируем при сборке
    offset = len(prog["main"]["code"])
    for name in prog["fns"]:
        f = prog["fns"][name]
        for ins in f["code"]:
            if ins[0] in ("JZ", "JMP"):
                ins[1] += offset
        offset += len(f["code"])
    return prog

def main():
    src_path = sys.argv[1] if len(sys.argv) > 1 else "fact.pr"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "fact.sound.json"
    text = open(src_path, encoding="utf-8").read()
    prog = compile_program(text)
    n_instr = sum(len(f["code"]) for f in prog["fns"].values()) + len(prog["main"]["code"])
    import json
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(prog, fh, ensure_ascii=False, indent=1)
    print(f"функций: {len(prog['fns'])} (без main)")
    print(f"инструкций: {n_instr} (все функции + main)")
    print(f"fmt={prog['fmt']}  src_sha256={prog['src_sha256'][:16]}…")
    print(f"записано: {out_path}")

if __name__ == "__main__":
    main()
