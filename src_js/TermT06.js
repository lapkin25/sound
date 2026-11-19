// TermT06.js
const { SoundValue, Trace } = require('./SoundValue');
const Ops = require('./Ops');

// Терм T06: замыкание, которое возвращает 6.
// Важно: лексический захват значения, а не переменной.
function termT06() {
  const x = SoundValue.intOf(1n);
  const y = SoundValue.intOf(5n);

  // bind событий по контракту
  Trace.bind('x', x);
  Trace.bind('y', y);

  const sum = Ops.add(x, y);
  Trace.bind('sum', sum);

  Trace.result(sum);
  // Ожидаемый вывод:
  // bind x 1
  // bind y 5
  // bind sum 6
  // result 6
}

termT06();
