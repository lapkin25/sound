# sheet_meta.py — метаданные табличного слоя Sound (v0.3 «Sheet»)
# Схема ячейки: type, unit, role, invariant, display, label, provenance.
# Деревья формул — фикстурный формат этапа 2, право-ассоциативные (J01/J05).
# Валидация: SM-001 unknown, SM-003 unit mismatch, SM-004 inv name,
#            SM-005 role violation, SM-006 missing value (SM-002 — резерв типа).
# Литеральный 0 совместим с любой единицей (как s >= 0 в эталоне).
import json, math, re, shlex
from dataclasses import dataclass

BASE = ("m", "s", "kg", "A", "K")
ZERO_DIM = (0, 0, 0, 0, 0)

def parse_unit(s):
    if s in ("-", "", "1"): return ZERO_DIM
    num, den, state = [0]*5, [0]*5, True
    for tok in re.split(r'([*/])', s):
        tok = tok.strip()
        if tok == '/': state = False
        elif tok == '*': pass
        elif tok:
            m = re.match(r'^([a-zA-Z]+)(?:\^(-?\d+))?$', tok)
            if not m: raise ValueError(f"bad unit token: {tok!r}")
            base, power = m.group(1), int(m.group(2) or 1)
            if base not in BASE: raise ValueError(f"unknown unit base: {base}")
            (num if state else den)[BASE.index(base)] += power
    return tuple(n - d for n, d in zip(num, den))

def unit_str(u):
    pos = [f"{b}^{n}" if n != 1 else b for b, n in zip(BASE, u) if n > 0]
    neg = [f"{b}^{-n}" if n != -1 else b for b, n in zip(BASE, u) if n < 0]
    if not pos and not neg: return "1"
    s = "*".join(pos) if pos else "1"
    if neg: s += "/" + "*".join(neg)
    return s

TOK_RE = re.compile(r'\s*(\d+\.\d+|\.\d+|\d+|[A-Za-z_][A-Za-z0-9_]*|[+\-*/()])')

def tokenize(expr):
    toks, i = [], 0
    while i < len(expr):
        m = TOK_RE.match(expr, i)
        if not m:
            if expr[i:].strip() == '': break
            raise ValueError(f"bad token at {expr[i:]!r}")
        toks.append(m.group(1)); i = m.end()
    return toks

class ExprParser:
    """Рекурсивный спуск; все бинарные операции правые — как в эталоне."""
    def __init__(self, toks): self.toks, self.i = toks, 0
    def peek(self): return self.toks[self.i] if self.i < len(self.toks) else None
    def next(self): t = self.peek(); self.i += 1; return t
    def parse(self):
        e = self.add()
        if self.peek() is not None:
            raise ValueError(f"trailing tokens: {self.toks[self.i:]}")
        return e
    def add(self):
        e = self.mul()
        while self.peek() in ('+', '-'):
            e = [self.next(), e, self.add()]
        return e
    def mul(self):
        e = self.unary()
        while self.peek() in ('*', '/'):
            e = [self.next(), e, self.mul()]
        return e
    def unary(self):
        if self.peek() == '-':
            self.next(); return ['neg', self.unary()]
        return self.atom()
    def atom(self):
        t = self.next()
        if t is None: raise ValueError("unexpected end of expression")
        if t == '(':
            e = self.add()
            if self.next() != ')': raise ValueError("missing ')'")
            return e
        if re.match(r'^[.\d]', t): return float(t)
        if re.match(r'^[A-Za-z_]', t): return t
        raise ValueError(f"unexpected token {t!r}")

def parse_expr(expr):
    return ExprParser(tokenize(expr)).parse()

def collect_names(tree, acc):
    if isinstance(tree, str): acc.add(tree)
    elif isinstance(tree, list):
        if tree[0] == 'neg': collect_names(tree[1], acc)
        else:
            collect_names(tree[1], acc); collect_names(tree[2], acc)
    return acc

@dataclass
class Column:
    name: str
    type: str = "Float64"
    unit: tuple = ZERO_DIM
    unit_src: str = "1"
    role: str = "input"          # input | computed | const
    label: str = ""
    display: str = ""
    value: float = None
    provenance: str = "user"
    formula: object = None
    formula_src: str = ""
    invariant: object = None     # (op, lhs_name|float, rhs_name|float)
    invariant_src: str = ""

