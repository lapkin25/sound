class MMCodeGenerator:
    def __init__(self):
        self.functions = {}
        self.main_code = []
        self.label_counter = 0
        self.array_counter = 0  # Для генерации уникальных имен массивов

    # Добавляем поддержку массивов
    def translate_array(self, node):
        array_name = f"array_{self.array_counter}"
        self.array_counter += 1
        size = self.translate_expr(node[1])
        return (
            f"CREATE_ARRAY {size}\n"
            f"STORE {array_name}"
        )

    def translate_index(self, node):
        array = self.translate_expr(node[1])
        index = self.translate_expr(node[2])
        return f"{array}\n{index}\nLOAD_INDEX"

    def translate_assign(self, node):
        array = self.translate_expr(node[1])
        index = self.translate_expr(node[2])
        value = self.translate_expr(node[3])
        return (
            f"{array}\n"
            f"{index}\n"
            f"{value}\n"
            f"STORE_INDEX"
        )

    def translate_for(self, node):
        init = self.translate_expr(node[1])
        cond = self.translate_expr(node[2])
        step = self.translate_expr(node[3])
        body = self.translate_expr(node[4])
        loop_label = f"for_loop_{self.label_counter}"
        end_label = f"for_end_{self.label_counter}"
        self.label_counter += 1
        return (
            f"{init}\n"
            f"{loop_label}:\n"
            f"{cond}\n"
            f"IFZ_JMP {end_label}\n"
            f"{body}\n"
            f"{step}\n"
            f"JMP {loop_label}\n"
            f"{end_label}:\n"
        )

    # Обновленный метод translate_expr с поддержкой новых конструкций
    def translate_expr(self, node):
        if node[0] == "array":
            return self.translate_array(node)
        elif node[0] == "index":
            return self.translate_index(node)
        elif node[0] == "assign":
            return self.translate_assign(node)
        elif node[0] == "for":
            return self.translate_for(node)
        elif node[0] == "num":
            return f"LOAD {node[1]}"
        elif node[0] == "var":
            return f"LOAD {node[1]}"
        elif node[0] == "bin":
            return self.translate_binop(node)
        elif node[0] == "call":
            return self.translate_call(node)
        elif node[0] == "ifz":
            return self.translate_ifz(node)
        elif node[0] == "spawn":
            return self.translate_spawn(node)
        elif node[0] == "await":
            return self.translate_await(node)
        elif node[0] == "prec":
            return self.translate_prec(node)
        raise NotImplementedError(f"Неизвестный узел {node[0]}")

    def generate_phi_functions(self):
        # Добавляем функцию gcd
        self.generate_function(
            "gcd",
            ["a", "b"],
            ("ifz", ("var", "b"), ("var", "a"), 
             ("call", "gcd", [("var", "b"), ("bin", "mod", ("var", "a"), ("var", "b"))])
            )
        )
        
        # Добавляем функцию is_coprime
        self.generate_function(
            "is_coprime",
            ["a", "b"],
            ("call", "gcd", [("var", "a"), ("var", "b")]),
            ("ifz", ("var", "gcd_result"), 1, 0)
        )
        
        # Добавляем оптимизированную функцию phi
        self.generate_function(
            "phi_optimized",
            ["n"],
            ("let", "result", ("var", "n"),
             ("let", "i", 2,
              ("while", ("bin", "<=", ("bin", "*", ("var", "i"), ("var", "i")), ("var", "n")),
               ("if", ("bin", "==", ("bin", "mod", ("var", "n"), ("var", "i")), 0),
                ("block",
                 ("assign", ("var", "result"), 
                  ("bin", "-", ("var", "result"), 
                   ("bin", "/", ("var", "result"), ("var", "i")))),
                 ("while", ("bin", "==", ("bin", "mod", ("var", "n"), ("var", "i")), 0),
                  ("assign", ("var", "n"), 
                   ("bin", "/", ("var", "n"), ("var", "i"))))),
                ("assign", ("var", "i"), ("bin", "+", ("var", "i"), 1)))),
              ("if", ("bin", ">", ("var", "n"), 1),
               ("assign", ("var", "result"), 
                ("bin", "-", ("var", "result"), 
                 ("bin", "/", ("var", "result"), ("var", "n"))))),
             ("return", ("var", "result"))
            )
        )

    def generate_main_phi_test(self):
        self.generate_main("phi_optimized", [36])  # Тестовый случай

# Пример использования
if __name__ == "__main__":
    gen = MMCodeGenerator()
    gen.generate_phi_functions()
    gen.generate_main_phi_test()
    print(gen.emit())

