FUNC sieve
    LOAD n
    CREATE_ARRAY n
    STORE sieve
    CREATE_ARRAY 0
    STORE primes
    LOAD 2
    STORE i
sieve_loop:
    LOAD i
    LOAD n
    IFZ_JMP sieve_end
    LOAD sieve
    LOAD i
    IFZ_JMP skip_prime
    LOAD primes
    LOAD i
    CALL append
    STORE primes
    LOAD i
    MUL_OP
    STORE j
inner_loop:
    LOAD j
    LOAD n
    IFZ_JMP inner_end
    LOAD sieve
    LOAD j
    STORE false
    LOAD j
    LOAD i
    ADD_OP
    STORE j
    JMP inner_loop
inner_end:
    LOAD i
    INC
    STORE i
    JMP sieve_loop
skip_prime:
    LOAD i
    INC
    STORE i
    JMP sieve_loop
sieve_end:
    LOAD primes
    RETURN
END
