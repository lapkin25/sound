%% run_script.m — автогенерируется кодогенератором
A = load_triomat('graph.triomat');
bc = current_flow_betweenness(A);
save_triomat('result.triomat', bc);
