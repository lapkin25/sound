FUNC gcd
    LOAD a
    LOAD b
    IFZ_JMP gcd_end
    LOAD b
    LOAD a
    MOD_OP
    CALL gcd
    JMP gcd_exit
gcd_end:
    LOAD a
gcd_exit:
    RETURN
END

FUNC is_coprime
    CALL gcd
    IFZ_JMP coprime_true
    LOAD 0
    JMP coprime_end
coprime_true:
    LOAD 1
coprime_end:
    RETURN
END

FUNC phi_optimized
    LOAD n
    STORE result
    LOAD 2
    STORE i
phi_loop:
    LOAD i
    LOAD i
    MUL_OP
    LOAD n
    IFZ_JMP phi_end
    LOAD n
    LOAD i
    MOD_OP
    IFZ_JMP not_divisible
    LOAD result
    LOAD i
    DIV_OP
    SUB_OP
    STORE result
    LOAD n
    LOAD i
    DIV_OP
    STORE n
    JMP phi_loop
not_divisible:
    LOAD i
    INC
    STORE i
    JMP phi_loop
phi_end:
    LOAD n
    LOAD 1
    IFZ_JMP skip_last
    LOAD result
    LOAD n
    DIV_OP
    SUB_OP
    STORE result
skip_last:
    LOAD result
    RETURN
END
