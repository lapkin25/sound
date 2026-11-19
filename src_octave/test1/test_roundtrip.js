// test_roundtrip.js — полный цикл: JS -> Octave -> JS, сравнение с ожиданием
const fs = require('fs');
const { execFileSync } = require('child_process');
const { writeTriomat } = require('./trio_to_octave');   // из прошлого сообщения
const { readTriomat, toMatrix } = require('./readTriomat');

// 1. Готовим вход: матрица 2x3, знаем точный ожидаемый выход (A * 2)
const input = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]];
const expected = input.map(row => row.map(x => x * 2));
writeTriomat('test.triomat', 2, 3, 0, 0, input.flat());
console.log('js: wrote test.triomat (2x3, double, flags=0)');

// 2. Прогоняем Octave
execFileSync('octave', ['--no-gui', '--quiet', 'test_roundtrip.m'], { stdio: 'inherit' });

// 3. Читаем результат, сверяем побитово
const v = readTriomat('result.triomat');
if (v.rows !== 2 || v.cols !== 3) throw new Error('Err(ShapeError): wrong result shape');
const got = toMatrix(v);

let ok = true;
for (let r = 0; r < 2; r++)
  for (let c = 0; c < 3; c++) {
    const a = input[r][c] * 2, b = got[r][c];
    // побитовое сравнение: NaN не даёт ложного PASS, -0.0 не путается с 0.0
    if (new Float64Array([a])[0] !== new Float64Array([b])[0]) {
      console.error(`FAIL at [${r}][${c}]: expected ${a}, got ${b}`);
      ok = false;
    }
  }

console.log(ok
  ? 'PASS: round-trip JS -> Octave -> JS, values match bit-for-bit'
  : 'FAIL');
process.exit(ok ? 0 : 1);
