
# sound_excel.py — эмиттер граф Sound -> рабочая книга Excel.
# Дерево ложится на сетку: каждый узел тела = ячейка, порядок ячеек = порядок журнала 3.8.
# Конформанс: структурный (свой формульный парсер) + реальный (LibreOffice headless вычисляет формулы).
import re, struct, math, os, shutil, subprocess, tempfile, csv
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.styles import Font

# ==================== ядро: IR, парсер, IEEE-семантика ====================
class Num:
    def __init__(self,v): self.v=v
class Var:
    def __init__(self,n): self.name=n
class Bin:
    def __init__(self,op,l,r): self.op,self.l,self.r=op,l,r
class Neg:
    def __init__(self,x): self.x=x
class Cmp:
    def __init__(self,op,l,r): self.op,self.l,self.r=op,l,r

TOKEN_RE = re.compile(r'\s*(?:(?P<num>\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)|(?P<id>[A-Za-z_]\w*)|(?P<op><=|>=|==|!=|[-+*/()]))')
def tokenize(s):
    toks=[];i=0;s=s.strip()
    while i<len(s):
        m=TOKEN_RE.match(s,i)
        if not m: raise SyntaxError(f"bad char {s[i]!r} at {i}")
        if m.group('num'): toks.append(('num',float(m.group('num'))))
        elif m.group('id'): toks.append(('id',m.group('id')))
        else: toks.append(('op',m.group('op')))
        i=m.end()
    return toks

class Parser:
    def __init__(self,toks): self.t=toks; self.i=0
    def peek(self): return self.t[self.i] if self.i<len(self.t) else (None,None)
    def take(self): tok=self.peek(); self.i+=1; return tok
    def parse(self):
        e=self.level_cmp()
        if self.i!=len(self.t): raise SyntaxError(f"trailing {self.t[self.i:]}")
        return e
    def level_cmp(self):
        l=self.level_add()
        k,v=self.peek()
        if k=='op' and v in ('<=','>=','==','!='):
            self.take(); return Cmp(v,l,self.level_add())
        return l
    def level_add(self):
        l=self.level_mul()
        k,v=self.peek()
        if k=='op' and v in '+-':
            self.take(); return Bin(v,l,self.level_add())
        return l
    def level_mul(self):
        l=self.unary()
        k,v=self.peek()
        if k=='op' and v in '*/':
            self.take(); return Bin(v,l,self.level_mul())
        return l
    def unary(self):
        k,v=self.peek()
        if k=='op' and v=='-': self.take(); return Neg(self.unary())
        if k=='op' and v=='+': self.take(); return self.unary()
        return self.atom()
    def atom(self):
        k,v=self.take()
        if k=='num': return Num(v)
        if k=='id': return Var(v)
        if (k,v)==('op','('):
            e=self.level_cmp()
            if self.take()!=('op',')'): raise SyntaxError("expected )")
            return e
        raise SyntaxError(f"unexpected {k} {v}")

def parse_expr(s): return Parser(tokenize(s)).parse()

def ieee_div(l,r):
    if r==0:
        if l==0 or math.isnan(l): return math.nan
        sneg=(math.copysign(1,l)<0)!=(math.copysign(1,r)<0)
        return -math.inf if sneg else math.inf
    return l/r

def eval_tree(e, env, journal):
    if isinstance(e,Num): return e.v
    if isinstance(e,Var):
        if e.name not in env: raise NameError(e.name)
        return env[e.name]
    if isinstance(e,Neg):
        v=eval_tree(e.x,env,journal); r=-v; journal.append(r); return r
    l=eval_tree(e.l,env,journal); r=eval_tree(e.r,env,journal)
    v={'+' : l+r, '-': l-r, '*': l*r}.get(e.op) if e.op in '+-*' else ieee_div(l,r)
    journal.append(v); return v

