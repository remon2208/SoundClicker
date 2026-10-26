"""SoundClicker main window (Tkinter)."""

import copy
import json
import os
import queue
import sys
import threading
import time
from collections import deque

import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk

import numpy as np

from . import __version__
from .actions import (DEFAULT_STEPS, MODIFIERS, STEP_TYPES, ActionRunner, describe, event_mods,
                      format_keys, key_token, legacy_steps, parse_keys, step_seconds, type_name)
from .engine import (HOP, MAX_SAVE_LEN, SR, TRIM_DB, AudioService, FeatureStream, Matcher,
                     list_inputs, load_template, read_audio, trim_event, write_wav)
from .i18n import LANGS, T, detect_lang, get_lang, set_lang
from .winaudio import friendly_error, list_windows, open_source, pid_alive, window_capture_supported

if getattr(sys, "frozen", False):
    # The .exe keeps templates and settings in %APPDATA%\SoundClicker
    APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "SoundClicker")
else:
    # Running from source: next to SoundClicker.pyw (the folder above this package)
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL_DIR = os.path.join(APP_DIR, "templates")
CFG_PATH = os.path.join(APP_DIR, "sound_clicker_settings.json")

DEFAULT_CFG = dict(lang=None, device=None, device_loop=True, templates=[], threshold=0.75,
                   cooldown=1.0, max_len=0.8, min_db=-55.0,
                   record_seconds=5, test_mode=False, topmost=False, actions={},
                   src_mode="device", win_exe="", win_title="",
                   # settings of older versions (only used to build the first action list)
                   delay=0.0, second_click=True, second_gap=2.0)

C = dict(bg="#15171c", grid="#2a2e37", line="#4fc3f7", thr="#ffa726",
         hit="#66bb6a", text="#8b93a3", good="#66bb6a",
         start="#2e7d32", start_hi="#388e3c", stop="#c62828", stop_hi="#d32f2f")

GRAPH_FRAMES = 500   # the graph shows the last 5 s

FONTS = {
    "zh": ("Microsoft JhengHei UI", "Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC", "Noto Sans TC"),
    "ja": ("Yu Gothic UI", "Meiryo UI", "Meiryo", "Hiragino Sans", "Noto Sans CJK JP", "Noto Sans JP"),
    "en": ("Segoe UI", "Helvetica Neue", "Noto Sans", "DejaVu Sans"),
}


def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        cfg.update({k: v for k, v in data.items() if k in DEFAULT_CFG})
        cfg["_has_actions"] = "actions" in data
    except Exception:  # noqa: BLE001
        cfg["_has_actions"] = False
    return cfg


