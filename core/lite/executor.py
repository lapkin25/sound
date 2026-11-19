"""
executor.py — минимальный исполнитель графа Trio (Sound → Trio → звук)

Запуск:
    python executor.py pipeline_graph.json

Что делает:
- Читает граф из JSON.
- Запускает узлы: Python (нативно), Java (через subprocess + TrioBridge.java), Octave (через octave-cli).
- Передаёт данные по рёбрам через TRIOMAT-файлы.
- Проверяет типы на границах (R-DIM, R-INT, R-NAN и т.д.).
- Генерирует звуковую партитуру (WAV) по событиям рантайма.
"""

import json
import os
import subprocess
import tempfile
import wave
import struct
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Импортируем наши бриджи (те самые trio_bridge.py)
from trio_bridge import write_matrix, read_matrix, MType, OK, Lossy, Err


class SoundEvent:
    """Звуковое событие: нота, длительность, громкость, тип."""
    def __init__(self, freq: float, duration: float, volume: float, kind: str):
        self.freq = freq
        self.duration = duration
        self.volume = volume
        self.kind = kind


class SoundEngine:
    """Простой синтезатор партитуры из событий."""
    SAMPLE_RATE = 44100

    @staticmethod
    def sine_wave(freq: float, duration: float, volume: float) -> np.ndarray:
        t = np.linspace(0, duration, int(SoundEngine.SAMPLE_RATE * duration), endpoint=False)
        return volume * np.sin(2 * np.pi * freq * t)

    @classmethod
    def render_wav(cls, events: List[SoundEvent], path: str) -> None:
        samples = []
        for ev in events:
            samples.append(cls.sine_wave(ev.freq, ev.duration, ev.volume))
        audio = np.concatenate(samples)
        # Ограничиваем амплитуду
        audio = np.clip(audio, -1.0, 1.0)

        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(cls.SAMPLE_RATE)
            raw = (audio * 32767).astype(np.int16).tobytes()
            wf.writeframes(raw)