class Sheet:
    def __init__(self, name):
        self.name = name
        self.meta = {"title": name, "version": 1}
        self.cols = {}
    def col(self, name, type="Float64", unit="1", role="input", label="", display=""):
        self.cols[name] = Column(name, type, parse_unit(unit), unit, role, label, display)
        return self
    def set(self, name, value):
        self.cols[name].value = float(value); return self
    def formula(self, name, expr):
        self.cols[name].formula_src = expr
        self.cols[name].formula = parse_expr(expr)
        self.cols[name].provenance = "derived:" + expr
        return self
    def invariant(self, name, op, rhs):
        c = self.cols[name]
        rtree = parse_expr(rhs)
        if isinstance(rtree, list) and len(rtree) == 1 and isinstance(rtree[0], str):
            rtree = rtree[0]
        c.invariant = (op, c.name, rtree)
        c.invariant_src = f"{c.name} {op} {rhs}"
        return self

    def validate(self):
        errs = []
        for c in self.cols.values():
            if c.role in ("input", "const") and c.value is None and c.formula is None:
                errs.append(f"SM-006: no value for {c.role} column {c.name}")
            if c.formula is not None and c.role != "computed":
                errs.append(f"SM-005: formula on {c.role} column {c.name}")
            if c.formula is None and c.role == "computed":
                errs.append(f"SM-005: no formula for computed column {c.name}")
            if c.invariant is not None:
                op, lhs, rhs = c.invariant
                unknown = [n for t in (lhs, rhs)
                           for n in collect_names(t, set()) if n not in self.cols]
                for n in unknown:
                    errs.append(f"SM-004: unknown name {n} in invariant of {c.name}")
                if not unknown:
                    ld = self._dim(lhs, errs, f"invariant {c.name}")
                    rd = self._dim(rhs, errs, f"invariant {c.name}")
                    if ld is not None and rd is not None and ld != rd:
                        zl = isinstance(lhs, float) and lhs == 0.0
                        zr = isinstance(rhs, float) and rhs == 0.0
                        if not (zl or zr):
                            errs.append(f"SM-003: unit mismatch in invariant of {c.name}: "
                                        f"{unit_str(ld)} vs {unit_str(rd)}")
            if c.formula is not None:
                d = self._dim(c.formula, errs, f"formula {c.name}")
                if d is not None and d != c.unit:
                    errs.append(f"SM-003: {c.name} declared {unit_str(c.unit)}, "
                                f"expression yields {unit_str(d)}")
        return errs

    def _dim(self, tree, errs, ctx):
        n0 = len(errs)
        d = self._dim_raw(tree, errs, ctx)
        return None if len(errs) > n0 else d

    def _dim_raw(self, tree, errs, ctx):
        if isinstance(tree, str):
            if tree in self.cols: return self.cols[tree].unit
            msg = f"SM-001: unknown name {tree} in {ctx}"
            if msg not in errs: errs.append(msg)
            return None
        if isinstance(tree, float): return ZERO_DIM
        op = tree[0]
        if op == 'neg': return self._dim_raw(tree[1], errs, ctx)
        l = self._dim_raw(tree[1], errs, ctx)
        r = self._dim_raw(tree[2], errs, ctx)
        if op in ('+', '-'):
            if l is not None and r is not None and l != r:
                errs.append(f"SM-003: unit mismatch in {ctx}: {unit_str(l)} vs {unit_str(r)}")
            return l if l is not None else r
        if l is None or r is None: return None
        if op == '*': return tuple(a + b for a, b in zip(l, r))
        if op == '/': return tuple(a - b for a, b in zip(l, r))
        return None

    def compile(self):
        errs = self.validate()
        if errs: raise ValueError("sheet has errors: " + "; ".join(errs))
        facts, rules = {}, {}
        for c in self.cols.values():
            if c.role in ("input", "const"): facts[c.name] = c.value
        for c in self.cols.values():
            if c.role != "computed" or c.formula is None: continue
            names = collect_names(c.formula, set())
            params = [n for n in self.cols if n in names]
            rule = {"param": params[0] if params else "unit",
                    "params": params, "tree": c.formula,
                    "param_types": {n: self.cols[n].type for n in params},
                    "ret": c.type}
            if c.invariant is not None:
                rule["inv"] = list(c.invariant)
            rules[c.name] = rule
        return {"format": "sound-sheet-graph-1", "meta": self.meta,
                "facts": facts, "rules": rules}

    def to_spec(self):
        g = self.compile()
        out = [f"spec {self.name}_v{self.meta['version']} {{\n"]
        for n, v in g["facts"].items():
            c = self.cols[n]
            ts = f" : {c.type}" if c.unit_src != "1" else ""
            out.append(f"  fact {n} = {repr(v)}{ts};\n")
        out.append("\n")
        for n, r in g["rules"].items():
            ps = ", ".join(f"{p}: Float64" for p in r["params"])
            inv = f" invariant {self.cols[n].invariant_src}" if self.cols[n].invariant else ""
            out.append(f"  rule {n}({ps}) -> Float64{inv} = {self.cols[n].formula_src};\n")
        out.append("}\n")
        return "".join(out)

    def to_json(self):
        g = self.compile()
        meta_cells = {n: {"type": c.type, "unit": c.unit_src, "role": c.role,
                          "label": c.label, "display": c.display,
                          "provenance": c.provenance,
                          "invariant": c.invariant_src}
                      for n, c in self.cols.items()}
        return json.dumps({"format": "sound-sheet-1", "sheet": self.name,
                           "meta": self.meta, "columns": meta_cells, **g},
                          indent=2, ensure_ascii=False)

