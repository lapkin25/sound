// TermT06.java -- автогенерированный файл. Не редактировать вручную.
public final class TermT06 {

    public static SoundValue run() {
        // let x1 = 1
        SoundValue x1 = SoundValue.intOf(1);
        SoundValue.Trace.bind("x1", x1);
        Ops.Env env1 = new Ops.Env("x1", x1, null);

        // let f = fun y -> x1 + y   -- захват env1 (снимок на момент создания)
        Ops.Closure f = new Ops.Closure(env1,
            (Ops.Env cenv, SoundValue y) -> Ops.add(Ops.Env.get(cenv, "x1"), y));
        SoundValue.Trace.bind("f", SoundValue.of(f));
        Ops.Env env2 = new Ops.Env("f", SoundValue.of(f), env1);

        // let x1 = 105  -- затенение; замыкание f его НЕ видит
        SoundValue x1s = SoundValue.intOf(105);
        SoundValue.Trace.bind("x1", x1s);
        Ops.Env env3 = new Ops.Env("x1", x1s, env2);

        // f 5
        SoundValue res = Ops.apply(Ops.Env.get(env3, "f"), SoundValue.intOf(5));
        SoundValue.Trace.result(res);
        return res;
    }

    public static void main(String[] args) {
        run();
        SoundValue.Trace.flush();
    }
}
