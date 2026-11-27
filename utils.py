# --- utils.py ---

import ctypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import cv2
import numpy as np
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.03

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

# Thread-safe ADB and vision caches
_adb_lock = threading.RLock()
_adb_device_id = None
_adb_resolution = None
_scale_cache = {}
_template_cache = {}
_digit_templates = None

# Normalized ROIs (x1, y1, x2, y2) relative to a 1600x900 Clash viewport
ENEMY_LOOT_ROIS = {
    "enemy_gold": (0.044, 0.095, 0.180, 0.142),
    "enemy_elixir": (0.044, 0.153, 0.180, 0.200),
    "enemy_dark": (0.044, 0.212, 0.180, 0.262),
}

SCOUT_OWN_ROIS = {
    "own_gold": (0.790, 0.004, 0.953, 0.055),
    "own_elixir": (0.790, 0.070, 0.953, 0.125),
    "own_dark": (0.790, 0.136, 0.953, 0.192),
}

HOME_OWN_ROIS = {
    "own_gold": (0.790, 0.030, 0.953, 0.080),
    "own_elixir": (0.790, 0.095, 0.953, 0.145),
    "own_dark": (0.790, 0.160, 0.953, 0.212),
}

# When the Buildings & Heroes drawer is open on the right, own resource bars shift left
HOME_DRAWER_OWN_ROIS = {
    "own_gold": (0.545, 0.030, 0.688, 0.080),
    "own_elixir": (0.545, 0.095, 0.688, 0.145),
    "own_dark": (0.545, 0.160, 0.688, 0.212),
}

LOOT_ROIS = {**ENEMY_LOOT_ROIS, **SCOUT_OWN_ROIS}

# Deployment points for keys 0-9 as percentages of the base viewport
KEY_PERCENT_MAP = {
    '1': (0.5585, 0.7248),
    '2': (0.5980, 0.6656),
    '3': (0.6375, 0.6142),
    '4': (0.6757, 0.5606),
    '5': (0.7127, 0.5081),
    '6': (0.7528, 0.4578),
    '7': (0.7923, 0.3975),
    '8': (0.8425, 0.3327),
    '9': (0.5196, 0.7752),
    '0': (0.8738, 0.2891),
}

# Android KeyEvent code map for fallback and daemon key dispatch
ANDROID_KEYCODE_MAP = {
    'esc': 4,
    'escape': 4,
    'back': 4,
    'enter': 66,
    'space': 62,
    '`': 68,
    '[': 71,
    ']': 72,
}
for _idx, _ch in enumerate("0123456789"):
    ANDROID_KEYCODE_MAP[_ch] = 7 + _idx
for _idx, _ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    ANDROID_KEYCODE_MAP[_ch] = 29 + _idx


def get_resource_path(relative_path):
    """Resolves resource path seamlessly whether running as script or compiled exe."""
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        local_path = os.path.join(exe_dir, relative_path)
        if os.path.exists(local_path):
            return local_path
    if os.path.exists(relative_path):
        return os.path.abspath(relative_path)
    if hasattr(sys, '_MEIPASS'):
        bundle_path = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(bundle_path):
            return bundle_path
    return relative_path


def _ensure_desktop():
    """Attaches thread to interactive Default desktop without leaking desktop handles."""
    h_desk = None
    user32 = ctypes.windll.user32
    try:
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass
    finally:
        if h_desk:
            try:
                user32.CloseDesktop(h_desk)
            except Exception:
                pass


