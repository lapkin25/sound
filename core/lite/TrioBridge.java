// TrioBridge.java — JVM-сторона референсного бридга Trio Type Bridge Spec v0.1.
// Без внешних зависимостей; требуется Java 17+ (switch expressions, instanceof patterns).
//
// Формат TRIOMAT — байт-в-байт как в trio_bridge.py / trio_bridge.m:
//   0..7   magic "TRIOMAT\x01"
//   8      version = 1
//   9      layout: 0 = row-major, 1 = column-major
//   10     dtype:  0 = Float64, 1 = Float32, 2 = Int64, 3 = Bool
//   11     ndim
//   далее  ndim x u64 big-endian — размеры
//   далее  payload в объявленном dtype, LITTLE-endian (кроссплатформенный
//          контракт; заголовок — big-endian), в layout-порядке
// Размер элемента: Float64/Int64 = 8 байт, Float32 = 4, Bool = 1.
// Для ndim = 0 payload пуст (скалярная вырожденная форма).
//
// Запуск тестов: javac TrioBridge.java TrioBridgeTest.java && java TrioBridgeTest

import java.io.BufferedOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public final class TrioBridge {

    private TrioBridge() {}

    // ---------- R-ERR1/2: закрытое перечисление ошибок ----------

    public enum Variant {
        TypeMismatch, DomainError, ShapeError, MissingField,
        IntRangeOverflow, FractionalInt, NoCoercion, EncodingFault,
        HeterogeneousMatrix, NaNAsMissing, SentinelDetected, DomainViolation,
        LayoutMismatch, UndefinedBridge, NullPointer, ResourceLost
    }

    /** Ошибка Trio. trusted=false => узел помечается недоверенным (R-ERR2). */
    public static final class TrioError extends Exception {
        public final Variant variant;
        public final boolean trusted;

        public TrioError(Variant variant, String message, boolean trusted) {
            super(message == null || message.isEmpty()
                    ? variant.name() : variant + ": " + message);
            this.variant = variant;
            this.trusted = trusted;
        }

        public TrioError(Variant variant, String message) { this(variant, message, true); }
    }

    // ---------- Результаты конверсии: Ok | Lossy | ErrConv ----------

    /** Lossy не является ошибкой: потеря объявлена (раздел 1 спеки). */
    public interface Conv<T> {}

    public static final class Ok<T> implements Conv<T> {
        public final T value;
        public final List<String> meta; // R-TRACE: происхождение значения

        public Ok(T value, String... meta) {
            this.value = value;
            this.meta = List.of(meta);
        }

        @Override public String toString() { return "Ok(" + value + ")"; }
    }

    public static final class Lossy<T> implements Conv<T> {
        public final T value;
        public final String delta; // "repr" | "precision" | "dropped_fields"
        public final List<String> meta;

        public Lossy(T value, String delta, String... meta) {
            this.value = value;
            this.delta = delta;
            this.meta = List.of(meta);
        }

        @Override public String toString() { return "Lossy(" + value + ", " + delta + ")"; }
    }

    public static final class ErrConv<T> implements Conv<T> {
        public final TrioError error;

        public ErrConv(TrioError error) { this.error = error; }

        @Override public String toString() { return "Err(" + error.getMessage() + ")"; }
    }

    // ---------- DType ----------

    public enum DType {
        FLOAT64(0, 8), FLOAT32(1, 4), INT64(2, 8), BOOL(3, 1);

        public final int code;
        public final int itemSize;

        DType(int code, int itemSize) { this.code = code; this.itemSize = itemSize; }

        public static DType byCode(int code) throws TrioError {
            for (DType t : values()) {
                if (t.code == code) return t;
            }
            throw new TrioError(Variant.UndefinedBridge, "dtype-код " + code);
        }
    }

    public static final long INT64_LIMIT = 9007199254740992L; // 2^53

    // ---------- MType: dtype + измерения-типы ----------

    /** dims[i] > 0 — фиксированный размер; -1 — '?'; < -1 — id DimVar (v0.2). */
    public static final class MType {
        public final DType dtype;
        public final long[] dims;

        public MType(DType dtype, long... dims) {
            this.dtype = dtype;
            this.dims = dims.clone();
        }

        public boolean fullyKnown() {
            for (long d : dims) {
                if (d <= 0) return false;
            }
            return true;
        }

        /** R-DIM5/R-DIM7: унификация; '?' и DimVar фиксируются первым значением. */
        public Conv<MType> check(long... shape) {
            if (shape.length != dims.length) {
                return new ErrConv<>(new TrioError(Variant.ShapeError,
                        "ранг " + shape.length + " != " + dims.length));
            }
            long[] bound = new long[dims.length];
            for (int i = 0; i < dims.length; i++) {
                if (dims[i] > 0) {
                    if (dims[i] != shape[i]) {
                        return new ErrConv<>(new TrioError(Variant.ShapeError,
                                "размер " + shape[i] + " != объявленного " + dims[i]));
                    }
                    bound[i] = dims[i];
                } else {
                    bound[i] = shape[i]; // R-DIM5
                }
            }
            return new Ok<>(new MType(dtype, bound));
        }

        /** R-DIM6: единственный путь от конкретного размера к '?'. */
        public MType generalize(int index) {
            long[] d = dims.clone();
            d[index] = -1;
            return new MType(dtype, d);
        }

        @Override public String toString() {
            StringBuilder sb = new StringBuilder("MType(").append(dtype).append(", [");
            for (int i = 0; i < dims.length; i++) {
                if (i > 0) sb.append(", ");
                sb.append(dims[i] == -1 ? "?" : Long.toString(dims[i]));
            }
            return sb.append("])").toString();
        }
    }

    // ---------- Режимы передачи ----------

    public enum TransferMode { VIEW, COPY }

    /** Матрица в Octave-семантике: плоский payload + layout + режим. */
    public static final class OctavePayload {
        public final double[] payload; // row-major или col-major по флагу
        public final MType type;
        public final boolean columnMajor;
        public final TransferMode mode;

        public OctavePayload(double[] payload, MType type,
                             boolean columnMajor, TransferMode mode) {
            this.payload = payload;
            this.type = type;
            this.columnMajor = columnMajor;
            this.mode = mode;
        }
    }

    // ---------- Внутренние проверки ----------

    /** R-OPT1/R-NAN: NaN вне домена — отсутствие, а не число. */
    private static ErrConv<?> nanCheck(double v, boolean nanDomain) {
        if (Double.isNaN(v)) {
            if (!nanDomain) {
                return new ErrConv<>(new TrioError(Variant.NaNAsMissing, "R-OPT1"));
            }
            return null;
        }
        if (Double.isInfinite(v) && !nanDomain) {
            return new ErrConv<>(new TrioError(Variant.DomainViolation, "Inf вне домена nan"));
        }
        return null;
    }

    private static ErrConv<?> sentinelCheck(double v, Double sentinel) {
        if (sentinel != null && Double.compare(v, sentinel) == 0) {
            return new ErrConv<>(new TrioError(Variant.SentinelDetected,
                    "значение-сентинел " + sentinel + " на границе"));
        }
        return null;
    }

    private static <T> ErrConv<T> err(Variant v, String msg) {
        return new ErrConv<>(new TrioError(v, msg));
    }

    // ---------- Экспорт: ядро -> Octave-представление ----------

    /**
     * Непрерывный (row-major) источник. mode=VIEW легален только для
     * непрерывного буфера (R-MAT1); здесь double[] всегда непрерывен.
     */
    public static Conv<OctavePayload> exportToOctave(
            double[] flat, long rows, long cols, MType mt,
            TransferMode mode, boolean nanDomain, Double sentinel) {

        if (flat.length != rows * cols) {
            return err(Variant.ShapeError, "flat.length != rows*cols");
        }

        Conv<MType> bound = mt.check(rows, cols);
        if (bound instanceof ErrConv) {
            @SuppressWarnings("unchecked")
            ErrConv<MType> e = (ErrConv<MType>) bound;
            return new ErrConv<>(e.error);
        }
        MType bt = ((Ok<MType>) bound).value;

        // R-MAT1: VIEW без копирования возможен только для FLOAT64;
        // прочие dtype требуют конверсии элементов -> понижение до COPY
        boolean viewable = mode == TransferMode.VIEW && mt.dtype == DType.FLOAT64;

        double[] payload = viewable ? flat : new double[(int) (rows * cols)];
        boolean lossy = false;
        int k = 0;
        for (double v : flat) {
            ErrConv<?> e = sentinelCheck(v, sentinel);
            if (e != null) return new ErrConv<>(e.error);
            e = nanCheck(v, nanDomain);
            if (e != null) return new ErrConv<>(e.error);
            switch (mt.dtype) {
                case FLOAT64 -> payload[k++] = v;
                case FLOAT32 -> { payload[k++] = (double) (float) v; lossy = true; } // R-FLT1
                case INT64 -> { // R-INT3: дробные не проходят; диапазон в исходном домене
                    if (v != Math.floor(v)) {
                        return err(Variant.FractionalInt, "R-INT3: дробное значение");
                    }
                    if (Math.abs(v) > (double) INT64_LIMIT) {
                        return err(Variant.IntRangeOverflow, "R-INT2: |v| > 2^53");
                    }
                    payload[k++] = v;
                }
                case BOOL -> {
                    if (v == 0.0 || v == 1.0) {
                        payload[k++] = v;
                    } else {
                        return err(Variant.TypeMismatch, "Bool: значения должны быть 0/1");
                    }
                }
            }
        }
        OctavePayload p = new OctavePayload(payload, bt, false, mode);
        return lossy ? new Lossy<>(p, "precision") : new Ok<>(p);
    }

    /** Удобная обёртка: row-major источник 2D, режим COPY. */
    public static Conv<OctavePayload> exportToOctave(
            double[][] src, MType mt, boolean nanDomain, Double sentinel) {
        long rows = src.length;
        long cols = rows == 0 ? 0 : src[0].length;
        for (double[] row : src) {
            if (row.length != cols) return err(Variant.ShapeError, "рваная матрица");
        }
        double[] flat = new double[(int) (rows * cols)];
        int k = 0;
        for (double[] row : src) {
            for (double v : row) flat[k++] = v;
        }
        return exportToOctave(flat, rows, cols, mt, TransferMode.COPY, nanDomain, sentinel);
    }

    // ---------- Импорт: Octave-сторона -> ядро ----------

    /** Octave -> ядро (R-INT3, R-FLT1/2, R-BOOL, R-OPT1/R-NAN). */
    public static Conv<Object> fromOctave(
            double[][] src, DType target, boolean nanDomain, Double sentinel) {
        int rows = src.length;
        int cols = rows == 0 ? 0 : src[0].length;
        switch (target) {
            case FLOAT64 -> {
                double[][] out = new double[rows][cols];
                for (int i = 0; i < rows; i++) {
                    for (int j = 0; j < cols; j++) {
                        double v = src[i][j];
                        ErrConv<?> e = sentinelCheck(v, sentinel);
                        if (e != null) return new ErrConv<>(e.error);
                        e = nanCheck(v, nanDomain);
                        if (e != null) return new ErrConv<>(e.error);
                        out[i][j] = v;
                    }
                }
                return new Ok<Object>(out, "origin=OCT");
            }
            case FLOAT32 -> { // R-FLT1: сужение — Lossy(precision)
                float[][] out = new float[rows][cols];
                for (int i = 0; i < rows; i++) {
                    for (int j = 0; j < cols; j++) {
                        double v = src[i][j];
                        ErrConv<?> e = sentinelCheck(v, sentinel);
                        if (e != null) return new ErrConv<>(e.error);
                        e = nanCheck(v, nanDomain);
                        if (e != null) return new ErrConv<>(e.error);
                        out[i][j] = (float) v;
                    }
                }
                return new Lossy<Object>(out, "precision");
            }
            case INT64 -> {
                long[][] out = new long[rows][cols];
                for (int i = 0; i < rows; i++) {
                    for (int j = 0; j < cols; j++) {
                        double v = src[i][j];
                        ErrConv<?> e = sentinelCheck(v, sentinel);
                        if (e != null) return new ErrConv<>(e.error);
                        e = nanCheck(v, nanDomain);
                        if (e != null) return new ErrConv<>(e.error);
                        if (v != Math.floor(v)) {
                            return err(Variant.FractionalInt, "R-INT3: дробное значение");
                        }
                        // R-INT3: проверка в double-домене корректна: порог 2^53
                        // точно представим, дробные отсечены до сравнения
                        if (Math.abs(v) > (double) INT64_LIMIT) {
                            return err(Variant.IntRangeOverflow, "R-INT3: |v| > 2^53");
                        }
                        out[i][j] = (long) v;
                    }
                }
                return new Ok<Object>(out, "origin=OCT");
            }
            case BOOL -> {
                boolean[][] out = new boolean[rows][cols];
                for (int i = 0; i < rows; i++) {
                    for (int j = 0; j < cols; j++) {
                        double v = src[i][j];
                        if (v == 0.0 || v == 1.0) {
                            out[i][j] = v == 1.0;
                        } else {
                            return err(Variant.TypeMismatch, "Bool: значения должны быть 0/1");
                        }
                    }
                }
                return new Ok<Object>(out, "origin=OCT");
            }
        }
        return err(Variant.UndefinedBridge, "тип " + target + " не описан");
    }

    // ---------- Скалярные конверсии ----------

    /** Скалярные правила R-INT1..3, R-FLT1..3, R-BOOL. */
    public static Conv<Object> convertScalar(Object value, DType target, boolean nanDomain) {
        if (value instanceof Boolean) {
            return err(Variant.NoCoercion, "Bool к числу через границу не приводится");
        }
        switch (target) {
            case INT64 -> {
                if (value instanceof Long l) { // R-INT1: Int64 -> long тождественно;
                    // R-INT2: граница с double-представлением Octave
                    if (Math.abs(l) > INT64_LIMIT) {
                        return err(Variant.IntRangeOverflow, "R-INT2: |v| > 2^53");
                    }
                    return new Lossy<Object>((double) l, "repr");
                }
                if (value instanceof Double d) {
                    ErrConv<?> e = nanCheck(d, nanDomain);
                    if (e != null) return new ErrConv<>(e.error);
                    if (d != Math.floor(d)) {
                        return err(Variant.FractionalInt, "R-INT3: дробное значение");
                    }
                    if (Math.abs(d) > (double) INT64_LIMIT) {
                        return err(Variant.IntRangeOverflow, "R-INT3: |v| > 2^53");
                    }
                    return new Ok<Object>((long) d);
                }
                return err(Variant.TypeMismatch,
                        "Int64: " + value.getClass().getSimpleName());
            }
            case FLOAT64 -> {
                if (value instanceof Long l) return new Ok<Object>((double) l);
                if (value instanceof Double d) {
                    ErrConv<?> e = nanCheck(d, nanDomain);
                    if (e != null) return new ErrConv<>(e.error);
                    return new Ok<Object>(d);
                }
                if (value instanceof Float f) {
                    return new Ok<Object>((double) f, "origin=F32"); // R-FLT3
                }
                return err(Variant.TypeMismatch,
                        "Float64: " + value.getClass().getSimpleName());
            }
            case FLOAT32 -> {
                if (value instanceof Long l) {
                    return new Lossy<Object>((float) (double) l, "precision");
                }
                if (value instanceof Double d) {
                    ErrConv<?> e = nanCheck(d, nanDomain);
                    if (e != null) return new ErrConv<>(e.error);
                    return new Lossy<Object>((float) (double) d, "precision"); // R-FLT1
                }
                return err(Variant.TypeMismatch,
                        "Float32: " + value.getClass().getSimpleName());
            }
            case BOOL -> {
                // R-BOOL: числа к Bool не приводятся (попадаем сюда только не-Bool)
                return err(Variant.NoCoercion, "R-BOOL: числа к Bool не приводятся");
            }
        }
        return err(Variant.UndefinedBridge, "тип " + target + " не описан");
    }

    public static Conv<Boolean> convertBoolean(Boolean value) {
        return new Ok<>(value);
    }

    /** R-STR: неспаренные суррогаты -> EncodingFault (спаренные кодируются). */
    public static Conv<String> convertString(String s) {
        boolean bad = s.codePoints().anyMatch(c -> c >= 0xD800 && c <= 0xDFFF);
        if (bad) {
            return new ErrConv<>(new TrioError(Variant.EncodingFault, "R-STR: суррогатный кодпоинт"));
        }
        return new Ok<>(s);
    }

    // ---------- Формат TRIOMAT ----------

    private static final byte[] MAGIC = {'T', 'R', 'I', 'O', 'M', 'A', 'T', 0x01};
    private static final int VERSION = 1;
    private static final int HEADER_SIZE = 12;

    /** Пишет TRIOMAT-файл: заголовок big-endian, payload little-endian. */
    public static void writeMatrix(Path path, OctavePayload p) throws IOException {
        try (DataOutputStream out = new DataOutputStream(
                new BufferedOutputStream(Files.newOutputStream(path)))) {
            out.write(MAGIC);
            out.writeByte(VERSION);
            out.writeByte(p.columnMajor ? 1 : 0);
            out.writeByte(p.type.dtype.code);
            out.writeByte(p.type.dims.length);
            for (long d : p.type.dims) {
                out.writeLong(d); // u64 big-endian
            }
            for (double v : p.payload) {
                switch (p.type.dtype) {
                    case FLOAT64 -> out.writeLong(
                            Long.reverseBytes(Double.doubleToRawLongBits(v)));
                    case INT64 -> out.writeLong(
                            Long.reverseBytes(Double.doubleToRawLongBits(v) == 0
                                    ? 0L : (long) v));
                    case FLOAT32 -> out.writeInt(
                            Integer.reverseBytes(Float.floatToRawIntBits((float) v)));
                    case BOOL -> out.writeByte(v == 0.0 ? 0 : 1);
                }
            }
        }
    }

    /** Результат чтения TRIOMAT: ядро в row-major + метаданные заголовка. */
    public static final class ReadResult {
        public final double[][] kernel; // row-major нормализация ядра
        public final DType source;
        public final long[] dims;

        ReadResult(double[][] kernel, DType source, long[] dims) {
            this.kernel = kernel;
            this.source = source;
            this.dims = dims;
        }
    }

    /** Читает TRIOMAT-файл, нормализует к row-major ядру (R-DIM7 на границе). */
    public static Conv<ReadResult> readMatrix(Path path) throws IOException {
        byte[] blob = Files.readAllBytes(path);
        if (blob.length < HEADER_SIZE) {
            return err(Variant.ShapeError, "файл короче заголовка");
        }
        for (int i = 0; i < MAGIC.length; i++) {
            if (blob[i] != MAGIC[i]) {
                return err(Variant.UndefinedBridge, "не TRIOMAT-файл");
            }
        }
        int version = blob[8] & 0xFF;
        if (version != VERSION) {
            return err(Variant.UndefinedBridge, "версия " + version);
        }
        int layoutCode = blob[9] & 0xFF;
        if (layoutCode != 0 && layoutCode != 1) {
            return err(Variant.LayoutMismatch, "layout=" + layoutCode);
        }
        boolean columnMajor = layoutCode == 1;
        DType dtype;
        try {
            dtype = DType.byCode(blob[10] & 0xFF);
        } catch (TrioError e) {
            return new ErrConv<>(e);
        }
        int ndim = blob[11] & 0xFF;
        if (ndim > 2) {
            return err(Variant.UndefinedBridge, "ndim > 2 не поддерживается JVM-бриджем v0.1");
        }
        long[] dims = new long[ndim];
        int p = HEADER_SIZE;
        for (int i = 0; i < ndim; i++) {
            long d = 0;
            for (int b = 0; b < 8; b++) {
                d = (d << 8) | (blob[p++] & 0xFFL);
            }
            dims[i] = d;
        }
        long count = 0;
        if (ndim > 0) {
            count = 1;
            for (long d : dims) count *= d;
        }
        if (blob.length != HEADER_SIZE + 8L * ndim + count * dtype.itemSize) {
            return err(Variant.ShapeError, "размер payload не совпадает с заголовком");
        }

        double[] vals = new double[(int) count];
        p = HEADER_SIZE + 8 * ndim;
        for (int k = 0; k < count; k++) {
            switch (dtype) {
                case FLOAT64, INT64 -> {
                    long bits = 0;
                    for (int b = 0; b < 8; b++) {
                        bits |= (blob[p + b] & 0xFFL) << (8 * b);
                    }
                    p += 8;
                    // INT64-пейлоад читается как long и расширяется в double;
                    // значения в пределах 2^53 точны (R-INT2/R-INT3)
                    vals[k] = dtype == DType.INT64 ? (double) bits : Double.longBitsToDouble(bits);
                }
                case FLOAT32 -> {
                    int bits = 0;
                    for (int b = 0; b < 4; b++) {
                        bits |= (blob[p + b] & 0xFF) << (8 * b);
                    }
                    p += 4;
                    vals[k] = Float.intBitsToFloat(bits);
                }
                case BOOL -> vals[k] = blob[p++] == 0 ? 0.0 : 1.0;
            }
        }

        // нормализация к row-major ядру (без лишнего транспонирования)
        double[][] kernel;
        if (ndim == 0) {
            kernel = new double[0][0];
        } else if (ndim == 1) {
            kernel = new double[1][(int) dims[0]];
            for (int i = 0; i < dims[0]; i++) kernel[0][i] = vals[i];
        } else {
            int r = (int) dims[0];
            int c = (int) dims[1];
            kernel = new double[r][c];
            for (int i = 0; i < r; i++) {
                for (int j = 0; j < c; j++) {
                    kernel[i][j] = columnMajor ? vals[j * r + i] : vals[i * c + j];
                }
            }
        }
        return new Ok<>(new ReadResult(kernel, dtype, dims));
    }

    // ---------- Перевод исключений (R-ERR1/2) ----------

    /** Закрытая таблица; неизвестное -> ResourceLost с trusted=false. */
    public static TrioError translate(Throwable t) {
        if (t instanceof TrioError te) return te;
        String name = t.getClass().getSimpleName();
        String msg = name + ": " + t.getMessage();
        switch (name) {
            case "ClassCastException":
                return new TrioError(Variant.TypeMismatch, msg, true);
            case "ArrayIndexOutOfBoundsException":
            case "IndexOutOfBoundsException":
                return new TrioError(Variant.ShapeError, msg, true);
            case "NullPointerException":
                return new TrioError(Variant.NullPointer, msg, true);
            case "IllegalArgumentException":
            case "NumberFormatException":
            case "ArithmeticException":
                return new TrioError(Variant.DomainError, msg, true);
            case "NoSuchElementException":
                return new TrioError(Variant.MissingField, msg, true);
            case "IOException":
            case "FileNotFoundException":
                return new TrioError(Variant.ResourceLost, msg, true);
            default:
                return new TrioError(Variant.ResourceLost, msg, false);
        }
    }

    /** Octave error("...") -> DomainError с текстом. */
    public static TrioError octaveErrorToTrio(String text) {
        return new TrioError(Variant.DomainError, text);
    }
}
