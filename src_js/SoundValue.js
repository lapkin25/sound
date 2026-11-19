// SoundValue.js

/**
 * SoundValue — каноническое значение SCore.
 * Контракт: ровно один double (IEEE-754), целые через BigInt,
 * каноническая сериализация fmtHexDouble по 7.1.
 */
class SoundValue {
  /** @type {'INT'|'FLOAT'|'BOOL'|'VEC'|'CLOSURE'|'ERR'} */
  constructor(type, i, f, b, vec, clo, err) {
    this.type = type;
    this.i = i;        // BigInt для неограниченной точности
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

  static floatOf(x) {
    return new SoundValue('FLOAT', 0n, Number(x), false, null, null, null);
  }

  static boolOf(b) {
    return new SoundValue('BOOL', 0n, 0, Boolean(b), null, null, null);
  }

  static vecOf(arr) {
    return new SoundValue('VEC', 0n, 0, false, arr.map(v => Number(v)), null, null);
  }

  static of(clo) {
    return new SoundValue('CLOSURE', 0n, 0, false, null, clo, null);
  }

  static errOf(code) {
    return new SoundValue('ERR', 0n, 0, false, null, null, String(code));
  }

  isErr() {
    return this.type === 'ERR';
  }

  /**
   * Контракт 7.1: канонический hex-формат double.
   * Требования:
   * - мантисса ровно 13 hex-цифр
   * - знак порядка обязателен
   * - субнормали без перенормировки
   * - различение -0.0
   */
  static fmtHexDouble(x) {
    if (x !== x) return 'nan';
    if (x === Infinity) return 'inf';
    if (x === -Infinity) return '-inf';

    const buf = new ArrayBuffer(8);
    const dv = new DataView(buf);
    dv.setFloat64(0, x, false); // little-endian, но биты нам важны как есть
    const bits = dv.getBigUint64(0);

    const neg = (bits >> 63n) & 1n;
    const exp = Number((bits >> 52n) & 0x7FFn);
    const mant = bits & 0xFFFFFFFFFFFFFn; // ровно 52 бита

    const sign = neg ? '-' : '';

    // -0.0 vs +0.0: Object.is видит разницу
    if (Object.is(x, -0)) return '-0x0.0p+0';
    if (x === 0) return '0x0.0p+0';

    if (exp === 0) {
      // субнормаль: 0x0.<13 цифр>p-1022
      const mHex = mant.toString(16).padStart(13, '0');
      return `${sign}0x0.${mHex}p-1022`;
    }

    const e = exp - 1023;
    const mHex = mant.toString(16).padStart(13, '0');
    const pSign = e >= 0 ? '+' : '';
    return `${sign}0x1.${mHex}p${pSign}${e}`;
  }

  canon() {
    switch (this.type) {
      case 'INT':
        return this.i.toString();
      case 'FLOAT':
        return SoundValue.fmtHexDouble(this.f);
      case 'BOOL':
        return this.b ? 'true' : 'false';
      case 'VEC': {
        const parts = this.vec.map(v => SoundValue.fmtHexDouble(v));
        return '[' + parts.join(',') + ']';
      }
      case 'CLOSURE':
        return '<closure>';
      case 'ERR':
        return `Err(${this.err})`;
      default:
        return '?';
    }
  }
}

/**
 * Trace — журнал исполнения (контракт 7.2).
 * bind: имя + значение + (если ошибка) событие err.
 * result: возвращаемое значение.
 */
const Trace = {
  bind(name, v) {
    console.log(`bind ${name} ${v.canon()}`);
    if (v.isErr()) {
      console.log(`err ${name} Err(${v.err})`);
    }
  },
  result(v) {
    console.log(`result ${v.canon()}`);
  },
  flush() {
    // в Node.js stdout буферизуется, но для простого лога достаточно console.log
  }
};

module.exports = { SoundValue, Trace };
