# O.2 — матрица гипотез отпечатка (харнесс)

Цель: фиксация пространства кандидатов на эталонных байтах DemoMax (60 строк, дословно из журнала приёмки).
Известный обрезок DemoSum: prefix=721b9d5c5972, suffix=800d. Совпадений на DemoMax нет — это норма: скоупы разных файлов.

| Скоуп | Алгоритм | prefix | suffix | длина hex |
|---|---|---|---|---|
| S1 full+LF | sha256 | 7dc69c9c6fce | 354c | 64 |
| S1 full+LF | sha1 | b5776a97ff27 | 581d | 40 |
| S1 full+LF | md5 | 21cf44aadc11 | 4321 | 32 |
| S1 full+LF | sha512t | 82c4e3eb084e | 9ed6 | 64 |
| S1 full+LF | blake2b | ffd84e082f16 | c3a9 | 64 |
| S2 full, no NL | sha256 | 6d65e69f9fd2 | 08b4 | 64 |
| S2 full, no NL | sha1 | a42318244f3d | 7277 | 40 |
| S2 full, no NL | md5 | 180d15119a5b | 0e03 | 32 |
| S2 full, no NL | sha512t | 1b27c7f01076 | 6a58 | 64 |
| S2 full, no NL | blake2b | 052c80ec33d1 | 9cbe | 64 |
| S3 full+CRLF | sha256 | 4258a5bc01fe | 6379 | 64 |
| S3 full+CRLF | sha1 | e82494f5e75f | 5ec5 | 40 |
| S3 full+CRLF | md5 | 9cb7b7a5481c | 3ced | 32 |
| S3 full+CRLF | sha512t | 62532a19a7c5 | 0581 | 64 |
| S3 full+CRLF | blake2b | e007ed26d275 | 0fe0 | 64 |
| S4 steps+LF | sha256 | d06047f0c5b0 | b735 | 64 |
| S4 steps+LF | sha1 | cda0126a400d | 39f0 | 40 |
| S4 steps+LF | md5 | e8a4523bc81d | 0449 | 32 |
| S4 steps+LF | sha512t | 1bf68fa55404 | 9f5d | 64 |
| S4 steps+LF | blake2b | 7f41f591b2aa | 2d18 | 64 |
| S5 steps, no NL | sha256 | fa8652cd391b | 084e | 64 |
| S5 steps, no NL | sha1 | 713ba942ef5a | 4d69 | 40 |
| S5 steps, no NL | md5 | d296907a554d | cc66 | 32 |
| S5 steps, no NL | sha512t | 994d1a61be17 | 239d | 64 |
| S5 steps, no NL | blake2b | 7948582b1436 | 8741 | 64 |
| S6 header only | sha256 | 0ad06f4ebde5 | d191 | 64 |
| S6 header only | sha1 | d5bf019cbcdf | 3f7c | 40 |
| S6 header only | md5 | 8091c4f397e8 | bd6a | 32 |
| S6 header only | sha512t | 1b9f55a82a4c | 00d5 | 64 |
| S6 header only | blake2b | fd639882b6e3 | 8d4f | 64 |
| S7 canonical | sha256 | a3f5fb6dbe42 | e1b5 | 64 |
| S7 canonical | sha1 | b1795060162e | fb9f | 40 |
| S7 canonical | md5 | bda1a8ab039f | 5e03 | 32 |
| S7 canonical | sha512t | aeea79a4ff9b | ffc3 | 64 |
| S7 canonical | blake2b | 5b01e6a12614 | 313e | 64 |