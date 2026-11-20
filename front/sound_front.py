# sound_front.py -- frontend Sound v0.3: lexer -> parser -> compiler -> TRIOBOOK1.
# Battery T20-T27: 9 checks. Run: python3 sound_front.py

import json
import struct

# ---------- Diagnostics ----------
class Diag(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg
        super().__init__(code + " " + msg)

# ---------- Canonical float (SCore 7.1) ----------
def canon_float(x):
    return float(x).hex()

def canon_scalar(v):
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, int): return str(v)
    if isinstance(v, float): return canon_float(v)
    if isinstance(v, str): return v
    raise TypeError("non-canonical scalar: " + repr(v))

# ---------- STRUCT terms ----------
def T(head, **f):
    return {"h": head, "f": f}

def ser_val(v):
    if isinstance(v, dict) and "h" in v: return ser_term(v)
    if isinstance(v, list):
        return "[" + " ".join(ser_val(x) for x in v) + "]"
    if isinstance(v, bool): return "true" if v else "false"
    if isinstance(v, float): return canon_float(v)
    if isinstance(v, int): return str(v)
    if isinstance(v, str): return json.dumps(v, ensure_ascii=False)
    raise TypeError("not serializable: " + repr(v))

def ser_term(t):
    s = "{" + t["h"]
    for k, v in t["f"].items():
        s += " " + k + "=" + ser_val(v)
    return s + "}"

def struct_eq(a, b):
    if isinstance(a, dict) and isinstance(b, dict) and "h" in a and "h" in b:
        if a["h"] != b["h"] or list(a["f"].keys()) != list(b["f"].keys()):
            return False
        return all(struct_eq(a["f"][k], b["f"][k]) for k in a["f"])
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(struct_eq(x, y) for x, y in zip(a, b))
    if isinstance(a, float) and isinstance(b, float):
        return struct.pack("<d", a) == struct.pack("<d", b)
    return type(a) is type(b) and a == b

# ---------- Term text parser (canonical form) ----------
def term_tokens(s):
    toks, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1; continue
        if c in "{}[]=":
            toks.append(("P", c)); i += 1; continue
        if c == '"':
            j = i + 1; buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n:
                    buf.append(s[j + 1]); j += 2
                else:
                    buf.append(s[j]); j += 1
            if j >= n: raise SyntaxError("unterminated string in term")
            toks.append(("STR", "".join(buf))); i = j + 1; continue
        j = i
        while j < n and s[j] not in ' \t\r\n{}[]="':
            j += 1
        toks.append(("ATOM", s[i:j])); i = j
    return toks

def atom_val(w):
    if w == "true": return True
    if w == "false": return False
    try: return int(w)
    except ValueError: pass
    try: return float.fromhex(w)
    except ValueError: pass
    try: return float(w)
    except ValueError: pass
    raise SyntaxError("unknown atom: " + repr(w))

def parse_term_text(s):
    toks = term_tokens(s)
    if not toks: raise SyntaxError("empty term")
    t, j = _pt(toks, 0)
    if j != len(toks): raise SyntaxError("trailing tokens in term")
    return t

def _pt(toks, i):
    if i >= len(toks) or toks[i] != ("P", "{"): raise SyntaxError("expected {")
    if i + 1 >= len(toks) or toks[i + 1][0] != "ATOM":
        raise SyntaxError("expected term head")
    head = toks[i + 1][1]
    f = {}; i += 2
    while i < len(toks) and toks[i] != ("P", "}"):
        if toks[i][0] != "ATOM": raise SyntaxError("expected field name")
        key = toks[i][1]
        if i + 1 >= len(toks) or toks[i + 1] != ("P", "="):
            raise SyntaxError("expected = after field " + key)
        v, i = _pv(toks, i + 2)
        f[key] = v
    if i >= len(toks): raise SyntaxError("unterminated term")
    return {"h": head, "f": f}, i + 1

def _pv(toks, i):
    if i >= len(toks): raise SyntaxError("unexpected EOF in term")
    t = toks[i]
    if t == ("P", "{"): return _pt(toks, i)
    if t == ("P", "["):
        i += 1; out = []
        while i < len(toks) and toks[i] != ("P", "]"):
            v, i = _pv(toks, i); out.append(v)
        if i >= len(toks): raise SyntaxError("unterminated vec")
        return out, i + 1
    if t[0] == "STR": return t[1], i + 1
    if t[0] == "ATOM": return atom_val(t[1]), i + 1
    raise SyntaxError("unexpected token in term: " + repr(t))

