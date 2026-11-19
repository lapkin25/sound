/* sound_rt.h -- каркас API рантайма SCore на C99.
   ВНИМАНИЕ: заголовок восстановлен по использованию в all_terms.c.
   Полная зеркально-проверенная реализация (sound_rt.c) -- см. RESTORE.md. */
#ifndef SOUND_RT_H
#define SOUND_RT_H

typedef enum { VT_INT, VT_FLOAT, VT_BOOL, VT_VEC, VT_CLOSURE, VT_ERR } VType;

typedef struct EnvNode EnvNode;
typedef struct Closure Closure;
typedef struct Value Value;

struct Value {
    VType type;
    long long i;        /* INT; отклонение D-J1: неограниченные целые -- в эталоне */
    double f;           /* FLOAT: единственный плавающий тип, IEEE-754 double */
    int b;              /* BOOL */
    double *vec; int n; /* VEC */
    Closure *clo;       /* CLOSURE */
    const char *err;    /* ERR */
};

struct EnvNode { const char *name; Value val; EnvNode *next; };

struct Closure { EnvNode *env; Value (*fn)(Closure *, Value); };

Value make_int(long long x);
Value make_float(double x);
Value make_bool(int b);
Value make_vec(double *arr, int n);
Value make_closure(Closure *c);
Value make_err(const char *code);

EnvNode *env_cons(const char *name, Value v, EnvNode *next);
Value env_get(EnvNode *env, const char *name);

Value rt_apply(Value f, Value x);
Value rt_select(Value c, Value t, Value e);

void trace_bind(const char *name, Value v);
void trace_result(Value v);

const char *fmt_hex_double(double x);   /* контракт 7.1: побитовый аналог float.hex() */

#endif
