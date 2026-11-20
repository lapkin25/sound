% projectile.m - реализация узла "projectile" (host: octave)
% Спека: spec projectile ;
%        fact v0 25.0 ; fact g 9.81 ; fact alpha_deg 45.0 ;
%        pure rule flight_range s = (v0 * v0) * s / g invariant s >= 0 ;

function f = projectile_facts()
  f.v0 = 25.0;
  f.g = 9.81;
  f.alpha_deg = 45.0;
endfunction

function s = projectile_sin2a()
  % Трансцендентная часть - обязанность хоста (§9: в ядре v0.2 нет trig).
  % Дерево конверсии зафиксировано по §2.6 (правоассоц.): pi/180 первым.
  f = projectile_facts();
  a = f.alpha_deg * (pi / 180);
  s = sin(2 * a);
endfunction

function [val, log] = projectile_flight_range(s)
  % pure rule flight_range s = (v0 * v0) * s / g invariant s >= 0
  % Дерево тела: t0=(v0*v0), t1=(s/g), t2=t0*t1 - зеркалим спеку, §8.2 п.7
  f = projectile_facts();
  log = {};
  if ~(s >= 0)
    log{end+1} = 'err DomainError flight_range: invariant';
    val = [];
    return
  endif
  t0 = f.v0 * f.v0;
  t1 = s / f.g;
  t2 = t0 * t1;
  log{end+1} = ['bind s  = Float64 ' canon(s)];
  log{end+1} = ['bind t0 = Float64 ' canon(t0)];
  log{end+1} = ['bind t1 = Float64 ' canon(t1)];
  log{end+1} = ['bind t2 = Float64 ' canon(t2)];
  log{end+1} = ['result  = Float64 ' canon(t2)];
  val = t2;
endfunction

function s = canon(x)
  % канонический float, §6.4; с веткой денормалов
  if (isnan(x)); s = 'nan'; return; endif
  if (isinf(x));
    if (x > 0); s = 'inf'; else; s = '-inf'; endif
    return
  endif
  if (x == 0);
    if (1 / x < 0); s = '-0x0.0p+0'; else; s = '0x0.0p+0'; endif
    return
  endif
  h = tolower(num2hex(x));                 % 16 hex digits, big-endian
  v = hex2dec(h(1:3));                     % знак + 11 бит экспоненты
  e = mod(v, 2048) - 1023;
  mant = h(4:16);                          % 13 hex digits мантиссы
  if (e == -1023)
    body = ['0x0.' mant 'p-1022'];         % денормал: ведущей единицы нет
  else
    es = num2str(e);
    if (e >= 0); es = ['+' es]; endif
    body = ['0x1.' mant 'p' es];
  endif
  if (v >= 2048); s = ['-' body]; else; s = body; endif
endfunction

function b = tri_pack(dt, shape, payload)
  % TRIOMAT1, вариант Б: payload в C-порядке логических значений
  parts = cell(1, numel(shape));
  for k = 1:numel(shape)
    parts{k} = num2str(shape(k));
  endfor
  h = sprintf('{"dtype":"%s","shape":[%s]}', dt, strjoin(parts, ','));
  b = [uint8('TRIOMAT1'), ...
       reshape(typecast(uint32(numel(h)), 'uint8'), 1, []), ...
       uint8(h), reshape(payload, 1, [])];
endfunction
