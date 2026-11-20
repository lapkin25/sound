# sound_reader.py -- TRIOBOOK1 reader: deterministic render + score.
# Battery T-RD: 8 checks. Run: python3 sound_reader.py

import json
import math
import struct
import wave
import io

# ---------- Diagnostics ----------
class BadFormat(Exception): pass

# ---------- STRUCT terms (canonical form, as in the frontend) ----------
def T(head, **f):
    return {"h": head, "f": f}

def canon_float(x):
    return float(x).hex()

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
    toks = term_tokens(s.strip())
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

# ---------- Book loading (nested blocks with depth counting) ----------
SECTIONS = ["program", "models", "nodes", "journal", "golden"]

def load_book(text):
    lines = text.splitlines()
    if not lines: raise BadFormat("empty book")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as e:
        raise BadFormat("header is not JSON: " + str(e))
    if header.get("format") != "TRIOBOOK1": raise BadFormat("bad magic")
    if list(header.get("sections", [])) != SECTIONS: raise BadFormat("bad sections")
    counts = header.get("counts")
    if not isinstance(counts, dict): raise BadFormat("no counts")
    blocks = {s: [] for s in SECTIONS}
    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1; continue
        if not line.startswith("@begin "): raise BadFormat("expected @begin")
        name = line[len("@begin "):].strip()
        if name not in SECTIONS: raise BadFormat("unknown section " + name)
        i += 1; depth = 1
        while i < len(lines) and depth > 0:
            l = lines[i].strip()
            if l.startswith("@begin "):
                depth += 1
            elif l.startswith("@end"):
                depth -= 1
                if depth == 0: break
            if l: blocks[name].append(block_line_to_term(l))
            i += 1
        if depth != 0: raise BadFormat("unclosed section " + name)
        i += 1
    for s in SECTIONS:
        if counts.get(s, None) != len(blocks[s]):
            raise BadFormat("counts mismatch in " + s)
    return header, blocks

def block_line_to_term(line):
    line = line.strip()
    if not line: raise BadFormat("empty block line")
    return parse_term_text(line)

def serialize_book(header, blocks):
    out = json.dumps({"format": header["format"], "version": header["version"],
                      "sections": header["sections"], "counts": header["counts"]},
                     ensure_ascii=False, separators=(",", ":"))
    for s in header["sections"]:
        out += "\n@begin " + s + "\n"
        for v in blocks.get(s, []):
            out += ser_val(v) + "\n"
        out += "@end " + s + "\n"
    return out

# ---------- Golden ----------
def golden_marks(journal, golden):
    marks = []
    for line in journal:
        if isinstance(line, str) and line.startswith("OUT"):
            mark = "OK" if line in golden else "FAIL"
            marks.append((line, mark))
    return marks

# ---------- Deterministic render ----------
def render(header, blocks):
    out = []
    out.append("# TRIOBOOK1 view (deterministic render)")
    out.append("")
    out.append("format: TRIOBOOK1 v" + str(header["version"]) +
               "; sections: " + ", ".join(header["sections"]))
    out.append("")
    for s in ["program", "models", "nodes"]:
        out.append("## " + s.capitalize())
        for i, t in enumerate(blocks[s], 1):
            out.append("{:3d}  {}".format(i, ser_val(t)))
        out.append("")
    out.append("## Journal")
    marks = golden_marks(blocks["journal"], blocks["golden"])
    mi = 0
    score = build_score(blocks["journal"])
    for i, line in enumerate(blocks["journal"], 1):
        if isinstance(line, str) and line.startswith("OUT"):
            line_text, mark = marks[mi]; mi += 1
            if mark == "OK":
                out.append("{:3d}  {:<48} [OK] golden".format(i, line))
            else:
                g = golden_value(line, blocks["golden"])
                out.append("{:3d}  {:<48} [FAIL] golden: {}".format(i, line, g))
        elif isinstance(line, str):
            note = annotate(line, score)
            out.append("{:3d}  {:<48} {}".format(i, line, note))
        else:
            out.append("{:3d}  {}".format(i, ser_val(line)))
    out.append("")
    out.append("## Golden")
    for i, g in enumerate(blocks["golden"], 1):
        out.append("{:3d}  {}".format(i, ser_val(g)))
    return "\n".join(out) + "\n"

def golden_value(out_line, golden):
    for g in golden:
        if isinstance(g, str) and g.startswith("OUT ") and \
           g.split()[1] == out_line.split()[1]:
            return g.split(None, 2)[2] if len(g.split(None, 2)) > 2 else ""
    return "not found"

def annotate(line, score):
    for ev in score:
        if ev.get("line") == line:
            if ev["kind"] == "start":
                return "<- " + ev["note"]
            if ev["kind"] == "end":
                return "<- " + ev["note"] + " (fifth)"
            if ev["kind"] == "edge":
                return "<- damping 6 dB" if ev.get("lossy") else ""
            if ev["kind"] == "err":
                return "<- tritone/minor second"
            if ev["kind"] == "chord":
                return "<- final consonance"
    return ""
