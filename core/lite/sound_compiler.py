#!/usr/bin/env python3
"""sound_compiler.py — прототип компилятора Sound v0.1: спека -> граф Trio.

Что делает:
  1. парсит spec-файл (fact / rule / wire / invariant);
  2. собирает граф узлов и рёбер с типами и режимами передачи;
  3. проверяет правила спеки Trio:
       R-DIM5/6/7 — унификация размеров, привязка DimVar, несходящиеся
                    размеры = ошибка связывания (ShapeError на границе);
       R-ERR1     — полнота обработки ошибок на рёбрах Result;
       R-STREAM1  — move запрещён для Stream;
       R-MAT1     — view между разными dtype понижается до copy (warning);
  4. строит звуковую партитуру: узел -> нота по рантайму
     (octave: 110 Гц, java: 220 Гц, python: 440 Гц, факт: 880 Гц),
     инварианты звучат чистой квинтой;
  5. рендерит score.wav (статическая репетиция графа).

Запуск: python sound_compiler.py pipeline.sound
"""
import json
import math
import re
import sys
import wave

import numpy as np

RUNTIMES = {"python", "java", "octave"}
SCALARS = {"Int64", "Float64", "Float32", "Bool", "String"}
DTYPES = {"F64": "Float64", "F32": "Float32", "I64": "Int64", "Bool": "Bool"}
INT64_LIMIT = 2 ** 53

PITCH = {"octave": 110.0, "java": 220.0, "python": 440.0, "fact": 880.0}
DUR = {"octave": 0.6, "java": 0.35, "python": 0.2, "fact": 0.08}
AMP = {"octave": 0.9, "java": 0.8, "python": 0.7, "fact": 0.6}


class SoundParseError(Exception):
    pass


# ---------------------------------------------------------------- типы

def _split_top(s):
    parts, depth, cur = [], 0, []
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur).strip())
    return parts


def parse_type(s):
    s = s.strip()
    if s in SCALARS:
        return {"kind": "scalar", "name": s}
    m = re.fullmatch(r"(Stream|Result|Matrix|Vector)\[(.*)\]", s)
    if not m:
        raise SoundParseError(f"неизвестный тип: {s!r}")
    kw, inner = m.group(1), m.group(2)
    if kw == "Stream":
        return {"kind": "Stream", "elem": parse_type(inner)}
    if kw == "Result":
        parts = _split_top(inner)
        if len(parts) != 2:
            raise SoundParseError(f"Result требует [T, Err]: {s!r}")
        return {"kind": "Result", "ok": parse_type(parts[0]), "err": parts[1].strip()}
    parts = _split_top(inner)
    dtype = parts[0].strip()
    if dtype not in DTYPES:
        raise SoundParseError(f"неизвестный dtype: {dtype!r}")
    dims = []
    for d in parts[1:]:
        d = d.strip()
        if d != "?" and not (d.isdigit() or d.isidentifier()):
            raise SoundParseError(f"некорректная размерность: {d!r}")
        dims.append("?" if d == "?" else (int(d) if d.isdigit() else d))
    return {"kind": kw, "dtype": DTYPES[dtype], "dims": dims}


def unify_dims(d1, d2, env, where, errors):
    """R-DIM5/R-DIM6: унификация размеров; DimVar привязывается первым значением."""
    if len(d1) != len(d2):
        errors.append(f"{where}: ранг {len(d1)} != {len(d2)} (R-DIM7)")
        return False
    ok = True
    for a, b in zip(d1, d2):
        if isinstance(a, int) and isinstance(b, int):
            if a != b:
                errors.append(f"{where}: размер {a} != {b} (R-DIM7)")
                ok = False
        elif isinstance(a, int):
            if isinstance(b, str) and b != "?":
                if env.get(b, a) != a:
                    errors.append(f"{where}: DimVar {b} уже связан со значением "
                                  f"{env[b]}, конфликт с {a} (R-DIM6)")
                    ok = False
                else:
                    env[b] = a
        elif isinstance(b, int):
            if isinstance(a, str) and a != "?":
                if env.get(a, b) != b:
                    errors.append(f"{where}: DimVar {a} уже связан со значением "
                                  f"{env[a]}, конфликт с {b} (R-DIM6)")
                    ok = False
                else:
                    env[a] = b
        elif a == "?" or b == "?":
            pass  # неизвестный размер совместим с DimVar; связка — в рантайме (R-DIM5)
        elif a != b:
            errors.append(f"{where}: несовместимые DimVar {a} и {b}")
            ok = False
    return ok


