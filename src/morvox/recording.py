"""morvox.recording — recording lifecycle (start, stop, recorder helper, finalization)."""

import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .backends import BACKEND
from .backends.windows import WindowsBackend
from .constants import (
    DEFAULT_MODEL,
    WHISPER_BIN,
    _NOISE_TOKENS,
    default_model_for_language,
    default_model_url_for_language,
)
from .state import (
    _debug_log,
    _log_file,
    _pcm_file,
    _pid_file,
    _state,
    _stop_file,
    _target_file,
    _txt_file,
    _wav_file,
    _whisper_log,
    cleanup_state,
    close_widget,
    die,
    is_recording,
    pid_alive,
    read_pid,
    require_tool,
    signal_widget,
    _wait_for_pid_exit,
)
from .widget import spawn_widget


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _download_default_model(model_path: Path, model_url: str) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{model_path.name}.",
        suffix=".part",
        dir=str(model_path.parent),
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        curl = shutil.which("curl")
        if curl:
            result = subprocess.run(
                [curl, "-L", "--fail", "--output", str(tmp_path), model_url],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "curl download failed").strip()
                raise RuntimeError(detail)
        else:
            with urllib.request.urlopen(model_url, timeout=120) as response:
                with tmp_path.open("wb") as out:
                    shutil.copyfileobj(response, out)
        if not tmp_path.exists() or tmp_path.stat().st_size == 0:
            raise RuntimeError("downloaded model file is empty")
        tmp_path.replace(model_path)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


def ensure_model_available(model_path: str, language: str, model_explicit: bool = False) -> str:
    resolved = _normalize_path(model_path)
    if model_explicit:
        return resolved

    default_model = _normalize_path(DEFAULT_MODEL)
    if resolved != default_model:
        return resolved

    managed_model = _normalize_path(default_model_for_language(language))
    model_url = default_model_url_for_language(language)

    path = Path(managed_model)
    if path.exists():
        try:
            if path.stat().st_size > 0:
                return str(path)
            path.unlink()
        except OSError:
            pass

    print(f"morvox: downloading default whisper model to {path}", file=sys.stderr)
    _debug_log("default-model", f"downloading default model from {model_url} to {path}")
    try:
        _download_default_model(path, model_url)
    except (OSError, RuntimeError, urllib.error.URLError) as e:
        _debug_log("default-model", f"download failed: {e}")
        die(f"failed to download default whisper model: {e}")
    _debug_log("default-model", f"download complete: {path}")
    return str(path)


def cmd_recorder(args) -> int:
    """Hidden Windows recorder helper."""
    from .constants import STATE_DIR
    if sys.platform != "win32" or not isinstance(BACKEND, WindowsBackend):
        return 1

    BACKEND._init_audio()
    dev = args.source or WindowsBackend._audio_dev or "default"
    api = WindowsBackend._audio_api or "dshow"
    input_arg = f"audio={dev}" if api == "dshow" else dev
    cmd = [
        "ffmpeg", "-hide_banner",
        "-f", api, "-i", input_arg,
        "-map", "0:a:0", "-ac", "1", "-ar", "16000",
        "-f", "s16le", "pipe:1",
    ]

    _stop_file().unlink(missing_ok=True)
    stream_pcm = os.environ.get("MORVOX_RECORDER_STREAM") == "1"
    out = sys.stdout.buffer if stream_pcm else None

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=sys.stderr, creationflags=BACKEND._creationflags(),
            close_fds=True,
        )
    except FileNotFoundError:
        print("morvox-recorder: ffmpeg not found", file=sys.stderr)
        return 127

    stop_sent = False
    try:
        with open(_pcm_file(), "wb", buffering=0) as pcm:
            while True:
                chunk = proc.stdout.read(4096) if proc.stdout else b""
                if chunk:
                    pcm.write(chunk)
                    if out is not None:
                        try:
                            out.write(chunk)
                            out.flush()
                        except (BrokenPipeError, OSError):
                            out = None
                elif proc.poll() is not None:
                    break

                if not stop_sent and _stop_file().exists():
                    stop_sent = True
                    try:
                        if proc.stdin:
                            proc.stdin.write(b"q\n")
                            proc.stdin.flush()
                    except (BrokenPipeError, OSError):
                        try:
                            proc.terminate()
                        except OSError:
                            pass
    finally:
        try:
            if proc.poll() is None:
                proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.terminate()
            except OSError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        try:
            _stop_file().unlink(missing_ok=True)
        except OSError:
            pass

    return 0 if stop_sent else int(proc.returncode or 0)


