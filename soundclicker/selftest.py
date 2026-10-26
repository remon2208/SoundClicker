"""`SoundClicker.exe --selftest result.json`: quick health check used by CI on the built .exe."""

import json
import os
import tempfile
import threading
import time
import traceback

import numpy as np


def _engine_detects():
    from .engine import SR, FeatureStream, Matcher, load_template, write_wav
    rng = np.random.default_rng(0)
    t = np.arange(int(0.4 * SR)) / SR
    ding = (np.sin(2 * np.pi * 1046 * t) + 0.5 * np.sin(2 * np.pi * 2093 * t)) * np.exp(-t / 0.12)
    ding = (0.5 * ding).astype(np.float32)
    d = tempfile.mkdtemp()
    path = os.path.join(d, "ding.wav")
    write_wav(path, ding)
    tpl = load_template(path, 0.8)
    stream = (rng.standard_normal(SR * 3) * 0.003).astype(np.float32)
    stream[SR:SR + len(ding)] += ding * 0.3
    m, fs, hits = Matcher([tpl], 0.75, -55, 1.0), FeatureStream(), []
    for i in range(0, len(stream), 960):
        hits += m.push(fs.push(stream[i:i + 960]))[1]
    assert len(hits) == 1, hits
    when = hits[0][0] * 480 / SR
    assert 1.0 < when < 1.8, when
    return f"hit at {when:.2f}s, score {hits[0][1]:.2f}"


def _i18n_complete():
    import string
    from .i18n import LANGS, STRINGS
    for key, entry in STRINGS.items():
        ref = {f for _, f, _, _ in string.Formatter().parse(entry["en"]) if f}
        for lang in LANGS:
            assert entry.get(lang), (key, lang)
            assert {f for _, f, _, _ in string.Formatter().parse(entry[lang]) if f} == ref, (key, lang)
    return f"{len(STRINGS)} strings x {len(LANGS)} languages"


def _actions():
    from .actions import describe, parse_keys
    from .i18n import LANGS, set_lang
    assert parse_keys("Ctrl + E") == "ctrl+e"
    out = []
    for lang in LANGS:
        set_lang(lang)
        out.append(describe(dict(type="hold", button=None, keys="ctrl+w", seconds=1.5)))
    set_lang("en")
    return " | ".join(out)


def _inputs():
    from pynput import keyboard, mouse
    mouse.Controller()
    keyboard.Controller()
    __import__("soundcard")
    return "pynput + soundcard import ok"


def _windows():
    from .winaudio import list_windows, window_capture_supported
    ok, why = window_capture_supported()
    wins = list_windows() if ok else []
    return f"window capture supported={ok} {why} windows={len(wins)}"


def _ui():
    import tkinter as tk
    from tkinter import messagebox
    from pynput import keyboard, mouse
    from . import app as appmod
    from .i18n import LANGS
    shown = []
    for name in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, name, lambda *a, _n=name, **k: shown.append((_n, a)))
    appmod.APP_DIR = tempfile.mkdtemp()
    appmod.TPL_DIR = os.path.join(appmod.APP_DIR, "templates")
    appmod.CFG_PATH = os.path.join(appmod.APP_DIR, "settings.json")
    root = tk.Tk()
    a = appmod.App(root, mouse, keyboard)
    t0 = time.time()
    for lang in list(LANGS) + ["en"]:
        a.set_language(lang)
        while time.time() - t0 < 0.5:
            root.update()
            time.sleep(0.02)
        t0 = time.time()
    title = root.title()
    a.on_close()
    return f"built UI in {len(LANGS)} languages, title={title!r}, dialogs={len(shown)}"


def run_selftest(out_path=None):
    results = []
    for name, fn in [("i18n", _i18n_complete), ("engine", _engine_detects), ("actions", _actions),
                     ("inputs", _inputs), ("windows", _windows), ("ui", _ui)]:
        try:
            results.append(dict(name=name, ok=True, info=fn()))
        except Exception:  # noqa: BLE001
            results.append(dict(name=name, ok=False, info=traceback.format_exc()[-1500:]))
    ok = all(r["ok"] for r in results)
    data = dict(ok=ok, results=results, threads=threading.active_count())
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if ok else 1