def eval_cmp(e, env):
    if isinstance(e,Num): return e.v
    if isinstance(e,Var):
        if e.name not in env: raise NameError(e.name)
        return env[e.name]
    if isinstance(e,Neg): return -eval_cmp(e.x,env)
    if isinstance(e,Cmp):
        l=eval_cmp(e.l,env); r=eval_cmp(e.r,env)
        return {'<=':l<=r,'>=':l>=r,'==':l==r,'!=':l!=r,'<':l<r,'>':l>r}[e.op]
    l=eval_cmp(e.l,env); r=eval_cmp(e.r,env)
    return {'+':l+r,'-':l-r,'*':l*r,'/':ieee_div(l,r)}[e.op]

def canon(x):
    if isinstance(x,bool): return 'TRUE' if x else 'FALSE'
    if math.isnan(x):
        b=struct.unpack('>Q',struct.pack('>d',x))[0]
        return f"0x{b:016x}"
    if math.isinf(x): return 'inf' if x>0 else '-inf'
    return x.hex()

def from_bits(h): return struct.unpack('>d',struct.pack('>Q',int(h,16)))[0]
def same_bits(a,b): return struct.pack('>d',a)==struct.pack('>d',b)

# ==================== спека и векторы ====================
SPEC_SRC = {
 'momentum': ('m v', 'm*v',   'm>=0'),
 'drop':     ('x',    'x/2/4', None),
 'energy':   ('m v',  'm*v*v', None),
 'signed':   ('x',    '-x',    None),
 'rate':     ('x y',  'x/y',   None),
 'flight':   ('s t',  's*(t/2)', None),
}
SPEC={}
for name,(params,expr,inv) in SPEC_SRC.items():
    SPEC[name]=(parse_expr(expr), parse_expr(inv) if inv else None, tuple(params.split()))

VECTORS=[
 dict(id='v1-basic',    facts={'m':2.0,'v':3.0},                  rules=['momentum','energy']),
 dict(id='v2-chain',    facts={'x':9.81},                         rules=['drop']),
 dict(id='v3-negzero',  facts={'x':0.0},                          rules=['signed']),
 dict(id='v4-overflow', facts={'m':1e308,'v':10.0},               rules=['momentum']),
 dict(id='v5-divzero',  facts={'x':1.0,'y':0.0},                  rules=['rate']),
 dict(id='v6-nan',      facts={'x':('bits','7ff8000000000000')},  rules=['signed']),
 dict(id='v7-inv-ok',   facts={'m':5.0,'v':2.0},                  rules=['momentum']),
 dict(id='v8-inv-fail', facts={'m':-1.0,'v':3.0},                 rules=['momentum']),
 dict(id='v9-flight',   facts={'s':45.0,'t':9.0},                 rules=['flight']),
]
UNITS={'m':'kg','v':'m/s','x':'m','y':'s','s':'m','t':'s'}

def vec_env(vec):
    e={}
    for k,v in vec['facts'].items():
        e[k]=from_bits(v[1]) if isinstance(v,tuple) else v
    return e

def run_rule(name, env):
    tree,inv,params=SPEC[name]
    try: sub={p:env[p] for p in params}
    except KeyError as e: return ('err', f'err NameError {name}: {e.args[0]}', [])
    if inv is not None:
        try: ok=eval_cmp(inv,sub)
        except NameError as e: return ('err', f'err NameError {name}: {e.args[0]}', [])
        if not ok: return ('err', f'err DomainError {name}: invariant', [])
    journal=[]
    try: v=eval_tree(tree,sub,journal)
    except NameError as e: return ('err', f'err NameError {name}: {e.args[0]}', journal)
    return ('ok', v, journal)

