# Golden Corpus: pattern battery for spec Demo
# sound-0.3 | host runtime: python | created: 2026-11-22
# Fingerprint: fp0 = 64 zeros; fp_i = sha256(fp_{i-1} + canonical_line).
# Canonical line = journal line WITHOUT the comment.
# Int64 canon: two's complement, 16 hex. Float64 canon: fmt_hex_double.

=== TRACE DemoNeg ===
spec:        DemoNeg
version:     sound-0.3
runtime:     python
created:     2026-11-22T15:29:07+10:00
seed:        none

--- journal ---
t0 const fffffffffffffff9 -> fffffffffffffff9                   ; fact a = -7
        fp: 96c31345291194440ffc917170816baff3f6de4dcf692a416d4c858065a8b2d2
t1 const 0000000000000002 -> 0000000000000002                   ; fact b = 2
        fp: 1dd77f02a6cc78992f8a7f245ec85221263e125416aabf287fd67bdcec73c589
t2 ref a -> fffffffffffffff9                                    ; read a
        fp: 9499ee354f654e3fc1168e3a6c2b66e68effa44e48a79c290b0eaf477bf4280e
t3 ref b -> 0000000000000002                                    ; read b
        fp: 5bebf65f87996fb2f850531da2eef10177dcbc43b07ff4d7d319315ed24eed13
t4 quotient t2 t3 -> fffffffffffffffd                           ; trunc(-7/2) = -3, not floor = -4
        fp: 1ffb496bdb048c2426fa93eb6f63bdd978ac3825ccf00c89c58db82dbd19db36
t5 mod t2 t3 -> ffffffffffffffff                                ; -7 - trunc(-7/2)*2 = -1 (sign of dividend)
        fp: 77bddf79016d12e7a653c2dedd2694b14c2afc0fddc702b9a60996b08f91a59f
t6 const 0000000000000007 -> 0000000000000007                   ; fact c = 7
        fp: 4ad0c842923d1af4f8c1de566a41e4df127a0b39a6fc0ae52ae0d360f75df8e4
t7 quotient t6 t3 -> 0000000000000003                           ; trunc(7/2) = 3
        fp: 1bc040fe14fa0dd32dd9dd9cc4986a589336e0a411116b1edc15c60e113fa3bc
t8 mod t6 t3 -> 0000000000000001                                ; 7 - 3*2 = 1
        fp: ca6397a63d0c9ed7ba54df86d77df426dec614caaafaf964a6f374c03a02aeac
t9 const fffffffffffffffe -> fffffffffffffffe                   ; fact d = -2
        fp: 82327731fe53b892201162a315589800fc680c41b6b6b828583b50601425dc1a
t10 quotient t2 t10 -> 0000000000000003                         ; trunc(-7/-2) = trunc(3.5) = 3
        fp: 2e7a51d624066f48a7e8eb00c1f5aa23297cb1f32d37cae97a6b4492f6ae83a8
t11 mod t2 t10 -> ffffffffffffffff                              ; -7 - 3*(-2) = -1
        fp: 232ac891c77017a22b046a5a297d4886b78b4f16509758253ece76797372a4f4

--- fingerprint ---
232ac891c77017a22b046a5a297d4886b78b4f16509758253ece76797372a4f4
=== END TRACE ===

=== TRACE DemoWrap ===
spec:        DemoWrap
version:     sound-0.3
runtime:     python
created:     2026-11-22T15:29:07+10:00
seed:        none

--- journal ---
t0 const 7fffffffffffffff -> 7fffffffffffffff                   ; fact m = Int64 max
        fp: 58c4052c03d92ebbc75fea30f85110825e793c7bb11c569b1f0e24d5a5952284
t1 const 0000000000000001 -> 0000000000000001                   ; one
        fp: 0e2c2b283275a828205ba074bf903fadc7350fdd4481ba54e69a366bd90c8e54