# ---------- Book: serialize / load (TRIOBOOK1) ----------
SECTIONS = ["program", "models", "nodes", "journal", "golden"]

def serialize_book(counts, blocks):
    header = {"format": "TRIOBOOK1", "version": 1,
              "sections": SECTIONS, "counts": {s: counts[s] for s in SECTIONS}}
    out = json.dumps(header, ensure_ascii=False, separators=(",", ":"))
    for s in SECTIONS:
        out += "\n@begin " + s + "\n"
        for line in blocks.get(s, []):
            if isinstance(line, str):
                out += ser_val(line) + "\n"
            else:
                out += ser_term(line) + "\n"
        out += "@end " + s + "\n"
    return out

def load_book_text(text):
    lines = text.splitlines()
    if not lines: raise SyntaxError("empty book")
    header = json.loads(lines[0])
    if header.get("format") != "TRIOBOOK1": raise SyntaxError("bad magic")
    if list(header.get("sections", [])) != SECTIONS: raise SyntaxError("bad sections")
    blocks = {s: [] for s in SECTIONS}
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1; continue
        if not line.startswith("@begin "): raise SyntaxError("expected @begin")
        name = line[len("@begin "):].strip()
        if name not in SECTIONS: raise SyntaxError("unknown section " + name)
        i += 1; depth = 1
        while i < len(lines) and depth > 0:
            l = lines[i].strip()
            if l.startswith("@begin "): depth += 1
            elif l.startswith("@end"):
                depth -= 1
                if depth == 0: break
            if l: blocks[name].append(block_line_to_term(l))
            i += 1
        if depth != 0: raise SyntaxError("unclosed section " + name)
        i += 1
    for s in SECTIONS:
        if header["counts"].get(s, None) != len(blocks[s]):
            raise SyntaxError("counts mismatch in " + s)
    return header, blocks

def block_line_to_term(line):
    line = line.strip()
    if not line: return None
    if line.startswith('"'):
        return parse_term_text(line)
    return parse_term_text(line)

# ---------- Lexer (.sound, Lang Spec section 2) ----------
KEYWORDS = {"spec","fact","rule","wire","invariant","goal","implementation",
            "dim","requires","domain","in","as","handle","from","minimize",
            "maximize","let","fun","if","then","else","not","and","or",
            "true","false"}
TWO = {"->","==","!=","<=",">="}
ONE = set("()[]{};:,.<>+-*/%=")

def lex(src):
    toks, i, n, line = [], 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c in " \t\r":
            i += 1; continue
        if c == "#":  # inherited form
            while i < n and src[i] != "\n": i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n": i += 1
            continue
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0: raise Diag("SC-099", "unterminated block comment")
            line += src.count("\n", i, j); i = j + 2; continue
        if c == '"':
            j = i + 1; buf = []
            while j < n and src[j] != '"':
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j + 1]); j += 2
                else:
                    buf.append(src[j]); j += 1
            if j >= n: raise Diag("SC-099", "unterminated string")
            toks.append(("STR", "".join(buf), line)); i = j + 1; continue
        if c.isdigit():
            j = i
            while j < n and (src[j].isdigit() or src[j] in ".eE"):
                if src[j] in "eE" and j + 1 < n and src[j + 1] in "+-": j += 1
                j += 1
            text = src[i:j]
            isfloat = "." in text or "e" in text or "E" in text
            try:
                v = float(text) if isfloat else int(text)
            except ValueError:
                raise Diag("SC-099", "bad literal " + repr(text))
            toks.append(("FLOAT" if isfloat else "NAT", v, line)); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"): j += 1
            w = src[i:j]; i = j
            toks.append(("KW" if w in KEYWORDS else "IDENT", w, line)); continue
        if src[i:i+2] in TWO:
            toks.append(("OP", src[i:i+2], line)); i += 2; continue
        if c in ONE:
            toks.append(("OP", c, line)); i += 1; continue
        raise Diag("SC-099", "unexpected character " + repr(c))
    toks.append(("EOF", None, line))
    return toks