def unify_types(t1, t2, env, where, errors):
    """t1 — тип источника, t2 — тип приёмника. Возвращает конверсию ребра:
    None — точная; 'lossy:repr' / 'lossy:precision' — объявленная потеря."""
    if t1["kind"] != t2["kind"]:
        errors.append(f"{where}: несоответствие типов {t1['kind']} и {t2['kind']}")
        return None
    if t1["kind"] == "scalar":
        if t1["name"] == t2["name"]:
            return None
        conv = _SCALAR_CONV.get((t1["name"], t2["name"]), _FORBIDDEN)
        if conv is _FORBIDDEN:
            errors.append(f"{where}: конверсия {t1['name']} -> {t2['name']} "
                          f"не определена (UndefinedBridge)")
        return conv
    if t1["kind"] == "Stream":
        return unify_types(t1["elem"], t2["elem"], env, where, errors)
    if t1["kind"] == "Result":
        return unify_types(t1["ok"], t2["ok"], env, where, errors)
    # Matrix / Vector
    if t1["dtype"] == t2["dtype"]:
        if not unify_dims(t1["dims"], t2["dims"], env, where, errors):
            return None
        return None
    conv = _SCALAR_CONV.get((t1["dtype"], t2["dtype"]), _FORBIDDEN)
    if conv is _FORBIDDEN:
        errors.append(f"{where}: конверсия {t1['dtype']} -> {t2['dtype']} "
                      f"не определена (UndefinedBridge)")
        return None
    if not unify_dims(t1["dims"], t2["dims"], env, where, errors):
        return None
    return conv


_FORBIDDEN = object()
_SCALAR_CONV = {
    ("Float32", "Float64"): None,          # расширение — OK (R-FLT1)
    ("Float64", "Float32"): "lossy:precision",
    ("Int64", "Float64"): "lossy:repr",    # R-INT2
    ("Int64", "Float32"): "lossy:precision",
}


RE_FACT = re.compile(r"^fact\s+(\w+)\s*->\s*(.+)$")
RE_RULE = re.compile(r"^rule\s+(\w+)\s*\((.*?)\)\s*(?:requires\s+(.+?)\s*)?->\s*(.+)$")
RE_WIRE = re.compile(r"^wire\s+([\w.]+)\s*=\s*(.+)$")
RE_INV = re.compile(r"^invariant\s+(.+)$")

RE_CLAUSE_RANGE = re.compile(r"^\w+\s+in\s+\[\s*-?\d+\s*,\s*-?\d+\s*\]$")
RE_CLAUSE_MOD = re.compile(r"^\w+\s*%\s*\d+\s*==\s*\d+$")
RE_CLAUSE_CMP = re.compile(r"^\w+\s*(?:>|<|>=|<=|==|!=)\s*-?\d+(?:\.\d+)?$")


def _strip_runtime(stmt):
    m = re.match(r"^(.*?)#\s*(\w+)\s*$", stmt)
    if m and m.group(2) in RUNTIMES:
        return m.group(1).strip(), m.group(2)
    return stmt.strip(), None


def _split_statements(body):
    """Разбивает тело спеки на утверждения. Комментарий-рантайм (# python и т.п.)
    может стоять на любой строке утверждения — собираем его по всему утверждению."""
    out, cur_code, cur_comment = [], [], None
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        c = line.find("#")
        code, comment = (line[:c].rstrip(), line[c + 1:].strip()) if c >= 0 else (line, "")
        if comment and re.fullmatch(r"(python|java|octave)", comment):
            cur_comment = comment
        if code:
            cur_code.append(code)
        if code.endswith(";"):
            stmt = " ".join(cur_code).strip()
            stmt = stmt[:-1].rstrip()
            if cur_comment:
                stmt = f"{stmt} #{cur_comment}"
            out.append(stmt)
            cur_code, cur_comment = [], None
    if cur_code:
        raise SoundParseError("незавершённое утверждение (нет ';'): " + " ".join(cur_code))
    return out


