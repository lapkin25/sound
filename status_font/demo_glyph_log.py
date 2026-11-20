# demo_glyph_log.py - как выглядит консоль живой партитуры после интеграции глифов.
# Точки патча в sound_engine.py: каждая строка [SOUND] ... получает префикс
# status_char(kind) из sound_glyphs; ASCII-fallback включается, если терминал
# не умеет PUA (сравнение по фактическому рендеру - обязанность терминала).
from sound_glyphs import status_char, terminal_fallback

LOG = [
    ("fact",         "g",            "9.81 Hz"),
    ("fact",         "half",         "9.81 Hz"),
    ("node_start",   "python flight_range", "440.00 Hz"),
    ("node_finish",  "flight_range",        "528.00 Hz"),
    ("node_start",   "python hypotenuse",   "440.00 Hz"),
    ("node_finish",  "hypotenuse",          "528.00 Hz"),
    ("edge_error",   "wire flight_range",   "150.00 Hz"),
    ("success",      "graph",               "880.00 Hz"),
]

def print_log(use_fallback=False):
    pick = terminal_fallback if use_fallback else status_char
    for kind, node, freq in LOG:
        print("[SOUND] %s %-28s @ %s" % (pick(kind), node, freq))

if __name__ == "__main__":
    print("-- PUA glyphs --")
    print_log()
    print("-- ASCII fallback --")
    print_log(use_fallback=True)
