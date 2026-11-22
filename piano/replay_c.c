/* replay_c.c - SCore c_backend mirror replay (generated)
 * build: gcc -O0 -std=c11 -fno-fast-math -o replay_c replay_c.c
 * contract: results compared as hex strings, never as values */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* ---------- SHA-256 (FIPS 180-4) ---------- */
static const uint32_t KC[64] = {
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
static uint32_t rotr(uint32_t x,int n){return (x>>n)|(x<<(32-n));}
static void sha256(const uint8_t*msg,size_t len,uint8_t out[32]){
  uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                 0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  size_t total=((len+9+63)/64)*64;
  uint8_t*buf=(uint8_t*)calloc(total,1);
  memcpy(buf,msg,len); buf[len]=0x80;
  uint64_t bl=(uint64_t)len*8;
  for(int i=0;i<8;i++) buf[total-1-i]=(uint8_t)(bl>>(8*i));
  for(size_t off=0;off<total;off+=64){
    uint32_t w[64];
    for(int i=0;i<16;i++)
      w[i]=((uint32_t)buf[off+4*i]<<24)|((uint32_t)buf[off+4*i+1]<<16)
          |((uint32_t)buf[off+4*i+2]<<8)|buf[off+4*i+3];
    for(int i=16;i<64;i++){
      uint32_t s0=rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>3);
      uint32_t s1=rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>10);
      w[i]=w[i-16]+s0+w[i-7]+s1;
    }
    uint32_t a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],hh=h[7];
    for(int i=0;i<64;i++){
      uint32_t S1=rotr(e,6)^rotr(e,11)^rotr(e,25);
      uint32_t ch=(e&f)^((~e)&g);
      uint32_t t1=hh+S1+ch+KC[i]+w[i];
      uint32_t S0=rotr(a,2)^rotr(a,13)^rotr(a,22);
      uint32_t mj=(a&b)^(a&c)^(b&c);
      uint32_t t2=S0+mj;
      hh=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
    }
    h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=hh;
  }
  free(buf);
  for(int i=0;i<8;i++){out[4*i]=h[i]>>24;out[4*i+1]=h[i]>>16;out[4*i+2]=h[i]>>8;out[4*i+3]=h[i];}
}
static void fp_chain(const char*fp,const char*line,char out[65]){
  size_t lf=strlen(fp),ll=strlen(line);
  uint8_t*msg=(uint8_t*)malloc(lf+ll);
  memcpy(msg,fp,lf); memcpy(msg+lf,line,ll);
  uint8_t d[32]; sha256(msg,lf+ll,d); free(msg);
  for(int i=0;i<32;i++) sprintf(out+2*i,"%02x",d[i]);
  out[64]=0;
}

/* ---------- TRIOMAT gates: hex <-> bits ---------- */
static uint64_t h2u(const char*s){uint64_t u=0;sscanf(s,"%16llx",&u);return u;}
static double u2d(uint64_t u){double d;memcpy(&d,&u,8);return d;}
static uint64_t d2u(double d){uint64_t u;memcpy(&u,&d,8);return u;}
static void u2hx(uint64_t u,char*s){sprintf(s,"%016llx",(unsigned long long)u);}
static double hex2d(const char*s){return u2d(h2u(s));}
static void d2hex(double d,char*s){u2hx(d2u(d),s);}
static int iserr(const char*v){return strncmp(v,"err:",4)==0;}

/* ---------- environment ---------- */
typedef struct { char name[16]; char val[128]; } Env;
static Env env[32]; static int envn=0;
static void envset(const char*n,const char*v){
  for(int i=0;i<envn;i++) if(!strcmp(env[i].name,n)){strcpy(env[i].val,v);return;}
  snprintf(env[envn].name,16,"%s",n);
  snprintf(env[envn].val,128,"%s",v);
  envn++;
}
static const char* envget(const char*n){
  for(int i=0;i<envn;i++) if(!strcmp(env[i].name,n)) return env[i].val;
  return NULL;
}
static const char* resolve(const char*s){const char*v=envget(s);return v?v:s;}

/* ---------- ops ---------- */
typedef struct { const char*op; const char*a1,*a2,*var;
                 int then_i,else_i,jmp; const char*exp; } Node;
typedef struct { const char*name; int n; const Node*nodes;
                 const Env*init; int nenv; const char*expfp; } Trace;

