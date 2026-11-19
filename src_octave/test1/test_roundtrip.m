%% test_roundtrip.m — цикл: TRIOMAT -> Octave -> TRIOMAT
%% КЛЮЧЕВОЙ МОМЕНТ: reshape в Octave column-major, а TRIOMAT — row-major.
%% Поэтому reshape(data, rows, cols) ДАЁТ ТРАНСПОНИРОВАННУЮ матрицу.
%% Правильно: reshape(data, cols, rows)'  (сначала cm, потом транспонировать).

function M = load_triomat(fname)
  fid = fopen(fname, 'rb', 'ieee-le');   % явный little-endian — не полагаемся на нативный порядок
  if fid == -1, error('Err(CannotOpen): %s', fname); end
  header = fread(fid, 4, 'int32');
  rows = header(1); cols = header(2); dtype = header(3); flags = header(4);
  if dtype ~= 0, error('Err(ShapeError): dtype=%d', dtype); end
  data = fread(fid, rows * cols, 'double');
  M = reshape(data, cols, rows)';        % row-major -> матрица rows x cols
  fclose(fid);
endfunction

function save_triomat(fname, M)
  [rows, cols] = size(M);
  fid = fopen(fname, 'wb', 'ieee-le');
  if fid == -1, error('Err(CannotOpen): %s', fname); end
  fwrite(fid, [rows, cols, 0, 0], 'int32');
  fwrite(fid, M', 'double');             % M' в column-major == M в row-major
  fclose(fid);
endfunction

%% Тест: читаем матрицу, удваиваем, пишем обратно
A = load_triomat('test.triomat');
printf('octave: received %dx%d\n', size(A, 1), size(A, 2));
printf('octave: A(1,:) = %g %g %g\n', A(1,1), A(1,2), A(1,3));
B = A * 2;
save_triomat('result.triomat', B);
printf('octave: wrote result %dx%d\n', size(B, 1), size(B, 2));
