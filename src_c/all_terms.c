#include "sound_rt.h"

/* Автогенерированный файл. Не редактируйте вручную. */

Value term_T06(void) {
    EnvNode *env = NULL;
    Value val_x1 = make_int(1);
    trace_bind("x1", val_x1);
    EnvNode *env_x1 = env_cons("x1", val_x1, env);

    /* Замыкание: params=['y'] */
    Closure clo_T06_f = { .env = env_x1, .fn = NULL };
    Value val_f = make_closure(&clo_T06_f);
    trace_bind("f", val_f);
    EnvNode *env_f = env_cons("f", val_f, env_x1);

    Value val_x1__2 = make_int(105);
    trace_bind("x1", val_x1__2);
    EnvNode *env_x1__2 = env_cons("x1", val_x1__2, env_f);

    Value arg = make_int(5);
    Value res = rt_apply(env_get(env_x1__2, "f"), arg);
    trace_result(res);
    return res;
}
