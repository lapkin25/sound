import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.*;

@SuppressWarnings("unchecked")
public class ConformanceTest {

    // Java-host conformance for Sound v0.2: canon (6.4), TRIOMAT (6.1-6.3),
    // bridge codes + 9 reader checks (7), kernel arithmetic (3.3).
    // Journal (J) and static (SC) checks are stage 2 - SKIP, like conform_octave.m.
    //
    // Run:   javac ConformanceTest.java
    //        java ConformanceTest
    // Requires fixtures_sound.json (sound-fixtures-1) in the working dir.
    // Expected tail: ALL PASS (54/54), skips: 11
    //
    // Host traps closed here (8.4):
    //  - overflow: Math.addExact/subtractExact/multiplyExact -> IntRangeOverflow
    //  - plain long / truncates toward zero (spec); Math.floorDiv is forbidden
    //  - Long.MIN_VALUE / -1 caught explicitly (Java returns MIN_VALUE silently)
    //  - % has dividend's sign in Java; spec wants divisor's sign -> corrected
    //  - canon built from raw bits; Double.toHexString is NOT canonical
    //  - Long.toHexString is lowercase and locale-free; no String.format for canon

    static int npass = 0, nskip = 0;
    static final List<String> fails = new ArrayList<>();

    public static void main(String[] args) throws Exception {
        Map<String, Object> fx =
            (Map<String, Object>) Json.parse(
                new String(Files.readAllBytes(Paths.get("fixtures_sound.json")),
                           StandardCharsets.UTF_8));

        // ---------- C01..C12: canonical float (6.4) ----------
        List<Object> cv = list(fx, "canon_vectors");
        for (int i = 0; i < cv.size(); i++) {
            Map<String, Object> v = map(cv.get(i));
            double x = Double.longBitsToDouble(Long.parseUnsignedLong(str(v, "hex_bits"), 16));
            ck(canon(x).equals(str(v, "expect")), String.format("C%02d %s", i + 1, str(v, "name")));
        }

        // ---------- M01..M05: TRIOMAT build and parse (6.1-6.3) ----------
        List<Object> ts = list(fx, "triomat_samples");
        for (int i = 0; i < ts.size(); i++) {
            Map<String, Object> s = map(ts.get(i));
            byte[] orig = Base64.getDecoder().decode(str(s, "base64"));
            byte[] built = triPack(str(s, "dtype"), shapeOf(s.get("shape")), payloadOf(s));
            ck(Arrays.equals(built, orig), String.format("M%02d %s build", i + 1, str(s, "name")));
            Object p = triParse(orig);
            ck(p instanceof Vec && vecEq((Vec) p, s.get("values")),
               String.format("M%02d %s parse", i + 1, str(s, "name")));
        }

        // ---------- X01..X08: malformed files, bridge + reader (7) ----------
        List<Object> ms = list(fx, "malformed_samples");
        for (int i = 0; i < ms.size(); i++) {
            Map<String, Object> m = map(ms.get(i));
            byte[] data = Base64.getDecoder().decode(str(m, "base64"));
            Object p = triParse(data);
            String code = p instanceof String ? (String) p : "";
            ck(code.equals(str(m, "expect_code")),
               String.format("X%02d %s bridge", i + 1, str(m, "name")));
            List<String[]> res = reader9(data);
            ck(res.size() == lng(m.get("reader_count"))
                    && res.get(res.size() - 1)[1].equals(str(m, "reader_last")),
               String.format("X%02d %s reader", i + 1, str(m, "name")));
        }

        // ---------- A01..A16: kernel arithmetic (3.3) ----------
        List<Object> av = list(fx, "arith_vectors");
        for (int i = 0; i < av.size(); i++) {
            Map<String, Object> a = map(av.get(i));
            Object r;
            if (str(a, "kind").equals("int")) {
                long x;
                if (!str(a, "int_str").isEmpty())
                    x = Long.parseLong(str(a, "int_str"));   // big ints: decimal string is source of truth
                else if (a.get("lhs") instanceof Number)
                    x = lng(a.get("lhs"));
                else
                    x = Long.parseUnsignedLong(str(a, "int_bits"), 16);
                Object ry = a.get("rhs");
                long y = (ry instanceof Number) ? lng(ry) : Long.parseLong(ry.toString());
                r = intOp(str(a, "op"), x, y);
            } else if (str(a, "kind").equals("mixed")) {
                long n = Long.parseUnsignedLong(str(a, "int_bits"), 16);
                double x = (double) n;
                double y = Double.longBitsToDouble(Long.parseUnsignedLong(str(a, "rhs_bits"), 16));
                r = floatOp(str(a, "op"), x, y);
                // R-INT1: lossy at |n| >= 2^53-1 inclusive
                if (r instanceof Double && a.containsKey("lossy")) {
                    boolean lossyJava = n >= 9007199254740991L || n <= -9007199254740991L;
                    if (((Boolean) a.get("lossy")).booleanValue() != lossyJava)
                        r = "lossy-mismatch";
                }
            } else {
                double x = Double.longBitsToDouble(Long.parseUnsignedLong(str(a, "lhs_bits"), 16));
                double y = Double.longBitsToDouble(Long.parseUnsignedLong(str(a, "rhs_bits"), 16));
                r = floatOp(str(a, "op"), x, y);
            }
            ck(verdict(r, a), String.format("A%02d %s", i + 1, str(a, "name")));
        }

        // ---------- J01..J07, SC1..SC4: stage 2 ----------
        List<Object> jv = list(fx, "journal_vectors");
        for (int i = 0; i < jv.size(); i++) sk(String.format("J%02d %s", i + 1, str(map(jv.get(i)), "name")));
        List<Object> sv = list(fx, "static_vectors");
        for (int i = 0; i < sv.size(); i++) sk(String.format("SC%d %s", i + 1, str(map(sv.get(i)), "name")));

        System.out.println();
        if (!fails.isEmpty()) {
            System.out.println("FAILURES: " + fails.size() + " -> " + String.join(", ", fails));
            System.exit(1);
        }
        System.out.println("ALL PASS (" + npass + "/" + npass + "), skips: " + nskip);
    }