def parse_spec(text):
    m = re.search(r"^spec\s+(\w+)\s*\{(.*)\}\s*$", text, re.S | re.M)
    if not m:
        raise SoundParseError("не найден блок spec NAME { ... }")
    name, body = m.group(1), m.group(2)
    if "{" in body or "}" in body:
        raise SoundParseError("вложенные блоки не поддерживаются в v0.1")

    nodes, wires, invariants = {}, [], []
    for raw in _split_statements(body):
        stmt, runtime = _strip_runtime(raw)
        kind = stmt.split(None, 1)[0]
        if kind == "fact":
            mm = RE_FACT.match(stmt)
            if not mm:
                raise SoundParseError("не разобран fact: " + stmt)
            nodes[mm.group(1)] = {
                "name": mm.group(1), "kind": "fact", "runtime": runtime or "python",
                "inputs": {}, "output": parse_type(mm.group(2)), "requires": [],
            }
        elif kind == "rule":
            mm = RE_RULE.match(stmt)
            if not mm:
                raise SoundParseError("не разобран rule: " + stmt)
            inputs = {}
            for arg in _split_top(mm.group(2)):
                pname, ptype = arg.split(":", 1)
                inputs[pname.strip()] = parse_type(ptype)
            nodes[mm.group(1)] = {
                "name": mm.group(1), "kind": "rule", "runtime": runtime,
                "inputs": inputs, "output": parse_type(mm.group(4)),
                "requires": [mm.group(3)] if mm.group(3) else [],
            }
        elif kind == "wire":
            mm = RE_WIRE.match(stmt)
            if not mm:
                raise SoundParseError("не разобран wire: " + stmt)
            dst, rhs = mm.group(1), mm.group(2)
            handle = None
            h = re.search(r"\s*handle\s*\[([^\]]*)\]\s*$", rhs)
            if h:
                handle = [x.strip() for x in h.group(1).split(",") if x.strip()]
                rhs = rhs[:h.start()].strip()
            mode = "copy"
            w = re.search(r"\s*as\s+(view|move|copy)\s*$", rhs)
            if w:
                mode, rhs = w.group(1), rhs[:w.start()].strip()
            wires.append({"dst": dst, "src": rhs, "mode": mode, "handle": handle})
        elif kind == "invariant":
            invariants.append(RE_INV.match(stmt).group(1).strip())
        else:
            raise SoundParseError("неизвестное утверждение: " + stmt)
    return {"name": name, "nodes": nodes, "wires": wires, "invariants": invariants}


# ---------------------------------------------------------------- проверки

def check_requires(node, errors):
    """v0.1: проверка формы ограничений; исполнение — на границе узла (R-OPT/R-NAN)."""
    for clause_full in node["requires"]:
        for clause in clause_full.split(" and "):
            clause = clause.strip()
            if not (RE_CLAUSE_RANGE.match(clause) or RE_CLAUSE_MOD.match(clause)
                    or RE_CLAUSE_CMP.match(clause)):
                errors.append(f"{node['name']}: неизвестная форма ограничения "
                              f"{clause!r} (v0.1 понимает 'x in [a,b]', "
                              f"'x % n == r', сравнения)")