t2 plus t0 t1 -> 8000000000000000                               ; wrap: 2^63-1 + 1 -> -2^63
        fp: 0f00465d3ec101b1dd776681ba6479b310015ecc3c2e22962a03ff80f05ef134
t3 const 0000000000000002 -> 0000000000000002                   ; two
        fp: 32657de1f13b25a3cdda1a756f3bcf1c87b72624aa23d8b55316f4bb14429e52
t4 mul t0 t3 -> fffffffffffffffe                                ; wrap: 2*max mod 2^64 = -2
        fp: 58dfaf74e027bb58be55224a2e74e2a7e785d8a67787d1f17f21ba1566d863e3
t5 neg t2 -> 8000000000000000                                   ; neg(-2^63) wraps to itself
        fp: 3323a32bdc8e74cad305764f8d757220febf592a2a39993723dc3e884a5c1a2c

--- fingerprint ---
3323a32bdc8e74cad305764f8d757220febf592a2a39993723dc3e884a5c1a2c
=== END TRACE ===

=== TRACE DemoDenorm ===
spec:        DemoDenorm
version:     sound-0.3
runtime:     python
created:     2026-11-22T15:29:07+10:00
seed:        none

--- journal ---
t0 const 0000000000000001 -> 0000000000000001                   ; fact d = 5e-324 (min subnormal, 1 ulp)
        fp: e00450648e7e89954ac2dbc70ce55b1c3b9dde076e13e27454dd5011b9a44439
t1 const 3fe0000000000000 -> 3fe0000000000000                   ; half
        fp: 59b31e6952094acdeb025f11e9b7e94a2c537dd05d773c3ce7efb909c4922136
t2 ref d -> 0000000000000001                                    ; read d
        fp: 6c5dde599697aeadcd1433ee80a5a3e7826c54c740452c18176be18752ca8510
t3 mul t2 t1 -> 0000000000000000                                ; 0.5 ulp: ties-to-even rounds to +0
        fp: 865be5b5d1ec485feb8de4a141eb3b414b342450b24f6fdea2683c37d9bd7a16
t4 plus t2 t2 -> 0000000000000002                               ; exact sum: 2 ulp = 1e-323
        fp: 762dd026cd2987f5ddcfc0729db247c889366d6d4d06e6c90ead036b6996ba5a
t5 const 4000000000000000 -> 4000000000000000                   ; two
        fp: ddd40c61619d893805cb6954af0984cbe328ae351aede78c0b36f03a3804dc46
t6 div t4 t5 -> 0000000000000001                                ; 2 ulp / 2 = 1 ulp, exact
        fp: 68074766077b3fabffc4a013813c521feda64760b2eb061a2dad640818f8168c

--- fingerprint ---
68074766077b3fabffc4a013813c521feda64760b2eb061a2dad640818f8168c
=== END TRACE ===

=== TRACE DemoNaN ===
spec:        DemoNaN
version:     sound-0.3
runtime:     python
created:     2026-11-22T15:29:07+10:00
seed:        none

--- journal ---
t0 const 7ff8000000000001 -> 7ff8000000000001                   ; fact n = NaN with payload 1
        fp: adab9b7f5ffe42302e2d1ee3561fd2301e47f4a28a921ff88b577444529e5b8d
t1 eq t0 t0 -> false                                            ; IEEE: NaN != NaN, even with itself
        fp: e4878d5ca0e6aefdc50bebcb873c7958bd44f73505ffc32a2ac882399f39272d
t2 neq t0 t0 -> true                                            ; negated comparison
        fp: 666b2bf77f8dd02ba8e09228e50de25a7b496a79652fb409fb81f7272c6d95f6
t3 neg t0 -> fff8000000000001                                   ; contract: sign flips, payload preserved
        fp: 34a85a912a2ed514aef1e0d41ac7d85c96c0918fc8b9d1012d4562abc53fca1d
t4 const 7ff8000000000000 -> 7ff8000000000000                   ; canonical NaN, no payload
        fp: dcd7e95cc48e07d5a7230ebde1e1823410f756d5afbbc73e5c5f4b0290f3d8f5
