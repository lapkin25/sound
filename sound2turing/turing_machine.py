class TuringMachine:
    def __init__(self, config):
        self.config = config
        self.tape = ['_'] * 1000  # Можно сделать динамическим
        self.head_position = 500
        self.current_state = config['initial_state']
        self.log = []
        self.max_steps = 10000  # Добавить как параметр

    # Добавить метод для динамического расширения ленты
    def extend_tape(self):
        if self.head_position >= len(self.tape):
            self.tape += ['_'] * 1000
        if self.head_position < 0:
            self.tape = ['_'] * 1000 + self.tape
            self.head_position += 1000

    # Модифицировать метод step
    def step(self):
        self.extend_tape()  # Динамическое расширение
        # Остальной код...
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

    def debug_mode(self):
        while True:
            input("Нажмите Enter для следующего шага...")
            self.step()
            self.print_tape()

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
        
        # Оптимизированная обработка результата
        result = [int(x) for x in result if x != '_']
        result.reverse()
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


class TuringMachineGraph:
    def __init__(self, transitions):
        self.graph = {}
        for (state, symbol), (next_state, _, _) in transitions.items():
            if state not in self.graph:
                self.graph[state] = {}
            if next_state not in self.graph[state]:
                self.graph[state][next_state] = []
            self.graph[state][next_state].append(symbol)

    def print_graph(self):
        for state, edges in self.graph.items():
            print(f"Состояние: {state}")
            for next_state, symbols in edges.items():
                print(f"  → {next_state} при символах: {', '.join(symbols)}")
