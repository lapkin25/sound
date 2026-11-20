%% conform_sheet_octave.m
%% Кросс-хост-конформанс листа: Octave против Python-эталона (sheet_meta.py).
%% Сравнение — по каноническим строкам (canon.m, этап 1): биты IEEE, не числа.
%%
%% Запуск:   octave --eval conform_sheet_octave
%% Требует:  canon.m (этап 1) в той же директории, sheet_fixtures.json (этап 3),
%%           Octave 7+ (нужен jsondecode).
%%
%% Схема фикстур (генерирует sheet_meta.py):
%%   {
%%     "target": "dist",
%%     "columns": [
%%       {"name":"time","role":"input","type":"Float64","unit":"s"},
%%       {"name":"half","role":"const","type":"Float64","unit":"1","value":0.5},
%%       {"name":"g","role":"const","type":"Float64","unit":"m/s^2","value":9.81},
%%       {"name":"dist","role":"computed","type":"Float64","unit":"m",
%%        "formula": {"op":"*","l":{"ref":"time"},
%%                          "r":{"op":"*","l":{"ref":"half"},
%%                                    "r":{"op":"*","l":{"ref":"time"},
%%                                              "r":{"ref":"g"}}}},
%%        "invariant": {"cmp":">=","l":{"ref":"dist"},"r":{"const":0}}}
%%     ],
%%     "vectors": [
%%       {"name":"j01","binds":{"time":45.0,"half":0.5,"g":9.81},
%%        "expect":{"hex_bits":"0x1.3665000000001p+13"}},
%%       {"name":"neg-half","binds":{"time":45.0,"half":-0.5,"g":9.81},
%%        "expect":{"err":"err DomainError dist: invariant"}}
%%     ]
%%   }
%%
%% Бинды — ровно транзитивные входы целевой колонки, в порядке объявления.
%% Значение бинда: число или "0x..." — 16 шестнадцатеричных цифр битов IEEE-дабла
%% (для NaN, -0.0 и прочего, что через JSON-число не передать честно).

function conform_sheet_octave()
  printf("== conform_sheet (Octave) ==\n");

  if exist("canon", "file") ~= 2
    error("canon.m не найден — положите его рядом (набор этапа 1)");
  end
  if ~exist("jsondecode", "builtin")
    error("нужен Octave 7+ (jsondecode)");
  end

  fx = jsondecode(fileread("sheet_fixtures.json"));
  cols  = fx.columns;
  vecs  = fx.vectors;
  target = fx.target;
  cols = normalize_cols(cols);

  deps = transitive_closure(cols, target);
  check_order(cols, deps);

  passed = 0; total = numel(vecs);
  for v = 1:total
    if iscell(vecs), vec = vecs{v}; else vec = vecs(v); end
    [hexout, errline] = run_vector(cols, deps, target, vec);
    if isfield(vec, "expect") && isfield(vec.expect, "err") && ~isempty(vec.expect.err)
      want = vec.expect.err;  got = errline;  tag = "err";
    else
      want = vec.expect.hex_bits;  got = hexout;  tag = "val";
    end
    if strcmp(want, got)
      passed += 1;
      printf("PASS (%s) %s = %s\n", tag, vec.name, got);
    else
      printf("FAIL (%s) %s\n  want: %s\n  got : %s\n", tag, vec.name, want, got);
    end
  end

  if passed == total
    printf("ALL PASS (%d/%d)\n", passed, total);
  else
    printf("FAILED (%d/%d)\n", passed, total);
  end
end

%% --- замыкание: цель + все её транзитивные ссылки, в порядке объявления ---
function deps = transitive_closure(cols, target)
  n = numel(cols);
  seen = false(1, n);
  seen(find_col(cols, target)) = true;
  front = tree_refs(cols(find_col(cols, target)).formula);
  while ~isempty(front)
    j = find_col(cols, front{1});
    front(1) = [];
    if seen(j), continue; end
    seen(j) = true;
    if strcmp(cols(j).role, "computed")
      front = [front, tree_refs(cols(j).formula)];
    end
  end
  deps = find(seen);
end

%% --- порядок: каждая вычисляемая колонка ссылается только на уже объявленные ---
function check_order(cols, deps)
  for k = deps
    c = cols(k);
    if strcmp(c.role, "computed")
      for r = tree_refs(c.formula)
        j = find_col(cols, r);
        if j >= k || ~ismember(j, deps)
          error("порядок: %s ссылается на %s позже объявления", c.name, r);
        end
      end
    end
  end
end

