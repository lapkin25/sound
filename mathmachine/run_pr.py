#!/usr/bin/env python3
# run_pr.py v0.3.1 — прямой интерпретатор PR («прямая дорога»)
#
# Схема записи .pr:
#   def имя(параметры) = выражение
#   entry имя(аргументы)
# Выражения: литералы, имена, вызовы, + - *, succ(x), prec(c, g, h).
# Схема prec (счётчик — первый аргумент):
#   f(0)   = g
#   f(n+1) = h(n, f(n))
#
# Вывод: value, steps, sha256 нормализованного текста.
# Нормализация: построчный rstrip, пустые строки отбрасываются.

import sys, hashlib, re

# ---------- нормализация и хеш ----------

def normalize(text):
    lines = [ln.rstrip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln.strip())

def sha256_of(text):
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()

# ---------- разбор ----------

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

# ---------- исполнение ----------

class Interp:
    def __init__(self, fns):
        self.fns = fns
        self.steps = 0
    def eval(self, node, env):
        k = node[0]
        if k == "num":
            return node[1]
        if k == "var":
            if node[1] not in env:
                raise NameError(f"имя {node[1]} не определено")
            return env[node[1]]
        if k == "bin":
            op, l, r = node[1], node[2], node[3]
            a = self.eval(l, env); b = self.eval(r, env)
            self.steps += 1
            return a + b if op == "+" else a - b if op == "-" else a * b
        if k == "call":
            name, argnodes = node[1], node[2]
            if name == "succ":
                x = self.eval(argnodes[0], env)
                self.steps += 1
                return x + 1
            f = self.fns.get(name)
            if f is None:
                raise NameError(f"функция {name} не определена")
            args = [self.eval(x, env) for x in argnodes]
            return self.eval(f["body"], dict(zip(f["params"], args)))
        if k == "prec":
            c_expr, g_expr, h_ref = node[1], node[2], node[3]
            h = self.fns.get(h_ref[1])
            if h is None:
                raise NameError(f"функция шага {h_ref[1]} не определена")
            if len(h["params"]) != 2:
                raise SyntaxError("функция шага prec принимает 2 параметра: h(n, acc)")
            n = self.eval(c_expr, env)
            v = self.eval(g_expr, env)
            p0, p1 = h["params"]
            for i in range(n):
                self.steps += 1
                v = self.eval(h["body"], {p0: i, p1: v})
            return v
        raise RuntimeError(f"неизвестный узел {k}")

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "fact.pr"
    text = open(path, encoding="utf-8").read()
    fns, entry = parse_program(normalize(text))
    interp = Interp(fns)
    f = fns.get(entry["name"])
    if f is None:
        raise NameError(f"entry-функция {entry['name']} не определена")
    args = [interp.eval(x, {}) for x in entry["args"]]
    value = interp.eval(f["body"], dict(zip(f["params"], args)))
    print(f"value={value}")
    print(f"steps={interp.steps}")
    print(f"sha256={sha256_of(text)}")

if __name__ == "__main__":
    main()