# ---------- Parser (section 3) ----------
class Parser:
    def __init__(self, toks):
        self.toks = toks; self.i = 0
    def at(self, kind, val=None):
        t = self.toks[self.i]
        return t[0] == kind and (val is None or t[1] == val)
    def next(self):
        t = self.toks[self.i]; self.i += 1; return t
    def expect(self, kind, val=None):
        t = self.next()
        if t[0] != kind or (val is not None and t[1] != val):
            raise Diag("SC-097", "expected " + str(val or kind) +
                       ", got " + repr(t[1]))
        return t
    def ident(self):
        t = self.next()
        if t[0] != "IDENT":
            raise Diag("SC-097", "expected identifier, got " + repr(t[1]))
        return t[1]

TYPE_ALIAS = {"F64": "Float64", "F32": "Float32"}

def parse_type(p):
    t = p.next()
    if t[0] != "IDENT": raise Diag("SC-097", "expected type, got " + repr(t[1]))
    name = TYPE_ALIAS.get(t[1], t[1])
    if name in {"Int64","Float64","Float32","Bool","String","Any"}:
        return T("type", name=name)
    if name == "Matrix":
        p.expect("OP", "["); elem = p.ident(); elem = TYPE_ALIAS.get(elem, elem)
        p.expect("OP", ",")
        dims = [parse_dim(p)]
        while p.at("OP", ","):
            p.next(); dims.append(parse_dim(p))
        p.expect("OP", "]")
        return T("type", name="Matrix", elem=elem, dims=dims)
    if name == "Vector":
        p.expect("OP", "["); elem = p.ident(); elem = TYPE_ALIAS.get(elem, elem)
        p.expect("OP", ","); d = parse_dim(p); p.expect("OP", "]")
        return T("type", name="Vector", elem=elem, dims=[d])
    if name in {"Stream", "Seq", "Optional"}:
        p.expect("OP", "["); inner = parse_type(p); p.expect("OP", "]")
        return T("type", name=name, elem=inner)
    if name == "Result":
        p.expect("OP", "["); ok = parse_type(p); p.expect("OP", ",")
        e = p.ident(); p.expect("OP", "]")
        return T("type", name="Result", ok=ok, err=e)
    if name == "Record":
        p.expect("OP", "{"); fields = []
        while not p.at("OP", "}"):
            fn = p.ident(); p.expect("OP", ":"); ft = parse_type(p)
            fields.append((fn, ft))
            if p.at("OP", ","): p.next()
        p.expect("OP", "}")
        return T("type", name="Record", fields=fields)
    raise Diag("SC-097", "unknown type " + repr(name))

def parse_dim(p):
    t = p.next()
    if t[0] == "NAT": return t[1]
    if t[0] == "IDENT":
        name = t[1]
        # linear dimexpr: IDENT/NAT (+|-|* NAT/IDENT)
        while p.at("OP", "+") or p.at("OP", "-") or p.at("OP", "*"):
            op = p.next()[1]
            rhs = p.next()
            return T("dimexpr", op=op, l=name, r=rhs[1])
        return name
    if t[0] == "OP" and t[1] == "?":
        return "?"
    raise Diag("SC-097", "bad dimension " + repr(t[1]))

def parse_port(p):
    n = p.ident()
    if p.at("OP", "."):
        p.next(); return (n, p.ident())
    return (n, None)

def parse_rulemods(p):
    requires, domain, invariant, binding = [], "strict", [], None
    while p.at("KW", "requires") or p.at("KW", "domain") \
          or p.at("KW", "invariant") or p.at("KW", "in"):
        k2, v2, _ = p.next()
        if v2 == "requires":
            cond = parse_expr(p); requires.append(cond)
        elif v2 == "domain":
            domain = p.ident()
        elif v2 == "invariant":
            words = []
            while not (p.at("OP", "->") or p.at("OP", ";")):
                words.append(str(p.next()[1]))
            invariant.append(" ".join(words))
        elif v2 == "in":
            rt = p.ident()
            if rt not in {"python", "java", "octave"}:
                raise Diag("SC-097", "unknown runtime " + repr(rt))
            p.expect("OP", ":"); art = p.expect("STR")[1]
            binding = (rt, art)
    return {"requires": requires, "domain": domain,
            "invariant": invariant, "binding": binding}