def _get_hwnd_process_basename(hwnd):
    """Returns lowercase executable basename for a window handle, or empty string."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h_proc = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h_proc:
        return ""
    try:
        buf_len = wintypes.DWORD(512)
        buf = ctypes.create_unicode_buffer(512)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(buf_len)):
            return os.path.basename(buf.value).lower()
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(h_proc)
    return ""


def find_bluestacks_windows():
    """Locates the top-level BlueStacks Player window and its inner viewport child."""
    _ensure_desktop()
    user32 = ctypes.windll.user32
    candidates = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def enum_cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        title = buf.value.lower()
        if 'overlay' in title or 'trainer' in title or 'web' in title:
            return True

        proc_name = _get_hwnd_process_basename(hwnd)
        if proc_name == 'hd-player.exe' or 'bluestacks' in title:
            candidates.append((hwnd, proc_name == 'hd-player.exe'))
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    if not candidates:
        return None, None

    candidates.sort(key=lambda item: (0 if item[1] else 1))

    best_main = None
    best_render = None
    for main_hwnd, is_hd in candidates:
        render_hwnds = []

        def enum_child(hwnd, lparam):
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            rect = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            render_hwnds.append((hwnd, cls.value.lower(), w, h))
            return True

        user32.EnumChildWindows(main_hwnd, WNDENUMPROC(enum_child), 0)

        for ch_hwnd, cls_name, w, h in render_hwnds:
            if 'bluestacksapp' in cls_name:
                if w >= 400 and h >= 300:
                    return main_hwnd, ch_hwnd
                if best_main is None:
                    best_main = main_hwnd
                    best_render = ch_hwnd
        if is_hd and best_main is None:
            best_main = main_hwnd
            best_render = render_hwnds[0][0] if render_hwnds else main_hwnd

    return best_main, best_render


def ensure_bluestacks_active(status_callback=None):
    """Brings BlueStacks to foreground cleanly for foreground-mode input."""
    _ensure_desktop()
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    main_hwnd, _ = find_bluestacks_windows()
    if not main_hwnd:
        if status_callback:
            status_callback("Warning: BlueStacks window not found.")
        return False

    try:
        if user32.IsIconic(main_hwnd):
            user32.ShowWindow(main_hwnd, 9)  # SW_RESTORE
            time.sleep(0.12)

        fg = user32.GetForegroundWindow()
        if fg != main_hwnd:
            user32.ShowWindow(main_hwnd, 5)  # SW_SHOW
            cur_thread = kernel32.GetCurrentThreadId()
            fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
            attached = False
            if fg_thread and fg_thread != cur_thread:
                attached = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
            try:
                user32.SetForegroundWindow(main_hwnd)
                user32.BringWindowToTop(main_hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(cur_thread, fg_thread, False)
            time.sleep(0.12)
        return True
    except Exception:
        return False


def normalized_to_action_coords(nx, ny, background_mode=False, source_size=(1600, 900)):
    """Converts normalized coordinates from source_size to ADB or desktop click coordinates."""
    sw, sh = source_size
    if background_mode:
        aw, ah = get_adb_resolution()
        return (int(round(nx * aw / sw)), int(round(ny * ah / sh)))

    _, render_hwnd = find_bluestacks_windows()
    if render_hwnd:
        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if user32.GetClientRect(render_hwnd, ctypes.byref(rect)):
            vw = rect.right - rect.left
            vh = rect.bottom - rect.top
            if vw >= 400 and vh >= 300:
                pt = wintypes.POINT(0, 0)
                user32.ClientToScreen(render_hwnd, ctypes.byref(pt))
                return (pt.x + int(round(nx * vw / sw)), pt.y + int(round(ny * vh / sh)))

    scr_w, scr_h = pyautogui.size()
    return (int(round(nx * scr_w / sw)), int(round(ny * scr_h / sh)))


def get_adb_path():
    """Locates the built-in HD-Adb executable from the local BlueStacks installation."""
    candidates = [
        r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        r"C:\Program Files (x86)\BlueStacks_nxt\HD-Adb.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _run_adb(args, timeout=5, capture_output=True):
    """Executes an HD-Adb command cleanly with hidden console window."""
    adb_path = get_adb_path()
    if not adb_path:
        return None
    kwargs = {
        "timeout": timeout,
        "stdin": subprocess.DEVNULL,
        "creationflags": CREATE_NO_WINDOW,
    }
    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    else:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    return subprocess.run([adb_path] + list(args), **kwargs)


def _read_bluestacks_adb_ports():
    """Reads configured BlueStacks ADB ports from bluestacks.conf, defaulting to 5555."""
    ports = []
    conf_path = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"
    if os.path.exists(conf_path):
        try:
            with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            for match in re.finditer(r'adb_port\s*=\s*"(\d+)"', text):
                p = match.group(1)
                if p not in ports:
                    ports.append(p)
        except Exception:
            pass
    if "5555" not in ports:
        ports.append("5555")
    return ports


def _parse_adb_devices(stdout_text):
    """Parses attached online devices from 'adb devices' output."""
    devices = []
    for line in stdout_text.strip().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    if not devices:
        return None
    for preferred in devices:
        if preferred.startswith("emulator-"):
            return preferred
    return devices[0]


def get_adb_device(force_refresh=False, try_connect=True):
    """Finds and caches an attached BlueStacks ADB device identifier."""
    global _adb_device_id
    with _adb_lock:
        if _adb_device_id and not force_refresh:
            return _adb_device_id

        try:
            res = _run_adb(["devices"], timeout=6, capture_output=True)
            if res and res.returncode == 0:
                dev = _parse_adb_devices(res.stdout.decode("utf-8", errors="ignore"))
                if dev:
                    _adb_device_id = dev
                    return _adb_device_id
        except Exception:
            pass

        if try_connect:
            for port in _read_bluestacks_adb_ports():
                try:
                    _run_adb(["connect", f"127.0.0.1:{port}"], timeout=3, capture_output=True)
                except Exception:
                    pass
            try:
                res = _run_adb(["devices"], timeout=5, capture_output=True)
                if res and res.returncode == 0:
                    dev = _parse_adb_devices(res.stdout.decode("utf-8", errors="ignore"))
                    if dev:
                        _adb_device_id = dev
                        return _adb_device_id
            except Exception:
                pass

        _adb_device_id = None
        return None


def invalidate_adb_state():
    """Resets cached ADB connection and stops touch daemon so next check reconnects cleanly."""
    global _adb_device_id, _adb_resolution
    with _adb_lock:
        _adb_device_id = None
        _adb_resolution = None
    _touch_daemon.stop()


def is_adb_ready(force_refresh=False, try_connect=True):
    """Returns True if BlueStacks local ADB is available and responding."""
    return get_adb_device(force_refresh=force_refresh, try_connect=try_connect) is not None


def get_adb_resolution():
    """Queries and caches Android framebuffer resolution (Override or Physical)."""
    global _adb_resolution
    with _adb_lock:
        if _adb_resolution:
            return _adb_resolution
        dev = get_adb_device(try_connect=False)
        if not dev:
            return (1600, 900)
        try:
            res = _run_adb(["-s", dev, "shell", "wm", "size"], timeout=4, capture_output=True)
            if res and res.returncode == 0:
                txt = res.stdout.decode("utf-8", errors="ignore")
                override_m = re.search(r"Override size:\s*(\d+)x(\d+)", txt)
                phys_m = re.search(r"Physical size:\s*(\d+)x(\d+)", txt)
                match = override_m or phys_m
                if match:
                    w, h = int(match.group(1)), int(match.group(2))
                    if w > 0 and h > 0:
                        _adb_resolution = (w, h)
                        return _adb_resolution
        except Exception:
            pass
        _adb_resolution = (1600, 900)
        return _adb_resolution


def get_scaled_point(key, width=None, height=None):
    """Calculates pixel coordinates of a mapped deployment key for Android resolution."""
    if width is None or height is None:
        width, height = get_adb_resolution()
    if key in KEY_PERCENT_MAP:
        x_pct, y_pct = KEY_PERCENT_MAP[key]
        return (int(round(x_pct * width)), int(round(y_pct * height)))
    return (int(width * 0.5), int(height * 0.5))


class _TouchDaemon:
    """
    Persistent ADB shell helper running ClashTouch inside Android for low-latency
    taps, smooth pans, and genuine multi-touch pinch zoom without console flashes.
    """

    REMOTE_JAR = "/data/local/tmp/clash_touch.jar"

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self._device = None
        self._pushed_devices = set()
        self._line_queue = None
        self._reader_thread = None
        self._retry_after = 0.0

    def _reader_loop(self, proc, q):
        try:
            for line in proc.stdout:
                q.put(line.strip())
        except Exception:
            pass
        finally:
            q.put(None)

    def stop(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        proc = self._proc
        self._proc = None
        self._device = None
        self._line_queue = None
        if proc:
            try:
                if proc.stdin:
                    proc.stdin.write("quit\n")
                    proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.wait(timeout=0.6)
            except Exception:
                try:
                    proc.terminate()
                    proc.wait(timeout=0.8)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    def ensure_started(self):
        with self._lock:
            if time.time() < self._retry_after:
                return False
            adb_path = get_adb_path()
            dev = get_adb_device(try_connect=False)
            if not adb_path or not dev:
                return False

            if self._proc and self._proc.poll() is None and self._device == dev:
                return True

            self._close_locked()
            jar_path = get_resource_path(os.path.join("assets", "clash_touch.jar"))
            if not os.path.exists(jar_path):
                self._retry_after = time.time() + 30.0
                return False

            try:
                if dev not in self._pushed_devices:
                    push_res = _run_adb(["-s", dev, "push", jar_path, self.REMOTE_JAR], timeout=8, capture_output=True)
                    if not push_res or push_res.returncode != 0:
                        self._retry_after = time.time() + 10.0
                        return False
                    self._pushed_devices.add(dev)

                cmd = [
                    adb_path, "-s", dev, "shell",
                    f"CLASSPATH={self.REMOTE_JAR} app_process /system/bin ClashTouch"
                ]
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    creationflags=CREATE_NO_WINDOW,
                )
                q = queue.Queue()
                t = threading.Thread(target=self._reader_loop, args=(proc, q), daemon=True)
                t.start()

                first_line = q.get(timeout=5.0)
                if first_line == "READY":
                    self._proc = proc
                    self._device = dev
                    self._line_queue = q
                    self._reader_thread = t
                    return True
                proc.kill()
            except Exception:
                self._close_locked()

            self._retry_after = time.time() + 12.0
            return False

    def send(self, command_line, timeout=4.0):
        if not self.ensure_started():
            return False
        with self._lock:
            proc = self._proc
            q = self._line_queue
            if not proc or proc.poll() is not None or not q:
                self._close_locked()
                return False
            try:
                while not q.empty():
                    q.get_nowait()
                proc.stdin.write(command_line + "\n")
                proc.stdin.flush()
                reply = q.get(timeout=timeout)
                if reply == "OK":
                    return True
            except Exception:
                pass
            self._close_locked()
            return False


_touch_daemon = _TouchDaemon()


def ensure_touch_daemon():
    """Warms up the persistent ADB touch daemon for zero-latency background input."""
    return _touch_daemon.ensure_started()


def stop_touch_daemon():
    """Stops the persistent ADB touch daemon cleanly."""
    _touch_daemon.stop()


def adb_tap(x, y, hold_ms=16):
    """Executes a background touch tap via persistent ADB daemon or fallback shell."""
    ix, iy = int(round(x)), int(round(y))
    if _touch_daemon.send(f"tap {ix} {iy} {int(hold_ms)}", timeout=3.0):
        return True
    dev = get_adb_device(try_connect=False)
    if not dev:
        return False
    try:
        res = _run_adb(["-s", dev, "shell", "input", "tap", str(ix), str(iy)], timeout=4, capture_output=False)
        if res and res.returncode == 0:
            return True
    except Exception:
        pass
    invalidate_adb_state()
    return False


def adb_batch_taps(points_list):
    """Executes multiple background taps rapidly via daemon or single shell invocation."""
    if not points_list:
        return False
    if _touch_daemon.ensure_started():
        ok = True
        for x, y in points_list:
            if not _touch_daemon.send(f"tap {int(round(x))} {int(round(y))} 14", timeout=3.0):
                ok = False
                break
        if ok:
            return True
    dev = get_adb_device(try_connect=False)
    if not dev:
        return False
    try:
        cmd_str = "; ".join(f"input tap {int(round(x))} {int(round(y))}" for x, y in points_list)
        res = _run_adb(["-s", dev, "shell", cmd_str], timeout=10, capture_output=False)
        return bool(res and res.returncode == 0)
    except Exception:
        return False


def adb_swipe(x1, y1, x2, y2, duration_ms=220, steps=16):
    """Executes a smooth background swipe via persistent ADB daemon or fallback shell."""
    ix1, iy1 = int(round(x1)), int(round(y1))
    ix2, iy2 = int(round(x2)), int(round(y2))
    dur = max(60, int(duration_ms))
    if _touch_daemon.send(f"swipe {ix1} {iy1} {ix2} {iy2} {dur} {int(steps)}", timeout=max(4.0, dur / 1000.0 + 2.0)):
        return True
    dev = get_adb_device(try_connect=False)
    if not dev:
        return False
    try:
        res = _run_adb(
            ["-s", dev, "shell", "input", "swipe", str(ix1), str(iy1), str(ix2), str(iy2), str(dur)],
            timeout=max(5, dur // 1000 + 3),
            capture_output=False,
        )
        if res and res.returncode == 0:
            return True
    except Exception:
        pass
    return False


def adb_pinch_zoom(zoom_in=False, repeats=2, duration_ms=340):
    """Performs a native multi-touch pinch gesture in the background via ADB touch daemon."""
    w, h = get_adb_resolution()
    if zoom_in:
        x1s, x1e = int(w * 0.45), int(w * 0.24)
        x2s, x2e = int(w * 0.55), int(w * 0.76)
    else:
        x1s, x1e = int(w * 0.24), int(w * 0.46)
        x2s, x2e = int(w * 0.76), int(w * 0.54)
    y = int(h * 0.48)

    ok_any = False
    for idx in range(max(1, int(repeats))):
        if _touch_daemon.send(
            f"pinch {x1s} {y} {x1e} {y} {x2s} {y} {x2e} {y} {int(duration_ms)} 20",
            timeout=max(4.0, duration_ms / 1000.0 + 2.0),
        ):
            ok_any = True
        if idx + 1 < repeats:
            time.sleep(0.06)
    if ok_any:
        time.sleep(0.06)
    return ok_any


def adb_keyevent(key_or_code):
    """Sends an Android keyevent directly through ADB without stealing window focus."""
    if isinstance(key_or_code, int):
        code = key_or_code
    else:
        raw = str(key_or_code).strip().lower()
        if raw.isdigit():
            code = int(raw)
        else:
            code = ANDROID_KEYCODE_MAP.get(raw)
            if code is None:
                code = str(key_or_code)

    if isinstance(code, int) and _touch_daemon.send(f"key {code}", timeout=3.0):
        return True

    dev = get_adb_device(try_connect=False)
    if not dev:
        return False
    try:
        res = _run_adb(["-s", dev, "shell", "input", "keyevent", str(code)], timeout=4, capture_output=False)
        return bool(res and res.returncode == 0)
    except Exception:
        return False


def _resize_frame(img, target_w, target_h):
    """Resizes an image array to target dimensions only when dimensions differ."""
    h, w = img.shape[:2]
    if w == target_w and h == target_h:
        return img
    interp = cv2.INTER_AREA if w > target_w else cv2.INTER_LINEAR
    return cv2.resize(img, (target_w, target_h), interpolation=interp)


def _adb_screencap_frame(target_w, target_h, as_color=False):
    """Captures Android framebuffer via adb exec-out screencap resized to target dimensions."""
    dev = get_adb_device(try_connect=False)
    if not dev:
        return None
    try:
        res = _run_adb(["-s", dev, "exec-out", "screencap", "-p"], timeout=6, capture_output=True)
        if not res or res.returncode != 0 or not res.stdout:
            return None
        arr = np.frombuffer(res.stdout, dtype=np.uint8)
        flag = cv2.IMREAD_COLOR if as_color else cv2.IMREAD_GRAYSCALE
        img = cv2.imdecode(arr, flag)
        if img is None or img.size == 0:
            return None
        return _resize_frame(img, target_w, target_h)
    except Exception:
        return None


def _printwindow_frame(render_hwnd, target_w, target_h, as_color=False):
    """Captures BlueStacks viewport via PrintWindow cleanly with guaranteed GDI cleanup."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd_dc = None
    mfc_dc = None
    save_bmp = None
    old_bmp = None
    try:
        rect = wintypes.RECT()
        user32.GetClientRect(render_hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 400 or h < 300:
            return None

        hwnd_dc = user32.GetDC(render_hwnd)
        if not hwnd_dc:
            return None
        mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        save_bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
        if not mfc_dc or not save_bmp:
            return None
        old_bmp = gdi32.SelectObject(mfc_dc, save_bmp)

        res = user32.PrintWindow(render_hwnd, mfc_dc, 2)  # PW_RENDERFULLCONTENT
        if not res:
            return None

        struct_fmt = ctypes.c_uint32 * 10
        bmi = struct_fmt(40, w, -h, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mfc_dc, save_bmp, 0, h, buf, ctypes.byref(bmi), 0)

        bgra = np.frombuffer(buf, dtype=np.uint8).reshape((h, w, 4))
        conv = cv2.COLOR_BGRA2BGR if as_color else cv2.COLOR_BGRA2GRAY
        img = cv2.cvtColor(bgra, conv)

        if float(np.std(img)) < 1.5:
            return None

        return _resize_frame(img, target_w, target_h)
    except Exception:
        return None
    finally:
        if mfc_dc and old_bmp:
            try:
                gdi32.SelectObject(mfc_dc, old_bmp)
            except Exception:
                pass
        if save_bmp:
            try:
                gdi32.DeleteObject(save_bmp)
            except Exception:
                pass
        if mfc_dc:
            try:
                gdi32.DeleteDC(mfc_dc)
            except Exception:
                pass
        if hwnd_dc:
            try:
                user32.ReleaseDC(render_hwnd, hwnd_dc)
            except Exception:
                pass


def _capture_background_frame(as_color=False):
    """Captures normalized Android frame via PrintWindow or ADB screencap fallback."""
    adb_w, adb_h = get_adb_resolution()
    user32 = ctypes.windll.user32
    main_hwnd, render_hwnd = find_bluestacks_windows()
    if render_hwnd and main_hwnd and not user32.IsIconic(main_hwnd):
        frame = _printwindow_frame(render_hwnd, adb_w, adb_h, as_color=as_color)
        if frame is not None:
            return frame
    return _adb_screencap_frame(adb_w, adb_h, as_color=as_color)


def capture_screen(background_mode=False):
    """Captures grayscale frame for template matching in Background or Foreground mode."""
    _ensure_desktop()
    if background_mode:
        return _capture_background_frame(as_color=False)
    try:
        screenshot = pyautogui.screenshot()
        return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    except Exception:
        return None


def capture_game_bgr(background_mode=False, target_size=(1600, 900)):
    """
    Captures color BGR game viewport normalized to 1600x900 regardless of whether
    BlueStacks is windowed, fullscreen, or running via Background Mode.
    """
    _ensure_desktop()
    tw, th = target_size
    if background_mode:
        frame = _capture_background_frame(as_color=True)
        return _resize_frame(frame, tw, th) if frame is not None else None

    try:
        screenshot = pyautogui.screenshot()
        bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        sh, sw = bgr.shape[:2]

        _, render_hwnd = find_bluestacks_windows()
        if render_hwnd:
            user32 = ctypes.windll.user32
            rect = wintypes.RECT()
            if user32.GetClientRect(render_hwnd, ctypes.byref(rect)):
                vw = rect.right - rect.left
                vh = rect.bottom - rect.top
                if vw >= 400 and vh >= 300:
                    pt = wintypes.POINT(0, 0)
                    user32.ClientToScreen(render_hwnd, ctypes.byref(pt))
                    x1 = max(0, pt.x)
                    y1 = max(0, pt.y)
                    x2 = min(sw, pt.x + vw)
                    y2 = min(sh, pt.y + vh)
                    if x2 - x1 >= 400 and y2 - y1 >= 300:
                        bgr = bgr[y1:y2, x1:x2]

        return _resize_frame(bgr, tw, th)
    except Exception:
        return None


def _get_tesseract_cmd():
    """Returns path to Tesseract executable if available on this system."""
    candidates = [
        r"C:\Nimit\tesseractOCR\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


try:
    import pytesseract
    _tess_bin = _get_tesseract_cmd()
    if _tess_bin:
        pytesseract.pytesseract.tesseract_cmd = _tess_bin
except ImportError:
    pytesseract = None


def _run_tesseract_tsv(img, psm=11):
    """Runs zero-flash Tesseract TSV OCR via stdin PNG and parses token boxes safely."""
    tess_bin = _get_tesseract_cmd()
    if not tess_bin or img is None or img.size == 0:
        return []
    ok, png_buf = cv2.imencode(".png", img)
    if not ok:
        return []
    try:
        res = subprocess.run(
            [tess_bin, "stdin", "stdout", "--psm", str(psm), "tsv"],
            input=png_buf.tobytes(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=6,
        )
        if res.returncode != 0:
            return []
        tokens = []
        lines = res.stdout.decode("utf-8", errors="ignore").splitlines()
        for ln in lines[1:]:
            cols = ln.split("\t")
            if len(cols) < 12:
                continue
            txt = cols[11].strip()
            if not txt:
                continue
            try:
                conf = float(cols[10])
                left = int(cols[6])
                top = int(cols[7])
                width = int(cols[8])
                height = int(cols[9])
            except ValueError:
                continue
            tokens.append({
                "text": txt,
                "conf": conf,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "cx": left + width // 2,
                "cy": top + height // 2,
            })
        return tokens
    except Exception:
        return []


def _load_digit_templates():
    """Loads bundled Supercell-Magic digit bitmaps 0-9 into memory."""
    global _digit_templates
    if _digit_templates is not None:
        return _digit_templates
    loaded = {}
    for d in range(10):
        path = get_resource_path(os.path.join("assets", "digits", f"{d}.png"))
        if os.path.exists(path):
            im = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if im is not None:
                loaded[str(d)] = im
    _digit_templates = loaded
    return _digit_templates


def _extract_white_digit_mask(crop_bgr):
    """Isolates crisp white HUD digit pixels while rejecting colored village/scenery elements."""
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 1] < 85) & (hsv[:, :, 2] > 180)).astype(np.uint8) * 255