def cmd_start(args) -> int:
    for tool in BACKEND.required_tools():
        require_tool(tool)

    args.model = ensure_model_available(args.model, args.language, args.model_explicit)

    state = _state()

    # Stale lock handling: if pid file exists but process is dead, clean up.
    existing = read_pid()
    if existing is not None and not pid_alive(existing):
        _pid_file().unlink(missing_ok=True)
        close_widget()

    for p in (_stop_file(), _target_file(), _wav_file(), _pcm_file(), _txt_file()):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    # Capture currently focused window/app id. Hotkey launchers can pass a
    # pre-captured handle when launching morvox would otherwise steal focus.
    explicit_target = args.target_window or os.environ.get("MORVOX_TARGET_WINDOW")
    win = explicit_target
    if not win:
        win = BACKEND.get_active_window()
    if not win:
        die("could not determine active window")

    _target_file().write_text(win + "\n")

    # Truncate previous log.
    log_path = _log_file()
    log_fd = open(log_path, "wb")

    try:
        proc = BACKEND.record_to_wav(
            args.source, _wav_file(), log_fd,
            stream_pcm=(sys.platform == "win32" and not args.no_widget),
        )
    except FileNotFoundError:
        log_fd.close()
        die(f"{BACKEND.required_tools()[0]} not found")
        return 1
    finally:
        # The child has inherited the fd; safe to close ours.
        try:
            log_fd.close()
        except Exception:
            pass

    # Give the recorder a brief moment to fail fast (e.g. bad source).
    time.sleep(0.4 if sys.platform == "win32" else 0.1)
    if proc.poll() is not None:
        # It died immediately.
        try:
            log_text = log_path.read_text(errors="replace").strip()
        except OSError:
            log_text = ""
        cleanup_state()
        die(f"recorder failed to start (exit {proc.returncode}). "
            f"Log: {log_text}")

    _pid_file().write_text(f"{proc.pid}\n")
    if not args.no_widget:
        spawn_widget(args.source, pcm_proc=proc)
    print(f"recording (pid={proc.pid})")
    return 0


def stop_recorder(pid: int, timeout: float = 2.0) -> bool:
    """Ask the recorder to stop, then terminate it if needed."""
    if sys.platform == "win32":
        try:
            _stop_file().write_text("stop\n")
        except OSError:
            return False

        if _wait_for_pid_exit(pid, timeout):
            return True

        # Avoid os.kill(SIGTERM) on Windows: it is TerminateProcess, not a
        # console signal, so a stale/reused recorder PID could close an
        # unrelated terminal or app. The hidden recorder watches rec.stop and
        # shuts ffmpeg down cooperatively.
        return False

    try:
        os.kill(pid, signal.SIGINT)
    except ProcessLookupError:
        return True
    except PermissionError:
        # Can't signal it; treat as not-our-problem.
        return False

    if _wait_for_pid_exit(pid, timeout):
        return True

    # Escalate.
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True

    if _wait_for_pid_exit(pid, 1.0):
        return True

    # Last resort.
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return not pid_alive(pid)


