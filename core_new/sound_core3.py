# sound_core3.py — ядро: значения, IEEE-арифметика, замыкания, журнал
import math

INT53 = 2**53
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1
CORE_CODES = {"MalformedHeader","MalformedDtype","MalformedPayload","MalformedShape",
 "UnknownCode","IntRangeOverflow","TypeMismatch","UnknownName","UnknownSymbol",
 "DivisionByZero","NaNOutsideDomain","DomainError","ResourceLost","ResourceBusy",
 "AccessDenied","PermissionDenied","Timeout","Cancelled","InternalError"}

class VNil:
    def j(self): return "nil"
class VBool:
    def __init__(self,v): self.v=bool(v)
    def j(self): return "Bool " + ("true" if self.v else "false")
class VInt:
    def __init__(self,v):
        v=int(v)
        if v < INT64_MIN or v > INT64_MAX: raise VOverflow()
        self.v=v
    def j(self): return "Int64 " + str(self.v)
class VFloat:
    def __init__(self,v): self.v=float(v)
    def j(self):
        x=self.v
        if math.isnan(x): return "Float64 nan"
        if math.isinf(x): return "Float64 " + ("inf" if x>0 else "-inf")
        return "Float64 " + x.hex()
class VStr:
    def __init__(self,v): self.v=str(v)
    def j(self): return 'Str "' + self.v + '"'
class VOverflow(Exception): code="IntRangeOverflow"

class VErr:
    def __init__(self, code, detail=""):
        assert code in CORE_CODES, f"unknown code {code!r}"
        self.code=code; self.detail=detail
    def j(self): return "Err " + self.code + ((" "+self.detail) if self.detail else "")

class Clo:
    def __init__(self, params, body, env, bindings=None):
        self.params=list(params); self.body=body
        self.env=dict(env)
        # bindings: список пар (имя_параметра, значение)
        b = bindings or []
        self.bindings=[p if isinstance(p,tuple) else None for p in b]
        self._vals=[p[1] if isinstance(p,tuple) else p for p in b]
    def j(self): return "Clo"

class Run:
    def __init__(self, env=None):
        self.log=[]; self.n=0; self.env=dict(env or {})
    def bind(self, name, val): self.log.append(f"bind {name} = {val.j()}")
    def coerce(self, name, lossy): self.log.append(f"coerce {name} lossy:{'true' if lossy else 'false'}")
    def err(self, code, detail=""): self.log.append(f"err {code}" + (f" {detail}" if detail else ""))
    def result(self, val): self.log.append(f"result {val.j()}")

REGISTRY = {}
def register_fn(name, params, body): REGISTRY[name] = (list(params), body)

OPS = {"+","-","*","/","%","==","!=","<",">","<=",">=","and","or","?"}

def _to_float(v):
    if isinstance(v,VInt): return float(v.v), abs(v.v) >= INT53 - 1
    if isinstance(v,VFloat): return v.v, False
    return None, False

def _arith(op, a, b):
    if isinstance(a,VErr): return a
    if isinstance(b,VErr): return b
    if op in ("and","or"):
        if not isinstance(a,VBool) or not isinstance(b,VBool):
            return VErr("TypeMismatch","and/or on non-bool")
        return VBool(a.v and b.v) if op=="and" else VBool(a.v or b.v)
    ints = isinstance(a,VInt) and isinstance(b,VInt)
    if ints:
        av,bv = a.v,b.v
        try:
            if op=="+": r=VInt(av+bv)
            elif op=="-": r=VInt(av-bv)
            elif op=="*": r=VInt(av*bv)
            elif op=="/":
                if bv==0: return VErr("DivisionByZero")
                r=VInt(int(av/bv))          # целочисленное: усечение к нулю
            elif op=="%":
                if bv==0: return VErr("DivisionByZero")
                r=VInt(av % bv)
            else: return _num_cmp(op, av, bv)
        except VOverflow:
            return VErr("IntRangeOverflow")
        return r
    fa, la = _to_float(a); fb, lb = _to_float(b)
    if fa is None or fb is None: return VErr("TypeMismatch", op)
    if op in ("==","!=","<",">","<=",">="):
        r = {"==":fa==fb,"!=":fa!=fb,"<":fa<fb,">":fa>fb,"<=":fa<=fb,">=":fa>=fb}[op]
        return VBool(r)
    if op=="?" or op=="/":
        if op=="/" and fb==0.0:
            if fa==0.0: return VErr("NaNOutsideDomain")
            return VFloat(math.copysign(float("inf"), fa))
        if op=="?":
            return VFloat(fa) if fa != 0.0 else VFloat(fb)   # выбор по умолчанию
    if op=="+": r=fa+fb
    elif op=="-": r=fa-fb
    elif op=="*": r=fa*fb
    elif op=="/": r=fa/fb
    else: return VErr("TypeMismatch", op)
    if math.isnan(r): return VErr("NaNOutsideDomain")     # inf-inf, inf*0, ...
    return VFloat(r)

def _num_cmp(op, av, bv):
    r={"==":av==bv,"!=":av!=bv,"<":av<bv,">":av>bv,"<=":av<=bv,">=":av>=bv}[op]
    return VBool(r)

