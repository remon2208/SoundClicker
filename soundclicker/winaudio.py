"""Windows-only: capture the audio of a single application (Windows 10 2004+), list windows."""

import ctypes
import os
import sys
import threading
import time
import uuid

import numpy as np

from .engine import SR, find_input
from .i18n import T

WINDOW_CAPTURE_MIN_BUILD = 19041
_W = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
_KEEP = []          # objects handed to Windows must never be garbage-collected


def window_capture_supported():
    if sys.platform != "win32":
        return False, T("win_only_windows")
    try:
        build = sys.getwindowsversion().build
    except Exception:  # noqa: BLE001
        return False, T("win_unknown_version")
    if build < WINDOW_CAPTURE_MIN_BUILD:
        return False, T("win_too_old", build=build)
    return True, ""


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    ctypes.memmove(ctypes.byref(g), uuid.UUID(s).bytes_le, 16)
    return g


IID_IUnknown = _guid("00000000-0000-0000-C000-000000000046")
IID_IAgileObject = _guid("94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90")
IID_IActivateCompletion = _guid("41D949AB-9862-444A-80F6-C261334DA5EB")
IID_IAudioClient = _guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = _guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
_HANDLER_IIDS = {bytes(IID_IUnknown), bytes(IID_IAgileObject), bytes(IID_IActivateCompletion)}
E_NOINTERFACE = -2147467262      # 0x80004002


class _LoopbackParams(ctypes.Structure):
    _fields_ = [("TargetProcessId", ctypes.c_uint32), ("ProcessLoopbackMode", ctypes.c_int)]


class _ActivationParams(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int), ("ProcessLoopbackParams", _LoopbackParams)]


class _Blob(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("pBlobData", ctypes.c_void_p)]


class _PropVariant(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("blob", _Blob)]


class _WaveFormatEx(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_uint16), ("nChannels", ctypes.c_uint16),
                ("nSamplesPerSec", ctypes.c_uint32), ("nAvgBytesPerSec", ctypes.c_uint32),
                ("nBlockAlign", ctypes.c_uint16), ("wBitsPerSample", ctypes.c_uint16),
                ("cbSize", ctypes.c_uint16)]


