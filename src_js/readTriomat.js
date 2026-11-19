// readTriomat.js — канонический TRIOMAT1 (спека моста Trio, раздел 8).
// Семантика: любое расхождение — Err(...), ноль эвристик.
'use strict';
const fs = require('fs');

function soundErr(code, msg) {
  const e = new Error('Err(' + code + '): ' + msg);
  e.soundCode = code;
  return e;
}

const ELEM = { 'Float64': 8, 'Int64': 8, 'Bool': 1 };

// Ошибки: MalformedHeader | ShapeError | TypeError | BoolPayload
function parseTriomat(buf) {
  if (buf.length < 4) throw soundErr('ShapeError', 'truncated: no header length');
  const hlen = buf.readUInt32LE(0);
  if (4 + hlen > buf.length) throw soundErr('ShapeError', 'header length ' + hlen + ' exceeds file');

  let header;
  try { header = JSON.parse(buf.slice(4, 4 + hlen).toString('utf8')); }
  catch (e) { throw soundErr('MalformedHeader', 'header is not valid UTF-8 JSON'); }
  if (header.magic !== 'TRIOMAT1')
    throw soundErr('MalformedHeader', 'magic=' + JSON.stringify(header.magic) + ', expected "TRIOMAT1"');

  const dt = header.dtype;
  const elem = ELEM[dt];
  if (!elem) throw soundErr('TypeError', 'dtype=' + JSON.stringify(dt) + ', expected Float64|Int64|Bool');

  const shape = header.shape;
  if (!Array.isArray(shape) || !shape.every(d => Number.isInteger(d) && d >= 0))
    throw soundErr('ShapeError', 'shape=' + JSON.stringify(shape) + ', expected array of non-negative ints');

  const f = header.flags || {};
  const flags = { stub: Boolean(f.stub), lossy: Boolean(f.lossy), trusted: f.trusted !== false };

  let count = 1;
  for (const d of shape) count *= d;                 // пустая shape -> 1 (скаляр)
  const payload = buf.length - 4 - hlen;
  if (payload !== count * elem)
    throw soundErr('ShapeError', 'payload=' + payload + ' bytes, expected ' + count * elem);

  const off = 4 + hlen;
  const values = new Array(count);
  if (dt === 'Float64') {
    for (let i = 0; i < count; i++) values[i] = buf.readDoubleLE(off + i * 8);
    // -0.0 и паттерны NaN сохраняются как прочитаны; канонизация — только в canon()
  } else if (dt === 'Int64') {
    for (let i = 0; i < count; i++) values[i] = buf.readBigInt64LE(off + i * 8);
  } else {
    for (let i = 0; i < count; i++) {
      const b = buf.readUInt8(off + i);
      if (b !== 0 && b !== 1)
        throw soundErr('BoolPayload', 'byte ' + b + ' at offset ' + (off + i) + ', expected 0 or 1');
      values[i] = b === 1;
    }
  }

  const rows = shape.length >= 2 ? shape[0] : 1;
  const cols = shape.length >= 2 ? shape[1] : count;
  return { dtype: dt, shape, flags, values, rows, cols };
}

function readTriomat(filename) {
  const p = parseTriomat(fs.readFileSync(filename));
  p.matrix = [];
  for (let r = 0; r < p.rows; r++)
    p.matrix.push(p.values.slice(r * p.cols, (r + 1) * p.cols));
  return p;
}

if (typeof module !== 'undefined') module.exports = { parseTriomat, readTriomat, soundErr };
