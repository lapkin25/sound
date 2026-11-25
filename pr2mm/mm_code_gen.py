class MMCodeGenerator:
    def __init__(self):
        self.functions = {}
        self.main_code = []
        self.label_counter = 0
        self.verification_rules = {}  # Хранилище правил верификации

    def load_verification_rules(self, rules):
        self.verification_rules = rules

    def verify_ast(self, ast):
        # Базовая структура верификации
        for node in ast:
            if node[0] == 'call':
                self.verify_function_call(node)
            elif node[0] == 'bin':
                self.verify_binary_operation(node)
            # Добавить другие проверки

    def verify_function_call(self, node):
        func_name = node[1]
        args = node[2]
        if func_name in self.verification_rules['functions']:
            expected_params = self.verification_rules['functions'][func_name]['params']
            if len(args) != len(expected_params):
                raise ValueError(f"Неверное количество аргументов для {func_name}")
            # Добавить проверку типов и значений

    def verify_binary_operation(self, node):
        op = node[1]
        if op not in self.verification_rules['operations']:
            raise ValueError(f"Недопустимая операция {op}")
        # Добавить проверку операндов

    # Остальные методы класса...
