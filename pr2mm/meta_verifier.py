class MetaVerifier:
    def __init__(self, rules):
        self.rules = rules
        self.errors = []
        self.context = {}

    def verify(self, ast):
        self.verify_functions(ast)
        self.verify_arrays(ast)
        self.verify_loops(ast)
        return self.errors

    def verify_functions(self, ast):
        for node in ast:
            if node[0] == 'call':
                func_name = node[1]
                args = node[2]
                if func_name in self.rules['functions']:
                    self.check_function_params(func_name, args)

    def verify_arrays(self, ast):
        for rule in self.rules['arrays']['checks']:
            if rule['type'] == 'bounds':
                self.check_array_bounds(ast)
            elif rule['type'] == 'init':
                self.check_array_init(ast)

    def verify_loops(self, ast):
        for rule in self.rules['loops']['conditions']:
            if rule['type'] == 'termination':
                self.check_loop_termination(ast)
            elif rule['type'] == 'step':
                self.check_loop_step(ast)

    def check_function_params(self, func_name, args):
        expected = self.rules['functions'][func_name]['params']
        for param, value in zip(expected.keys(), args):
            if not self.check_param(value, expected[param]):
                self.errors.append(f"Ошибка проверки параметра {param}")

    def check_param(self, value, spec):
        # Проверка типа и ограничений
        pass

    def check_array_bounds(self, ast):
        # Проверка выхода за границы
        pass

    def check_array_init(self, ast):
        # Проверка инициализации
        pass

    def check_loop_termination(self, ast):
        # Проверка условия завершения
        pass

    def check_loop_step(self, ast):
        # Проверка шага цикла
        pass
