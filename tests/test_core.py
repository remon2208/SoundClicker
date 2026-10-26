"""Core tests (no GUI, no sound card needed):  python -m pytest -q"""

import string
import threading
import time
import types

import numpy as np
import pytest

from soundclicker import actions, engine, i18n, winaudio
from soundclicker.actions import ActionRunner, describe, format_keys, legacy_steps, parse_keys
from soundclicker.engine import HOP, SR, FeatureStream, Matcher, load_template, write_wav


# ------------------------------------------------------------------ i18n
def test_every_string_has_all_languages_and_same_placeholders():
    for key, entry in i18n.STRINGS.items():
        ref = {f for _, f, _, _ in string.Formatter().parse(entry["en"]) if f}
        for lang in i18n.LANGS:
            assert entry.get(lang), f"{key} is missing {lang}"
            got = {f for _, f, _, _ in string.Formatter().parse(entry[lang]) if f}
            assert got == ref, f"{key}/{lang}: placeholders {got} != {ref}"


def test_language_switch():
    try:
        i18n.set_lang("ja")
        assert i18n.T("tpl_play") == "▶ 再生"
        i18n.set_lang("xx")
        assert i18n.get_lang() == "en"
    finally:
        i18n.set_lang("en")


# ------------------------------------------------------------------ keys and step text
@pytest.mark.parametrize("text,expected", [
    ("Ctrl + E", "ctrl+e"), ("space", "space"), ("shift+tab", "shift+tab"), ("F1", "f1"),
    ("ctrl+shift+a", "ctrl+shift+a"), ("空白", "space"), ("スペース", "space"), ("1", "1"),
])
def test_parse_keys(text, expected):
    assert parse_keys(text) == expected


@pytest.mark.parametrize("bad", ["", "ctrl+", "abc", "a+ctrl", "f8", "ctrl+f8"])
def test_parse_keys_rejects(bad):
    with pytest.raises(ValueError):
        parse_keys(bad)


def test_format_keys():
    assert format_keys("ctrl+shift+a") == "Ctrl + Shift + A"


STEPS = [dict(type="click", button="right", count=2, pos=[300, 400]),
         dict(type="key", keys="ctrl+e"),
         dict(type="hold", button=None, keys="w", seconds=1.5),
         dict(type="hold", button="left", seconds=0.3),
         dict(type="wait", seconds=2.0, jitter=0.5),
         dict(type="move", pos=[10, 20]),
         dict(type="scroll", amount=-3)]


@pytest.mark.parametrize("lang", list(i18n.LANGS))
def test_describe_every_step_in_every_language(lang):
    try:
        i18n.set_lang(lang)
        texts = [describe(s) for s in STEPS]
    finally:
        i18n.set_lang("en")
    assert all(texts) and len(set(texts)) == len(texts)
    assert "300" in texts[0] and "1.5" in texts[2] and "3" in texts[6]


def test_legacy_settings_become_actions():
    steps = legacy_steps(dict(delay=0.5, second_click=True, second_gap=1.5))
    assert [s["type"] for s in steps] == ["wait", "click", "wait", "click"]
    assert steps[0]["seconds"] == 0.5 and steps[2]["seconds"] == 1.5
    assert [s["type"] for s in legacy_steps(dict(second_click=False))] == ["click"]


# ------------------------------------------------------------------ detection engine
def _ding(f0, dur=0.5, decay=0.15):
    t = np.arange(int(dur * SR)) / SR
    y = np.sin(2 * np.pi * f0 * t) + 0.5 * np.sin(2 * np.pi * 2.01 * f0 * t)
    return (y * np.minimum(1, t / 0.005) * np.exp(-t / decay) * 0.5).astype(np.float32)


def _scan(stream, templates, threshold=0.75):
    m, fs, hits = Matcher(templates, threshold, -55, 1.0), FeatureStream(), []
    for i in range(0, len(stream), 960):
        hits += m.push(fs.push(stream[i:i + 960]))[1]
    return [(h[0] * HOP / SR, h[1], h[2]) for h in hits]


