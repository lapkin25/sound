% demo_projectile.m - прогон узла: расчёт и обмен через TRIOMAT
for deg = [20 30 45 60 75 100]
  f = projectile_facts();
  f.alpha_deg = deg;                         % подмена факта для сценария
  a = f.alpha_deg * (pi / 180);
  s = sin(2 * a);
  [R, log] = projectile_flight_range(s);
  printf('alpha=%3d  s=%s  R=%s\n', deg, canon(s), canon(R));
  if strcmp(log{1}(1:3), 'err')
    printf('  журнал: %s\n', log{1});
  endif
endfor

% запись .tri для alpha=45 - то, что узел отправил бы соседу
f = projectile_facts();
a = f.alpha_deg * (pi / 180);
s = sin(2 * a);
[~, log] = projectile_flight_range(s);
fid = fopen('projectile_sin2a_45.tri', 'wb');
fwrite(fid, tri_pack('Float64', [1], typecast(s, 'uint8')));
fclose(fid);
[R45, ~] = projectile_flight_range(s);
fid = fopen('projectile_range_45.tri', 'wb');
fwrite(fid, tri_pack('Float64', [1], typecast(R45, 'uint8')));
fclose(fid);
printf('журнал flight_range(45):\n');
for i = 1:numel(log)
  printf('  %s\n', log{i});
endfor