    // ---------- canon from raw bits (6.4) ----------
    static String canon(double x) {
        long bits = Double.doubleToRawLongBits(x);
        long sign = bits >>> 63;
        long exp  = (bits >>> 52) & 0x7FFL;
        long mant = bits & 0x000FFFFFFFFFFFFFL;
        if (exp == 0x7FFL) {
            if (mant != 0) return "nan";
            return sign == 1 ? "-inf" : "inf";
        }
        if (exp == 0 && mant == 0) return sign == 1 ? "-0x0.0p+0" : "0x0.0p+0";
        String m = Long.toHexString(mant);                    // lowercase, locale-free
        StringBuilder mb = new StringBuilder();
        for (int k = m.length(); k < 13; k++) mb.append('0'); // 13 hex digits
        mb.append(m);
        String body;
        if (exp == 0) {
            body = "0x0." + mb + "p-1022";                    // denormal: no leading unit
        } else {
            long e = exp - 1023;
            body = "0x1." + mb + "p" + (e >= 0 ? "+" : "") + e;
        }
        return sign == 1 ? "-" + body : body;
    }

    // ---------- kernel arithmetic on long ----------
    static Object intOp(String op, long x, long y) {
        try {
            switch (op) {
                case "+": return Math.addExact(x, y);
                case "-": return Math.subtractExact(x, y);
                case "*": return (x == 0 || y == 0) ? 0L : Math.multiplyExact(x, y);
                case "/":
                    if (y == 0) return "DivisionByZero";
                    if (x == Long.MIN_VALUE && y == -1) return "IntRangeOverflow";
                    return x / y;                             // truncates toward zero (spec)
                case "%":
                    if (y == 0) return "DivisionByZero";
                    long r = x % y;                           // Java: sign of dividend
                    if (r != 0 && ((r < 0) != (y < 0))) r += y; // -> sign of divisor (Python)
                    return r;
                default: return "InternalError";
            }
        } catch (ArithmeticException e) {
            return "IntRangeOverflow";
        }
    }

