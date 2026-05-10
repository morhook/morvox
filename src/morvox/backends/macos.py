"""morvox.backends.macos — MacOSBackend."""

import re
import subprocess
import sys
from pathlib import Path

from ..state import die


class MacOSBackend:
    name = "macos"

    def required_tools(self) -> list[str]:
        return ["ffmpeg", "osascript"]

    def has_display(self) -> bool:
        # Practically every macOS user session has WindowServer; only
        # pure SSH-into-headless-server lacks it. Tk will fail loudly
        # if not, which is fine.
        return True

    # ---- audio ----

    def record_to_wav(self, source: str | None, wav_path: Path,
                      log_fd, stream_pcm: bool = False) -> subprocess.Popen:
        dev = source or ":0"  # avfoundation: ":<audio_idx>" or ":default"
        cmd = [
            "ffmpeg", "-y",
            "-f", "avfoundation",
            "-i", dev,
            "-ac", "1",
            "-ar", "16000",
            "-f", "wav",
            str(wav_path),
        ]
        return subprocess.Popen(
            cmd, stdout=log_fd, stderr=log_fd, stdin=subprocess.DEVNULL,
            start_new_session=True, close_fds=True,
        )

    def record_pcm_stream(self, source: str | None,
                          log_fd) -> subprocess.Popen:
        dev = source or ":0"
        cmd = [
            "ffmpeg",
            "-f", "avfoundation",
            "-i", dev,
            "-ac", "1",
            "-ar", "16000",
            "-f", "s16le",
            "-",
        ]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=log_fd,
            stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )

    # ---- window control ----

    def get_active_window(self) -> str | None:
        try:
            out = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to '
                 'get unix id of (first process whose frontmost is true)'],
                check=True, capture_output=True, text=True, timeout=2,
            ).stdout.strip()
        except subprocess.CalledProcessError as e:
            die(f"osascript getactivewindow failed: "
                f"{(e.stderr or '').strip()}")
            return None  # unreachable
        except subprocess.TimeoutExpired:
            die("osascript getactivewindow timed out")
            return None
        return out or None

    def focus_window(self, handle: str, timeout: float = 3.0) -> bool:
        script = (
            'tell application "System Events" to '
            f'set frontmost of (first process whose unix id is {handle}) '
            'to true'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=True, capture_output=True, text=True, timeout=timeout,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            err = getattr(e, "stderr", "") or ""
            print(
                f"morvox: warning: could not re-focus pid {handle}: "
                f"{err.strip() if isinstance(err, str) else err}; "
                "typing into currently focused app instead.",
                file=sys.stderr,
            )
            return False

    def type_text(self, text: str, delay_ms: int) -> None:
        # AppleScript string literal: escape backslashes and double quotes.
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            'tell application "System Events" to '
            f'keystroke "{escaped}"'
        )
        try:
            subprocess.run(["osascript", "-e", script], check=True)
        except subprocess.CalledProcessError as e:
            # -1743 is errAEEventNotPermitted (Accessibility not granted).
            msg = str(e)
            if "1743" in msg or "not allowed" in msg.lower():
                die(
                    "osascript keystroke was denied. Grant the controlling "
                    "terminal Accessibility permission in System Settings → "
                    "Privacy & Security → Accessibility."
                )
            raise

    # ---- display geometry ----

    def pointer_xy(self) -> tuple[int, int] | None:
        try:
            from Quartz import CGEventCreate, CGEventGetLocation  # type: ignore
        except ImportError:
            return None
        try:
            loc = CGEventGetLocation(CGEventCreate(None))
            return int(loc.x), int(loc.y)
        except Exception:
            return None

    def monitors(self) -> list[tuple[int, int, int, int]]:
        # Preferred path: AppKit via pyobjc gives us per-display origin and
        # size including secondary monitors and the menubar offset.
        try:
            from AppKit import NSScreen  # type: ignore
            out: list[tuple[int, int, int, int]] = []
            for s in NSScreen.screens():
                f = s.frame()
                out.append((int(f.origin.x), int(f.origin.y),
                            int(f.size.width), int(f.size.height)))
            if out:
                return out
        except ImportError:
            pass
        except Exception:
            pass

        # Fallback: parse `system_profiler SPDisplaysDataType -json`. This
        # is stdlib-only and works without pyobjc; we lose true origin
        # info (so all displays are reported at 0,0) but at least the
        # widget can be placed inside a real display's bounds rather than
        # against the Tk primary-screen number, which on macOS sometimes
        # underreports for Retina + external monitor layouts.
        try:
            import json
            proc = subprocess.run(
                ["system_profiler", "-json", "SPDisplaysDataType"],
                capture_output=True, text=True, timeout=2,
            )
            if proc.returncode != 0:
                return []
            data = json.loads(proc.stdout or "{}")
            out2: list[tuple[int, int, int, int]] = []
            for gpu in data.get("SPDisplaysDataType", []):
                for disp in gpu.get("spdisplays_ndrvs", []) or []:
                    res = disp.get("_spdisplays_resolution") \
                        or disp.get("spdisplays_resolution") \
                        or disp.get("_spdisplays_pixels") \
                        or ""
                    # Examples:
                    #   "1512 x 982 @ 120.00Hz"
                    #   "3840x2160"
                    m = re.search(r"(\d+)\s*x\s*(\d+)", str(res))
                    if not m:
                        continue
                    w, h = int(m.group(1)), int(m.group(2))
                    if w > 0 and h > 0:
                        out2.append((0, 0, w, h))
            return out2
        except (FileNotFoundError, subprocess.TimeoutExpired,
                subprocess.CalledProcessError, ValueError):
            return []
        except Exception:
            return []

    # ---- widget chrome ----

    def configure_widget_window(self, tk_root) -> None:
        # Aqua Tk's `overrideredirect(True)` is unreliable: depending on the
        # Tk build the window may never be mapped, never come to front, or
        # render with an invisible background. The documented incantation
        # for "borderless utility window that doesn't steal focus" is the
        # private `MacWindowStyle` Tk command — apply it best-effort.
        try:
            tk_root.tk.call(
                "::tk::unsupported::MacWindowStyle",
                "style", tk_root._w,
                "plain", "noActivates",
            )
        except Exception:
            pass
        try:
            tk_root.attributes("-topmost", True)
        except Exception:
            pass
        # Force the window to actually appear & come forward. With
        # overrideredirect on Aqua, Tk sometimes leaves the window
        # withdrawn until something pokes it.
        try:
            tk_root.update_idletasks()
        except Exception:
            pass
        try:
            tk_root.deiconify()
        except Exception:
            pass
        try:
            tk_root.lift()
        except Exception:
            pass

    def apply_rounded_corners(self, tk_root, w: int, h: int, r: int,
                              force_remap: bool = False) -> None:
        # macOS Tk has no XShape. Older versions of this code tried to make
        # the root window transparent (`bg="systemTransparent"` plus the
        # `-transparent` window attribute) so a rounded-rect polygon drawn
        # on the canvas would peek through with rounded corners. In
        # practice, on most macOS + Tk combinations this rendered the
        # entire widget invisible (the window background went transparent
        # but the polygon never composited correctly under
        # `overrideredirect`). We now leave the window opaque and accept
        # square corners on macOS — same fallback already documented for
        # non-X11 setups.
        return
