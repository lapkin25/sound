# Sound Language Specification v0.1

## 1. Обзор и принципы

Sound — декларативный язык спецификаций вычислительных конвейеров. Программа описывает **что** должно быть истинно (факты, правила, инварианты, цели), но не **как** это вычислять. Компилятор Sound превращает программу в граф Trio (узлы/рёбра/режимы передачи), опираясь на правила конверсий из Trio Type Bridge Spec v0.1 (обозначения R-*).

Три принципа:

1. **Нет императивного кода.** В языке нет циклов, `if`, присваиваний. Управление потоком выводится из графа данных.
2. **Ошибки — значения.** Любой частичный сбой выражается через `Result[T, E]`; непокрытые варианты — ошибка компиляции (R-ERR1).
3. **Программа звучит.** Каждая программа имеет определённую звуковую семантику: исполнение графа порождает партитуру (§9).

## 2. Лексическая структура

- Файл — UTF-8, расширение `.sound`.
- Идентификаторы: `[A-Za-z_][A-Za-z0-9_]*`. Ключевые слова — строчные: `spec, fact, rule, wire, invariant, goal, implementation, requires, domain, as, handle, from, in, minimize, maximize, dim, where`.
- Комментарии: `//` до конца строки (каноническая форма), `/* … */` для блоков. Прототип дополнительно принимает `#` — считается унаследованной формой.
- Числовые литералы: целые `7`, вещественные `3.5`. Строки — в двойных кавычках.
- Разделяющие пробелы и переводы строк незначимы; каждое объявление завершается `;`.

## 3. Грамматика (EBNF)

    program      = spec ;
    spec         = "spec" IDENT "{" { item } "}" ;
    item         = fact | rule | wire | invariant | goal | impl | dimdecl ;

    fact         = "fact" IDENT [ "from" STRING ] "->" type ";" ;

    rule         = "rule" IDENT "(" args ")" { rulemod } "->" type [ "=" expr ] ";" ;
    args         = arg { "," arg } ;
    arg          = IDENT ":" type ;
    rulemod      = requires | domain | ruleinv | binding ;
    requires     = "requires" cond ;
    domain       = "domain" IDENT ;                    (* "nan" | "strict"; по умолчанию strict *)
    ruleinv      = "invariant" pred ;
    binding      = "in" runtime ":" STRING ;           (* каноническая привязка *)

    wire         = "wire" port "=" source
                   [ "as" mode ]
                   [ "handle" "[" IDENT { "," IDENT } "]" ] ";" ;
    port         = IDENT [ "." IDENT ] ;               (* rule.out, rule.имя_аргумента, rule.ok, rule.err *)
    source       = port | literal ;
    mode         = "copy" | "view" | "move" ;

    invariant    = "invariant" pred ";" ;              (* на уровне spec *)
    goal         = "goal" goalitem { "," goalitem } ";" ;
    goalitem     = ( "minimize" | "maximize" ) "(" IDENT ")" ;

    impl         = "implementation" IDENT "in" runtime ":" STRING ";" ;
    runtime      = "python" | "java" | "octave" ;

    dimdecl      = "dim" IDENT [ "=" dimexpr ] ";" ;   (* ◻ зарезервировано *)

Типы:

    type      = basetype | matrix | vector | seq | stream | optional
              | record | result | "Any" ;
    basetype  = "Int64" | "Float64" | "Float32" | "Bool" | "String" ;
    matrix    = "Matrix" "[" stype "," dimlist "]" ;     (* допустимы псевдонимы F64, F32 *)
    vector    = "Vector" "[" stype "," dim "]" ;
    seq       = "Seq" "[" type "]" ;
    stream    = "Stream" "[" type "]" ;
    optional  = "Optional" "[" type "]" ;                (* вложенность запрещена — R-OPT2 *)
    record    = "Record" "{" field { "," field } "}" ;   (* ◻ *)
    field     = IDENT ":" type ;
    result    = "Result" "[" type "," ERRVAR "]" ;       (* ERRVAR ∈ TrioError, §8 *)
    dimlist   = dim { "," dim } ;
    dim       = NAT | "?" | IDENT | dimexpr ;            (* IDENT с малой буквы = DimVar *)
    dimexpr   = линейное выражение над DimVar и NAT: + − ×(на NAT), скобки ;

