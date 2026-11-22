# Golden Corpus: Demo — шесть трейсов (каноническая версия)

Все отпечатки вычислены реально: цепочка SHA-256 поверх строк журнала,
начальный вектор — 64 нуля. Hex-канон — нижний регистр, 16 символов на значение.
Сверка — строками (strcmp), не числами.

=== GOLDEN TRACE: DemoNeg ===
runtime: reference (host)
--- environment ---
a = fffffffffffffff9
b = 0000000000000002
--- journal ---
t0 const fffffffffffffff9 -> fffffffffffffff9
    fp: 96c31345291194440ffc917170816baff3f6de4dcf692a416d4c858065a8b2d2
t1 const 0000000000000002 -> 0000000000000002
    fp: 1dd77f02a6cc78992f8a7f245ec85221263e125416aabf287fd67bdcec73c589
t2 ref a -> fffffffffffffff9
    fp: 9499ee354f654e3fc1168e3a6c2b66e68effa44e48a79c290b0eaf477bf4280e
t3 ref b -> 0000000000000002
    fp: 5bebf65f87996fb2f850531da2eef10177dcbc43b07ff4d7d319315ed24eed13
t4 quotient t2 t3 -> fffffffffffffffd
    fp: 1ffb496bdb048c2426fa93eb6f63bdd978ac3825ccf00c89c58db82dbd19db36
t5 mod t2 t3 -> ffffffffffffffff
    fp: 77bddf79016d12e7a653c2dedd2694b14c2afc0fddc702b9a60996b08f91a59f
t6 set r t5 -> ffffffffffffffff
    fp: b49dd640b4b790713296aecfa2830670996b0b91e2fed357402949845b252fc1
--- fingerprint ---
b49dd640b4b790713296aecfa2830670996b0b91e2fed357402949845b252fc1
--- что проверяет ---
Проверяет усечённое деление и mod на отрицательных: остаток наследует знак делимого. Бьёт по floor-ориентированным mod Octave/WL, не по C99 (там деление уже усекающее).

=== GOLDEN TRACE: DemoWrap ===
runtime: reference (host)
--- environment ---
max = 7fffffffffffffff
one = 0000000000000001
--- journal ---
t0 const 7fffffffffffffff -> 7fffffffffffffff
    fp: 58c4052c03d92ebbc75fea30f85110825e793c7bb11c569b1f0e24d5a5952284
t1 const 0000000000000001 -> 0000000000000001
    fp: 0e2c2b283275a828205ba074bf903fadc7350fdd4481ba54e69a366bd90c8e54
t2 ref max -> 7fffffffffffffff
    fp: fe8cde33a2f3131366b854268d2f54b2a24c8842fdacffeabea764b02f33c5fb
t3 ref one -> 0000000000000001
    fp: 092c5ccdadfe2a0a10a2cad28f4d60abc7664b90827ed5b7e564f8d19b5a79f2
t4 iplus t2 t3 -> 8000000000000000
    fp: ccd13eabccd5713a4e226dcfaacefcc8a38799acd245b47ce83b6278b29ed123
t5 isub t4 t3 -> 7fffffffffffffff
    fp: 359b5f29c47e99f92261eb4e28610d9d26f7abdad05f82589bf7308e581b4c1f
t6 imul t2 t2 -> 0000000000000001
    fp: c4e7e35785b4689dfacf1744589f2c39fff709994b2e5c713b6be0d783c36c0a
t7 set r t6 -> 0000000000000001
    fp: 5919f4f01dede789db9ee7b5725f09de8100ef82ec45bef11aa2a46548b65004
--- fingerprint ---
5919f4f01dede789db9ee7b5725f09de8100ef82ec45bef11aa2a46548b65004
--- что проверяет ---
Проверяет переполнение Int64 по модулю 2^64: max+1 -> min, min-1 -> max, max*max -> 1. Бьёт по языкам с молчаливым повышением точности.

=== GOLDEN TRACE: DemoDenorm ===
runtime: reference (host)
--- environment ---
d = 0000000000000001
half = 3fe0000000000000
--- journal ---
t0 const 0000000000000001 -> 0000000000000001
    fp: e00450648e7e89954ac2dbc70ce55b1c3b9dde076e13e27454dd5011b9a44439
t1 const 3fe0000000000000 -> 3fe0000000000000
    fp: 59b31e6952094acdeb025f11e9b7e94a2c537dd05d773c3ce7efb909c4922136
t2 ref d -> 0000000000000001
    fp: 6c5dde599697aeadcd1433ee80a5a3e7826c54c740452c18176be18752ca8510
t3 ref half -> 3fe0000000000000
    fp: 0a772da8183381ca48c705201189ccfd2473e0c0864915e8a78e587f5aba3855
t4 mul t2 t3 -> 0000000000000000
    fp: 5ba547e4897b8ee8556ba0e446b3bb3ab0659d1da933724c76fe9fd63a23c0b7
t5 plus t2 t2 -> 0000000000000002
    fp: de1552843db5a4e90d24fee124c8cabedcb27147002f7fc16a8717cadb311434
t6 div t5 t2 -> 4000000000000000
    fp: bd6b35c11872071a8a0c89528c60e41126ff7fc176714a91295ffb219693e089
t7 set r t6 -> 4000000000000000
    fp: 27f241bf40f85b47463ba32ca699aefca9f1d9ab185486e5bd3b81068fe9dafe
