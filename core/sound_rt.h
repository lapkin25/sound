#ifndef SOUND_RT_H
#define SOUND_RT_H

/*
 * sound_rt.h -- рантайм языка Sound (SCore), C99.
 *
 * Контракт:
 *   7.1  каноническая сериализация чисел (fmt_hex_double == float.hex() CPython);
 *   7.2  err-событие пишется в каждом именованном связывании со значением Err;
 *   7.3  ошибки -- значения, протекают через операции (первая ошибка побеждает).
 */

#include <stddef.h>
#include <stdint.h>

typedef enum {
    VT_INT64,    /* целое: неограниченное в ядре, здесь int64 */
    VT_FLOAT64,  /* единственный плавающий тип: IEEE-754 F64 */
    VT_BOOL,
    VT_VEC,
    VT_CLOSURE,
    VT_ERR
} ValueType;

typedef struct Closure Closure;
typedef struct EnvNode EnvNode;

typedef struct Value {
    ValueType type;
    union {
        int64_t i;
        double f;
        int b;
        struct {
            double *data;   /* память принадлежит кодогенератору */
            size_t len;
        } vec;
        Closure *clo;
        const char *err;    /* статический литерал из сгенерированного кода */
    } v;
} Value;

struct EnvNode {
    const char *name;       /* статические литералы: без strdup */
    Value val;
    EnvNode *next;
};

struct Closure {
    EnvNode *env;           /* снимок окружения на момент создания */
    Value (*fn)(Closure *, Value);
};

/* Конструкторы */
Value make_int(int64_t x);
Value make_float(double x);
Value make_bool(int b);
Value make_vec(double *data, size_t len);
Value make_err(const char *code);

/* Операции: ошибки протекают, результат не зависит от порядка операндов */
Value op_add(Value a, Value b);
Value op_sub(Value a, Value b);
Value op_mul(Value a, Value b);
Value op_div(Value a, Value b);
Value op_eq(Value a, Value b);
Value op_ne(Value a, Value b);
Value op_lt(Value a, Value b);
Value op_le(Value a, Value b);
Value op_and(Value a, Value b);
Value op_or(Value a, Value b);
Value op_not(Value a);

/* Коэрсии (событие coerce пишет вызывающий код) */
Value coerce_widen(Value v);
Value coerce_narrow(Value v);   /* Err(PrecisionLoss), если дробная часть ненулевая */

/* Применение и select: БЕЗ trace -- события пишет вызывающий код,
   иначе сгенерированный код и rt_apply задвоят bind */
Value rt_apply(Value f, Value arg);
Value rt_select(Value cond, Value if_true, Value if_false);

/* Вектор: чтение по индексу с проверкой границ */
Value vec_get(Value v, int64_t idx);

/* Окружение: список пар (имя, значение) */
EnvNode *env_cons(const char *name, Value v, EnvNode *parent);
Value env_get(EnvNode *e, const char *name);
void env_set(EnvNode *e, const char *name, Value v);

/* Trace API: строки в stdout, их разбирает run_golden_c.py
   bind <name> <canon>
   err  <name> Err(<code>)
   result <canon> */
void trace_bind(const char *name, Value v);
void trace_result(Value v);
void trace_flush(void);

/* Каноническая сериализация double: контракт 7.1 */
const char *fmt_hex_double(double x);

#endif /* SOUND_RT_H */
