// generate_nodes.js — v2: универсальный генератор узлов SCore
// Бэкенды: "octave" (.m + run-скрипт + JS-мост) и "external" (любая CLI-программа + JS-мост)
'use strict';
const fs = require('fs');
const path = require('path');

const TYPES = new Set(['scalar', 'vector', 'matrix']);
const DTYPES = new Set(['Float64', 'Int64', 'Bool']);
const BACKENDS = new Set(['octave', 'external']);
const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

function specErr(msg) { throw new Error('SpecError: ' + msg); }

function validateSpec(spec) {
  if (!spec || typeof spec !== 'object' || Array.isArray(spec)) specErr('spec must be an object');
  if (!NAME_RE.test(spec.name || '')) specErr(`bad node name: ${JSON.stringify(spec.name)}`);
  if (!BACKENDS.has(spec.backend)) specErr(`node "${spec.name}": backend must be "octave" or "external"`);

  for (const key of ['inputs', 'outputs']) {
    if (!Array.isArray(spec[key])) specErr(`node "${spec.name}": "${key}" must be an array`);
    const seen = new Set();
    spec[key].forEach((io, i) => {
      if (!NAME_RE.test(io.name || '')) specErr(`node "${spec.name}": ${key}[${i}].name invalid`);
      if (seen.has(io.name)) specErr(`node "${spec.name}": duplicate "${io.name}" in ${key}`);
      seen.add(io.name);
      if (!TYPES.has(io.type)) specErr(`node "${spec.name}": ${io.name}.type must be scalar|vector|matrix`);
      io.dtype = io.dtype || 'Float64';
      if (!DTYPES.has(io.dtype)) specErr(`node "${spec.name}": ${io.name}.dtype must be Float64|Int64|Bool`);
    });
  }
  const inNames = new Set(spec.inputs.map(i => i.name));
  for (const o of spec.outputs)
    if (inNames.has(o.name)) specErr(`node "${spec.name}": output "${o.name}" collides with an input`);

  if (spec.backend === 'external') {
    const c = spec.command || {};
    if (typeof c.program !== 'string' || !c.program) specErr(`node "${spec.name}": external needs command.program`);
    if (c.args !== undefined && (!Array.isArray(c.args) || c.args.some(a => typeof a !== 'string')))
      specErr(`node "${spec.name}": command.args must be an array of strings`);
    if (c.timeout !== undefined && !(Number.isFinite(c.timeout) && c.timeout > 0))
      specErr(`node "${spec.name}": command.timeout must be a positive number`);
  }
  spec.flags = Object.assign({ lossy: false, trusted: true }, spec.flags || {});
  spec.contract = spec.contract || {};
  return spec;
}

// ---------- Octave-шаблоны ----------
function octaveTypeCheck(v, type) {
  const fn = { matrix: 'ismatrix', vector: 'isvector', scalar: 'isscalar' }[type];
  return `  if ~${fn}(${v})\n    error('Err(ShapeError): input "${v}" must be a ${type}');\n  end\n`;
}

function generateOctaveFunction(spec) {
  const args = spec.inputs.map(i => i.name).join(', ');
  const outs = spec.outputs.map(o => o.name).join(', ');
  let checks = spec.inputs.map(i => octaveTypeCheck(i.name, i.type)).join('');
  if (spec.contract.square_input) {
    const m = spec.inputs.find(i => i.type === 'matrix');
    if (m) checks += `\n  [r, c] = size(${m.name});\n  if r ~= c\n    error('Err(ShapeError): "${m.name}" must be square');\n  end\n`;
  }
  return `%% ${spec.name}.m — автогенерировано generate_nodes.js
function [${outs}] = ${spec.name}(${args})
${checks}
% TODO: реализация численной схемы узла "${spec.name}"

error('Err(NotImplemented): node ${spec.name} is a stub');
endfunction
`;
}

function generateOctaveRunScript(spec) {
  const reads = spec.inputs.map(i => `  ${i.name} = load_triomat('${i.name}.triomat');`).join('\n') || '% (входов нет)';
  const outsN = spec.outputs.map((o, i) => `out${i}`).join(', ');
  const call = spec.inputs.map(i => i.name).join(', ');
  const assign = spec.outputs.map((o, i) => `  ${o.name} = out${i};`).join('\n');
  const saves = spec.outputs.map(o => `  save_triomat('${o.name}.triomat', ${o.name});`).join('\n') || '% (выходов нет)';
  return `%% run_${spec.name}.m — автогенерировано generate_nodes.js
% Загружаем входы
${reads}

[${outsN}] = ${spec.name}(${call});
${assign}

% Сохраняем выходы
${saves}
`;
}

