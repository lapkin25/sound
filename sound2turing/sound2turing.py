class SoundToTuringCompiler:
    SYMBOLS = ('0', '1', '#', '_')

    def __init__(self, sound_program):
        self.program = sound_program
        self.transitions = {}
        self.functions = {}
        for fn_name, fn_def in sound_program['fns'].items():
            self.functions[fn_name] = {
                'params': fn_def['params'],
                'slots': fn_def['slots'],
                'code': fn_def['code'],
            }
        self.label_counter = 0

    def get_next_state(self, suffix=''):
        self.label_counter += 1
        return f"q{self.label_counter}{suffix}"

    def compile(self):
        entry = self.program['entry']
        self.compile_function(entry)
        return {
            'alphabet': set(self.SYMBOLS),
            'initial_state': f"q_{entry}_start",
            'accept_state': 'q_accept',
            'transitions': dict(self.transitions),
        }

    def compile_function(self, fn_name):
        code = self.functions[fn_name]['code']
        state = f"q_{fn_name}_start"
        for instr in code:
            op = instr[0]
            if op == 'ADD':
                state = self.compile_add(state)
            elif op == 'RET':
                state = self.compile_return(state)
            else:
                # LOAD / STORE / PUSH / CALL — пока заглушки:
                # не трогаем ни ленту, ни головку ('N' = стоим на месте)
                nxt = self.get_next_state('_nop')
                for sym in self.SYMBOLS:
                    self.transitions[(state, sym)] = (nxt, sym, 'N')
                state = nxt
        return state


    def compile_add(self, start):
        # Состояния для обработки
        read1 = self.get_next_state('_read1')
        read2 = self.get_next_state('_read2')
        write = self.get_next_state('_write')
        carry = self.get_next_state('_carry')
        done = self.get_next_state('_done')

        # Начальная позиция - поиск первого числа
        self.transitions[(start, '_')] = (start, '_', 'R')
        self.transitions[(start, '0')] = (read1, '0', 'R')
        self.transitions[(start, '1')] = (read1, '1', 'R')

        # Чтение первого числа
        for bit in self.SYMBOLS:
            self.transitions[(read1, bit)] = (read2, bit, 'R')

        # Чтение второго числа
        for bit1 in ['0', '1']:
            for bit2 in ['0', '1']:
                self.transitions[(read2, bit2)] = (write, bit2, 'L')

                # Логика сложения
                if bit1 == '0' and bit2 == '0':
                    self.transitions[(write, bit1)] = (done, '0', 'L')
                elif bit1 == '0' and bit2 == '1':
                    self.transitions[(write, bit1)] = (done, '1', 'L')
                elif bit1 == '1' and bit2 == '0':
                    self.transitions[(write, bit1)] = (done, '1', 'L')
                elif bit1 == '1' and bit2 == '1':
                    self.transitions[(write, bit1)] = (carry, '0', 'L')

        # Обработка переноса
        self.transitions[(carry, '0')] = (done, '1', 'L')
        self.transitions[(carry, '1')] = (carry, '0', 'L')
        self.transitions[(carry, '#')] = (done, '#', 'L')

        # Завершение работы
        self.transitions[(done, '_')] = ('q_accept', '_', 'N')
        self.transitions[(done, '0')] = (done, '0', 'L')
        self.transitions[(done, '1')] = (done, '1', 'L')
        self.transitions[(done, '#')] = (done, '#', 'L')

        return start


    def compile_return(self, state):
        for sym in self.SYMBOLS:
            self.transitions[(state, sym)] = ('q_accept', sym, 'N')
        return 'q_accept'

    def compile_sub(self, state):
        # Пока не реализовано: ведём себя как заглушка, чтобы не ломать проход
        nxt = self.get_next_state('_sub_nop')
        for sym in self.SYMBOLS:
            self.transitions[(state, sym)] = (nxt, sym, 'N')
        return nxt
