%% current_flow_betweenness.m
function bc = current_flow_betweenness(A)
  n = size(A, 1);
  if size(A, 2) ~= n
    error('Err(ShapeError): graph must be square');
  end

  D = diag(sum(A, 2));
  L = D - A;

  % регуляризация (утечка) для устойчивости
  lambda = 1e-6;
  L_reg = L + lambda * eye(n);

  % проверка на сингулярность (через ранг)
  if rank(L_reg) < n
    error('Err(SingularMatrix)');
  end

  L_pinv = pinv(L_reg);

  bc = zeros(n, 1);
  for i = 1:n
    for j = i+1:n
      for k = 1:n
        if k ~= i && k ~= j
          bc(k) = bc(k) + abs(L_pinv(i,i) + L_pinv(j,j) - L_pinv(i,j) - L_pinv(k,k));
        end
      end
    end
  end
endfunction