def parse_item(p):
    k, v, _ = p.next()
    if k != "KW": raise Diag("SC-097", "expected item, got " + repr(v))
    if v == "fact":
        name = p.ident()
        src = None
        if p.at("KW", "from"):
            p.next(); src = p.expect("STR")[1]
        p.expect("OP", "->"); ty = parse_type(p); p.expect("OP", ";")
        return {"kind": "fact", "name": name, "src": src, "type": ty}
    if v == "rule":
        name = p.ident(); p.expect("OP", "(")
        args = []
        while not p.at("OP", ")"):
            an = p.ident(); p.expect("OP", ":"); at = parse_type(p)
            args.append((an, at))
            if p.at("OP", ","): p.next()
        p.expect("OP", ")")
        m1 = parse_rulemods(p)          # grammar order: mods before ->
        p.expect("OP", "->"); ty = parse_type(p)
        m2 = parse_rulemods(p)          # order of the full example in section 11
        requires = m1["requires"] + m2["requires"]
        invariant = m1["invariant"] + m2["invariant"]
        domain = m2["domain"] if m2["domain"] != "strict" else m1["domain"]
        binding = m2["binding"] or m1["binding"]
        body = None
        if p.at("OP", "="):
            p.next(); body = parse_expr(p)
        p.expect("OP", ";")
        return {"kind": "rule", "name": name, "args": args,
                "requires": requires, "domain": domain,
                "invariant": invariant, "binding": binding,
                "type": ty, "body": body}
    if v == "wire":
        dst = parse_port(p); p.expect("OP", "=")
        if p.at("NAT") or p.at("FLOAT") or p.at("STR") \
           or (p.at("KW", "true") or p.at("KW", "false")):
            t = p.next()
            lit = t[1] if t[0] in ("NAT", "FLOAT", "STR") \
                else (t[1] == "true")
        else:
            lit = None
        src = parse_port(p) if lit is None else None
        mode = None; handle = []
        if p.at("KW", "as"):
            p.next(); mode = p.ident()
            if mode not in {"copy", "view", "move"}:
                raise Diag("SC-097", "unknown mode " + repr(mode))
        if p.at("KW", "handle"):
            p.next(); p.expect("OP", "[")
            while not p.at("OP", "]"):
                handle.append(p.ident())
                if p.at("OP", ","): p.next()
            p.expect("OP", "]")
        p.expect("OP", ";")
        return {"kind": "wire", "dst": dst, "src": src, "lit": lit,
                "mode": mode, "handle": handle}
    if v == "invariant":
        words = []
        while not p.at("OP", ";"):
            words.append(str(p.next()[1]))
        p.expect("OP", ";")
        return {"kind": "invariant", "text": " ".join(words)}
    if v == "goal":
        goals = []
        while not p.at("OP", ";"):
            g, gv, _ = p.next()
            if g != "KW" or gv not in {"minimize", "maximize"}:
                raise Diag("SC-097", "expected goal, got " + repr(gv))
            p.expect("OP", "("); ident = p.ident(); p.expect("OP", ")")
            goals.append((gv, ident))
            if p.at("OP", ","): p.next()
        p.expect("OP", ";")
        return {"kind": "goal", "goals": goals}
    if v == "implementation":
        name = p.ident(); p.expect("KW", "in"); rt = p.ident()
        if rt not in {"python", "java", "octave"}:
            raise Diag("SC-097", "unknown runtime " + repr(rt))
        p.expect("OP", ":"); art = p.expect("STR")[1]; p.expect("OP", ";")
        return {"kind": "impl", "name": name, "runtime": rt, "artifact": art}
    if v == "dim":
        name = p.ident()
        val = None
        if p.at("OP", "="):
            p.next(); val = p.next()[1]
        p.expect("OP", ";")
        return {"kind": "dim", "name": name, "value": val}
    raise Diag("SC-097", "unknown item " + repr(v))

