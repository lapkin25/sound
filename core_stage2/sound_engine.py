
# sound_engine.py - unified SCore engine: one vocabulary, one synthesizer.
# Replaces the two divergent implementations (compiler rehearsal + executor
# live score) with a single code path selected by profile.
#
#   rehearsal - compiler pre-play: runtimes on the octave ladder
#               (octave 110, java 220, python 440, fact 880);
#   live      - executor session: A4/C5/E5 triad by runtime (440/523.25/659.25).
#
# Signals shared by both profiles: edge_error 150 Hz, node_error 110 Hz,
# config_error 120 Hz, resource_lost 130.81 Hz (new), success 880 Hz,
# invariant chord 440+660 Hz (pure fifth, muted 0.35).
# Finish note = start * 1.2 (minor third above) - unified contract.
#
# README parity: lossy-edge and resource-lost events are now REAL events,
# not unimplemented claims. Synthesis: attack 8 ms, exponential decay,
# 20 ms gaps, peak normalized to 0.9, mono WAV 44.1 kHz 16-bit.

import numpy as np, wave

SAMPLE_RATE = 44100
ATTACK = 0.008
GAP    = 0.020

RUNTIME_NOTES = {
    "rehearsal": {"octave": 110.0, "java": 220.0, "python": 440.0, "fact": 880.0},
    "live":      {"python": 440.0, "java": 523.25, "octave": 659.25},
}
SIGNAL_NOTES = {
    "edge_error": 150.0, "node_error": 110.0, "config_error": 120.0,
    "resource_lost": 130.81, "success": 880.0,
}
FINISH_RATIO = 1.2
INVARIANT_CHORD = (440.0, 660.0)
INVARIANT_AMP = 0.35

def make_event(kind, node="", runtime=None):
    """Unified event: the only shape the engine accepts."""
    return {"kind": kind, "node": node, "runtime": runtime}

def note_for(ev, profile):
    kind = ev["kind"]
    if kind == "node_start":
        f = RUNTIME_NOTES[profile]["fact" if ev["runtime"] == "fact" else ev["runtime"]]
        return f, 0.25, 0.9
    if kind == "node_finish":
        return RUNTIME_NOTES[profile][ev["runtime"]] * FINISH_RATIO, 0.12, 0.55
    if kind == "invariant_ok":
        return None, 0.0, INVARIANT_AMP
    if kind in SIGNAL_NOTES:
        return SIGNAL_NOTES[kind], 0.30, 0.9
    raise ValueError(f"unknown event kind: {kind!r}")

class SoundEngine:
    def __init__(self, profile="live"):
        if profile not in RUNTIME_NOTES:
            raise ValueError(f"profile must be one of {sorted(RUNTIME_NOTES)}")
        self.profile = profile

    def render(self, events):
        chunks = []
        for ev in events:
            f, dur, amp = note_for(ev, self.profile)
            if ev["kind"] == "invariant_ok":
                n = int(0.5 * SAMPLE_RATE)
                chord = sum(_tone(fc, 0.5, 1.0) for fc in INVARIANT_CHORD)
                chunks.append(INVARIANT_AMP * chord * 2 / len(INVARIANT_CHORD))
            elif ev["kind"] == "resource_lost":
                n = int(0.10 * SAMPLE_RATE)          # abrupt cut, no tail
                t = np.arange(n) / SAMPLE_RATE
                env = np.ones(n); env[:int(ATTACK*SAMPLE_RATE)] = \
                    np.linspace(0.0, 1.0, int(ATTACK*SAMPLE_RATE))
                chunks.append(0.9 * np.sin(2*np.pi*f*t) * env)
            else:
                chunks.append(_tone(f, dur, amp))
            chunks.append(_silence(GAP))
        x = np.concatenate(chunks) if chunks else _silence(0.05)
        peak = np.max(np.abs(x)) or 1.0
        return (0.9 * x / peak * 32767).astype("<i2").tobytes(), len(x)/SAMPLE_RATE

    def write_wav(self, path, events):
        pcm, seconds = self.render(events)
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm)
        return seconds

def _tone(freq, dur, amp=0.9):
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    w = np.sin(2*np.pi*freq*t)
    env = np.ones(n); na = max(1, int(ATTACK*SAMPLE_RATE))
    env[:na] = np.linspace(0.0, 1.0, na)
    env[na:] = np.exp(-4.0*(t[na:] - ATTACK)/max(dur-ATTACK, 1e-9))
    return amp * w * env

def _silence(dur):
    return np.zeros(int(dur * SAMPLE_RATE))

def log_line(ev, profile):
    f, _, _ = note_for(ev, profile)
    if ev["kind"] == "invariant_ok":
        return "[SCORE] invariant chord @ 440+660 Hz (pure fifth)"
    return f"[SCORE] {ev['kind']} @ {f:.2f} Hz"
