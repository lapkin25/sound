# sound_glyphs.py - глифы состояния SCore (PUA U+E000..E009)
# Шрифт: sound_status.ttf (моноширинный, advance 0.6 em, UPM 1000 -
# сетка JetBrains Mono, глифы совместимы с pyftmerge).
# Возврат всегда str: если глиф недоступен в текущем терминале,
# terminal_fallback() даёт ASCII-замену.

STATUS_GLYPHS = {
    "node_start":    0xE000,   # ▶ старт узла (рантайм-нота в партитуре)
    "node_finish":   0xE001,   # финиш узла (старт x 1.2)
    "edge_error":    0xE002,   # диссонанс на ребре (150 Гц)
    "node_error":    0xE003,   # сбой узла (110 Гц)
    "config_error":  0xE004,   # ошибка конфигурации (несколько входов)
    "resource_lost": 0xE005,   # потеря ресурса (обрыв, 130.81 Гц)
    "invariant_ok":  0xE006,   # инвариант пройден (квинта 440+660)
    "success":       0xE007,   # успех всего графа (880 Гц)
    "fact":          0xE008,   # факт (факты парят над правилами)
    "lossy_edge":    0xE009,   # lossy-конверсия на ребре (приглушённый диссонанс)
}

CONSOLE_FALLBACK = {
    "node_start": ">", "node_finish": "o", "edge_error": "~", "node_error": "x",
    "config_error": "!", "resource_lost": "/", "invariant_ok": "v",
    "success": "*", "fact": "<>", "lossy_edge": "~",
}

def status_char(kind):
    cp = STATUS_GLYPHS.get(kind)
    if cp is None:
        return "?"
    ch = chr(cp)
    try:
        ch.encode("utf-8")   # кодируемо всегда; оставлено как страж
    except UnicodeEncodeError:
        return CONSOLE_FALLBACK.get(kind, "?")
    return ch

def terminal_fallback(kind):
    return CONSOLE_FALLBACK.get(kind, "?")
