class TuringMachine:
    def __init__(self, config):
        self.config = config
        self.tape = ['_'] * 1000  # Инициализация ленты
        self.head_position = 500  # Начальная позиция головки
        self.current_state = config['initial_state']
        self.log = []  # Для логирования

    def set_input(self, input_data):
        # Числа пишем в обратном порядке: младший бит — первым (LSB-first)
        num1 = [str(b) for b in input_data[0]][::-1]
        num2 = [str(b) for b in input_data[1]][::-1]

        max_len = max(len(num1), len(num2))
        num1 = num1 + ['0'] * (max_len - len(num1))  # нули дописываем со стороны старшего бита
        num2 = num2 + ['0'] * (max_len - len(num2))

        pos = self.head_position
        for bit in num1:
            self.tape[pos] = bit
            pos += 1
        self.tape[pos] = '#'  # меняем разделитель на '#'
        pos += 1
        for bit in num2:
            self.tape[pos] = bit
            pos += 1

    def step(self):
        current_symbol = self.tape[self.head_position]
        transition = self.config['transitions'].get((self.current_state, current_symbol))
        if transition:
            next_state, write_symbol, move = transition

            self.log.append({
                'step': len(self.log) + 1,
                'current_state': self.current_state,
                'symbol': current_symbol,
                'next_state': next_state,
                'write': write_symbol,
                'move': move,
                'head_pos': self.head_position
            })

            self.tape[self.head_position] = write_symbol

            if move == 'R':
                self.head_position += 1
            elif move == 'L':
                self.head_position -= 1
            elif move == 'N':
                pass

            self.current_state = next_state
            return True
        return False

   def run(self, max_steps=10000):
       steps = 0
       while steps < max_steps:
           if not self.step():
               break
           steps += 1
           if self.current_state == self.config['accept_state']:
               break
               
       if steps >= max_steps:
           print("\nПредупреждение: достигнуто максимальное количество шагов!")

    def get_output(self):
        try:
            sep = self.tape.index('#')
        except ValueError:
            return []
        result = []
        for symbol in self.tape[sep + 1:]:
            if symbol == '_':
                break
            result.append(int(symbol))
        result.reverse()  # Переворачиваем, так как храним младший бит первым
        while len(result) > 1 and result[0] == 0:  # Убираем незначащие нули
            result.pop(0)
        return result

    def print_commands(self):
        print("\nВсе команды машины Тьюринга:")
        for (state, symbol), (next_state, write, move) in sorted(self.config['transitions'].items()):
            print(f"({state}, {symbol}) → ({write}, {move}, {next_state})")

    def print_tape(self):
        start = max(0, self.head_position - 20)
        end = min(len(self.tape), self.head_position + 20)
        tape_view = ''.join(self.tape[start:end])
        
        # Создаем маркер позиции головки
        marker = ' ' * (self.head_position - start) + '^'
        
        print(f"\nСостояние ленты:")
        print(f"Лента: {tape_view}")
        print(f"Маркер: {marker}")
        print(f"Текущее состояние: {self.current_state}")
        print(f"Позиция головки: {self.head_position}")

    def print_log(self):
        print("\nПодробный лог выполнения:")
        print(f"{'Шаг':<5} | {'Текущее состояние':<15} | {'Символ':<5} | {'Следующее состояние':<15} | {'Запись':<5} | {'Движение':<5} | {'Позиция головки'}")
        print("-" * 80)
        
        for step in self.log:
            print(f"{step['step']:<5} | {step['current_state']:<15} | {step['symbol']:<5} | "
                  f"{step['next_state']:<15} | {step['write']:<5} | {step['move']:<5} | "
                  f"{step['head_pos']}")
