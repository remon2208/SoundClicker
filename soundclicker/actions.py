"""What to do after a sound is detected: action steps, key parsing and the step runner."""

import random
import re
import sys

from .i18n import T

STEP_TYPES = ("click", "key", "hold", "wait", "move", "scroll")
MOUSE_BUTTONS = ("left", "right", "middle")

KEY_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt",
    "win": "cmd", "windows": "cmd", "cmd": "cmd",
    "enter": "enter", "return": "enter", "space": "space", "空白": "space", "空白鍵": "space",
    "スペース": "space",
    "tab": "tab", "esc": "esc", "escape": "esc", "backspace": "backspace",
    "delete": "delete", "del": "delete", "insert": "insert", "ins": "insert",
    "home": "home", "end": "end",
    "pageup": "page_up", "page_up": "page_up", "pgup": "page_up",
    "pagedown": "page_down", "page_down": "page_down", "pgdn": "page_down",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "↑": "up", "↓": "down", "←": "left", "→": "right",
    "capslock": "caps_lock", "caps_lock": "caps_lock",
}
for _i in range(1, 21):
    KEY_ALIASES[f"f{_i}"] = f"f{_i}"
MODIFIERS = ("ctrl", "shift", "alt", "cmd")
KEY_LABEL = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "cmd": "Win", "enter": "Enter",
             "space": "Space", "tab": "Tab", "esc": "Esc", "backspace": "Backspace",
             "delete": "Delete", "insert": "Insert", "home": "Home", "end": "End",
             "page_up": "PageUp", "page_down": "PageDown", "up": "↑", "down": "↓",
             "left": "←", "right": "→", "caps_lock": "CapsLock"}
HOTKEY = "f8"   # global start/stop hotkey; actions may not use it

DEFAULT_STEPS = [dict(type="click", button="left", count=1, pos=None),
                 dict(type="wait", seconds=2.0, jitter=0.0),
                 dict(type="click", button="left", count=1, pos=None)]


def parse_keys(text):
    """'Ctrl + E' -> 'ctrl+e'. Raises ValueError with a message meant for the user."""
    raw = (text or "").strip().lower().replace(" ", "")
    if not raw:
        raise ValueError(T("key_err_empty"))
    out = []
    for tok in raw.split("+"):
        if not tok:
            raise ValueError(T("key_err_format"))
        if tok in KEY_ALIASES:
            out.append(KEY_ALIASES[tok])
        elif len(tok) == 1:
            out.append(tok)
        else:
            raise ValueError(T("key_err_unknown", key=tok))
    if any(t not in MODIFIERS for t in out[:-1]):
        raise ValueError(T("key_err_combo"))
    if HOTKEY in out:
        raise ValueError(T("key_err_hotkey"))
    return "+".join(out)


def format_keys(keys):
    return " + ".join(KEY_LABEL.get(t) or t.upper() for t in keys.split("+"))


def type_name(t):
    return T("type_" + t)


def button_name(b):
    return T("btn_" + b)


def describe(st):
    """One-line, human readable description of a step (in the current language)."""
    t = st.get("type")
    if t == "click":
        pos = st.get("pos")
        where = T("at_pos", x=pos[0], y=pos[1]) if pos else T("at_cursor")
        cnt = T("double_click") if int(st.get("count", 1)) == 2 else T("single_click")
        return T("desc_click", button=button_name(st["button"]), count=cnt, where=where)
    if t == "key":
        return T("desc_key", keys=format_keys(st["keys"]))
    if t == "hold":
        what = (T("mouse_button", button=button_name(st["button"])) if st.get("button")
                else T("keyboard_key", keys=format_keys(st["keys"])))
        return T("desc_hold", what=what, sec=float(st["seconds"]))
    if t == "wait":
        s = T("desc_wait", sec=float(st["seconds"]))
        if st.get("jitter"):
            s += T("desc_wait_jitter", sec=float(st["jitter"]))
        return s
    if t == "move":
        return T("desc_move", x=st["pos"][0], y=st["pos"][1])
    if t == "scroll":
        a = int(st["amount"])
        return T("desc_scroll_up" if a > 0 else "desc_scroll_down", n=abs(a))
    return str(st)


def step_seconds(st):
    if st.get("type") == "wait":
        return float(st.get("seconds", 0)) + float(st.get("jitter", 0) or 0) / 2
    if st.get("type") == "hold":
        return float(st.get("seconds", 0))
    if st.get("type") == "key":
        return 0.05
    return 0.0