def compile_spec(text):
    errors, warnings = [], []
    spec = parse_spec(text)
    nodes, wires, env = spec["nodes"], spec["wires"], {}
    if not nodes:
        errors.append("спека пуста: нет ни fact, ни rule")

    for node in nodes.values():
        check_requires(node, errors)

    used_inputs = {}
    for w in wires:
        dst_node, dst_port = w["dst"].split(".", 1)
        if dst_node not in nodes:
            errors.append(f"wire {w['dst']}: узел {dst_node} не объявлен")
            continue
        node = nodes[dst_node]
        if dst_port not in node["inputs"]:
            errors.append(f"wire {w['dst']}: у {dst_node} нет входа {dst_port}")
            continue
        if w["dst"] in used_inputs:
            errors.append(f"wire {w['dst']}: вход уже связан (R-ERR?)")
        used_inputs[w["dst"]] = w

        dst_type = node["inputs"][dst_port]
        where = f"wire {w['dst']}"

        # const-источник
        if re.fullmatch(r"-?\d+", w["src"]):
            v = int(w["src"])
            if abs(v) > INT64_LIMIT:
                errors.append(f"{where}: константа {v} за границей 2^53 (R-INT2)")
                continue
            unify_types(dst_type, {"kind": "scalar", "name": "Int64"}, env, where, errors)
            w["const"] = v
            continue
        if re.fullmatch(r"-?\d+\.\d+", w["src"]):
            if dst_type.get("name") == "Int64":
                errors.append(f"{where}: дробная константа к Int64 не проходит (R-INT3)")
            else:
                unify_types(dst_type, {"kind": "scalar", "name": "Float64"}, env, where, errors)
            w["const"] = float(w["src"])
            continue

        src_node, src_port = w["src"].split(".", 1)
        if src_node not in nodes:
            errors.append(f"wire {w['dst']}: узел-источник {src_node} не объявлен")
            continue
        if src_port != "out":
            errors.append(f"wire {w['dst']}: у {src_node} единственный выход — 'out'")
            continue
        src_type = nodes[src_node]["output"]
        w["src_node"] = src_node

        effective_src = src_type
        if src_type["kind"] == "Result":
            # R-ERR1: полнота обработки ошибок; после handle ребро несёт ok-тип
            if w["handle"] is None:
                errors.append(f"{where}: источник {src_node} отдаёт Result[..., "
                              f"{src_type['err']}] — вариант не обработан (R-ERR1)")
            elif w["handle"] != [src_type["err"]]:
                errors.append(f"{where}: handle {w['handle']} не покрывает "
                              f"{src_type['err']} (R-ERR1)")
            else:
                effective_src = src_type["ok"]
        elif w["handle"] is not None:
            errors.append(f"{where}: handle на ребре без Result")

        conv = unify_types(effective_src, dst_type, env, where, errors)
        if conv:
            w["conversion"] = conv

        # R-STREAM1: move запрещён для потоков
        if src_type["kind"] == "Stream" and w["mode"] == "move":
            errors.append(f"{where}: move запрещён для Stream (R-STREAM1)")
            w["mode"] = "copy"
        # R-MAT1: view между разными dtype — понижение до copy
        if (w["mode"] == "view"
                and src_type["kind"] in ("Matrix", "Vector")
                and dst_type["kind"] in ("Matrix", "Vector")
                and src_type["dtype"] != dst_type["dtype"]):
            warnings.append(f"{where}: view между {src_type['dtype']} и "
                            f"{dst_type['dtype']} понижен до copy (R-MAT1)")
            w["mode"] = "copy"
        # view/copy не может идти от fact в Octave напрямую без прослойки —
        # для v0.1 просто фиксируем режим в графе.

    for node in nodes.values():
        if node["kind"] != "rule":
            continue
        for port in node["inputs"]:
            if f"{node['name']}.{port}" not in used_inputs:
                errors.append(f"узел {node['name']}: вход {port} не связан")

    # топологический порядок (Kahn); цикл = ошибка связывания
    order, done = [], set()
    dep = {n: {w["src_node"] for w in wires
               if w["dst"].split(".")[0] == n and "src_node" in w}
           for n in nodes}
    pending = [n for n in nodes if nodes[n]["kind"] == "fact"]
    pending += [n for n in nodes if nodes[n]["kind"] == "rule" and not dep[n]]
    while pending:
        n = pending.pop(0)
        if n in done:
            continue
        done.add(n)
        order.append(n)
        for m, ds in dep.items():
            if m not in done and ds <= done:
                pending.append(m)
    if len(order) != len(nodes):
        errors.append("в графе цикл или недостижимые узлы: "
                      + ", ".join(sorted(set(nodes) - set(order))))

    graph = {
        "spec": spec["name"], "nodes": [nodes[n] for n in order],
        "edges": wires, "invariants": spec["invariants"],
        "dim_env": env, "errors": errors, "warnings": warnings,
    }
    return graph


