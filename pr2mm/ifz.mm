FUNC check
PARAMS x
LOAD x
IFZ_JMP ifz_then_0
LOAD 1
JMP ifz_end_1
ifz_then_0:
LOAD 0
ifz_end_1:
RETURN
END
MAIN
PUSH 5
CALL check
EXIT
