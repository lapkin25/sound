# mm_interp.py — интерпретатор MM-кода (стековая машина с задачами)

from collections import deque


class MMInterpreter:
    def __init__(self, code):
        self.funcs = {}
        self.main = []
        self._parse(code)
        self.steps = 0
        self.tasks_created = 0
        self.awaits = 0
        self.tasks = {}
        self.pending = deque()
        self.builtins = {
            'add': (2, lambda a, b: a + b),
            'sub': (2, lambda a, b: a - b),
            'mul': (2, lambda a, b: a * b),
            'div': (2, lambda a, b: a // b),
        }

    def _parse(self, code):
        current = None
        target = None
        name = None
        for raw in code.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith('FUNC '):
                name = line[5:].strip()
                current = {'params': [], 'body': [], 'labels': {}}
                target = current['body']
                continue
            if line == 'MAIN':
                current = None
                target = self.main
                continue
            if line == 'END':
                if current is not None:
                    self.funcs[name] = current
                    current = None
                    target = None
                continue
            if target is None:
                continue
            if line.startswith('PARAMS'):
                args = line[len('PARAMS'):].strip()
                current['params'] = args.split(',') if args else []
                continue
            if line.endswith(':'):
                current['labels'][line[:-1]] = len(target)
                continue
            target.append(line)

    def _build_labels(self, instrs):
        labels = {}
        for i, ins in enumerate(instrs):
            if ins.endswith(':'):
                labels[ins[:-1]] = i
        return labels

    def run(self):
        labels = self._build_labels(self.main)
        result = self.exec_block(self.main, labels, {}, [])
        return result

    def exec_block(self, instrs, labels, frame, stack):
        pc = 0
        result = None
        while pc < len(instrs):
            ins = instrs[pc]
            self.steps += 1
            parts = ins.split(None, 1)
            op = parts[0]
            arg = parts[1] if len(parts) > 1 else None
            if op == 'LOAD':
                if arg.lstrip('-').isdigit():
                    stack.append(int(arg))
                else:
                    stack.append(frame[arg])
            elif op == 'PUSH':
                stack.append(int(arg))
            elif op == 'STORE':
                frame[arg] = stack.pop()
            elif op == 'INC':
                stack.append(stack.pop() + 1)
            elif op == 'DEC':
                stack.append(stack.pop() - 1)
            elif op in ('ADD_OP', 'SUB_OP', 'MUL_OP', 'DIV_OP'):
                b = stack.pop()
                a = stack.pop()
                if op == 'ADD_OP':
                    stack.append(a + b)
                elif op == 'SUB_OP':
                    stack.append(a - b)
                elif op == 'MUL_OP':
                    stack.append(a * b)
                else:
                    stack.append(a // b)
            elif op == 'IFZ_JMP':
                if stack.pop() == 0:
                    pc = labels[arg]
                    continue
            elif op == 'JMP':
                pc = labels[arg]
                continue
            elif op == 'CALL':
                stack.append(self.run_call(arg, stack))
            elif op == 'RETURN':
                if stack:
                    result = stack.pop()
                return result
            elif op == 'SPAWN_TASK':
                arity, _ = self._fn_info(arg)
                args = [stack.pop() for _ in range(arity)][::-1]
                tid = self.tasks_created
                self.tasks_created += 1
                self.tasks[tid] = {'status': 'pending', 'fn': arg, 'args': args}
                self.pending.append(tid)
                stack.append(tid)
            elif op == 'AWAIT_TASK':
                self.awaits += 1
                tid = stack.pop()
                while self.tasks[tid]['status'] == 'pending':
                    if not self.pending:
                        raise RuntimeError('задача %d не найдена в очереди' % tid)
                    nxt = self.pending.popleft()
                    t = self.tasks[nxt]
                    if t['status'] == 'pending':
                        t['status'] = 'running'
                        t['result'] = self.run_call(t['fn'], t['args'])
                        t['status'] = 'done'
                stack.append(self.tasks[tid]['result'])
            elif op == 'EXIT':
                return stack[-1] if stack else None
            else:
                raise RuntimeError('неизвестная инструкция %s' % ins)
            pc += 1
        return result

    def _fn_info(self, name):
        if name in self.funcs:
            return len(self.funcs[name]['params']), None
        if name in self.builtins:
            return self.builtins[name][0], self.builtins[name][1]
        raise RuntimeError('неизвестная функция %s' % name)

    def run_call(self, fname, stack):
        arity, fn = self._fn_info(fname)
        args = [stack.pop() for _ in range(arity)][::-1]
        if fname in self.funcs:
            f = self.funcs[fname]
            frame = dict(zip(f['params'], args))
            return self.exec_block(f['body'], f['labels'], frame, [])
        return fn(*args)
