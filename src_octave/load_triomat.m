%% load_triomat.m — канонический читатель TRIOMAT1 (спека моста, раздел 8).
%% Требуется Octave >= 7 (jsondecode).
%% КЛЮЧЕВОЙ МОМЕНТ: reshape в Octave column-major, а TRIOMAT payload — row-major.
%% Правильно: reshape(data, cols, rows)'  (сначала column-major, потом транспонировать).
%% Ошибка reshape(data, rows, cols) даёт ТРАНСПОНИРОВАННУЮ матрицу — и для
%% квадратных симметричных (граф смежности!) проходит незамеченной.
function M = load_triomat(fname)
  fid = fopen(fname, 'rb', 'ieee-le');   % явный little-endian
  if fid == -1, error('Err(CannotOpen): %s', fname); end
  hlen = fread(fid, 1, 'uint32');
  raw = fread(fid, hlen, 'uchar')';
  hdr = jsondecode(char(raw));
  if ~strcmp(hdr.magic, 'TRIOMAT1'), error('Err(MalformedHeader): magic'); end
  if ~strcmp(hdr.dtype, 'Float64'), error('Err(TypeError): dtype=%s', hdr.dtype); end
  shape = hdr.shape(:)';
  rows = shape(1); cols = shape(2);
  data = fread(fid, rows * cols, 'double');
  M = reshape(data, cols, rows)';        % row-major -> матрица rows x cols
  fclose(fid);
endfunction
