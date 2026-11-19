// Ops.js
const { SoundValue } = require('./SoundValue');

/**
 * Ops — чистые операции по контракту SCore.
 * Ошибки протекают как значения.
 */
const Ops = {};

function isNum(v) {
  return v.type === 'INT' || v.type === 'FLOAT';
}

function widen(v) {
  if (v.type === 'INT') {
    // BigInt -> Number (до 2^53 точно; дальше — потеря, но это часть контракта Trio)
    return SoundValue.floatOf(Number(v.i));
  }
  return v;
}

function numOf(v) {
  if (v.type === 'INT') return Number(v.i);
  return v.f;
}

Ops.add = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  if (a.type === 'INT' && b.type === 'INT') {
    return SoundValue.intOf(a.i + b.i); // BigInt арифметика
  }
  const av = widen(a), bv = widen(b);
  return SoundValue.floatOf(av.f + bv.f);
};

Ops.sub = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  if (a.type === 'INT' && b.type === 'INT') {
    return SoundValue.intOf(a.i - b.i);
  }
  const av = widen(a), bv = widen(b);
  return SoundValue.floatOf(av.f - bv.f);
};

Ops.mul = (a, b) => {
  if (a.isErr()) return a;
  if (b.isErr()) return b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  if (a.type === 'INT' && b.type === 'INT') {
    return SoundValue.intOf(a.i * b.i);
  }
  const av = widen(a), bv = widen(b);
  return SoundValue.floatOf(av.f * bv.f);
};

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
  switch (a.type) {
    case 'INT': return SoundValue.boolOf(a.i === b.i);
    case 'FLOAT': return SoundValue.boolOf(a.f === b.f);
    case 'BOOL': return SoundValue.boolOf(a.b === b.b);
    default: return SoundValue.errOf('TypeMismatch');
  }
};

Ops.lt = (a, b) => {
  if (a.isErr() || b.isErr()) return a.isErr() ? a : b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(numOf(a) < numOf(b));
};

Ops.le = (a, b) => {
  if (a.isErr() || b.isErr()) return a.isErr() ? a : b;
  if (!isNum(a) || !isNum(b)) return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(numOf(a) <= numOf(b));
};

Ops.and = (a, b) => {
  if (a.isErr() || b.isErr()) return a.isErr() ? a : b;
  if (a.type !== 'BOOL' || b.type !== 'BOOL') return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(a.b && b.b);
};

Ops.or = (a, b) => {
  if (a.isErr() || b.isErr()) return a.isErr() ? a : b;
  if (a.type !== 'BOOL' || b.type !== 'BOOL') return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(a.b || b.b);
};

Ops.not = (a) => {
  if (a.isErr()) return a;
  if (a.type !== 'BOOL') return SoundValue.errOf('TypeMismatch');
  return SoundValue.boolOf(!a.b);
};

Ops.widenCoerce = (v) => {
  if (v.isErr()) return v;
  if (v.type === 'INT') return SoundValue.floatOf(Number(v.i));
  if (v.type === 'FLOAT') return v;
  return SoundValue.errOf('TypeMismatch');
};

Ops.narrowCoerce = (v) => {
  if (v.isErr()) return v;
  if (v.type !== 'FLOAT') return SoundValue.errOf('TypeMismatch');
  if (v.f !== Math.rint(v.f)) return SoundValue.errOf('PrecisionLoss');
  // проверка диапазона BigInt не нужна: BigInt принимает любые числа, но если v.f вне безопасного диапазона — это уже потеря точности
  return SoundValue.intOf(BigInt(Math.round(v.f)));
};

/**
 * Замыкание: снимок окружения на момент создания + функция.
 */
class Closure {
  constructor(env, fn) {
    this.env = env;
    this.fn = fn;
  }
  apply(arg) {
    return this.fn(this.env, arg);
  }
}

Ops.Closure = Closure;

/**
 * Окружение: односвязный список пар (имя, значение).
 */
class Env {
  constructor(name, val, next) {
    this.name = name;
    this.val = val;
    this.next = next;
  }
  static get(e, name) {
    for (let cur = e; cur !== null; cur = cur.next) {
      if (cur.name === name) return cur.val;
    }
    return SoundValue.errOf('UndefinedVariable');
  }
}

Ops.Env = Env;

/**
 * Применение и select.
 */
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

module.exports = Ops;