# ---------- Expressions (Addendum v0.2 grammar) ----------
def parse_expr(p):  # let | fun | if | or
    if p.at("KW", "let"):
        p.next(); name = p.ident(); p.expect("OP", "=")
        e1 = parse_expr(p); p.expect("KW", "in"); e2 = parse_expr(p)
        return T("let", name=name, body=e1, next=e2)
    if p.at("KW", "fun"):
        p.next(); params = [p.ident()]
        while p.at("IDENT"): params.append(p.ident())
        p.expect("OP", "->"); body = parse_expr(p)
        return T("fun", params=params, body=body)
    if p.at("KW", "if"):
        p.next(); c = parse_expr(p); p.expect("KW", "then")
        a = parse_expr(p); p.expect("KW", "else"); b = parse_expr(p)
        return T("if", cond=c, then=a, else_=b)
    return parse_or(p)

def parse_or(p):
    l = parse_and(p)
    while p.at("KW", "or"):
        p.next(); l = T("op", name="or", args=[l, parse_and(p)])
    return l

def parse_and(p):
    l = parse_cmp(p)
    while p.at("KW", "and"):
        p.next(); l = T("op", name="and", args=[l, parse_cmp(p)])
    return l

def parse_cmp(p):
    l = parse_add(p)
    if p.at("OP"):
        t = p.toks[p.i]
        if t[1] in {"==","!=","<","<=",">",">="}:
            p.next()
            l = T("op", name=t[1], args=[l, parse_add(p)])
    return l

def parse_add(p):
    l = parse_mul(p)
    while p.at("OP", "+") or p.at("OP", "-"):
        op = p.next()[1]
        l = T("op", name=op, args=[l, parse_mul(p)])
    return l

def parse_mul(p):
    l = parse_unary(p)
    while p.at("OP", "*") or p.at("OP", "/") or p.at("OP", "%"):
        op = p.next()[1]
        l = T("op", name=op, args=[l, parse_unary(p)])
    return l

def parse_unary(p):
    if p.at("OP", "-"):
        p.next(); return T("neg", x=parse_unary(p))
    if p.at("KW", "not"):
        p.next(); return T("not", x=parse_unary(p))
    return parse_app(p)

def parse_app(p):
    f = parse_atom(p)
    while p.at("IDENT") or p.at("NAT") or p.at("FLOAT") \
          or (p.at("KW", "true") or p.at("KW", "false")):
        f = T("app", f=f, args=[parse_atom(p)])
    return f

def parse_atom(p):
    t = p.next()
    if t[0] == "NAT": return T("num", v=t[1])
    if t[0] == "FLOAT": return T("num", v=t[1])
    if t[0] == "KW" and t[1] in {"true", "false"}:
        return T("bool", v=(t[1] == "true"))
    if t[0] == "IDENT": return T("var", name=t[1])
    if t[0] == "OP" and t[1] == "(":
        e = parse_expr(p); p.expect("OP", ")"); return e
    if t[0] == "OP" and t[1] == "[":
        items = []
        while not p.at("OP", "]"):
            items.append(parse_expr(p))
            if p.at("OP", ";") or p.at("OP", ","): p.next()
        p.expect("OP", "]")
        return T("vec", items=items)
    raise Diag("SC-097", "unexpected token " + repr(t[1]))

def parse_spec(src):
    toks = lex(src)
    p = Parser(toks)
    p.expect("KW", "spec")
    name = p.ident()
    p.expect("OP", "{")
    items = []
    while not p.at("OP", "}"):
        items.append(parse_item(p))
    p.expect("OP", "}")
    if not p.at("EOF"):
        raise Diag("SC-098", "trailing tokens after spec")
    return {"kind": "spec", "name": name, "items": items}

# ---------- Compiler: spec -> TRIOBOOK1 ----------
BASE_TYPES = {"Int64", "Float64", "Float32", "Bool", "String"}

def collect_dimvars(spec):
    s = set()
    def walk(t):
        if isinstance(t, dict) and "h" in t:
            if t["h"] == "type" and t["f"].get("name") in {"Matrix", "Vector"}:
                for d in t["f"].get("dims", []):
                    if isinstance(d, str) and d != "?":
                        s.add(d)
            for v in t["f"].values(): walk(v)
        elif isinstance(t, list):
            for x in t: walk(x)
    walk(spec)
    return s

