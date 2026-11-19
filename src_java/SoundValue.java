// SoundValue.java
import java.util.List;
import java.util.ArrayList;

public final class SoundValue {

    public enum Type { INT, FLOAT, BOOL, VEC, CLOSURE, ERR }

    public final Type type;
    public final long i;            // INT: см. пометку об отклонении D-J1 ниже
    public final double f;          // FLOAT: единственный плавающий тип, IEEE-754 F64
    public final boolean b;
    public final double[] vec;      // VEC: память принадлежит кодогенератору
    public final Closure clo;
    public final String err;        // ERR: статический литерал из сгенерированного кода

    private SoundValue(Type t, long i, double f, boolean b, double[] vec,
                       Closure clo, String err) {
        this.type = t; this.i = i; this.f = f; this.b = b;
        this.vec = vec; this.clo = clo; this.err = err;
    }

    public static SoundValue intOf(long x)     { return new SoundValue(Type.INT, x, 0, false, null, null, null); }
    public static SoundValue floatOf(double x) { return new SoundValue(Type.FLOAT, 0, x, false, null, null, null); }
    public static SoundValue boolOf(boolean x) { return new SoundValue(Type.BOOL, 0, 0, x, null, null, null); }
    public static SoundValue vecOf(double[] d) { return new SoundValue(Type.VEC, 0, 0, false, d, null, null); }
    public static SoundValue of(Closure c)     { return new SoundValue(Type.CLOSURE, 0, 0, false, null, c, null); }
    public static SoundValue errOf(String code){ return new SoundValue(Type.ERR, 0, 0, false, null, null, code); }

    public boolean isErr() { return type == Type.ERR; }

    /** Контракт 7.1: побитовый эквивалент float.hex() из CPython. */
    public static String fmtHexDouble(double x) {
        if (Double.isNaN(x)) return "nan";
        if (Double.isInfinite(x)) return x > 0 ? "inf" : "-inf";
        long bits = Double.doubleToRawLongBits(x);
        boolean neg = bits < 0;
        int exp = (int)((bits >>> 52) & 0x7FF);
        long mant = bits & 0xFFFFFFFFFFFFFL;           // ровно 52 бита: 13 hex-цифр

        if (x == 0.0) return neg ? "-0x0.0p+0" : "0x0.0p+0";
        if (exp == 0) {
            // субнормаль: 0x0.<13 цифр>p-1022, БЕЗ перенормировки (как в float.hex())
            return (neg ? "-" : "") + "0x0." + pad13(mant) + "p-1022";
        }
        exp -= 1023;
        return (neg ? "-" : "") + "0x1." + pad13(mant)
             + "p" + (exp >= 0 ? "+" : "") + exp;
    }

    private static String pad13(long mant) {
        return String.format("%013x", mant);
    }

    /** Каноническая сериализация значения (для журнала). */
    public String canon() {
        switch (type) {
            case INT:     return Long.toString(i);
            case FLOAT:   return fmtHexDouble(f);
            case BOOL:    return b ? "true" : "false";
            case VEC: {
                StringBuilder sb = new StringBuilder("[");
                for (int k = 0; k < vec.length; k++) {
                    if (k > 0) sb.append(',');
                    sb.append(fmtHexDouble(vec[k]));
                }
                return sb.append(']').toString();
            }
            case CLOSURE: return "<closure>";
            case ERR:     return "Err(" + err + ")";
            default:      return "?";
        }
    }

    /** Контракт 7.2: bind-событие; при значении Err — ещё и err-событие. */
    public static final class Trace {
        public static void bind(String name, SoundValue v) {
            System.out.println("bind " + name + " " + v.canon());
            if (v.isErr())
                System.out.println("err " + name + " Err(" + v.err + ")");
        }
        public static void result(SoundValue v) {
            System.out.println("result " + v.canon());
        }
        public static void flush() {
            System.out.flush();
        }
    }
}
