# run_tests.py — прогон PR-программ через парсер, транслятор и интерпретатор MM

from pr_parser import parse_program
from translator import translate_program
from mm_interp import MMInterpreter

TESTS = {
    'add.pr': (
        'def add(x, y) = x + y\nentry add(5, 3)',
        8,
    ),
    'ifz.pr': (
        'def check(x) = ifz(x, 0, 1)\nentry check(5)',
        1,
    ),
    'fib.pr': (
        'def add(x, y) = x + y\n'
        'def sub(x, y) = x - y\n'
        'def fib(n) = ifz(n, 0, ifz(sub(n, 1), 1, add(fib(sub(n, 1)), fib(sub(n, 2)))))\n'
        'entry fib(5)',
        5,
    ),
    'factorial.pr': (
        'def sub(x, y) = x - y\n'
        'def fact(n) = ifz(n, 1, mul(n, fact(sub(n, 1))))\n'
        'entry fact(5)',
        120,
    ),
    'ackermann.pr': (
        'def sub(x, y) = x - y\n'
        'def ack(m, n) = ifz(m, succ(n), ifz(n, ack(sub(m, 1), 1), ack(sub(m, 1), ack(m, sub(n, 1)))))\n'
        'entry ack(2, 3)',
        9,
    ),
    'async.pr': (
        'def add(x, y) = x + y\n'
        'def task(x) = spawn(add(x, 1))\n'
        'def main(x) = await(task(x))\n'
        'entry main(5)',
        6,
    ),
}


def main():
    print('%-14s %-10s %-10s %-6s %-8s %-7s %-7s' % (
        'тест', 'ожидание', 'получено', 'ок', 'шаги', 'задачи', 'awaits'))
    print('-' * 70)
    all_ok = True
    for fname, (src, expected) in TESTS.items():
        functions, entry = parse_program(src)
        mm = translate_program(functions, entry)
        with open(fname.replace('.pr', '.mm'), 'w') as fh:
            fh.write(mm + '\n')
        interp = MMInterpreter(mm)
        got = interp.run()
        ok = got == expected
        all_ok = all_ok and ok
        print('%-14s %-10s %-10s %-6s %-8d %-7d %-7d' % (
            fname, expected, got, 'да' if ok else 'НЕТ',
            interp.steps, interp.tasks_created, interp.awaits))
    print('-' * 70)
    print('ИТОГ:', 'все тесты пройдены' if all_ok else 'есть падения')

    print('\n--- MM-код для ackermann.pr ---')
    functions, entry = parse_program(TESTS['ackermann.pr'][0])
    print(translate_program(functions, entry))


if __name__ == '__main__':
    main()