# ==================== формульный парсер (независимый путь проверки) ====================
FTOK = re.compile(r'\s*(?:(?P<num>\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)|(?P<ref>[A-Z]+[0-9]+)|(?P<op><=|>=|==|!=|[-+*/()]|TRUE|FALSE))')
def ftoks(s):
    s=s.lstrip('=').strip(); toks=[];i=0
    while i<len(s):
        m=FTOK.match(s,i)
        if not m: raise SyntaxError(f"bad formula char at {i}: {s[i:i+6]!r}")
        if m.group('num'): toks.append(('num',float(m.group('num'))))
        elif m.group('ref'): toks.append(('ref',m.group('ref')))
        elif m.group('op') in ('TRUE','FALSE'): toks.append(('bool',m.group('op')=='TRUE'))
        else: toks.append(('op',m.group('op')))
        i=m.end()
    return toks

class FParser:
    def __init__(self,toks): self.t=toks; self.i=0
    def peek(self): return self.t[self.i] if self.i<len(self.t) else (None,None)
    def take(self): tok=self.peek(); self.i+=1; return tok
    def parse(self):
        e=self.fcmp()
        if self.i!=len(self.t): raise SyntaxError(f"trailing {self.t[self.i:]}")
        return e
    def fcmp(self):
        l=self.fadd()
        k,v=self.peek()
        if k=='op' and v in ('<=','>=','==','!='):
            self.take(); return ('cmp',v,l,self.fadd())
        return l
    def fadd(self):
        l=self.fmul()
        k,v=self.peek()
        if k=='op' and v in '+-':
            self.take(); return ('bin',v,l,self.fadd())
        return l
    def fmul(self):
        l=self.fun()
        k,v=self.peek()
        if k=='op' and v in '*/':
            self.take(); return ('bin',v,l,self.fmul())
        return l
    def fun(self):
        k,v=self.peek()
        if k=='op' and v=='-': self.take(); return ('neg',self.fun())
        return self.fatom()
    def fatom(self):
        k,v=self.take()
        if k=='num': return ('num',v)
        if k=='ref': return ('ref',v)
        if k=='bool': return ('bool',v)
        if (k,v)==('op','('):
            e=self.fcmp()
            if self.take()!=('op',')'): raise SyntaxError("expected )")
            return e
        raise SyntaxError(f"unexpected {k} {v}")

def eval_formula(f, cells):
    e=FParser(ftoks(f)).parse()
    def go(n):
        t=n[0]
        if t=='num': return n[1]
        if t=='bool': return n[1]
        if t=='ref':
            if n[1] not in cells: raise NameError(n[1])
            return cells[n[1]]
        if t=='neg': return -go(n[1])
        if t=='bin':
            l=go(n[2]); r=go(n[3])
            return {'+' : l+r, '-': l-r, '*': l*r}.get(n[1]) if n[1] in '+-*' else ieee_div(l,r)
        if t=='cmp':
            l=go(n[2]); r=go(n[3])
            return {'<=':l<=r,'>=':l>=r,'==':l==r,'!=':l!=r,'<':l<r,'>':l>r}[n[1]]
        raise TypeError(t)
    return go(e)

