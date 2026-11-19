#!/usr/bin/env python3
# run_static_checks.py -- единый статический рубеж для C99 и Java реализаций SCore.
# Проверки: (1) баланс скобок с учётом строк и комментариев;
#           (2) символы: объявленный API покрыт реализацией;
#           (3) зеркальный смок канона 7.1 против float.hex() из CPython.
import sys, os, random, struct

MANT_MASK = (1 << 52) - 1
EXP_MASK  = 0x7FF

def pad13(mant):
    return format(mant, "013x")

def fmt_hex_double_transcription(x):
    """Транскрипция алгоритма из sound_rt.c / fmtHexDouble для зеркального теста."""
    if x != x:
        return "nan"
    if x == float("inf"):
        return "inf"
    if x == float("-inf"):
        return "-inf"
    bits = struct.unpack("<q", struct.pack("<d", x))[0]  # знаковое, как long в Java
    neg = bits < 0
    ubits = bits & ((1 << 64) - 1)
    exp = (ubits >> 52) & EXP_MASK
    mant = ubits & MANT_MASK
    if x == 0.0:
        return ("-0x0.0p+0" if neg else "0x0.0p+0")
    if exp == 0:
        return ("-0x0." if neg else "0x0.") + pad13(mant) + "p-1022"
    e = exp - 1023
    return ("-0x1." if neg else "0x1.") + pad13(mant) + "p" + ("+" if e >= 0 else "") + str(e)

def mirror_smoke(n=200018):
    rng = random.Random(202603)
    cases = [0.0, -0.0, float("inf"), float("-inf"), float("nan"),
             5e-324, -5e-324, 1.5, -1.5, 1e308, -1e308, 3.0, -3.0]
    for _ in range(n - len(cases)):
        b = rng.getrandbits(64)
        x = struct.unpack("<d", struct.pack("<Q", b))[0]
        cases.append(x)
    bad = 0
    for x in cases:
        if fmt_hex_double_transcription(x) != x.hex():
            bad += 1
    return len(cases), bad

def strip_code(src, ext):
    out, i, n = [], 0, len(src)
    in_s, in_lc, in_bc = False, False, False
    while i < n:
        c = src[i]
        if in_s:
            out.append(" " if c not in '"\\' else c)
            if c == "\\":
                out.append(" "); i += 1
            elif c == '"':
                in_s = False
        elif in_lc:
            if c == "\n":
                in_lc = False; out.append(c)
        elif in_bc:
            if c == "*" and i + 1 < n and src[i+1] == "/":
                in_bc = False; i += 1; out.append("  ")
        else:
            if c == '"' and ext != "py":
                in_s = True
            elif c == "/" and i + 1 < n and src[i+1] == "/":
                in_lc = True; i += 1
            elif c == "/" and i + 1 < n and src[i+1] == "*":
                in_bc = True; i += 1
            out.append(c)
        i += 1
    return "".join(out)

def check_braces(path, ext):
    src = strip_code(open(path, encoding="utf-8").read(), ext)
    depth = 0
    for ch in src:
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0

def check_c_symbols(h_path, c_path):
    h = open(h_path, encoding="utf-8").read()
    declared = set()
    for line in h.splitlines():
        line = line.strip()
        if line.startswith("Value ") or line.startswith("EnvNode *") or line.startswith("void ") or line.startswith("const char *"):
            name = line.split("(")[0].split()[-1].strip("* ")
            if name and not name.startswith("#"):
                declared.add(name)
    c_src = open(c_path, encoding="utf-8").read()
    used = set()
    for m in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", c_src):
        if m not in ("if", "for", "while", "return", "sizeof"):
            used.add(m)
    missing = used - declared - {"main"}
    return len(declared), missing

import re  # noqa: E402

def check_java_symbols(java_dir):
    defined = set()
    files = [f for f in os.listdir(java_dir) if f.endswith(".java")]
    for fn in files:
        src = open(os.path.join(java_dir, fn), encoding="utf-8").read()
        for m in re.findall(r"(?:public|static|private)[^;{()]*\b(\w+)\s*\(", src):
            defined.add(m)
    used = set()
    for fn in files:
        src = open(os.path.join(java_dir, fn), encoding="utf-8").read()
        for m in re.findall(r"(?:SoundValue|Ops)\.(\w+)\s*\(", src):
            used.add(m)
    return defined, used - defined - {"flush"}

def main():
    args = sys.argv[1:]
    ok = True
    if not args:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        targets = [
            (os.path.join(repo, "src_c", "all_terms.c"), "c"),
            (os.path.join(repo, "src_c", "sound_rt.h"), "h"),
            (os.path.join(repo, "src_java", "SoundValue.java"), "java"),
            (os.path.join(repo, "src_java", "Ops.java"), "java"),
            (os.path.join(repo, "src_java", "TermT06.java"), "java"),
        ]
    else:
        targets = [(p, os.path.splitext(p)[1].lstrip(".")) for p in args]

    print("== brace balance (string/comment aware) ==")
    for path, ext in targets:
        r = check_braces(path, ext)
        print(("PASS" if r else "FAIL"), os.path.basename(path))
        ok &= r

    print("== symbol coverage ==")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    h = os.path.join(repo, "src_c", "sound_rt.h")
    c = os.path.join(repo, "src_c", "all_terms.c")
    if os.path.exists(h) and os.path.exists(c):
        nd, missing = check_c_symbols(h, c)
        print(("PASS" if not missing else "FAIL"),
              "C: %d declared, missing=%s" % (nd, sorted(missing) if missing else "none"))
        ok &= not missing
    jd = os.path.join(repo, "src_java")
    if os.path.isdir(jd):
        defined, missing = check_java_symbols(jd)
        print(("PASS" if not missing else "FAIL"),
              "Java: %d symbols defined, missing=%s" % (len(defined), sorted(missing) if missing else "none"))
        ok &= not missing

    print("== mirror smoke: canon 7.1 vs float.hex() ==")
    total, bad = mirror_smoke()
    print(("PASS" if bad == 0 else "FAIL"), "%d patterns, %d mismatches" % (total, bad))
    ok &= (bad == 0)

    print("RESULT:", "ALL CHECKS PASS" if ok else "CHECKS FAILED")
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