static void binop(const char*op,const char*x,const char*y,char*res){
  if(iserr(x)){strcpy(res,x);return;}
  if(iserr(y)){strcpy(res,y);return;}
  double a=hex2d(x),b=hex2d(y),d;
  if(!strcmp(op,"plus")) d=a+b;
  else if(!strcmp(op,"sub")) d=a-b;
  else if(!strcmp(op,"mul")) d=a*b;
  else d=a/b;
  /* kernel NaN policy: first NaN operand wins, payload preserved */
  if(a!=a) d2hex(a,res);
  else if(b!=b) d2hex(b,res);
  else d2hex(d,res);
}
static void intop(const char*op,const char*x,const char*y,char*res){
  uint64_t ua=h2u(x),ub=h2u(y),r;
  if(!strcmp(op,"iplus")) r=ua+ub;
  else if(!strcmp(op,"isub")) r=ua-ub;
  else r=ua*ub;                       /* wrap mod 2^64 */
  u2hx(r,res);
}
static void idivop(const char*op,const char*x,const char*y,char*res){
  uint64_t ua=h2u(x),ub=h2u(y);
  if(ub==0){sprintf(res,"err:div0:%s",x);return;}
  int64_t a=(int64_t)ua,b=(int64_t)ub,q;
  if(a==INT64_MIN&&b==-1) q=INT64_MIN; else q=a/b;   /* trunc toward zero */
  if(!strcmp(op,"quotient")) u2hx((uint64_t)q,res);
  else u2hx(ua-(uint64_t)q*ub,res);                  /* sign of dividend */
}
static void foldop(const char*op,const char*lc,const char*accs,char*res){
  int n=atoi(lc); const char*p=strchr(lc,'|')+1;
  double acc=hex2d(accs);
  char hx[24],ph[24],out[512]; out[0]=0;
  for(int i=0;i<n;i++){
    memcpy(hx,p,16); hx[16]=0; p+=17;
    double x=hex2d(hx);
    acc=(acc!=acc)?acc:acc+x;
    if(!strcmp(op,"foldlist")){
      d2hex(acc,ph);
      sprintf(out+strlen(out),"%s%s",i?",":"",ph);
    }
  }
  if(!strcmp(op,"foldlist")) sprintf(res,"%d|%s",n,out);
  else d2hex(acc,res);
}

static void compute(const Node*nd,char*res,int*chosen){
  const char*op=nd->op; *chosen=-1;
  if(!strcmp(op,"const")){ strcpy(res,nd->a1); if(nd->var[0]) envset(nd->var,res); }
  else if(!strcmp(op,"list")){ strcpy(res,nd->a1); if(nd->var[0]) envset(nd->var,res); }
  else if(!strcmp(op,"ref")) strcpy(res,envget(nd->a1));
  else if(!strcmp(op,"set")){ strcpy(res,resolve(nd->a2)); envset(nd->a1,res); }
  else if(!strcmp(op,"plus")||!strcmp(op,"sub")||!strcmp(op,"mul")||!strcmp(op,"div"))
    binop(op,resolve(nd->a1),resolve(nd->a2),res);
  else if(!strcmp(op,"iplus")||!strcmp(op,"isub")||!strcmp(op,"imul"))
    intop(op,resolve(nd->a1),resolve(nd->a2),res);
  else if(!strcmp(op,"quotient")||!strcmp(op,"mod"))
    idivop(op,resolve(nd->a1),resolve(nd->a2),res);
  else if(!strcmp(op,"neg")){
    uint64_t u=h2u(resolve(nd->a1)); u^=1ULL<<63;   /* sign flip, payload kept */
    u2hx(u,res);
  }
  else if(!strcmp(op,"eq")){
    double a=hex2d(resolve(nd->a1)),b=hex2d(resolve(nd->a2));
    strcpy(res,(a==b)?"true":"false");
  }
  else if(!strcmp(op,"if")){
    const char*c=resolve(nd->a1);
    if(iserr(c)){strcpy(res,c);return;}
    *chosen=(strcmp(c,"true")==0)?nd->then_i:nd->else_i;
    strcpy(res,(*chosen==nd->then_i)?"branch_t":"branch_f");
  }
  else if(!strcmp(op,"err")) sprintf(res,"err:%s:%s",nd->a1,resolve(nd->a2));
  else if(!strcmp(op,"fold")||!strcmp(op,"foldlist"))
    foldop(op,resolve(nd->a1),resolve(nd->a2),res);
}

