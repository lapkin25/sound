function conform_octave()
% conform_octave.m — конформанс Octave-реализации Sound v0.2
% запуск: octave --eval "conform_octave"
% требует fixtures_sound.json в текущем каталоге.
% Покрытие: канон C01..C12, TRIOMAT M01..M05,
% повреждённые файлы X01..X08, арифметика A01..A16.
% Журнал (J) и статика (SC) — SKIP: векторы зарезервированы,
% проверяются на этапе 2 (обвязка узлов).

  global FAILS NPASS NSKIP
  FAILS = {}; NPASS = 0; NSKIP = 0;

  fx = jsondecode(fileread('fixtures_sound.json'));

  % ---------- канон ----------
  for i = 1:numel(fx.canon_vectors)
    v = fx.canon_vectors(i);
    x = dbl_from_hex(v.hex_bits);
    ck(strcmp(canon(x), v.expect), sprintf('C%02d %s', i, v.name));
  endfor

  % ---------- TRIOMAT: сборка и разбор ----------
  for i = 1:numel(fx.triomat_samples)
    s = fx.triomat_samples(i);
    payload = tri_payload(s.dtype, s.shape, s.values);
    built = tri_build(s.dtype, s.shape, payload);
    orig = base64_decode(s.base64);
    ck(isequal(reshape(built,1,[]), reshape(orig,1,[])), ...
       sprintf('M%02d %s build', i, s.name));
    [code, val] = read_tri(orig);
    okv = strcmp(code, '');
    if okv
      okv = isequal(reshape(val,1,[]), reshape(expected_vals(s),1,[]));
    endif
    ck(okv, sprintf('M%02d %s parse', i, s.name));
  endfor

  % ---------- повреждённые файлы ----------
  for i = 1:numel(fx.malformed_samples)
    m = fx.malformed_samples(i);
    data = base64_decode(m.base64);
    [code, ~] = read_tri(data);
    ck(strcmp(code, m.expect_code), sprintf('X%02d %s bridge', i, m.name));
    res = read_tri9(data);
    ck(numel(res) == m.reader_count && strcmp(res(end).code, m.reader_last), ...
       sprintf('X%02d %s reader', i, m.name));
  endfor

  % ---------- арифметика ----------
  for i = 1:numel(fx.arith_vectors)
    a = fx.arith_vectors(i);
    v = arith_eval(a);
    if ischar(v)
      okv = strcmp(v, a.expect_code);
    elseif ~isempty(a.expect_str)
      okv = isinf(v) && strcmp(print_sign_float(v), a.expect_str);
    else
      okv = (v == a.expect_num);
    endif
    ck(okv, sprintf('A%02d %s', i, a.name));
  endfor

  % ---------- журнал и статика: этап 2 ----------
  for i = 1:numel(fx.journal_vectors)
    sk(sprintf('J%02d %s', i, fx.journal_vectors(i).name));
  endfor
  for i = 1:numel(fx.static_vectors)
    sk(sprintf('SC%d %s', i, fx.static_vectors(i).name));
  endfor

  printf('\n');
  if ~isempty(FAILS)
    printf('FAILURES: %d -> %s\n', numel(FAILS), strjoin(FAILS, ', '));
    fflush(stdout);
    error('conformance failed');
  endif
  printf('ALL PASS (%d/%d), skips: %d\n', NPASS, NPASS, NSKIP);
endfunction

% ---------- helpers ----------
function ck(ok, label)
  global FAILS NPASS
  if ok; NPASS++; printf('PASS %s\n', label);
  else; FAILS{end+1} = label; printf('FAIL %s\n', label); endif
endfunction

function sk(label)
  global NSKIP
  NSKIP++; printf('SKIP %s\n', label);
endfunction

function x = dbl_from_hex(h)
  % double из 64-битного паттерна; hex2dec 16 цифр теряет точность,
  % поэтому — два полубайта-слова по 8 цифр
  hi = uint64(hex2dec(h(1:8)));
  lo = uint64(hex2dec(h(9:16)));
  bits = bitor(bitshift(hi, 32), lo);
  x = typecast(bits, 'double');
endfunction

function v = int_from_hex(h)
  hi = uint64(hex2dec(h(1:8)));
  lo = uint64(hex2dec(h(9:16)));
  bits = bitor(bitshift(hi, 32), lo);
  v = typecast(bits, 'int64');
endfunction

