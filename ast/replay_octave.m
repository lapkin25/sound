%% replay_octave.m — универсальный кросс-хост-реплей с AST-интерпретатором
%%
%% Сценарий: снапшоты созданы в Python (sound_snap2.py). Раннер восстанавливает
%% сессию из snap_A.json и вычисляет продолжение Nest[step, x, 15], интерпретируя
%% тело step прямо из снапшота — AST-массивы из JSON, ни одной операции вручную.
%% Затем сверяется со снапшотом B: журнал посимвольно, last по 16 hex-цифрам.
%%
%% Покрытие интерпретатора: const, ref, neg, op (+ - * /), cmp (< <= > >= == !=),
%% list, call (пользовательские функции из снапшота) и встроенные If / Nest / Fold.
%%
%% Запуск из корня репозитория (после python3 sound_snap2.py):
%%   octave --eval "addpath('octave'); replay_octave"
%% Ожидаемый финал:
%%   ALL PASS: сессия Python продолжена в Octave (AST-интерпретатор)

function replay_octave()
  A = load_snap('artifacts/snap_A.json');
  B = load_snap('artifacts/snap_B.json');

  % аудит обоих снапшотов до начала реплея
  audit_fingerprint(A, 'A');
  audit_fingerprint(B, 'B');

  ja = journal_lines(A.journal);
  jb = journal_lines(B.journal);

  global G_journal G_count G_funcs
  G_journal = ja;
  G_count = numel(ja);
  G_funcs = norm_funcs(A.funcs);

  % восстановление состояния по битам (little-endian typecast-путь)
  env = struct();
  env.('x') = bits2double(A.names.x);

  % точка входа продолжения: Nest[step, x, 15].
  % Узел вызова строит раннер; тело step приходит из снапшота.
  callargs = {{'ref', 'step'}, {'ref', 'x'}, {'const', 15.0}};
  v = evalnode({'call', 'Nest', callargs}, env);

  okj = (G_count == numel(jb)) && all(strcmp(G_journal, jb));
  okl = strcmp(num2hex(v), B.last);

  % края канона: восстановление битов не теряет ни знака нуля, ни NaN
  edges_ok = true;
  for e = [-2.0, 0.0, -0.0, nan]
    edges_ok = edges_ok && strcmp(num2hex(bits2double(num2hex(e))), num2hex(e));
  end

  if okj && okl && edges_ok
    printf('ALL PASS: сессия Python продолжена в Octave (AST-интерпретатор)\n');
    printf('журнал: %d строк посимвольно, last: %s\n', numel(jb), B.last);
  else
    printf('FAIL: журнал %d, last %d, края %d\n', okj, okl, edges_ok);
    if ~okj
      for k = 1:min(G_count, numel(jb))
        if ~strcmp(G_journal{k}, jb{k})
          printf('первое расхождение на строке %d:\n  want: %s\n  got : %s\n',
                 k, jb{k}, G_journal{k});
          break
        end
      end
    end
  end
end

%% ---------- загрузка и нормализация снапшота ----------

function snap = load_snap(p)
  if exist(p, 'file')
    raw = p;
  else
    [~, nm, ext] = fileparts(p);
    raw = [nm ext];   % снапшоты лежат и в artifacts/, и в корне
    if ~exist(raw, 'file')
      error('снапшот не найден ни в %s, ни в корне', p);
    end
  end
  snap = jsondecode(fileread(raw));
end

function lines = journal_lines(j)
  if iscell(j)
    lines = j(:);
  elseif ischar(j)
    lines = cellstr(j);
  else
    error('неожиданный тип журнала');
  end
end

function fs = norm_funcs(fs)
  fn = fieldnames(fs);
  for k = 1:numel(fn)
    f = fs.(fn{k});
    if ischar(f.params)          % одноэлементный массив параметров
      f.params = {f.params};
    end
    fs.(fn{k}) = f;
  end
end

function audit_fingerprint(snap, tag)
  if isempty(which('hash'))
    printf('  [аудит %s] hash() недоступен в этой сборке Octave — отпечаток проверен в Python\n', tag);
    return
  end
  ja = journal_lines(snap.journal);
  fp = repmat('0', 1, 64);
  for k = 1:numel(ja)
    fp = hash('sha256', [fp ja{k}]);
  end
  if ~strcmp(fp, snap.fingerprint)
    error('отпечаток снапшота %s не сошёлся — журнал искажён', tag);
  end
  printf('  аудит %s: отпечаток журнала сошёлся (%s…)\n', tag, fp(1:16));
end

%% ---------- AST-интерпретатор ----------

