# translator.py — генератор MM-кода из AST языка PR


class MMCodeGenerator:
    def __init__(self):
        self.functions = {}
        self.main_code = []
        self.label_counter = 0

    def new_label(self, prefix):
        label = '%s_%d' % (prefix, self.label_counter)
        self.label_counter += 1
        return label

    def generate_function(self, name, params, body):
        self.functions[name] = {
            'params': params,
            'body': self.translate_expr(body),
        }

    def generate_main(self, entry_name, args):
        self.main_code = ['MAIN']
        for arg in args:
            self.main_code.append(self.translate_push(arg))
        self.main_code.append('CALL %s' % entry_name)
        self.main_code.append('EXIT')

    def translate_push(self, node):
        if node[0] == 'num':
            return 'PUSH %d' % node[1]
        return self.translate_expr(node)

    def translate_expr(self, node):
        kind = node[0]
        if kind == 'num':
            return 'LOAD %d' % node[1]
        if kind == 'var':
            return 'LOAD %s' % node[1]
        if kind == 'bin':
            return self.translate_binop(node)
        if kind == 'call':
            return self.translate_call(node)
        raise NotImplementedError('неизвестный узел %s' % kind)

    OP_MAP = {'+': 'ADD', '-': 'SUB', '*': 'MUL', '/': 'DIV'}

    def translate_binop(self, node):
        op = self.OP_MAP[node[1]]
        left = self.translate_expr(node[2])
        right = self.translate_expr(node[3])
        return '%s\n%s\n%s_OP' % (left, right, op)

    def translate_call(self, node):
        name, args = node[1], node[2]
        if name == 'ifz':
            return self.translate_ifz(args[0], args[1], args[2])
        if name == 'succ':
            return self.translate_expr(args[0]) + '\nINC'
        if name == 'spawn':
            return self.translate_spawn(args[0])
        if name == 'await':
            return self.translate_await(args[0])
        if name == 'prec':
            return self.translate_prec(args[0], args[1], args[2])
        parts = [self.translate_expr(a) for a in args]
        return '\n'.join(parts) + '\nCALL %s' % name

    def translate_ifz(self, cond, then, els):
        then_label = self.new_label('ifz_then')
        end_label = self.new_label('ifz_end')
        return (
            self.translate_expr(cond) + '\n'
            'IFZ_JMP %s\n' % then_label +
            self.translate_expr(els) + '\n'
            'JMP %s\n' % end_label +
            '%s:\n' % then_label +
            self.translate_expr(then) + '\n'
            '%s:' % end_label
        )

    def translate_spawn(self, inner):
        if inner[0] == 'call':
            parts = [self.translate_expr(a) for a in inner[2]]
            return '\n'.join(parts) + '\nSPAWN_TASK %s' % inner[1]
        raise NotImplementedError('spawn поддерживает только вызов функции')

    def translate_await(self, inner):
        if inner[0] == 'call' and inner[1] == 'spawn':
            return self.translate_spawn(inner[2][0]) + '\nAWAIT_TASK'
        return self.translate_expr(inner) + '\nAWAIT_TASK'

    def translate_prec(self, counter, base, step):
        if isinstance(step, str):
            step_name = step
        elif step[0] == 'var':
            step_name = step[1]
        elif step[0] == 'call':
            step_name = step[1]
        else:
            raise NotImplementedError('prec: третий аргумент должен быть именем функции')
        loop_label = self.new_label('prec_loop')
        end_label = self.new_label('prec_end')
        return (
            self.translate_expr(counter) + '\nSTORE COUNTER\n' +
            self.translate_expr(base) + '\nSTORE ACC\n' +
            '%s:\n' % loop_label +
            'LOAD COUNTER\n'
            'IFZ_JMP %s\n' % end_label +
            'LOAD COUNTER\n'
            'LOAD ACC\n'
            'CALL %s\n' % step_name +
            'STORE ACC\n'
            'LOAD COUNTER\n'
            'DEC\n'
            'STORE COUNTER\n'
            'JMP %s\n' % loop_label +
            '%s:\n' % end_label +
            'LOAD ACC'
        )

    def emit(self):
        lines = []
        for fname, f in self.functions.items():
            lines.append('FUNC %s' % fname)
            lines.append('PARAMS %s' % ','.join(f['params']))
            lines.append(f['body'])
            lines.append('RETURN')
            lines.append('END')
        lines.extend(self.main_code)
        return '\n'.join(lines)


def translate_program(functions, entry):
    gen = MMCodeGenerator()
    for name, f in functions.items():
        gen.generate_function(name, f['params'], f['body'])
    gen.generate_main(entry['name'], entry['args'])
    return gen.emit()
