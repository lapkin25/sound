function replay_octave
% REPLAY_OCTAVE - зеркальный реплей журнала Sound на рантайме Octave.
% Читает снапшот (snap_mult.json либо snap_A.json), сверяет отпечаток
% журнала цепочкой sha256, затем переигрывает каждую операцию на своём
% рантайме и сверяет каждый результат бит-в-бит. Пользовательские функции
% берутся из AST снапшота - сценарий Octave не знает, он лишь дублёр.

  global G_env G_funcs
  if exist('snap_mult.json', 'file')
    fn = 'snap_mult.json';
  elseif exist('snap_A.json', 'file')
    fn = 'snap_A.json';
  else
    error('снапшот не найден: сначала запустите питонскую сторону');
  end

  S = jsondecode(fileread(fn));
  printf('== Реплей %s на Octave ==\n', fn);

  % --- 1. отпечаток: та же цепочка sha256, что в питонском хосте ---
  fp = repmat('0', 1, 64);
  for k = 1:numel(S.journal)
    fp = hash('sha256', [fp S.journal{k}]);
  end
  fp_ok = strcmp(fp, S.fingerprint);
  printf('  отпечаток: %s\n', fp);
  if fp_ok
    printf('  сверка отпечатка: сошёлся\n');
  else
    printf('  сверка отпечатка: РАСХОЖДЕНИЕ (в файле: %s)\n', S.fingerprint);
  end

  % --- 2. среда и функции из снапшота ---
  G_env = struct();
  G_funcs = struct();
  names = fieldnames(S.names);

  for k = 1:numel(names)
    name = names{k};
    if ~ischar(name)
      error(['Некорректное имя переменной: ' name]);
    end
    G_env.(name) = hex2val(S.names.(name));
  end

  fnames = fieldnames(S.funcs);
  for k = 1:numel(fnames)
    fname = fnames{k};
    if ~ischar(fname)
      error(['Некорректное имя функции: ' fname]);
    end
    if ~isstruct(S.funcs.(fname))
      error(['Данные функции ' fname ' не являются структурой']);
    end
    G_funcs.(fname) = S.funcs.(fname);
  end

  printf('  среда: %d имён, функций: %d\n', numel(names), numel(fnames));

  % --- 3. реплей: каждая строка журнала переигрывается и сверяется ---
  n_ok = 0; n_bad = 0;
  for k = 1:numel(S.journal)
    [n_ok, n_bad] = replay_line(S.journal{k}, n_ok, n_bad);
  end
  printf('  реплей: %d из %d операций сошлись\n', n_ok, n_ok + n_bad);
  if n_bad == 0 && fp_ok
    printf('ALL PASS\n');
  else
    printf('FAILED\n');
  end
end

function [n_ok, n_bad] = replay_line(line, n_ok, n_bad)
  global G_env
  m = regexp(line, '^(t\\d+) ([A-Za-z_*+\-/<>!=]+)(\\((.*?)\\)) -> (.+)$', 'tokens', 'once');
  if isempty(m)
    n_bad = n_bad + 1;
    printf('НЕ РАСПОЗНАНО: %s\n', line);
    return;
  end
  tn = m{1};
  op = m{2};
  payload = m{4};  % Изменённый индекс
  recorded = m{5};
  args = getargs(payload);
  [val, ok] = reapply(op, args, recorded);
  if ~ok
    n_bad = n_bad + 1;
    printf('НЕ ИЗВЕСТНА ОПЕРАЦИЯ %s %s\n', tn, op);
    return;
  end
  if strcmp(op, 'set')
    n_ok = n_ok + 1;   % set - источник истины: записанное значение и есть среда
    return;
  end
  got = hexof(val);
  if strcmp(got, recorded)
    n_ok = n_ok + 1;
  else
    n_bad = n_bad + 1;
    printf('РАСХОЖДЕНИЕ %s %s\n    ждали    %s\n    получили %s\n', tn, op, recorded, got);
  end