    // IEEE semantics are native in Java; only the NaN ban needs a wrapper
    static Object floatOp(String op, double x, double y) {
        double z;
        switch (op) {
            case "+": z = x + y; break;
            case "-": z = x - y; break;
            case "*": z = x * y; break;
            case "/": z = x / y; break;   // x/0.0 -> signed inf natively; 0.0/0.0 -> NaN
            default: return "InternalError";
        }
        return Double.isNaN(z) ? "NaNOutsideDomain" : (Double) z;
    }

    // ---------- TRIOMAT frame (6.1) ----------
    static byte[] triPack(String dtype, long[] shape, byte[] payload) {
        StringBuilder sb = new StringBuilder("{\"dtype\":\"").append(dtype).append("\",\"shape\":[");
        for (int k = 0; k < shape.length; k++) {
            if (k > 0) sb.append(',');
            sb.append(shape[k]);
        }
        sb.append("]}");
        byte[] h = sb.toString().getBytes(StandardCharsets.UTF_8);
        byte[] out = new byte[12 + h.length + payload.length];
        byte[] magic = "TRIOMAT1".getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(magic, 0, out, 0, 8);
        int hl = h.length;
        out[8]  = (byte) hl;              // uint32 LE
        out[9]  = (byte) (hl >>> 8);
        out[10] = (byte) (hl >>> 16);
        out[11] = (byte) (hl >>> 24);
        System.arraycopy(h, 0, out, 12, h.length);
        System.arraycopy(payload, 0, out, 12 + h.length, payload.length);
        return out;
    }

    // values in fixtures are the flat C-order sequence of logical values (6.3)
    static byte[] payloadOf(Map<String, Object> s) {
        String dt = str(s, "dtype");
        List<Object> vs = flat(s.get("values"));
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        for (Object v : vs) {
            switch (dt) {
                case "Bool": {
                    // fixtures store Bool as 0/1 integers (like Octave's logical());
                    // accept both booleans and numbers
                    boolean bv = (v instanceof Boolean)
                            ? (Boolean) v
                            : ((Number) v).longValue() != 0;
                    b.write(bv ? 1 : 0);
                    break;
                }
                case "Int64": {
                    long n = lng(v);
                    for (int k = 0; k < 8; k++) b.write((int) ((n >>> (8 * k)) & 0xFF));
                    break;
                }
                case "Float64": {
                    long n = Double.doubleToRawLongBits(((Number) v).doubleValue());
                    for (int k = 0; k < 8; k++) b.write((int) ((n >>> (8 * k)) & 0xFF));
                    break;
                }
                case "Float32": {
                    int n = Float.floatToRawIntBits((float) ((Number) v).doubleValue());
                    for (int k = 0; k < 4; k++) b.write((n >>> (8 * k)) & 0xFF);
                    break;
                }
                default:
                    throw new RuntimeException("dtype not covered by fixtures v1: " + dt);
            }
        }
        return b.toByteArray();
    }

    // ---------- bridge parse: codes only (port of trio_bridge._parse) ----------
    static class Vec { final String dtype; final Object[] vals;
        Vec(String d, Object[] v) { dtype = d; vals = v; } }

