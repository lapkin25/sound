#include "sound_rt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <math.h>

/* ------------------------------------------------------------------ */
/* 7.1. Каноническая сериализация double: побитовый эквивалент        */
/* float.hex() из CPython.                                            */
/* ------------------------------------------------------------------ */

static char hexbuf[40];

const char *fmt_hex_double(double x) {
    uint64_t bits;
    memcpy(&bits, &x, sizeof(bits));

    int sign = (int)(bits >> 63);
    int exp  = (int)((bits >> 52) & 0x7FF);
    uint64_t mant = bits & 0xFFFFFFFFFFFFFULL; /* ровно 52 бита: 13 hex-цифр */

    if (exp == 0x7FF) {
        if (mant == 0) return sign ? "-inf" : "inf";
        return "nan";
    }

    int leading;
    if (exp == 0) {
        if (mant == 0) {
            strcpy(hexbuf, sign ? "-0x0.0p+0" : "0x0.0p+0");
            return hexbuf;
        }
        /* субнормаль: 0x0.<13 цифр>p-1022, БЕЗ перенормировки --
           float.hex() сохраняет нулевой порядок субнормалей */
        leading = '0';
        exp = -1022;
    } else {
        leading = '1';
        exp -= 1023;
    }

    char *p = hexbuf;
    if (sign) *p++ = '-';
    *p++ = '0';
    *p++ = 'x';
    *p++ = leading;
    *p++ = '.';
    for (int k = 0; k < 13; k++) {
        int nib = (int)((mant >> (48 - 4 * k)) & 0xFULL);
        *p++ = "0123456789abcdef"[nib];
    }
    *p++ = 'p';
    if (exp < 0) {
        *p++ = '-';
        exp = -exp;
    } else {
        *p++ = '+';
    }
    char digs[8];
    int nd = 0;
    if (exp == 0) digs[nd++] = '0';
    while (exp > 0) {
        digs[nd++] = (char)('0' + (exp % 10));
        exp /= 10;
    }
    while (nd > 0) *p++ = digs[--nd];
    *p = '\0';
    return hexbuf;
}

/* ------------------------------------------------------------------ */
/* Конструкторы                                                       */
/* ------------------------------------------------------------------ */

Value make_int(int64_t x) {
    Value v;
    v.type = VT_INT64;
    v.v.i = x;
    return v;
}

Value make_float(double x) {
    Value v;
    v.type = VT_FLOAT64;
    v.v.f = x;
    return v;
}

Value make_bool(int b) {
    Value v;
    v.type = VT_BOOL;
    v.v.b = b ? 1 : 0;
    return v;
}

Value make_vec(double *data, size_t len) {
    Value v;
    v.type = VT_VEC;
    v.v.vec.data = data;
    v.v.vec.len = len;
    return v;
}

Value make_err(const char *code) {
    Value v;
    v.type = VT_ERR;
    v.v.err = code;
    return v;
}

/* ------------------------------------------------------------------ */
/* Помощники операций                                                 */
/* ------------------------------------------------------------------ */

static Value widen(Value v) {
    if (v.type == VT_INT64) return make_float((double)v.v.i);
    return v;
}

static int is_num(Value v) {
    return v.type == VT_INT64 || v.type == VT_FLOAT64;
}

static double num_of(Value v) {
    return (v.type == VT_INT64) ? (double)v.v.i : v.v.f;
}

/* Арифметика: int+int -> int; иначе float-приоритет через widen.
   Bool/vec/closure -> TypeMismatch (7.3: неявного смешивания нет). */
Value op_add(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (is_num(a) && is_num(b)) {
        if (a.type == VT_INT64 && b.type == VT_INT64)
            return make_int(a.v.i + b.v.i);
        a = widen(a);
        b = widen(b);
        return make_float(a.v.f + b.v.f);
    }
    return make_err("TypeMismatch");
}

Value op_sub(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (is_num(a) && is_num(b)) {
        if (a.type == VT_INT64 && b.type == VT_INT64)
            return make_int(a.v.i - b.v.i);
        a = widen(a);
        b = widen(b);
        return make_float(a.v.f - b.v.f);
    }
    return make_err("TypeMismatch");
}

Value op_mul(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (is_num(a) && is_num(b)) {
        if (a.type == VT_INT64 && b.type == VT_INT64)
            return make_int(a.v.i * b.v.i);
        a = widen(a);
        b = widen(b);
        return make_float(a.v.f * b.v.f);
    }
    return make_err("TypeMismatch");
}

/* Деление: всегда float, деление на ноль -- IEEE (inf/-inf/nan). */
Value op_div(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (is_num(a) && is_num(b)) {
        double av = num_of(a);
        double bv = num_of(b);
        if (bv == 0.0) {
            if (av > 0.0) return make_float(INFINITY);
            if (av < 0.0) return make_float(-INFINITY);
            return make_float(NAN);
        }
        return make_float(av / bv);
    }
    return make_err("TypeMismatch");
}

/* Сравнения: смешанные int/float сравниваются числово; eq на разных
   типах без ошибок даёт false; иные типы -- TypeMismatch. */
Value op_eq(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (a.type != b.type) return make_bool(0);
    switch (a.type) {
    case VT_INT64:   return make_bool(a.v.i == b.v.i);
    case VT_FLOAT64: return make_bool(a.v.f == b.v.f);
    case VT_BOOL:    return make_bool(a.v.b == b.v.b);
    default:         return make_err("TypeMismatch");
    }
}

