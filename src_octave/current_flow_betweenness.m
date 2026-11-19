%% current_flow_betweenness.m — узел Octave-рантайма (пример из спеки v0.1).
function bc = current_flow_betweenness(A)
  n = size(A, 1);
  D = diag(sum(A, 2));
  L = D - A;

  % регуляризация (утечка) для устойчивости
  lambda = 1e-6;
  L_reg = L + lambda * eye(n);

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
