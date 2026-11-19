%% trio_bridge.m — Octave-сторона Trio Type Bridge Spec v0.1
%% Реализует чтение/запись формата TRIOMAT (байт-в-байт с trio_bridge.py и TrioBridge.java)
%%
%% Формат файла:
%%   байты 0..7  : magic "TRIOMAT\x01"
%%   байт 8      : version = 1
%%   байт 9      : layout: 0 = row-major, 1 = column-major
%%   байт 10     : dtype: 0=Float64, 1=Float32, 2=Int64, 3=Bool
%%   байт 11     : ndim
%%   далее       : ndim * 8 байт (u64, big-endian) — размеры
%%   далее       : payload в объявленном dtype, little-endian
%%
%% Функции:
%%   trio_bridge_save(path, A, dtype, layout)
%%   trio_bridge_load(path, target_dtype, domain)
%%

function trio_bridge_save(path, A, dtype_str, layout_str)
  % A — матрица (допускаются double, single, int64, logical)
  % dtype_str — "Float64", "Float32", "Int64", "Bool"
  % layout_str — "row" или "col"

  magic = uint8([84,82,73,79,77,65,84,1]);  % "TRIOMAT"+0x01
  version = uint8(1);

  layout_code = (strcmp(layout_str, "row") ? 0 : 1);
  dtype_map = containers.Map({"Float64","Float32","Int64","Bool"}, [0,1,2,3]);
  if ~isKey(dtype_map, dtype_str)
    error("trio_bridge: unknown dtype '%s'", dtype_str);
  end
  dtype_code = dtype_map(dtype_str);

  ndim = ndims(A);
  dims = size(A);

  % Заголовок: magic (8) + version (1) + layout (1) + dtype (1) + ndim (1) = 12 байт
  header = [magic, version, uint8(layout_code), uint8(dtype_code), uint8(ndim)];

  % Размеры: ndim * 8 байт, u64, big-endian
  dims_be = zeros(1, ndim*8, "uint8");
  for i = 1:ndim
    v = dims(i);
    % записать u64 в big-endian
    dims_be((i-1)*8+1 : i*8) = typecast(uint64(v), "uint8")(end:-1:1);
  end

  % Payload: little-endian, в объявленном dtype
  switch dtype_str
    case "Float64"
      if ~isa(A, "double") && ~isa(A, "single")
        error("trio_bridge: Float64 требует double/single");
      end
      B = double(A);  % гарантируем double
    case "Float32"
      if ~isa(A, "single") && ~isa(A, "double")
        error("trio_bridge: Float32 требует single/double");
      end
      B = single(A);
    case "Int64"
      if ~isa(A, "int64") && ~isa(A, "double")
        error("trio_bridge: Int64 требует int64/double");
      end
      % Важно: пишем именно int64-байты, конверсия к double — на границе, не на диске
      if isa(A, "double")
        % проверка диапазона 2^53
        if any(abs(A(:)) > 9007199254740992)
          error("trio_bridge: Int64 out of range (>2^53)");
        end
        B = int64(A);
      else
        B = A;
      end
    case "Bool"
      if ~isa(A, "logical") && ~isa(A, "double")
        error("trio_bridge: Bool требует logical/double");
      end
      if isa(A, "double")
        if any((A(:) ~= 0) & (A(:) ~= 1))
          error("trio_bridge: Bool: значения должны быть 0/1");
        end
        B = logical(A);
      else
        B = A;
      end
  end

  % Layout: Octave — column-major. Если layout="row", делаем permute
  if layout_code == 0  % row-major
    if ndim == 2
      B = permute(B, [2,1]);
    else
      error("trio_bridge: row-major layout поддерживается только для 2D");
    end
  end

  % Байты payload: little-endian. typecast даёт native-порядок; на x86 это LE.
  payload = typecast(B(:), "uint8");  % column-major flatten

  fid = fopen(path, "wb");
  if fid < 0
    error("trio_bridge: cannot open file '%s' for writing", path);
  end
  fwrite(fid, header, "uint8");
  fwrite(fid, dims_be, "uint8");
  fwrite(fid, payload, "uint8");
  fclose(fid);
endfunction