%% --- один вектор: бинды -> вычисление -> инвариант пост-фактум -> canon ---
function [hexout, errline] = run_vector(cols, deps, target, vec)
  hexout = ""; errline = "";

  % jsondecode сводит поля разных векторов в объединение — пустые бинды не бинды
  bind_names = {};
  if isfield(vec, "binds")
    fn = fieldnames(vec.binds);
    for k = 1:numel(fn)
      if ~isempty(vec.binds.(fn{k}))
        bind_names{end+1} = fn{k};   %#ok<AGROW>
      end
    end
  end

  closure_names = {cols(deps).name};
  inputs = {};
  for k = 1:numel(deps)
    if strcmp(cols(deps(k)).role, "input")
      inputs{end+1} = cols(deps(k)).name;  %#ok<AGROW>
    end
  end

  for k = 1:numel(bind_names)
    if ~any(strcmp(closure_names, bind_names{k}))
      errline = sprintf("err BindSet %s: лишний бинд %s", vec.name, bind_names{k});
      return
    end
  end
  for k = 1:numel(inputs)
    if ~any(strcmp(bind_names, inputs{k}))
      errline = sprintf("err BindSet %s: не задан вход %s", vec.name, inputs{k});
      return
    end
  end

  env = struct();
  for k = 1:numel(deps)
    c = cols(deps(k));
    switch c.role
      case "const"
        if any(strcmp(bind_names, c.name))
          env.(c.name) = bind_value(vec.binds.(c.name));
        else
          env.(c.name) = c.value;
        end
      case "input"
        env.(c.name) = bind_value(vec.binds.(c.name));
      case "computed"
        val = eval_tree(c.formula, env);
        env.(c.name) = val;
        % инвариант — пост-фактум, на вычисленной колонке (листовая семантика)
        if isfield(c, "invariant") && ~isempty(c.invariant) && ~eval_cmp(c.invariant, env)
          errline = sprintf("err DomainError %s: invariant", c.name);
          return
        end
    end
  end

  hexout = canon(env.(target));
end

function val = bind_value(b)
  if ischar(b) || isstring(b)
    val = bits2double(char(b));
  else
    val = double(b);
  end
end

%% --- дерево выражений: const / ref / op(+,-,*,/,neg) ---
function val = eval_tree(t, env)
  if isempty(t) || ~isstruct(t)
    error("пустой узел дерева");
  end
  if isfield(t, "const"); val = t.const; return; end
  if isfield(t, "ref");   val = env.(t.ref);  return; end
  if isfield(t, "op")
    switch t.op
      case "+"   val = eval_tree(t.l, env) + eval_tree(t.r, env);
      case "-"   val = eval_tree(t.l, env) - eval_tree(t.r, env);
      case "*"   val = eval_tree(t.l, env) * eval_tree(t.r, env);
      case "/"   val = eval_tree(t.l, env) / eval_tree(t.r, env);
      case "neg" val = -eval_tree(t.a, env);
      otherwise  error("неизвестная операция: %s", t.op);
    end
    return
  end
  error("неизвестный узел дерева");
end

%% --- дерево сравнения для инвариантов ---
function ok = eval_cmp(t, env)
  a = eval_tree(t.l, env);
  b = eval_tree(t.r, env);
  switch t.cmp
    case "<"   ok = a <  b;
    case "<="  ok = a <= b;
    case ">"   ok = a >  b;
    case ">="  ok = a >= b;
    case "=="  ok = a == b;
    case "!="  ok = a != b;
    otherwise  error("неизвестное сравнение: %s", t.cmp);
  end
end

function refs = tree_refs(t)
  refs = {};
  if isempty(t) || ~isstruct(t), return; end
  if isfield(t, "ref")
    refs{1} = t.ref;
  elseif isfield(t, "op")
    refs = horzcat(tree_refs(t.l), tree_refs(t.r));
  end
end

function j = find_col(cols, nm)
  hits = find(strcmp({cols.name}, nm));
  if numel(hits) ~= 1
    error("колонка %s не найдена или дублируется", nm);
  end
  j = hits(1);
end

%% --- биты -> double. На входе 16 hex-цифр; байты кладутся младшими вперёд
%% (x86 little-endian). На big-endian-хосте нужен flip — как в этапе 2. ---
function d = bits2double(s)
  t = strrep(s, "0x", "");
  if length(t) ~= 16
    error("hex_bits: нужно 16 шестнадцатеричных цифр, получено: %s", s);
  end
  u = uint64(0);
  for k = 1:16
    u = bitor(bitshift(u, 4), uint64(hexval(t(k))));
  end
  bytes = zeros(8, 1, "uint8");
  for k = 1:8
    bytes(k) = uint8(bitand(bitshift(u, -8*(k-1)), uint64(255)));
  end
  d = typecast(bytes, "double");
end

function d = hexval(ch)
  if ch >= "0" && ch <= "9"
    d = double(ch - "0");
  elseif ch >= "a" && ch <= "f"
    d = double(ch - "a") + 10;
  elseif ch >= "A" && ch <= "F"
    d = double(ch - "A") + 10;
  else
    error("не шестнадцатеричная цифра: %s", ch);
  end
end

%% --- jsondecode при разнородных полях возвращает cell структур:
%% выравниваем в struct-массив с полным набором полей ---
function cols = normalize_cols(cols)
  if ~iscell(cols), cols = {cols}; end

  base = struct("name", "", "role", "", "type", "", "unit", "", ...
                "formula", "", "value", NaN, "invariant", "");
  out = repmat(base, 1, numel(cols));
  for k = 1:numel(cols)
    c = cols{k};
    if isstruct(c)
      fn = fieldnames(c);
      for i = 1:numel(fn)
        out(k).(fn{i}) = c.(fn{i});
      end
    end
  end
  cols = out;
end