/* ---------- generated trace tables ---------- */
static const Node N_DemoNeg[] = {
  {"const","fffffffffffffff9","","a",-1,-1,-1,"fffffffffffffff9"},
  {"const","0000000000000002","","b",-1,-1,-1,"0000000000000002"},
  {"ref","a","","",-1,-1,-1,"fffffffffffffff9"},
  {"ref","b","","",-1,-1,-1,"0000000000000002"},
  {"quotient","t2","t3","",-1,-1,-1,"fffffffffffffffd"},
  {"mod","t2","t3","",-1,-1,-1,"ffffffffffffffff"},
  {"set","r","t5","",-1,-1,-2,"ffffffffffffffff"},
};
static const Env E_DemoNeg[] = {
  {"a","fffffffffffffff9"},
  {"b","0000000000000002"},
};
static const Trace T_DemoNeg = {"DemoNeg", 7, N_DemoNeg, E_DemoNeg, 2, "b49dd640b4b790713296aecfa2830670996b0b91e2fed357402949845b252fc1"};

static const Node N_DemoWrap[] = {
  {"const","7fffffffffffffff","","max",-1,-1,-1,"7fffffffffffffff"},
  {"const","0000000000000001","","one",-1,-1,-1,"0000000000000001"},
  {"ref","max","","",-1,-1,-1,"7fffffffffffffff"},
  {"ref","one","","",-1,-1,-1,"0000000000000001"},
  {"iplus","t2","t3","",-1,-1,-1,"8000000000000000"},
  {"isub","t4","t3","",-1,-1,-1,"7fffffffffffffff"},
  {"imul","t2","t2","",-1,-1,-1,"0000000000000001"},
  {"set","r","t6","",-1,-1,-2,"0000000000000001"},
};
static const Env E_DemoWrap[] = {
  {"max","7fffffffffffffff"},
  {"one","0000000000000001"},
};
static const Trace T_DemoWrap = {"DemoWrap", 8, N_DemoWrap, E_DemoWrap, 2, "5919f4f01dede789db9ee7b5725f09de8100ef82ec45bef11aa2a46548b65004"};

static const Node N_DemoDenorm[] = {
  {"const","0000000000000001","","d",-1,-1,-1,"0000000000000001"},
  {"const","3fe0000000000000","","half",-1,-1,-1,"3fe0000000000000"},
  {"ref","d","","",-1,-1,-1,"0000000000000001"},
  {"ref","half","","",-1,-1,-1,"3fe0000000000000"},
  {"mul","t2","t3","",-1,-1,-1,"0000000000000000"},
  {"plus","t2","t2","",-1,-1,-1,"0000000000000002"},
  {"div","t5","t2","",-1,-1,-1,"4000000000000000"},
  {"set","r","t6","",-1,-1,-2,"4000000000000000"},
};
static const Env E_DemoDenorm[] = {
  {"d","0000000000000001"},
  {"half","3fe0000000000000"},
};
static const Trace T_DemoDenorm = {"DemoDenorm", 8, N_DemoDenorm, E_DemoDenorm, 2, "27f241bf40f85b47463ba32ca699aefca9f1d9ab185486e5bd3b81068fe9dafe"};

static const Node N_DemoNaN[] = {
  {"const","7ff8000000000001","","n",-1,-1,-1,"7ff8000000000001"},
  {"ref","n","","",-1,-1,-1,"7ff8000000000001"},
  {"neg","t1","","",-1,-1,-1,"fff8000000000001"},
  {"const","0000000000000000","","zero",-1,-1,-1,"0000000000000000"},
  {"ref","zero","","",-1,-1,-1,"0000000000000000"},
  {"plus","t2","t4","",-1,-1,-1,"fff8000000000001"},
  {"set","r","t5","",-1,-1,-2,"fff8000000000001"},
};
static const Env E_DemoNaN[] = {
  {"n","7ff8000000000001"},
  {"zero","0000000000000000"},
};
static const Trace T_DemoNaN = {"DemoNaN", 7, N_DemoNaN, E_DemoNaN, 2, "dd184d71f9e2f993d2b9b94fa257c75dac912f208692f36ecb4cc992e3a5d600"};

