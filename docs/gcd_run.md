# Протокол прогона: gcd через трёхслойную систему

## Программа
    a = A; b = B;
    while b != 0:
        t = b
        b = a mod b
        a = t
    return a

## Сообщения по грамматике SPEC

MSG#1  TASK       USER -> L0    program=gcd; checks=[division_by_zero, termination]

MSG#2  MODEL      L0 -> L1
        CFG: ENTRY -> L -> {BODY, EXIT}; BODY -> L (back edge)
        SCC: {L, BODY} (Тарьян: 1 цикл)
        потоки/разрезы: неприменимо (нет ресурсной модели)
        паросочетания: неприменимо
        тривиальные вердикты: нет (деление только внутри цикла)
        очередь: [loop L..BODY..L]

MSG#3  VERDICTS   L1            (сценарий A: вход a,b in [1, +inf), целые)
        итерации fixed-point:
          iter 1: I[L] = a:[1,+inf] b:[1,+inf]  ->  a:[1,+inf] b:[0,+inf]
          iter 2: I[L] = a:[1,+inf] b:[0,+inf]  ->  без изменений (неподвижная точка)
        фильтр условия: b in [0,+inf] ^ b != 0 -> [1,+inf] (целочисленный домен)
        verdict `a mod b`: SAFE

MSG#4  MAYBE_QUEUE L1 -> L2      (сценарий B: входы без ограничений)
        hole_id=1; kind=DIVISION; loc="BODY: b = a mod b"
        invariant: I[L] = a:[-inf,+inf] b:[-inf,+inf]
        причина: интервал делителя пересекает 0; выпуклость домена не позволяет
                 выразить "b != 0"; widening границы не улучшает
        parent_chain: [mod-check@L1]

MSG#5  CERTIFICATE L2 -> REPORT
        verdict: PROOF (безопасно)
        доказательство: path condition {b != 0} противоречит цели {b == 0};
                        SMT: UNSAT -> контрпримера не существует
        завершаемость: вариант V = b; после тела 0 <= b' < b при b >= 1
                       (b' = a mod b); строгое убывание + ограничение снизу
                       => цикл завершается для всех целых входов

MSG#6  REPORT
        checks: 2; SAFE: 2; UNSAFE: 0; MAYBE_out: 0 (закрыто слоем 2)
        certificates: PROOF x2 (деление, завершаемость)
        caveats: сценарий B потребовал слоя 2; сценарий A закрыт слоем 1 за 2 итерации