def _vcall(ptr, index, restype, argtypes, *args):
    """Calls method number `index` of a COM object's vtable."""
    p = ptr.value if isinstance(ptr, ctypes.c_void_p) else ptr
    vtbl = ctypes.cast(ctypes.c_void_p(p), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    fn = _W(restype, ctypes.c_void_p, *argtypes)(vtbl[index])
    return fn(p, *args)


def _release(ptr):
    if ptr is not None and (ptr.value if isinstance(ptr, ctypes.c_void_p) else ptr):
        _vcall(ptr, 2, ctypes.c_ulong, [])


def _hr_text(hr):
    return f"0x{hr & 0xFFFFFFFF:08X}"


def _check(hr, what):
    if hr < 0:
        raise OSError(f"{what} failed ({_hr_text(hr)})")


class _CompletionHandler:
    """A ctypes IActivateAudioInterfaceCompletionHandler (it also claims IAgileObject)."""

    def __init__(self):
        self.done = threading.Event()
        self.hr = None
        self.client = None
        qi = _W(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
        ref = _W(ctypes.c_ulong, ctypes.c_void_p)
        fin = _W(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
        self._cbs = (qi(self._qi), ref(self._addref), ref(self._release), fin(self._completed))
        self._vtbl = (ctypes.c_void_p * 4)(*[ctypes.cast(c, ctypes.c_void_p).value for c in self._cbs])
        self._obj = (ctypes.c_void_p * 1)(ctypes.addressof(self._vtbl))
        self.ptr = ctypes.c_void_p(ctypes.addressof(self._obj))
        _KEEP.append(self)

    def _qi(self, this, riid, ppv):
        try:
            if bytes(riid.contents) in _HANDLER_IIDS:
                ppv[0] = self.ptr.value
                return 0
            ppv[0] = None
        except Exception:  # noqa: BLE001
            pass
        return E_NOINTERFACE

    def _addref(self, this):
        return 2

    def _release(self, this):
        return 1

    def _completed(self, this, op):
        try:
            hr = ctypes.c_long(0)
            punk = ctypes.c_void_p()
            r = _vcall(op, 3, ctypes.c_long, [ctypes.POINTER(ctypes.c_long),
                                              ctypes.POINTER(ctypes.c_void_p)],
                       ctypes.byref(hr), ctypes.byref(punk))
            self.hr = hr.value if r >= 0 else r
            self.client = punk if (r >= 0 and hr.value >= 0) else None
        except Exception:  # noqa: BLE001
            self.hr = -1
        finally:
            self.done.set()
        return 0


def _activate_process_loopback(pid):
    mmdev = ctypes.WinDLL("Mmdevapi.dll")
    fn = mmdev.ActivateAudioInterfaceAsync
    fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(_GUID), ctypes.POINTER(_PropVariant),
                   ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    fn.restype = ctypes.c_long
    params = _ActivationParams(1, _LoopbackParams(int(pid), 0))   # 1 = process loopback; 0 = include child processes
    pv = _PropVariant()
    pv.vt = 65                                                   # VT_BLOB
    pv.blob.cbSize = ctypes.sizeof(params)
    pv.blob.pBlobData = ctypes.addressof(params)
    handler = _CompletionHandler()
    _KEEP.append((params, pv))
    op = ctypes.c_void_p()
    hr = fn("VAD\\Process_Loopback", ctypes.byref(IID_IAudioClient), ctypes.byref(pv),
            handler.ptr, ctypes.byref(op))
    _check(hr, "ActivateAudioInterfaceAsync")
    ok = handler.done.wait(5.0)
    _release(op)
    if not ok:
        raise OSError("ActivateAudioInterfaceAsync timed out")
    if handler.hr is None or handler.hr < 0 or handler.client is None:
        raise OSError(f"activation failed ({_hr_text(handler.hr or -1)})")
    return handler.client


class _LinearResampler:
    """Streaming linear-interpolation resampler (chunks join seamlessly)."""

    def __init__(self, sr_in, sr_out):
        self.step = sr_in / sr_out
        self.pos = 0.0
        self.tail = np.zeros(0, dtype=np.float32)

    def __call__(self, x):
        buf = np.concatenate([self.tail, x])
        if len(buf) < 2:
            self.tail = buf
            return np.zeros(0, dtype=np.float32)
        last = len(buf) - 1
        n = int(np.floor((last - self.pos) / self.step)) + 1
        if n <= 0:
            self.tail = buf
            return np.zeros(0, dtype=np.float32)
        idx = self.pos + self.step * np.arange(n)
        out = np.interp(idx, np.arange(len(buf)), buf).astype(np.float32)
        nxt = idx[-1] + self.step
        keep = int(np.floor(nxt))
        self.tail = buf[keep:]
        self.pos = nxt - keep
        return out


class ProcessLoopback:
    """Records only the audio of one process (and its children). Same interface as a soundcard recorder."""

    # (sample rate, format 3=float / 1=PCM, bits)
    FORMATS = [(48000, 3, 32), (44100, 3, 32), (48000, 1, 16), (44100, 1, 16)]
    LOOPBACK, EVENTCALLBACK, AUTOCONVERT, SRC_QUALITY = 0x00020000, 0x00040000, 0x80000000, 0x08000000

    def __init__(self, pid):
        self.pid = int(pid)
        self.client = self.cap = self.event = None
        self.buf = np.zeros(0, dtype=np.float32)
        self.clock = None
        self.resample = None

    def __enter__(self):
        try:
            self.open()
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def open(self):
        last = None
        flag_sets = [self.LOOPBACK | self.EVENTCALLBACK | self.AUTOCONVERT | self.SRC_QUALITY,
                     self.LOOPBACK | self.EVENTCALLBACK]
        for flags in flag_sets:
            for rate, tag, bits in self.FORMATS:
                client = _activate_process_loopback(self.pid)
                align = 2 * bits // 8
                wf = _WaveFormatEx(tag, 2, rate, rate * align, align, bits, 0)
                hr = _vcall(client, 3, ctypes.c_long,
                            [ctypes.c_int, ctypes.c_uint32, ctypes.c_longlong, ctypes.c_longlong,
                             ctypes.POINTER(_WaveFormatEx), ctypes.c_void_p],
                            0, flags, 2_000_000, 0, ctypes.byref(wf), None)
                if hr >= 0:
                    self.client, self.rate, self.tag, self.align = client, rate, tag, align
                    break
                last = hr
                _release(client)
            if self.client is not None:
                break
        if self.client is None:
            raise OSError(f"Initialize failed ({_hr_text(last or -1)})")
        cap = ctypes.c_void_p()
        _check(_vcall(self.client, 14, ctypes.c_long,
                      [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)],
                      ctypes.byref(IID_IAudioCaptureClient), ctypes.byref(cap)), "GetService")
        self.cap = cap
        k32 = ctypes.WinDLL("kernel32")
        k32.CreateEventW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p]
        k32.CreateEventW.restype = ctypes.c_void_p
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k32.WaitForSingleObject.restype = ctypes.c_uint32
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        self.k32 = k32
        self.event = k32.CreateEventW(None, 0, 0, None)
        _check(_vcall(self.client, 13, ctypes.c_long, [ctypes.c_void_p], self.event), "SetEventHandle")
        _check(_vcall(self.client, 10, ctypes.c_long, []), "Start")
        if self.rate != SR:
            self.resample = _LinearResampler(self.rate, SR)

    def _drain(self):
        n = ctypes.c_uint32()
        while True:
            _check(_vcall(self.cap, 5, ctypes.c_long, [ctypes.POINTER(ctypes.c_uint32)],
                          ctypes.byref(n)), "GetNextPacketSize")
            if n.value == 0:
                return
            data, frames, flags = ctypes.c_void_p(), ctypes.c_uint32(), ctypes.c_uint32()
            _check(_vcall(self.cap, 3, ctypes.c_long,
                          [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
                           ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p],
                          ctypes.byref(data), ctypes.byref(frames), ctypes.byref(flags), None, None),
                   "GetBuffer")
            nf = frames.value
            if nf and data.value and not (flags.value & 0x2):         # 0x2 = silent packet
                raw = ctypes.string_at(data.value, nf * self.align)
                if self.tag == 3:
                    x = np.frombuffer(raw, dtype="<f4").reshape(-1, 2).mean(axis=1)
                else:
                    x = np.frombuffer(raw, dtype="<i2").reshape(-1, 2).mean(axis=1) / 32768.0
            else:
                x = np.zeros(nf, dtype=np.float32)
            _vcall(self.cap, 4, ctypes.c_long, [ctypes.c_uint32], nf)
            x = x.astype(np.float32)
            if self.resample is not None:
                x = self.resample(x)
            self.buf = np.concatenate([self.buf, x])

    def record(self, numframes):
        """Returns (numframes, 1). Windows sends nothing while the app is silent, so silence is filled in by the clock."""
        now = time.time()
        if self.clock is None or self.clock < now - 0.2:
            self.clock = now
        target = self.clock + numframes / SR
        self._drain()
        while len(self.buf) < numframes:
            remaining = target + 0.03 - time.time()
            if remaining <= 0:
                break
            self.k32.WaitForSingleObject(self.event, max(1, int(min(remaining, 0.02) * 1000)))
            self._drain()
        if len(self.buf) < numframes:
            self.buf = np.concatenate([self.buf, np.zeros(numframes - len(self.buf), np.float32)])
        out, self.buf = self.buf[:numframes], self.buf[numframes:]
        if len(self.buf) > SR:                      # more than 1 s behind: drop the backlog
            self.buf = self.buf[-numframes:]
        self.clock = target
        return out[:, None]

    def close(self):
        try:
            if self.client is not None:
                _vcall(self.client, 11, ctypes.c_long, [])
        except Exception:  # noqa: BLE001
            pass
        for p in (self.cap, self.client):
            try:
                _release(p)
            except Exception:  # noqa: BLE001
                pass
        self.cap = self.client = None
        if self.event:
            try:
                self.k32.CloseHandle(self.event)
            except Exception:  # noqa: BLE001
                pass
            self.event = None


def _user32():
    u = ctypes.WinDLL("user32")
    H = ctypes.c_void_p
    u.IsWindowVisible.argtypes = [H]
    u.GetWindowTextLengthW.argtypes = [H]
    u.GetWindowTextW.argtypes = [H, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindowLongW.argtypes = [H, ctypes.c_int]
    u.GetWindow.argtypes = [H, ctypes.c_uint]
    u.GetWindow.restype = H
    u.GetWindowThreadProcessId.argtypes = [H, ctypes.POINTER(ctypes.c_uint32)]
    return u


def process_name(pid):
    k32 = ctypes.WinDLL("kernel32")
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p,
                                               ctypes.POINTER(ctypes.c_uint32)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenProcess(0x1000, 0, int(pid))          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return "?"
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_uint32(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return "?"
    finally:
        k32.CloseHandle(h)


def pid_alive(pid):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.OpenProcess(0x1000, 0, int(pid))
    if not h:
        return ctypes.get_last_error() == 5          # access denied (e.g. elevated app): assume alive
    try:
        code = ctypes.c_uint32()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
            return True
        return code.value == 259                          # STILL_ACTIVE
    finally:
        k32.CloseHandle(h)


def list_windows():
    """Visible top-level windows as [{pid, title, exe}], one per process, in Z-order."""
    u = _user32()
    try:
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                              ctypes.c_uint32]
    except OSError:
        dwm = None
    me = os.getpid()
    seen, out = set(), []
    proto = _W(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)

    def cb(hwnd, _lp):
        try:
            if not u.IsWindowVisible(hwnd):
                return 1
            n = u.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return 1
            if u.GetWindowLongW(hwnd, -20) & 0x80:          # WS_EX_TOOLWINDOW
                return 1
            if u.GetWindow(hwnd, 4):                         # owned (dialog-like) window
                return 1
            if dwm is not None:
                cloaked = ctypes.c_int(0)
                if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4) == 0 and cloaked.value:
                    return 1
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title or title == "Program Manager":
                return 1
            pid = ctypes.c_uint32()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in seen or pid.value == me:
                return 1
            seen.add(pid.value)
            out.append(dict(pid=pid.value, title=title, exe=process_name(pid.value)))
        except Exception:  # noqa: BLE001
            pass
        return 1

    callback = proto(cb)
    u.EnumWindows.argtypes = [proto, ctypes.c_void_p]
    u.EnumWindows(callback, None)
    return out


def friendly_error(e, src=None):
    msg = str(e) or type(e).__name__
    if src and src.get("kind") == "window" and isinstance(e, OSError):
        return T("err_window_capture", title=src["title"], msg=msg)
    return msg


def open_source(sc, src):
    """Opens the chosen source. Returns (recorder context manager, display name, fell back to default?)."""
    if src["kind"] == "window":
        return ProcessLoopback(src["pid"]), T("src_window_label", title=src["title"]), False
    mic, fell_back = find_input(sc, src["name"], src["loop"])
    return mic.recorder(samplerate=SR), mic.name, fell_back