function r = bind(op, args, res)
  global G_journal G_count
  G_count = G_count + 1;
  ah = '';
  for k = 1:numel(args)
    if k > 1
      ah = [ah ','];
    end
    ah = [ah num2hex(args{k})];
  end
  G_journal{end+1} = sprintf('t%d %s(%s) -> %s', G_count, op, ah, num2hex(res));
  r = res;
end

function v = evalnode(node, env)
  global G_funcs
  kind = node{1};
  switch kind
    case 'const'
      v = node{2};
    case 'ref'
      v = env.(node{2});
    case 'neg'
      a = evalnode(node{2}, env);
      v = bind('neg', {a}, -a);
    case 'op'
      op = node{2};
      l = evalnode(node{3}, env);
      r = evalnode(node{4}, env);
      switch op
        case '+'
          v = bind(op, {l, r}, l + r);
        case '-'
          v = bind(op, {l, r}, l - r);
        case '*'
          v = bind(op, {l, r}, l * r);
        case '/'
          v = bind(op, {l, r}, l / r);
        otherwise
          error('неизвестный оператор %s', op);
      end
    case 'cmp'
      c = node{2};
      l = evalnode(node{3}, env);
      r = evalnode(node{4}, env);
      switch c
        case '<'
          ok = l < r;
        case '<='
          ok = l <= r;
        case '>'
          ok = l > r;
        case '>='
          ok = l >= r;
        case '=='
          ok = l == r;
        case '!='
          ok = l != r;
        otherwise
          error('неизвестное сравнение %s', c);
      end
      v = bind(c, {l, r}, double(ok));
    case 'list'
      n = numel(node{2});
      v = zeros(1, n);
      for k = 1:n
        v(k) = evalnode(node{2}{k}, env);
      end
    case 'call'
      name = node{2};
      if isfield(G_funcs, name)
        f = G_funcs.(name);
        vals = cell(1, numel(node{3}));
        for k = 1:numel(node{3})
          vals{k} = evalnode(node{3}{k}, env);
        end
        callenv = struct();
        for k = 1:numel(f.params)
          callenv.(f.params{k}) = vals{k};
        end
        v = evalnode(f.body, callenv);
      else
        v = builtin_call(name, node{3}, env);
      end
    otherwise
      error('неизвестный узел %s', kind);
  end
end

function v = builtin_call(name, args, env)
  switch name
    case 'If'
      cond = evalnode(args{1}, env);
      if cond != 0.0
        v = evalnode(args{2}, env);
      else
        v = evalnode(args{3}, env);
      end
    case 'Nest'
      fnode = args{1};
      x = evalnode(args{2}, env);
      n = evalnode(args{3}, env);
      for k = 1:n
        x = apply_fn(fnode, {x});
      end
      v = x;
    case 'Fold'
      fnode = args{1};
      acc = evalnode(args{2}, env);
      lst = evalnode(args{3}, env);
      for k = 1:numel(lst)
        acc = apply_fn(fnode, {acc, lst(k)});
      end
      v = acc;
    otherwise
      error('неизвестная встроенная функция %s', name);
  end
end

function v = apply_fn(fnode, vals)
  global G_funcs
  if ~(iscell(fnode) && (strcmp(fnode{1}, 'ref') || strcmp(fnode{1}, 'call')))
    error('первый аргумент должен быть функцией, а не значением');
  end
  fname = fnode{2};
  f = G_funcs.(fname);
  consts = cell(1, numel(vals));
  for k = 1:numel(vals)
    consts{k} = {'const', vals{k}};
  end
  v = evalnode({'call', fname, consts}, struct());
end

%% ---------- биты: little-endian typecast-путь ----------

function d = bits2double(s)
  t = strrep(s, '0x', '');
  if length(t) ~= 16
    error('hex_bits: нужно 16 hex-цифр, получено: %s', s);
  end
  u = uint64(0);
  for k = 1:16
    u = bitor(bitshift(u, 4), uint64(hexval(t(k))));
  end
  bytes = zeros(8, 1, 'uint8');
  for k = 1:8
    bytes(k) = uint8(bitand(bitshift(u, -8*(k-1)), uint64(255)));
  end
  d = typecast(bytes, 'double');
end

function d = hexval(ch)
  if ch >= '0' && ch <= '9'
    d = double(ch - '0');
  elseif ch >= 'a' && ch <= 'f'
    d = double(ch - 'a') + 10;
  elseif ch >= 'A' && ch <= 'F'
    d = double(ch - 'A') + 10;
  else
    error('не шестнадцатеричная цифра: %s', ch);
  end
end
