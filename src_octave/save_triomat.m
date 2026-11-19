%% save_triomat.m — канонический писатель TRIOMAT1 (Octave -> JS/SCore).
%% fwrite(fid, M', 'double'): M' в column-major == M в row-major.
function save_triomat(fname, M, flags)
  if nargin < 3, flags = struct(); end
  [rows, cols] = size(M);
  hdr = struct('magic', 'TRIOMAT1', 'dtype', 'Float64', ...
               'shape', [rows cols], 'flags', flags);
  raw = jsonencode(hdr);
  fid = fopen(fname, 'wb', 'ieee-le');
  if fid == -1, error('Err(CannotOpen): %s', fname); end
  fwrite(fid, uint32(length(raw)), 'uint32');
  fwrite(fid, uint8(raw), 'uchar');
  fwrite(fid, M', 'double');             % column-major от транспонированной == row-major
  fclose(fid);
endfunction
