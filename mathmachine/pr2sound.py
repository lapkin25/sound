#!/usr/bin/env python3
# pr2sound.py v0.3 — компилятор PR → звуковая машина v0.3
#
# Машина: фреймовая. Аккумулятор V, стек значений, регистры внутри фрейма.
# Инструкции:
#   LOADI k        V := k
#   LOADA i        V := R["a{i}"]        (аргумент текущего фрейма)
#   LOADR r        V := R[r]
#   STORER r       R[r] := V
#   PUSH           stack.push(V)
#   ADD/SUB/MUL    b=pop, a=pop, V := a OP b
#   EQ             b=pop, a=pop, V := 1 если a=b иначе 0
#   JZ lbl         если V=0 — переход на метку
#   JMP lbl        безусловный переход
#   CALL fn n      снять n аргументов со стека (последний сверху, затем переворот),
#                  сохранить (ret_pc, V), создать фрейм с R={a0..}, cid += 1, V := 0
#   RET            V := V (возвращаемое значение), восстановить pc из фрейма, снять фрейм
#   HALT           останов; результат — текущее V
#
# Каждая исполненная инструкция даёт одну запись протокола.
#
# Соглашение протокола (MM-1.4, черновик до живой сверки):
#   i     — номер шага (0-базный)
#   op    — имя инструкции
#   args  — аргументы инструкции
#   state — снимок после исполнения: {"V": ...}
#   depth — глубина вызова ПОСЛЕ исполнения CALL (CALL и все записи его инстанции,
#           включая её RET, имеют одинаковый depth)
#   cid   — монотонный номер вызова: CALL записывает новый cid; записи инстанции
#           (включая её RET) несут его; main — cid 0.
#   pc    — индекс исполнявшейся инструкции в коде функции
#
# Хеш программы-источника — sha256 нормализованного текста (D3), пишется в объект.
import sys, re, json, hashlib

# ---- парсер PR (автономный, дублирует run_pr.py намеренно) ----

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
            defs[m.group(1)] = (params, m.group(3).strip())
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

# ---- компилятор ----

class Fn:
    def __init__(self, name, params):
        self.name = name; self.params = params
        self.code = []; self.labels = {}; self.pend = []
    def emit(self, op, args=None):
        self.code.append({"op": op, "args": args if args is not None else []})
        return len(self.code) - 1
    def label(self, name):
        self.labels[name] = len(self.code)
    def patch(self):
        for idx, lbl in self.pend:
            self.code[idx]["args"] = [self.labels[lbl]]

def compile_expr(e, fn, defs, prec_fns):
    k = e[0]
    if k == 'lit':
        fn.emit('LOADI', [e[1]]); return
    if k == 'var':
        fn.emit('LOADA', [fn.params.index(e[1])]); return
    name, args = e[1], e[2]
    if name == 'succ':
        compile_expr(args[0], fn, defs, prec_fns)
        fn.emit('PUSH'); fn.emit('LOADI', [1]); fn.emit('ADD'); return
    if name in ('add', 'mul'):
        compile_expr(args[0], fn, defs, prec_fns); fn.emit('PUSH')
        compile_expr(args[1], fn, defs, prec_fns); fn.emit('PUSH')
        fn.emit('ADD' if name == 'add' else 'MUL'); return
    if name == 'prec':
        n_e, g_e, h_e = args
        hname = h_e[1]
        if g_e[0] != 'lit':
            raise SyntaxError("g в prec — пока только литерал")
        if hname not in defs or len(defs[hname][0]) != 2:
            raise SyntaxError("h в prec — должен быть def с 2 параметрами")
        j = "p%d" % len(prec_fns)
        # место вызова: вычислить n, положить на стек, CALL
        compile_expr(n_e, fn, defs, prec_fns)
        fn.emit('PUSH')
        fn.emit('CALL', [j, 1])
        # сабрутина prec
        sub = Fn(j, ["n"])
        sub.emit('LOADA', [0]); sub.emit('STORER', ["n"])
        sub.emit('LOADR', ["n"]); sub.emit('PUSH')
        sub.emit('LOADI', [0]); sub.emit('PUSH'); sub.emit('EQ')
        ji = sub.emit('JZ', None); sub.pend.append((ji, "rec"))
        sub.emit('LOADI', [g_e[1]])
        je = sub.emit('JMP', None); sub.pend.append((je, "end"))
        sub.label("rec")
        sub.emit('LOADR', ["n"]); sub.emit('PUSH'); sub.emit('LOADI', [1]); sub.emit('SUB')
        sub.emit('STORER', ["m"])
        sub.emit('LOADR', ["m"]); sub.emit('PUSH')   # будущий аргумент 1 для h
        sub.emit('LOADR', ["m"]); sub.emit('PUSH')   # аргумент для рекурсивного CALL
        sub.emit('CALL', [j, 1])                     # V = prec(n-1)
        sub.emit('PUSH')                             # стек: [n-1, acc]
        sub.emit('CALL', [hname, 2])                 # V = h(n-1, acc)
        sub.emit('RET')
        sub.label("end")
        sub.emit('RET')
        prec_fns[j] = sub
        return
    if name in defs:
        for a in args:
            compile_expr(a, fn, defs, prec_fns)
            fn.emit('PUSH')
        fn.emit('CALL', [name, len(args)])
        return
    raise NameError("неизвестное имя: %r" % name)

def main():
    src_path, out_path = sys.argv[1], sys.argv[2]
    text = open(src_path, encoding='utf-8').read()
    defs, entry = parse(text)
    fns, prec_fns = {}, {}
    for name, (params, rhs) in defs.items():
        f = Fn(name, params)
        compile_expr(parse_expr(rhs), f, defs, prec_fns)
        f.emit('RET')
        f.patch()
        fns[name] = f
    for j, sub in prec_fns.items():
        sub.patch()
        fns[j] = sub
    mainf = Fn("main", [])
    for a in entry[1]:
        mainf.emit('LOADI', [a]); mainf.emit('PUSH')
    mainf.emit('CALL', [entry[0], len(entry[1])])
    mainf.emit('HALT')
    mainf.patch()
    prog = {
        "spec": "mm-sound-v0.3",
        "src_sha256": hashlib.sha256(normalize(text).encode('utf-8')).hexdigest(),
        "entry": {"fn": entry[0], "args": entry[1]},
        "main": mainf.code,
        "fns": {name: {"params": f.params, "code": f.code} for name, f in fns.items()},
    }
    json.dump(prog, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    n_instr = sum(len(f.code) for f in fns.values()) + len(mainf.code)
    print("compiled fns=%d instrs=%d" % (len(fns) + 1, n_instr))
    print("sha256=%s" % prog["src_sha256"])

if __name__ == '__main__':
    main()