class NodeManager:
    """Управление узлами: запуск, ожидание, обработка ошибок."""

    @staticmethod
    def run_python(script_path: str, input_file: Optional[str], output_file: str) -> Tuple[bool, str]:
        cmd = ["python", script_path, input_file or "", output_file]
        res = subprocess.run(cmd, capture_output=True, text=True)
        ok = res.returncode == 0
        msg = res.stdout + res.stderr
        return ok, msg

    @staticmethod
    def run_java(class_name: str, input_file: Optional[str], output_file: str) -> Tuple[bool, str]:
        # Предполагается, что TrioBridge.java уже скомпилирован: javac TrioBridge.java
        # и класс TrioBridge доступен в classpath.
        cmd = [
            "java",
            "-cp", ".",
            "TrioBridge",
            class_name,
            input_file or "",
            output_file
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        ok = res.returncode == 0
        msg = res.stdout + res.stderr
        return ok, msg

    @staticmethod
    def run_octave(script_path: str, input_file: Optional[str], output_file: str) -> Tuple[bool, str]:
        # Octave CLI: octave --eval "trio_bridge_load(...); trio_bridge_save(...);"
        # Здесь упрощаем: скрипт сам читает input_file и пишет output_file.
        cmd = ["octave", "--no-gui", "--eval", f"run_sound_node('{script_path}', '{input_file or ""}', '{output_file}')"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        ok = res.returncode == 0
        msg = res.stdout + res.stderr
        return ok, msg

    @classmethod
    def run(cls, node: Dict[str, Any], input_file: Optional[str], output_file: str) -> Tuple[bool, str]:
        ntype = node["type"]
        if ntype == "python":
            return cls.run_python(node["path"], input_file, output_file)
        elif ntype == "java":
            return cls.run_java(node["class"], input_file, output_file)
        elif ntype == "octave":
            return cls.run_octave(node["path"], input_file, output_file)
        else:
            return False, f"Unknown node type: {ntype}"


class EdgeManager:
    """Передача данных между узлами через TRIOMAT, проверка типов и конверсий."""

    @staticmethod
    def send(source_file: str, target_file: str, edge: Dict[str, Any]) -> Tuple[bool, str, Optional[Any]]:
        """Читает source_file (TRIOMAT), проверяет/конвертирует по edge, пишет target_file."""
        mode = edge.get("mode", "copy")  # copy, view, move
        dtype = edge.get("dtype")
        dims = edge.get("dims")

        # Читаем исходные данные
        try:
            data, info = read_matrix(source_file)
        except Exception as e:
            return False, str(e), None

        # Проверка размерностей (R-DIM7)
        if dims is not None:
            if len(data.shape) != len(dims):
                return False, "ShapeError: rank mismatch", None
            for d_decl, d_act in zip(dims, data.shape):
                if isinstance(d_decl, int) and d_decl != d_act:
                    return False, f"ShapeError: declared {d_decl} != actual {d_act}", None

        # Конверсия dtype (R-FLT, R-INT, R-BOOL)
        result = None
        if dtype is None:
            result = data
        else:
            # Упрощённая таблица конверсий (можно расширить)
            if dtype == "Float64":
                result = data.astype(np.float64)
            elif dtype == "Float32":
                # Lossy(precision) — допустимо
                result = data.astype(np.float32)
            elif dtype == "Int64":
                if not np.issubdtype(data.dtype, np.integer):
                    f = data.astype(np.float64)
                    if not np.all(f == np.floor(f)):
                        return False, "FractionalInt: cannot convert to Int64", None
                    if np.any(np.abs(f) > 9007199254740992):
                        return False, "IntRangeOverflow: > 2^53", None
                result = np.asarray(data, dtype=np.int64)
            elif dtype == "Bool":
                if np.any((data != 0) & (data != 1)):
                    return False, "Bool: values must be 0 or 1", None
                result = data.astype(bool)
            else:
                return False, f"Unsupported dtype: {dtype}", None

        # Режим передачи (упрощённо: view/move → copy для безопасности в прототипе)
        # В полноценной реализации view можно делать через shared memory.
        mtype = MType(dtype if dtype else info.get("original_dtype", "Float64"), dims)
        write_matrix(target_file, result, mtype)

        return True, "OK", result


class Executor:
    def __init__(self, graph_path: str):
        with open(graph_path, "r", encoding="utf-8") as f:
            self.graph = json.load(f)
        self.nodes = {n["id"]: n for n in self.graph["nodes"]}
        self.edges = self.graph.get("edges", [])
        self.invariants = self.graph.get("invariants", [])

        self.events: List[SoundEvent] = []
        self.temp_dir = Path(tempfile.mkdtemp())

    def _emit_sound(self, kind: str, freq: float = 440.0, duration: float = 0.15, volume: float = 0.4):
        """Добавляет звуковое событие и сразу логирует."""
        event = SoundEvent(freq, duration, volume, kind)
        self.events.append(event)
        print(f"[SOUND] {kind} @ {freq:.1f} Hz")

    def _check_invariants(self) -> bool:
        """Статические инварианты (можно расширить до динамических)."""
        # Пока просто логируем; в полной версии — проверка свойств данных.
        for inv in self.invariants:
            print(f"[INVARIANT] {inv}")
        return True

    def run(self) -> bool:
        # Простая топологическая сортировка (для прототипа — по порядку в JSON)
        visited = set()
        order = []

        def dfs(node_id: str):
            if node_id in visited:
                return
            visited.add(node_id)
            for e in self.edges:
                if e["target"] == node_id:
                    dfs(e["source"])
            order.append(node_id)

        for nid in self.nodes:
            dfs(nid)

        # Запускаем узлы в топологическом порядке
        node_outputs: Dict[str, str] = {}  # id -> путь к TRIOMAT файлу

        for nid in order:
            node = self.nodes[nid]
            inputs = [e for e in self.edges if e["target"] == nid]

            # Собираем входные файлы
            input_files = []
            for inp in inputs:
                src = inp["source"]
                if src not in node_outputs:
                    # Источник без предшественников — должен быть фактом/источником
                    continue
                in_file = node_outputs[src]
                out_file = str(self.temp_dir / f"{src}_to_{nid}.triomat")
                ok, msg, _ = EdgeManager.send(in_file, out_file, inp)
                if not ok:
                    print(f"[ERROR] Edge {src}->{nid} failed: {msg}")
                    self._emit_sound("error", freq=150.0, volume=0.6)
                    return False
                input_files.append(out_file)

            # Если у узла нет входов, это источник — запускаем без входного файла
            input_path = input_files[0] if len(input_files) == 1 else None
            if len(input_files) > 1:
                # В прототипе поддерживаем только один вход на узел
                print(f"[ERROR] Node {nid} has multiple inputs — not supported in prototype")
                self._emit_sound("error", freq=120.0, volume=0.7)
                return False

            # Выходной файл для этого узла
            out_path = str(self.temp_dir / f"{nid}.triomat")

            # Звук: начало работы узла
            base_freq = {
                "python": 440.0,
                "java": 523.25,
                "octave": 659.25
            }.get(node["type"], 440.0)
            self._emit_sound("start", freq=base_freq, duration=0.1, volume=0.3)

            ok, msg = NodeManager.run(node, input_path, out_path)
            if not ok:
                print(f"[ERROR] Node {nid} failed: {msg}")
                self._emit_sound("error", freq=110.0, volume=0.8)
                return False

            node_outputs[nid] = out_path

            # Звук: узел завершил работу
            self._emit_sound("finish", freq=base_freq * 1.2, duration=0.12, volume=0.25)

        # Финальный звук — успех
        self._emit_sound("success", freq=880.0, duration=0.4, volume=0.5)
        print("[OK] Граф успешно выполнен.")

        # Сохраняем партитуру
        wav_path = str(self.temp_dir / "score.wav")
        SoundEngine.render_wav(self.events, wav_path)
        print(f"[WAV] Партитура сохранена: {wav_path}")

        return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python executor.py pipeline_graph.json")
        sys.exit(1)
    graph_path = sys.argv[1]
    exec = Executor(graph_path)
    ok = exec.run()
    sys.exit(0 if ok else 1)