## 4. Типы ядра

| Тип | Комментарий |
|---|---|
| `Int64` | граница 2^53 при переводе в `double`-рантаймы |
| `Float64`, `Float32` | `F32 → F64` — точное расширение; обратное — `Lossy(precision)` |
| `Bool` | не приводится к числам и обратно (R-BOOL) |
| `String` | UTF-8 |
| `Matrix[T, …]` | измерения — типы: NAT, `?`, DimVar, линейное выражение |
| `Vector[T, N]` | вырожденная матрица, одна размерность |
| `Stream[T]` | только pull-модель (R-STREAM1) |
| `Seq[T]` | гомогенный список |
| `Optional[T]` | без вложенности (R-OPT2) |
| `Result[T, E]` | ошибки как значения (§8) |
| `Any` | постепенная типизация; уточнение фиксируется трассой (R-COMP2) |

**Область видимости DimVar.** DimVar идентифицируется по имени в пределах всего `spec` и унифицируется глобально (R-DIM3). `?` совместим с DimVar до первого рантайм-значения; обратное ослабление — только через явный `generalize` (R-DIM5/6).

## 5. Декларации и семантика

### fact

Объявляет источник данных. Компилируется в узел-источник графа. `"from"` — необязательное имя физического источника. Тип с `?` фиксируется первым реальным значением.

### rule

Узел вычислений. Аргументы — входные порты; выход — порт `имя.out`. Модификаторы:

- **`requires`** — предусловие. Статически проверяется по размерностям и константам; динамически проверяется на границе узла, нарушение — `Err(DomainError)`.
- **`domain nan`** — легализует NaN/Inf внутри узла (R-NAN). Без объявления — `strict`.
- **`invariant`** — инвариант выхода узла (§6).
- **`in runtime : "артефакт"`** — привязка реализации. Форматы артефактов: `python` — `"файл:функция"`, `java` — `"FQCN:метод"`, `octave` — `"файл:функция"`. Правило без привязки — ошибка компиляции **SC-001 UnboundRule**.
- **`= expr`** — чистое тело (функциональное ядро v0.2, см. `Sound_Functional_Core_Addendum_v0.2.md`). Правило с телом исполняется нативно, SC-001 к нему не применяется.

### wire

Ребро графа.

- Источник — порт другого узла или литерал. Литерал проверяется скалярными правилами: дробная константа к `Int64` и значения за 2^53 не проходят.
- **`as` mode** задаёт режим передачи; если опущен, компилятор выводит его сам: `move`, если источник после этого ребра не читается, `view`, если безопасно по layout и непрерывности (R-MAT1), иначе `copy`. Выводимый режим виден в диагностиках.
- **`handle`** обязателен на ребре из порта узла с `Result`-выходом и перечисляет покрытые варианты (R-ERR1).

### invariant

На уровне `spec` — инвариант ребра или узла (синтаксис `where`, ◻). Внутри `rule` — инвариант выхода.

### goal

Цели решателя для свободных параметров. В v0.1 компилятор фиксирует цели в графе; численная оптимизация — ◻.

### implementation

Каноническая привязка правила к рантайму; эквивалентна модификатору `in` внутри `rule`.

## 6. Выражения и предикаты

- Арифметика: `+ − *`, скобки; умножение DimVar — только на натуральную константу. Нелинейное условие в `requires` — ошибка **SC-020 NonLinearConstraint**.
- Сравнения: `== != < <= > >=`; принадлежность диапазону: `in [a, b]`; чётность через `%`.
- Логика: `and or not`.
- Библиотека инвариантов ✅: `every X has exactly one Y`, `X is finite`, `X >= 0`, size-условия. Пользовательские предикаты — ◻.

## 7. Связывание рёбер

Тип порта источника унифицируется с типом порта приёмника:

- несовпадение ранга/значений размерностей — **ShapeError** на границе (R-DIM7);
- конверсии dtype — по таблице: точные (`F32→F64`, `Int64→Float64` с `Lossy(repr)`), объявленно-потерьные (`F64→F32` — ребро помечается `lossy:precision`), запрещённые (`Bool→число` — **UndefinedBridge**, R-BOOL);
- сужение `Float64 → Int64` на ребре запрещено статически — SC-040 (R-INT2);
- `move` на `Stream` запрещён, автоматически понижается до `copy` (R-STREAM1);
- несовместимый layout при `view` понижается до `copy` с предупреждением (R-MAT1).