t5 eq t0 t4 -> false                                            ; distinct NaNs unequal
        fp: 44e407302dd147e4f6ea6525d0f703871ef9f679995d6cd3e215f8e12b25872d

--- fingerprint ---
44e407302dd147e4f6ea6525d0f703871ef9f679995d6cd3e215f8e12b25872d
=== END TRACE ===

=== TRACE DemoDiv0 ===
spec:        DemoDiv0
version:     sound-0.3
runtime:     python
created:     2026-11-22T15:29:07+10:00
seed:        none

--- journal ---
t0 const 3ff0000000000000 -> 3ff0000000000000                   ; fact a = 1.0
        fp: 0d961951d17880d845a39210cd6e564f53b4e754247f5b25b42139338911fb47
t1 const 0000000000000000 -> 0000000000000000                   ; fact b = 0.0
        fp: e26ed8a7373751f66217ec6b247e0c13ccf913200f41d93ab16d5bb65e486252
t2 ref a -> 3ff0000000000000                                    ; read a
        fp: 7902598b22df35d00c657c5d5e0b7deb4a32681dbf4e6334650acda715a5d5b8
t3 ref b -> 0000000000000000                                    ; read b
        fp: ed43d5718cef993dbd2b1da5018e3ff35bcf6385a70b154dfec829bdd689250d
t4 eq t3 t1 -> true                                             ; b == 0.0
        fp: 7b600f16bd2fc5eb22b8264ab31ee91ffd2c628205b23eb00d0b17193eba668f
t5 if t4 then t5 else t6 -> branch_t                            ; condition true -> error branch
        fp: 4068eac3d98158387fdd9a324fa278139ef3cb9334f8866d44743a35b55c068c
t6 err div0 3ff0000000000000 -> err:div0:3ff0000000000000       ; error value, payload = offending operand
        fp: 0e3013135fa0a41139bcccc95df6c0cd4b208b02694389effc250763cda60070
t7 plus t5 t1 -> err:div0:3ff0000000000000                      ; Railway: error flows through, unchanged
        fp: 91adb82c8a7a3c1c8bc43bc26932b92ee96c1059cf22d492b42991d85490e6e2
t8 set r t6 -> err:div0:3ff0000000000000                        ; source of truth accepted
        fp: 33f2d2ec2d352bf7dec8b59fc7415cd00ffea2871778e2eb41811950fef5ca87

--- fingerprint ---
33f2d2ec2d352bf7dec8b59fc7415cd00ffea2871778e2eb41811950fef5ca87
=== END TRACE ===

=== TRACE DemoFold ===
spec:        DemoFold
version:     sound-0.3
runtime:     python
created:     2026-11-22T15:29:07+10:00
seed:        none

--- journal ---
t0 const 3|4000000000000000,4008000000000000,4010000000000000 -> 3|4000000000000000,4008000000000000,4010000000000000; list [2.0, 3.0, 4.0] in canonical form
        fp: 4f66df00d1b5fd81d45c8dfed43696123f03955fcd0910cb3eb46d0dd0794999
t1 const 0000000000000000 -> 0000000000000000                   ; fact acc = 0.0
        fp: 78b7754534830d8a5a8971d9afcff165dceac240898b1a640fcda628dd04f607
t2 fold plus t1 t0 -> 4022000000000000                          ; left-to-right: ((0+2)+3)+4 = 9.0
        fp: 1bba8ea3e652e9d5df20584699ddca4869880e26a14a6cce74153c5571051d2a
t3 foldlist plus t1 t0 -> 3|4000000000000000,4014000000000000,4022000000000000; partial sums [2.0, 5.0, 9.0]
        fp: b6906a4ede6af1287851efb26b0ff1de6b83844abbb04db21106e8964e4d92ba

--- fingerprint ---
b6906a4ede6af1287851efb26b0ff1de6b83844abbb04db21106e8964e4d92ba
=== END TRACE ===