# ---------------------------------------------------------------- звук

def build_score(graph):
    """Партитура: нота на узел по рантайму + квинта на инварианты."""
    events = []
    for node in graph["nodes"]:
        key = "fact" if node["kind"] == "fact" else node["runtime"]
        events.append({"name": node["name"], "freq": PITCH[key],
                       "dur": DUR[key], "amp": AMP[key],
                       "freq2": None, "kind": key})
    if graph["invariants"]:
        events.append({"name": "invariants", "freq": 440.0, "freq2": 660.0,
                       "dur": 0.5, "amp": 0.35, "kind": "invariant"})
    return events


def render_wav(events, path, sr=44100):
    total = sum(e["dur"] for e in events) + len(events) * 0.02 + 0.25
    buf = np.zeros(int(total * sr))
    t0 = 0.0
    for e in events:
        n = int(e["dur"] * sr)
        t = np.arange(n) / sr
        sig = np.sin(2 * np.pi * e["freq"] * t)
        if e.get("freq2"):
            sig = sig + 0.5 * np.sin(2 * np.pi * e["freq2"] * t)
        env = np.minimum(t / 0.008, 1.0) * np.exp(-4.0 * t / e["dur"])
        i0 = int(t0 * sr)
        buf[i0:i0 + n] += e["amp"] * sig * env
        t0 += e["dur"] + 0.02
    peak = np.max(np.abs(buf)) or 1.0
    pcm = (buf / peak * 0.9 * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def draw_graph(graph, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    nodes = graph["nodes"]
    n = len(nodes)
    fig, ax = plt.subplots(figsize=(1.9 * max(n, 2) + 1, 3.2))
    pos = {}
    for i, node in enumerate(nodes):
        pos[node["name"]] = (i * 2.0, 0)
    for node in nodes:
        x, y = pos[node["name"]]
        color = {"python": "#dfefff", "java": "#ffe9d6", "octave": "#e6ffe1"}.get(
            node["runtime"], "#eee")
        box = FancyBboxPatch((x - 0.8, y - 0.45), 1.6, 0.9,
                             boxstyle="round,pad=0.08",
                             fc=color, ec="#444", lw=1.2)
        ax.add_patch(box)
        ttype = node["output"]
        label = f"{node['name']}\n[{node['runtime']}]\n{ttype.get('kind', '?')}"
        ax.text(x, y, label, ha="center", va="center", fontsize=8)
    for w in graph["edges"]:
        if "src_node" in w and w["src_node"] in pos and w["dst"].split(".")[0] in pos:
            x1, y1 = pos[w["src_node"]]
            x2, y2 = pos[w["dst"].split(".")[0]]
            ax.add_patch(FancyArrowPatch((x1 + 0.85, y1), (x2 - 0.85, y2),
                                         arrowstyle="-|>", mutation_scale=14,
                                         color="#555"))
            ax.text((x1 + x2) / 2, y2 + 0.12, w["mode"], ha="center",
                    fontsize=7, color="#555")
    ax.set_xlim(-1.1, 2.0 * n + 0.1)
    ax.set_ylim(-0.9, 0.9)
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------- main

def main():
    if len(sys.argv) != 2:
        print("использование: python sound_compiler.py <spec.sound>")
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as fh:
        graph = compile_spec(fh.read())
    for w in graph["warnings"]:
        print("WARN:", w)
    for e in graph["errors"]:
        print("ERROR:", e)
    if graph["errors"]:
        print(f"компиляция не удалась: {len(graph['errors'])} ошибок")
        sys.exit(1)
    with open("pipeline_graph.json", "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in graph.items() if k not in ("errors", "warnings")},
                  fh, ensure_ascii=False, indent=2)
    events = build_score(graph)
    render_wav(events, "score.wav")
    draw_graph(graph, "graph.png")
    print("OK: узлов =", len(graph["nodes"]), "| рёбер =", len(graph["edges"]),
          "| инвариантов =", len(graph["invariants"]),
          "| событий партитуры =", len(events))


if __name__ == "__main__":
    main()
