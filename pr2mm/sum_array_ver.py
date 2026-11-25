class ArrayVerifier:
    def __init__(self, ast):
        self.ast = ast
        self.errors = []
        self.array_sizes = {}
        self.check_arrays()
        self.check_loops()
    
    def check_arrays(self):
        for node in self.ast:
            if node[0] == 'array':
                size = self.evaluate_expression(node[1])
                if size <= 0:
                    self.errors.append("Размер массива должен быть положительным")
                self.array_sizes[node[2]] = size
            elif node[0] == 'index':
                array_name = node[1]
                index = self.evaluate_expression(node[2])
                if array_name not in self.array_sizes:
                    self.errors.append(f"Массив {array_name} не инициализирован")
                elif index < 0 or index >= self.array_sizes[array_name]:
                    self.errors.append(f"Выход за границы массива {array_name}")
    
    def check_loops(self):
        for node in self.ast:
            if node[0] == 'for':
                init = node[1]
                cond = node[2]
                step = node[3]
                if not self.check_loop_conditions(init, cond, step):
                    self.errors.append("Некорректные условия цикла")
    
    def evaluate_expression(self, expr):
        # Простая оценка выражений для верификации
        if expr[0] == 'num':
            return expr[1]
        elif expr[0] == 'var':
            return self.get_variable_value(expr[1])
        elif expr[0] == 'bin':
            left = self.evaluate_expression(expr[2])
            right = self.evaluate_expression(expr[3])
            op = expr[1]
            if op == '+':
                return left + right
            elif op == '-':
                return left - right
            # Добавить остальные операции
    
    def report(self):
        if self.errors:
            return f"Верификация не пройдена:\n" + "\n".join(self.errors)
        return "Верификация прошла успешно"