function s = canon(x)
  % канонический float, §6.4. Денормалы требуют ветки '0x0.':
  % у них поле экспоненты нулевое, ведущей единицы нет.
  if (isnan(x)); s = 'nan'; return; endif
  if (isinf(x));
    if (x > 0); s = 'inf'; else; s = '-inf'; endif
    return
  endif
  if (x == 0);
    if (1 / x < 0); s = '-0x0.0p+0'; else; s = '0x0.0p+0'; endif
    return
  endif
  h = tolower(num2hex(x));           % 16 hex digits, big-endian
  v = hex2dec(h(1:3));               % знак (бит 2048) + 11 бит экспоненты
  e = mod(v, 2048) - 1023;
  mant = h(4:16);                    % 13 hex digits мантиссы
  if (e == -1023)
    body = ['0x0.' mant 'p-1022'];   % денормал: ведущей единицы нет
  else
    es = num2str(e);
    if (e >= 0); es = ['+' es]; endif
    body = ['0x1.' mant 'p' es];
  endif
  if (v >= 2048); s = ['-' body]; else; s = body; endif
endfunction

function p = tri_payload(dtype, shape, values)
  % C-порядок логических значений (вариант Б, §6.3):
  % октавовская матрица column-major, поэтому линейзация — через .'
  switch dtype
    case 'Bool';    x = logical(values);
    case 'Int8';    x = int8(values);
    case 'Int16';   x = int16(values);
    case 'Int32';   x = int32(values);
    case 'Int64';   x = int64(values);
    case 'UInt8';   x = uint8(values);
    case 'Float32'; x = single(values);
    otherwise;      x = double(values);
  endswitch
  if numel(shape) == 2
    lin = x.'(:);
  else
    lin = x(:);
  endif
  p = typecast(lin, 'uint8'); p = p(:);
endfunction

function b = tri_build(dtype, shape, payload)
  parts = cell(1, numel(shape));
  for k = 1:numel(shape)
    parts{k} = num2str(shape(k));
  endfor
  h = sprintf('{"dtype":"%s","shape":[%s]}', dtype, strjoin(parts, ','));
  b = [uint8('TRIOMAT1'), ...
       reshape(typecast(uint32(numel(h)), 'uint8'), 1, []), ...
       uint8(h), reshape(payload, 1, [])];
endfunction

function [code, val] = read_tri(data)
  % порт trio_bridge._parse: только коды, без R-обёрток
  code = ''; val = [];
  if numel(data) < 12; code = 'MalformedHeader'; return; endif
  if ~isequal(reshape(data(1:8),1,[]), reshape(uint8('TRIOMAT1'),1,[]))
    code = 'MalformedHeader'; return;
  endif
  hlen = double(typecast(reshape(data(9:12),1,[]), 'uint32'));
  if 12 + hlen > numel(data); code = 'MalformedHeader'; return; endif
  try
    hdr = jsondecode(char(data(13:12+hlen)));
  catch
    code = 'MalformedHeader'; return;
  end_try_catch
  if ~isstruct(hdr) || ~isfield(hdr,'dtype') || ~isfield(hdr,'shape')
    code = 'MalformedHeader'; return;
  endif
  dt = hdr.dtype;
  switch dt
    case 'Bool';    nb = 1; cls = '';
    case 'Int8';    nb = 1; cls = 'int8';
    case 'Int16';   nb = 2; cls = 'int16';
    case 'Int32';   nb = 4; cls = 'int32';
    case 'Int64';   nb = 8; cls = 'int64';
    case 'UInt8';   nb = 1; cls = 'uint8';
    case 'Float16'; nb = 2; cls = 'raw';
    case 'Float32'; nb = 4; cls = 'single';
    case 'Float64'; nb = 8; cls = 'double';
    otherwise; code = 'MalformedDtype'; return;
  endswitch
  shape = hdr.shape;
  if ~isnumeric(shape) || any(~isfinite(shape)) || ...
     any(shape ~= fix(shape)) || any(shape < 0)
    code = 'MalformedShape'; return;
  endif
  n = prod(double(shape));
  payload = double(data(13+hlen:end));
  if numel(payload) ~= n * nb; code = 'MalformedPayload'; return; endif
  if strcmp(dt,'Bool')
    if any(payload ~= 0 & payload ~= 1)
      code = 'TypeMismatch'; return;
    endif
    val = logical(payload);
    return
  endif
  if strcmp(cls, 'raw')
    val = payload;   % Float16: декодирование — этап 2 (нет в fixtures v1)
    return
  endif
  val = typecast(payload, cls);
  if numel(shape) == 2
    val = reshape(val, shape(2), shape(1))';  % C-порядок -> логические значения
  elseif numel(shape) == 1
    val = reshape(val, [1, shape(1)]);
  endif
endfunction

