# sound_all.py - сборка всех слоёв Sound в один след и стековый манифест
# Запуск: python3 sound_all.py   (в папке со всеми файлами стека)
#
# Жанр: каждый слой самопроверяется своим сценарием; сборка запускает их
# подряд - один непрерывный след - и завершает манифестом: sha256 каждого
# файла и цепочный отпечаток стека, посчитанный как цепочка журнала.

import json, hashlib, struct
import sound_snap2
import ledger
import accounting
import report


def _H(d):
    # num2hex в Octave: 16 hex-цифр big-endian
    return struct.pack('>d', d).hex()


def _bits2double_oct(h16):
    # путь Octave: big-endian hex -> uint64 -> байты от младшего -> typecast
    t = h16[2:] if h16.startswith('0x') else h16
    u = int(t, 16)
    le = bytes((u >> (8 * k)) & 255 for k in range(8))
    return struct.unpack('<d', le)[0]


def octave_mirror():
    """Звено 4: кросс-хост - зеркало точного пути Octave-раннера.
    sprintf-формат строк, little-endian typecast-путь битов, независимый
    счётчик t-биндов. Успех = журнал B продолжен посимвольно и last сошёлся."""
    A = json.load(open('snap_A.json', encoding='utf-8'))
    B = json.load(open('snap_B.json', encoding='utf-8'))
    ja, jb = A['journal'], B['journal']
    n0 = len(ja)
    v = _bits2double_oct(A['names']['x'])
    jrn = list(ja)
    for k in range(15):
        q = 2.0 / v
        n0 += 1; jrn.append('t%d /(%s,%s) -> %s' % (n0, _H(2.0), _H(v), _H(q)))
        sm = v + q
        n0 += 1; jrn.append('t%d +(%s,%s) -> %s' % (n0, _H(v), _H(q), _H(sm)))
        r = sm / 2.0
        n0 += 1; jrn.append('t%d /(%s,%s) -> %s' % (n0, _H(sm), _H(2.0), _H(r)))
        v = r
    okj = (len(jrn) == len(jb)) and all(a == b for a, b in zip(jrn, jb))
    okl = _H(v) == B['last']
    edges_ok = all(_H(_bits2double_oct(_H(e))) == _H(e)
                   for e in (-2.0, 0.0, -0.0, float('nan')))
    print('  зеркало Octave-пути: журнал %s, last %s, края %s'
          % (okj, okl, 'ок' if edges_ok else 'FAIL'))
    return okj and okl and edges_ok


def manifest():
    files = ['sound_snap2.py', 'ledger.py', 'accounting.py', 'report.py',
             'replay_octave.m', 'sound_all.py']
    print('== Манифест стека: цепочка ответственности слоёв ==')
    chain = '0' * 64
    rows = []
    for f in files:
        h = hashlib.sha256(open(f, 'rb').read()).hexdigest()
        rows.append({'file': f, 'sha256': h})
        print('  %-18s %s' % (f, h))
        chain = hashlib.sha256((chain + f + ':' + h).encode()).hexdigest()
    print('  стековый отпечаток: %s' % chain)
    with open('sound_manifest.json', 'w', encoding='utf-8') as fo:
        json.dump({'files': rows, 'stack_fingerprint': chain}, fo,
                  ensure_ascii=False, indent=1)
    print('  манифест записан: sound_manifest.json')
    return chain


def main():
    print('================ СЛЕД ВСЕГО СТЕКА ================')
    r = {}
    print('== Звенья 1-3: ядро + слой WL + снапшоты ==')
    r['snap'] = sound_snap2.scenario()
    print('== Звено 4: кросс-хост (зеркало Octave-пути) ==')
    r['mirror'] = octave_mirror()
    print('== Звено 5: регистры ==')
    r['reg'] = ledger.scenario()
    print('== Звено 6: двойная запись ==')
    r['acc'] = accounting.scenario()
    print('== Звено 7: отчёт ==')
    r['rep'] = report.scenario()
    chain = manifest()
    print('==================================================')
    ok = all(r.values())
    print('СТЕК ЦЕЛИКОМ: %s' % ('ALL PASS' if ok else 'FAILED'))
    print('стековый отпечаток: %s' % chain)
    return ok


if __name__ == '__main__':
    main()
