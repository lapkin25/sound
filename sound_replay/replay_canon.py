"""Независимый реплеер sound-журналов.
Форматы: legacy (именованные узлы, инлайновые литералы),
canon 0.5.1 (t-id + ref/len), canon 0.5.3 (deref-канон, без ref/len).
Написан по канон-спецификации; журналы читаются только прогоном."""
import re

VAL = {'const','snoc','part','plus','lt','if','tail','len','ref','div','mod'}
LINE = re.compile(r'^\s*(\d+)\s+([a-z]+)\s+(.*?)\s*->\s*(.+?)\s*$')

def parse_val(s):
    s = s.strip()
    if s == 'nil': return []
    if s.startswith('['):
        inner = s[1:s.rfind(']')].strip()
        return [] if not inner else [int(x) for x in inner.replace(',', ' ').split()]
    return int(s)

def fmt(v):
    return '[' + ','.join(map(str, v)) + ']' if isinstance(v, list) else str(v)

def tdiv(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q

def replay(path, mode):                      # mode: 'legacy' | 'canon'
    env, errs, n = {}, [], 0
    for raw in open(path, encoding='utf-8'):
        raw = raw.rstrip('\n')
        if not raw.strip() or raw.lstrip().startswith('#'): continue
        m = LINE.match(raw)
        if not m:
            errs.append(f'не разобрана: {raw}'); continue
        n += 1
        ln, op, args, shown_s = m.group(1), m.group(2), m.group(3).split(), m.group(4)
        if op not in VAL:
            errs.append(f'{ln}: неизвестная операция {op}'); continue
        if op == 'const':
            a = [parse_val(args[1])]         # литерал легален только в const
        else:
            a = []
            for tok in args:
                if mode == 'legacy' and tok in env: a.append(env[tok])
                elif re.fullmatch(r'-?\d+', tok):   a.append(int(tok))
                elif tok in env:                    a.append(env[tok])
                else: errs.append(f'{ln}: {tok} не вычислен'); a.append(None)
        if any(x is None for x in a): continue
        if   op == 'snoc': v = list(a[0]) + [a[1]]
        elif op == 'part': v = a[0][a[1]]
        elif op == 'plus': v = a[0] + a[1]
        elif op == 'lt':   v = 1 if a[0] < a[1] else 0
        elif op == 'if':   v = a[1] if a[0] != 0 else a[2]
        elif op == 'tail': v = a[0][1:]
        elif op == 'len':  v = len(a[0])
        elif op == 'ref':  v = list(a[0])
        elif op == 'div':  v = tdiv(a[0], a[1])
        elif op == 'mod':  v = a[0] - tdiv(a[0], a[1]) * a[1]
        else:              v = a[0]              # const
        shown = parse_val(shown_s)
        if v != shown:
            errs.append(f'{ln}: {op} вычислено {fmt(v)}, показано {shown_s}')
        env[args[0] if mode == 'legacy' else f't{int(ln):04d}'] = v
    return n, errs
