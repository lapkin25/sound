// SoundValue.js
/**
 * SoundValue — каноническое значение SCore.
 * Контракт: ровно один плавающий тип (IEEE-754 double), целые через BigInt
 * (неограниченная точность эталона, закрывает D-J1), каноническая
 * сериализация fmtHexDouble по 7.1.
 */
class SoundValue {
  constructor(type, i, f, b, vec, clo, err) {
    this.type = type;
    this.i = i;        // BigInt
    this.f = f;        // IEEE-754 double
    this.b = b;
    this.vec = vec;    // Array<number>
    this.clo = clo;    // Closure
    this.err = err;    // string
  }
  static intOf(x) {
    const v = typeof x === 'bigint' ? x : BigInt(x);
    return new SoundValue('INT', v, 0, false, null, null, null);
  }
  static floatOf(x) { return new SoundValue('FLOAT', 0n, Number(x), false, null, null, null); }
  static boolOf(b)  { return new SoundValue('BOOL', 0n, 0, Boolean(b), null, null, null); }
  static vecOf(arr) { return new SoundValue('VEC', 0n, 0, false, arr.map(v => Number(v)), null, null); }
  static of(clo)    { return new SoundValue('CLOSURE', 0n, 0, false, null, clo, null); }
  static errOf(code){ return new SoundValue('ERR', 0n, 0, false, null, null, String(code)); }
  isErr() { return this.type === 'ERR'; }

  /**
   * Контракт 7.1: побитовый эквивалент float.hex() из CPython.
   * Требования: мантисса ровно 13 hex-цифр, знак порядка обязателен,
   * субнормали без перенормировки, различение -0.0, единый nan.
   */
  static fmtHexDouble(x) {
    if (x !== x) return 'nan';
    if (x === Infinity) return 'inf';
    if (x === -Infinity) return '-inf';
    const buf = new ArrayBuffer(8);
    const dv = new DataView(buf);
    dv.setFloat64(0, x);
    const bits = dv.getBigUint64(0);
    const neg = (bits >> 63n) & 1n;                 // знаковый бит — урок Java-транскрипции
    const exp = Number((bits >> 52n) & 0x7FFn);
    const mant = bits & 0xFFFFFFFFFFFFFn;           // ровно 52 бита — урок C-бага
    const sign = neg ? '-' : '';
    if (Object.is(x, -0)) return '-0x0.0p+0';
    if (x === 0) return '0x0.0p+0';
    if (exp === 0) return sign + '0x0.' + mant.toString(16).padStart(13, '0') + 'p-1022';
    const e = exp - 1023;
    return sign + '0x1.' + mant.toString(16).padStart(13, '0') + 'p' + (e >= 0 ? '+' : '') + e;
  }

  canon() {
    switch (this.type) {
      case 'INT':     return this.i.toString();
      case 'FLOAT':   return SoundValue.fmtHexDouble(this.f);
      case 'BOOL':    return this.b ? 'true' : 'false';
      case 'VEC':     return '[' + this.vec.map(v => SoundValue.fmtHexDouble(v)).join(',') + ']';
      case 'CLOSURE': return '<closure>';
      case 'ERR':     return 'Err(' + this.err + ')';
      default:        return '?';
    }
  }
}

/** Trace — журнал исполнения (контракт 7.2). */
const Trace = {
  bind(name, v) {
    console.log('bind ' + name + ' ' + v.canon());
    if (v.isErr()) console.log('err ' + name + ' Err(' + v.err + ')');
  },
  result(v) { console.log('result ' + v.canon()); },
  flush()   { process.stdout.write(''); }
};

if (typeof module !== 'undefined') module.exports = { SoundValue, Trace };
