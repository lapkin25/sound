FUNC sub
LOAD a
LOAD b
-_OP
RETURN
END
FUNC succ
LOAD n
LOAD 1
CALL add
RETURN
END
FUNC ack
LOAD m
IFZ_JMP ifz_true_1
LOAD n
IFZ_JMP ifz_true_0
LOAD m
LOAD 1
CALL sub
LOAD m
LOAD n
LOAD 1
CALL sub
CALL ack
CALL ack
JMP ifz_end_0
ifz_true_0:
LOAD m
LOAD 1
CALL sub
LOAD 1
CALL ack
ifz_end_0:

JMP ifz_end_1
ifz_true_1:
LOAD n
CALL succ
ifz_end_1:

RETURN
END
FUNC add
LOAD a
LOAD b
+_OP
RETURN
END
MAIN
PUSH 2
PUSH 3
CALL ack
EXIT