"""Sound detection engine: features, template matching, audio file I/O, audio devices."""

import os
import queue
import threading
import warnings
import wave

import numpy as np

from .i18n import T

SR = 48000          # internal sample rate
N_FFT = 2048        # analysis window (~43 ms)
HOP = 480           # one spectrum frame every 10 ms
N_MELS = 64
FMIN, FMAX = 60.0, 16000.0
DYN_RANGE = 60.0    # only the top 60 dB matter; anything quieter is treated as floor
FLOOR_DB = -100.0
MASK_DB = 20.0      # a template's "main energy": within 20 dB of its peak
BASE_W = 0.03       # weight of the rest, so background music hurts the score less
TRIM_DB = 30.0      # auto-trim: keep what is within 30 dB of the peak
MAX_SAVE_LEN = 3.0  # longest template we save (seconds)


def _mel_filterbank(sr=SR, n_fft=N_FFT, n_mels=N_MELS, fmin=FMIN, fmax=FMAX):
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    hz = mel2hz(np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2))
    fb = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for i in range(n_mels):
        lo, ce, hi = hz[i], hz[i + 1], hz[i + 2]
        up = (freqs - lo) / max(ce - lo, 1e-9)
        down = (hi - freqs) / max(hi - ce, 1e-9)
        fb[i] = np.maximum(0, np.minimum(up, down))
        if fb[i].sum() == 0:
            fb[i, np.argmin(np.abs(freqs - ce))] = 1.0
    return fb


_WINDOW = np.hanning(N_FFT).astype(np.float32)
_WSUM = float(_WINDOW.sum())
_MELFB = _mel_filterbank()


def frames_to_feat(frames):
    spec = np.fft.rfft(frames * _WINDOW, axis=1) * (2.0 / _WSUM)
    power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
    mel = power @ _MELFB.T
    return np.maximum(10.0 * np.log10(mel + 1e-12), FLOOR_DB).astype(np.float32)


class FeatureStream:
    """Turns a continuous audio stream into 10 ms mel-spectrum frames."""

    def __init__(self):
        self.buf = np.zeros(N_FFT - HOP, dtype=np.float32)

    def push(self, samples):
        self.buf = np.concatenate([self.buf, samples.astype(np.float32)])
        if len(self.buf) < N_FFT:
            return np.zeros((0, N_MELS), dtype=np.float32)
        n = 1 + (len(self.buf) - N_FFT) // HOP
        idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]
        feats = frames_to_feat(self.buf[idx])
        self.buf = self.buf[n * HOP:]
        return feats


def audio_to_feat(x):
    return FeatureStream().push(np.concatenate([x, np.zeros(N_FFT, dtype=np.float32)]))


def _shape(win):
    c = np.maximum(win, win.max() - DYN_RANGE)
    x = 0.25 * np.roll(c, 1, axis=1) + 0.5 * c + 0.25 * np.roll(c, -1, axis=1)
    x[:, 0] = c[:, 0]
    x[:, -1] = c[:, -1]
    return x


def prep_template(feat):
    w = (feat >= feat.max() - MASK_DB).astype(np.float32) + BASE_W
    w /= w.sum()
    x = _shape(feat)
    z = x - (w * x).sum()
    norm = np.sqrt((w * z * z).sum())
    if norm < 1e-6:
        return None
    return dict(w=w.ravel(), wz=(w * z).ravel() / norm)


def score_window(win, tp):
    x = _shape(win).ravel()
    w = tp["w"]
    mean = w @ x
    var = w @ (x * x) - mean * mean
    if var < 1e-6:
        return 0.0
    return float(tp["wz"] @ x) / np.sqrt(var)


def trim_event(x, trim_db=TRIM_DB, max_len=0.8):
    """Finds the loudest event in a recording and trims the quiet parts around it."""
    hop = 240
    n = len(x) // hop
    if n == 0:
        return x
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    peak = int(np.argmax(db))
    gate = db[peak] - trim_db
    max_gap = int(0.15 / (hop / SR))
    start = end = peak
    for step, edge in ((-1, 0), (1, n - 1)):
        i, gap = peak, 0
        while i != edge and gap <= max_gap:
            i += step
            if db[i] >= gate:
                gap = 0
                if step < 0:
                    start = i
                else:
                    end = i
            else:
                gap += 1
    s = max(0, start * hop - hop * 2)
    e = min(len(x), (end + 1) * hop + hop * 2)
    seg = x[s:e]
    if max_len and len(seg) > int(max_len * SR):
        seg = seg[: int(max_len * SR)]
    return seg


