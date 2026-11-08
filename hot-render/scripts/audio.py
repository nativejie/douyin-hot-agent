"""背景音乐和转场音效，纯 Python 标准库合成（不用 numpy）。由 render.py 调用。

音乐：120 BPM、4 小节循环（Am - F - C - G），底鼓 + 拍手 + 闭镲 + 反拍贝斯 + 八分音符拨弦。
每拍 0.5 秒，所以停留整数秒或半秒的屏，切换正好落在拍子上。
音效：每次切屏前一点点一个轻的「嗖」，两个音效之间至少隔 1.5 秒、每分钟不超过 30 个。
"""
import math, random, struct, wave
from array import array

SR = 44100
BPM = 120
BEAT = 60 / BPM


def _add(buf, start, samples, gain=1.0):
    i0 = int(start * SR)
    for j, x in enumerate(samples):
        k = i0 + j
        if 0 <= k < len(buf):
            buf[k] += x * gain


def _kick():
    n, out, ph = int(.32 * SR), [], 0.0
    for i in range(n):
        t = i / SR
        f = 45 + 80 * math.exp(-t / .03)
        ph += 2 * math.pi * f / SR
        out.append(math.sin(ph) * math.exp(-t / .13))
    return out


def _noise_hit(dur, tau, hp=True, rnd=None):
    rnd = rnd or random.Random(1)
    n, out, prev = int(dur * SR), [], 0.0
    for i in range(n):
        x = rnd.uniform(-1, 1)
        y = (x - prev) if hp else x
        prev = x
        out.append(y * math.exp(-(i / SR) / tau))
    return out


def _tone(freqs, dur, tau, attack=.005, harm=.3):
    n, out = int(dur * SR), []
    for i in range(n):
        t = i / SR
        env = min(1, t / attack) * math.exp(-t / tau)
        s = sum(math.sin(2 * math.pi * f * t) + harm * math.sin(4 * math.pi * f * t) for f in freqs) / len(freqs)
        out.append(s * env)
    return out


# 和弦：贝斯根音 + 拨弦用的四个音
CHORDS = [
    (55.00, [440.00, 523.25, 659.25, 523.25]),   # Am
    (43.65, [349.23, 440.00, 523.25, 440.00]),   # F
    (65.41, [392.00, 523.25, 659.25, 523.25]),   # C
    (49.00, [392.00, 493.88, 587.33, 493.88]),   # G
]


def music_bed(seconds):
    """返回 [-1,1] 的浮点列表，长度 seconds。"""
    bar = 4 * BEAT
    loop = [0.0] * int(4 * bar * SR)
    kick, rnd = _kick(), random.Random(7)
    clap = _noise_hit(.18, .05, hp=False, rnd=rnd)
    hat = _noise_hit(.05, .012, rnd=rnd)
    for b, (root, arp) in enumerate(CHORDS):
        t0 = b * bar
        bass = _tone([root * 2], BEAT * .9, .22, attack=.01, harm=.5)
        for beat in range(4):
            tb = t0 + beat * BEAT
            _add(loop, tb, kick, .85)
            _add(loop, tb + BEAT / 2, hat, .16)
            _add(loop, tb + BEAT / 2, bass, .32)
            if beat in (1, 3):
                _add(loop, tb, clap, .22)
        for k in range(8):
            _add(loop, t0 + k * BEAT / 2, _tone([arp[k % 4]], .3, .11), .09)
    n = int(seconds * SR)
    out = [loop[i % len(loop)] for i in range(n)]
    fade_in, fade_out = int(.05 * SR), int(min(1.5, seconds / 4) * SR)
    for i in range(min(fade_in, n)):
        out[i] *= i / fade_in
    for i in range(min(fade_out, n)):
        out[n - 1 - i] *= i / fade_out
    return [math.tanh(1.2 * x) for x in out]


def _whoosh(rnd):
    dur = .36
    n, out, lp = int(dur * SR), [], 0.0
    for i in range(n):
        t = i / SR
        x = rnd.uniform(-1, 1)
        u = t / dur
        cutoff = 300 + 5000 * math.sin(math.pi * u) ** 2      # 截止频率先升后降
        a = 1 - math.exp(-2 * math.pi * cutoff / SR)
        lp += a * (x - lp)
        out.append(lp * math.sin(math.pi * u) ** 1.5)
    return out


def sfx_track(seconds, cuts, min_gap=1.5, per_min=30):
    """cuts：切屏时刻（秒）。音效在切屏前 0.2 秒起、切屏那一刻最响。"""
    buf = [0.0] * int(seconds * SR)
    rnd = random.Random(11)
    kept, last = [], -99
    for c in sorted(cuts):
        if c - last < min_gap:
            continue
        if len([k for k in kept if c - k < 60]) >= per_min:
            continue
        kept.append(c)
        last = c
        _add(buf, max(0, c - .2), _whoosh(rnd), .5)
    return buf, kept


def write_wav(path, samples):
    peak = max(1e-9, max(abs(x) for x in samples))
    g = .89 / peak if peak > .89 else 1.0
    data = array("h", (int(max(-1, min(1, x * g)) * 32767) for x in samples))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def mix(a, b, ga=1.0, gb=1.0):
    n = max(len(a), len(b))
    return [(a[i] if i < len(a) else 0) * ga + (b[i] if i < len(b) else 0) * gb for i in range(n)]
