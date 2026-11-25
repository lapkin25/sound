# pr_parser.py — парсер языка PR (рекурсивный спуск)

import re

TOKEN_SPEC = [
    ('NUM',    r'\d+'),
    ('DEF',    r'def\b'),
    ('ENTRY',  r'entry\b'),
    ('IFZ',    r'ifz\b'),
    ('SUCC',   r'succ\b'),
    ('SPAWN',  r'spawn\b'),
    ('AWAIT',  r'await\b'),
    ('PREC',   r'prec\b'),
    ('ID',     r'[A-Za-z_]\w*'),
    ('OP',     r'[+\-*/]'),
    ('LPAREN', r'\('),
    ('RPAREN', r'\)'),
    ('COMMA',  r','),
    ('EQ',     r'='),
    ('WS',     r'\s+'),
]

NAME_KINDS = ('ID', 'IFZ', 'SUCC', 'SPAWN', 'AWAIT', 'PREC')


class PRParser:
    def __init__(self, text):
        self.tokens = self.tokenize(text)
        self.pos = 0

    # --- лексер ---
    def tokenize(self, text):
        regex = '|'.join('(?P<%s>%s)' % (k, v) for k, v in TOKEN_SPEC)
        tokens = []
        for mo in re.finditer(regex, text):
            kind = mo.lastgroup
            if kind == 'WS':
                continue
            tokens.append((kind, mo.group()))
        return tokens

    # --- служебные методы ---
    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ('EOF', '')

    def peek_kind(self):
        return self.peek()[0]

    def consume(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, kind):
        tok = self.consume()
        if tok[0] != kind:
            raise SyntaxError('ожидался %s, получен %s "%s"' % (kind, tok[0], tok[1]))
        return tok[1]

    def at_end(self):
        return self.pos >= len(self.tokens)

    # --- программа ---
    def parse(self):
        functions = {}
        entry = None
        while not self.at_end():
            kind = self.peek_kind()
            if kind == 'DEF':
                f = self.parse_function()
                functions[f['name']] = f
            elif kind == 'ENTRY':
                entry = self.parse_entry()
            else:
                raise SyntaxError('неожиданный токен %s' % (self.peek(),))
        if entry is None:
            raise SyntaxError('не найдена точка входа entry')
        return functions, entry

    def parse_function(self):
        self.expect('DEF')
        name = self.expect('ID')
        params = self.parse_params()
        self.expect('EQ')
        body = self.parse_expr()
        return {'name': name, 'params': params, 'body': body}

    def parse_params(self):
        self.expect('LPAREN')
        params = []
        if self.peek_kind() != 'RPAREN':
            params.append(self.expect('ID'))
            while self.peek_kind() == 'COMMA':
                self.consume()
                params.append(self.expect('ID'))
        self.expect('RPAREN')
        return params

    def parse_entry(self):
        self.expect('ENTRY')
        name = self.expect('ID')
        self.expect('LPAREN')
        args = []
        if self.peek_kind() != 'RPAREN':
            args.append(self.parse_expr())
            while self.peek_kind() == 'COMMA':
                self.consume()
                args.append(self.parse_expr())
        self.expect('RPAREN')
        return {'name': name, 'args': args}

    # --- выражения с приоритетом * / над + - ---
    def parse_expr(self):
        return self.parse_additive()

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.peek_kind() == 'OP' and self.peek()[1] in ('+', '-'):
            op = self.consume()[1]
            right = self.parse_multiplicative()
            left = ('bin', op, left, right)
        return left

    def parse_multiplicative(self):
        left = self.parse_atom()
        while self.peek_kind() == 'OP' and self.peek()[1] in ('*', '/'):
            op = self.consume()[1]
            right = self.parse_atom()
            left = ('bin', op, left, right)
        return left

    def parse_atom(self):
        kind, val = self.peek()
        if kind == 'NUM':
            self.consume()
            return ('num', int(val))
        if kind in NAME_KINDS:
            self.consume()
            if self.peek_kind() == 'LPAREN':
                self.consume()
                args = []
                if self.peek_kind() != 'RPAREN':
                    args.append(self.parse_expr())
                    while self.peek_kind() == 'COMMA':
                        self.consume()
                        args.append(self.parse_expr())
                self.expect('RPAREN')
                return ('call', val, args)
            return ('var', val)
        if kind == 'LPAREN':
            self.consume()
            expr = self.parse_expr()
            self.expect('RPAREN')
            return expr
        raise SyntaxError('неожиданный токен %s "%s"' % (kind, val))


def parse_program(text):
    return PRParser(text).parse()
