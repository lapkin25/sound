// readTriomat.js
const fs = require('fs');

// Контракт: любое расхождение — Err(ShapeError), без эвристик
function readTriomat(filename) {
  const buf = fs.readFileSync(filename);
  if (buf.length < 16) throw new Error('Err(ShapeError): truncated header');

  const rows  = buf.readInt32LE(0);
  const cols  = buf.readInt32LE(4);
  const dtype = buf.readInt32LE(8);
  const flags = buf.readInt32LE(12);

  if (dtype !== 0) throw new Error('Err(ShapeError): dtype=' + dtype + ', expected 0 (double)');

  const payloadBytes = buf.length - 16;
  if (payloadBytes !== rows * cols * 8)
    throw new Error('Err(ShapeError): payload=' + payloadBytes + ', expected ' + rows * cols * 8);

  const data = new Float64Array(rows * cols);
  for (let i = 0; i < data.length; i++) data[i] = buf.readDoubleLE(16 + i * 8);

  return { rows, cols, dtype, flags, data };
}

function toMatrix(v) {
  const m = [];
  for (let r = 0; r < v.rows; r++) m.push(Array.from(v.data.slice(r * v.cols, (r + 1) * v.cols)));
  return m;
}

module.exports = { readTriomat, toMatrix };