Value op_ne(Value a, Value b) {
    Value e = op_eq(a, b);
    if (e.type == VT_ERR) return e;
    return make_bool(!e.v.b);
}

Value op_lt(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (is_num(a) && is_num(b)) return make_bool(num_of(a) <  num_of(b));
    return make_err("TypeMismatch");
}

Value op_le(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (is_num(a) && is_num(b)) return make_bool(num_of(a) <= num_of(b));
    return make_err("TypeMismatch");
}

Value op_and(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (a.type == VT_BOOL && b.type == VT_BOOL)
        return make_bool(a.v.b && b.v.b);
    return make_err("TypeMismatch");
}

Value op_or(Value a, Value b) {
    if (a.type == VT_ERR) return a;
    if (b.type == VT_ERR) return b;
    if (a.type == VT_BOOL && b.type == VT_BOOL)
        return make_bool(a.v.b || b.v.b);
    return make_err("TypeMismatch");
}

Value op_not(Value a) {
    if (a.type == VT_ERR) return a;
    if (a.type == VT_BOOL) return make_bool(!a.v.b);
    return make_err("TypeMismatch");
}

/* ------------------------------------------------------------------ */
/* Коэрсии                                                            */
/* ------------------------------------------------------------------ */

Value coerce_widen(Value v) {
    if (v.type == VT_ERR) return v;
    if (v.type == VT_INT64) return make_float((double)v.v.i);
    if (v.type == VT_FLOAT64) return v;
    return make_err("TypeMismatch");
}

Value coerce_narrow(Value v) {
    if (v.type == VT_ERR) return v;
    if (v.type != VT_FLOAT64) return make_err("TypeMismatch");
    double ip;
    double fr = modf(v.v.f, &ip);
    if (fr != 0.0) return make_err("PrecisionLoss");
    if (ip > 9223372036854775807.0 || ip < -9223372036854775808.0)
        return make_err("PrecisionLoss");
    return make_int((int64_t)ip);
}

/* ------------------------------------------------------------------ */
/* Применение и select: чистые, без trace                             */
/* ------------------------------------------------------------------ */

Value rt_apply(Value f, Value arg) {
    if (f.type == VT_ERR) return f;
    if (f.type != VT_CLOSURE) return make_err("ApplyOnNonClosure");
    return f.v.clo->fn(f.v.clo, arg);
}

Value rt_select(Value cond, Value if_true, Value if_false) {
    if (cond.type == VT_ERR) return cond;
    if (cond.type != VT_BOOL) return make_err("SelectOnNonBool");
    return cond.v.b ? if_true : if_false;
}

Value vec_get(Value v, int64_t idx) {
    if (v.type == VT_ERR) return v;
    if (v.type != VT_VEC) return make_err("TypeMismatch");
    if (idx < 0 || (uint64_t)idx >= v.v.vec.len)
        return make_err("OutOfRange");
    return make_float(v.v.vec.data[idx]);
}

/* ------------------------------------------------------------------ */
/* Окружение                                                          */
/* ------------------------------------------------------------------ */

EnvNode *env_cons(const char *name, Value v, EnvNode *parent) {
    EnvNode *n = (EnvNode *)malloc(sizeof(EnvNode));
    n->name = name;
    n->val = v;
    n->next = parent;
    return n;
}

Value env_get(EnvNode *e, const char *name) {
    for (; e != NULL; e = e->next)
        if (strcmp(e->name, name) == 0) return e->val;
    return make_err("UndefinedVariable");
}

void env_set(EnvNode *e, const char *name, Value v) {
    for (; e != NULL; e = e->next)
        if (strcmp(e->name, name) == 0) {
            e->val = v;
            return;
        }
    /* по контракту сюда не доходит: SC-002 ловит раньше */
}

/* ------------------------------------------------------------------ */
/* Trace                                                              */
/* ------------------------------------------------------------------ */

static const char *canon_of(Value v, char *buf, size_t bufsz) {
    switch (v.type) {
    case VT_INT64:
        snprintf(buf, bufsz, "%" PRId64, v.v.i);
        return buf;
    case VT_FLOAT64:
        return fmt_hex_double(v.v.f);
    case VT_BOOL:
        return v.v.b ? "true" : "false";
    case VT_VEC: {
        size_t off = 0;
        buf[off++] = '[';
        for (size_t k = 0; k < v.v.vec.len && off + 32 < bufsz; k++) {
            if (k > 0) buf[off++] = ',';
            const char *s = fmt_hex_double(v.v.vec.data[k]);
            size_t sl = strlen(s);
            memcpy(buf + off, s, sl);
            off += sl;
        }
        buf[off++] = ']';
        buf[off] = '\0';
        return buf;
    }
    case VT_CLOSURE:
        return "<closure>";
    case VT_ERR:
        snprintf(buf, bufsz, "Err(%s)", v.v.err);
        return buf;
    }
    return "?";
}

/* bind + err одним жестом: правило 7.2 -- err-событие в каждом
   именованном связывании со значением Err. */
void trace_bind(const char *name, Value v) {
    char buf[512];
    printf("bind %s %s\n", name, canon_of(v, buf, sizeof(buf)));
    if (v.type == VT_ERR)
        printf("err %s Err(%s)\n", name, v.v.err);
}

void trace_result(Value v) {
    char buf[512];
    printf("result %s\n", canon_of(v, buf, sizeof(buf)));
}

void trace_flush(void) {
    fflush(stdout);
}