def _score_glyph(glyph, tmpls):
    """Scores a single segmented white digit glyph against bundled 0-9 templates."""
    gh, gw = glyph.shape[:2]
    g_ar = gw / float(gh)
    best_d, best_s, second_s = '', -999.0, -999.0
    for d, t in tmpls.items():
        th, tw = t.shape[:2]
        ar_diff = abs(g_ar - tw / float(th))
        if ar_diff > 0.35:
            continue
        rg = _resize_frame(glyph, tw, th)
        gn = rg.astype(np.float32) / 255.0
        tn = t.astype(np.float32) / 255.0
        denom = float(np.sqrt(np.sum(gn ** 2) * np.sum(tn ** 2)) + 1e-6)
        cos = float(np.sum(gn * tn)) / denom
        sc = cos - 0.35 * ar_diff
        if sc > best_s:
            second_s = best_s
            best_s = sc
            best_d = d
        elif sc > second_s:
            second_s = sc
    return best_d, best_s, best_s - second_s


def _sliding_decode_mask(mask, tmpls):
    """Decodes digits via multi-scale sliding-window correlation when glyphs touch."""
    pad = cv2.copyMakeBorder(mask, 8, 8, 8, 8, cv2.BORDER_CONSTANT, value=0)
    hits = []
    for d, t in tmpls.items():
        for s in (0.95, 1.0, 1.05):
            tw = max(3, int(round(t.shape[1] * s)))
            th = max(8, int(round(t.shape[0] * s)))
            rt = cv2.resize(t, (tw, th))
            if th > pad.shape[0] or tw > pad.shape[1]:
                continue
            res = cv2.matchTemplate(pad, rt, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res >= 0.72)
            for y, x in zip(ys, xs):
                hits.append((float(res[y, x]), x + tw / 2.0, tw, d))
    hits.sort(key=lambda h: h[0], reverse=True)
    kept = []
    for score, cx, w, d in hits:
        if any(abs(cx - kcx) < max(4.5, min(w, kw) * 0.55) for _, kcx, kw, _ in kept):
            continue
        kept.append((score, cx, w, d))
    kept.sort(key=lambda h: h[1])
    digits = "".join(h[3] for h in kept)
    return int(digits) if digits else 0


