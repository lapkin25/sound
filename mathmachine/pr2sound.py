#!/usr/bin/env python3
# pr2sound.py v0.3.1 — компилятор PR → звуковая машина
#
# Вход: .pr-программа (формат как в run_pr.py).
# Выход: .sound.json — программа звуковой машины:
#   {"fmt": "sound-v0.3", "src_sha256": ..., "entry": имя,
#    "fns": {имя: {"params": [...], "code": [...]}},
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

# ---------- компиляция ----------

class FnCompiler:
    def __init__(self, name, params):
        self.name = name
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
        self.emit("CALL", [h_ref, 2])
        self.emit("STORE", self.slots[ACC])
        self.emit("LOAD", self.slots[C])
        self.emit("PUSH", 1)
        self.emit("ADD")
        self.emit("STORE", self.slots[C])
        self.emit("JMP", l1)
        l2 = len(self.code)
        self.code[jz_idx][1] = l2
        self.emit("LOAD", self.slots[ACC])        # результат — на стек

KNOWN_FNS = set()

def compile_program(text):
    fns, entry = parse_program(normalize(text))
    KNOWN_FNS.update(fns.keys())
    prog = {
        "fmt": "sound-v0.3",
        "src_sha256": sha256_of(text),
        "entry": entry["name"],
        "fns": {},
    }
    for name, f in fns.items():
        comp = FnCompiler(name, f["params"])
        comp.compile_expr(f["body"])
        if not comp.code or comp.code[-1][0] != "RET":
            comp.emit("RET")
        slots = [None] * len(comp.slots)
        for nm, idx in comp.slots.items():
            slots[idx] = nm
        prog["fns"][name] = {
            "params": f["params"],
            "slots": slots,
            "code": comp.code,
        }
    comp = FnCompiler("main", [])
    for aexpr in entry["args"]:
        comp.compile_expr(aexpr)
    comp.emit("CALL", [entry["name"], len(entry["args"])])
    comp.emit("HALT")
    prog["main"] = {"code": comp.code}
    # метки компилировались в локальных координатах функции,
    # исполняются в глобальных — перебазируем при сборке
    offset = len(prog["main"]["code"])
    for f in prog["fns"].values():
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
