function replay_octave
% REPLAY_OCTAVE - зеркальный реплей журнала Sound на рантайме Octave.
% Читает снапшот (snap_mult.json либо snap_A.json), сверяет отпечаток
% журнала цепочкой sha256, затем переигрывает каждую операцию на своём
% рантайме и сверяет каждый результат бит-в-бит. Пользовательские функции
% берутся из AST снапшота - сценарий Octave не знает, он лишь дублёр.
% Запуск:  octave --eval replay_octave
% Требования: Octave >= 7 (jsondecode); hash с SHA256 (встроен).

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
    G_env.(names{k}) = hex2val(S.names.(names{k}));
  end
  fnames = fieldnames(S.funcs);
  for k = 1:numel(fnames)
    G_funcs.(fnames{k}) = S.funcs.(fnames{k});
  end
  printf('  среда: %d имён, функций: %d\n', numel(names), numel(fnames));
  #isfield(G_funcs, 'mul10')
  #printf('Доступные функции: %s\n')
  #fieldnames(G_funcs)
  #if isfield(G_funcs, 'mul10')
  #disp(G_funcs.mul10)
  #end
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
  m = regexp(line, '^(t\d+) ([A-Za-z_*+\-/<>!=]+)\((.*?)\) -> (.+)$', 'tokens', 'once');
  if isempty(m)
    n_bad = n_bad + 1;
    printf('НЕ РАСПОЗНАНО: %s\n', line);
    return;
  end
  tn = m{1}; op = m{2}; payload = m{3}; recorded = m{4};
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
      12345
      acc = hex2val(args{2}); lst = hex2val(args{3});
      out = acc;
      for j = 1:numel(lst)
        acc = dofold(args{1}, acc, lst(j));
        out(end+1) = acc;
      end
      val = out;
    case 'table'
      1234
      val = dotable(G_funcs.(args{1}), hex2val(args{2}));
    otherwise
      ok = false;
  end
end

function out = dofold(fname, acc, lst)
  for j = 1:numel(lst)
    acc = apply_fn(fname, {acc, lst(j)});
  end
  out = acc;
end

function v = dotable(fstruct, n)
  global G_env

  % Проверяем корректность входных данных
  if ~isstruct(fstruct) || ~isfield(fstruct, 'params') || ~isfield(fstruct, 'body')
    error('dotable: получен не объект функции');
  end

  v = [];  % Инициализируем результат как пустой массив

  % Создаем таблицу значений от 0 до n-1
  for k = 0:n-1
    callenv = struct();  % Создаем локальную среду выполнения

    % Преобразуем параметр к строке
    param_name = fstruct.params{1};
    callenv.(param_name) = double(k);  % Присваиваем текущее значение параметра
    % Вычисляем значение функции в данной точке
    v(end+1) = evalnode(fstruct.body, callenv);
  end
end


function v = apply_fn(fname, vals)
  global G_funcs
  printf('apply_fn');
  fname
  f = G_funcs.(fname);
  callenv = struct();
  for j = 1:numel(vals)
    callenv.(f.params{j}) = vals{j};
  end
  v = evalnode(f.body, callenv);
end

function v = evalnode(node, env)
  global G_env G_funcs
  % Перед вызовом evalnode
  if ~iscell(node)
    disp(['Ошибка: передан не узел, а значение: ', mat2str(node)]);
  end
  #node
  k = node{1};
  printf('Обработка узла типа: %s\n', k);  % Добавить отладку
  switch k
    case 'const'
      v = node{2};
    case 'ref'
      nm = node{2};
      if isfield(env, nm)
        v = env.(nm);
        printf('Найдено в локальном окружении: %s\n', nm);
      elseif isfield(G_env, nm)
        v = G_env.(nm);
        printf('Найдено в глобальном окружении: %s\n', nm);
      elseif isfield(G_funcs, nm)
        v = G_funcs.(nm);
        printf('Найдено в функциях: %s\n', nm);
      else
        error('имя %s не задано', nm);
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
        name = node{2};
        argn = node{3};
        args = cell(1, numel(argn));

        for j = 1:numel(argn)
            current_arg = argn{j};
            if iscell(current_arg)  % Если это узел
                args{j} = evalnode(current_arg, env);
            elseif isnumeric(current_arg) || ischar(current_arg)  % Если это простое значение
                args{j} = current_arg;
            else
                error(['Некорректный тип аргумента: ', class(current_arg)]);
            end
        end

        if isfield(G_funcs, name)
           f = G_funcs.(name);
           callenv = struct();
        % ... создание окружения ...
           v = evalnode(f.body, callenv);
        else
           v = builtin_call(name, args, env);
        end
    otherwise
      error('узел %s', k);
  end
end

function v = builtin_call(name, args, env)
  switch name
    case 'If'
      c = evalnode(args{1}, env);
      if c ~= 0.0
        v = evalnode(args{2}, env);
      else
        v = evalnode(args{3}, env);
      end
    case 'Nest'
      f = args{1};
      x = evalnode(args{2}, env);
      n = round(evalnode(args{3}, env));
      for k = 1:n
        x = apply_fn(f{2}, {x});
      end
      v = x;
    case 'Fold'
      f = args{1};
      acc = evalnode(args{2}, env);
      lst = evalnode(args{3}, env);
      for k = 1:numel(lst)
        acc = apply_fn(f{2}, {acc, lst(k)});
      end
      v = acc;
    case 'FoldList'
      f = args{1};
      acc = evalnode(args{2}, env);
      lst = evalnode(args{3}, env);
      out = acc;
      for k = 1:numel(lst)
        acc = apply_fn(f{2}, {acc, lst(k)});
        out(end+1) = acc;
      end
      v = out;
    case 'Table'
      f = args{1};
      n = round(evalnode(args{2}, env));
      fdef = G_funcs.(f{2});
      v = [];
      for k = 0:n-1
        callenv = struct();
        callenv.(fdef.params{1}) = double(k);
        v(end+1) = evalnode(fdef.body, callenv);
      end
    case 'Mod'
      v = idiv(evalnode(args{1}, env), evalnode(args{2}, env), 'mod');
    case 'Quotient'
      v = idiv(evalnode(args{1}, env), evalnode(args{2}, env), 'quotient');
    case 'Part'
      lst = evalnode(args{1}, env);
      i = evalnode(args{2}, env);
      k = round(i) + 1;
      if k < 1 || k > numel(lst)
        error('Part: индекс вне списка');
      end
      v = lst(k);
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
    v = tok;  % имя функции (fold/foldlist/table)
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