def _cmp(op, a, b):
    if isinstance(a,VErr): return a
    if isinstance(b,VErr): return b
    if isinstance(a,VStr) and isinstance(b,VStr) and op in ("==","!=","<",">","<=",">="):
        r={"==":a.v==b.v,"!=":a.v!=b.v,"<":a.v<b.v,">":a.v>b.v,"<=":a.v<=b.v,">=":a.v>=b.v}[op]
        return VBool(r)
    if isinstance(a,(VInt,VFloat)) and isinstance(b,(VInt,VFloat)):
        return _num_cmp(op, a.v, b.v)
    if op in ("==","!=") and type(a) is type(b):
        return VBool((a.v==b.v) if op=="==" else (a.v!=b.v))
    return VErr("TypeMismatch", op)

def widen_lossy(a, b):
    """Нормализация пары к общей ширине: (значение, lossy)."""
    if isinstance(a,VInt) and isinstance(b,VInt): return a, False
    if isinstance(a,VFloat) and isinstance(b,VFloat): return a, False
    if isinstance(a,VInt):
        return VFloat(float(a.v)), abs(a.v) >= INT53 - 1
    if isinstance(b,VInt):
        return VFloat(float(b.v)), abs(b.v) >= INT53 - 1
    return a, False

def to_int64(v):
    """Приведение к Int64: за 2^53 -> Err(IntRangeOverflow)."""
    if isinstance(v,VErr): return v
    if isinstance(v,VInt):
        if abs(v.v) >= INT53: return VErr("IntRangeOverflow")
        return v
    if isinstance(v,VFloat):
        x=v.v
        if math.isnan(x): return VErr("NaNOutsideDomain")
        if math.isinf(x) or abs(x) >= INT53: return VErr("IntRangeOverflow")
        return VInt(int(x)) if x==math.floor(x) else None
    return VErr("TypeMismatch","to_int64")

def call_fn(f, args, run):
    if isinstance(f,VErr): return f
    if callable(f):
        try: return f(*args)
        except Exception as e: return VErr("InternalError", str(e))
    if isinstance(f, Clo):
        free = f.params[len(f.bindings):]
        if len(args) < len(free):
            newb = list(zip(free[:len(args)], args))
            return Clo(f.params, f.body, f.env, f.bindings + newb)
        if len(args) > len(free):
            return VErr("TypeMismatch","too many args")
        env2 = dict(f.env)
        env2.update(dict(f.bindings))                    # (имя, значение) -> env
        env2.update(dict(zip(free, args)))
        val = eval_expr(f.body, env2, run, REGISTRY)
        return val
    return VErr("TypeMismatch","not callable")

def eval_expr(t, env, run, registry=None):
    registry = registry if registry is not None else REGISTRY
    if not isinstance(t,(list,tuple)): return VErr("TypeMismatch","bad term")
    t = tuple(t) if isinstance(t,list) else t
    tag = t[0]
    if tag=="lit":
        v=t[1]
        if isinstance(v,bool): return VBool(v)
        if isinstance(v,int):  return VInt(v)
        if isinstance(v,float):return VFloat(v)
        if isinstance(v,str):  return VStr(v)
        return v
    if tag=="sym":
        if t[1] in env: return env[t[1]]
        if t[1] in registry:            # замыкание: снимок окружения в момент обращения
            params, body = registry[t[1]]
            return Clo(params, body, env, [])
        return VErr("UnknownName", t[1])
    if tag in OPS:
        a = eval_expr(t[1], env, run, registry)
        b = eval_expr(t[2], env, run, registry)
        r = _cmp(t[0],a,b) if t[0] in ("==","!=","<",">","<=",">=") else _arith(t[0],a,b)
        if isinstance(r,VErr):
            run.err(r.code, r.detail); return r
        if not isinstance(r,VBool):
            run.bind("t%d"%run.n, r); run.n+=1
        return r
    if tag=="let":
        v = eval_expr(t[2], env, run, registry)
        if isinstance(v,VErr): return v
        env = dict(env); env[t[1]] = v
        run.bind(t[1], v)
        return eval_expr(t[3], env, run, registry)
    if tag=="if":
        c = eval_expr(t[1], env, run, registry)
        if isinstance(c,VErr): return c
        if not isinstance(c,VBool): return VErr("TypeMismatch","cond not bool")
        return eval_expr(t[2] if c.v else t[3], env, run, registry)
    if tag=="call":
        f = eval_expr(t[1], env, run, registry)
        args = [eval_expr(a, env, run, registry) for a in t[2]]
        if any(isinstance(a,VErr) for a in args):
            return next(a for a in args if isinstance(a,VErr))
        r = call_fn(f, args, run)
        if isinstance(r,VErr):
            run.err(r.code, r.detail); return r
        run.bind("t%d"%run.n, r); run.n+=1
        return r
    if tag=="err":
        return VErr(t[1], t[2] if len(t)>2 else "")
    return VErr("TypeMismatch", f"unknown tag {tag}")

def _mk_clo(name, registry):
    params, body = registry[name]
    return Clo(params, body, {}, [])

def run(expr, env=None):
    if isinstance(env, Run):
        r = env; envd = dict(r.env)
    else:
        r = Run(env); envd = dict(env or {})
    val = eval_expr(expr, envd, r, REGISTRY)
    if isinstance(val,VErr): r.err(val.code, val.detail)
    else: r.result(val)
    return val
