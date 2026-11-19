%% admm_step.m
function x_proj = admm_step(z, u, rho, A, b)
  [m, n] = size(A);
  if length(z) ~= n || length(u) ~= n || length(b) ~= m
    error('Err(ShapeError): inconsistent shapes');
  end

  % нормальные уравнения: (A'A + rho*I) x = A'b + rho*(z + u)
  AtA = A' * A;
  rhs = A' * b + rho * (z + u);

  M = AtA + rho * eye(n);
  if rank(M) < n
    error('Err(SingularMatrix)');
  end

  x_proj = M \ rhs;
endfunction
