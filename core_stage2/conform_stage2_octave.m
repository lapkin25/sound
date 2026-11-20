% conform_stage2_octave.m - stage 2: journal conformance (7 vectors)
% Run: octave --eval conform_stage2_octave
% Expected tail: ALL PASS (7/7)
%
% Spec parsing and static checks (SC) are the etalon's job: hosts receive
% already-parsed trees from fixtures_stage2.json. Host duties here: execute
% the tree and reproduce the journal 3.8 byte-for-byte. Requires canon.m
% from the stage-1 set. NaN arguments arrive as {"hex_bits": "..."} since
% JSON has no NaN literal.

function conform_stage2_octave()
  S = jsondecode(fileread('fixtures_stage2.json'));
  npass = 0; nfail = 0; fails = {};
  jv = S.journal_vectors;
  for i = 1:numel(jv)
    v = jv(i);
    [journal, val] = exec_rule(v.rule, S.rules.(v.rule), S.facts, v.args);
    el = strcell(v.expect_log);
    ok = cell_str_equal(journal, el) && value_ok(val, v.expect_value);
    if ok
      npass++;
      printf('PASS %s\n', v.name);
    else
      nfail++;
      fails{end+1} = v.name;
      printf('FAIL %s\n', v.name);
      for k = 1:max(numel(journal), numel(el))
        a = ''; b = '';
        if k <= numel(journal); a = journal{k}; endif
        if k <= numel(el); b = el{k}; endif
        if ~strcmp(a, b)
          printf('  line %d: got  %s\n', k, a);
          printf('  line %d: want %s\n', k, b);
        endif
      endfor
    endif
  endfor
  printf('\n');
  if nfail > 0
    printf('FAILURES: %d -> %s\n', nfail, strjoin(fails, ', '));
    return
  endif
  printf('ALL PASS (%d/%d)\n', npass, npass);
endfunction

function [journal, val] = exec_rule(rname, r, facts, args)
  % 1) invariant first, silently; violation -> single err line (3.8)
  ps = r.params;
  env = struct();
  for k = 1:numel(ps)
    p = ps{k};
    a = args.(p);
    if isstruct(a)
      env.(p) = bits2double(a.hex_bits);
    else
      env.(p) = a;
    endif
  endfor
  has_inv = isfield(r, 'inv') && ~(isnumeric(r.inv) && isscalar(r.inv) && isnan(r.inv));
  if has_inv
    fenv = facts;
    pn = fieldnames(env);
    for k = 1:numel(pn)
      fenv.(pn{k}) = env.(pn{k});
    endfor
    okv = eval_silent(r.inv, fenv);
    if ~(okv == 1)          % NaN == 1 is false -> DomainError
      journal = {sprintf('err DomainError %s: invariant', rname)};
      val = [];
      return
    endif
  endif
  % 2) binds of parameters, names padded to max(2, longest name)
  pad = 2;
  for k = 1:numel(ps)
    pad = max(pad, numel(ps{k}));
  endfor
  journal = {};
  for k = 1:numel(ps)
    journal{end+1} = sprintf('bind %s = Float64 %s', padname(ps{k}, pad), canon(env.(ps{k})));
  endfor
  % 3) body: left, right, operation; t-bind after each operation node
  counter = 0;
  [val, counter, journal] = eval_j(r.tree, env, facts, journal, pad, counter);
  % 4) result line
  journal{end+1} = sprintf('result  = Float64 %s', canon(val));
endfunction

function s = padname(nm, pad)
  s = nm;
  while numel(s) < pad
    s = [s ' '];
  endwhile
endfunction

function d = bits2double(hs)
  lo = uint64(hex2dec(hs(9:16)));
  hi = uint64(hex2dec(hs(1:8)));
  d = typecast(uint64(hi * uint64(4294967296) + lo), 'double');
endfunction

function [v, counter, journal] = eval_j(tree, env, facts, journal, pad, counter)
  if ischar(tree)
    if isfield(env, tree)
      v = env.(tree);
    else
      v = facts.(tree);
    endif
  elseif isnumeric(tree)
    v = tree;
  else
    op = tree{1};
    [lv, counter, journal] = eval_j(tree{2}, env, facts, journal, pad, counter);
    if strcmp(op, 'neg')
      v = -lv;
    else
      [rv, counter, journal] = eval_j(tree{3}, env, facts, journal, pad, counter);
      switch op
        case '+'
          v = lv + rv;
        case '-'
          v = lv - rv;
        case '*'
          v = lv * rv;
        case '/'
          v = lv / rv;
      endswitch
    endif
    nm = sprintf('t%d', counter);
    counter = counter + 1;
    journal{end+1} = sprintf('bind %s = Float64 %s', padname(nm, pad), canon(v));
  endif
endfunction

function ok = eval_silent(tree, fenv)
  if ischar(tree)
    ok = fenv.(tree);
  elseif isnumeric(tree)
    ok = tree;
  else
    op = tree{1};
    a = eval_silent(tree{2}, fenv);
    if strcmp(op, 'neg')
      ok = -a;
      return
    endif
    b = eval_silent(tree{3}, fenv);
    switch op
      case '>='
        ok = a >= b;
      case '<='
        ok = a <= b;
      case '>'
        ok = a > b;
      case '<'
        ok = a < b;
      case '=='
        ok = a == b;
      case '!='
        ok = a != b;
      case '+'
        ok = a + b;
      case '-'
        ok = a - b;
      case '*'
        ok = a * b;
      case '/'
        ok = a / b;
    endswitch
  endif
endfunction

function eq = cell_str_equal(a, b)
  eq = numel(a) == numel(b);
  if eq
    for k = 1:numel(a)
      if ~strcmp(a{k}, b{k})
        eq = false;
        return
      endif
    endfor
  endif
endfunction

function ok = value_ok(val, expect)
  if ischar(expect)          % "nan" | "inf" | "-inf"
    ok = strcmp(canon(val), expect);
    return
  endif
  if isstruct(expect)        % {"hex_bits": ...} — точные биты IEEE-754
    ok = strcmp(canon(val), canon(bits2double(expect.hex_bits)));
    return
  endif
  if isnumeric(expect) && numel(expect) == 0   % null -> err-вектор
    ok = isempty(val);
    return
  endif
  ok = strcmp(canon(val), canon(expect));
endfunction

function c = strcell(js)
  if ~iscell(js)
    c = {js};          % на всякий случай: одиночная строка из jsondecode
    return
  endif
  c = cell(1, numel(js));   % именно 1 x N, не cell(numel(js))
  for k = 1:numel(js)
    c{k} = js{k};
  endfor
endfunction

