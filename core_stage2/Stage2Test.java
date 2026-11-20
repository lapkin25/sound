// Stage2Test.java - stage 2: journal conformance (7 vectors)
// Reuses canon() and Json from ConformanceTest.java (same directory).
// Run: javac ConformanceTest.java Stage2Test.java && java Stage2Test
// Expected tail: ALL PASS (7/7)
//
// Spec parsing and static checks (SC) are the etalon's job: hosts receive
// already-parsed trees from fixtures_stage2.json. Host duties: execute the
// tree, reproduce the journal 3.8 byte-for-byte. NaN argument arrives as
// {"hex_bits": "..."} since JSON has no NaN literal.

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class Stage2Test {

    public static void main(String[] args) throws Exception {
        Map<String, Object> fx = (Map<String, Object>) ConformanceTest.Json.parse(
            new String(Files.readAllBytes(Paths.get("fixtures_stage2.json")),
                       StandardCharsets.UTF_8));
        Map<String, Object> rules = cast(fx.get("rules"));
        Map<String, Object> facts = cast(fx.get("facts"));
        List<Object> jv = cast(fx.get("journal_vectors"));

        int npass = 0; List<String> fails = new ArrayList<>();
        for (Object o : jv) {
            Map<String, Object> v = cast(o);
            String name = (String) v.get("name");
            ExecResult res = execRule((String) v.get("rule"),
                                      cast(rules.get(v.get("rule"))), facts,
                                      cast(v.get("args")));
            List<Object> expect = cast(v.get("expect_log"));
            boolean ok = res.journal.equals(expect)
                      && valueOk(res.value, v.get("expect_value"));
            if (ok) { npass++; System.out.println("PASS " + name); }
            else {
                fails.add(name);
                System.out.println("FAIL " + name);
                int n = Math.max(res.journal.size(), expect.size());
                for (int k = 0; k < n; k++) {
                    String a = k < res.journal.size() ? res.journal.get(k) : "";
                    String b = k < expect.size() ? String.valueOf(expect.get(k)) : "";
                    if (!a.equals(b)) {
                        System.out.println("  line " + (k + 1) + ": got  " + a);
                        System.out.println("  line " + (k + 1) + ": want " + b);
                    }
                }
            }
        }
        System.out.println();
        if (!fails.isEmpty()) {
            System.out.println("FAILURES: " + fails.size() + " -> " + String.join(", ", fails));
            System.exit(1);
        }
        System.out.println("ALL PASS (" + npass + "/" + npass + ")");
    }

    static class ExecResult { List<String> journal; Double value; }

    static ExecResult execRule(String rname, Map<String, Object> r,
                               Map<String, Object> facts, Map<String, Object> args) {
        List<Object> params = cast(r.get("params"));
        Map<String, Double> env = new LinkedHashMap<>();
        for (Object p : params) {
            String pn = (String) p;
            env.put(pn, argVal(args.get(pn)));
        }
        ExecResult res = new ExecResult();
        res.journal = new ArrayList<>();

        // 1) invariant first, silently; violation -> single err line (3.8)
        Object inv = r.get("inv");
        if (inv != null) {
            Map<String, Double> fenv = new LinkedHashMap<>();
            for (Map.Entry<String, Object> e : facts.entrySet())
                fenv.put(e.getKey(), ((Number) e.getValue()).doubleValue());
            fenv.putAll(env);
            Object okv = evalSilent(inv, fenv);
            boolean ok = (okv instanceof Boolean)
                       ? (Boolean) okv
                       : ((Double) okv) == 1.0;      // NaN == 1.0 is false
            if (!ok) {
                res.journal.add("err DomainError " + rname + ": invariant");
                return res;                          // value stays null
            }
        }

        // 2) binds of parameters, names padded to max(2, longest name)
        int pad = 2;
        for (Object p : params) pad = Math.max(pad, ((String) p).length());
        for (Object p : params) {
            String pn = (String) p;
            res.journal.add("bind " + pad(pn, pad) + " = Float64 "
                            + ConformanceTest.canon(env.get(pn)));
        }

        // 3) body: left, right, operation; t-bind after each operation node
        int[] counter = {0};
        double val = evalJ(r.get("tree"), env, facts, res.journal, pad, counter);

        // 4) result line
        res.journal.add("result  = Float64 " + ConformanceTest.canon(val));
        res.value = val;
        return res;
    }

    static double evalJ(Object tree, Map<String, Double> env, Map<String, Object> facts,
                        List<String> journal, int pad, int[] counter) {
        if (tree instanceof String) {
            return env.containsKey(tree)
                 ? env.get(tree)
                 : ((Number) facts.get((String) tree)).doubleValue();
        }
        if (tree instanceof Number) return ((Number) tree).doubleValue();
        List<Object> n = cast(tree);
        String op = n.get(0).toString();
        double lv = evalJ(n.get(1), env, facts, journal, pad, counter);
        double v;
        if (op.equals("neg")) {
            v = -lv;
        } else {
            double rv = evalJ(n.get(2), env, facts, journal, pad, counter);
            switch (op) {
                case "+": v = lv + rv; break;
                case "-": v = lv - rv; break;
                case "*": v = lv * rv; break;
                default:  v = lv / rv; break;   // IEEE; 0.0/0.0 -> NaN natively
            }
        }
        journal.add("bind " + pad("t" + counter[0], pad) + " = Float64 "
                    + ConformanceTest.canon(v));
        counter[0]++;
        return v;
    }

    static Object evalSilent(Object node, Map<String, Double> env) {
        if (node instanceof String) return env.get(node);
        if (node instanceof Number) return ((Number) node).doubleValue();
        List<Object> n = cast(node);
        String op = n.get(0).toString();
        Object a = evalSilent(n.get(1), env);
        if (op.equals("neg")) return -((Double) a);
        if (op.equals(">=") || op.equals("<=") || op.equals(">")
                || op.equals("<") || op.equals("==") || op.equals("!=")) {
            double av = (Double) a, bv = (Double) evalSilent(n.get(2), env);
            boolean r;
            switch (op) {
                case ">=": r = av >= bv; break;
                case "<=": r = av <= bv; break;
                case ">":  r = av > bv;  break;
                case "<":  r = av < bv;  break;
                case "==": r = av == bv; break;
                default:   r = av != bv; break;
            }
            return r;
        }
        double av = (Double) a, bv = (Double) evalSilent(n.get(2), env);
        switch (op) {
            case "+": return av + bv;
            case "-": return av - bv;
            case "*": return av * bv;
            default:  return av / bv;           // IEEE; 0.0/0.0 -> NaN natively
        }
    }

    static double argVal(Object o) {
        if (o instanceof Number) return ((Number) o).doubleValue();
        Map<String, Object> m = cast(o);
        return Double.longBitsToDouble(Long.parseUnsignedLong((String) m.get("hex_bits"), 16));
    }

    static boolean valueOk(Double val, Object expect) {
        if (expect == null) return val == null;
        return ConformanceTest.canon(val)
            .equals(ConformanceTest.canon(((Number) expect).doubleValue()));
    }

    static String pad(String s, int w) {
        StringBuilder b = new StringBuilder(s);
        while (b.length() < w) b.append(' ');
        return b.toString();
    }

    @SuppressWarnings("unchecked")
    static <T> T cast(Object o) { return (T) o; }
}
