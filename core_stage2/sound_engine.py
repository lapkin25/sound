# sound_engine.py - единый звуковой движок SCore
# Один словарь событий, один синтезатор, два профиля.
# Событие: {kind, node, runtime, lossy}. Контракт финиша един: старт * FINISH_RATIO.
# Профили различаются ТОЛЬКО таблицей частот рантаймов:
#   live      - живая партитура: ля-минорное трезвучие (python 440, java 523.25, octave 659.25);
#   rehearsal - репетиция: октавная лестница (octave 110, java 220, python 440, факты 880).
# README-паритет: lossy-конверсия и resource_lost - настоящие события, не обещания.
import math, wave, struct

SR = 44100
ATTACK = 0.008        # атака 8 мс
GAP = 0.020           # зазор 20 мс между нотами
PEAK = 0.9            # нормализация пика всего трека
FINISH_RATIO = 1.2    # финиш = старт * 1.2 (чистая малая терция 6/5)

RUNTIME_FREQ = {
    'live':      {'octave': 659.25, 'java': 523.25, 'python': 440.0, 'fact': None},
    'rehearsal': {'octave': 110.0, 'java': 220.0, 'python': 440.0, 'fact': 880.0},
}
EVENT_FREQ = {'edge_error': 150.0, 'node_error': 110.0,
              'config_error': 120.0, 'resource_lost': 130.81, 'success': 880.0}
DUR = {'node_start': 0.18, 'node_finish': 0.12, 'edge_error': 0.25,
       'node_error': 0.25, 'config_error': 0.25, 'resource_lost': 0.08,
       'invariant_ok': 0.5, 'success': 0.4}

def make_event(kind, node=None, runtime=None, lossy=False):
    if kind not in DUR:
        raise ValueError('unknown event kind: %r' % kind)
    return {'kind': kind, 'node': node, 'runtime': runtime, 'lossy': lossy}

def describe(ev, profile='live'):
    k = ev['kind']
    if k in ('node_start', 'node_finish'):
        f = RUNTIME_FREQ[profile].get(ev['runtime'])
        if f is None:
            return '[SOUND] %s %s (факт, в профиле %s не звучит)' % (k, ev['node'], profile)
        if k == 'node_finish':
            f = f * FINISH_RATIO
        word = 'start' if k == 'node_start' else 'finish'
        return '[SOUND] %s %s %s @ %.2f Hz' % (word, ev['runtime'], ev['node'], f)
    if k == 'edge_error':
        return '[SOUND] error edge @ %.1f Hz%s' % (EVENT_FREQ[k],
                ' (lossy)' if ev.get('lossy') else '')
    if k == 'invariant_ok':
        return '[SOUND] invariant chord @ 440.0+660.0 Hz'
    if k == 'resource_lost':
        return '[SOUND] resource lost @ %.2f Hz' % EVENT_FREQ[k]
    return '[SOUND] %s @ %.1f Hz' % (k, EVENT_FREQ[k])

def _tone(freq, dur, amp=1.0, abrupt=False, chord=None):
    n = int(round(dur * SR))
    if chord:
        freqs, amps = chord, [0.35] * len(chord)
    else:
        freqs, amps = [freq], [amp]
    out = [0.0] * n
    for f, a in zip(freqs, amps):
        for i in range(n):
            t = i / SR
            env = 1.0 if abrupt else min(1.0, t / ATTACK) * math.exp(-4.0 * t / dur)
            out[i] += a * env * math.sin(2.0 * math.pi * f * t)
    return out

def render(events, profile):
    chunks = []
    for ev in events:
        k = ev['kind']
        f = None
        if k in ('node_start', 'node_finish'):
            f = RUNTIME_FREQ[profile].get(ev['runtime'])
            if f is None:
                continue          # событие в журнале есть, в этом профиле не звучит
            if k == 'node_finish':
                f = f * FINISH_RATIO
        elif k != 'invariant_ok':  # инварианты играют аккордом, частота не нужна
            f = EVENT_FREQ[k]
        amp = 0.35 if (k == 'edge_error' and ev.get('lossy')) else 1.0
        abrupt = (k == 'resource_lost')
        if k == 'invariant_ok':
            chunks.append(_tone(0.0, DUR[k], chord=[440.0, 660.0]))
        else:
            chunks.append(_tone(f, DUR[k], amp, abrupt=abrupt))
        chunks.append([0.0] * int(round(GAP * SR)))
    data = [s for c in chunks for s in c]
    peak = max((abs(s) for s in data), default=0.0)
    if peak > 0:
        data = [s * (PEAK / peak) for s in data]
    return data

def write_wav(path, data):
    with wave.open(path, 'w') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b''.join(struct.pack('<h',
            int(max(-1.0, min(1.0, s)) * 32767)) for s in data))

class SoundEngine:
    def __init__(self):
        self.events = []
    def add(self, kind, **kw):
        self.events.append(make_event(kind, **kw))
        return self.events[-1]
    def log(self, profile='live'):
        return [describe(e, profile) for e in self.events]
    def render_to(self, path, profile):
        write_wav(path, render(self.events, profile))
        return path

if __name__ == '__main__':
    evs = [make_event('node_start', node='flight_range', runtime='python'),
           make_event('node_finish', node='flight_range', runtime='python'),
           make_event('node_start', node='hypotenuse', runtime='java'),
           make_event('node_finish', node='hypotenuse', runtime='java'),
           make_event('edge_error', lossy=True),
           make_event('node_error'),
           make_event('config_error'),
           make_event('resource_lost'),
           make_event('invariant_ok'),
           make_event('success')]
    for line in [describe(e) for e in evs]:
        print(line)
    for prof in ('live', 'rehearsal'):
        data = render(evs, prof)
        peak = max(abs(s) for s in data)
        print('%s: %d samples, %.3f s, peak %.3f' % (prof, len(data), len(data)/SR, peak))
