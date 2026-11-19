// Ops.java
public final class Ops {

    private Ops() {}

    // --- Помощники: float-приоритет через widen ---

    static boolean isNum(SoundValue v) {
        return v.type == SoundValue.Type.INT || v.type == SoundValue.Type.FLOAT;
    }

    static SoundValue widen(SoundValue v) {
        if (v.type == SoundValue.Type.INT) return SoundValue.floatOf((double) v.i);
        return v;
    }

    static double numOf(SoundValue v) {
        return v.type == SoundValue.Type.INT ? (double) v.i : v.f;
    }

    // --- Арифметика: int+int -> int; иначе widen в F64. Ошибки протекают. ---

    public static SoundValue add(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (isNum(a) && isNum(b)) {
            if (a.type == SoundValue.Type.INT && b.type == SoundValue.Type.INT)
                return SoundValue.intOf(a.i + b.i);      // см. отклонение D-J1
            a = widen(a); b = widen(b);
            return SoundValue.floatOf(a.f + b.f);
        }
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue sub(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (isNum(a) && isNum(b)) {
            if (a.type == SoundValue.Type.INT && b.type == SoundValue.Type.INT)
                return SoundValue.intOf(a.i - b.i);
            a = widen(a); b = widen(b);
            return SoundValue.floatOf(a.f - b.f);
        }
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue mul(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (isNum(a) && isNum(b)) {
            if (a.type == SoundValue.Type.INT && b.type == SoundValue.Type.INT)
                return SoundValue.intOf(a.i * b.i);
            a = widen(a); b = widen(b);
            return SoundValue.floatOf(a.f * b.f);
        }
        return SoundValue.errOf("TypeMismatch");
    }

    /** Деление: всегда float; деление на ноль — IEEE (inf/-inf/nan). */
    public static SoundValue div(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (isNum(a) && isNum(b)) {
            double av = numOf(a), bv = numOf(b);
            if (bv == 0.0) {
                if (av > 0) return SoundValue.floatOf(Double.POSITIVE_INFINITY);
                if (av < 0) return SoundValue.floatOf(Double.NEGATIVE_INFINITY);
                return SoundValue.floatOf(Double.NaN);
            }
            return SoundValue.floatOf(av / bv);
        }
        return SoundValue.errOf("TypeMismatch");
    }

    // --- Сравнения и логика ---

    public static SoundValue eq(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (a.type != b.type) return SoundValue.boolOf(false);
        switch (a.type) {
            case INT:   return SoundValue.boolOf(a.i == b.i);
            case FLOAT: return SoundValue.boolOf(a.f == b.f);
            case BOOL:  return SoundValue.boolOf(a.b == b.b);
            default:    return SoundValue.errOf("TypeMismatch");
        }
    }

    public static SoundValue lt(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (isNum(a) && isNum(b)) return SoundValue.boolOf(numOf(a) < numOf(b));
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue le(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (isNum(a) && isNum(b)) return SoundValue.boolOf(numOf(a) <= numOf(b));
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue and(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (a.type == SoundValue.Type.BOOL && b.type == SoundValue.Type.BOOL)
            return SoundValue.boolOf(a.b && b.b);
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue or(SoundValue a, SoundValue b) {
        if (a.isErr()) return a;
        if (b.isErr()) return b;
        if (a.type == SoundValue.Type.BOOL && b.type == SoundValue.Type.BOOL)
            return SoundValue.boolOf(a.b || b.b);
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue not(SoundValue a) {
        if (a.isErr()) return a;
        if (a.type == SoundValue.Type.BOOL) return SoundValue.boolOf(!a.b);
        return SoundValue.errOf("TypeMismatch");
    }

    // --- Коэрсии ---

    public static SoundValue widenCoerce(SoundValue v) {
        if (v.isErr()) return v;
        if (v.type == SoundValue.Type.INT)   return SoundValue.floatOf((double) v.i);
        if (v.type == SoundValue.Type.FLOAT) return v;
        return SoundValue.errOf("TypeMismatch");
    }

    public static SoundValue narrowCoerce(SoundValue v) {
        if (v.isErr()) return v;
        if (v.type != SoundValue.Type.FLOAT) return SoundValue.errOf("TypeMismatch");
        if (v.f != Math.rint(v.f))           return SoundValue.errOf("PrecisionLoss");
        // отклонение D-J1: целые неограниченны в эталоне, здесь — long
        if (v.f > Long.MAX_VALUE || v.f < Long.MIN_VALUE)
            return SoundValue.errOf("PrecisionLoss");
        return SoundValue.intOf((long) v.f);
    }

    // --- Применение и select: чистые, без trace ---

    public static SoundValue apply(SoundValue f, SoundValue arg) {
        if (f.isErr()) return f;
        if (f.type != SoundValue.Type.CLOSURE)
            return SoundValue.errOf("ApplyOnNonClosure");
        return f.clo.apply(arg);
    }

    public static SoundValue select(SoundValue c, SoundValue t, SoundValue e) {
        if (c.isErr()) return c;
        if (c.type != SoundValue.Type.BOOL)
            return SoundValue.errOf("SelectOnNonBool");
        return c.b ? t : e;
    }

    // --- Окружение: односвязный список пар (имя, значение) ---

    public static final class Env {
        final String name;
        final SoundValue val;
        final Env next;
        public Env(String name, SoundValue val, Env next) {
            this.name = name; this.val = val; this.next = next;
        }
        public static SoundValue get(Env e, String name) {
            for (; e != null; e = e.next)
                if (e.name.equals(name)) return e.val;
            return SoundValue.errOf("UndefinedVariable");
        }
    }

    // --- Замыкание: снимок окружения на момент создания + функция ---

    public interface SoundFn {
        SoundValue apply(Env captured, SoundValue arg);
    }

    public static final class Closure {
        final Env env;      // лексический захват: снимок на момент создания
        final SoundFn fn;
        public Closure(Env env, SoundFn fn) { this.env = env; this.fn = fn; }
        public SoundValue apply(SoundValue arg) { return fn.apply(env, arg); }
    }

    // --- Reduce: явный аккумулятор, шаги видимы в журнале ---

    public static SoundValue reduce(SoundValue vec, SoundValue acc, SoundValue step) {
        if (vec.isErr()) return vec;
        if (acc.isErr()) return acc;
        SoundValue a = acc;
        for (double x : vec.vec) {
            a = apply(step, SoundValue.floatOf(x));
            if (a.isErr()) return a;
        }
        return a;
    }
}