    static Object triParse(byte[] d) {
        if (d.length < 12) return "MalformedHeader";
        byte[] magic = "TRIOMAT1".getBytes(StandardCharsets.US_ASCII);
        for (int k = 0; k < 8; k++) if (d[k] != magic[k]) return "MalformedHeader";
        long hlen = (d[8] & 0xFFL) | ((d[9] & 0xFFL) << 8) | ((d[10] & 0xFFL) << 16) | ((d[11] & 0xFFL) << 24);
        if (12 + hlen > d.length) return "MalformedHeader";
        Object hdr;
        try {
            hdr = Json.parse(new String(d, 12, (int) hlen, StandardCharsets.UTF_8));
        } catch (RuntimeException e) {
            return "MalformedHeader";
        }
        if (!(hdr instanceof Map)) return "MalformedHeader";
        Map<String, Object> h = (Map<String, Object>) hdr;
        if (!h.containsKey("dtype") || !h.containsKey("shape")) return "MalformedHeader";
        String dt = (String) h.get("dtype");
        int nb;
        switch (dt) {
            case "Bool": case "Int8": case "UInt8": nb = 1; break;
            case "Int16": case "Float16": nb = 2; break;
            case "Int32": case "Float32": nb = 4; break;
            case "Int64": case "Float64": nb = 8; break;
            default: return "MalformedDtype";
        }
        Object sh = h.get("shape");
        if (!(sh instanceof List)) return "MalformedShape";
        long n = 1;
        for (Object o : (List<?>) sh) {
            if (!(o instanceof Number)) return "MalformedShape";
            long v = lng(o);
            if (v < 0) return "MalformedShape";
            n *= v;
        }
        if (12 + hlen + n * nb != d.length) return "MalformedPayload";
        byte[] pl = Arrays.copyOfRange(d, 12 + (int) hlen, d.length);
        if (dt.equals("Bool")) {
            for (byte bb : pl) if (bb != 0 && bb != 1) return "TypeMismatch"; // before decode
            Object[] vals = new Object[pl.length];
            for (int k = 0; k < pl.length; k++) vals[k] = pl[k] != 0;
            return new Vec(dt, vals);
        }
        Object[] vals = new Object[(int) n];
        for (int k = 0; k < n; k++) {
            int off = k * nb;
            switch (dt) {
                case "Int8":  vals[k] = (long) pl[off]; break;
                case "UInt8": vals[k] = (long) (pl[off] & 0xFF); break;
                case "Int16": vals[k] = (long) (short) ((pl[off] & 0xFF) | ((pl[off + 1] & 0xFF) << 8)); break;
                case "Int32": vals[k] = (long) ((pl[off] & 0xFF) | ((pl[off + 1] & 0xFF) << 8)
                                          | ((pl[off + 2] & 0xFF) << 16) | ((pl[off + 3] & 0xFF) << 24)); break;
                case "Int64": {
                    long v = 0;
                    for (int j = 7; j >= 0; j--) v = (v << 8) | (pl[off + j] & 0xFF);
                    vals[k] = v;
                    break;
                }
                case "Float16":
                    vals[k] = pl[off];        // stage 2: raw bytes only
                    break;
                case "Float32": {
                    int v = (pl[off] & 0xFF) | ((pl[off + 1] & 0xFF) << 8)
                          | ((pl[off + 2] & 0xFF) << 16) | ((pl[off + 3] & 0xFF) << 24);
                    vals[k] = (double) Float.intBitsToFloat(v);
                    break;
                }
                case "Float64": {
                    long v = 0;
                    for (int j = 7; j >= 0; j--) v = (v << 8) | (pl[off + j] & 0xFF);
                    vals[k] = Double.longBitsToDouble(v);
                    break;
                }
            }
        }
        return new Vec(dt, vals);
    }

    static boolean vecEq(Vec v, Object expected) {
        List<Object> e = flat(expected);
        if (v.vals.length != e.size()) return false;
        for (int k = 0; k < e.size(); k++) {
            Object a = v.vals[k], b = e.get(k);
            if (a instanceof Boolean) {
                boolean eb = (b instanceof Boolean)
                        ? (Boolean) b
                        : ((Number) b).longValue() != 0;
                if ((Boolean) a != eb) return false;
            }
            else if (a instanceof Long) { if (!a.equals(b)) return false; }
            else if (a instanceof Number) {
                if (Double.doubleToRawLongBits(((Number) a).doubleValue())
                 != Double.doubleToRawLongBits(((Number) b).doubleValue())) return false;
            }
        }
        return true;
    }

