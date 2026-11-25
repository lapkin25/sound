FUNC sub
PARAMS x,y
LOAD x
LOAD y
SUB_OP
RETURN
END
FUNC ack
PARAMS m,n
LOAD m
IFZ_JMP ifz_then_0
LOAD n
IFZ_JMP ifz_then_2
LOAD m
LOAD 1
CALL sub
LOAD m
LOAD n
LOAD 1
CALL sub
CALL ack
CALL ack
JMP ifz_end_3
ifz_then_2:
LOAD m
LOAD 1
CALL sub
LOAD 1
CALL ack
ifz_end_3:
JMP ifz_end_1
ifz_then_0:
LOAD n
INC
ifz_end_1:
RETURN
END
MAIN
PUSH 2
PUSH 3
CALL ack
EXIT
