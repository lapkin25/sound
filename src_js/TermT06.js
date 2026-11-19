// TermT06.js — автогенерируемый терм T06: лексический захват значения.
// Канонический журнал:
//   bind x1 1
//   bind f <closure>
//   bind x1 105
//   result 6
// Затенение x1 = 105 НЕ видно замыканию: оно захватило снимок env1.
const { SoundValue, Trace } = require('./SoundValue');
const Ops = require('./Ops');

function termT06() {
  // let x1 = 1
  const x1 = SoundValue.intOf(1n);
  Trace.bind('x1', x1);
  const env1 = new Ops.Env('x1', x1, null);

  // let f = fun y -> x1 + y  — захват снимка env1
  const f = SoundValue.of(new Ops.Closure(env1,
    (cenv, y) => Ops.add(Ops.Env.get(cenv, 'x1'), y)));
  Trace.bind('f', f);
  const env2 = new Ops.Env('f', f, env1);

  // let x1 = 105 — затенение; замыкание его не видит
  const x1s = SoundValue.intOf(105n);
  Trace.bind('x1', x1s);
  const env3 = new Ops.Env('x1', x1s, env2);

  // f 5
  const res = Ops.apply(Ops.Env.get(env3, 'f'), SoundValue.intOf(5n));
  Trace.result(res);
  return res;
}

termT06();
Trace.flush();