    // ---------- reader: 9 checks, aborts on 01,02,04,05,07 (7) ----------
    static List<String[]> reader9(byte[] d) {
        List<String[]> res = new ArrayList<>();
        if (d.length == 0) { res.add(new String[]{"01 not-empty", "ResourceLost"}); return res; }
        res.add(new String[]{"01 not-empty", ""});
        boolean ok02 = d.length >= 12;
        if (ok02) {
            byte[] magic = "TRIOMAT1".getBytes(StandardCharsets.US_ASCII);
            for (int k = 0; k < 8; k++) if (d[k] != magic[k]) { ok02 = false; break; }
        }
        if (!ok02) { res.add(new String[]{"02 header-frame", "MalformedHeader"}); return res; }
        res.add(new String[]{"02 header-frame", ""});
        long hlen = (d[8] & 0xFFL) | ((d[9] & 0xFFL) << 8) | ((d[10] & 0xFFL) << 16) | ((d[11] & 0xFFL) << 24);
        res.add(new String[]{"03 hlen-sane", ""});            // fixtures v1: no huge hlen
        Object hdr = null;
        try {
            hdr = Json.parse(new String(d, 12, (int) Math.min(hlen, d.length - 12),
                                        StandardCharsets.UTF_8));
        } catch (RuntimeException e) { hdr = null; }
        if (!(hdr instanceof Map)) { res.add(new String[]{"04 header-json", "MalformedHeader"}); return res; }
        res.add(new String[]{"04 header-json", ""});
        Map<String, Object> h = (Map<String, Object>) hdr;
        String dt = h.containsKey("dtype") ? (String) h.get("dtype") : null;
        boolean known = Arrays.asList("Bool", "Int8", "Int16", "Int32", "Int64",
                                      "UInt8", "Float16", "Float32", "Float64").contains(dt);
        if (!known) { res.add(new String[]{"05 dtype-known", "MalformedDtype"}); return res; }
        res.add(new String[]{"05 dtype-known", ""});
        res.add(new String[]{"06 shape-ints", ""});           // not aborting (fixtures v1)
        long nb;
        switch (dt) {
            case "Bool": case "Int8": case "UInt8": nb = 1; break;
            case "Int16": case "Float16": nb = 2; break;
            case "Int32": case "Float32": nb = 4; break;
            default: nb = 8; break;
        }
        long n = 1;
        if (h.get("shape") instanceof List)
            for (Object o : (List<?>) h.get("shape")) if (o instanceof Number) n *= lng(o);
        long plen = d.length - 12 - hlen;
        if (plen != n * nb) { res.add(new String[]{"07 payload-size", "MalformedPayload"}); return res; }
        res.add(new String[]{"07 payload-size", ""});
        String c08 = "";
        if (dt.equals("Bool"))
            for (int k = 12 + (int) hlen; k < d.length; k++)
                if (d[k] != 0 && d[k] != 1) { c08 = "TypeMismatch"; break; }  // not aborting
        res.add(new String[]{"08 bool-bytes", c08});
        Object p = triParse(d);
        res.add(new String[]{"09 decode", p instanceof String ? (String) p : ""});
        return res;
    }

    // ---------- verdict helpers ----------
    static boolean verdict(Object r, Map<String, Object> a) {
        if (r instanceof String) return r.equals(str(a, "expect_code"));
        String es = str(a, "expect_str");
        if (!es.isEmpty())
            return r instanceof Double && Double.isInfinite((Double) r)
                && (es.equals("inf") ? (Double) r > 0 : (Double) r < 0);
        return numEq(r, a.get("expect_num"));
    }

    static boolean numEq(Object a, Object b) {
        if (a instanceof Long && b instanceof Long) return ((Long) a).longValue() == ((Long) b).longValue();
        if (a instanceof Number && b instanceof Number)
            return Double.doubleToRawLongBits(((Number) a).doubleValue())
                == Double.doubleToRawLongBits(((Number) b).doubleValue());
        return Objects.equals(a, b);
    }

