# Trio Type Bridge Spec v0.1

## 1. Назначение

Trio — среда передачи данных между тремя рантаймами (Python, Java, Octave) и чистыми узлами ядра Sound. Спецификация фиксирует: модель конверсий, закрытый набор ошибок, правила R-* и байтовый формат TRIOMAT. Три реализации бриджа сверяются с этой спекой.

## 2. Модель конверсий

Каждая конверсия на границе рантаймов возвращает один из трёх исходов:

- **OK** — точное преобразование;
- **Lossy(tag)** — объявленно-потерьное преобразование; `tag ∈ {precision, repr}`;
- **Err(err)** — конверсия невозможна, `err ∈ TrioError`.

Конверсия, не описанная в таблице ниже, — `Err(UndefinedBridge)`.

## 3. Скалярные правила

- **R-INT1.** `Int64 → Int64` — OK. Значения за пределами 2^53 при передаче в `double`-рантаймы — `Err(IntRangeOverflow)`.
- **R-INT2.** `Float64 → Int64` — `Err(FractionalInt)`, если есть дробная часть; целые в пределах 2^53 — OK, но **на рёбрах графа запрещено** (сужение проверяется статически, SC-040).
- **R-INT3.** `Int64 → Float64` — OK, но `Lossy(repr)` для значений, не представимых точно в double.
- **R-FLT1.** `Float64 → Float64` — OK.
- **R-FLT2.** `Float32 → Float64` — точное расширение, OK.
- **R-FLT3.** `Float64 → Float32` — `Lossy(precision)`.
- **R-BOOL.** `Bool` не приводится к числам и обратно. Попытка — `Err(UndefinedBridge)`.
- **R-STR.** `String` — UTF-8; невалидная последовательность — `Err(EncodingFault)`.

## 4. Матрицы и размерности

- **R-MAT1.** Передача `view` допустима только при совпадении layout и непрерывности; иначе понижение до `copy` с диагностикой `SC-011 ModeDowngrade`.
- **R-DIM3.** DimVar унифицируется по имени в пределах всей спеки.
- **R-DIM5/6.** Уточнение `? → DimVar/NAT` — при первом рантайм-значении; обратное ослабление — только явное.
- **R-DIM7.** Несовпадение ранга или значений размерностей — `Err(ShapeError)` / диагностика SC-050 DimConflict.
- **R-HET.** Гетерогенная матрица (элементы разных типов) — `Err(HeterogeneousMatrix)` / SC-060.

## 5. Домены

- **R-OPT1.** Отсутствие канонизируется как `Optional[T]` без вложенности; вложенный `Optional` — ошибка (R-OPT2).
- **R-NAN.** NaN/Inf в `strict`-домене — `Err(NaNAsMissing)`/`DomainError`; в домене `nan` — легальны. Дефолт — `strict`.

## 6. Потоки и постепенность

- **R-STREAM1.** `Stream[T]` — только pull-модель; `move` на потоке запрещён (понижение до `copy`).
- **R-COMP2.** Тип `Any` уточняется при первом использовании; уточнение фиксируется в трассе.

## 7. Ошибки и доверие

Закрытый набор `TrioError`: `TypeMismatch, ShapeError, DomainError, IntRangeOverflow, FractionalInt, NoCoercion, EncodingFault, NaNAsMissing, SentinelDetected, LayoutMismatch, MissingField, HeterogeneousMatrix, NullPointer, UnsupportedStreaming, ResourceLost, UndefinedBridge`.

- **R-ERR1.** Ошибки — значения (`Result[T, E]`); ребро с `handle` обязано покрыть все варианты источника — иначе SC-030 UncoveredVariant.
- **R-ERR2.** Непереводимое исключение рантайма → `ResourceLost`, узел получает `trusted=false`, граф перепланируется.

## 8. Формат TRIOMAT v1

Байтовый контракт файла:

    [u32 little-endian: длина заголовка]
    [заголовок: UTF-8 JSON]
    [payload: сырые байты в порядке C]

Заголовок:

    { "magic": "TRIOMAT1", "dtype": "Float64|Int64|Bool", "shape": [..], "flags": {} }

Флаги: `stub` (источник — эмуляция), `lossy` (ребро с потерями), `trusted` (по умолчанию true).

Payload интерпретируется строго по `shape` и `dtype`; расхождение — `Err(ShapeError)`.

## 9. Соответствие реализациям

Проверки прототипа: Python-бридж — 37 проверок, Java-бридж — 27 (счёт из прогонов прототипа); негативные тесты графа — 5 из 5 (SC-001/040/050/070, UndefinedBridge).
