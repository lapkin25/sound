# sound_reader.py — ридер .tri: 9 проверок, сводка OK/Lossy/Err
import trio_bridge as tb

def read_file(path_or_bytes):
    data = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) \
        else open(path_or_bytes, 'rb').read()
    results = []

    def add(name, r):
        results.append((name, r))
        return r

    r = add('01 not-empty', tb.OK(len(data)) if data
            else tb.Err('ResourceLost', 'empty'))
    if not r.ok:
        return results
    r = add('02 header-frame', tb.OK() if (len(data) >= 12
            and data[:8] == tb.MAGIC) else tb.Err('MalformedHeader'))
    if not r.ok:
        return results
    import struct, json
    hlen = struct.unpack('<I', data[8:12])[0]
    add('03 hlen-sane', tb.OK() if 0 < hlen <= 4096
        else tb.Err('MalformedHeader', 'hlen'))
    try:
        hdr = json.loads(data[12:12+hlen])
        r = add('04 header-json', tb.OK(hdr) if isinstance(hdr, dict)
                else tb.Err('MalformedHeader'))
    except Exception:
        r = add('04 header-json', tb.Err('MalformedHeader', 'json'))
    if not r.ok:
        return results
    dt = hdr.get('dtype', '')
    r = add('05 dtype-known', tb.OK(dt) if dt in tb._DT2NP
            else tb.Err('MalformedDtype', dt))
    if not r.ok:
        return results
    shape = hdr.get('shape', [])
    r = add('06 shape-ints', tb.OK(shape)
            if all(isinstance(s, int) and s >= 0 for s in shape)
            else tb.Err('MalformedShape'))
    n = 1
    for s in shape:
        n *= s
    payload = data[12+hlen:]
    r = add('07 payload-size', tb.OK()
            if len(payload) == n*tb._DTYPE_SIZE[dt]
            else tb.Err('MalformedPayload'))
    if not r.ok:
        return results
    if dt == 'Bool' and any(b not in (0, 1) for b in payload):
        r = add('08 bool-bytes', tb.Err('TypeMismatch', 'bool bytes'))
    else:
        r = add('08 bool-bytes', tb.OK())
    add('09 decode', tb.read_matrix(data))
    return results

def summary(results):
    return tb.aggregate([r for _, r in results])
