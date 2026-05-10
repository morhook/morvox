"""morvox.state — state-dir helpers, process/widget coordination utilities."""

import os
import shutil
import signal
import stat
import sys
import time
from pathlib import Path

from .constants import STATE_DIR


def _state() -> Path:
    p = Path(STATE_DIR)
    try:
        p.mkdir(parents=True, mode=0o700, exist_ok=True)
        if p.is_symlink():
            print(f"morvox: state dir {p} must not be a symlink", file=sys.stderr)
            sys.exit(1)
        if os.name == "posix":
            st = p.stat()
            uid = os.getuid()
            if st.st_uid != uid:
                print(
                    f"morvox: state dir {p} is owned by uid {st.st_uid}, "
                    f"not current uid {uid}",
                    file=sys.stderr,
                )
                sys.exit(1)
            mode = stat.S_IMODE(st.st_mode)
            if mode != 0o700:
                p.chmod(0o700)
    except OSError as e:
        print(f"morvox: cannot use state dir {p}: {e}", file=sys.stderr)
        sys.exit(1)
    return p


def _pid_file() -> Path:
    return _state() / "rec.pid"


def _stop_file() -> Path:
    return _state() / "rec.stop"


def _target_file() -> Path:
    return _state() / "target_window"


def _wav_file() -> Path:
    return _state() / "rec.wav"


def _pcm_file() -> Path:
    return _state() / "rec.pcm"


def _txt_file() -> Path:
    return _state() / "rec.txt"


def _log_file() -> Path:
    return _state() / "parecord.log"


def _whisper_log() -> Path:
    return _state() / "whisper.log"


def _append_whisper_log(text: str) -> None:
    try:
        with _whisper_log().open("a", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass


def _debug_log(section: str, message: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_whisper_log(f"[{stamp}] {section}: {message}\n")


def _widget_pid_file() -> Path:
    return _state() / "widget.pid"


def _widget_log() -> Path:
    return _state() / "widget.log"


def _widget_state_file() -> Path:
    # Polled by the widget process; written by the main process.
    return _state() / "widget.state"


def _has_display() -> bool:
    from .backends import BACKEND
    return BACKEND.has_display()


def _read_widget_pid() -> int | None:
    pf = _widget_pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 0 else None


def _write_widget_state(state: str) -> None:
    """Write a state token the widget polls (transcribing, empty, done, error)."""
    try:
        _widget_state_file().write_text(state)
    except OSError:
        pass


def signal_widget(state: str, terminate: bool = False) -> None:
    """Update widget state file and optionally terminate the widget process."""
    _write_widget_state(state)
    pid = _read_widget_pid()
    if pid is None or not pid_alive(pid):
        return
    try:
        if terminate and sys.platform != "win32":
            os.kill(pid, signal.SIGTERM)
        elif hasattr(signal, "SIGUSR1"):
            # SIGUSR1 nudges the widget to re-read state immediately.
            os.kill(pid, signal.SIGUSR1)
        # Windows has no SIGUSR1; the widget polls the state file instead.
        # Avoid SIGTERM there because Python maps it to TerminateProcess,
        # which can close an unrelated app if a stale widget PID was reused.
    except (ProcessLookupError, PermissionError, OSError):
        pass


def close_widget() -> None:
    """Terminate the widget process if running and clean up its files."""
    pid = _read_widget_pid()
    if pid is not None and pid_alive(pid):
        if sys.platform == "win32":
            # The widget polls this state and exits on "done". Do not use
            # SIGTERM on Windows: os.kill(SIGTERM) is TerminateProcess and a
            # stale/reused PID can close an unrelated window.
            _write_widget_state("done")
            _wait_for_pid_exit(pid, 0.5)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    for p in (_widget_pid_file(), _widget_state_file()):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def die(msg: str, code: int = 1) -> None:
    print(f"morvox: {msg}", file=sys.stderr)
    close_widget()
    sys.exit(code)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        die(f"required tool not found: {name}")
    return path


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                         wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                                ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                      False, pid)
        if not handle:
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD(0)
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but is owned by someone else.
        return True
    return True


def read_pid() -> int | None:
    pf = _pid_file()
    if not pf.exists():
        return None
    try:
        pid = int(pf.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if pid > 0 else None


def is_recording() -> bool:
    pid = read_pid()
    return pid is not None and pid_alive(pid)


def cleanup_state(keep_temp: bool = False) -> None:
    if keep_temp:
        return
    for p in (_pid_file(), _stop_file(), _target_file(), _wav_file(),
              _pcm_file(), _txt_file()):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def _wait_for_pid_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return not pid_alive(pid)