def check_nonlinear(cond, dimvars):
    def is_dim(t):
        return isinstance(t, dict) and t.get("h") == "var" \
               and t["f"]["name"] in dimvars
    def walk(t):
        if isinstance(t, dict) and t.get("h") == "op":
            if t["f"]["name"] == "*":
                l, r = t["f"]["args"]
                if is_dim(l) and is_dim(r):
                    raise Diag("SC-020", "non-linear condition")
            for v in t["f"].values(): walk(v)
        elif isinstance(t, list):
            for x in t: walk(x)
    walk(cond)

def lit_type(v):
    if isinstance(v, bool): return T("type", name="Bool")
    if isinstance(v, int): return T("type", name="Int64")
    if isinstance(v, float): return T("type", name="Float64")
    return T("type", name="String")

def check_conv(src_t, dst_t, lit):
    # returns (lossy flag); raises Diag on forbidden conversions
    sb = src_t["f"].get("name"); db = dst_t["f"].get("name")
    sbase = sb if sb in BASE_TYPES else None
    dbase = db if db in BASE_TYPES else None
    if src_t == dst_t:
        if sbase == "Int64" and lit is not None and abs(lit) > 2**53:
            raise Diag("IntRangeOverflow", "integer beyond 2^53")
        return False
    if sbase is None or dbase is None:
        raise Diag("SC-040", "forbidden conversion: type mismatch")
    if sbase == dbase:
        if sbase == "Int64" and lit is not None and abs(lit) > 2**53:
            raise Diag("IntRangeOverflow", "integer beyond 2^53")
        return False
    if sbase == "Float32" and dbase == "Float64": return False
    if sbase == "Float64" and dbase == "Float32": return False  # Lossy(precision) at bridge
    if sbase == "Int64" and dbase == "Float64":
        if lit is not None and abs(lit) > 2**53:
            raise Diag("IntRangeOverflow", "integer beyond 2^53")
        return False
    if sbase == "Float64" and dbase == "Int64":
        if lit is not None and isinstance(lit, float) and lit != int(lit):
            raise Diag("SC-040", "fractional literal to Int64")
        raise Diag("SC-040", "narrowing Float64->Int64 on edge")
    if sbase == "Bool" or dbase == "Bool":
        raise Diag("UndefinedBridge", "Bool does not coerce to numbers")
    raise Diag("SC-040", "forbidden conversion " + sbase + "->" + dbase)

class Book:
    def __init__(self, blocks):
        self.blocks = blocks
        self.counts = {s: len(blocks[s]) for s in SECTIONS}
    def serialize(self):
        return serialize_book(self.counts, self.blocks)