end



function [val, ok] = reapply(op, args, recorded)
  global G_env G_funcs
  ok = true; val = [];
  switch op
    case 'set'
      G_env.(args{1}) = hex2val(recorded);
    case '+'
      val = hex2val(args{1}) + hex2val(args{2});
    case '-'
      val = hex2val(args{1}) - hex2val(args{2});
    case '*'
      val = hex2val(args{1}) * hex2val(args{2});
    case '/'
      val = hex2val(args{1}) / hex2val(args{2});
    case 'neg'
      val = -hex2val(args{1});
    case {'<', '<=', '>', '>=', '==', '!='}
      val = itest(hex2val(args{1}), hex2val(args{2}), op);
    case 'mod'
      val = idiv(hex2val(args{1}), hex2val(args{2}), 'mod');
    case 'quotient'
      val = idiv(hex2val(args{1}), hex2val(args{2}), 'quotient');
    case 'part'
      lst = hex2val(args{1}); i = hex2val(args{2});
      k = round(i) + 1;
      if k < 1 || k > numel(lst)
        error('part: индекс вне списка');
      end
      val = lst(k);
    case 'fold'
      val = dofold(args{1}, hex2val(args{2}), hex2val(args{3}));
    case 'foldlist'
      val = dofold(args{1}, hex2val(args{2}), hex2val(args{3}));
    case 'table'
      fname = args{1};  % Используем как есть
      if ~ischar(fname)
        error(['Имя функции не является строкой: ' fname]);
      end
      fstruct = G_funcs.(fname);

      if ~isstruct(fstruct) || ~isfield(fstruct, 'params') || ~isfield(fstruct, 'body')
        error('table: первый аргумент не является функцией');
      end

      n = hex2val(args{2});
      val = dotable(fstruct, n);

    otherwise
      ok = false;
  end
end

function v = dofold(fstruct, acc, lst)
  if ~isstruct(fstruct)
    error('dofold: не структура функции');
  end
  for k = 1:numel(lst)
    acc = apply_fn(fstruct, {acc, lst{k}});
  end
  v = acc;
end


function v = dotable(fstruct, n)
  global G_env

  % Проверяем, что fstruct - это структура функции
  if ~isstruct(fstruct) || ~isfield(fstruct, 'params') || ~isfield(fstruct, 'body')
    error('dotable: получен не объект функции');
  end

  v = [];
  for k = 0:n-1
    callenv = struct();
    % Преобразуем параметр к строке
    param_name = string(fstruct.params{1});
    callenv.(param_name) = double(k);
    v(end+1) = evalnode(fstruct.body, callenv);
  end
end



function v = apply_fn(fstruct, vals)
  % Проверяем, что это структура функции
  if ~isstruct(fstruct) || ~isfield(fstruct, 'params') || ~isfield(fstruct, 'body')
    error(['apply_fn получил не структуру функции: ' fstruct]);
  end

  callenv = struct();

  if numel(vals) ~= numel(fstruct.params)
    error(['арность функции: ожидалось ' num2str(numel(fstruct.params)) ', получено ' num2str(numel(vals))]);
  end

  for k = 1:numel(fstruct.params)
    param_name = fstruct.params{k};  % Убираем string()
    callenv.(param_name) = vals{k};
  end

  v = evalnode(fstruct.body, callenv);
end



