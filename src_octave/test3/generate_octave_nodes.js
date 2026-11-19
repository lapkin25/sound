// generate_octave_nodes.js
'use strict';
const fs = require('fs');
const path = require('path');

function validateSpec(spec) {
  if (!spec.name || typeof spec.name !== 'string') throw new Error('Missing/invalid "name"');
  if (!Array.isArray(spec.inputs)) throw new Error('Missing "inputs" array');
  if (!Array.isArray(spec.outputs)) throw new Error('Missing "outputs" array');
  spec.inputs.forEach((i, idx) => {
    if (!i.name || !i.type) throw new Error(`Input #${idx} missing name/type`);
  });
  spec.outputs.forEach((o, idx) => {
    if (!o.name || !o.type) throw new Error(`Output #${idx} missing name/type`);
  });
}

function typeCheckCode(name, type, dtype) {
  // В Octave нет строгой типизации, но мы делаем проверки форм
  if (type === 'matrix') {
    return `  if ~ismatrix(${name})\n    error('Err(ShapeError): input "${name}" must be a matrix');\n  end\n`;
  } else if (type === 'vector') {
    return `  if !isvector(${name})\n    error('Err(ShapeError): input "${name}" must be a vector');\n  end\n`;
  } else if (type === 'scalar') {
    return `  if !isscalar(${name})\n    error('Err(ShapeError): input "${name}" must be a scalar');\n  end\n`;
  }
  return '';
}

function generateFunctionFile(spec, outDir) {
  const name = spec.name;
  const inputs = spec.inputs;
  const outputs = spec.outputs;

  const argList = inputs.map(i => i.name).join(', ');
  const outList = outputs.map(o => o.name).join(', ');

  let checks = '';
  inputs.forEach(i => {
    checks += typeCheckCode(i.name, i.type, i.dtype);
  });

  // Доп. проверки по контракту
  if (spec.contract?.square_input) {
    const mName = inputs.find(i => i.type === 'matrix')?.name || 'M';
    checks += `\n  [r, c] = size(${mName});\n  if r ~= c\n    error('Err(ShapeError): "${mName}" must be square');\n  end\n`;
  }

  const template = `%% ${name}.m
function [${outList}] = ${name}(${argList})
${checks}

% TODO: вставить реализацию здесь
% Пример:
% n = size(${inputs[0].name}, 1);
% D = diag(sum(${inputs[0].name}, 2));
% L = D - ${inputs[0].name};
% ...

error('Err(NotImplemented): функция ${name} ещё не реализована');
endfunction
`;

  fs.writeFileSync(path.join(outDir, `${name}.m`), template);
  console.log(`Generated: ${path.join(outDir, name)}.m`);
}

function generateRunScript(spec, outDir) {
  const name = spec.name;
  const inFiles = spec.inputs.map(i => `"${i.name}.triomat"`).join(', ');
  const outFiles = spec.outputs.map(o => `"${o.name}.triomat"`).join(', ');

  // Читаем все входы через load_triomat, который у тебя уже есть
  const readLines = spec.inputs.map(i => `  ${i.name} = load_triomat('${i.name}.triomat');`).join('\n');

  const callArgs = spec.inputs.map(i => i.name).join(', ');
  const assignOut = spec.outputs.map((o, i) => `  ${o.name} = out${i};`).join('\n');
  const saveLines = spec.outputs.map((o, i) => `  save_triomat('${o.name}.triomat', ${o.name});`).join('\n');

  const template = `%% run_${name}.m — автогенерируемый скрипт
% Загружаем входы
${readLines}

% Вызываем узел
[${spec.outputs.map(o => `out${spec.outputs.indexOf(o)}`).join(', ')}] = ${name}(${callArgs});

${assignOut}

% Сохраняем выходы
${saveLines}
`;

  fs.writeFileSync(path.join(outDir, `run_${name}.m`), template);
  console.log(`Generated: run_${name}.m`);
}

function generateJsStub(spec, outDir) {
  const name = spec.name;
  const inNames = spec.inputs.map(i => i.name);
  const outNames = spec.outputs.map(o => o.name);

  const template = `// sound_node_${name}.js — заглушка для Trio Bridge
const { readTriomat, writeTriomat1 } = require('./readTriomat');

async function runNode(inputs, outputsDir) {
  // Чтение входов
  const data = {};
${inNames.map(n => `  data.${n} = readTriomat(inputs['${n}']);`).join('\n')}

  // TODO: здесь должен быть вызов внешнего процесса Octave:
  // execFileSync('octave', ['--no-gui', '--eval', 'run_${name}.m'])

  // Чтение выходов из .triomat
${outNames.map((n, i) => `  const res${i} = readTriomat('${n}.triomat');`).join('\n')}

  return {
${outNames.map((n, i) => `    ${n}: res${i}.matrix`).join(',\n')}
  };
}

module.exports = { runNode };
`;

  fs.writeFileSync(path.join(outDir, `sound_node_${name}.js`), template);
  console.log(`Generated: sound_node_${name}.js`);
}

function main() {
  const specPath = process.argv[2];
  const outDir = process.argv[3] || './octave_nodes';

  if (!specPath) {
    console.error('Usage: node generate_octave_nodes.js <spec.json> [output_dir]');
    process.exit(1);
  }

  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  validateSpec(spec);

  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  generateFunctionFile(spec, outDir);
  generateRunScript(spec, outDir);
  generateJsStub(spec, outDir);
}

main();