def compile_spec(spec):
    facts, rules = {}, {}
    wires, impls = [], []
    for it in spec["items"]:
        k = it["kind"]
        if k == "fact": facts[it["name"]] = it
        elif k == "rule": rules[it["name"]] = it
        elif k == "wire": wires.append(it)
        elif k == "impl": impls.append(it)
        # invariant/goal/dim are fixed in the graph (v0.1)
    dimvars = collect_dimvars(spec)
    for r in rules.values():
        for cond in r["requires"]:
            check_nonlinear(cond, dimvars)
    for r in rules.values():
        if r["binding"] is None and r["body"] is None:
            raise Diag("SC-001", "unbound rule " + r["name"])

    def port_type(node, field):
        if node in facts:
            if field in (None, "out"): return facts[node]["type"]
            raise Diag("SC-002", "no port " + str(field))
        if node in rules:
            r = rules[node]
            if field is None or field == "out": return r["type"]
            for an, at in r["args"]:
                if an == field: return at
            raise Diag("SC-002", "no port " + str(field) + " at " + node)
        raise Diag("SC-002", "unknown name " + str(node))

    # topological order over data edges src_node -> dst_node
    edges, indeg = {}, {}
    allnodes = list(facts) + list(rules)
    for n in allnodes: indeg[n] = 0
    for w in wires:
        if w["lit"] is not None: continue
        sn = w["src"][0]; dn = w["dst"][0]
        if sn not in facts and sn not in rules: continue  # error at emission
        if dn not in facts and dn not in rules: continue
        if sn == dn: raise Diag("SC-070", "self-cycle " + sn)
        edges.setdefault(sn, []).append(dn)
        indeg[dn] += 1
    from collections import deque
    q = deque([n for n in allnodes if indeg[n] == 0])
    order = []
    while q:
        n = q.popleft(); order.append(n)
        for m in edges.get(n, []):
            indeg[m] -= 1
            if indeg[m] == 0: q.append(m)
    if len(order) != len(allnodes):
        cyc = sorted(set(allnodes) - set(order))
        raise Diag("SC-070", "cycle: " + ", ".join(cyc))

    program, nodes, models = [], [], []
    for name, f in facts.items():
        nodes.append(T("node", name=name, kind="source", out=f["type"]))
    for rname, r in rules.items():
        argt = T("vec", items=[T("port", name=a, type=t) for a, t in r["args"]])
        nodes.append(T("node", name=rname, kind="compute",
                       args=argt, out=r["type"],
                       domain=r["domain"]))
    def fmt_port(pt):
        return pt[0] if pt[1] is None else pt[0] + "." + pt[1]
    def emit_wire(w):
        dn, df = w["dst"]
        dty = port_type(dn, df)
        lossy = False
        if w["lit"] is not None:
            lty = lit_type(w["lit"])
            lossy = check_conv(lty, dty, w["lit"])
            src_term = T("lit", value=canon_scalar(w["lit"]), type=lty)
        else:
            sn, sf = w["src"]
            sty = port_type(sn, sf)
            lossy = check_conv(sty, dty, None)
            src_term = fmt_port((sn, sf))
        mode = w["mode"] or "copy"
        program.append(T("wire", dst=fmt_port((dn, df)),
                         src=src_term, mode=mode, lossy=lossy))
    emitted = set()
    for node in order:
        if node in facts:
            program.append(T("source", name=node,
                             type=facts[node]["type"]))
            continue
        r = rules[node]
        for w in wires:
            if w["dst"][0] == node and id(w) not in emitted:
                emit_wire(w); emitted.add(id(w))
        if r["binding"] is not None:
            rt, art = r["binding"]
            args = [node + "." + an for an, _ in r["args"]]
            program.append(T("call_node", name=node, runtime=rt,
                             artifact=art, args=args))
            models.append(T("model", name=node, runtime=rt, artifact=art))
        else:
            outname = node + ".out"
            program.append(T("let", name=outname, body=r["body"],
                             next=T("var", name=outname)))
    for w in wires:  # sinks and unknown sources -> errors here
        if id(w) not in emitted:
            emit_wire(w)
    for it in impls:
        models.append(T("model", name=it["name"],
                        runtime=it["runtime"], artifact=it["artifact"]))
    return Book({"program": program, "models": models, "nodes": nodes,
                 "journal": [], "golden": []})