// ---------- JS-мост: единый для octave и external ----------
function generateJsBridge(spec) {
  const writes = spec.inputs.map(i =>
`    writeTriomat1(path.join(workDir, '${i.name}.triomat'), '${i.dtype}', inputs.${i.name}.shape, { lossy: ${spec.flags.lossy}, trusted: ${spec.flags.trusted} }, inputs.${i.name}.values);`
  ).join('\n');
  const reads = spec.outputs.map(o =>
`    outputs.${o.name} = readTriomat(path.join(workDir, '${o.name}.triomat'));
    if (outputs.${o.name}.dtype !== '${o.dtype}')
      return ERR('TypeError', 'output "${o.name}": dtype=' + outputs.${o.name}.dtype + ', expected ${o.dtype}');`
  ).join('\n');
  const cmd = spec.backend === 'octave'
    ? `'octave', ['--no-gui', '--quiet', 'run_${spec.name}.m']`
    : JSON.stringify(spec.command.program) + ', ' + JSON.stringify(spec.command.args || []);
  const timeout = spec.backend === 'external' && spec.command.timeout ? `, timeout: ${spec.command.timeout}` : '';
  const doc = spec.inputs.map(i => `${i.name}: { shape: [...], values: [...] }`).join(', ');

  return `// sound_node_${spec.name}.js — автогенерировано generate_nodes.js. Не редактировать вручную.
// backend: ${spec.backend} | lossy: ${spec.flags.lossy} | trusted: ${spec.flags.trusted}
'use strict';
const { execFileSync } = require('child_process');
const path = require('path');
const { writeTriomat1, readTriomat } = require('./trio_io');

const ERR = (code, message) => ({ ok: false, error: { code, message } });

// inputs: { ${doc} }
// Возвращает { ok: true, outputs } или { ok: false, error: { code, message } } — ошибки как значения.
function runNode(inputs, workDir) {
  workDir = workDir || process.cwd();
  try {
${writes}
  } catch (e) { return ERR('ShapeError', String(e.message)); }

  try {
    execFileSync(${cmd}, { cwd: workDir, stdio: 'inherit'${timeout} });
  } catch (e) {
    return ERR(e.killed ? 'Timeout' : 'ProcessError', String(e.message));
  }

  try {
    const outputs = {};
${reads}
    return { ok: true, outputs };
  } catch (e) {
    const m = /Err\$(\\w+)\$/.exec(String(e.message));
    return ERR(m ? m[1] : 'ReadError', String(e.message));
  }
}

module.exports = { runNode };
`;
}

function generateManifest(specs) {
  return JSON.stringify({
    format: 'TRIOMAT1',
    generator: 'generate_nodes.js v2',
    nodes: specs.map(s => ({
      name: s.name, backend: s.backend, flags: s.flags,
      files: s.backend === 'octave'
        ? [`${s.name}.m`, `run_${s.name}.m`, `sound_node_${s.name}.js`]
        : [`sound_node_${s.name}.js`],
    })),
  }, null, 2);
}

function main() {
  const [specPath, outDir = './generated_nodes'] = process.argv.slice(2);
  if (!specPath) {
    console.error('Usage: node generate_nodes.js <spec.json | specs_dir> [out_dir]');
    process.exit(1);
  }
  const stat = fs.statSync(specPath);
  const files = stat.isDirectory()
    ? fs.readdirSync(specPath).filter(f => f.endsWith('.json')).sort()
    : [specPath];
  if (files.length === 0) { console.error('No .json specs found'); process.exit(1); }

  const specs = [];
  for (const f of files) {
    const parsed = JSON.parse(fs.readFileSync(f, 'utf8'));
    for (const s of Array.isArray(parsed) ? parsed : [parsed]) specs.push(validateSpec(s));
  }
  const names = new Set();
  for (const s of specs) {
    if (names.has(s.name)) specErr(`duplicate node name "${s.name}"`);
    names.add(s.name);
  }

  fs.mkdirSync(outDir, { recursive: true });
  for (const s of specs) {
    if (s.backend === 'octave') {
      fs.writeFileSync(path.join(outDir, `${s.name}.m`), generateOctaveFunction(s));
      fs.writeFileSync(path.join(outDir, `run_${s.name}.m`), generateOctaveRunScript(s));
    }
    fs.writeFileSync(path.join(outDir, `sound_node_${s.name}.js`), generateJsBridge(s));
  }
  fs.writeFileSync(path.join(outDir, 'manifest.json'), generateManifest(specs));
  console.log(`Generated ${specs.length} node(s) -> ${outDir}`);
}

main();
