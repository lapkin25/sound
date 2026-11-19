// trio_to_octave.js — канонический писатель TRIOMAT1 (JS -> Octave).
// Контракт Trio: потеря точности — только с явным флагом.
'use strict';
const fs = require('fs');

function writeTriomat1(filename, dtype, shape, flags, data) {
  const header = Buffer.from(JSON.stringify(
    { magic: 'TRIOMAT1', dtype, shape, flags }), 'utf8');
  const len = Buffer.alloc(4);
  len.writeUInt32LE(header.length, 0);
  let payload;
  if (dtype === 'Float64') payload = Buffer.from(Float64Array.from(data).buffer);
  else if (dtype === 'Int64') {
    payload = Buffer.alloc(data.length * 8);
    data.forEach((v, i) => payload.writeBigInt64LE(BigInt(v), i * 8));
  } else payload = Buffer.from(data.map(b => (b ? 1 : 0)));
  fs.writeFileSync(filename, Buffer.concat([len, header, payload]));
}

// Матрица смежности графа -> TRIOMAT для Octave-узла.
// hasLoss=true, если данные прошли через неограниченные целые (флаг 0x01/lossy).
function saveGraphForOctave(filename, matrix, hasLoss) {
  const rows = matrix.length, cols = matrix[0].length;
  writeTriomat1(filename, 'Float64', [rows, cols],
    { stub: false, lossy: Boolean(hasLoss), trusted: true },
    matrix.flat());
}

if (typeof module !== 'undefined') module.exports = { writeTriomat1, saveGraphForOctave };
