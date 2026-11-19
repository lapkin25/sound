# gen_java.py -- эскиз генератора ANF -> Java.
# Полная версия добавляет все узлы ANF и контр-стабилизацию имён повторных let.
# Терм T06 в архиве сгенерирован по этой схеме вручную (TermT06.java).

def sanitize(name: str) -> str:
    s = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)
    if not (s[0].isalpha() or s[0] == "_"):
        s = "_" + s
    return s

# rhs: ("int", k) | ("float", hexlit) | ("var", name) | ("op", "+", a, b)
#      | ("app", f, x) | ("if", c, t, e)

def emit_rhs(rhs):
    tag = rhs[0]
    if tag == "int":    return "SoundValue.intOf(%d)" % rhs[1]
    if tag == "float":  return "SoundValue.floatOf(%s)" % rhs[1]  # hex-литерал вида 0x1.8p1
    if tag == "var":    return 'Ops.Env.get(env, "%s")' % sanitize(rhs[1])
    if tag == "op":
        fn = {"+": "add", "-": "sub", "*": "mul", "/": "div",
              "==": "eq", "<": "lt", "<=": "le",
              "and": "and", "or": "or"}[rhs[1]]
        return "Ops.%s(%s, %s)" % (fn, emit_rhs(rhs[2]), emit_rhs(rhs[3]))
    if tag == "app":    return "Ops.apply(%s, %s)" % (emit_rhs(rhs[1]), emit_rhs(rhs[2]))
    if tag == "if":     return "Ops.select(%s, %s, %s)" % (emit_rhs(rhs[1]), emit_rhs(rhs[2]), emit_rhs(rhs[3]))
    raise ValueError("node %s not covered in sketch" % tag)

def generate_terms(terms):
    java = ["// TermAll.java -- автогенерированный файл.",
            "public final class TermAll {"]
    for name, ast in terms.items():
        java.append("    public static SoundValue term_%s() {" % name)
        java.append("        Ops.Env env0 = null;")
        java.append("        /* TODO: полная эмиссия ANF -- см. комментарий выше */")
        java.append("    }")
    java += ["    public static void main(String[] args) {",
             "        SoundValue.Trace.flush();",
             "    }", "}"]
    return "\n".join(java)