def _decode_anchored_crop(crop_bgr, anchor, tmpls):
    """
    Decodes HUD resource numbers using Y-band alignment, left/right contiguity clustering,
    and template scoring so nearby bright white walls/buildings never pollute digits.
    Returns (value, needs_fallback, tight_crop_or_None).
    """
    ch, cw = crop_bgr.shape[:2]
    mask = _extract_white_digit_mask(crop_bgr)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask)

    cands = []
    wide_cands = []
    for i in range(1, num_labels):
        x, y, w, h, area = (int(v) for v in stats[i])
        if 14 <= h <= 24 and area >= 36:
            if 4 <= w <= 22:
                cands.append((x, y, w, h))
            elif 23 <= w <= 48:
                wide_cands.append((x, y, w, h))

    # Group digit-sized boxes into horizontal baseline bands (<= 4.5px Y drift)
    bands = []
    for box in sorted(cands, key=lambda b: b[1] + b[3] / 2.0):
        yc = box[1] + box[3] / 2.0
        placed = False
        for b_entry in bands:
            if abs(yc - b_entry[0]) <= 4.5:
                b_entry[1].append(box)
                placed = True
                break
        if not placed:
            bands.append([yc, [box]])

    best_cluster = None
    best_digits = None
    best_rank = -1.0
    needs_fb = False

    for _, boxes in bands:
        boxes.sort(key=lambda b: b[0])
        clusters = [[boxes[0]]]
        for b in boxes[1:]:
            gap = b[0] - (clusters[-1][-1][0] + clusters[-1][-1][2])
            if gap <= 24:
                clusters[-1].append(b)
            else:
                clusters.append([b])

        for cl in clusters:
            if anchor == 'right' and (cl[-1][0] + cl[-1][2]) < cw * 0.55:
                continue
            if anchor == 'left' and cl[0][0] > cw * 0.45:
                continue
            if not tmpls:
                return 0, True, crop_bgr

            decoded = []
            sc_sum = 0.0
            low_conf = False
            for x, y, w, h in cl:
                d, sc, margin = _score_glyph(mask[y:y + h, x:x + w], tmpls)
                if d and sc >= 0.72:
                    decoded.append((d, sc, h))
                    sc_sum += sc
                    if sc < 0.78 or margin < 0.018:
                        low_conf = True
            if not decoded:
                continue
            avg_h = sum(h for _, _, h in decoded) / len(decoded)
            rank = sc_sum * (1.0 if avg_h >= 16.0 else 0.5)
            if rank > best_rank:
                best_rank = rank
                best_cluster = cl
                best_digits = "".join(d for d, _, _ in decoded)
                needs_fb = low_conf

    if best_cluster is not None and not needs_fb:
        return int(best_digits), False, None

    if best_cluster is not None and needs_fb:
        x0 = max(0, best_cluster[0][0] - 8)
        y0 = max(0, min(b[1] for b in best_cluster) - 8)
        x1 = min(cw, best_cluster[-1][0] + best_cluster[-1][2] + 8)
        y1 = min(ch, max(b[1] + b[3] for b in best_cluster) + 8)
        return int(best_digits), True, crop_bgr[y0:y1, x0:x1]

    # Check if wide touching digit blobs exist near anchor
    anchored_wide = [
        b for b in wide_cands
        if ((anchor == 'right' and b[0] + b[2] >= cw * 0.55) or (anchor == 'left' and b[0] <= cw * 0.45))
    ]
    if anchored_wide:
        if tmpls:
            sl_val = _sliding_decode_mask(mask, tmpls)
            if sl_val > 0:
                return sl_val, False, None
        return 0, True, crop_bgr

    return 0, False, None


