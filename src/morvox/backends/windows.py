"""morvox.backends.windows — WindowsBackend."""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


class WindowsBackend:
    name = "windows"

    def required_tools(self) -> list[str]:
        return ["ffmpeg"]

    def has_display(self) -> bool:
        return True

    # ---- audio ----

    @staticmethod
    def _ffmpeg_has_audio_api(name: str) -> bool:
        """Check whether this ffmpeg build supports a given audio input API."""
        try:
            r = subprocess.run(
                ["ffmpeg", "-devices"],
                capture_output=True, text=True, timeout=5,
            )
            return name in (r.stdout + r.stderr)
        except Exception:
            return False

    @staticmethod
    def _get_dshow_default_device() -> str | None:
        """Return the first DirectShow audio capture device listed by ffmpeg."""
        try:
            r = subprocess.run(
                ["ffmpeg", "-hide_banner", "-list_devices", "true",
                 "-f", "dshow", "-i", "dummy"],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return None
        for line in (r.stderr or "").splitlines():
            m = re.search(r'"(.+)"\s+\(audio\)', line)
            if m:
                return m.group(1)
        return None

    _audio_api: str | None = None
    _audio_dev: str | None = None

    def _init_audio(self):
        if WindowsBackend._audio_api is not None:
            return
        if self._ffmpeg_has_audio_api("wasapi"):
            WindowsBackend._audio_api = "wasapi"
            WindowsBackend._audio_dev = "default"
        else:
            WindowsBackend._audio_api = "dshow"
            dev = self._get_dshow_default_device()
            WindowsBackend._audio_dev = dev

    def _creationflags(self) -> int:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return flags

    def record_to_wav(self, source: str | None, wav_path: Path,
                      log_fd, stream_pcm: bool = False) -> subprocess.Popen:
        from ..constants import STATE_DIR
        self_path = os.path.realpath(sys.argv[0])
        cmd = [sys.executable, self_path, "--recorder"]
        if source:
            cmd += ["--source", source]
        env = os.environ.copy()
        env["MORVOX_STATE_DIR"] = STATE_DIR
        env["MORVOX_RECORDER_STREAM"] = "1" if stream_pcm else "0"
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE if stream_pcm else log_fd,
            stderr=log_fd, stdin=subprocess.DEVNULL,
            creationflags=self._creationflags(), close_fds=True, env=env,
        )

    def record_pcm_stream(self, source: str | None,
                          log_fd) -> subprocess.Popen:
        self._init_audio()
        dev = source or WindowsBackend._audio_dev or "default"
        api = WindowsBackend._audio_api or "dshow"
        cmd = [
            "ffmpeg",
            "-f", api,
        ]
        if api == "dshow":
            cmd += ["-i", f"audio={dev}"]
        else:
            cmd += ["-i", dev]
        cmd += ["-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=log_fd,
            stdin=subprocess.DEVNULL, creationflags=self._creationflags(),
            close_fds=True,
        )

    # ---- window control ----

    def _wait_for_hotkey_keys_released(self, timeout: float = 2.0) -> bool:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = wintypes.SHORT

        keys = (
            0x5B, 0x5C,  # left/right Windows
            0xA2, 0xA3,  # left/right Ctrl
            0xA4, 0xA5,  # left/right Alt
            0xA0, 0xA1,  # left/right Shift
            0xC0,        # ` / ~ on US keyboards
            *range(0x70, 0x7C),  # F1-F12, often used in hotkey chords
        )
        deadline = time.monotonic() + timeout
        while True:
            if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in keys):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    def _release_stuck_modifiers(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

            @property
            def ki(self):
                return self.u.ki

        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        modifier_vks = (
            0x5B, 0x5C,  # left/right Windows
            0xA2, 0xA3,  # left/right Ctrl
            0xA4, 0xA5,  # left/right Alt
            0xA0, 0xA1,  # left/right Shift
        )

        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        release_inputs = (INPUT * len(modifier_vks))()
        for i, vk in enumerate(modifier_vks):
            release_inputs[i].type = INPUT_KEYBOARD
            release_inputs[i].ki.wVk = vk
            release_inputs[i].ki.dwFlags = KEYEVENTF_KEYUP
        user32.SendInput(len(release_inputs), release_inputs, ctypes.sizeof(INPUT))
        time.sleep(0.08)

    def get_active_window(self) -> str | None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        value = hwnd if isinstance(hwnd, int) else (hwnd.value if hwnd else 0)
        return str(value) if value else None

    def _window_pid(self, handle: str | int) -> int | None:
        import ctypes
        from ctypes import wintypes

        try:
            hwnd = int(handle, 0) if isinstance(handle, str) else int(handle)
        except (TypeError, ValueError):
            return None
        if not hwnd:
            return None

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                    ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value else None

    def _process_name(self, pid: int | None) -> str | None:
        if not pid:
            return None

        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                         wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid)
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buf))
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                       ctypes.byref(size)):
                return None
            return os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(handle)

    def get_live_type_target(self) -> tuple[str | None, str | None]:
        """Return a safe foreground HWND for typing, or a warning reason."""
        import ctypes
        from ctypes import wintypes
        from ..state import _read_widget_pid

        handle = self.get_active_window()
        if not handle:
            return None, "no foreground window is active"

        try:
            hwnd = int(handle, 0)
        except ValueError:
            return None, f"invalid foreground window handle {handle!r}"
        if not hwnd:
            return None, "no foreground window is active"

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        if not user32.IsWindow(hwnd):
            return None, f"foreground window {handle} is no longer valid"

        window_pid = self._window_pid(handle)
        if window_pid and window_pid == os.getpid():
            return None, "foreground window belongs to morvox itself"

        widget_pid = _read_widget_pid()
        if widget_pid is not None and window_pid == widget_pid:
            return None, "foreground window is the morvox widget"

        return handle, None

    def is_shell_window(self, handle: str | None) -> bool:
        if not handle:
            return False
        pid = self._window_pid(handle)
        return self._process_name(pid) == "explorer.exe"

    def describe_window(self, handle: str | None) -> str:
        if not handle:
            return "hwnd=<none>"
        try:
            hwnd = int(handle, 0)
        except (TypeError, ValueError):
            return f"hwnd={handle!r} pid=<unknown> process=<unknown>"
        pid = self._window_pid(hwnd)
        proc = self._process_name(pid) or "<unknown>"
        return f"hwnd={handle} pid={pid or '<unknown>'} process={proc}"

    def focus_window(self, handle: str, timeout: float = 3.0) -> bool:
        import ctypes
        from ctypes import wintypes

        try:
            hwnd = int(handle, 0)
        except ValueError:
            hwnd = 0
        if not hwnd:
            return False

        self._wait_for_hotkey_keys_released(timeout=1.0)
        self._release_stuck_modifiers()

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                    ctypes.c_void_p]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                             wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        if not user32.IsWindow(hwnd):
            return False

        SW_SHOW = 5
        SW_RESTORE = 9

        def foreground_is_target() -> bool:
            current = user32.GetForegroundWindow()
            value = current if isinstance(current, int) else (current.value if current else 0)
            return int(value or 0) == hwnd

        def wait_foreground() -> bool:
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if foreground_is_target():
                    return True
                time.sleep(0.02)
            return foreground_is_target()

        user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
        if user32.SetForegroundWindow(hwnd) and wait_foreground():
            return True

        current = user32.GetForegroundWindow()
        current_thread = kernel32.GetCurrentThreadId()
        foreground_thread = user32.GetWindowThreadProcessId(current, None) if current else 0
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached = []
        try:
            for other in (foreground_thread, target_thread):
                if other and other != current_thread:
                    if user32.AttachThreadInput(current_thread, other, True):
                        attached.append(other)
            user32.ShowWindow(hwnd, SW_RESTORE if user32.IsIconic(hwnd) else SW_SHOW)
            if user32.SetForegroundWindow(hwnd) and wait_foreground():
                return True
        finally:
            for other in attached:
                user32.AttachThreadInput(current_thread, other, False)

        print(
            f"morvox: warning: could not re-focus window {handle}; "
            "typing into currently focused window instead.",
            file=sys.stderr,
        )
        return False

    def type_text(self, text: str, delay_ms: int) -> None:
        if not text:
            return

        from ..state import _debug_log
        _debug_log("windows-insert", f"type_text start chars={len(text)} delay_ms={delay_ms}")

        self._wait_for_hotkey_keys_released(timeout=2.0)
        self._release_stuck_modifiers()

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

            @property
            def ki(self):
                return self.u.ki

        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        KEYEVENTF_UNICODE = 0x0004

        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT

        # Send Unicode text directly instead of pasting with Ctrl+V. This
        # avoids sending command chords to the foreground app and leaves the
        # user's clipboard untouched.
        data = text.encode("utf-16-le", "surrogatepass")
        units = [int.from_bytes(data[i:i + 2], "little")
                 for i in range(0, len(data), 2)]

        def send_units(chunk: list[int]) -> None:
            inputs = (INPUT * (len(chunk) * 2))()
            for i, unit in enumerate(chunk):
                down = i * 2
                up = down + 1
                inputs[down].type = INPUT_KEYBOARD
                inputs[down].ki.wScan = unit
                inputs[down].ki.dwFlags = KEYEVENTF_UNICODE
                inputs[up].type = INPUT_KEYBOARD
                inputs[up].ki.wScan = unit
                inputs[up].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            expected = len(inputs)
            sent = user32.SendInput(expected, inputs, ctypes.sizeof(INPUT))
            if sent != expected:
                err = ctypes.get_last_error()
                raise subprocess.CalledProcessError(
                    1, "SendInput", stderr=f"Win32 error {err}"
                )

        if delay_ms > 0:
            for unit in units:
                send_units([unit])
                time.sleep(delay_ms / 1000.0)
            _debug_log("windows-insert", "type_text success (delayed)")
            return

        for i in range(0, len(units), 64):
            send_units(units[i:i + 64])
        _debug_log("windows-insert", "type_text success")

    def paste_text(self, text: str, target: str | None = None) -> None:
        if not text:
            return

        from ..state import _debug_log
        _debug_log(
            "windows-insert",
            f"paste_text start chars={len(text)} target={self.describe_window(target)}",
        )

        if target and self.get_active_window() != target:
            raise RuntimeError("foreground window changed before paste")
        if target:
            self.focus_window(target, timeout=0.5)
            time.sleep(0.08)
            if self.get_active_window() != target:
                raise RuntimeError("foreground window changed before paste")

        self.copy_text(text)
        _debug_log("windows-insert", "clipboard updated for paste")
        time.sleep(0.15)
        self._wait_for_hotkey_keys_released(timeout=2.0)
        self._release_stuck_modifiers()
        if target and self.get_active_window() != target:
            raise RuntimeError("foreground window changed before paste")
        time.sleep(0.12)

        last_error = None
        for name, method in (
            ("wscript-sendkeys", self._paste_via_wscript_sendkeys),
            ("forms-sendkeys", self._paste_via_sendkeys),
            ("sendinput", self._paste_via_sendinput),
        ):
            try:
                _debug_log("windows-insert", f"paste attempt via {name}")
                method(target=target)
                _debug_log("windows-insert", f"paste success via {name}")
                return
            except Exception as e:
                last_error = e
                stderr = getattr(e, "stderr", None)
                detail = f"{type(e).__name__}: {e}"
                if stderr:
                    detail += f" stderr={stderr!r}"
                _debug_log("windows-insert", f"paste failure via {name}: {detail}")
                time.sleep(0.08)
        if last_error is not None:
            raise last_error

    def _paste_via_wscript_sendkeys(self, target: str | None = None) -> None:
        if target and self.get_active_window() != target:
            raise RuntimeError("foreground window changed before paste")

        shell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not shell:
            raise RuntimeError("powershell not found for WScript paste")

        cmd = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$ws.SendKeys('^v')"
        )
        subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-STA", "-Command", cmd],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=self._creationflags(),
        )

    def _paste_via_sendkeys(self, target: str | None = None) -> None:
        if target and self.get_active_window() != target:
            raise RuntimeError("foreground window changed before paste")

        shell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not shell:
            raise RuntimeError("powershell not found for SendKeys paste")

        cmd = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "[System.Windows.Forms.SendKeys]::SendWait('^v')"
        )
        subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-STA", "-Command", cmd],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=self._creationflags(),
        )

    def _paste_via_sendinput(self, target: str | None = None) -> None:
        if target and self.get_active_window() != target:
            raise RuntimeError("foreground window changed before paste")

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", INPUTUNION)]

            @property
            def ki(self):
                return self.u.ki

        INPUT_KEYBOARD = 1
        KEYEVENTF_KEYUP = 0x0002
        VK_CONTROL = 0x11
        VK_V = 0x56

        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT

        inputs = (INPUT * 4)()
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki.wVk = VK_CONTROL
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki.wVk = VK_V
        inputs[2].type = INPUT_KEYBOARD
        inputs[2].ki.wVk = VK_V
        inputs[2].ki.dwFlags = KEYEVENTF_KEYUP
        inputs[3].type = INPUT_KEYBOARD
        inputs[3].ki.wVk = VK_CONTROL
        inputs[3].ki.dwFlags = KEYEVENTF_KEYUP

        sent = user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            err = ctypes.get_last_error()
            raise subprocess.CalledProcessError(
                1, "SendInput", stderr=f"Win32 error {err}"
            )

    def copy_text(self, text: str) -> None:
        if not text:
            return

        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.EmptyClipboard.restype = wintypes.BOOL
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.CloseClipboard.restype = wintypes.BOOL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL

        data = text.encode("utf-16-le", "surrogatepass") + b"\x00\x00"
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            err = ctypes.get_last_error()
            raise subprocess.CalledProcessError(
                1, "GlobalAlloc", stderr=f"Win32 error {err}"
            )
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            err = ctypes.get_last_error()
            raise subprocess.CalledProcessError(
                1, "GlobalLock", stderr=f"Win32 error {err}"
            )
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(handle)

        if not user32.OpenClipboard(None):
            err = ctypes.get_last_error()
            raise subprocess.CalledProcessError(
                1, "OpenClipboard", stderr=f"Win32 error {err}"
            )
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                err = ctypes.get_last_error()
                raise subprocess.CalledProcessError(
                    1, "SetClipboardData", stderr=f"Win32 error {err}"
                )
            handle = None
        finally:
            user32.CloseClipboard()

    # ---- display geometry ----

    def pointer_xy(self) -> tuple[int, int] | None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        pt = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return int(pt.x), int(pt.y)

    def monitors(self) -> list[tuple[int, int, int, int]]:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        result: list[tuple[int, int, int, int]] = []
        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
            ctypes.POINTER(RECT), wintypes.LPARAM,
        )

        def callback(_monitor, _dc, rect_ptr, _data):
            rct = rect_ptr.contents
            w = int(rct.right - rct.left)
            h = int(rct.bottom - rct.top)
            if w > 0 and h > 0:
                result.append((int(rct.left), int(rct.top), w, h))
            return True

        user32.EnumDisplayMonitors.argtypes = [
            wintypes.HDC, ctypes.POINTER(RECT), MONITORENUMPROC,
            wintypes.LPARAM,
        ]
        user32.EnumDisplayMonitors.restype = wintypes.BOOL
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(callback), 0)
        return result

    # ---- widget chrome ----

    def configure_widget_window(self, tk_root) -> None:
        self._make_widget_noactivate(tk_root)

    def _widget_hwnd(self, tk_root) -> int | None:
        import ctypes
        from ctypes import wintypes

        try:
            hwnd = int(tk_root.winfo_id())
        except Exception:
            return None
        if not hwnd:
            return None

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        GA_ROOT = 2

        root_hwnd = user32.GetAncestor(hwnd, GA_ROOT)
        value = root_hwnd if isinstance(root_hwnd, int) else root_hwnd.value
        return int(value or hwnd)

    def _make_widget_noactivate(self, tk_root) -> int | None:
        import ctypes
        from ctypes import wintypes

        hwnd = self._widget_hwnd(tk_root)
        if not hwnd:
            return None

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            get_window_long = user32.GetWindowLongPtrW
            set_window_long = user32.SetWindowLongPtrW
            long_ptr = ctypes.c_longlong
        else:
            get_window_long = user32.GetWindowLongW
            set_window_long = user32.SetWindowLongW
            long_ptr = ctypes.c_long

        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_NOACTIVATE = 0x08000000

        get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
        get_window_long.restype = long_ptr
        set_window_long.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
        set_window_long.restype = long_ptr
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_uint]

        style = int(get_window_long(hwnd, GWL_EXSTYLE))
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        style &= ~WS_EX_APPWINDOW
        set_window_long(hwnd, GWL_EXSTYLE, long_ptr(style))

        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        SWP_FRAMECHANGED = 0x0020
        HWND_TOPMOST = wintypes.HWND(-1)
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return hwnd

    def apply_rounded_corners(self, tk_root, w: int, h: int, r: int,
                              force_remap: bool = False) -> None:
        import ctypes
        from ctypes import wintypes

        try:
            tk_root.update_idletasks()
            hwnd = int(tk_root.winfo_id())
        except Exception:
            return
        if not hwnd:
            return

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int]
        gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN,
                                        wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]

        region = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r * 2, r * 2)
        if not region:
            return
        if not user32.SetWindowRgn(hwnd, region, True):
            gdi32.DeleteObject(region)
