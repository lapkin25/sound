// tests/test_roundtrip.js — канонический TRIOMAT1: JS -> Octave -> JS.
// Побитовое сравнение: NaN не даёт ложного PASS, -0.0 не путается с 0.0.
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
const { writeTriomat1 } = require('../src_js/trio_to_octave');
const { readTriomat } = require('../src_js/readTriomat');

const input = [
  [1.0, 2.5, -0.0],
  [1e-320, Infinity, NaN],       // субнормаль, бесконечность, NaN — все ловушки сразу
];
const rows = 2, cols = 3;

writeTriomat1('test.triomat', 'Float64', [rows, cols],
  { stub: false, lossy: false, trusted: true }, input.flat());
console.log('js: wrote test.triomat (2x3, Float64, canonical TRIOMAT1)');

execFileSync('octave',
  ['--no-gui', '--quiet', path.join('src_octave', 'test_roundtrip.m')],
  { stdio: 'inherit' });

const v = readTriomat('result.triomat');
if (v.rows !== rows || v.cols !== cols)
  throw new Error('Err(ShapeError): wrong result shape ' + v.rows + 'x' + v.cols);

let ok = true;
for (let r = 0; r < rows; r++)
  for (let c = 0; c < cols; c++) {
    const a = input[r][c] * 2, b = v.matrix[r][c];
    // побитовое сравнение через буфер
    const ab = Buffer.alloc(8), bb = Buffer.alloc(8);
    ab.writeDoubleLE(a); bb.writeDoubleLE(b);
    if (!ab.equals(bb)) {
      console.error('FAIL at [' + r + '][' + c + ']: expected ' + a + ', got ' + b);
      ok = false;
    }
  }

console.log(ok
  ? 'PASS: canonical roundtrip JS -> Octave -> JS, bit-for-bit'
  : 'FAIL');
process.exit(ok ? 0 : 1);
