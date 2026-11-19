// generate_octave_node.js

// запуск: node generate_octave_node.js

const fs = require('fs');

function generateOctaveNode(spec) {
  const name = spec.name;
  const inputs = Object.keys(spec.input);
  const outputs = Object.values(spec.output);

  let args = inputs.join(', ');
  let argChecks = '';

  inputs.forEach(inp => {
    const t = spec.input[inp];
    if (t.startsWith('matrix')) {
      argChecks += `  if ~ismatrix(${inp})\n    error('Err(ShapeError)');\n  end\n`;
    } else if (t.startsWith('vector')) {
      argChecks += `  if !isvector(${inp})\n    error('Err(ShapeError)');\n  end\n`;
    }
  });

  const template = `%% ${name}.m
function [${outputs.join(', ')}] = ${name}(${args})
${argChecks}
% TODO: вставить реализацию
endfunction
`;
  return template;
}

// Пример использования
const spec = {
  name: 'current_flow_betweenness',
  input: { graph: 'matrix[double]' },
  output: { bc: 'vector[double]' }
};

fs.writeFileSync('current_flow_betweenness.m', generateOctaveNode(spec));
console.log('Generated current_flow_betweenness.m');
