"""morvox.backends.linux — LinuxX11Backend (also handles Wayland fallback chain)."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..constants import LEVEL_CHUNK_MS


class LinuxX11Backend:
    name = "x11"

    def required_tools(self) -> list[str]:
        # xdotool is still needed on Wayland for get_active_window (XWayland)
        # and as a last-resort typing fallback. For typing on Wayland we
        # prefer wtype (most compositors) or ydotool (GNOME/Mutter), but
        # neither is hard-required because xdotool serves as the fallback.
        return ["parecord", "xdotool"]

    def has_display(self) -> bool:
        return bool(os.environ.get("DISPLAY") or
                    os.environ.get("WAYLAND_DISPLAY"))

    # ---- audio ----

    def record_to_wav(self, source: str | None, wav_path: Path,
                      log_fd, stream_pcm: bool = False) -> subprocess.Popen:
        cmd = [
            "parecord",
            "--channels=1",
            "--rate=16000",
            "--format=s16le",
            "--file-format=wav",
        ]
        if source:
            cmd += ["-d", source]
        cmd.append(str(wav_path))
        return subprocess.Popen(
            cmd, stdout=log_fd, stderr=log_fd, stdin=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )

    def record_pcm_stream(self, source: str | None,
                          log_fd) -> subprocess.Popen:
        cmd = [
            "parec",
            "--raw",
            "--channels=1",
            "--rate=16000",
            "--format=s16le",
            f"--latency-msec={LEVEL_CHUNK_MS}",
        ]
        if source:
            cmd += ["-d", source]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=log_fd,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )

    # ---- window control ----

    def get_active_window(self) -> str | None:
        from ..state import die
        try:
            out = subprocess.run(
                ["xdotool", "getactivewindow"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as e:
            die(f"xdotool getactivewindow failed: {e.stderr.strip()}")
            return None  # unreachable
        return out or None

    def focus_window(self, handle: str, timeout: float = 3.0) -> bool:
        # On native Wayland sessions xdotool windowactivate cannot focus
        # Wayland windows. The Wayland typing tools (wtype/ydotool) inject
        # into whatever is currently focused, so skip refocus entirely.
        if os.environ.get("WAYLAND_DISPLAY"):
            return True
        try:
            subprocess.run(
                ["xdotool", "windowactivate", "--sync", handle],
                check=True, capture_output=True, text=True, timeout=timeout,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            err = getattr(e, "stderr", "") or ""
            print(
                f"morvox: warning: could not re-focus window {handle}: "
                f"{err.strip() if isinstance(err, str) else err}; "
                "typing into currently focused window instead.",
                file=sys.stderr,
            )
            return False

    def type_text(self, text: str, delay_ms: int) -> None:
        # Typing strategy:
        #   1. On Wayland, prefer wtype (zwp_virtual_keyboard_v1).
        #      Works on Sway/Hyprland/KWin/river. GNOME/Mutter does NOT
        #      implement this protocol and wtype will exit 1 with the
        #      message "Compositor does not support the virtual keyboard
        #      protocol".
        #   2. Fall back to ydotool, which uses /dev/uinput at the kernel
        #      level and works on any compositor (including GNOME) provided
        #      the ydotoold daemon is running and the user has access to
        #      /dev/uinput (typically via the `input` group).
        #   3. Clipboard-paste fallback: copy the transcript with wl-copy
        #      and synthesise Ctrl+Shift+V. This is the only path that
        #      works on GNOME Wayland without extra setup. If we still
        #      can't inject the paste keystroke we leave the text on the
        #      clipboard and tell the user to paste manually — much better
        #      than dropping the transcript silently.
        #   4. Finally fall back to xdotool. On native Wayland windows
        #      xdotool exits 0 silently with no effect, so we only use it
        #      on X11 sessions or as a last resort for XWayland clients.
        is_wayland = bool(os.environ.get("WAYLAND_DISPLAY"))

        if is_wayland and shutil.which("wtype"):
            try:
                subprocess.run(
                    ["wtype", "--", text],
                    check=True, capture_output=True, text=True,
                )
                return
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or "").strip()
                # If wtype failed because the compositor lacks the protocol
                # (the GNOME case) we fall through to ydotool. For other
                # errors we still try ydotool, then re-raise if nothing
                # worked.
                print(
                    f"morvox: wtype failed ({stderr or e}); "
                    "trying ydotool fallback.",
                    file=sys.stderr,
                )

        if is_wayland and shutil.which("ydotool"):
            # ydotool's --key-delay is in milliseconds and works on the
            # virtual keyboard regardless of compositor.
            try:
                subprocess.run(
                    ["ydotool", "type", "--key-delay", str(delay_ms),
                     "--", text],
                    check=True, capture_output=True, text=True,
                )
                return
            except subprocess.CalledProcessError as e:
                stderr = (e.stderr or "").strip()
                print(
                    f"morvox: ydotool failed ({stderr or e}). "
                    "Is ydotoold running and is your user in the `input` "
                    "group? Trying clipboard-paste fallback.",
                    file=sys.stderr,
                )

        if is_wayland and shutil.which("wl-copy") and self._paste_via_clipboard(text):
            return

        subprocess.run(
            ["xdotool", "type",
             "--delay", str(delay_ms),
             "--clearmodifiers",
             "--", text],
            check=True,
        )

    def _paste_via_clipboard(self, text: str) -> bool:
        """Copy ``text`` to the Wayland clipboard, then try to send
        Ctrl+Shift+V to the focused window.

        Returns True if the text reached the clipboard; the keystroke
        injection is best-effort. If injection fails we still return True
        (the user can paste manually) but emit a clear hint.
        """
        try:
            subprocess.run(
                ["wl-copy"],
                input=text, text=True,
                check=True, capture_output=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            stderr = getattr(e, "stderr", "") or ""
            print(
                f"morvox: wl-copy failed ({stderr.strip() if isinstance(stderr, str) else e}); "
                "skipping clipboard fallback.",
                file=sys.stderr,
            )
            return False

        # Try to synthesise Ctrl+Shift+V. wtype uses keysym names; ydotool
        # uses Linux input event codes (29=L-Ctrl, 42=L-Shift, 47=V, with
        # ":1" press / ":0" release).
        if shutil.which("wtype"):
            try:
                subprocess.run(
                    ["wtype",
                     "-M", "ctrl", "-M", "shift",
                     "-P", "v", "-p", "v",
                     "-m", "shift", "-m", "ctrl"],
                    check=True, capture_output=True, text=True,
                )
                return True
            except subprocess.CalledProcessError:
                pass

        if shutil.which("ydotool"):
            try:
                subprocess.run(
                    ["ydotool", "key",
                     "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
                    check=True, capture_output=True, text=True,
                )
                return True
            except subprocess.CalledProcessError:
                pass

        # Couldn't inject the paste keystroke. Tell the user, but consider
        # the operation a success — the transcript is on their clipboard.
        print(
            "morvox: transcript copied to clipboard. Press Ctrl+Shift+V "
            "to paste it (no working keystroke injector found — install "
            "ydotoold or use a Wayland compositor that supports "
            "zwp_virtual_keyboard_v1 to enable automatic typing).",
            file=sys.stderr,
        )
        return True

    # ---- display geometry ----

    def pointer_xy(self) -> tuple[int, int] | None:
        try:
            out = subprocess.run(
                ["xdotool", "getmouselocation"],
                capture_output=True, text=True, check=True, timeout=1,
            ).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError):
            return None
        m = re.search(r"x:(-?\d+)\s+y:(-?\d+)", out)
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    def monitors(self) -> list[tuple[int, int, int, int]]:
        try:
            out = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True, text=True, check=True, timeout=2,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError):
            return []
        result: list[tuple[int, int, int, int]] = []
        pat = re.compile(
            r"^\S+\s+connected(?:\s+primary)?\s+(\d+)x(\d+)\+(-?\d+)\+(-?\d+)",
            re.MULTILINE,
        )
        for m in pat.finditer(out):
            w, h, x, y = (int(m.group(i)) for i in (1, 2, 3, 4))
            result.append((x, y, w, h))
        return result

    # ---- widget chrome ----

    def configure_widget_window(self, tk_root) -> None:
        try:
            tk_root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            tk_root.attributes("-type", "dock")
        except Exception:
            pass

    def apply_rounded_corners(self, tk_root, w: int, h: int, r: int,
                              force_remap: bool = False) -> None:
        from ..widget import _apply_rounded_shape
        _apply_rounded_shape(tk_root, w, h, r, force_remap=force_remap)
