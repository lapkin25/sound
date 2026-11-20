% demo_projectile.m - node run: calculation + TRIOMAT exchange
% save as UTF-8 without BOM

for deg = [20 30 45 60 75 100]
  f = projectile_facts();
  f.alpha_deg = deg;                         % fact override for the scenario
  a = f.alpha_deg * (pi / 180);
  s = sin(2 * a);
  [R, log] = projectile_flight_range(s);
  if isempty(R)
    printf('alpha=%3d  s=%s  R=%s\n', deg, canon(s), log{1});
    continue;
  endif
  printf('alpha=%3d  s=%s  R=%s\n', deg, canon(s), canon(R));
endfor

% write .tri files for alpha=45 - what the node would send to a neighbour
f = projectile_facts();
a = f.alpha_deg * (pi / 180);
s = sin(2 * a);
[R45, log] = projectile_flight_range(s);

fid = fopen('projectile_sin2a_45.tri', 'wb');
fwrite(fid, tri_pack('Float64', [1], typecast(s, 'uint8')));
fclose(fid);

fid = fopen('projectile_range_45.tri', 'wb');
fwrite(fid, tri_pack('Float64', [1], typecast(R45, 'uint8')));
fclose(fid);

fid = fopen('projectile_journal.txt', 'w');
for i = 1:numel(log)
  fprintf(fid, '%s\n', log{i});
endfor
fclose(fid);

printf('journal of flight_range(45):\n');
for i = 1:numel(log)
  printf('  %s\n', log{i});
endfor
