%% laplace_solve.m
function x = laplace_solve(L, b, lambda)
  n = size(L, 1);
  if size(L, 2) ~= n || length(b) ~= n
    error('Err(ShapeError): inconsistent shapes');
  end

  M = L + lambda * eye(n);
  if rank(M) < n
    error('Err(SingularMatrix)');
  end

  x = M \ b;
endfunction