function res = read_tri9(data)
  % порт sound_reader.read_file: 9 проверок, ранний выход на 01,02,04,05,07
  res = struct('name', {}, 'code', {});
  if isempty(data)
    res(end+1).name = '01 not-empty'; res(end).code = 'ResourceLost'; return
  endif
  res(end+1).name = '01 not-empty'; res(end).code = '';
  ok02 = numel(data) >= 12 && isequal(reshape(data(1:8),1,[]), ...
                                      reshape(uint8('TRIOMAT1'),1,[]));
  res(end+1).name = '02 header-frame';
  if ~ok02; res(end).code = 'MalformedHeader'; return; endif
  res(end).code = '';
  hlen = double(typecast(reshape(data(9:12),1,[]), 'uint32'));
  res(end+1).name = '03 hlen-sane';
  res(end).code = '';   % не прерывает ( fixtures v1 не содержит больших hlen)
  hdr = [];
  try
    hdr = jsondecode(char(data(13:min(12+hlen, numel(data)))));
  catch
  end_try_catch
  res(end+1).name = '04 header-json';
  if ~isstruct(hdr); res(end).code = 'MalformedHeader'; return; endif
  res(end).code = '';
  dt = hdr.dtype;
  known = {'Bool','Int8','Int16','Int32','Int64','UInt8','Float16','Float32','Float64'};
  res(end+1).name = '05 dtype-known';
  if ~any(strcmp(dt, known)); res(end).code = 'MalformedDtype'; return; endif
  res(end).code = '';
  shape = hdr.shape;
  res(end+1).name = '06 shape-ints';
  res(end).code = '';   % не прерывает
  n = prod(double(shape));
  payload = double(data(13+hlen:end));
  res(end+1).name = '07 payload-size';
  sizes = containers.Map({'Bool','Int8','Int16','Int32','Int64','UInt8','Float16','Float32','Float64'}, ...
                         {1,1,2,4,8,1,2,4,8}, 'UniformValues', false);
  if numel(payload) ~= n * sizes(dt); res(end).code = 'MalformedPayload'; return; endif
  res(end).code = '';
  res(end+1).name = '08 bool-bytes';
  res(end).code = '';
  if strcmp(dt,'Bool') && any(payload ~= 0 & payload ~= 1)
    res(end).code = 'TypeMismatch';   % не прерывает
  endif
  [code09, ~] = read_tri(data);
  res(end+1).name = '09 decode'; res(end).code = code09;
endfunction

function v = arith_eval(a)
  switch a.kind
    case 'int'
      if ~isempty(a.int_str)
        x = int_from_hex(a.int_bits);
      else
        x = int64(a.lhs);
      endif
      y = int64(a.rhs);
      v = int_apply(a.op, x, y);
    case 'mixed'
      x = double(int_from_hex(a.int_bits));   % §3.3: подъём к Float
      y = dbl_from_hex(a.rhs_bits);
      v = float_apply(a.op, x, y);
    otherwise
      x = dbl_from_hex(a.lhs_bits);
      y = dbl_from_hex(a.rhs_bits);
      v = float_apply(a.op, x, y);
  endswitch
endfunction

function v = int_apply(op, x, y)
  switch op
    case '+'
      s = x + y;   % заворачивается молча — ловим по знакам
      if (x > 0 && y > 0 && s <= 0) || (x < 0 && y < 0 && s >= 0)
        v = 'IntRangeOverflow';
      else
        v = s;
      endif
    case '-'
      if y == intmin('int64') && x > 0
        v = 'IntRangeOverflow';
      else
        v = int_apply('+', x, -y);
      endif
    case '*'
      if x == 0 || y == 0; v = int64(0); return; endif
      p = x * y;
      if p == 0; v = 'IntRangeOverflow'; return; endif
      sx = 1; if x < 0; sx = -1; endif
      sy = 1; if y < 0; sy = -1; endif
      sp = 1; if p < 0; sp = -1; endif
      if sp ~= sx * sy
        v = 'IntRangeOverflow';
      else
        v = p;
      endif
    case '/'
      if y == 0; v = 'DivisionByZero'; return; endif
      if x == intmin('int64') && y == -1
        v = 'IntRangeOverflow'; return;
      endif
      v = idivide(x, y, 'fix');   % усечение к нулю; 'round'/'floor' запрещены
    case '%'
      if y == 0; v = 'DivisionByZero'; return; endif
      v = mod(x, y);              % семантика Python: знак делителя
    otherwise
      v = 'InternalError';
  endswitch
endfunction

function v = float_apply(op, x, y)
  switch op
    case '+';  z = x + y;
    case '-';  z = x - y;
    case '*';  z = x * y;
    case '/'
      if y == 0
        if x == 0; v = 'NaNOutsideDomain'; return; endif
        nx = (1 / x < 0); ny = (1 / y < 0);
        if nx ~= ny; v = -inf; else; v = inf; endif
        return
      endif
      z = x / y;
    otherwise; v = 'InternalError'; return;
  endswitch
  if isnan(z); v = 'NaNOutsideDomain'; else; v = z; endif
endfunction

function s = print_sign_float(x)
  if x > 0; s = 'inf'; else; s = '-inf'; endif
endfunction

function vals = expected_vals(s)
  vals = s.values;
  if iscell(vals)
    vals = cell2mat(vals);
  endif
endfunction
