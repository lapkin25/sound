%% test_roundtrip.m — канонический цикл TRIOMAT1: чтение -> A*2 -> запись.
%% Неквадратная матрица 2x3 нарочно: она вылавливает класс бага
%% «column-major против row-major», невидимый на симметричных квадратных.
addpath(dirname(mfilename('fullpath')));   % чтобы найти load/save_triomat
A = load_triomat('test.triomat');
printf('octave: received %dx%d\n', size(A, 1), size(A, 2));
printf('octave: A(1,:) = %g %g %g\n', A(1,1), A(1,2), A(1,3));
B = A * 2;
save_triomat('result.triomat', B);
printf('octave: wrote result %dx%d\n', size(B, 1), size(B, 2));