def finalize_recording() -> None:
    if sys.platform != "win32":
        return

    pcm = _pcm_file()
    if not pcm.exists() or pcm.stat().st_size == 0:
        return

    import wave

    wav = _wav_file()
    with open(pcm, "rb") as inp, wave.open(str(wav), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        while True:
            chunk = inp.read(1024 * 1024)
            if not chunk:
                break
            out.writeframesraw(chunk)


def clean_transcript(raw: str) -> str:
    # Collapse all whitespace runs (including newlines) into single spaces.
    return re.sub(r"\s+", " ", raw).strip()


def is_noise(text: str) -> bool:
    if not text:
        return True
    return text.strip().lower() in _NOISE_TOKENS


def cmd_stop(args) -> int:
    from .constants import WHISPER_DIR

    # Only the typing tool is strictly required to finish a stop cycle.
    # On Linux that's xdotool; on macOS osascript (always present).
    for tool in BACKEND.required_tools():
        if tool in ("xdotool", "osascript"):
            require_tool(tool)

    pid = read_pid()
    if pid is None or not pid_alive(pid):
        # Nothing to stop. Treat as a no-op fresh state.
        cleanup_state()
        close_widget()
        print("not recording", file=sys.stderr)
        return 0

    if not stop_recorder(pid):
        die("failed to stop recorder")

    # Recorder is done; pid file no longer relevant.
    _pid_file().unlink(missing_ok=True)
    finalize_recording()

    wav = _wav_file()
    if not wav.exists() or wav.stat().st_size == 0:
        cleanup_state(keep_temp=args.keep_temp)
        die("no audio captured (empty wav)")

    # Verify whisper-cli & model.
    if os.path.isabs(WHISPER_BIN) and not Path(WHISPER_BIN).exists():
        die(f"whisper-cli not found at {WHISPER_BIN}")
    model_path = ensure_model_available(args.model, args.language, args.model_explicit)
    if not Path(model_path).exists():
        die(f"whisper model not found: {model_path}")

    out_prefix = str(_state() / "rec")  # whisper writes <prefix>.txt

    whisper_cmd = [
        WHISPER_BIN,
        "-m", model_path,
        "-f", str(wav),
        "-l", args.language,
        "-t", str(args.threads),
        "-nt",
        "-np",
        "-otxt",
        "-of", out_prefix,
    ]

    signal_widget("transcribing")
    try:
        result = subprocess.run(
            whisper_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        cleanup_state(keep_temp=args.keep_temp)
        die(
            "whisper-cli not found (checked $MORVOX_WHISPER_BIN, "
            f"{WHISPER_DIR}/build/bin/whisper-cli, {WHISPER_DIR}/bin/whisper-cli, "
            "and $PATH)"
        )
        return 1

    # Persist whisper log for debugging.
    try:
        _whisper_log().write_text(
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n"
        )
    except OSError:
        pass

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        signal_widget("error", terminate=False)
        print(f"morvox: whisper-cli failed (exit {result.returncode})", file=sys.stderr)
        if err:
            print(err, file=sys.stderr)
        # Give the widget a beat to show "Error" before we exit and the
        # SIGTERM-on-die path closes it. Then explicitly close.
        time.sleep(1.2)
        close_widget()
        # Leave temp around for debugging unless keep-temp explicitly false?
        # User asked to delete on success only; failure -> keep for debugging.
        return result.returncode

    txt = _txt_file()
    if not txt.exists():
        die("whisper produced no .txt file")

    raw = txt.read_text(errors="replace")
    text = clean_transcript(raw)

    if is_noise(text):
        signal_widget("empty")
        # Let the widget show "No speech detected" briefly, then it self-closes.
        time.sleep(1.0)
        close_widget()
        cleanup_state(keep_temp=args.keep_temp)
        return 0

    # Windows types into the live foreground window at insertion time rather
    # than reviving the previously saved HWND. That avoids re-activating an
    # older app and reduces the chance of sending keystrokes somewhere stale.
    target = ""
    tf = _target_file()
    if tf.exists():
        target = tf.read_text().strip()

    refocused = False
    try:
        if sys.platform == "win32" and isinstance(BACKEND, WindowsBackend):
            _debug_log("windows-insert", "begin Windows insertion flow")
            live_target, reason = BACKEND.get_live_type_target()
            if not live_target:
                _debug_log("windows-insert", f"no live target: {reason}")
                if target and reason in (
                    "foreground window belongs to morvox itself",
                    "foreground window is the morvox widget",
                ):
                    live_target = target
                    _debug_log(
                        "windows-insert",
                        "falling back from morvox-owned foreground to saved target "
                        f"{BACKEND.describe_window(live_target)}",
                    )
            if not live_target:
                copier = getattr(BACKEND, "copy_text", None)
                if not copier:
                    raise RuntimeError("clipboard fallback is unsupported")
                copier(text)
                _debug_log("windows-insert", "clipboard-only fallback used")
                print(
                    "morvox: transcript copied to clipboard; not typing because "
                    f"{reason}.",
                    file=sys.stderr,
                )
            else:
                _debug_log(
                    "windows-insert",
                    f"live target selected: {BACKEND.describe_window(live_target)}",
                )
                if target and BACKEND.is_shell_window(live_target):
                    _debug_log(
                        "windows-insert",
                        "live target is explorer shell; falling back to saved target "
                        f"{BACKEND.describe_window(target)}",
                    )
                    live_target = target
                BACKEND.focus_window(live_target, timeout=0.5)
                time.sleep(0.08)
                _debug_log(
                    "windows-insert",
                    f"foreground after focus attempt: "
                    f"{BACKEND.describe_window(BACKEND.get_active_window())}",
                )
                try:
                    BACKEND.paste_text(text, target=live_target)
                except Exception:
                    e = sys.exc_info()[1]
                    stderr = getattr(e, "stderr", None)
                    detail = f"{type(e).__name__}: {e}"
                    if stderr:
                        detail += f" stderr={stderr!r}"
                    _debug_log("windows-insert", f"paste path failed: {detail}")
                    try:
                        BACKEND.type_text(text, args.type_delay)
                    except Exception:
                        e = sys.exc_info()[1]
                        stderr = getattr(e, "stderr", None)
                        detail = f"{type(e).__name__}: {e}"
                        if stderr:
                            detail += f" stderr={stderr!r}"
                        _debug_log("windows-insert", f"type path failed: {detail}")
                        copier = getattr(BACKEND, "copy_text", None)
                        if not copier:
                            raise
                        copier(text)
                        _debug_log("windows-insert", "final fallback: clipboard only")
                        print(
                            "morvox: direct typing and auto-paste both failed; "
                            "transcript copied to clipboard instead.",
                            file=sys.stderr,
                        )
                    else:
                        _debug_log("windows-insert", "fallback succeeded via direct typing")
                        print(
                            "morvox: automatic paste failed; used direct typing "
                            "for the focused app instead.",
                            file=sys.stderr,
                        )
                else:
                    _debug_log("windows-insert", "primary paste path succeeded")
        else:
            if target:
                refocused = BACKEND.focus_window(target)

            # Type text into the (re-)focused window.
            BACKEND.type_text(text, args.type_delay)
    except Exception as e:
        try:
            with _whisper_log().open("a", encoding="utf-8") as f:
                f.write(f"\n--- post-processing error ---\n{type(e).__name__}: {e}\n")
                stderr = getattr(e, "stderr", None)
                if stderr:
                    f.write(f"stderr: {stderr}\n")
        except OSError:
            pass
        signal_widget("error", terminate=False)
        time.sleep(1.2)
        close_widget()
        cleanup_state(keep_temp=args.keep_temp)
        print(f"morvox: failed after transcription: {e}", file=sys.stderr)
        return 1

    signal_widget("done", terminate=True)
    close_widget()
    cleanup_state(keep_temp=args.keep_temp)
    if not refocused and target:
        return 0  # warning already emitted
    return 0