--- fingerprint ---
27f241bf40f85b47463ba32ca699aefca9f1d9ab185486e5bd3b81068fe9dafe
--- что проверяет ---
Проверяет денормалы и ties-to-even: 1ulp*0.5 -> +0, 1ulp+1ulp -> 2ulp, 2ulp/1ulp -> 2.0. Бьёт по -ffast-math и flush-to-zero.

=== GOLDEN TRACE: DemoNaN ===
runtime: reference (host)
--- environment ---
n = 7ff8000000000001
zero = 0000000000000000
--- journal ---
t0 const 7ff8000000000001 -> 7ff8000000000001
    fp: adab9b7f5ffe42302e2d1ee3561fd2301e47f4a28a921ff88b577444529e5b8d
t1 ref n -> 7ff8000000000001
    fp: c14fda5c21f86c045aea39e4cce7ade7cc2e8d696141a9477105c6e54b60ff5e
t2 neg t1 -> fff8000000000001
    fp: 2a44cc31cdbb67c8157d2c9c7de471f393639f04f01fd1d40559a102f715bcba
t3 const 0000000000000000 -> 0000000000000000
    fp: 2ca8cd13a38ebcfb31e826dbba503b922117383f25dfa5d587b1f238afd8ad01
t4 ref zero -> 0000000000000000
    fp: 64cbb30a3de236889d3fc341217b3906c4df08cc791d2741ed77f5f1cadf6cea
t5 plus t2 t4 -> fff8000000000001
    fp: b60a462f705ac5928ae8e1f48060ed29bf690614b3f183965a35ea6365b7ad4c
t6 set r t5 -> fff8000000000001
    fp: dd184d71f9e2f993d2b9b94fa257c75dac912f208692f36ecb4cc992e3a5d600
--- fingerprint ---
dd184d71f9e2f993d2b9b94fa257c75dac912f208692f36ecb4cc992e3a5d600
--- что проверяет ---
Назначает политику NaN: neg переворачивает только знаковый бит (payload сохраняется); первым NaN-операндом в plus побеждает левый. Стандарт C это оставляет неопределённым — след назначает.

=== GOLDEN TRACE: DemoDiv0 ===
runtime: reference (host)
--- environment ---
a = 3ff0000000000000
b = 0000000000000000
--- journal ---
t0 const 3ff0000000000000 -> 3ff0000000000000
    fp: 0d961951d17880d845a39210cd6e564f53b4e754247f5b25b42139338911fb47
t1 const 0000000000000000 -> 0000000000000000
    fp: e26ed8a7373751f66217ec6b247e0c13ccf913200f41d93ab16d5bb65e486252
t2 ref b -> 0000000000000000
    fp: ebab1a5359e9c6ae153805373e63a80a4a78e2f82b6663af954bbb966c521847
t3 eq t2 0000000000000000 -> true
    fp: 22e98645518c0009a95e64fcb4b9fe30fc65dbcbac035bd7a1746716535e9fa6
t4 if t3 t5 t7 -> branch_t
    fp: 075a50a21270a7780c35feba93801ad4944aa42ebf8fe55ad4e87c2cf4d4bc7e
t5 err div0 3ff0000000000000 -> err:div0:3ff0000000000000
    fp: 5a54d71030cf8c4478807a3911fb22e97588eb4294407fa51e4e8d29ec15d2d3
t6 set r t5 -> err:div0:3ff0000000000000
    fp: b3813a7b76b536ee4c37164a1653d783fb8de4671952d6cea638f83b75e12672
--- fingerprint ---
b3813a7b76b536ee4c37164a1653d783fb8de4671952d6cea638f83b75e12672
--- что проверяет ---
Проверяет Railway: ошибка возникает как значение err:div0:<payload>, протекает в set, наблюдаема в журнале, не прерывает вычисление. Ветка else не исполняется и в журнал не попадает.

=== GOLDEN TRACE: DemoFold ===
runtime: reference (host)
--- environment ---
acc = 0000000000000000
L = 3|4341c37937e08000,3ff0000000000000,c341c37937e08000
--- journal ---
t0 const 0000000000000000 -> 0000000000000000
    fp: beca06fff28934025792f6c8292a4a08d071d1219fd7c27e1253d76ae7d60770
t1 list 3|4341c37937e08000,3ff0000000000000,c341c37937e08000 -> 3|4341c37937e08000,3ff0000000000000,c341c37937e08000
    fp: d911a59d60e99139c43526c2c2338cde1e5ff1c47b01f01014e72d5cc3a2279d
t2 fold L acc -> 0000000000000000
    fp: 6d73b82e24517bb3856938b19aac7521d868947a3784bb1e2c0b6a9bbebe3a88
t3 foldlist L acc -> 3|4341c37937e08000,4341c37937e08000,0000000000000000
    fp: 638e21283c93649476e6fbb03e8925c64eab2e50b83df7f5ae21a9835ba874a9
t4 set r t3 -> 3|4341c37937e08000,4341c37937e08000,0000000000000000
    fp: 540908d7730ea17d8aa645ff70cbc26a827f1861c81aef368889b4f6a3be103f
--- fingerprint ---
540908d7730ea17d8aa645ff70cbc26a827f1861c81aef368889b4f6a3be103f
--- что проверяет ---
Фиксирует порядок накопления (левая ассоциативность) и канон списка N|h1,...,hN. 1e16+1.0 -> 1e16 (ulp=2, ties-to-even вниз), любая перестановка свёртки ломает отпечаток.
