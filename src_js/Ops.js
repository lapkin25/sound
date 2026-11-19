// Ops.js — операции по контракту SCore; ошибки протекают как значения.
const { SoundValue } = require('./SoundValue');

function isNum(v) { return v.type === 'INT' || v.type === 'FLOAT'; }
function widen(v) {
  if (v.type === 'INT') return SoundValue.floatOf(Number(v.i)); // R-INT1: > 2^53 — lossy, см. Trio
  return v;
}
function numOf(v) { return v.type === 'INT' ? Number(v.i) : v.f; }

function binop(fn, intFn) {
  return (a, b) => {
    if (a.isErr()) return a;
    if (b.isErr()) return b;
    if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
    if (a.type === 'INT' && b.type === 'INT') return intFn(a.i, b.i);
    return fn(widen(a).f, widen(b).f);
  };
}

Ops.add = binop((x, y) => SoundValue.floatOf(x + y), (a, b) => SoundValue.intOf(a + b));
Ops.sub = binop((x, y) => SoundValue.floatOf(x - y), (a, b) => SoundValue.intOf(a - b));
Ops.mul = binop((x, y) => SoundValue.floatOf(x * y), (a, b) => SoundValue.intOf(a * b));

// Деление: всегда float; деление на ноль — IEEE-семантика (inf/-inf/nan)
Ops.div = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  const av = numOf(a), bv = numOf(b);
  if (bv === 0) {
    if (av > 0) return SoundValue.floatOf(Infinity);
    if (av < 0) return SoundValue.floatOf(-Infinity);
    return SoundValue.floatOf(NaN);
  }
  return SoundValue.floatOf(av / bv);
};

Ops.eq = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (a.type !== b.type) return SoundValue.boolOf(false);
  if (a.type === 'INT')   return SoundValue.boolOf(a.i === b.i);
  if (a.type === 'FLOAT') return SoundValue.boolOf(a.f === b.f);
  if (a.type === 'BOOL')  return SoundValue.boolOf(a.b === b.b);
  return SoundValue.errOf('TypeMismatch');
};
Ops.lt = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(numOf(a) < numOf(b));
};
Ops.le = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(numOf(a) <= numOf(b));
};
Ops.and = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (a.type !== 'BOOL' || b.type !== 'BOOL') return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(a.b && b.b);
};
Ops.or = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (a.type !== 'BOOL' || b.type !== 'BOOL') return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(a.b || b.b);
};
Ops.not = (a) => {
  if (a.isErr()) return a;
  if (a.type !== 'BOOL') return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(!a.b);
};

// Коэрсии
Ops.widenCoerce = (v) => {
  if (v.isErr()) return v;
  if (v.type === 'INT') return SoundValue.floatOf(Number(v.i));
  if (v.type === 'FLOAT') return v;
  return SoundValue.errOf('TypeMismatch');
};
Ops.narrowCoerce = (v) => {
  if (v.isErr()) return v;
  if (v.type !== 'FLOAT') return SoundValue.errOf('TypeMismatch');
  if (v.f !== Math.trunc(v.f)) return SoundValue.errOf('PrecisionLoss');
  if (v.f > Number.MAX_SAFE_INTEGER || v.f < -Number.MAX_SAFE_INTEGER)
    return SoundValue.errOf('PrecisionLoss');
  return SoundValue.intOf(BigInt(v.f));
};

// Замыкание: снимок окружения на момент создания + функция
class Closure {
  constructor(env, fn) { this.env = env; this.fn = fn; }
  apply(arg) { return this.fn(this.env, arg); }
}
Ops.Closure = Closure;

// Окружение: односвязный список пар (имя, значение)
class Env {
  constructor(name, val, next) { this.name = name; this.val = val; this.next = next; }
  static get(e, name) {
    for (let cur = e; cur !== null; cur = cur.next)
      if (cur.name === name) return cur.val;
    return SoundValue.errOf('UndefinedVariable');
  }
}
Ops.Env = Env;

Ops.apply = (f, arg) => {
  if (f.isErr()) return f;
  if (f.type !== 'CLOSURE') return SoundValue.errOf('ApplyOnNonClosure');
  return f.clo.apply(arg);
};
Ops.select = (c, t, e) => {
  if (c.isErr()) return c;
  if (c.type !== 'BOOL') return SoundValue.errOf('SelectOnNonBool');
  return c.b ? t : e;
};

// Reduce: явный аккумулятор, шаги видимы в журнале
Ops.reduce = (vec, acc, step) => {
  if (vec.isErr()) return vec;
  if (acc.isErr()) return acc;
  let a = acc;
  for (const x of vec.vec) {
    a = Ops.apply(step, SoundValue.floatOf(x));
    if (a.isErr()) return a;
  }
  return a;
};

if (typeof module !== 'undefined') module.exports = Ops;