function [A, info] = trio_bridge_load(path, target_dtype_str, domain_str)
  % Возвращает:
  %   A — матрица в целевом dtype (double/single/int64/logical)
  %   info — struct с метаданными (layout, original dtype, trusted)
  %
  % domain_str: "strict" (NaN/Inf запрещены) или "nan" (разрешены)

  if nargin < 3
    domain_str = "strict";
  end

  fid = fopen(path, "rb");
  if fid < 0
    error("trio_bridge: cannot open file '%s' for reading", path);
  end

  % Читаем заголовок
  magic_raw = fread(fid, 8, "uint8");
  version_raw = fread(fid, 1, "uint8");
  layout_raw = fread(fid, 1, "uint8");
  dtype_raw = fread(fid, 1, "uint8");
  ndim_raw = fread(fid, 1, "uint8");

  expected_magic = uint8([84,82,73,79,77,65,84,1]);
  if any(magic_raw ~= expected_magic)
    fclose(fid);
    error("trio_bridge: not a TRIOMAT file (bad magic)");
  end
  if version_raw ~= 1
    fclose(fid);
    error("trio_bridge: unsupported TRIOMAT version %d", version_raw);
  end

  layout = layout_raw(1);  % 0=row, 1=col
  dtype_code = dtype_raw(1);
  ndim = ndim_raw(1);

  dtype_names = {"Float64","Float32","Int64","Bool"};
  dtype_codes = [0,1,2,3];
  if sum(dtype_code == dtype_codes) == 0
    fclose(fid);
    error("trio_bridge: unknown dtype code %d", dtype_code);
  end
  orig_dtype = dtype_names{find(dtype_codes == dtype_code, 1)};

  % Читаем размеры (u64, big-endian)
  dims_raw = fread(fid, ndim*8, "uint8");
  dims = zeros(1, ndim, "uint64");
  for i = 1:ndim
    idx = (i-1)*8;
    % читаем u64 из big-endian
    u = typecast(dims_raw(idx+1:idx+8), "uint64")(1);
    dims(i) = swapbytes(u);  % конвертируем BE->LE для Octave
  end

  total_elems = prod(dims);
  switch orig_dtype
    case "Float64"
      bytes_per_elem = 8;
      read_dtype = "double";
    case "Float32"
      bytes_per_elem = 4;
      read_dtype = "single";
    case "Int64"
      bytes_per_elem = 8;
      read_dtype = "int64";
    case "Bool"
      bytes_per_elem = 1;
      read_dtype = "logical";
  end

  payload_size = total_elems * bytes_per_elem;
  file_size = ftell(fid);  % текущая позиция после заголовка+размеров
  remaining = feof(fid) ? 0 : fseek(fid, 0, "eof");  % не очень надёжно: лучше fstat
  % Вместо fstat (нет в Octave), читаем до конца
  fseek(fid, file_size, "bof");
  payload_raw = fread(fid, payload_size, "uint8");
  actual_size = numel(payload_raw);

  if actual_size ~= payload_size
    fclose(fid);
    error("trio_bridge: payload size mismatch: %d != %d", actual_size, payload_size);
  end

  % Восстанавливаем массив в column-major (Octave)
  B = typecast(payload_raw, read_dtype);
  B = reshape(B, dims);  % column-major по умолчанию

  % Если файл был row-major, делаем permute обратно
  if layout == 0  % row-major в файле
    if ndim == 2
      B = permute(B, [2,1]);
    else
      fclose(fid);
      error("trio_bridge: row-major layout поддерживается только для 2D");
    end
  end

  fclose(fid);

  % Конвертация к целевому dtype и проверка домена
  info = struct();
  info.layout = (layout == 0 ? "row" : "col");
  info.original_dtype = orig_dtype;
  info.trusted = true;

  switch target_dtype_str
    case "Float64"
      if strcmp(orig_dtype, "Float64")
        A = double(B);
      elseif strcmp(orig_dtype, "Float32")
        A = double(single(B));  % расширение — OK
      elseif strcmp(orig_dtype, "Int64")
        % R-INT2: проверка диапазона в исходном домене
        if any(abs(B(:)) > 9007199254740992)
          info.trusted = false;
          error("trio_bridge: Int64->Float64: overflow beyond 2^53");
        end
        A = double(B);  % Lossy(repr) на границе
      elseif strcmp(orig_dtype, "Bool")
        A = double(B);
      else
        error("trio_bridge: unhandled dtype conversion");
      end

    case "Float32"
      A = single(double(B));  % сужение — Lossy(precision)

    case "Int64"
      % Сначала к double, чтобы проверить дробность
      tmp = double(B);
      if any(tmp(:) ~= floor(tmp(:)))
        info.trusted = false;
        error("trio_bridge: fractional values cannot be converted to Int64");
      end
      if any(abs(tmp(:)) > 9007199254740992)
        info.trusted = false;
        error("trio_bridge: values out of Int64 range (>2^53)");
      end
      A = int64(tmp);

    case "Bool"
      tmp = double(B);
      if any((tmp(:) ~= 0) & (tmp(:) ~= 1))
        info.trusted = false;
        error("trio_bridge: Bool requires 0/1 values");
      end
      A = logical(tmp);

    otherwise
      error("trio_bridge: unknown target dtype '%s'", target_dtype_str);
  end

  % Проверка NaN/Inf вне домена
  if strcmp(domain_str, "strict")
    if any(isnan(A(:)))
      info.trusted = false;
      error("trio_bridge: NaN detected outside 'nan' domain");
    end
    if any(~isfinite(A(:)))
      info.trusted = false;
      error("trio_bridge: Inf detected outside 'nan' domain");
    end
  end
endfunction