def legacy_steps(cfg):
    """Settings from v1/v2 ('click delay' + 'second click') converted to an action list."""
    steps = []
    if float(cfg.get("delay") or 0) > 0:
        steps.append(dict(type="wait", seconds=float(cfg["delay"]), jitter=0.0))
    steps.append(dict(type="click", button="left", count=1, pos=None))
    if cfg.get("second_click", True):
        steps.append(dict(type="wait", seconds=float(cfg.get("second_gap") or 2.0), jitter=0.0))
        steps.append(dict(type="click", button="left", count=1, pos=None))
    return steps


class ActionRunner:
    """Runs a list of steps. When `cancel` (a threading.Event) is set it stops quickly
    and releases anything it is holding down."""

    def __init__(self, mouse_mod, keyboard_mod):
        self.mm, self.km = mouse_mod, keyboard_mod
        self.mouse = mouse_mod.Controller()
        self.kb = keyboard_mod.Controller()

    def _btn(self, name):
        return getattr(self.mm.Button, name)

    def _keys(self, keys):
        return [self.km.KeyCode.from_char(t) if len(t) == 1 else getattr(self.km.Key, t)
                for t in keys.split("+")]

    def run(self, steps, cancel):
        held_btn, held_keys = None, []
        try:
            for st in steps:
                if cancel.is_set():
                    return False
                t = st["type"]
                if t == "wait":
                    sec = float(st["seconds"]) + random.uniform(0, float(st.get("jitter") or 0))
                    if cancel.wait(sec):
                        return False
                elif t == "click":
                    if st.get("pos"):
                        self.mouse.position = (int(st["pos"][0]), int(st["pos"][1]))
                    self.mouse.click(self._btn(st["button"]), int(st.get("count", 1)))
                elif t == "key":
                    ks = self._keys(st["keys"])
                    for k in ks:
                        self.kb.press(k)
                    held_keys = ks
                    cancel.wait(0.05)          # hold ~50 ms so games register the press
                    for k in reversed(ks):
                        self.kb.release(k)
                    held_keys = []
                elif t == "hold":
                    if st.get("button"):
                        held_btn = self._btn(st["button"])
                        self.mouse.press(held_btn)
                    else:
                        held_keys = self._keys(st["keys"])
                        for k in held_keys:
                            self.kb.press(k)
                    stopped = cancel.wait(float(st["seconds"]))
                    if held_btn is not None:
                        self.mouse.release(held_btn)
                        held_btn = None
                    for k in reversed(held_keys):
                        self.kb.release(k)
                    held_keys = []
                    if stopped:
                        return False
                elif t == "move":
                    self.mouse.position = (int(st["pos"][0]), int(st["pos"][1]))
                elif t == "scroll":
                    self.mouse.scroll(0, int(st["amount"]))
            return True
        finally:
            if held_btn is not None:
                self.mouse.release(held_btn)
            for k in reversed(held_keys):
                self.kb.release(k)


# Tk key events -> our key names (used by "record key")
_TK_KEYS = {"space": "space", "Return": "enter", "KP_Enter": "enter", "Tab": "tab",
            "Escape": "esc", "BackSpace": "backspace", "Delete": "delete", "Insert": "insert",
            "Home": "home", "End": "end", "Prior": "page_up", "Next": "page_down",
            "Up": "up", "Down": "down", "Left": "left", "Right": "right",
            "Caps_Lock": "caps_lock"}
_TK_MODS = {"Control_L": "ctrl", "Control_R": "ctrl", "Shift_L": "shift", "Shift_R": "shift",
            "Alt_L": "alt", "Alt_R": "alt", "Meta_L": "alt", "Meta_R": "alt",
            "Win_L": "cmd", "Win_R": "cmd", "Super_L": "cmd", "Super_R": "cmd"}
_VK_OEM = {0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`",
           0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'"}


def key_token(e):
    """Returns (key name, is_modifier), or (None, False) if the key is not supported."""
    ks = e.keysym
    if ks in _TK_MODS:
        return _TK_MODS[ks], True
    if ks in _TK_KEYS:
        return _TK_KEYS[ks], False
    if re.fullmatch(r"F([1-9]|1[0-9]|20)", ks or ""):
        return ks.lower(), False
    if sys.platform == "win32":
        vk = e.keycode
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            return chr(vk).lower(), False
        if 0x60 <= vk <= 0x69:
            return str(vk - 0x60), False
        if vk in _VK_OEM:
            return _VK_OEM[vk], False
    if ks and len(ks) == 1:
        return ks.lower(), False
    ch = getattr(e, "char", "")
    if ch and len(ch) == 1 and ch.isprintable() and ch != " ":
        return ch.lower(), False
    return None, False


def event_mods(e):
    st = int(e.state) if isinstance(e.state, int) else 0
    mods = []
    if st & 0x4:
        mods.append("ctrl")
    if st & 0x1:
        mods.append("shift")
    if st & (0x20000 if sys.platform == "win32" else 0x8):
        mods.append("alt")
    return mods
