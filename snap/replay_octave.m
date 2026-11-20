%% replay_octave.m
%% Кросс-хост-реплей: сессия, рождённая в Python (sound_snap2.py),
%% продолжается в Octave и сверяется со снапшотом B — журнал посимвольно,
%% результат по 16 hex-цифрам. Тело step закодировано явно: (x + 2.0/x)/2.0.
%%
%% Запуск: octave --eval replay_octave   (рядом snap_A.json и snap_B.json)

function replay_octave()
  A = jsondecode(fileread("snap_A.json"));
  B = jsondecode(fileread("snap_B.json"));

  ja = journal_lines(A.journal);
  jb = journal_lines(B.journal);
  n0 = numel(ja);

  x = bits2double(A.names.x);

  jrn = ja;
  v = x;
  for k = 1:15
    q = 2.0 / v;
    n0 = n0 + 1;
    jrn{end+1} = sprintf("t%d /(%s,%s) -> %s", n0, num2hex(2.0), num2hex(v), num2hex(q));
    sm = v + q;
    n0 = n0 + 1;
    jrn{end+1} = sprintf("t%d +(%s,%s) -> %s", n0, num2hex(v), num2hex(q), num2hex(sm));
    r = sm / 2.0;
    n0 = n0 + 1;
    jrn{end+1} = sprintf("t%d /(%s,%s) -> %s", n0, num2hex(sm), num2hex(2.0), num2hex(r));
    v = r;
  end

  ok_journal = (numel(jrn) == numel(jb)) && all(strcmp(jrn, jb));
  ok_last = strcmp(num2hex(v), B.last);

  if ok_journal && ok_last
    printf("ALL PASS: сессия Python продолжена в Octave\n");
  else
    printf("FAIL: журнал %s, last %s\n", ok_journal, ok_last);
    if ~ok_journal
      for k = 1:min(numel(jrn), numel(jb))
        if ~strcmp(jrn{k}, jb{k})
          printf("первое расхождение на строке %d:\n  want: %s\n  got : %s\n", k, jb{k}, jrn{k});
          break
        end
      end
    end
  end
end

%% jsondecode отдаёт массив строк то cell-массивом, то char-матрицей — нормализуем
function lines = journal_lines(j)
  if iscell(j)
    lines = j(:);
  elseif ischar(j)
    lines = cellstr(j);
  else
    error("неожиданный тип журнала");
  end
end

%% 16 hex-цифр (big-endian) -> double: через little-endian typecast, как в этапе 2
function d = bits2double(s)
  t = strrep(s, "0x", "");
  if length(t) ~= 16
    error("hex_bits: нужно 16 hex-цифр, получено: %s", s);
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
