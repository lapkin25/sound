FUNC sum_array
    LOAD arr
    STORE arr_ref
    LOAD n
    STORE n_val
    LOAD 0
    STORE sum
    LOAD 0
    STORE i
sum_loop:
    LOAD i
    LOAD n_val
    IFZ_JMP sum_end
    LOAD arr_ref
    LOAD