def sheet_parse(text):
    sh = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        toks = shlex.split(line)
        kw = toks[0]
        if kw == 'sheet': sh = Sheet(toks[1])
        elif kw == 'meta': sh.meta[toks[1]] = toks[2]
        elif kw == 'col':
            c = sh.col(toks[1], type=toks[2], unit=toks[3], role=toks[4])
            if 'label' in toks: c.label = toks[toks.index('label') + 1]
        elif kw == 'set': sh.set(toks[1], toks[2])
        elif kw == 'formula': sh.formula(toks[1], " ".join(toks[2:]))
        elif kw == 'invariant': sh.invariant(toks[1], toks[2], toks[3])
        elif kw == 'display': sh.cols[toks[1]].display = toks[2]
        else: raise ValueError(f"unknown sheet keyword: {kw}")
    return sh

def canon(x):
    if math.isnan(x): return "nan"
    if math.isinf(x): return "inf" if x > 0 else "-inf"
    return float.hex(x)

def padname(nm, pad): return nm.ljust(pad)

def exec_rule(rule, env):
    """Журнал §3.8. Инвариант на параметр — до тела; на результат колонки — после."""
    pad = max(2, max(len(p) for p in rule["params"]))
    journal = [f"bind {padname(p, pad)} = Float64 {canon(env[p])}" for p in rule["params"]]
    counter = [0]
    def go(t):
        if isinstance(t, str): return env[t]
        if isinstance(t, float): return t
        op = t[0]
        if op == 'neg': v = -go(t[1])
        else:
            l = go(t[1]); r = go(t[2])
            v = {'+': l + r, '-': l - r, '*': l * r, '/': l / r}[op]
        journal.append(f"bind {padname(f't{counter[0]}', pad)} = Float64 {canon(v)}")
        counter[0] += 1
        return v
    def cmp(av, op, bv):
        return {'>=': av >= bv, '<=': av <= bv, '>': av > bv, '<': av < bv,
                '==': av == bv, '!=': av != bv}[op]
    inv = rule.get("inv")
    if inv:
        op, a, b = inv
        if isinstance(a, str) and a in env:
            bv = env[b] if isinstance(b, str) else b
            if not cmp(env[a], op, bv):
                return None, [f"err DomainError {rule.get('name','?')}: invariant"]
    val = go(rule["tree"])
    if inv:
        op, a, b = inv
        if isinstance(a, str) and a not in env:
            bv = env[b] if isinstance(b, str) else b
            if not cmp(val, op, bv):
                return None, journal + [f"err DomainError {rule.get('name','?')}: invariant"]
    journal.append(f"result  = Float64 {canon(val)}")
    return val, journal

def display_value(x, fmt):
    if not fmt: return repr(x)
    n = fmt.split('.')[1].count('#') if '.' in fmt else 0
    return f"{x:.{n}f}"
