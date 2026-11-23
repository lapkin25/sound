#!/usr/bin/env python3
# run_pr.py v0.3 — прямой интерпретатор PR-языка (дорога «прямая»)
# PR v0.3. Конструкции:
#   def f(a, b) = <expr>            — определение функции
#   succ(e), add(e1,e2), mul(e1,e2) — встроенные операции
#   prec(n, g, h)                   — схема примитивной рекурсии:
#         f(0) = g;  f(k+1) = h(k, f(k))
#     развёртка рекурсивная, вниз: prec(n,g,h) = g при n=0,
#     иначе h(n-1, prec(n-1,g,h)). Счётчик — первый аргумент шага (наша конвенция).
#     g — пока только целочисленный литерал; h — имя def с 2 параметрами (counter, acc)
#   entry f(a1, ...)                — точка входа в тексте программы
# Комментарии: от ';' до конца строки.
# Хеш программы: sha256 от нормализованного текста (построчный rstrip,
# пустые строки выброшены) — решение D3 из спецификации Math Machine v0.1.
import sys, re, hashlib

def normalize(text):
    lines = [l.rstrip() for l in text.splitlines()]
    return "\n".join(l for l in lines if l.strip())

def strip_comment(line):
    i = line.find(';')
    return line[:i] if i >= 0 else line

def parse(text):
    defs, entry = {}, None
    for raw in text.splitlines():
        line = strip_comment(raw).strip()
        if not line:
            continue
        m = re.match(r'^def\s+(\w+)\s*\(([^)]*)\)\s*=\s*(.+)$', line)
        if m:
            params = [p.strip() for p in m.group(2).split(',') if p.strip()]
            defs[m.group(1)] = (params, parse_expr(m.group(3).strip()))
            continue
        m = re.match(r'^entry\s+(\w+)\s*\(([^)]*)\)\s*$', line)
        if m:
            args = [int(x.strip()) for x in m.group(2).split(',') if x.strip()]
            entry = (m.group(1), args)
            continue
        raise SyntaxError("не разобрать строку: %r" % line)
    if entry is None:
        raise SyntaxError("нет строки entry")
    return defs, entry

def tokenize(s):
    return re.findall(r'\d+|\w+|[(),]', s)

class Tok:
    def __init__(self, toks):
        self.t = toks; self.i = 0
    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None
    def take(self):
        t = self.peek(); self.i += 1; return t

def parse_expr(s):
    t = Tok(tokenize(s))
    e = expr(t)
    if t.peek() is not None:
        raise SyntaxError("лишние токены в: %r" % s)
    return e

def expr(t):
    x = t.take()
    if x is None:
        raise SyntaxError("обрыв выражения")
    if x.isdigit():
        return ('lit', int(x))
    if re.match(r'^\w+$', x):
        if t.peek() == '(':
            t.take()
            args = []
            if t.peek() != ')':
                args.append(expr(t))
                while t.peek() == ',':
                    t.take(); args.append(expr(t))
            if t.take() != ')':
                raise SyntaxError("ожидалась )")
            return ('call', x, args)
        return ('var', x)
    raise SyntaxError("неожиданный токен %r" % x)

STEPS = 0

def evaluate(e, env, defs):
    global STEPS
    k = e[0]
    if k == 'lit':
        return e[1]
    if k == 'var':
        return env[e[1]]
    name, args = e[1], e[2]
    if name == 'succ':
        STEPS += 1
        return evaluate(args[0], env, defs) + 1
    if name == 'add':
        STEPS += 1
        return evaluate(args[0], env, defs) + evaluate(args[1], env, defs)
    if name == 'mul':
        STEPS += 1
        return evaluate(args[0], env, defs) * evaluate(args[1], env, defs)
    if name == 'prec':
        n = evaluate(args[0], env, defs)
        g = args[1]
        if g[0] != 'lit':
            raise SyntaxError("g в prec — только литерал")
        hname = args[2][1]
        hparams, hbody = defs[hname]
        def rec(k):
            global STEPS
            if k == 0:
                return g[1]
            STEPS += 1
            acc = rec(k - 1)
            henv = {hparams[0]: k - 1, hparams[1]: acc}
            return evaluate(hbody, henv, defs)
        return rec(n)
    if name in defs:
        params, body = defs[name]
        vals = [evaluate(a, env, defs) for a in args]
        return evaluate(body, dict(zip(params, vals)), defs)
    raise NameError("неизвестное имя: %r" % name)

def main():
    path = sys.argv[1]
    text = open(path, encoding='utf-8').read()
    defs, entry = parse(text)
    fn, argv = entry
    if fn not in defs:
        raise NameError("entry указывает на неизвестную функцию: %r" % fn)
    params, body = defs[fn]
    env = dict(zip(params, argv))
    value = evaluate(body, env, defs)
    h = hashlib.sha256(normalize(text).encode('utf-8')).hexdigest()
    print("value=%d" % value)
    print("steps=%d" % STEPS)
    print("sha256=%s" % h)

if __name__ == '__main__':
    main()