function v = evalnode(node, env)
  global G_env G_funcs
  if ~iscell(node)
    error('evalnode получил значение, а не узел: %g (двойное вычисление аргументов?)', node);
  end
  k = node{1};
  switch k
    case 'const'
      v = node{2};
    case 'ref'
      nm = node{2};  % Убираем string()
      if isfield(env, nm)
        v = env.(nm);
      elseif isfield(G_env, nm)
        v = G_env.(nm);
      else
        error(['имя ' nm ' не задано']);
      end

    case 'neg'
      v = -evalnode(node{2}, env);
    case 'op'
      l = evalnode(node{3}, env);
      r = evalnode(node{4}, env);
      switch node{2}
        case '+', v = l + r;
        case '-', v = l - r;
        case '*', v = l * r;
        case '/', v = l / r;
        otherwise, error('операция %s', node{2});
      end
    case 'cmp'
      l = evalnode(node{3}, env);
      r = evalnode(node{4}, env);
      switch node{2}
        case '<',  b = l < r;
        case '<=', b = l <= r;
        case '>',  b = l > r;
        case '>=', b = l >= r;
        case '==', b = l == r;
        case '!=', b = l != r;
        otherwise, error('сравнение %s', node{2});
      end
      v = double(b);
    case 'list'
      items = node{2};
      v = [];
      for j = 1:numel(items)
        v(end+1) = evalnode(items{j}, env);
      end
    case 'call'
      name = string(node{2});  % Добавляем преобразование в строку
      printf('evalnode: проверяем вызов функции %s\n', name);
      if ~ischar(name)
        error('Имя функции не является строкой: %s', mat2str(name));
      end
      if isfield(G_funcs, name)
        % пользовательская функция: аргументы вычисляются здесь, до тела
        f = G_funcs.(name);
        vals = cell(1, numel(node{3}));
        for k = 1:numel(node{3})
          vals{k} = evalnode(node{3}{k}, env);
        end
        callenv = struct();
        for k = 1:numel(f.params)
          param_name = string(f.params{k});  % Добавляем преобразование в строку
          callenv.(param_name) = vals{k};
        end
        v = evalnode(f.body, callenv);
      else
        % встроенная: аргументы отдаём УЗЛАМИ, builtin_call вычисляет сам
        v = builtin_call(name, node{3}, env);
      end

    otherwise
      error('узел %s', k);
  end
end

function v = builtin_call(name, args, env)
  global G_env G_funcs
  switch name
    case 'If'
      cond = evalnode(args{1}, env);
      if cond ~= 0.0
        v = evalnode(args{2}, env);
      else
        v = evalnode(args{3}, env);
      end

    case 'Nest'
      fstruct = G_funcs.(string(args{1}));  % Добавляем string()
      x = evalnode(args{2}, env);
      n = evalnode(args{3}, env);
      for k = 1:round(n)
        x = apply_fn(fstruct, {x});
      end
      v = x;

    case 'NestList'
      fstruct = G_funcs.(string(args{1}));  % Добавляем string()
      x = evalnode(args{2}, env);
      n = evalnode(args{3}, env);
      v = x;
      for k = 1:round(n)
        x = apply_fn(fstruct, {x});
        v(end+1) = x;
      end

    case 'Fold'
      fstruct = G_funcs.(string(args{1}));  % Добавляем string()
      acc = evalnode(args{2}, env);
      lst = evalnode(args{3}, env);
      for k = 1:numel(lst)
        acc = apply_fn(fstruct, {acc, lst(k)});
      end
      v = acc;

    case 'FoldList'
      fstruct = G_funcs.(string(args{1}));  % Добавляем string()
      acc = evalnode(args{2}, env);
      lst = evalnode(args{3}, env);
      v = acc;
      for k = 1:numel(lst)
        acc = apply_fn(fstruct, {acc, lst{k}});  % передаём узлы
        v(end+1) = acc;
      end

    case 'Table'
      fname = string(args{1});  % Добавляем явное преобразование
      printf('builtin_call: проверяем функцию %s\n', fname);
      if ~ischar(fname)
        error('Имя функции не является строкой: %s', mat2str(fname));
      end
      % Получаем структуру функции
      fstruct = G_funcs.(fname);

      if ~isstruct(fstruct) || ~isfield(fstruct, 'params') || ~isfield(fstruct, 'body')
        error('Table: первый аргумент не является функцией');
      end

      n = evalnode(args{2}, env);
      v = [];
      for k = 0:round(n)-1
        callenv = struct();
        % Преобразуем параметр к строке
        param_name = string(fstruct.params{1});
        callenv.(param_name) = double(k);
        v(end+1) = evalnode(fstruct.body, callenv);
      end

    case 'Mod'
      a = evalnode(args{1}, env); b = evalnode(args{2}, env);
      if b == 0.0, error('Mod: деление на ноль'); end
      q = floor(a / b);
      while q * b > a, q = q - 1; end
      while (q + 1.0) * b <= a, q = q + 1.0; end
      v = a - q * b;
    case 'Quotient'
      a = evalnode(args{1}, env); b = evalnode(args{2}, env);
      if b == 0.0, error('Quotient: деление на ноль'); end
      q = floor(a / b);
      while q * b > a, q = q - 1; end
      while (q + 1.0) * b <= a, q = q + 1.0; end
      v = q;
    case 'Part'
      lst = evalnode(args{1}, env);
      i = evalnode(args{2}, env);
      if i < 0.0 || i >= numel(lst), error('Part: индекс вне списка'); end
      v = lst(round(i) + 1);
    otherwise
      error('неизвестная функция %s', name);
  end