def resample(x, sr_in, sr_out=SR):
    if sr_in == sr_out or len(x) == 0:
        return x.astype(np.float32)
    try:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(sr_in), int(sr_out))
        return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)
    except ImportError:
        t_out = np.arange(int(len(x) * sr_out / sr_in)) / sr_out
        return np.interp(t_out, np.arange(len(x)) / sr_in, x).astype(np.float32)


def read_audio(path):
    """Reads an audio file as mono float32 at 48 kHz. WAV always works; ogg/flac/mp3 need `soundfile`."""
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        x = data.mean(axis=1)
    except ImportError:
        with wave.open(path, "rb") as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw == 1:
            x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
        elif sw == 2:
            x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
        elif sw == 3:
            b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
            v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
                 | (b[:, 2].astype(np.int32) << 16))
            v = np.where(v >= 1 << 23, v - (1 << 24), v)
            x = v.astype(np.float32) / (1 << 23)
        elif sw == 4:
            x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648
        else:
            raise ValueError(T("err_wav_format"))
        x = x.reshape(-1, ch).mean(axis=1)
    return resample(x, sr)


def write_wav(path, x, sr=SR):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def load_template(path, max_len):
    x = trim_event(read_audio(path), TRIM_DB, max_len)
    feat = audio_to_feat(x)[: max(5, int(np.ceil(len(x) / HOP)))]
    tp = prep_template(feat)
    if tp is None or feat.max() < -80:
        raise ValueError(T("err_template_silent", name=os.path.basename(path)))
    return dict(name=os.path.basename(path), path=path, tp=tp, frames=len(feat), dur=len(x) / SR)


class Matcher:
    def __init__(self, templates, threshold, min_db, cooldown):
        self.tpls = templates
        self.threshold = threshold
        self.min_db = min_db
        self.cooldown_frames = int(cooldown * SR / HOP)
        self.maxT = max(t["frames"] for t in templates)
        self.hist = np.full((self.maxT, N_MELS), FLOOR_DB, dtype=np.float32)
        self.filled = 0
        self.frame_no = 0
        self.last_hit = -10 ** 9

    def push(self, feats):
        scores, hits = [], []
        for f in feats:
            self.hist[:-1] = self.hist[1:]
            self.hist[-1] = f
            self.filled += 1
            self.frame_no += 1
            best, best_t = 0.0, None
            for t in self.tpls:
                T = t["frames"]
                if self.filled < T:
                    continue
                win = self.hist[-T:]
                if win.max() < self.min_db:
                    continue
                s = score_window(win, t["tp"])
                if s > best:
                    best, best_t = s, t
            scores.append(best)
            if (best >= self.threshold
                    and self.frame_no - self.last_hit >= self.cooldown_frames):
                self.last_hit = self.frame_no
                hits.append((self.frame_no, best, best_t["name"], best_t["path"]))
        return scores, hits


# ------------------------------------------------------------------ audio devices
def list_inputs(sc):
    try:
        spk = sc.default_speaker().name
    except Exception:
        spk = None
    out = []
    for m in sc.all_microphones(include_loopback=True):
        loop = bool(getattr(m, "isloopback", False))
        out.append(dict(name=m.name, loop=loop, default=loop and m.name == spk))
    out.sort(key=lambda d: (not d["default"], not d["loop"]))
    return out


def find_input(sc, name, loop):
    mics = list(sc.all_microphones(include_loopback=True))
    for m in mics:
        if m.name == name and bool(getattr(m, "isloopback", False)) == loop:
            return m, False
    try:
        return sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True), True
    except Exception:
        if mics:
            return mics[0], True
    raise RuntimeError(T("err_no_device"))


class AudioService(threading.Thread):
    """Every sound-card call happens on this one thread (COM threading rules on Windows)."""

    def __init__(self, post):
        super().__init__(daemon=True)
        self.post = post
        self.tasks = queue.Queue()

    def submit(self, fn):
        self.tasks.put(fn)

    def run(self):
        try:
            import soundcard as sc
        except Exception as e:  # noqa: BLE001
            self.post(("fatal", T("err_soundcard") + "\n\n" + str(e)))
            return
        warnings.filterwarnings("ignore", message=".*data discontinuity.*")
        while True:
            fn = self.tasks.get()
            try:
                fn(sc)
            except Exception as e:  # noqa: BLE001
                self.post(("error", f"{type(e).__name__}: {e}"))