# ---------- Battery T20-T27 ----------
def run_battery():
    results = []
    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    # Pin
    check("pin: canon 3.0 == 0x1.8000000000000p+1",
          canon_float(3.0) == "0x1.8000000000000p+1")

    DEMO = """spec Demo {
  // canonical comment
  fact A -> Matrix[F64, 2, 2];   # inherited form
  fact k -> Float64;

  rule scale(x: Matrix[F64, 2, 2]) -> Matrix[F64, 2, 2]
    domain strict
    in octave: "feat.m:scale";

  rule double(v: Float64) -> Float64 = v * 2.0;

  rule mix(a: Float64, b: Float64) -> Float64
    requires a <= b
    in python: "mix.py:mix";

  wire double.v = k.out;
  wire scale.x = A.out;
  wire mix.a = double.out;
  wire mix.b = k.out;
}
"""
    # T20: parsing of the full spec
    try:
        sp = parse_spec(DEMO)
        facts = [i for i in sp["items"] if i["kind"] == "fact"]
        rules = [i for i in sp["items"] if i["kind"] == "rule"]
        wires = [i for i in sp["items"] if i["kind"] == "wire"]
        scale = next(r for r in rules if r["name"] == "scale")
        double = next(r for r in rules if r["name"] == "double")
        mix = next(r for r in rules if r["name"] == "mix")
        ok20 = (sp["name"] == "Demo" and len(facts) == 2 and
                len(rules) == 3 and len(wires) == 4 and
                scale["domain"] == "strict" and
                scale["binding"] == ("octave", "feat.m:scale") and
                double["body"] is not None and
                len(mix["requires"]) == 1)
        check("T20: full spec parse (2 facts, 3 rules, 4 wires, mods)", ok20)
    except Exception as e:
        check("T20: full spec parse", False, repr(e)); sp = None

    # T21: compilation
    try:
        book = compile_spec(sp)
        ok_counts = all(book.counts[s] == len(book.blocks[s]) for s in SECTIONS)
        prg = book.blocks["program"]
        calls = [t for t in prg if isinstance(t, dict) and t.get("h") == "call_node"]
        ok21 = (ok_counts and len(calls) == 2 and
                calls[0]["f"]["name"] == "scale" and
                calls[0]["f"]["args"] == ["scale.x"] and
                len(book.blocks["models"]) == 2 and
                len(book.blocks["nodes"]) == 5)
        check("T21: compile -> counts consistent, terms in place", ok21)
    except Exception as e:
        check("T21: compile", False, repr(e)); book = None

    # T22: determinism
    try:
        s1 = book.serialize()
        s2 = compile_spec(parse_spec(DEMO)).serialize()
        check("T22: two compiles byte-identical", s1 == s2)
    except Exception as e:
        check("T22: determinism", False, repr(e)); s1 = None

    # T23: roundtrip
    try:
        header, blocks = load_book_text(s1)
        ok_eq = all(struct_eq(a, b) for a, b in
                    zip(blocks["program"], book.blocks["program"])) \
                and len(blocks["program"]) == len(book.blocks["program"])
        re_ser = serialize_book(header["counts"], blocks)
        check("T23: file -> load -> struct_eq; reserialize byte-identical",
              ok_eq and re_ser == s1)
    except Exception as e:
        check("T23: roundtrip", False, repr(e))

    def expect_diag(code, src):
        try:
            compile_spec(parse_spec(src))
        except Diag as d:
            return d.code == code
        except Exception:
            return False
        return False

    # T24: SC-001
    N24 = """spec N1 {
  fact A -> Float64;
  rule f(x: Float64) -> Float64;
  wire f.x = A.out;
}"""
    check("T24: SC-001 UnboundRule", expect_diag("SC-001", N24))

    # T25: SC-002 + SC-098
    N25a = """spec N2 {
  fact A -> Float64;
  wire w = ghost.out;
}"""
    ok25 = expect_diag("SC-002", N25a)
    try:
        parse_spec("spec D { fact A -> Float64; } stray")
        ok098 = False
    except Diag as d:
        ok098 = d.code == "SC-098"
    except Exception:
        ok098 = False
    check("T25: SC-002 UnknownName + SC-098 TrailingTokens", ok25 and ok098)

    # T26: forbidden conversions and literal limits
    N26a = """spec N3 {
  fact A -> Float64;
  rule f(x: Int64) -> Int64 in python: "f.py:f";
  wire f.x = A.out;
}"""
    N26b = """spec N4 {
  rule g(x: Int64) -> Int64 in python: "g.py:g";
  wire g.x = 3.5;
}"""
    N26c = """spec N5 {
  rule g(x: Int64) -> Int64 in python: "g.py:g";
  wire g.x = 9007199254740993;
}"""
    N26d = """spec N6 {
  fact B -> Bool;
  rule g(x: Float64) -> Float64 in python: "g.py:g";
  wire g.x = B.out;
}"""
    ok26 = (expect_diag("SC-040", N26a) and expect_diag("SC-040", N26b) and
            expect_diag("IntRangeOverflow", N26c) and
            expect_diag("UndefinedBridge", N26d))
    check("T26: SC-040 F64->I64, fractional literal, 2^53, UndefinedBridge", ok26)

    # T27: cycle
    N27 = """spec N7 {
  rule r1(x: Float64) -> Float64 = x + 1.0;
  rule r2(y: Float64) -> Float64 = y * 2.0;
  wire r1.x = r2.out;
  wire r2.y = r1.out;
}"""
    check("T27: SC-070 CycleOrOccurs", expect_diag("SC-070", N27))

    print("{:<62} {:<6}".format("TEST", "RES"))
    print("-" * 70)
    for name, ok, det in results:
        print("{:<62} {:<6} {}".format(name, "PASS" if ok else "FAIL", det))
    failed = sum(1 for _, ok, _ in results if not ok)
    print("-" * 70)
    print("TOTAL: {}, FAILED: {}".format(len(results), failed))
    return len(results), failed

if __name__ == "__main__":
    run_battery()