end

function r = idiv(a, b, kind)
  if b == 0.0
    error('%s: деление на ноль', kind);
  end
  q = floor(a / b);
  while q * b > a
    q = q - 1.0;
  end
  while (q + 1.0) * b <= a
    q = q + 1.0;
  end
  if strcmp(kind, 'mod')
    r = a - q * b;
  else
    r = q;
  end
end

function v = itest(a, b, op)
  switch op
    case '<',  r = a < b;
    case '<=', r = a <= b;
    case '>',  r = a > b;
    case '>=', r = a >= b;
    case '==', r = a == b;
    case '!=', r = a != b;
  end
  v = double(r);
end

% Канон списков: 'N|h1,h2,...' - без скобок и пробелов, ровно как canon_bits.
function s = hexof(x)
  if isvector(x) && numel(x) > 1
    parts = cell(1, numel(x));
    for j = 1:numel(x)
      parts{j} = num2hex(x(j));
    end
    s = sprintf('%d|%s', numel(x), strjoin(parts, ','));
  else
    s = num2hex(x);
  end
end

% Обратный канон: 'N|...' - список, 16-hex - скаляр, иначе - имя функции.
function v = hex2val(tok)
  #printf('hex2val: обрабатываем токен %s, тип: %s\n', tok, class(tok));
  p = strfind(tok, '|');
  if ~isempty(p)
    n = str2double(tok(1:p(1)-1));
    rest = tok(p(1)+1:end);
    parts = strsplit(rest, ',');
    v = zeros(1, n);
    for j = 1:n
      v(j) = hex2num(parts{j});
    end
  elseif numel(tok) == 16 && all(ismember(tok, '0123456789abcdef'))
    v = hex2num(tok);
  else
    #printf('hex2val: возвращаем имя функции %s\n', tok);
    v = string(tok);  % имя функции (fold/foldlist/table)
  end
end

% Разбор аргументов: запятая - разделитель ВЕРХНЕГО уровня; внутри списка
% 'N|h,h,h' запятые съедаются, пока не исчерпаны N hex-групп по 16 символов.
function args = getargs(s)
  args = {};
  i = 1; L = numel(s);
  while i <= L
    if s(i) == ','
      i = i + 1;
    else
      j = i;
      while j <= L && isdigit(s(j))
        j = j + 1;
      end
      if j <= L && s(j) == '|' && j > i
        n = str2double(s(i:j-1));
        start = i;
        i = j + 1;
        for g = 1:n
          while i <= L && s(i) == ','
            i = i + 1;
          end
          i = i + 16;
        end
        args{end+1} = s(start:i-1);
      else
        j2 = i;
        while j2 <= L && s(j2) ~= ','
          j2 = j2 + 1;
        end
        args{end+1} = s(i:j2-1);
        i = j2;
      end
    end
  end
end
