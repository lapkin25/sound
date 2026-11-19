# golden_corpus.py
import json
import math
from sound_core3 import Value, ValueType, add, widen, narrow

def canon(v):
    if v.t == ValueType.INT: return str(v.v)
    if v.t == ValueType.FLOAT: return float(v.v).hex()
    if v.t == ValueType.BOOL: return "true" if v.v else "false"
    if v.t == ValueType.VEC: return "[" + ",".join(str(x) for x in v.v) + "]"
    if v.t == ValueType.CLOSURE: return "<closure>"
    if v.t == ValueType.ERR: return f"Err({v.v})"
    return "?"

def run_term_T06():
    # let x1 = 1 in let f = fun y -> x1+y in let x1 = 105 in f 5
    events = []
    x1 = Value.i(1)
    events.append(("bind", "x1", canon(x1)))

    def f_fn(env_snap, y):
        # env_snap — снимок окружения, где x1=1
        x1_snap = env_snap["x1"]
        return add(x1_snap, y)
    f = Value(ValueType.CLOSURE, (f_fn, {"x1": x1}))
    events.append(("bind", "f", canon(f)))

    x1_shadow = Value.i(105)
    events.append(("bind", "x1", canon(x1_shadow)))

    arg = Value.i(5)
    res = f.v[1]({"x1": x1}, arg)  # apply через fn из замыкания
    events.append(("result", canon(res)))
    return events

def run_all():
    terms = {
        "T06": run_term_T06,
        # сюда можно добавить T07, T08, ..., T17
    }
    corpus = {}
    for name, runner in terms.items():
        corpus[name] = runner()
    with open("golden_traces.json", "w") as f:
        json.dump(corpus, f, indent=2)

if __name__ == "__main__":
    run_all()