static const Node N_DemoDiv0[] = {
  {"const","3ff0000000000000","","a",-1,-1,-1,"3ff0000000000000"},
  {"const","0000000000000000","","b",-1,-1,-1,"0000000000000000"},
  {"ref","b","","",-1,-1,-1,"0000000000000000"},
  {"eq","t2","0000000000000000","",-1,-1,-1,"true"},
  {"if","t3","","",5,7,-1,"branch_t"},
  {"err","div0","3ff0000000000000","",-1,-1,-1,"err:div0:3ff0000000000000"},
  {"set","r","t5","",-1,-1,-2,"err:div0:3ff0000000000000"},
  {"ref","a","","",-1,-1,-2,""},
};
static const Env E_DemoDiv0[] = {
  {"a","3ff0000000000000"},
  {"b","0000000000000000"},
};
static const Trace T_DemoDiv0 = {"DemoDiv0", 8, N_DemoDiv0, E_DemoDiv0, 2, "b3813a7b76b536ee4c37164a1653d783fb8de4671952d6cea638f83b75e12672"};

static const Node N_DemoFold[] = {
  {"const","0000000000000000","","acc",-1,-1,-1,"0000000000000000"},
  {"list","3|4341c37937e08000,3ff0000000000000,c341c37937e08000","","L",-1,-1,-1,"3|4341c37937e08000,3ff0000000000000,c341c37937e08000"},
  {"fold","L","acc","",-1,-1,-1,"0000000000000000"},
  {"foldlist","L","acc","",-1,-1,-1,"3|4341c37937e08000,4341c37937e08000,0000000000000000"},
  {"set","r","t3","",-1,-1,-2,"3|4341c37937e08000,4341c37937e08000,0000000000000000"},
};
static const Env E_DemoFold[] = {
  {"acc","0000000000000000"},
  {"L","3|4341c37937e08000,3ff0000000000000,c341c37937e08000"},
};
static const Trace T_DemoFold = {"DemoFold", 5, N_DemoFold, E_DemoFold, 2, "540908d7730ea17d8aa645ff70cbc26a827f1861c81aef368889b4f6a3be103f"};

static const Trace* TRACES[] = {
  &T_DemoNeg,
  &T_DemoWrap,
  &T_DemoDenorm,
  &T_DemoNaN,
  &T_DemoDiv0,
  &T_DemoFold
};
#define NTRACES (int)(sizeof(TRACES)/sizeof(TRACES[0]))

int main(void){
  int all_ok=1;
  for(int ti=0;ti<NTRACES;ti++){
    const Trace*t=TRACES[ti];
    envn=0;
    for(int i=0;i<t->nenv;i++) envset(t->init[i].name,t->init[i].val);
    char fp[65],fpn[65]; memset(fp,'0',64); fp[64]=0;
    printf("=== REPLAY: %s ===\n",t->name);
    int pc=0,pass=0,fail=0;
    while(1){
      const Node*nd=&t->nodes[pc]; int cur=pc;
      char res[512]; int chosen=-1;
      compute(nd,res,&chosen);
      char tn[16]; snprintf(tn,16,"t%d",cur); envset(tn,res);
      char line[768];
      if(!strcmp(nd->op,"if"))
        snprintf(line,sizeof line,"t%d %s %s t%d t%d -> %s",
                 cur,nd->op,nd->a1,nd->then_i,nd->else_i,res);
      else if(nd->a2[0]&&strcmp(nd->op,"const")&&strcmp(nd->op,"list"))
        snprintf(line,sizeof line,"t%d %s %s %s -> %s",cur,nd->op,nd->a1,nd->a2,res);
      else
        snprintf(line,sizeof line,"t%d %s %s -> %s",cur,nd->op,nd->a1,res);
      int ok=(strcmp(res,nd->exp)==0);
      if(ok)pass++;else fail++;
      printf("t%d %-8s %-4s %s\n",cur,nd->op,ok?"PASS":"FAIL",res);
      if(!ok)printf("    expected: %s\n",nd->exp);
      fp_chain(fp,line,fpn); strcpy(fp,fpn);
      if(!strcmp(nd->op,"if")) pc=chosen;
      else if(nd->jmp==-2) break;
      else if(nd->jmp==-1) pc++;
      else pc=nd->jmp;
    }
    int fpm=(strcmp(fp,t->expfp)==0);
    printf("fingerprint: %s %s\n",fp,fpm?"MATCH":"MISMATCH");
    printf("RESULT: %s\n\n",(fail==0&&fpm)?"MATCH":"FAIL");
    if(!(fail==0&&fpm)) all_ok=0;
  }
  printf(all_ok?"RESULT: ALL TRACES MATCH\n":"RESULT: CORPUS FAILED\n");
  return all_ok?0:1;
}
