/* sound_rt.h — каркас C99-рантайма SCore (см. RESTORE.md: полная версия
 * с протеканием ошибок, окружением и reduce восстанавливается из эталона). */
#ifndef SOUND_RT_H
#define SOUND_RT_H

#include <stdint.h>
#include <stddef.h>

/* Контракт 7.1: канонический формат, эквивалент float.hex() CPython.
 * buf должен вмещать минимум 64 байта. */
void sound_fmt_hex_double(double x, char *buf);

/* Контракт 7.2: bind-событие; при Err — дополнительное err-событие. */
void sound_trace_bind(const char *name, const void *value);
void sound_trace_result(const void *value);

#endif