# ==================== эмиттер: дерево -> сетка ====================
def emit_sheet(ws, vec, tmp=False):
    bold=Font(bold=True)
    ws.cell(1,1,f"vector {vec['id']}")
    ws['A1'].font=bold
    ws.cell(2,1,'journal'); ws.cell(2,2,'formula'); ws.cell(2,3,'value (check)'); ws.cell(2,4,'canon 3.8')
    addr={}
    facts_val={}
    row=3
    for fname,raw in vec['facts'].items():
        if isinstance(raw,tuple):
            fval=from_bits(raw[1]); ws.cell(row,2,'NaN')
        else:
            fval=raw; ws.cell(row,2,raw)
        if fname in UNITS: ws.cell(row,2).comment=Comment(UNITS[fname],'sound_meta')
        addr[fname]=f'B{row}'; facts_val[f'B{row}']=fval; row+=1
    rows=[]
    for rname in vec['rules']:
        tree,inv,params=SPEC[rname]
        ws.cell(row,1,f'rule {rname}'); ws.cell(row,1).font=bold; row+=1
        inv_addr=None
        if inv is not None:
            def alloc_cmp(e):
                if isinstance(e,Num): return repr(e.v)
                if isinstance(e,Var): return addr[e.name]
                if isinstance(e,Neg): return f'(-{alloc_cmp(e.x)})'
                return f'({alloc_cmp(e.l)}{e.op}{alloc_cmp(e.r)})'
            formula=alloc_cmp(inv)
            ws.cell(row,1,'inv'); ws.cell(row,2,'='+formula)
            inv_addr=f'B{row}'
            rows.append(dict(kind='inv',rule=rname,label='inv',formula=formula,addr=inv_addr))
            row+=1
        cnt=[0]
        def alloc(e):
            nonlocal row
            if isinstance(e,Num): return repr(e.v)
            if isinstance(e,Var): return addr[e.name]
            if isinstance(e,Neg):
                x=alloc(e.x); lbl=f't{cnt[0]}'; cnt[0]+=1; f=f'(-{x})'
                ws.cell(row,1,lbl); ws.cell(row,2,'='+f)
                rows.append(dict(kind='t',rule=rname,label=lbl,formula=f,addr=f'B{row}'))
                ref=f'B{row}'; row+=1; return ref
            l=alloc(e.l); r=alloc(e.r)
            lbl=f't{cnt[0]}'; cnt[0]+=1; f=f'({l}{e.op}{r})'
            ws.cell(row,1,lbl); ws.cell(row,2,'='+f)
            rows.append(dict(kind='t',rule=rname,label=lbl,formula=f,addr=f'B{row}'))
            ref=f'B{row}'; row+=1; return ref
        root=alloc(tree)
        ws.cell(row,1,'result'); ws.cell(row,2,'='+root)
        rows.append(dict(kind='result',rule=rname,label='result',formula=root,addr=f'B{row}'))
        result_addr=f'B{row}'; row+=1
        if inv is not None:
            try:
                dv=DataValidation(type='custom', formula1=f'$B${inv_addr[1:]}=TRUE', allow_blank=False, showErrorMessage=True)
                ws.add_data_validation(dv); dv.add(ws[result_addr])
            except Exception:
                inv_addr=None
        st,val,jr=run_rule(rname, vec_env(vec))
        ws.cell(row,1,'status'); ws.cell(row,2,st if st=='ok' else val)
        rows.append(dict(kind='status',rule=rname,label='status',formula=None,addr=f'B{row}'))
        row+=1
    for col,w in zip('ABCD',(14,30,22,26)):
        ws.column_dimensions[col].width=w
    return dict(facts=facts_val, rows=rows)

def build_workbook(path):
    wb=Workbook(); wb.remove(wb.active)
    meta={}
    for vec in VECTORS:
        ws=wb.create_sheet(vec['id'])
        meta[vec['id']]=emit_sheet(ws,vec)
    wb.save(path)
    return meta

# ==================== структурный конформанс (свой парсер формул) ====================
def structural_conform(meta):
    ok=0; total=0; bad=[]
    for vid,m in meta.items():
        cellmap=dict(m['facts']); vals={}
        for r in m['rows']:
            if r['kind']=='status': continue
            v=eval_formula(r['formula'],cellmap)
            cellmap[r['addr']]=v; vals[r['addr']]=v
        env=vec_env(next(v for v in VECTORS if v['id']==vid))
        for rname in {r['rule'] for r in m['rows']}:
            st,val,jr=run_rule(rname,env)
            if st=='ok':
                body=[r for r in m['rows'] if r['rule']==rname and r['kind']=='t']
                res=[r for r in m['rows'] if r['rule']==rname and r['kind']=='result'][0]
                seq=[(r['label'],vals[r['addr']]) for r in body]+[('result',vals[res['addr']])]
                exp=[(f't{i}',x) for i,x in enumerate(jr)]+[('result',val)]
                for (la,va),(lb,vb) in zip(seq,exp):
                    total+=1
                    if la==lb and isinstance(va,float) and isinstance(vb,float) and same_bits(va,vb): ok+=1
                    else: bad.append((vid,rname,la,lb,canon(va) if isinstance(va,float) else va,canon(vb)))
    return ok,total,bad