class App:
    def __init__(self, root, mouse_mod, keyboard_mod):
        self.root = root
        self.keyboard_mod = keyboard_mod
        self.runner = ActionRunner(mouse_mod, keyboard_mod)
        self.cfg = load_cfg()
        set_lang(self.cfg.get("lang") or detect_lang())
        self.cfg["lang"] = get_lang()
        self.ui_q = queue.Queue()
        self.audio = AudioService(self.ui_q.put)
        self.stop_evt = threading.Event()
        self.rec_cancel = threading.Event()
        self.try_cancel = threading.Event()
        self.lock = threading.Lock()
        self.scores = deque(maxlen=GRAPH_FRAMES)
        self.hit_frames = deque(maxlen=50)
        self.frame_no = 0
        self.devices = []
        self.windows = []        # [{pid, title, exe}]
        self.win_ok, self.win_reason = window_capture_supported()
        self.templates = []      # [{path, dur}]
        self.actions = {}        # template path -> [step, ...] (always replaced, never mutated)
        self.state = "idle"      # idle/starting/listening/stopping/recording/playing/trying
        self.triggers = 0
        self.fatal = False
        self.modal = False
        self.sess = None
        self.live = {}

        self._setup_style()
        self._build()
        self._load_templates_from_cfg()
        self._sync_live()
        self._refresh_actions()
        self._update_controls()
        self.audio.start()
        self.refresh_devices()
        if self.win_ok and self.v_src.get() == "window":
            self.refresh_windows()
        self._on_src_change(save=False)
        self._start_hotkeys()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._poll_job = root.after(40, self._poll)

    # ---------------------------------------------------- look & feel
    def _setup_style(self):
        r = self.root
        self.scale = max(1.0, r.winfo_fpixels("1i") / 96.0)
        families = set(tkfont.families(r))
        fam = next((c for c in FONTS.get(get_lang(), ()) if c in families), None)
        if fam is None:
            fam = next((c for lang in ("zh", "ja", "en") for c in FONTS[lang] if c in families), None)
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            f = tkfont.nametofont(name)
            if fam:
                f.configure(family=fam)
            f.configure(size=10)
        self.fam = fam or tkfont.nametofont("TkDefaultFont").actual("family")
        st = ttk.Style(r)
        if sys.platform != "win32" and "clam" in st.theme_names():
            st.theme_use("clam")
        st.configure("Hint.TLabel", foreground="#6b7280")
        st.configure("Big.TLabel", font=(self.fam, 13, "bold"))
        st.configure("Hit.TLabel", font=(self.fam, 13, "bold"), foreground=C["good"])
        st.configure("Section.TLabelframe.Label", font=(self.fam, 10, "bold"))
        st.configure("Treeview", rowheight=self._px(24), font=(self.fam, 10))
        st.configure("Treeview.Heading", font=(self.fam, 9))

    def _px(self, v):
        return int(v * self.scale)

    # ---------------------------------------------------- layout
    def _build(self):
        r = self.root
        r.title(f"{T('app_title')}  v{__version__}")
        main = ttk.Frame(r, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        r.columnconfigure(0, weight=1)
        r.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1, uniform="col")
        main.columnconfigure(1, weight=1, uniform="col")
        main.rowconfigure(0, weight=1)
        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        right = ttk.Frame(main)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        left.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self._build_source(left)
        self._build_templates(left)
        self._build_actions(left)
        left.rowconfigure(2, weight=1)
        self._build_settings(right)
        self._build_listen(right)
        right.rowconfigure(1, weight=1)
        r.update_idletasks()
        r.minsize(r.winfo_reqwidth(), r.winfo_reqheight())
        self._apply_topmost()

    def _section(self, parent, row, title, sticky="ew"):
        f = ttk.LabelFrame(parent, text=f" {title} ", padding=8, style="Section.TLabelframe")
        f.grid(row=row, column=0, sticky=sticky, pady=(0 if row == 0 else 10, 0))
        f.columnconfigure(0, weight=1)
        return f

    def _build_source(self, parent):
        f1 = self._section(parent, 0, T("sec_source"))
        f1.columnconfigure(0, weight=0)
        f1.columnconfigure(1, weight=1)
        mode = self.cfg.get("src_mode") if self.win_ok else "device"
        self.v_src = tk.StringVar(value=mode if mode in ("device", "window") else "device")
        self.rb_dev = ttk.Radiobutton(f1, text=T("src_device"), value="device", variable=self.v_src,
                                      command=self._on_src_change)
        self.rb_dev.grid(row=0, column=0, sticky="w")
        self.cb_dev = ttk.Combobox(f1, state="readonly", width=32)
        self.cb_dev.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.cb_dev.bind("<<ComboboxSelected>>", lambda e: self._on_device_pick())
        self.btn_refresh = ttk.Button(f1, text=T("refresh"), command=self.refresh_devices)
        self.btn_refresh.grid(row=0, column=2, padx=(6, 0))
        self.rb_win = ttk.Radiobutton(f1, text=T("src_window"), value="window", variable=self.v_src,
                                      command=self._on_src_change)
        self.rb_win.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.cb_win = ttk.Combobox(f1, state="readonly", width=32)
        self.cb_win.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(6, 0))
        self.cb_win.bind("<<ComboboxSelected>>", lambda e: self._on_win_pick())
        self.cb_win.bind("<Button-1>", lambda e: self._maybe_refresh_windows(), add="+")
        self.btn_win_refresh = ttk.Button(f1, text=T("refresh"), command=self.refresh_windows)
        self.btn_win_refresh.grid(row=1, column=2, padx=(6, 0), pady=(6, 0))
        self.lbl_src = ttk.Label(f1, text="", style="Hint.TLabel", wraplength=self._px(470))
        self.lbl_src.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _build_templates(self, parent):
        f2 = self._section(parent, 1, T("sec_templates"))
        lf = ttk.Frame(f2)
        lf.grid(row=0, column=0, sticky="nsew")
        self.lb_tpl = tk.Listbox(lf, height=4, activestyle="none", exportselection=False,
                                 font=(self.fam, 10), relief="solid", borderwidth=1,
                                 highlightthickness=0, selectbackground="#1976d2")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.lb_tpl.yview)
        self.lb_tpl.configure(yscrollcommand=sb.set)
        self.lb_tpl.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb_tpl.bind("<<ListboxSelect>>", lambda e: self._on_tpl_select())

        bf = ttk.Frame(f2)
        bf.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.btn_rec = ttk.Button(bf, text=T("tpl_record"), command=self.on_record)
        self.btn_add = ttk.Button(bf, text=T("tpl_add"), command=self.on_add)
        self.btn_play = ttk.Button(bf, text=T("tpl_play"), command=self.on_play)
        self.btn_del = ttk.Button(bf, text=T("tpl_remove"), command=self.on_remove)
        self.btn_dir = ttk.Button(bf, text=T("tpl_folder"), command=self.on_open_dir)
        for i, b in enumerate((self.btn_rec, self.btn_add, self.btn_play, self.btn_del, self.btn_dir)):
            bf.columnconfigure(i, weight=1, uniform="tb")
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))

        rf = ttk.Frame(f2)
        rf.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        rf.columnconfigure(2, weight=1)
        ttk.Label(rf, text=T("rec_seconds")).grid(row=0, column=0, sticky="w")
        self.v_recsec = tk.StringVar(value=f"{float(self.cfg['record_seconds']):g}")
        self.sp_recsec = ttk.Spinbox(rf, from_=2, to=20, increment=1, width=4,
                                     textvariable=self.v_recsec)
        self.sp_recsec.grid(row=0, column=1, padx=(6, 12))
        self.lbl_rec = ttk.Label(rf, text=T("rec_hint"), style="Hint.TLabel",
                                 wraplength=self._px(360))
        self.lbl_rec.grid(row=0, column=2, sticky="w")
        self.pb_rec = ttk.Progressbar(rf, maximum=1.0, mode="determinate")
        self.pb_rec.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.pb_rec.grid_remove()

    def _build_actions(self, parent):
        f3 = self._section(parent, 2, T("sec_actions"), sticky="nsew")
        f3.rowconfigure(1, weight=1)
        self.lbl_act = ttk.Label(f3, text="", wraplength=self._px(470))
        self.lbl_act.grid(row=0, column=0, sticky="w")
        tvf = ttk.Frame(f3)
        tvf.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.tv_act = ttk.Treeview(tvf, columns=("n", "desc"), show="headings", height=6,
                                   selectmode="browse")
        self.tv_act.heading("n", text=T("col_order"))
        self.tv_act.heading("desc", text=T("col_action"), anchor="w")
        self.tv_act.column("n", width=self._px(52), stretch=False, anchor="center")
        self.tv_act.column("desc", width=self._px(380), stretch=True, anchor="w")
        sb = ttk.Scrollbar(tvf, orient="vertical", command=self.tv_act.yview)
        self.tv_act.configure(yscrollcommand=sb.set)
        self.tv_act.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tv_act.bind("<Double-1>", lambda e: self.on_edit_step())
        self.tv_act.bind("<Delete>", lambda e: self.on_del_step())

        b1 = ttk.Frame(f3)
        b1.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.btn_step_add = ttk.Button(b1, text=T("step_add"), command=self.on_add_step)
        self.btn_step_edit = ttk.Button(b1, text=T("step_edit"), command=self.on_edit_step)
        self.btn_step_del = ttk.Button(b1, text=T("step_delete"), command=self.on_del_step)
        self.btn_step_up = ttk.Button(b1, text=T("step_up"), command=lambda: self.on_move_step(-1))
        self.btn_step_down = ttk.Button(b1, text=T("step_down"), command=lambda: self.on_move_step(1))
        self.act_btns = [self.btn_step_add, self.btn_step_edit, self.btn_step_del,
                         self.btn_step_up, self.btn_step_down]
        for i, b in enumerate(self.act_btns):
            b1.columnconfigure(i, weight=1, uniform="ab")
            b.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))

        b2 = ttk.Frame(f3)
        b2.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        b2.columnconfigure(2, weight=1)
        self.btn_try = ttk.Button(b2, text=T("try"), command=self.on_try)
        self.btn_try.grid(row=0, column=0, sticky="w")
        self.btn_apply_all = ttk.Button(b2, text=T("apply_all"), command=self.on_apply_all)
        self.btn_apply_all.grid(row=0, column=1, sticky="w", padx=(4, 0))
        self.act_btns.append(self.btn_apply_all)
        self.lbl_try = ttk.Label(b2, text=T("try_hint"), style="Hint.TLabel",
                                 wraplength=self._px(250))
        self.lbl_try.grid(row=0, column=2, sticky="w", padx=(10, 0))

    def _build_settings(self, parent):
        f4 = self._section(parent, 0, T("sec_settings"))
        f4.columnconfigure(0, weight=0)
        f4.columnconfigure(1, weight=1)
        ttk.Label(f4, text=T("threshold")).grid(row=0, column=0, sticky="w")
        self.v_thr = tk.DoubleVar(value=self.cfg["threshold"])
        self.sc_thr = ttk.Scale(f4, from_=0.50, to=0.95, variable=self.v_thr,
                                command=lambda v: self._sync_live())
        self.sc_thr.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.lbl_thr = ttk.Label(f4, text="", width=5, font=(self.fam, 11, "bold"))
        self.lbl_thr.grid(row=0, column=2)
        ttk.Label(f4, text=T("threshold_hint"), style="Hint.TLabel").grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(8, 0))

        grid = ttk.Frame(f4)
        grid.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.v_cool = tk.StringVar(value=f"{float(self.cfg['cooldown']):g}")
        self.v_maxlen = tk.StringVar(value=f"{float(self.cfg['max_len']):g}")
        self.v_mindb = tk.StringVar(value=str(int(self.cfg["min_db"])))
        specs = [
            ("cooldown", self.v_cool, 0, 10, 0.1, T("unit_sec"), T("cooldown_tip")),
            ("max_len", self.v_maxlen, 0.2, 3, 0.1, T("unit_sec"), T("max_len_tip")),
            ("min_db", self.v_mindb, -80, -20, 1, "dB", T("min_db_tip")),
        ]
        self.spins = {}
        for i, (key, var, lo, hi, inc, unit, tip) in enumerate(specs):
            rr, cc = divmod(i, 2)
            lbl = ttk.Label(grid, text=T(key))
            lbl.grid(row=rr, column=cc * 3, sticky="w", pady=2)
            sp = ttk.Spinbox(grid, from_=lo, to=hi, increment=inc, width=6, textvariable=var,
                             command=self._sync_live)
            sp.grid(row=rr, column=cc * 3 + 1, sticky="w", padx=(6, 4), pady=2)
            sp.bind("<KeyRelease>", lambda e: self._sync_live())
            sp.bind("<FocusOut>", lambda e: self._sync_live())
            ttk.Label(grid, text=unit).grid(row=rr, column=cc * 3 + 2, sticky="w",
                                            padx=(0, 18), pady=2)
            self.spins[key] = sp
            _Tooltip(lbl, tip)
            _Tooltip(sp, tip)

        opt = ttk.Frame(f4)
        opt.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.v_test = tk.BooleanVar(value=self.cfg["test_mode"])
        self.v_top = tk.BooleanVar(value=self.cfg["topmost"])
        ttk.Checkbutton(opt, text=T("test_mode"), variable=self.v_test,
                        command=self._sync_live).pack(side="left")
        ttk.Checkbutton(opt, text=T("topmost"), variable=self.v_top,
                        command=self._apply_topmost).pack(side="left", padx=(18, 0))

        lang = ttk.Frame(f4)
        lang.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Label(lang, text="🌐 " + T("language")).pack(side="left")
        self.cb_lang = ttk.Combobox(lang, state="readonly", width=12, values=list(LANGS.values()))
        self.cb_lang.current(list(LANGS).index(get_lang()))
        self.cb_lang.pack(side="left", padx=(8, 0))
        self.cb_lang.bind("<<ComboboxSelected>>", lambda e: self.root.after(1, self._on_lang_pick))

    def _build_listen(self, parent):
        f5 = self._section(parent, 1, T("sec_listen"), sticky="nsew")
        f5.rowconfigure(3, weight=1)
        top = ttk.Frame(f5)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        self.btn_start = tk.Button(top, text="", command=self.toggle, font=(self.fam, 12, "bold"),
                                   fg="white", activeforeground="white", relief="flat",
                                   disabledforeground="#f0f0f0",
                                   borderwidth=0, padx=18, pady=6, cursor="hand2")
        self.btn_start.grid(row=0, column=0, rowspan=2, sticky="w")
        self.lbl_status = ttk.Label(top, text=T("st_idle"))
        self.lbl_status.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self.lbl_hotkey = ttk.Label(top, text=T("hotkey_hint"), style="Hint.TLabel")
        self.lbl_hotkey.grid(row=1, column=1, sticky="w", padx=(12, 0))
        self.lbl_count = ttk.Label(top, text=T("triggered", n=self.triggers), style="Big.TLabel")
        self.lbl_count.grid(row=0, column=2, rowspan=2, sticky="e")

        self.cv = tk.Canvas(f5, width=self._px(470), height=self._px(130), bg=C["bg"],
                            highlightthickness=0, cursor="sb_v_double_arrow")
        self.cv.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.cv.bind("<Button-1>", self._on_graph_click)
        self.cv.bind("<B1-Motion>", self._on_graph_click)
        ttk.Label(f5, text=T("graph_hint"), style="Hint.TLabel",
                  wraplength=self._px(470)).grid(row=2, column=0, sticky="w", pady=(4, 0))

        lg = ttk.Frame(f5)
        lg.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        self.lb_log = tk.Listbox(lg, height=7, activestyle="none", font=(self.fam, 9),
                                 relief="solid", borderwidth=1, highlightthickness=0)
        sb2 = ttk.Scrollbar(lg, orient="vertical", command=self.lb_log.yview)
        self.lb_log.configure(yscrollcommand=sb2.set)
        self.lb_log.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

    # ---------------------------------------------------- language
    def _on_lang_pick(self):
        i = self.cb_lang.current()
        code = list(LANGS)[i] if 0 <= i < len(LANGS) else get_lang()
        if code != get_lang():
            self.set_language(code)

    def set_language(self, code):
        """Switches the UI language in place (keeps templates, actions and the log state)."""
        if self.state != "idle" or self.modal:
            return
        sel = self._selected_template()
        win_sel = self._selected_window()
        self._sync_live()
        set_lang(code)
        self.cfg["lang"] = code
        self.save_cfg()
        for w in self.root.winfo_children():
            w.destroy()
        self._setup_style()
        self._build()
        self._refresh_tpl_list()
        if sel is not None and sel < len(self.templates):
            self.lb_tpl.selection_set(sel)
        if self.devices:
            self._on_devices(self.devices)
        if self.windows:
            self._fill_windows(self.windows, prefer=win_sel)
        self._refresh_actions()
        self._sync_live()
        self._on_src_change(save=False)
        self._update_controls()

    # ---------------------------------------------------- settings
    @staticmethod
    def _num(var, default, lo, hi):
        try:
            v = float(str(var.get()).strip())
        except (ValueError, tk.TclError):
            return default
        return min(max(v, lo), hi)

    def _sync_live(self):
        thr = round(self._num(self.v_thr, 0.75, 0.3, 0.99), 2)
        self.lbl_thr.configure(text=f"{thr:.2f}")
        self.live = dict(
            threshold=thr,
            cooldown=self._num(self.v_cool, 1.0, 0, 60),
            test_mode=bool(self.v_test.get()),
        )
        self.cfg.update(self.live)
        self.cfg["max_len"] = self._num(self.v_maxlen, 0.8, 0.1, MAX_SAVE_LEN)
        self.cfg["min_db"] = self._num(self.v_mindb, -55.0, -100, 0)
        self.cfg["record_seconds"] = self._num(self.v_recsec, 5, 1, 60)

    def _apply_topmost(self):
        self.cfg["topmost"] = bool(self.v_top.get())
        self.root.attributes("-topmost", self.cfg["topmost"])

    def save_cfg(self):
        self._sync_live()
        self.cfg["templates"] = [t["path"] for t in self.templates]
        self.cfg["actions"] = {t["path"]: self.actions.get(t["path"], []) for t in self.templates}
        data = {k: v for k, v in self.cfg.items() if not k.startswith("_")}
        try:
            os.makedirs(APP_DIR, exist_ok=True)
            with open(CFG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # ---------------------------------------------------- state
    def _set_state(self, s):
        self.state = s
        self._update_controls()

    def _update_controls(self):
        s = self.state
        idle = s == "idle" and not self.fatal
        on = "normal" if idle else "disabled"
        for w in (self.btn_add, self.btn_play, self.btn_del, self.sp_recsec):
            w.configure(state=on)
        dev_mode = self.v_src.get() == "device"
        self.cb_dev.configure(state="readonly" if idle and dev_mode else "disabled")
        self.btn_refresh.configure(state="normal" if idle and dev_mode else "disabled")
        self.cb_win.configure(state="readonly" if idle and not dev_mode else "disabled")
        self.btn_win_refresh.configure(state="normal" if idle and not dev_mode else "disabled")
        self.rb_dev.configure(state=on)
        self.rb_win.configure(state=on if self.win_ok else "disabled")
        self.cb_lang.configure(state="readonly" if idle else "disabled")
        for k in ("max_len", "min_db"):
            self.spins[k].configure(state=on)
        if s == "recording":
            self.btn_rec.configure(text=T("tpl_record_cancel"), state="normal")
        else:
            self.btn_rec.configure(text=T("tpl_record"), state=on)

        has_tpl = self._current_tpl_path() is not None
        edit = "normal" if (self._can_edit() and has_tpl) else "disabled"
        for b in self.act_btns:
            b.configure(state=edit)
        if s == "trying":
            self.btn_try.configure(text=T("try_stop"), state="normal")
        else:
            self.btn_try.configure(text=T("try"), state="normal" if idle and has_tpl else "disabled")

        if s in ("listening", "starting"):
            self.btn_start.configure(text=T("btn_stop"), bg=C["stop"],
                                     activebackground=C["stop_hi"], state="normal")
        else:
            self.btn_start.configure(text=T("btn_start"), bg=C["start"] if idle else "#9e9e9e",
                                     activebackground=C["start_hi"],
                                     state="normal" if idle else "disabled")
        labels = dict(idle="st_idle", starting="st_starting", stopping="st_stopping",
                      recording="st_recording", playing="st_playing", trying="st_trying")
        if s in labels:
            self.lbl_status.configure(text=T(labels[s]))

    def _can_edit(self):
        # Actions may be edited while listening (the next trigger uses the new list)
        return not self.fatal and self.state not in ("recording", "trying")

    # ---------------------------------------------------- devices
    def refresh_devices(self):
        if self.state != "idle":
            return

        def task(sc):
            self.ui_q.put(("devices", list_inputs(sc)))
        self.audio.submit(task)

    def _on_devices(self, devs):
        self.devices = devs
        labels = [(T("dev_loopback") if d["loop"] else T("dev_mic")) + "｜" + d["name"] for d in devs]
        self.cb_dev.configure(values=labels)
        pick = None
        for i, d in enumerate(devs):
            if d["name"] == self.cfg.get("device") and d["loop"] == self.cfg.get("device_loop"):
                pick = i
                break
        if pick is None:
            pick = next((i for i, d in enumerate(devs) if d["default"]), 0 if devs else None)
        if pick is not None:
            self.cb_dev.current(pick)
            self._on_device_pick()
        else:
            self.cb_dev.set(T("dev_none"))

    def _on_device_pick(self):
        i = self.cb_dev.current()
        if 0 <= i < len(self.devices):
            self.cfg["device"] = self.devices[i]["name"]
            self.cfg["device_loop"] = self.devices[i]["loop"]

    def _selected_device(self):
        i = self.cb_dev.current()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    # ---------------------------------------------------- one window only
    def _on_src_change(self, save=True):
        mode = self.v_src.get()
        if mode == "window" and not self.win_ok:
            mode = "device"
            self.v_src.set(mode)
        if mode == "window":
            if not self.windows:
                self.refresh_windows()
            text = T("src_window_hint")
        else:
            text = T("src_device_hint")
            if not self.win_ok:
                text += "\n" + T("src_window_unavailable", reason=self.win_reason)
        self.lbl_src.configure(text=text)
        self.cfg["src_mode"] = mode
        self._update_controls()
        if save:
            self.save_cfg()

    def _maybe_refresh_windows(self):
        if self.state == "idle" and self.v_src.get() == "window":
            self.refresh_windows()

    def refresh_windows(self):
        if not self.win_ok:
            return
        try:
            wins = list_windows()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(T("win_list_title"), T("win_list_error", err=e))
            return
        self._fill_windows(wins, prefer=self._selected_window())

    def _fill_windows(self, wins, prefer=None):
        self.windows = wins
        labels = []
        for w in wins:
            t = w["title"] if len(w["title"]) <= 40 else w["title"][:39] + "…"
            labels.append(f"{t} ({w['exe']})")
        self.cb_win.configure(values=labels)
        want_pid = prefer["pid"] if prefer else None
        want_exe = prefer["exe"] if prefer else self.cfg.get("win_exe")
        want_title = prefer["title"] if prefer else self.cfg.get("win_title")
        pick = None
        for rule in (lambda w: w["pid"] == want_pid,
                     lambda w: w["exe"] == want_exe and w["title"] == want_title,
                     lambda w: bool(want_exe) and w["exe"] == want_exe):
            pick = next((i for i, w in enumerate(wins) if rule(w)), None)
            if pick is not None:
                break
        if pick is not None:
            self.cb_win.current(pick)
            self._on_win_pick(save=False)
        else:
            self.cb_win.set(T("win_pick") if wins else T("win_none"))

    def _on_win_pick(self, save=True):
        w = self._selected_window()
        if w:
            self.cfg["win_exe"], self.cfg["win_title"] = w["exe"], w["title"]
            if save:
                self.save_cfg()

    def _selected_window(self):
        i = self.cb_win.current()
        return self.windows[i] if 0 <= i < len(self.windows) else None

    def _selected_source(self):
        """The chosen audio source; shows a hint and returns None if nothing usable is selected."""
        if self.v_src.get() == "window":
            w = self._selected_window()
            if w and not pid_alive(w["pid"]):
                self.refresh_windows()
                w = self._selected_window()
                if w and not pid_alive(w["pid"]):
                    w = None
            if not w:
                messagebox.showinfo(T("src_window"), T("win_pick_first"))
                return None
            return dict(kind="window", pid=w["pid"], exe=w["exe"], title=w["title"])
        dev = self._selected_device()
        if not dev:
            messagebox.showwarning(T("no_device_title"), T("no_device"))
            return None
        return dict(kind="device", name=dev["name"], loop=dev["loop"])

    # ---------------------------------------------------- templates
    def _load_templates_from_cfg(self):
        paths = [p for p in self.cfg.get("templates", []) if os.path.exists(p)]
        legacy = os.path.join(APP_DIR, "template.wav")   # recorded by the old command-line version
        if not paths and os.path.exists(legacy):
            paths = [legacy]
        saved = self.cfg.get("actions") or {}
        fallback = legacy_steps(self.cfg) if not self.cfg.get("_has_actions") else DEFAULT_STEPS
        for p in paths:
            steps = saved.get(p, saved.get(os.path.abspath(p)))
            self._add_template(p, quiet=True, steps=steps if steps is not None else fallback)
        if self.templates:
            self.lb_tpl.selection_clear(0, "end")
            self.lb_tpl.selection_set(0)
        self._refresh_tpl_list(keep_selection=True)

    def _add_template(self, path, quiet=False, steps=None):
        path = os.path.abspath(path)
        if any(t["path"] == path for t in self.templates):
            return
        try:
            x = trim_event(read_audio(path), TRIM_DB, 0)
            dur = len(x) / SR
            if np.max(np.abs(x)) < 10 ** (-60 / 20):
                raise ValueError(T("file_silent"))
        except Exception as e:  # noqa: BLE001
            if not quiet:
                messagebox.showerror(T("file_bad_title"),
                                     f"{os.path.basename(path)}\n\n{e}\n\n{T('file_bad_hint')}")
            return
        if steps is None:   # a new template starts with a copy of the selected template's actions
            cur = self._current_tpl_path()
            steps = self.actions.get(cur) if cur else None
            if steps is None:
                steps = DEFAULT_STEPS
        self.actions[path] = copy.deepcopy(steps)
        self.templates.append(dict(path=path, dur=dur))
        self._refresh_tpl_list()
        self.lb_tpl.selection_clear(0, "end")
        self.lb_tpl.selection_set("end")
        self._on_tpl_select()

    def _refresh_tpl_list(self, keep_selection=False):
        sel = self.lb_tpl.curselection() if keep_selection else ()
        self.lb_tpl.delete(0, "end")
        for t in self.templates:
            self.lb_tpl.insert("end", "  " + T("tpl_item", name=os.path.basename(t["path"]), sec=t["dur"]))
        if not self.templates:
            self.lb_tpl.insert("end", "  " + T("tpl_empty"))
            self.lb_tpl.itemconfigure(0, foreground="#9e9e9e")
        elif sel and sel[0] < len(self.templates):
            self.lb_tpl.selection_set(sel[0])

    def _selected_template(self):
        sel = self.lb_tpl.curselection()
        if not sel or not self.templates or sel[0] >= len(self.templates):
            return None
        return sel[0]

    def _current_tpl_path(self):
        i = self._selected_template()
        return self.templates[i]["path"] if i is not None else None

    def _on_tpl_select(self):
        self._refresh_actions()
        self._update_controls()

    def on_add(self):
        paths = filedialog.askopenfilenames(
            title=T("file_pick_title"), parent=self.root,
            filetypes=[(T("file_type_audio"), "*.wav *.ogg *.flac *.mp3"), (T("file_type_all"), "*.*")])
        for p in paths:
            self._add_template(p)
        self.save_cfg()

    def on_open_dir(self):
        os.makedirs(TPL_DIR, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(TPL_DIR)
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", TPL_DIR])
        except Exception as e:  # noqa: BLE001
            messagebox.showinfo(T("tpl_folder"), T("folder_info", path=TPL_DIR, err=e))

    def on_remove(self):
        i = self._selected_template()
        if i is None:
            return
        path = self.templates[i]["path"]
        del self.templates[i]
        self.actions.pop(path, None)
        self._refresh_tpl_list()
        if self.templates:
            self.lb_tpl.selection_set(min(i, len(self.templates) - 1))
        self._on_tpl_select()
        self.save_cfg()

    def on_play(self):
        i = self._selected_template()
        if i is None:
            messagebox.showinfo(T("tpl_play_title"), T("tpl_pick_first"))
            return
        path = self.templates[i]["path"]
        max_len = self.cfg["max_len"]
        self._set_state("playing")

        def task(sc):
            try:
                x = trim_event(read_audio(path), TRIM_DB, max_len)
                sc.default_speaker().play(x, samplerate=SR)
            finally:
                self.ui_q.put(("played",))
        self.audio.submit(task)

    def on_record(self):
        if self.state == "recording":
            self.rec_cancel.set()
            return
        if self.state != "idle":
            return
        src = self._selected_source()
        if not src:
            return
        self._sync_live()
        seconds = self.cfg["record_seconds"]
        os.makedirs(TPL_DIR, exist_ok=True)
        n = 1
        while os.path.exists(os.path.join(TPL_DIR, f"sound_{n}.wav")):
            n += 1
        out = os.path.join(TPL_DIR, f"sound_{n}.wav")
        self.rec_cancel.clear()
        self._set_state("recording")
        self.pb_rec.configure(value=0)
        self.pb_rec.grid()
        self.audio.submit(lambda sc: self._record_task(sc, src, seconds, out))

    def _record_task(self, sc, src, seconds, out):
        post = self.ui_q.put
        try:
            rec_cm, _, _ = open_source(sc, src)
            for i in (3, 2, 1):
                post(("rec_status", T("rec_countdown", n=i)))
                for _ in range(10):
                    if self.rec_cancel.is_set():
                        post(("rec_done", None, T("rec_cancelled")))
                        return
                    time.sleep(0.1)
            post(("rec_status", T("rec_now")))
            total, got, chunks = int(seconds * SR), 0, []
            with rec_cm as rec:
                while got < total and not self.rec_cancel.is_set():
                    d = rec.record(numframes=min(4800, total - got))
                    chunks.append(d.mean(axis=1) if d.ndim == 2 else d)
                    got += len(chunks[-1])
                    post(("rec_progress", got / total))
            if self.rec_cancel.is_set():
                post(("rec_done", None, T("rec_cancelled")))
                return
            x = np.concatenate(chunks).astype(np.float32)
            peak_db = 20 * np.log10(np.max(np.abs(x)) + 1e-12)
            if peak_db < -50:
                post(("rec_done", None, T("rec_too_quiet", db=peak_db)))
                return
            seg = trim_event(x, TRIM_DB, MAX_SAVE_LEN)
            write_wav(out, seg)
            post(("rec_done", out, T("rec_ok", name=os.path.basename(out), sec=len(seg) / SR)))
        except Exception as e:  # noqa: BLE001
            post(("rec_done", None, T("rec_failed", err=friendly_error(e, src))))

    # ---------------------------------------------------- action list
    def _refresh_actions(self, select=None):
        tv = self.tv_act
        tv.delete(*tv.get_children())
        path = self._current_tpl_path()
        if not path:
            self.lbl_act.configure(text=T("act_pick_template"))
            return
        steps = self.actions.get(path, [])
        for i, st in enumerate(steps):
            tv.insert("", "end", iid=str(i), values=(i + 1, describe(st)))
        name = os.path.basename(path)
        if steps:
            total = round(sum(step_seconds(s) for s in steps), 2)
            self.lbl_act.configure(text=T("act_summary", name=name, n=len(steps), sec=total))
        else:
            self.lbl_act.configure(text=T("act_empty", name=name))
        if select is not None and 0 <= select < len(steps):
            tv.selection_set(str(select))
            tv.focus(str(select))
            tv.see(str(select))

    def _steps(self):
        path = self._current_tpl_path()
        return path, list(self.actions.get(path, [])) if path else []

    def _sel_step(self):
        sel = self.tv_act.selection()
        return int(sel[0]) if sel else None

    def _set_steps(self, path, steps, select=None):
        self.actions[path] = steps
        self._refresh_actions(select)
        self.save_cfg()

    def on_add_step(self):
        path, steps = self._steps()
        if not path or not self._can_edit():
            return
        dlg = StepDialog(self, None)
        dlg.show()
        if dlg.result:
            i = self._sel_step()
            i = len(steps) if i is None else i + 1
            steps.insert(i, dlg.result)
            self._set_steps(path, steps, i)

    def on_edit_step(self):
        path, steps = self._steps()
        i = self._sel_step()
        if not path or i is None or i >= len(steps) or not self._can_edit():
            return
        dlg = StepDialog(self, steps[i])
        dlg.show()
        if dlg.result:
            steps[i] = dlg.result
            self._set_steps(path, steps, i)

    def on_del_step(self):
        path, steps = self._steps()
        i = self._sel_step()
        if not path or i is None or i >= len(steps) or not self._can_edit():
            return
        del steps[i]
        self._set_steps(path, steps, min(i, len(steps) - 1) if steps else None)

    def on_move_step(self, d):
        path, steps = self._steps()
        i = self._sel_step()
        if not path or i is None or not self._can_edit():
            return
        j = i + d
        if 0 <= j < len(steps):
            steps[i], steps[j] = steps[j], steps[i]
            self._set_steps(path, steps, j)

    def on_apply_all(self):
        path, steps = self._steps()
        if not path or not self._can_edit():
            return
        others = [t for t in self.templates if t["path"] != path]
        if not others:
            messagebox.showinfo(T("apply_all"), T("apply_all_only_one"))
            return
        if messagebox.askyesno(T("apply_all"), T("apply_all_confirm", name=os.path.basename(path),
                                                 n=len(others))):
            for t in others:
                self.actions[t["path"]] = copy.deepcopy(steps)
            self.save_cfg()

    def on_try(self):
        if self.state == "trying":
            self.try_cancel.set()
            return
        if self.state != "idle":
            return
        path, steps = self._steps()
        if not path:
            return
        if not steps:
            messagebox.showinfo(T("try_title"), T("try_no_steps"))
            return
        ev = self.try_cancel = threading.Event()
        self._set_state("trying")
        post = self.ui_q.put

        def run():
            for i in (3, 2, 1):
                post(("try_status", T("try_countdown", n=i)))
                if ev.wait(1.0):
                    post(("try_done", None, 0.0))
                    return
            post(("try_status", T("try_running")))
            t0 = time.time()
            ok = None
            try:
                ok = self.runner.run(steps, ev)
            except Exception as e:  # noqa: BLE001
                post(("error", T("err_action", err=e)))
            post(("try_done", ok, time.time() - t0))
        threading.Thread(target=run, daemon=True).start()

    # ---------------------------------------------------- listening
    def toggle(self):
        if self.state == "trying":
            self.try_cancel.set()
        elif self.state in ("listening", "starting"):
            self.stop()
        elif self.state == "idle":
            self.start()

    def start(self):
        if self.fatal or self.state != "idle":
            return
        if not self.templates:
            messagebox.showinfo(T("no_templates_title"), T("no_templates"))
            return
        src = self._selected_source()
        if not src:
            return
        self.save_cfg()
        snap = dict(src=src, paths=[t["path"] for t in self.templates],
                    max_len=self.cfg["max_len"], min_db=self.cfg["min_db"])
        self.stop_evt.clear()
        sess = self.sess = dict(cancel=threading.Event(), busy=threading.Event())
        with self.lock:
            self.scores.clear()
            self.hit_frames.clear()
            self.frame_no = 0
        self._set_state("starting")
        self.audio.submit(lambda sc: self._listen_task(sc, snap, sess))

    def stop(self):
        self.stop_evt.set()
        if self.sess:
            self.sess["cancel"].set()      # also abort a running action list
        if self.state in ("listening", "starting"):
            self._set_state("stopping")

    def _run_seq(self, steps, sess):
        t0 = time.time()
        ok = None
        try:
            ok = self.runner.run(steps, sess["cancel"])
        except Exception as e:  # noqa: BLE001
            self.ui_q.put(("error", T("err_action", err=e)))
        finally:
            sess["busy"].clear()
            self.ui_q.put(("seq_done", ok, time.time() - t0))

    def _listen_task(self, sc, snap, sess):
        post = self.ui_q.put
        src = snap["src"]
        try:
            tpls = [load_template(p, snap["max_len"]) for p in snap["paths"]]
            rec_cm, label, fell_back = open_source(sc, src)
            live = self.live
            m = Matcher(tpls, live["threshold"], snap["min_db"], live["cooldown"])
            fs = FeatureStream()
            block = int(0.02 * SR)
            next_check = time.time() + 2.0
            with rec_cm as rec:
                post(("listening", label, fell_back))
                while not self.stop_evt.is_set():
                    if src["kind"] == "window" and time.time() > next_check:
                        next_check = time.time() + 2.0
                        if not pid_alive(src["pid"]):
                            post(("info", T("win_closed_title"), T("win_closed", title=src["title"])))
                            break
                    data = rec.record(numframes=block)
                    x = data.mean(axis=1) if data.ndim == 2 else data
                    live = self.live
                    m.threshold = live["threshold"]
                    m.cooldown_frames = int(live["cooldown"] * SR / HOP)
                    scores, hits = m.push(fs.push(x))
                    accepted = []
                    for fno, s, name, path in hits:
                        if sess["busy"].is_set():      # the previous action list is still running
                            continue
                        steps = self.actions.get(path) or []
                        test = live["test_mode"]
                        accepted.append(fno)
                        if steps and not test:
                            sess["busy"].set()
                            threading.Thread(target=self._run_seq, args=(steps, sess),
                                             daemon=True).start()
                        post(("hit", time.strftime("%H:%M:%S"), s, name, test, len(steps)))
                    with self.lock:
                        self.scores.extend(scores)
                        self.frame_no = m.frame_no
                        self.hit_frames.extend(accepted)
        except Exception as e:  # noqa: BLE001
            post(("error", friendly_error(e, src)))
        finally:
            post(("stopped",))

    # ---------------------------------------------------- hotkey
    def _start_hotkeys(self):
        kb = self.keyboard_mod

        def on_press(key):
            if key == kb.Key.f8:
                self.ui_q.put(("toggle",))

        try:
            self.kb_listener = kb.Listener(on_press=on_press)
            self.kb_listener.daemon = True
            self.kb_listener.start()
        except Exception:  # noqa: BLE001 — no global hook: at least F8 inside the window works
            self.root.bind("<F8>", lambda e: self.toggle())
            self.lbl_hotkey.configure(text=T("hotkey_hint_local"))

    # ---------------------------------------------------- messages from worker threads
    def _poll(self):
        try:
            while True:
                self._handle(self.ui_q.get_nowait())
        except queue.Empty:
            pass
        self._draw_graph()
        self._poll_job = self.root.after(40, self._poll)

    def _log(self, text, color=None):
        self.lb_log.insert("end", text)
        if color:
            self.lb_log.itemconfigure("end", foreground=color)
        if self.lb_log.size() > 300:
            self.lb_log.delete(0, self.lb_log.size() - 300)
        self.lb_log.see("end")

    def _handle(self, msg):
        kind = msg[0]
        now = time.strftime("%H:%M:%S")
        if kind == "devices":
            self._on_devices(msg[1])
        elif kind == "toggle":
            if not self.modal:
                self.toggle()
        elif kind == "listening":
            if self.stop_evt.is_set():
                return
            self._set_state("listening")
            name = msg[1] if len(msg[1]) <= 24 else msg[1][:23] + "…"
            self.lbl_status.configure(text=T("st_listening", name=name))
            mode = T("log_test_mode") if self.live.get("test_mode") else ""
            self._log(f"{now}  {T('log_started', name=msg[1])} {mode}", "#1565c0")
            if msg[2]:
                self._log("    " + T("log_fallback"), "#e65100")
        elif kind == "stopped":
            if self.state in ("listening", "starting", "stopping"):
                self._log(f"{now}  {T('log_stopped')}", "#1565c0")
            self._set_state("idle")
        elif kind == "hit":
            _, t, s, name, test, n = msg
            more = f", {name}" if len(self.templates) > 1 else ""
            if test:
                act = T("log_hit_test", n=n)
            elif n == 0:
                act = T("log_hit_no_actions")
            else:
                act = T("log_hit_run", n=n)
                self.triggers += 1
                self.lbl_count.configure(text=T("triggered", n=self.triggers))
            self._log(f"{t}  {T('log_hit', score=s, more=more)} → {act}",
                      "#6d4c41" if test else "#2e7d32")
            self._flash()
        elif kind == "seq_done":
            _, ok, dur = msg
            if ok is False:
                self._log(f"{now}    └ {T('log_aborted')}", "#e65100")
            elif ok and dur >= 0.5:
                self._log(f"{now}    └ {T('log_done', sec=dur)}", "#558b2f")
        elif kind == "try_status":
            self.lbl_try.configure(text=msg[1], style="TLabel")
        elif kind == "try_done":
            _, ok, dur = msg
            self.lbl_try.configure(text=T("try_done", sec=dur) if ok else T("try_cancelled"),
                                   style="Hint.TLabel")
            self._set_state("idle")
        elif kind == "rec_status":
            self.lbl_rec.configure(text=msg[1], style="TLabel")
        elif kind == "rec_progress":
            self.pb_rec.configure(value=msg[1])
        elif kind == "rec_done":
            self.pb_rec.grid_remove()
            self.lbl_rec.configure(text=msg[2], style="Hint.TLabel")
            self._set_state("idle")
            if msg[1]:
                self._add_template(msg[1])
                self.save_cfg()
            elif msg[2] != T("rec_cancelled"):
                messagebox.showwarning(T("rec_title"), msg[2])
        elif kind == "played":
            self._set_state("idle")
        elif kind == "info":
            messagebox.showinfo(msg[1], msg[2])
        elif kind == "error":
            if self.state not in ("idle", "listening"):
                self._set_state("idle")
            messagebox.showerror(T("error_title"), msg[1])
        elif kind == "fatal":
            self.fatal = True
            self._update_controls()
            messagebox.showerror(T("missing_pkg_title"), msg[1])

    def _flash(self):
        self.lbl_count.configure(style="Hit.TLabel")
        self.root.after(350, lambda: self.lbl_count.winfo_exists()
                        and self.lbl_count.configure(style="Big.TLabel"))

    # ---------------------------------------------------- similarity graph
    def _graph_geom(self):
        W = max(self.cv.winfo_width(), 50)
        H = max(self.cv.winfo_height(), 50)
        return W, H, self._px(30), self._px(8), self._px(10), self._px(10)

    def _on_graph_click(self, e):
        if self.state in ("recording",):
            return
        W, H, pl, pr, pt, pb = self._graph_geom()
        v = 1.0 - (e.y - pt) / max(H - pt - pb, 1)
        self.v_thr.set(round(min(max(v, 0.50), 0.95), 2))
        self._sync_live()

    def _draw_graph(self):
        cv = self.cv
        cv.delete("all")
        W, H, pl, pr, pt, pb = self._graph_geom()
        gw, gh = W - pl - pr, H - pt - pb

        def y(v):
            return pt + (1.0 - min(max(v, 0.0), 1.0)) * gh

        small = (self.fam, 8)
        for v in (0.0, 0.25, 0.5, 0.75, 1.0):
            cv.create_line(pl, y(v), W - pr, y(v), fill=C["grid"])
            cv.create_text(pl - 4, y(v), text=f"{v:g}", anchor="e", fill=C["text"], font=small)
        thr = self.live.get("threshold", 0.75)

        with self.lock:
            pts = list(self.scores)
            fno = self.frame_no
            hits = list(self.hit_frames)

        listening = self.state in ("listening", "stopping")
        if listening:
            for h in hits:
                age = fno - h
                if 0 <= age < GRAPH_FRAMES:
                    x = W - pr - age * gw / GRAPH_FRAMES
                    cv.create_line(x, pt, x, H - pb, fill=C["hit"], width=self._px(2))
            if len(pts) >= 2:
                coords = []
                n = len(pts)
                for i in range(0, n - 1, 2):
                    v = max(pts[i:i + 2])
                    coords += [W - pr - (n - 1 - i) * gw / GRAPH_FRAMES, y(v)]
                coords += [W - pr, y(pts[-1])]
                cv.create_line(*coords, fill=C["line"], width=self._px(2))
        cv.create_line(pl, y(thr), W - pr, y(thr), fill=C["thr"], dash=(6, 4), width=self._px(2))
        cv.create_text(pl + 4, y(thr) - 2, anchor="sw", fill=C["thr"], font=small,
                       text=T("graph_threshold", v=thr))
        if listening:
            cur = pts[-1] if pts else 0.0
            recent = max(pts[-300:]) if pts else 0.0
            col = C["good"] if cur >= thr else "#e0e0e0"
            t1 = cv.create_text(W - pr - 6, pt + 2, anchor="ne", fill=col,
                                font=(self.fam, 11, "bold"), text=T("graph_now", v=max(cur, 0)))
            t2 = cv.create_text(W - pr - 6, pt + self._px(22), anchor="ne", fill=C["text"],
                                font=small, text=T("graph_peak", v=max(recent, 0)))
            x0, y0, _, _ = cv.bbox(t1)
            x1, _, _, y1 = cv.bbox(t2)
            box = cv.create_rectangle(min(x0, x1) - 6, y0 - 2, W - pr, y1 + 3,
                                      fill=C["bg"], outline=C["grid"])
            cv.tag_lower(box, t1)
        else:
            cv.create_text(pl + gw / 2, pt + gh / 2, fill=C["text"], font=(self.fam, 10),
                           text=T("graph_idle"))

    # ---------------------------------------------------- closing
    def on_close(self):
        self.stop_evt.set()
        self.rec_cancel.set()
        self.try_cancel.set()
        if self.sess:
            self.sess["cancel"].set()
        self.save_cfg()
        try:
            self.root.after_cancel(self._poll_job)
        except (tk.TclError, AttributeError):
            pass
        self.root.destroy()


class StepDialog:
    """Small window to add or edit one action step."""

    def __init__(self, app, step):
        self.app = app
        self.result = None
        self.capturing = False
        self.pending_mod = None
        self.cap_job = None
        st = copy.deepcopy(step) if step else dict(type="click", button="left", count=1, pos=None)
        t = st.get("type", "click")
        self.types = list(STEP_TYPES)

        w = self.win = tk.Toplevel(app.root)
        w.withdraw()
        w.title(T("dlg_edit") if step else T("dlg_add"))
        w.transient(app.root)
        w.resizable(False, False)
        if app.cfg.get("topmost"):
            w.attributes("-topmost", True)

        self.v_type = tk.StringVar(value=type_name(t if t in self.types else "click"))
        self.v_btn = tk.StringVar(value=st.get("button") or "left")
        self.v_count = tk.IntVar(value=int(st.get("count", 1)))
        pos = st.get("pos")
        self.v_where = tk.StringVar(value="pos" if pos else "cur")
        self.v_x = tk.StringVar(value=str(pos[0]) if pos else "")
        self.v_y = tk.StringVar(value=str(pos[1]) if pos else "")
        self.v_keys = tk.StringVar(value=format_keys(st["keys"]) if st.get("keys") else "")
        self.v_hold = tk.StringVar(value=(st.get("button") or "key") if t == "hold" else "left")
        default_sec = 1.0 if t == "hold" else 2.0
        self.v_sec = tk.StringVar(value=f"{float(st.get('seconds', default_sec)):g}")
        self.v_jit = tk.StringVar(value=f"{float(st.get('jitter', 0.0) or 0):g}")
        amt = int(st.get("amount", 3))
        self.v_dir = tk.StringVar(value="up" if amt >= 0 else "down")
        self.v_amt = tk.StringVar(value=str(abs(amt) or 3))

        frm = ttk.Frame(w, padding=16)
        frm.grid(row=0, column=0, sticky="nsew")
        top = ttk.Frame(frm)
        top.grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=T("dlg_type")).pack(side="left")
        cb = ttk.Combobox(top, state="readonly", width=16, textvariable=self.v_type,
                          values=[type_name(x) for x in self.types])
        cb.pack(side="left", padx=(10, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._render())
        self.body = ttk.Frame(frm)
        self.body.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.lbl_err = ttk.Label(frm, text="", foreground="#c62828", wraplength=app._px(380))
        self.lbl_err.grid(row=2, column=0, sticky="w", pady=(8, 0))
        bf = ttk.Frame(frm)
        bf.grid(row=3, column=0, sticky="e", pady=(8, 0))
        ttk.Button(bf, text=T("ok"), command=self._ok).pack(side="left")
        ttk.Button(bf, text=T("cancel"), command=self._cancel).pack(side="left", padx=(6, 0))
        w.protocol("WM_DELETE_WINDOW", self._cancel)
        w.bind("<KeyPress>", self._on_key)
        w.bind("<KeyRelease>", self._on_key_release)
        self.v_hold.trace_add("write", lambda *a: self._sync_hold_state())
        self.v_where.trace_add("write", lambda *a: self._sync_pos_state())
        self._render()

    def _type(self):
        name = self.v_type.get()
        return next((x for x in self.types if type_name(x) == name), "click")

    # ---- fields for the chosen step type
    def _render(self):
        self._stop_capture()
        for c in self.body.winfo_children():
            c.destroy()
        self.lbl_err.configure(text="")
        t = self._type()
        b = self.body
        r = 0

        def row_label(text):
            ttk.Label(b, text=text).grid(row=r, column=0, sticky="nw", pady=3, padx=(0, 10))

        def radios(var, items, cmd=None):
            f = ttk.Frame(b)
            f.grid(row=r, column=1, sticky="w", pady=3)
            for val, txt in items:
                ttk.Radiobutton(f, text=txt, value=val, variable=var,
                                command=cmd).pack(side="left", padx=(0, 12))
            return f

        def spin(var, lo, hi, inc, unit):
            f = ttk.Frame(b)
            f.grid(row=r, column=1, sticky="w", pady=3)
            ttk.Spinbox(f, from_=lo, to=hi, increment=inc, width=7, textvariable=var).pack(side="left")
            ttk.Label(f, text=unit).pack(side="left", padx=(4, 0))
            return f

        btns = [("left", T("btn_left")), ("right", T("btn_right")), ("middle", T("btn_middle"))]
        if t == "click":
            row_label(T("f_button"))
            radios(self.v_btn, btns)
            r += 1
            row_label(T("f_count"))
            radios(self.v_count, [(1, T("single_click")), (2, T("double_click"))])
            r += 1
            row_label(T("f_position"))
            radios(self.v_where, [("cur", T("pos_cursor")), ("pos", T("pos_fixed"))],
                   cmd=self._sync_pos_state)
            r += 1
            self._pos_row(b, r)
        elif t == "key":
            row_label(T("f_key"))
            self._keys_row(b, r)
            r += 1
            ttk.Label(b, text=T("key_examples"), style="Hint.TLabel").grid(row=r, column=1, sticky="w")
        elif t == "hold":
            row_label(T("f_hold"))
            radios(self.v_hold, [("left", T("mouse_button", button=T("btn_left"))),
                                 ("right", T("mouse_button", button=T("btn_right"))),
                                 ("key", T("keyboard"))], cmd=self._sync_hold_state)
            r += 1
            row_label(T("f_key"))
            self._keys_row(b, r)
            r += 1
            row_label(T("f_hold_for"))
            spin(self.v_sec, 0.05, 600, 0.5, T("unit_sec"))
            self._sync_hold_state()
        elif t == "wait":
            row_label(T("f_wait"))
            spin(self.v_sec, 0.05, 3600, 0.5, T("unit_sec"))
            r += 1
            row_label(T("f_jitter"))
            f = spin(self.v_jit, 0, 60, 0.1, T("unit_sec"))
            ttk.Label(f, text=T("jitter_hint"), style="Hint.TLabel").pack(side="left", padx=(6, 0))
        elif t == "move":
            self.v_where.set("pos")
            self._pos_row(b, r)
        elif t == "scroll":
            row_label(T("f_direction"))
            radios(self.v_dir, [("up", T("dir_up")), ("down", T("dir_down"))])
            r += 1
            row_label(T("f_notches"))
            spin(self.v_amt, 1, 50, 1, T("unit_notch"))

    def _pos_row(self, b, r):
        ttk.Label(b, text=T("f_coords")).grid(row=r, column=0, sticky="nw", pady=3, padx=(0, 10))
        f = ttk.Frame(b)
        f.grid(row=r, column=1, sticky="w", pady=3)
        ttk.Label(f, text="X").pack(side="left")
        self.e_x = ttk.Entry(f, width=6, textvariable=self.v_x)
        self.e_x.pack(side="left", padx=(4, 8))
        ttk.Label(f, text="Y").pack(side="left")
        self.e_y = ttk.Entry(f, width=6, textvariable=self.v_y)
        self.e_y.pack(side="left", padx=(4, 8))
        self.btn_pos = ttk.Button(f, text=T("pick_pos"), command=self._capture_pos)
        self.btn_pos.pack(side="left")
        self.lbl_pos = ttk.Label(b, text=T("pick_pos_hint"), style="Hint.TLabel")
        self.lbl_pos.grid(row=r + 1, column=1, sticky="w")
        self._sync_pos_state()

    def _keys_row(self, b, r):
        f = ttk.Frame(b)
        f.grid(row=r, column=1, sticky="w", pady=3)
        self.e_keys = ttk.Entry(f, width=18, textvariable=self.v_keys)
        self.e_keys.pack(side="left")
        self.btn_cap = ttk.Button(f, text=T("record_key"), command=self._start_capture)
        self.btn_cap.pack(side="left", padx=(6, 0))

    def _sync_pos_state(self):
        if not hasattr(self, "e_x") or not self.e_x.winfo_exists():
            return
        st = "normal" if (self.v_where.get() == "pos" or self._type() == "move") else "disabled"
        for wdg in (self.e_x, self.e_y, self.btn_pos):
            wdg.configure(state=st)

    def _sync_hold_state(self):
        if not hasattr(self, "e_keys") or not self.e_keys.winfo_exists():
            return
        st = "normal" if self.v_hold.get() == "key" else "disabled"
        self.e_keys.configure(state=st)
        self.btn_cap.configure(state=st)

    # ---- pick a screen position
    def _capture_pos(self):
        if self.cap_job:
            return
        end = time.time() + 3.0

        def tick():
            try:
                x, y = self.app.runner.mouse.position
            except Exception:  # noqa: BLE001
                x, y = 0, 0
            left = end - time.time()
            if left > 0:
                self.lbl_pos.configure(text=T("pick_pos_countdown", sec=left, x=int(x), y=int(y)),
                                       style="TLabel")
                self.cap_job = self.win.after(100, tick)
            else:
                self.cap_job = None
                self.v_x.set(str(int(x)))
                self.v_y.set(str(int(y)))
                self.v_where.set("pos")
                self._sync_pos_state()
                self.lbl_pos.configure(text=T("pick_pos_done", x=int(x), y=int(y)), style="Hint.TLabel")
                try:
                    self.win.lift()
                except tk.TclError:
                    pass
        tick()

    # ---- record a key press
    def _start_capture(self):
        self.capturing = True
        self.pending_mod = None
        self.btn_cap.configure(text=T("record_key_wait"))
        self.lbl_err.configure(text="")
        self.win.focus_force()

    def _stop_capture(self):
        self.capturing = False
        self.pending_mod = None
        if getattr(self, "btn_cap", None) is not None and self.btn_cap.winfo_exists():
            self.btn_cap.configure(text=T("record_key"))

    def _finish_capture(self, combo):
        try:
            self.v_keys.set(format_keys(parse_keys(combo)))
        except ValueError as e:
            self.lbl_err.configure(text=str(e))
        self._stop_capture()

    def _on_key(self, e):
        if not self.capturing:
            if e.keysym == "Escape":
                self._cancel()
            elif e.keysym in ("Return", "KP_Enter"):
                self._ok()
            return None
        tok, is_mod = key_token(e)
        if tok is None:
            return "break"
        if is_mod:
            self.pending_mod = tok
            return "break"
        mods = [m for m in event_mods(e) if m != tok]
        if self.pending_mod and self.pending_mod not in mods:
            mods.append(self.pending_mod)
        self._finish_capture("+".join([m for m in MODIFIERS if m in mods] + [tok]))
        return "break"

    def _on_key_release(self, e):
        if self.capturing and self.pending_mod:
            tok, is_mod = key_token(e)
            if is_mod and tok == self.pending_mod:
                self._finish_capture(tok)
        return "break" if self.capturing else None

    # ---- OK / Cancel
    def _num(self, var, name, lo, hi, integer=False):
        try:
            v = float(str(var.get()).strip())
        except ValueError:
            raise ValueError(T("err_not_number", name=name)) from None
        if not lo <= v <= hi:
            raise ValueError(T("err_range", name=name, lo=lo, hi=hi))
        return int(round(v)) if integer else round(v, 3)

    def _collect(self):
        t = self._type()
        if t in ("click", "move"):
            pos = None
            if t == "move" or self.v_where.get() == "pos":
                if not str(self.v_x.get()).strip() or not str(self.v_y.get()).strip():
                    raise ValueError(T("err_need_coords"))
                pos = [self._num(self.v_x, "X", -20000, 20000, True),
                       self._num(self.v_y, "Y", -20000, 20000, True)]
            if t == "move":
                return dict(type="move", pos=pos)
            return dict(type="click", button=self.v_btn.get(), count=int(self.v_count.get()), pos=pos)
        if t == "key":
            return dict(type="key", keys=parse_keys(self.v_keys.get()))
        if t == "hold":
            sec = self._num(self.v_sec, T("f_hold_for"), 0.05, 600)
            if self.v_hold.get() == "key":
                return dict(type="hold", button=None, keys=parse_keys(self.v_keys.get()), seconds=sec)
            return dict(type="hold", button=self.v_hold.get(), seconds=sec)
        if t == "wait":
            return dict(type="wait", seconds=self._num(self.v_sec, T("f_wait"), 0.05, 3600),
                        jitter=self._num(self.v_jit, T("f_jitter"), 0, 60))
        if t == "scroll":
            n = self._num(self.v_amt, T("f_notches"), 1, 50, True)
            return dict(type="scroll", amount=n if self.v_dir.get() == "up" else -n)
        raise ValueError(t)

    def _ok(self):
        try:
            self.result = self._collect()
        except ValueError as e:
            self.lbl_err.configure(text=str(e))
            return
        self._close()

    def _cancel(self):
        self.result = None
        self._close()

    def _close(self):
        if self.cap_job:
            try:
                self.win.after_cancel(self.cap_job)
            except tk.TclError:
                pass
            self.cap_job = None
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()

    def show(self):
        """Shows the dialog modally; the result ends up in self.result."""
        w, root = self.win, self.app.root
        w.update_idletasks()
        x = root.winfo_rootx() + (root.winfo_width() - w.winfo_reqwidth()) // 3
        y = root.winfo_rooty() + (root.winfo_height() - w.winfo_reqheight()) // 3
        w.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        w.deiconify()
        self.app.modal = True
        try:
            w.wait_visibility()
            w.grab_set()
        except tk.TclError:
            pass
        w.focus_force()
        try:
            w.wait_window()
        finally:
            self.app.modal = False


class _Tooltip:
    """Shows a hint while the mouse is over a widget."""

    def __init__(self, widget, text):
        self.w, self.text, self.tip = widget, text, None
        for child in [widget] + list(widget.winfo_children()):
            child.bind("<Enter>", self.show, add="+")
            child.bind("<Leave>", self.hide, add="+")

    def show(self, _e=None):
        if self.tip:
            return
        x = self.w.winfo_rootx()
        y = self.w.winfo_rooty() + self.w.winfo_height() + 2
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#333", fg="white", padx=6, pady=3).pack()

    def hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def _icon_path():
    base = getattr(sys, "_MEIPASS", None)
    p = os.path.join(base, "app.ico") if base else os.path.join(APP_DIR, "assets", "app.ico")
    return p if os.path.exists(p) else None


def _report_error(exc, val, tb):
    import traceback
    msg = "".join(traceback.format_exception(exc, val, tb))
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(os.path.join(APP_DIR, "error_log.txt"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S\n") + msg + "\n")
    except OSError:
        pass
    messagebox.showerror(T("error_title"), msg[-1500:])


def _windows_setup():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SoundClicker")
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--selftest"]:
        from .selftest import run_selftest
        sys.exit(run_selftest(argv[1] if len(argv) > 1 else None))
    _windows_setup()
    root = tk.Tk()
    root.report_callback_exception = _report_error
    ico = _icon_path()
    if ico and sys.platform == "win32":
        try:
            root.iconbitmap(default=ico)
        except Exception:  # noqa: BLE001
            pass
    try:
        from pynput import keyboard, mouse
    except ImportError:
        root.withdraw()
        set_lang(detect_lang())
        messagebox.showerror(T("missing_pkg_title"), T("missing_pkg"))
        sys.exit(1)
    App(root, mouse, keyboard)
    root.mainloop()