def test_detects_the_template_and_ignores_a_different_sound(tmp_path):
    path = tmp_path / "ding.wav"
    write_wav(str(path), _ding(1046))
    tpl = load_template(str(path), 0.8)
    rng = np.random.default_rng(1)
    stream = (rng.standard_normal(SR * 6) * 0.003).astype(np.float32)
    for t, f in ((1.0, 1046), (3.0, 784), (4.5, 1046)):      # target, other pitch, target
        clip = _ding(f) * 0.4
        stream[int(t * SR):int(t * SR) + len(clip)] += clip
    hits = _scan(stream, [tpl])
    times = [round(h[0], 1) for h in hits]
    assert len(hits) == 2, hits
    assert 1.0 < times[0] < 1.8 and 4.5 < times[1] < 5.3
    assert all(h[2] == "ding.wav" for h in hits)


def test_silence_never_triggers(tmp_path):
    path = tmp_path / "ding.wav"
    write_wav(str(path), _ding(1046))
    tpl = load_template(str(path), 0.8)
    assert _scan(np.zeros(SR * 3, np.float32), [tpl]) == []


# ------------------------------------------------------------------ action runner
class _Log(list):
    def add(self, *a):
        self.append((time.time(), a))


def _fake_inputs(log):
    class Mouse:
        position = (0, 0)

        def click(self, b, n=1):
            log.add("click", b, n)

        def press(self, b):
            log.add("mdown", b)

        def release(self, b):
            log.add("mup", b)

        def scroll(self, dx, dy):
            log.add("scroll", dy)

    class Kb:
        def press(self, k):
            log.add("kdown", k)

        def release(self, k):
            log.add("kup", k)

    mouse = types.SimpleNamespace(Controller=Mouse,
                                  Button=types.SimpleNamespace(left="L", right="R", middle="M"))
    key = types.SimpleNamespace(ctrl="CTRL", space="SPACE")
    keyboard = types.SimpleNamespace(Controller=Kb, Key=key,
                                     KeyCode=types.SimpleNamespace(from_char=lambda c: c))
    return mouse, keyboard


def test_runner_order_and_timing():
    log = _Log()
    r = ActionRunner(*_fake_inputs(log))
    ok = r.run([dict(type="click", button="left", count=1, pos=None),
                dict(type="key", keys="ctrl+e"),
                dict(type="wait", seconds=0.3, jitter=0),
                dict(type="hold", button=None, keys="space", seconds=0.2),
                dict(type="scroll", amount=2)], threading.Event())
    assert ok
    seq = [a for _, a in log]
    assert seq == [("click", "L", 1), ("kdown", "CTRL"), ("kdown", "e"), ("kup", "e"), ("kup", "CTRL"),
                   ("kdown", "SPACE"), ("kup", "SPACE"), ("scroll", 2)]
    t = {a: ts for ts, a in log}
    assert 0.28 <= t[("kdown", "SPACE")] - t[("kup", "CTRL")] <= 0.45
    assert 0.18 <= t[("kup", "SPACE")] - t[("kdown", "SPACE")] <= 0.35


def test_cancel_releases_a_held_key_immediately():
    log = _Log()
    r = ActionRunner(*_fake_inputs(log))
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()
    t0 = time.time()
    assert r.run([dict(type="hold", button=None, keys="space", seconds=5.0)], cancel) is False
    assert time.time() - t0 < 0.6
    assert [a for _, a in log] == [("kdown", "SPACE"), ("kup", "SPACE")]


# ------------------------------------------------------------------ one-window capture helpers
def test_resampler_chunks_join_seamlessly():
    rs = winaudio._LinearResampler(44100, 48000)
    sig = np.sin(np.arange(44100) / 9.0).astype(np.float32)
    rng = np.random.default_rng(2)
    out, i = [], 0
    while i < len(sig):
        n = int(rng.integers(30, 900))
        out.append(rs(sig[i:i + n]))
        i += n
    out = np.concatenate(out)
    ref = np.interp(np.arange(len(out)) * 44100 / 48000, np.arange(len(sig)), sig)
    assert abs(len(out) - 48000) <= 2
    assert np.max(np.abs(out - ref)) < 1e-5


def test_window_recorder_fills_silence_in_real_time():
    p = winaudio.ProcessLoopback(1)
    p.event = 1
    p.k32 = types.SimpleNamespace(WaitForSingleObject=lambda ev, ms: time.sleep(ms / 1000))
    p._drain = lambda: None                      # the app makes no sound
    t0 = time.time()
    blocks = [p.record(960) for _ in range(25)]
    dt = time.time() - t0
    assert all(b.shape == (960, 1) and not b.any() for b in blocks)
    assert 0.4 <= dt <= 0.75, dt                 # 25 x 20 ms


def test_engine_constants_consistent():
    assert engine.SR % HOP == 0 and actions.HOTKEY == "f8"
