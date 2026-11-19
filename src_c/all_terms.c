/* all_terms.c — C99-рантайм SCore: каноническая сериализация и терм T06.
 * Полную версию sound_rt.c см. RESTORE.md: в архиве — реализованный контракт
 * сериализации и терм T06; протекание ошибок и окружение — каркас. */

#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>

/* --- Каноническая сериализация double (контракт 7.1) --- */

static void fmt_hex_double(double x, char *out) {
    uint64_t bits;
    memcpy(&bits, &x, 8);
    int neg = (int)(bits >> 63);
    int exp = (int)((bits >> 52) & 0x7FF);
    uint64_t mant = bits & 0xFFFFFFFFFFFFFULL;   /* ровно 52 бита */

    if (isnan(x)) { strcpy(out, "nan"); return; }
    if (isinf(x)) { strcpy(out, x > 0 ? "inf" : "-inf"); return; }
    if (x == 0.0) { strcpy(out, neg ? "-0x0.0p+0" : "0x0.0p+0"); return; }

    char m[16];
    snprintf(m, sizeof m, "%013llx", (unsigned long long)mant);

    if (exp == 0) {
        /* субнормаль: 0x0.<13 цифр>p-1022, БЕЗ перенормировки */
        snprintf(out, 64, "%s0x0.%sp-1022", neg ? "-" : "", m);
        return;
    }
    int e = exp - 1023;
    snprintf(out, 64, "%s0x1.%sp%s%d", neg ? "-" : "", m,
             e >= 0 ? "+" : "", e);
}

/* --- Значения и журнал (контракт 7.2) --- */

typedef enum { VT_INT, VT_FLOAT, VT_BOOL, VT_VEC, VT_CLOSURE, VT_ERR } VType;

typedef struct Value Value;
typedef struct Closure Closure;
typedef struct EnvNode EnvNode;
typedef Value *(*SoundFn)(EnvNode *captured, Value *arg);

struct Value {
    VType type;
    long long i;        /* D-J1: int64, эталон неограничен — см. RESTORE.md */
    double f;
    int b;
    double *vec; size_t n;
    Closure *clo;
    const char *err;
};

struct Closure { EnvNode *env; SoundFn fn; };
struct EnvNode { const char *name; Value *val; EnvNode *next; };

static void trace_bind(const char *name, Value *v) {
    char buf[64];
    if (v->type == VT_INT) {
        printf("bind %s %lld\n", name, v->i);
    } else if (v->type == VT_FLOAT) {
        fmt_hex_double(v->f, buf);
        printf("bind %s %s\n", name, buf);
    } else if (v->type == VT_BOOL) {
        printf("bind %s %s\n", name, v->b ? "true" : "false");
    } else if (v->type == VT_CLOSURE) {
        printf("bind %s <closure>\n", name);
    } else if (v->type == VT_ERR) {
        printf("bind %s Err(%s)\n", name, v->err);
        printf("err %s Err(%s)\n", name, v->err);
    }
    fflush(stdout);
}

static void trace_result(Value *v) {
    char buf[64];
    if (v->type == VT_INT)       printf("result %lld\n", v->i);
    else if (v->type == VT_FLOAT){ fmt_hex_double(v->f, buf); printf("result %s\n", buf); }
    else if (v->type == VT_BOOL) printf("result %s\n", v->b ? "true" : "false");
    else if (v->type == VT_ERR)  printf("result Err(%s)\n", v->err);
    fflush(stdout);
}

/* --- Операции: первая ошибка побеждает --- */

static Value *op_add(Value *a, Value *b) {
    if (a->type == VT_ERR) return a;
    if (b->type == VT_ERR) return b;
    if (a->type == VT_INT && b->type == VT_INT) {
        Value *r = malloc(sizeof(Value));   /* D-J1: переполнение int64 — отклонение */
        r->type = VT_INT; r->i = a->i + b->i; return r;
    }
    Value *r = malloc(sizeof(Value));
    r->type = VT_FLOAT;
    r->f = (a->type == VT_INT ? (double)a->i : a->f)
         + (b->type == VT_INT ? (double)b->i : b->f);
    return r;
}

/* --- Терм T06: лексический захват --- */

static Value *fn_t06_body(EnvNode *cenv, Value *y) {
    for (EnvNode *e = cenv; e; e = e->next)
        if (strcmp(e->name, "x1") == 0) return op_add(e->val, y);
    Value *r = malloc(sizeof(Value));
    r->type = VT_ERR; r->err = "UndefinedVariable";
    return r;
}


/* --- API из sound_rt.h: тонкие обёртки (гейт [2] требует покрытий) --- */

void sound_fmt_hex_double(double x, char *buf) { fmt_hex_double(x, buf); }
void sound_trace_bind(const char *name, const void *v) {
    trace_bind(name, (const Value *)v);
}
void sound_trace_result(const void *v) { trace_result((const Value *)v); }

int main(void) {
    /* let x1 = 1 */
    Value x1 = { VT_INT, 1, 0, 0, NULL, NULL, NULL };
    trace_bind("x1", &x1);
    EnvNode env1 = { "x1", &x1, NULL };

    /* let f = fun y -> x1 + y */
    Closure clo = { &env1, fn_t06_body };
    Value fv = { VT_CLOSURE, 0, 0, 0, NULL, &clo, NULL };
    trace_bind("f", &fv);
    EnvNode env2 = { "f", &fv, &env1 };

    /* let x1 = 105 — затенение; замыкание его не видит */
    Value x1s = { VT_INT, 105, 0, 0, NULL, NULL, NULL };
    trace_bind("x1", &x1s);
    EnvNode env3 = { "x1", &x1s, &env2 };

    /* f 5 */
    Value five = { VT_INT, 5, 0, 0, NULL, NULL, NULL };
    Value *res = clo.fn(clo.env, &five);
    trace_result(res);
    return 0;
}