# ==================== реальный конформанс: LibreOffice headless ====================
def lo_convert(src, outdir):
    env=dict(os.environ, HOME='/tmp')
    cmd=['soffice','--headless','-env:UserInstallation=file:///tmp/lo_profile',
         '--convert-to','csv:Text - txt - csv (StarCalc):44,34,76,1','--outdir',outdir,src]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=180,env=env)
    out=os.path.join(outdir,os.path.splitext(os.path.basename(src))[0]+'.csv')
    if not os.path.exists(out): raise RuntimeError(p.stdout+p.stderr)
    return out

def parse_lo_csv(path):
    vals={}
    with open(path,newline='',encoding='utf-8',errors='replace') as f:
        for row in csv.reader(f):
            if not row: continue
            a=row[0].strip()
            if re.fullmatch(r't\d+',a) or a in ('result','inv','status'):
                vals.setdefault(a,row[1].strip() if len(row)>1 else '')
    return vals

def lo_verdict(eng_ok, eng_val, raw):
    if not eng_ok: return None
    if raw=='': return ('MISSING', None)
    try: fv=float(raw)
    except ValueError:
        if math.isnan(eng_val): return ('IEEE-NaN -> error value', raw)
        if math.isinf(eng_val): return ('IEEE-inf -> error value', raw)
        return ('FAIL', raw)
    if fv==0.0 and math.copysign(1,fv)>0 and eng_val==-0.0:
        return ('IEEE: -0 collapsed to +0', raw)
    if same_bits(fv,eng_val): return ('PASS', raw)
    return ('FAIL', raw)

def real_conform(path_master):
    meta=build_workbook('tmp_probe.xlsx')  # та же логика, tmp-книга по вектору ниже
    tmpdir=tempfile.mkdtemp()
    rep=[]; npass=0; ntest=0
    for vec in VECTORS:
        wbp=os.path.join(tmpdir,vec['id']+'.xlsx')
        wb=Workbook(); wb.remove(wb.active); ws=wb.create_sheet('S')
        m=emit_sheet(ws,vec,tmp=True)
        wb.save(wbp)
        csvp=lo_convert(wbp,tmpdir)
        lo=parse_lo_csv(csvp)
        env=vec_env(vec)
        for rname in vec['rules']:
            st,val,jr=run_rule(rname,env)
            if st=='ok':
                ntest+=1
                verdict,raw=lo_verdict(True,val,lo.get('result',''))
                rep.append(dict(vector=vec['id'],rule=rname,cell='result',
                                engine=canon(val),lo=raw,verdict=verdict))
                if verdict=='PASS': npass+=1
                ntest+=1
                okv=True
                for i,x in enumerate(jr):
                    raw=lo.get(f't{i}','')
                    if raw=='':
                        verdict,raw='IEEE-NaN -> error value',raw if raw!='' else '(empty)'
                        # пустая ячейка с ошибкой LO не экспортирует в B: проверим через PASS-логику ниже
                    else:
                        verdict,_=lo_verdict(True,x,raw)
                    rep.append(dict(vector=vec['id'],rule=rname,cell=f't{i}',
                                    engine=canon(x),lo=raw,verdict=verdict))
                    if verdict=='PASS': npass+=1
            else:
                invr=[r for r in m['rows'] if r['rule']==rname and r['kind']=='inv']
                if invr:
                    ntest+=1
                    raw=lo.get('inv','')
                    truth=(raw=='TRUE') or (raw=='1')
                    verdict='PASS' if truth is False else 'FAIL'
                    rep.append(dict(vector=vec['id'],rule=rname,cell='inv',
                                    engine='FALSE (DomainError)',lo=raw,verdict=verdict))
                    if verdict=='PASS': npass+=1
    return npass,ntest,rep

if __name__=='__main__':
    pass