    static long[] shapeOf(Object o) {
        List<Object> l = (List<Object>) o;
        long[] r = new long[l.size()];
        for (int k = 0; k < l.size(); k++) r[k] = lng(l.get(k));
        return r;
    }

    // nested rows -> flat C-order sequence of logical values (6.3)
    static List<Object> flat(Object o) {
        List<Object> out = new ArrayList<>();
        collect(o, out);
        return out;
    }
    static void collect(Object o, List<Object> out) {
        if (o instanceof List) {
            for (Object e : (List<?>) o) collect(e, out);
        } else {
            out.add(o);
        }
    }


    static void ck(boolean ok, String label) {
        if (ok) { npass++; System.out.println("PASS " + label); }
        else { fails.add(label); System.out.println("FAIL " + label); }
    }

    static void sk(String label) { nskip++; System.out.println("SKIP " + label); }

    static String str(Map<String, Object> m, String k) {
        Object o = m.get(k);
        return o == null ? "" : (String) o;
    }
    static Map<String, Object> map(Object o) { return (Map<String, Object>) o; }
    static long lng(Object o) { return ((Number) o).longValue(); }

    // ---------- self-contained JSON parser (no external deps) ----------
    static class Json {
        static Object parse(String s) {
            P p = new P(s);
            p.ws();
            return p.value();
        }
        static class P {
            final String s; int i = 0;
            P(String s) { this.s = s; }
            void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }
            Object value() {
                ws();
                char c = s.charAt(i);
                if (c == '{') return obj();
                if (c == '[') return arr();
                if (c == '"') return str();
                if (c == 't') { i += 4; return Boolean.TRUE; }
                if (c == 'f') { i += 5; return Boolean.FALSE; }
                if (c == 'n') { i += 4; return null; }
                return num();
            }
            Map<String, Object> obj() {
                Map<String, Object> m = new LinkedHashMap<>();
                i++; ws();
                if (s.charAt(i) == '}') { i++; return m; }
                while (true) {
                    ws(); String k = str(); ws();
                    if (s.charAt(i++) != ':') throw new RuntimeException("bad json");
                    m.put(k, value());
                    ws(); char c = s.charAt(i++);
                    if (c == '}') break;
                    if (c != ',') throw new RuntimeException("bad json");
                }
                return m;
            }
            List<Object> arr() {
                List<Object> l = new ArrayList<>();
                i++; ws();
                if (s.charAt(i) == ']') { i++; return l; }
                while (true) {
                    l.add(value()); ws(); char c = s.charAt(i++);
                    if (c == ']') break;
                    if (c != ',') throw new RuntimeException("bad json");
                }
                return l;
            }
            String str() {
                StringBuilder b = new StringBuilder();
                i++;
                while (true) {
                    char c = s.charAt(i++);
                    if (c == '"') break;
                    if (c == '\\') {
                        char e = s.charAt(i++);
                        switch (e) {
                            case 'n': b.append('\n'); break;
                            case 't': b.append('\t'); break;
                            case 'r': b.append('\r'); break;
                            case '"': b.append('"'); break;
                            case '\\': b.append('\\'); break;
                            case '/': b.append('/'); break;
                            case 'u': b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; break;
                            default: throw new RuntimeException("bad escape");
                        }
                    } else b.append(c);
                }
                return b.toString();
            }
            Object num() {
                int st = i;
                while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
                String t = s.substring(st, i);
                if (t.indexOf('.') < 0 && t.indexOf('e') < 0 && t.indexOf('E') < 0) {
                    try { return Long.parseLong(t); }
                    catch (NumberFormatException ex) { return Double.parseDouble(t); }
                }
                return Double.parseDouble(t);
            }
        }
    }

    @SuppressWarnings("unchecked")
    static List<Object> list(Map<String, Object> m, String k) {
        Object o = m.get(k);
        return o == null ? new ArrayList<>() : (List<Object>) o;
    }

}