## 8. Модель ошибок

Закрытый набор вариантов `TrioError`: `TypeMismatch, ShapeError, DomainError, IntRangeOverflow, FractionalInt, NoCoercion, EncodingFault, NaNAsMissing, SentinelDetected, LayoutMismatch, MissingField, HeterogeneousMatrix, NullPointer, UnsupportedStreaming, ResourceLost, UndefinedBridge`.

Правила:

1. Узел с `Result`-выходом порождает порты `.ok` (тип `T`) и `.err` (варианты `E`). Ребро из `.ok` несёт развёрнутое значение; ребро с `handle` обязано покрыть все варианты источника — иначе **SC-030 UncoveredVariant**.
2. Непереводимое исключение рантайма → `ResourceLost`, `trusted=false`: узел помечается недоверенным, граф перепланируется (R-ERR2).

## 9. Звуковая семантика

Каждое событие исполнения отображается в партитуру. Отображение по умолчанию:

| Событие | Звучание |
|---|---|
| старт узла | нота по рантайму: python — A4 (440 Гц), java — C5 (523 Гц), octave — E5 (659 Гц), pure — G4 (392 Гц) |
| завершение узла | нота на квинту выше стартовой |
| ребро с `Lossy` | приглушение на 6 дБ, укороченный тембр |
| `ShapeError` | тритон-диссонанс |
| `DomainError` | малая секунда |
| `ResourceLost` | обрыв звука (тишина вплоть до конца такта) |
| успешный прогон | консонансный аккорд в финале |

Партитура рендерится в WAV с временными метками событий. Пользовательские переопределения (`sound`-директивы) — ◻ зарезервировано.

## 10. Компиляция и диагностики

Конвейер: разбор → IR → проверка типов и связывания (§6–8) → эмиссия `pipeline_graph.json` → раскладка партитуры.

Коды диагностики ✅: `SC-001 UnboundRule`, `SC-002 UnknownName`, `SC-003 WrongArity`, `SC-005 Recursion`, `SC-010 ShapeError`, `SC-011 ModeDowngrade` (view→copy), `SC-020 NonLinearConstraint`, `SC-030 UncoveredVariant`, `SC-040 ForbiddenConversion`, `SC-050 DimConflict`, `SC-060 HeterogeneousMatrix`, `SC-070 CycleOrOccurs`, `SC-097 SyntaxError`, `SC-098 TrailingTokens`, `SC-099 LexerError`.

## 11. Полный пример

    spec AnomalyMonitor {

      fact frames -> Stream[Matrix[F64, R, 512]];

      rule extract_features(frame: Matrix[F64, R, 512])
        -> Matrix[F64, R, 64]
        invariant every frame has exactly one features;

      rule score(batch: Matrix[F64, R, 64])
        requires R > 0
        -> Result[Vector[F64, 10], DomainError];

      rule smooth(scores: Vector[F64, 10], window: Int64)
        requires window in [3, 31] and window % 2 == 1
        -> Vector[F64, 10];

      wire extract_features.frame = frames.out as view;
      wire score.batch            = extract_features.out as move;
      wire smooth.scores          = score.ok as copy handle [DomainError];
      wire smooth.window          = 7;

      implementation extract_features in python: "feats.py:extract";
      implementation score           in java:   "com.trio.ScoreService";
      implementation smooth          in octave: "smooth_scores.m";

      goal minimize(false_alarm_rate), maximize(detection_rate);
    }

## 12. Открытые вопросы к v0.2

- Record-поля в `requires` и `invariant` (сейчас предикаты видят только размеры и константы).
- Явный синтаксис свободных параметров (`param window: Int64 where …`) вместо константы на `wire`.
- Модули и импорт спецификаций.
- Переопределяемая звуковая разметка.

---

Статус реализации: помеченное ✅ проверяется компилятором прототипа (включая негативные тесты SC-001/040/050/060/070); помеченное ◻ — зарезервировано для v0.2+.
