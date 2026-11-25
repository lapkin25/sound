# translator.py — транслятор PR в MM

class MMCodeGenerator:
    def __init__(self):
        self.functions = {}
        self.main_code = []
        self.label_counter = 0

    def generate_function(self, name, params, body):
        self.functions[name] = {
            'params': params,
            'body': self.translate_expr(body)
        }

    def generate_main(self, entry_name, args):
        self.main_code.append("MAIN")
        for arg in args:
            self.main_code.append(f"PUSH {self.translate_expr(arg)}")
        self.main_code.append(f"CALL {entry_name}")
        self.main_code.append("EXIT")

    def translate_expr(self, node):
        if node[0] == "num":
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

    def translate_binop(self, node):
        left = self.translate_expr(node[2])
        right = self.translate_expr(node[3])
        op = node[1].upper()
        return f"{left}\n{right}\n{op}_OP"

    def translate_call(self, node):
        func_name = node[1]
        args = [self.translate_expr(arg) for arg in node[2]]
        return f"{'\n'.join(args)}\nCALL {func_name}"

    def translate_ifz(self, node):
        cond = self.translate_expr(node[1])
        true_branch = self.translate_expr(node[2])
        false_branch = self.translate_expr(node[3])
        label = f"ifz_label_{self.label_counter}"
        self.label_counter += 1
        return (
            f"{cond}\n"
            f"IFZ_JMP {label}\n"
            f"{false_branch}\n"
            f"JMP ifz_end_{self.label_counter}\n"
            f"{label}:\n"
            f"{true_branch}\n"
            f"ifz_end_{self.label_counter}:\n"
        )

    def translate_spawn(self, node):
        inner = self.translate_expr(node[1])
        return f"{inner}\nCREATE_TASK"

    def translate_await(self, node):
        spawn_expr = self.translate_expr(node[1])
        return f"{spawn_expr}\nAWAIT_OP"

    def translate_prec(self, node):
        counter = self.translate_expr(node[1])
        base = self.translate_expr(node[2])
        step_func = node[3][1]
        loop_label = f"prec_loop_{self.label_counter}"
        end_label = f"prec_end_{self.label_counter}"
        self.label_counter += 1
        return (
            f"{counter}\n"
            f"STORE COUNTER\n"
            f"{base}\n"
            f"STORE ACC\n"
            f"{loop_label}:\n"
            f"LOAD COUNTER\n"
            f"IFZ_JMP {end_label}\n"
            f"LOAD ACC\n"
            f"LOAD COUNTER\n"
            f"CALL {step_func}\n"
            f"STORE ACC\n"