def _tesseract_batch_crops(crops_by_name):
    """
    Runs a single zero-flash batched Tesseract pass (1.5x scale, PSM 6) across ambiguous
    resource strips, aligning tokens by vertical strip coordinates.
    """
    tess_bin = _get_tesseract_cmd()
    if not tess_bin or not crops_by_name:
        return {}

    strips = []
    max_w = 0
    for name, crop_bgr in crops_by_name:
        up = cv2.resize(crop_bgr, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        mask = _extract_white_digit_mask(up)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        sh = mask.shape[0]
        clean = np.zeros_like(mask)
        xs = []
        for idx in range(1, num_labels):
            x, y, w, h, area = stats[idx]
            if h >= int(sh * 0.35) and area >= 34:
                clean[labels == idx] = 255
                xs.append((x, x + w))
        if xs:
            x0 = max(0, min(a for a, _ in xs) - 10)
            x1 = min(clean.shape[1], max(b for _, b in xs) + 10)
            clean = clean[:, x0:x1]
        inv = cv2.copyMakeBorder(cv2.bitwise_not(clean), 14, 14, 16, 16, cv2.BORDER_CONSTANT, value=255)
        strips.append((name, inv))
        max_w = max(max_w, inv.shape[1])

    padded = []
    bounds = []
    cur_y = 0
    for name, st in strips:
        pad_r = max_w - st.shape[1]
        row = cv2.copyMakeBorder(st, 4, 4, 4, 4 + pad_r, cv2.BORDER_CONSTANT, value=255)
        bounds.append((name, cur_y, cur_y + row.shape[0]))
        cur_y += row.shape[0]
        padded.append(row)

    stacked = np.vstack(padded)
    ok, png_buf = cv2.imencode(".png", stacked)
    if not ok:
        return {}

    try:
        res = subprocess.run(
            [tess_bin, "stdin", "stdout", "--psm", "6", "-c", "tessedit_char_whitelist=0123456789"],
            input=png_buf.tobytes(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=5,
        )
        if res.returncode != 0:
            return {}
        lines = [
            "".join(c for c in ln if c.isdigit())
            for ln in res.stdout.decode("utf-8", errors="ignore").splitlines()
        ]
        lines = [ln for ln in lines if ln]
        if len(lines) == len(crops_by_name):
            return {name: int(val) for (name, _), val in zip(crops_by_name, lines)}

        tokens = _run_tesseract_tsv(stacked, psm=6)
        tokens_by_name = {name: [] for name, _ in crops_by_name}
        for tok in tokens:
            txt = "".join(c for c in tok["text"] if c.isdigit())
            if not txt:
                continue
            for name, y0, y1 in bounds:
                if y0 <= tok["cy"] < y1:
                    tokens_by_name[name].append((tok["left"], txt))
                    break
        out = {}
        for name, _ in crops_by_name:
            joined = "".join(t[1] for t in sorted(tokens_by_name[name], key=lambda t: t[0]))
            if joined:
                out[name] = int(joined)
        return out
    except Exception:
        pass
    return {}


def _find_resource_icon_pair(img1600, x_pct1, x_pct2, y_pct1, y_pct2, min_area_g, min_area_e, dy_range, max_gold_y):
    """Finds vertically aligned Gold coin and Elixir drop icons in the given viewport region."""
    x0, x1 = int(x_pct1 * 1600), int(x_pct2 * 1600)
    y0, y1 = int(y_pct1 * 900), int(y_pct2 * 900)
    zone = img1600[y0:y1, x0:x1]
    hsv = cv2.cvtColor(zone, cv2.COLOR_BGR2HSV)
    mask_g = ((hsv[:, :, 0] >= 18) & (hsv[:, :, 0] <= 34) & (hsv[:, :, 1] >= 140) & (hsv[:, :, 2] >= 180)).astype(np.uint8) * 255
    mask_e = ((hsv[:, :, 0] >= 135) & (hsv[:, :, 0] <= 170) & (hsv[:, :, 1] >= 110) & (hsv[:, :, 2] >= 150)).astype(np.uint8) * 255

    def collect_cands(mask, min_area):
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        out = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if 20 <= w <= 65 and 20 <= h <= 65 and area >= min_area:
                out.append((x0 + x + w / 2.0, y0 + y + h / 2.0, float(w), float(h), area))
        return out

    g_list = [g for g in collect_cands(mask_g, min_area_g) if g[1] <= max_gold_y]
    e_list = collect_cands(mask_e, min_area_e)
    best_pair = None
    best_score = 0
    for g in g_list:
        for e in e_list:
            dy = e[1] - g[1]
            if abs(e[0] - g[0]) <= 30 and dy_range[0] <= dy <= dy_range[1]:
                sc = g[4] + e[4]
                if sc > best_score:
                    best_score = sc
                    best_pair = (g, e)
    return best_pair


def _read_anchored_triplet(img1600, pair, side, results, ambiguous, tmpls):
    """Extracts and decodes Gold, Elixir, Dark Elixir bars anchored cleanly to icon pair."""
    g, e = pair
    dy = e[1] - g[1]
    if side == 'right':
        keys = ("own_gold", "own_elixir", "own_dark")
        anchor = 'right'
        rx1 = int(min(g[0] - g[2] / 2.0, e[0] - e[2] / 2.0) - 3)
        rx0 = max(0, rx1 - 260)
        rx1 = max(rx0 + 20, rx1)
    else:
        keys = ("enemy_gold", "enemy_elixir", "enemy_dark")
        anchor = 'left'
        rx0 = max(0, int(max(g[0] + g[2] / 2.0, e[0] + e[2] / 2.0) + 3))
        rx1 = min(1600, rx0 + 250)

    y_centers = (g[1], e[1], e[1] + dy)
    for key, cy in zip(keys, y_centers):
        ry0 = max(0, int(cy - 22))
        ry1 = min(900, int(cy + 22))
        crop = img1600[ry0:ry1, rx0:rx1]
        val, needs_fb, fb_crop = _decode_anchored_crop(crop, anchor, tmpls)
        results[key] = val
        if needs_fb and fb_crop is not None:
            ambiguous.append((key, fb_crop))


def _is_build_drawer_open(img1600):
    """Checks quickly whether the right-side Buildings & Heroes drawer close button is on screen."""
    _, close_tpl = _load_template_gray("templates/build_close_btn.png")
    if close_tpl is None:
        return False
    roi_gray = cv2.cvtColor(img1600[0:100, 1450:1600], cv2.COLOR_BGR2GRAY)
    th, tw = close_tpl.shape[:2]
    if th > roi_gray.shape[0] or tw > roi_gray.shape[1]:
        return False
    res = cv2.matchTemplate(roi_gray, close_tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return max_val >= 0.72


def read_game_resources(img_bgr=None, include_enemy=True, background_mode=False):
    """
    Reads enemy available loot (gold, elixir, dark) and own resources (gold, elixir, dark)
    from a 1600x900-normalized game viewport by anchoring directly to the Gold/Elixir
    HUD icons so Home Village, open drawer, Scout, and cropped views all read accurately.
    """
    if img_bgr is None:
        img_bgr = capture_game_bgr(background_mode=background_mode)
    if img_bgr is None:
        return None

    img1600 = _resize_frame(img_bgr, 1600, 900)
    tmpls = _load_digit_templates()

    results = {
        "enemy_gold": None,
        "enemy_elixir": None,
        "enemy_dark": None,
        "own_gold": 0,
        "own_elixir": 0,
        "own_dark": 0,
    }
    ambiguous = []

    # Own resources: check standard top-right zone first, then drawer-shifted zone
    own_pair = _find_resource_icon_pair(img1600, 0.85, 0.995, 0.0, 0.25, 450, 350, (40, 88), 115)
    if not own_pair:
        own_pair = _find_resource_icon_pair(img1600, 0.62, 0.75, 0.0, 0.25, 450, 350, (40, 88), 115)

    if own_pair:
        _read_anchored_triplet(img1600, own_pair, 'right', results, ambiguous, tmpls)
    else:
        own_map = HOME_DRAWER_OWN_ROIS if _is_build_drawer_open(img1600) else (SCOUT_OWN_ROIS if include_enemy else HOME_OWN_ROIS)
        for key in ("own_gold", "own_elixir", "own_dark"):
            x1p, y1p, x2p, y2p = own_map[key]
            crop = img1600[int(y1p * 900):int(y2p * 900), int(x1p * 1600):int(x2p * 1600)]
            val, needs_fb, fb_crop = _decode_anchored_crop(crop, 'right', tmpls)
            results[key] = val
            if needs_fb and fb_crop is not None:
                ambiguous.append((key, fb_crop))

    # Enemy available loot (only populated when left-side Gold & Elixir icons are present)
    if include_enemy:
        enemy_pair = _find_resource_icon_pair(img1600, 0.005, 0.075, 0.05, 0.34, 280, 220, (34, 76), 210)
        if enemy_pair:
            _read_anchored_triplet(img1600, enemy_pair, 'left', results, ambiguous, tmpls)

    if ambiguous:
        tess_results = _tesseract_batch_crops(ambiguous)
        for key, _ in ambiguous:
            if key in tess_results and tess_results[key] > 0:
                results[key] = tess_results[key]

    return results


def find_wall_in_build_list(background_mode=False):
    """
    Scans the right-side Buildings & Heroes drawer for a 'Wall' / 'Wall x N' row
    and returns action-space coordinates (cx, cy) to select it, or None if not visible.
    """
    img1600 = capture_game_bgr(background_mode=background_mode)
    if img1600 is None:
        return None

    x0 = int(0.73 * 1600)
    x1 = int(0.99 * 1600)
    y0 = int(0.08 * 900)
    y1 = int(0.87 * 900)
    drawer = img1600[y0:y1, x0:x1]

    up_bgr = cv2.resize(drawer, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    up_gray = cv2.cvtColor(up_bgr, cv2.COLOR_BGR2GRAY)
    _, inv_gray = cv2.threshold(up_gray, 175, 255, cv2.THRESH_BINARY_INV)

    candidates = []
    for img_pass in (inv_gray, up_bgr):
        tokens = _run_tesseract_tsv(img_pass, psm=11)
        for tok in tokens:
            cleaned = re.sub(r'[^a-z]', '', tok["text"].lower())
            if cleaned in ("wall", "walls", "wallx", "wallsx") and tok["conf"] >= 45:
                nx = x0 + tok["cx"] / 2.0
                ny = y0 + tok["cy"] / 2.0
                # Ensure row lies cleanly inside scrollable card zone (not top bar or bottom tabs)
                if 0.10 * 900 <= ny <= 0.84 * 900:
                    candidates.append((ny, nx))
        if candidates:
            break

    if not candidates:
        return None

    # Prefer the topmost visible Wall entry in the drawer list
    candidates.sort(key=lambda pt: pt[0])
    best_ny, best_nx = candidates[0]
    return normalized_to_action_coords(best_nx, best_ny, background_mode=background_mode)


def _upgrade_btn_has_red_cost(img1600, nx, ny):
    """Detects bright neon-red unaffordable cost text on an Upgrade action button."""
    x0 = max(0, int(nx - 50))
    x1 = min(1600, int(nx + 35))
    y0 = max(0, int(ny - 48))
    y1 = min(900, int(ny - 8))
    if x1 <= x0 or y1 <= y0:
        return False
    patch = img1600[y0:y1, x0:x1]
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    red_mask = (((hsv[:, :, 0] <= 5) | (hsv[:, :, 0] >= 175)) & (hsv[:, :, 1] >= 180) & (hsv[:, :, 2] >= 200))
    return int(np.sum(red_mask)) >= 55


def find_upgrade_buttons(background_mode=False, check_affordable=False):
    """
    Scans the bottom unit/structure action bar for 'Upgrade' buttons (sorted left-to-right).
    When check_affordable is False, returns [pt1, pt2, ...].
    When check_affordable is True, returns [(pt1, is_affordable1), ...].
    """
    img1600 = capture_game_bgr(background_mode=background_mode)
    if img1600 is None:
        return []

    x0 = int(0.10 * 1600)
    x1 = int(0.90 * 1600)
    y0 = int(0.68 * 900)
    y1 = int(0.96 * 900)
    bar = img1600[y0:y1, x0:x1]

    up_bgr = cv2.resize(bar, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    up_gray = cv2.cvtColor(up_bgr, cv2.COLOR_BGR2GRAY)
    _, inv_gray = cv2.threshold(up_gray, 180, 255, cv2.THRESH_BINARY_INV)

    raw_pts = []
    for img_pass in (inv_gray, up_bgr):
        tokens = _run_tesseract_tsv(img_pass, psm=11)
        for tok in tokens:
            cleaned = re.sub(r'[^a-z]', '', tok["text"].lower())
            if "upgrad" in cleaned and tok["conf"] >= 45:
                nx = x0 + tok["cx"] / 2.0
                ny = y0 + tok["cy"] / 2.0
                raw_pts.append((nx, ny))
        if raw_pts:
            break

    # Fallback: match hammer icon multiple times across bottom bar sorted left-to-right
    if not raw_pts:
        _, hammer_tpl = _load_template_gray("templates/upgrade_hammer.png")
        if hammer_tpl is not None:
            bar_gray = cv2.cvtColor(bar, cv2.COLOR_BGR2GRAY)
            th, tw = hammer_tpl.shape[:2]
            if th <= bar_gray.shape[0] and tw <= bar_gray.shape[1]:
                res = cv2.matchTemplate(bar_gray, hammer_tpl, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(res >= 0.72)
                peaks = sorted([(float(res[yy, xx]), xx + tw / 2.0, yy + th / 2.0) for yy, xx in zip(ys, xs)], reverse=True)
                for _, px, py in peaks:
                    nx = x0 + px
                    ny = y0 + py
                    if all(abs(nx - ox) > 65 for ox, _ in raw_pts):
                        raw_pts.append((nx, ny))

    # Deduplicate overlapping horizontal detections and sort left-to-right (1st=Gold, 2nd=Elixir)
    raw_pts.sort(key=lambda pt: pt[0])
    deduped = []
    for nx, ny in raw_pts:
        if all(abs(nx - ox) > 45 for ox, _ in deduped):
            deduped.append((nx, ny))

    if check_affordable:
        return [
            (normalized_to_action_coords(nx, ny, background_mode=background_mode), not _upgrade_btn_has_red_cost(img1600, nx, ny))
            for nx, ny in deduped
        ]
    return [normalized_to_action_coords(nx, ny, background_mode=background_mode) for nx, ny in deduped]


def find_upgrade_confirm_button(background_mode=False):
    """
    Inspects the upgrade confirmation popup safely.
    Returns (action_coords, status) where status is one of:
      'ok'           -> valid Confirm/Upgrade button found
      'insufficient' -> popup asks to buy missing resources with Gems (do not click!)
      'none'         -> popup or confirm button not detected
    """
    # Check optional explicit confirm template first
    if os.path.exists(get_resource_path("templates/confirm_btn.png")):
        pt = find_image_multi_scale("templates/confirm_btn.png", lambda _m: None, background_mode=background_mode)
        if pt:
            return pt, "ok"

    img1600 = capture_game_bgr(background_mode=background_mode)
    if img1600 is None:
        return None, "none"

    x0 = int(0.20 * 1600)
    x1 = int(0.80 * 1600)
    y0 = int(0.16 * 900)
    y1 = int(0.88 * 900)
    modal = img1600[y0:y1, x0:x1]

    up_bgr = cv2.resize(modal, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    up_gray = cv2.cvtColor(up_bgr, cv2.COLOR_BGR2GRAY)
    _, inv_gray = cv2.threshold(up_gray, 180, 255, cv2.THRESH_BINARY_INV)

    tokens = _run_tesseract_tsv(inv_gray, psm=11) + _run_tesseract_tsv(up_bgr, psm=11)
    all_words = [re.sub(r'[^a-z]', '', t["text"].lower()) for t in tokens if t["text"].strip()]

    # Gem protection: abort immediately if popup is prompting to spend Gems for missing loot
    danger_words = ("missing", "needed", "shortage", "buy", "gem", "gems", "insufficient", "spend", "remaining", "remain")
    if any(w in danger_words for w in all_words):
        return None, "insufficient"

    # Priority 1: Explicit 'confirm' / 'upgrade' button text in lower half of modal (y >= 0.55*900)
    for target in ("confirm", "upgrad"):
        hits = [
            t for t in tokens
            if target in re.sub(r'[^a-z]', '', t["text"].lower())
            and (y0 + t["cy"] / 1.5) >= 0.55 * 900
            and t["conf"] >= 45
        ]
        if hits:
            hits.sort(key=lambda t: t["cy"], reverse=True)
            best = hits[0]
            nx = x0 + best["cx"] / 1.5
            ny = y0 + best["cy"] / 1.5
            return normalized_to_action_coords(nx, ny, background_mode=background_mode), "ok"

    # Priority 2: Green action pill button inside bottom center of confirm modal
    bx0, bx1 = int(0.30 * 1600), int(0.70 * 1600)
    by0, by1 = int(0.58 * 900), int(0.86 * 900)
    btn_zone = img1600[by0:by1, bx0:bx1]
    hsv = cv2.cvtColor(btn_zone, cv2.COLOR_BGR2HSV)
    green_mask = ((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85) & (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 100)).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(green_mask)
    best_area = 0
    best_center = None
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in stats[i])
        if area >= 2500 and w > h * 1.4 and 30 <= h <= 120:
            if area > best_area:
                best_area = area
                best_center = (bx0 + x + w // 2, by0 + y + h // 2)

    if best_center is not None:
        return normalized_to_action_coords(best_center[0], best_center[1], background_mode=background_mode), "ok"

    return None, "none"


def _load_template_gray(template_path):
    """Reads and caches grayscale template images."""
    resolved_path = get_resource_path(template_path)
    if not os.path.exists(resolved_path):
        return None, None
    mtime = os.path.getmtime(resolved_path)
    cached = _template_cache.get(resolved_path)
    if cached and cached[0] == mtime:
        return resolved_path, cached[1]
    template = cv2.imread(resolved_path, cv2.IMREAD_GRAYSCALE)
    if template is not None:
        _template_cache[resolved_path] = (mtime, template)
    return resolved_path, template


def find_image_with_score(template_path, status_callback, confidence=0.7, background_mode=False, gray_frame=None):
    """
    Searches for a template image across scales, returning (coords_or_None, best_val, best_scale).
    Optionally reuses a pre-captured grayscale frame for rapid multi-template inspection.
    """
    _ensure_desktop()
    resolved_path, template = _load_template_gray(template_path)
    if resolved_path is None:
        status_callback(f"Error: Template not found at {template_path}")
        return None, 0.0, 1.0
    if template is None:
        status_callback(f"Error: Could not read template at {template_path}")
        return None, 0.0, 1.0

    screenshot_gray = gray_frame if gray_frame is not None else capture_screen(background_mode=background_mode)
    if screenshot_gray is None:
        status_callback("Error capturing game view.")
        return None, 0.0, 1.0

    sh, sw = screenshot_gray.shape[:2]
    scales = [1.0]
    cached_scale = _scale_cache.get(resolved_path)
    if cached_scale and abs(cached_scale - 1.0) > 0.01:
        scales.append(cached_scale)
    for s in np.linspace(0.8, 1.2, 21):
        sf = float(s)
        if abs(sf - 1.0) > 0.01 and (not cached_scale or abs(sf - cached_scale) > 0.01):
            scales.append(sf)

    best_overall = 0.0
    best_scale = 1.0
    for scale in scales:
        width = int(template.shape[1] * scale)
        height = int(template.shape[0] * scale)
        if width <= 0 or height <= 0 or width > sw or height > sh:
            continue

        resized_template = template if scale == 1.0 else cv2.resize(template, (width, height))
        res = cv2.matchTemplate(screenshot_gray, resized_template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)

        if max_val > best_overall:
            best_overall = float(max_val)
            best_scale = scale

        if max_val >= confidence:
            _scale_cache[resolved_path] = scale
            cx = max_loc[0] + width // 2
            cy = max_loc[1] + height // 2
            return (cx, cy), float(max_val), scale

    return None, best_overall, best_scale


def find_image_multi_scale(template_path, status_callback, confidence=0.7, background_mode=False):
    """Searches for a template image using multi-scale matching in foreground or background mode."""
    coords, _, _ = find_image_with_score(
        template_path,
        status_callback,
        confidence=confidence,
        background_mode=background_mode,
    )
    return coords


def inspect_screen_templates(template_specs, status_callback, background_mode=False):
    """
    Captures one game frame and matches multiple (template_path, threshold) pairs at once.
    Returns dict: {template_path: (coords_or_None, best_val)}.
    """
    gray = capture_screen(background_mode=background_mode)
    if gray is None:
        return {}
    out = {}
    for tpl_path, conf in template_specs:
        coords, best_val, _ = find_image_with_score(
            tpl_path,
            status_callback,
            confidence=conf,
            background_mode=background_mode,
            gray_frame=gray,
        )
        out[tpl_path] = (coords, best_val)
    return out


def get_text_coords(target_text, status_callback, background_mode=False):
    """Finds screen/action coordinates of specific text using OCR in foreground or background mode."""
    _ensure_desktop()
    img1600 = capture_game_bgr(background_mode=background_mode)
    if img1600 is None:
        status_callback("Error capturing screen for OCR.")
        return None

    gray = cv2.cvtColor(img1600, cv2.COLOR_BGR2GRAY)
    tokens = _run_tesseract_tsv(gray, psm=11)
    target = target_text.lower().strip()

    for tok in tokens:
        if target == tok["text"].lower().strip() and tok["conf"] > 60:
            return normalized_to_action_coords(tok["cx"], tok["cy"], background_mode=background_mode)

    return None
