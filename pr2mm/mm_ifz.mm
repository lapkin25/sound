FUNC check
LOAD x
IFZ_JMP ifz_true_0
LOAD 1
JMP ifz_end_0
ifz_true_0:
LOAD 0
ifz_end_0:

RETURN
END
MAIN
PUSH 5
CALL check
EXIT