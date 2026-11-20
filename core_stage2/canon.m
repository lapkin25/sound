% canon.m - canonical string of a double, contract 6.4
% Python float.hex equivalence: "0x1.<13 hex>p(+|-)e", denormals
% "0x0.<13 hex>p-1022", signed zero, nan/inf by name.
function c = canon(x)
  x = double(x);
  if isnan(x), c = 'nan'; return; endif
  if isinf(x)
    if x > 0, c = 'inf'; else, c = '-inf'; endif
    return
  endif
  if x == 0
    if signbit(x), c = '-0x0.0p+0'; else, c = '0x0.0p+0'; endif
    return
  endif
  h = num2hex(x);   % 16 hex chars of the IEEE-754 bit pattern
  neg = any(h(1) == '89abcdef');
  expfield = mod(hex2dec(h(1)), 8) * 256 + hex2dec(h(2:3));
  frac = h(4:16);   % 13 hex digits = 52 mantissa bits
  if expfield > 0
    c = sprintf('0x1.%sp%+d', frac, expfield - 1023);
  else
    c = sprintf('0x0.%sp-1022', frac);
  endif
  if neg, c = ['-' c]; endif
endfunction

