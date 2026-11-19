// TrioBridgeTest.java — тесты JVM-бридга по чек-листу раздела 8 спеки.
// Запуск: javac TrioBridge.java TrioBridgeTest.java && java TrioBridgeTest
// Ожидаемый вывод: все строки PASS, финальная строка вида "N passed, 0 failed".

import java.nio.file.Files;
import java.nio.file.Path;

public class TrioBridgeTest {

    static int passed = 0;
    static int failed = 0;

    static void check(String name, boolean cond) {
        if (cond) {
            passed++;
            System.out.println("PASS " + name);
        } else {
            failed++;
            System.out.println("FAIL " + name);
        }
    }

    static boolean isOk(Object c) { return c instanceof TrioBridge.Ok; }

    static boolean isLossy(Object c) { return c instanceof TrioBridge.Lossy; }

    static boolean isErr(Object c) { return c instanceof TrioBridge.ErrConv; }

    static TrioBridge.Variant variant(Object c) {
        return ((TrioBridge.ErrConv<?>) c).error.variant;
    }

    @SuppressWarnings("unchecked")
    static <T> T value(Object c) {
        return ((TrioBridge.Ok<T>) c).value;
    }

    public static void main(String[] args) throws Exception {
        // ---- R-INT1/2/3: скаляры ----
        check("R-INT1 long->Float64 ok",
                isOk(TrioBridge.convertScalar(10L, TrioBridge.DType.FLOAT64, false)));
        check("R-INT2 2^53 в границе (Lossy repr)",
                isLossy(TrioBridge.convertScalar(9007199254740992L, TrioBridge.DType.INT64, false)));
        check("R-INT2 2^53+1 -> IntRangeOverflow",
                variant(TrioBridge.convertScalar(9007199254740993L, TrioBridge.DType.INT64, false))
                        == TrioBridge.Variant.IntRangeOverflow);
        check("R-INT3 1.0 -> Int64 ok",
                isOk(TrioBridge.convertScalar(1.0, TrioBridge.DType.INT64, false)));
        check("R-INT3 3.5 -> FractionalInt",
                variant(TrioBridge.convertScalar(3.5, TrioBridge.DType.INT64, false))
                        == TrioBridge.Variant.FractionalInt);
        check("R-INT3 NaN -> NaNAsMissing",
                variant(TrioBridge.convertScalar(Double.NaN, TrioBridge.DType.INT64, false))
                        == TrioBridge.Variant.NaNAsMissing);
        check("R-NAN NaN в домене -> ok",
                isOk(TrioBridge.convertScalar(Double.NaN, TrioBridge.DType.INT64, true)));

        // ---- R-FLT1/2/3 ----
        check("R-FLT1 2.5 -> Float32 Lossy precision",
                isLossy(TrioBridge.convertScalar(2.5, TrioBridge.DType.FLOAT32, false)));
        check("R-FLT3 float -> Float64 ok c origin=F32",
                isOk(TrioBridge.convertScalar(2.5f, TrioBridge.DType.FLOAT64, false)));

        // ---- R-BOOL ----
        check("R-BOOL true -> Bool ok",
                isOk(TrioBridge.convertScalar(Boolean.TRUE, TrioBridge.DType.BOOL, false)));
        check("R-BOOL 1.0 -> Bool NoCoercion",
                variant(TrioBridge.convertScalar(1.0, TrioBridge.DType.BOOL, false))
                        == TrioBridge.Variant.NoCoercion);
        check("R-BOOL true -> Float64 NoCoercion",
                variant(TrioBridge.convertScalar(Boolean.TRUE, TrioBridge.DType.FLOAT64, false))
                        == TrioBridge.Variant.NoCoercion);

        // ---- R-STR ----
        check("R-STR обычная строка ok",
                isOk(TrioBridge.convertString("привет")));
        check("R-STR неспаренный суррогат -> EncodingFault",
                isErr(TrioBridge.convertString("bad\uD800tail")));

        // ---- R-DIM5/6/7 ----
        TrioBridge.MType mt = new TrioBridge.MType(TrioBridge.DType.FLOAT64, 3, -1);
        check("R-DIM5 '?' фиксируется первым значением",
                value(mt.check(3, 5)).toString().equals("MType(FLOAT64, [3, 5])"));
        check("R-DIM6 generalize -> '?'",
                mt.generalize(0).toString().equals("MType(FLOAT64, [?, 5])".replace("5", "5")));
        check("R-DIM7 ранг не совпал -> ShapeError",
                variant(mt.check(3)) == TrioBridge.Variant.ShapeError);
        check("R-DIM7 размер не совпал -> ShapeError",
                variant(mt.check(4, 5)) == TrioBridge.Variant.ShapeError);

        // ---- экспорт матриц ----
        double[][] m = {{1, 2, 3}, {4, 5, 6}};
        Object r = TrioBridge.exportToOctave(m, new TrioBridge.MType(TrioBridge.DType.FLOAT64, 2, 3), false, null);
        check("R-MAT экспорт Float64 ok", isOk(r));
        check("R-MAT экспорт Int64 от 9007199254740992.0 ok",
                isOk(TrioBridge.exportToOctave(
                        new double[]{9007199254740992.0}, 1, 1,
                        new TrioBridge.MType(TrioBridge.DType.INT64, 1, 1),
                        TrioBridge.TransferMode.COPY, false, null)));
        check("R-MAT экспорт Int64 от 2^53+2 (double) -> IntRangeOverflow",
                variant(TrioBridge.exportToOctave(
                        new double[]{9007199254740994.0}, 1, 1,
                        new TrioBridge.MType(TrioBridge.DType.INT64, 1, 1),
                        TrioBridge.TransferMode.COPY, false, null))
                        == TrioBridge.Variant.IntRangeOverflow);
        check("R-MAT Float32 -> Lossy precision",
                isLossy(TrioBridge.exportToOctave(m,
                        new TrioBridge.MType(TrioBridge.DType.FLOAT32, 2, 3), false, null)));
        check("R-MAT Bool из 0/1 ok",
                isOk(TrioBridge.exportToOctave(new double[][]{{0, 1}, {1, 0}},
                        new TrioBridge.MType(TrioBridge.DType.BOOL, 2, 2), false, null)));
        check("R-MAT Bool из 2 -> TypeMismatch",
                variant(TrioBridge.exportToOctave(new double[][]{{0, 2}},
                        new TrioBridge.MType(TrioBridge.DType.BOOL, 1, 2), false, null))
                        == TrioBridge.Variant.TypeMismatch);
        check("R-OPT1 сентинел ловится",
                variant(TrioBridge.exportToOctave(new double[][]{{0, -1}},
                        new TrioBridge.MType(TrioBridge.DType.FLOAT64, 1, 2),
                        false, -1.0)) == TrioBridge.Variant.SentinelDetected);

        // ---- TRIOMAT: запись/чтение, все dtype ----
        Path dir = Files.createTempDirectory("triobridge");

        TrioBridge.OctavePayload p64 = value(TrioBridge.exportToOctave(m,
                new TrioBridge.MType(TrioBridge.DType.FLOAT64, 2, 3), false, null));
        TrioBridge.writeMatrix(dir.resolve("f64.triomat"), p64);
        Object back64 = TrioBridge.readMatrix(dir.resolve("f64.triomat"));
        check("TRIOMAT Float64 раундтрип", isOk(back64)
                && TrioBridgeTest.eq(value(back64).kernel, m));

        double[] flatInt = {10, -3, 0, 2};
        TrioBridge.OctavePayload pInt = value(TrioBridge.exportToOctave(flatInt, 2, 2,
                new TrioBridge.MType(TrioBridge.DType.INT64, 2, 2),
                TrioBridge.TransferMode.COPY, false, null));
        TrioBridge.writeMatrix(dir.resolve("int64.triomat"), pInt);
        Object backInt = TrioBridge.readMatrix(dir.resolve("int64.triomat"));
        check("TRIOMAT Int64 раундтрип", isOk(backInt)
                && eq(value(backInt).kernel, new double[][]{{10, -3}, {0, 2}}));

        TrioBridge.OctavePayload pBool = value(TrioBridge.exportToOctave(
                new double[][]{{0, 1}, {1, 0}},
                new TrioBridge.MType(TrioBridge.DType.BOOL, 2, 2), false, null));
        TrioBridge.writeMatrix(dir.resolve("bool.triomat"), pBool);
        Object backBool = TrioBridge.readMatrix(dir.resolve("bool.triomat"));
        check("TRIOMAT Bool раундтрип", isOk(backBool)
                && eq(value(backBool).kernel, new double[][]{{0, 1}, {1, 0}}));

        // col-major: payload в column-major порядке, чтение нормализует к ядру
        double[][] col = {{1, 2}, {3, 4}, {5, 6}}; // 3x2
        double[] colPayload = {1, 3, 5, 2, 4, 6};  // столбцами
        TrioBridge.OctavePayload pCol = new TrioBridge.OctavePayload(colPayload,
                new TrioBridge.MType(TrioBridge.DType.FLOAT64, 3, 2), true,
                TrioBridge.TransferMode.VIEW);
        TrioBridge.writeMatrix(dir.resolve("col.triomat"), pCol);
        Object backCol = TrioBridge.readMatrix(dir.resolve("col.triomat"));
        check("TRIOMAT col-major раундтрип", isOk(backCol)
                && eq(value(backCol).kernel, col));

        // битый файл: 5 байт -> ShapeError
        Path shortFile = dir.resolve("short.triomat");
        Files.write(shortFile, new byte[]{1, 2, 3, 4, 5});
        check("битый файл -> ShapeError",
                isErr(TrioBridge.readMatrix(shortFile))
                        && variant(TrioBridge.readMatrix(shortFile)) == TrioBridge.Variant.ShapeError);

        // не тот magic -> UndefinedBridge
        Path badMagic = dir.resolve("bad.triomat");
        byte[] bad = new byte[32];
        bad[0] = 'X';
        Files.write(badMagic, bad);
        check("чужой magic -> UndefinedBridge",
                variant(TrioBridge.readMatrix(badMagic)) == TrioBridge.Variant.UndefinedBridge);

        // fromOctave: Octave-сторона -> ядро
        Object fo = TrioBridge.fromOctave(new double[][]{{3.0}}, TrioBridge.DType.INT64, false, null);
        check("R-INT3 fromOctave 3.0 -> ok", isOk(fo));
        Object fo2 = TrioBridge.fromOctave(new double[][]{{3.5}}, TrioBridge.DType.INT64, false, null);
        check("R-INT3 fromOctave 3.5 -> FractionalInt",
                variant(fo2) == TrioBridge.Variant.FractionalInt);
        Object fo3 = TrioBridge.fromOctave(new double[][]{{2.5}}, TrioBridge.DType.FLOAT32, false, null);
        check("R-FLT1 fromOctave -> Lossy precision", isLossy(fo3));

        // ---- R-ERR1/2: перевод исключений ----
        check("NPE -> NullPointer (trusted)",
                TrioBridge.translate(new NullPointerException()).variant
                        == TrioBridge.Variant.NullPointer
                && TrioBridge.translate(new NullPointerException()).trusted);
        check("ClassCastException -> TypeMismatch",
                TrioBridge.translate(new ClassCastException("x")).variant
                        == TrioBridge.Variant.TypeMismatch);
        check("RuntimeException -> ResourceLost (trusted=false)",
                TrioBridge.translate(new RuntimeException("x")).variant
                        == TrioBridge.Variant.ResourceLost
                && !TrioBridge.translate(new RuntimeException("x")).trusted);

        System.out.println(passed + " passed, " + failed + " failed");
        if (failed > 0) System.exit(1);
    }

    static boolean eq(double[][] a, double[][] b) {
        if (a.length != b.length) return false;
        for (int i = 0; i < a.length; i++) {
            if (a[i].length != b[i].length) return false;
            for (int j = 0; j < a[i].length; j++) {
                if (Double.doubleToRawLongBits(a[i][j]) != Double.doubleToRawLongBits(b[i][j])) {
                    return false;
                }
            }
        }
        return true;
    }
}
