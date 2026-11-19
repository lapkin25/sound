// tools/check_js.js
const fs = require('fs');

const files = ['SoundValue.js', 'Ops.js', 'TermT06.js'];
let ok = true;

for (const file of files) {
  const src = fs.readFileSync(file, 'utf8');
  if (!src.includes('fmtHexDouble')) {
    console.error(`FAIL: ${file} does not contain fmtHexDouble`);
    ok = false;
  }
  if (!src.includes('BigInt')) {
    console.error(`FAIL: ${file} does not use BigInt for integers`);
    ok = false;
  }
  if (!src.includes('DataView') && !src.includes('getBigUint64')) {
    console.error(`FAIL: ${file} does not access raw bits correctly`);
    ok = false;
  }
}

if (!fs.readFileSync('TermT06.js', 'utf8').includes('result 6')) {
  console.error('FAIL: TermT06 does not produce result 6 in logs');
  ok = false;
}

console.log(ok ? 'ALL CHECKS PASS' : 'SOME CHECKS FAILED');
process.exit(ok ? 0 : 1);
