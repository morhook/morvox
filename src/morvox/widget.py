"""morvox.widget — widget spawn and Tk runtime subprocess."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .constants import (
    LEVEL_CHUNK_MS,
    LEVEL_SAMPLE_RATE,
    STATE_DIR,
    WIDGET_BOTTOM_OFFSET,
    WIDGET_FPS,
    WIDGET_H,
    WIDGET_RADIUS,
    WIDGET_W,
)
from .state import (
    _has_display,
    _widget_log,
    _widget_pid_file,
    _widget_state_file,
    _write_widget_state,
)

_TKINTER_HINT_PRINTED = False


def spawn_widget(source: str | None,
                 pcm_proc: subprocess.Popen | None = None) -> None:
    """Spawn a morvox --widget pipeline so the widget gets live PCM.

    If *pcm_proc* is given and has a valid stdout pipe, its stdout is used
    as the PCM source (avoids a second audio-device consumer). Otherwise a
    new recorder is started via the backend.

    Writes the widget process PID to the widget pid file. Best-effort: any
    failure is logged to widget.log and swallowed; recording is unaffected.
    """
    global _TKINTER_HINT_PRINTED

    if not _has_display():
        return

    # Pre-flight: if tkinter can't even be imported in the same Python,
    # there's no point spawning the widget — print a tailored install
    # hint once and move on. This is the single biggest cause of "I
    # installed python3-tk via brew but the widget never appears" on
    # macOS, where the correct formula is `python-tk` (matching the
    # Python version), not `python3-tk`.
    ok, err = _preflight_tkinter()
    if not ok:
        if not _TKINTER_HINT_PRINTED:
            _TKINTER_HINT_PRINTED = True
            print(
                f"morvox: widget disabled — tkinter unavailable.{_tkinter_install_hint()}"
                + (f"\n  detail: {err}" if err else ""),
                file=sys.stderr,
            )
        return

    # Reset state file so the widget starts in 'recording' mode.
    _write_widget_state("recording")

    from .backends import BACKEND

    self_path = os.path.realpath(sys.argv[0])
    widget_cmd = [sys.executable, self_path, "--widget"]

    # Open the widget log file (used for widget stderr/stdout).
    log_path = _widget_log()
    try:
        log_fd = open(log_path, "wb")
    except OSError:
        return

    # Determine the PCM source for the widget's stdin.
    #
    #   - If *pcm_proc* already has a stdout pipe, use it (avoids a second
    #     audio-device consumer on backends like Windows dshow where the
    #     device can't be shared).
    #   - On Windows without a shared recorder pipe, skip live PCM rather
    #     than opening the microphone a second time.
    #   - On other platforms (Linux PulseAudio, macOS AVFoundation) start
    #     a dedicated PCM stream, which is safe because those APIs allow
    #     multiple consumers on the same device.
    if pcm_proc is not None and pcm_proc.stdout is not None:
        parec_proc = pcm_proc
        widget_stdin = parec_proc.stdout
    elif sys.platform == "win32":
        parec_proc = None
        widget_stdin = subprocess.DEVNULL
    else:
        try:
            parec_proc = BACKEND.record_pcm_stream(source, log_fd)
        except FileNotFoundError:
            log_fd.close()
            return
        widget_stdin = parec_proc.stdout

    env = os.environ.copy()
    env["MORVOX_WIDGET_START"] = str(time.time())
    env["MORVOX_STATE_DIR"] = STATE_DIR

    try:
        widget_proc = subprocess.Popen(
            widget_cmd,
            stdin=widget_stdin,
            stdout=log_fd,
            stderr=log_fd,
            close_fds=True,
            env=env,
            **_session_popen_kwargs(),
        )
    except (FileNotFoundError, OSError):
        try:
            if parec_proc is not None:
                parec_proc.terminate()
        except Exception:
            pass
        log_fd.close()
        return

    # The widget owns the read end now; parent doesn't need it.
    try:
        if parec_proc is not None and parec_proc.stdout:
            parec_proc.stdout.close()
    except Exception:
        pass
    try:
        log_fd.close()
    except Exception:
        pass

    try:
        _widget_pid_file().write_text(f"{widget_proc.pid}\n")
    except OSError:
        pass

    # Give the widget subprocess a brief moment to fail-fast (e.g. missing
    # tkinter, no $DISPLAY, etc.). If it exited already, surface a one-time
    # hint to stderr so the user isn't left wondering why the widget never
    # appears, and clean up the pid file so close_widget() is a no-op.
    #
    # macOS gets a longer grace window because `ffmpeg -f avfoundation`
    # routinely takes 200-400 ms to bind the audio device; we don't want
    # to declare "early exit" while it's still booting.
    grace = 0.4 if sys.platform in ("darwin", "win32") else 0.15
    time.sleep(grace)
    if widget_proc.poll() is not None:
        log_excerpt = ""
        try:
            log_excerpt = log_path.read_text(errors="replace").strip()
        except OSError:
            pass
        hint = ""
        excerpt_lc = log_excerpt.lower()
        if (
            "no module named 'tkinter'" in log_excerpt
            or "morvox-widget: tkinter import failed" in log_excerpt
            or "morvox-widget: tk.tk() failed" in excerpt_lc
        ):
            hint = _tkinter_install_hint()
        elif (
            "avfoundation" in excerpt_lc
            and ("not permitted" in excerpt_lc
                 or "input/output error" in excerpt_lc
                 or "permission" in excerpt_lc
                 or "denied" in excerpt_lc)
        ):
            hint = (
                " (microphone access likely denied — System Settings -> "
                "Privacy & Security -> Microphone, enable your terminal app)"
            )
        elif "ffmpeg" in excerpt_lc and "not found" in excerpt_lc:
            hint = " (ffmpeg not found — `brew install ffmpeg`)"
        print(
            f"morvox: warning: widget subprocess exited early "
            f"(rc={widget_proc.returncode}){hint}. "
            f"Continuing without the widget. See {log_path}.",
            file=sys.stderr,
        )
        try:
            _widget_pid_file().unlink(missing_ok=True)
        except OSError:
            pass


def _tkinter_install_hint() -> str:
    """Build a platform-specific install hint for missing tkinter."""
    if sys.platform == "darwin":
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        return (
            f" (Python at {sys.executable} cannot `import tkinter`. "
            f"On macOS with Homebrew install the matching Tk for your "
            f"Python, e.g. `brew install python-tk@{ver}`. Note: there "
            f"is no `python3-tk` formula on Homebrew. Or pass --no-widget "
            f"to silence this warning.)"
        )
    if sys.platform == "win32":
        return (
            " (Python at " + sys.executable + " cannot `import tkinter`. "
            "Install a Python build that includes Tcl/Tk, or pass "
            "--no-widget to silence this warning.)"
        )
    return (
        " (your Python build lacks tkinter — on Debian/Ubuntu install "
        "`python3-tk`, or pass --no-widget to silence this warning)"
    )


def _preflight_tkinter() -> tuple[bool, str]:
    """Verify the same Python that will run --widget can import tkinter.

    Returns (ok, error_text). Cheap (<100 ms typically); avoids spawning
    the full widget pipeline when we can predict it will fail.
    """
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import tkinter"],
            capture_output=True, text=True, timeout=5,
            **_session_popen_kwargs(),
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, f"tkinter preflight failed: {e}"
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout or "").strip()


def _session_popen_kwargs() -> dict:
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return {"creationflags": flags}
    return {"start_new_session": True}


def _pick_monitor_geometry(fallback_w: int, fallback_h: int) -> tuple[int, int, int, int]:
    """Pick the monitor geometry to anchor the widget to.

    Strategy:
      1. Ask the backend for connected monitors.
      2. Ask the backend for the pointer position.
      3. Return the monitor containing the pointer.
      4. Fall back to the first monitor, then to (0, 0, fallback_w, fallback_h).
    """
    from .backends import BACKEND

    monitors = BACKEND.monitors()
    if not monitors:
        return (0, 0, fallback_w, fallback_h)

    mouse = BACKEND.pointer_xy()
    if mouse is not None:
        mx, my = mouse
        for (x, y, w, h) in monitors:
            if x <= mx < x + w and y <= my < y + h:
                return (x, y, w, h)

    # No pointer hit — prefer the first monitor (lists primary first when present).
    return monitors[0]


def _compute_rms(chunk: bytes) -> float:
    """Compute normalized RMS (0.0–1.0) from a buffer of s16le PCM samples."""
    if not chunk:
        return 0.0
    n = len(chunk) // 2
    if n == 0:
        return 0.0
    # Unpack as signed 16-bit little-endian via int.from_bytes per-sample.
    # For ~960-byte chunks (480 samples @ 30ms/16kHz) this is fast enough.
    total = 0
    for i in range(0, n * 2, 2):
        s = int.from_bytes(chunk[i:i + 2], "little", signed=True)
        total += s * s
    mean_sq = total / n
    rms = mean_sq ** 0.5
    # Normalize against int16 max; clamp.
    norm = rms / 32768.0
    if norm > 1.0:
        norm = 1.0
    return norm


def _apply_rounded_shape(tk_window, w, h, r, force_remap=False):
    """Apply an X11 Shape mask to give a Tk window rounded corners.

    Silently no-ops if libX11/libXext are unavailable or the call fails,
    so the widget still works (just with square corners) on non-X11 or
    unusual setups.

    Tk wraps overrideredirect toplevels in an outer X window, and on
    composited setups (e.g. fastcompmgr/xcompmgr) only that outer window
    is rendered to the screen — so we walk up the X tree from the inner
    XID returned by ``winfo_id()`` to the topmost ancestor that's a
    direct child of the root window, and apply both the bounding and
    clip shapes to every window in that chain.

    When ``force_remap`` is True the topmost ancestor is briefly unmapped
    and remapped after the shape is applied. Some compositors (notably
    xcompmgr/fastcompmgr) cache the window's bounding region at map time
    and never re-query it; remapping forces them to pick up the new
    shape so the corners are rounded on first render rather than after
    the next full screen refresh.
    """
    import ctypes
    import ctypes.util
    import math

    try:
        xext_path = ctypes.util.find_library("Xext") or "libXext.so.6"
        x11_path = ctypes.util.find_library("X11") or "libX11.so.6"
        xext = ctypes.CDLL(xext_path)
        x11 = ctypes.CDLL(x11_path)
    except OSError:
        return

    class XRectangle(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_short),
            ("y", ctypes.c_short),
            ("width", ctypes.c_ushort),
            ("height", ctypes.c_ushort),
        ]

    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XQueryTree.restype = ctypes.c_int
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XUnmapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XClearArea.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.c_int, ctypes.c_int,
        ctypes.c_uint, ctypes.c_uint,
        ctypes.c_int,
    ]
    xext.XShapeQueryExtension.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    xext.XShapeQueryExtension.restype = ctypes.c_int
    xext.XShapeCombineRectangles.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
        ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(XRectangle), ctypes.c_int,
        ctypes.c_int, ctypes.c_int,
    ]

    # Ensure the window is realized & mapped so winfo_id() returns a real XID.
    try:
        tk_window.update()
    except Exception:
        return
    inner_xid = tk_window.winfo_id()
    if not inner_xid:
        return

    try:
        display_name = tk_window.tk.call("winfo", "screen", tk_window._w)
    except Exception:
        display_name = ""
    dpy = x11.XOpenDisplay(display_name.encode() if display_name else None)
    if not dpy:
        return

    try:
        # Confirm the X Shape extension is available on this display.
        ev_base = ctypes.c_int(0)
        err_base = ctypes.c_int(0)
        if not xext.XShapeQueryExtension(dpy, ctypes.byref(ev_base),
                                         ctypes.byref(err_base)):
            return

        # Walk up the window tree from the inner Tk window to the topmost
        # ancestor whose parent is the root window. Tk's overrideredirect
        # toplevel is one or two levels above winfo_id().
        root_win = x11.XDefaultRootWindow(dpy)
        chain = [inner_xid]
        target = inner_xid
        for _ in range(8):  # safety cap; never deeper than 2-3 in practice
            r_ret = ctypes.c_ulong(0)
            p_ret = ctypes.c_ulong(0)
            kids = ctypes.POINTER(ctypes.c_ulong)()
            nkids = ctypes.c_uint(0)
            ok = x11.XQueryTree(dpy, ctypes.c_ulong(target),
                                ctypes.byref(r_ret), ctypes.byref(p_ret),
                                ctypes.byref(kids), ctypes.byref(nkids))
            if kids:
                x11.XFree(kids)
            if not ok or p_ret.value == 0 or p_ret.value == root_win:
                break
            target = p_ret.value
            chain.append(target)

        # Build horizontal 1-px scanlines for the rounded-rect region.
        rects = []
        cx_l = r - 0.5
        cx_r = (w - r) - 0.5
        cy_t = r - 0.5
        cy_b = (h - r) - 0.5
        for y in range(h):
            if y < r:
                dy = cy_t - y
            elif y >= h - r:
                dy = y - cy_b
            else:
                dy = -1.0
            if dy < 0:
                x0, x1 = 0, w
            else:
                inner = (r - 0.5) ** 2 - dy * dy
                if inner < 0:
                    continue
                dx = math.sqrt(inner)
                x0 = max(0, int(round(cx_l - dx)))
                x1 = min(w, int(round(cx_r + dx + 1)))
                if x1 <= x0:
                    continue
            rects.append(XRectangle(x0, y, x1 - x0, 1))

        if not rects:
            return

        arr = (XRectangle * len(rects))(*rects)
        SHAPE_BOUNDING = 0
        SHAPE_CLIP = 1
        SHAPE_SET = 0
        UNSORTED = 0

        # Apply bounding + clip shapes to every window in the chain so the
        # compositor (which composites the outermost ancestor) and the X
        # server's own renderer (which honours the inner window's clip)
        # both produce rounded corners.
        for win in chain:
            xext.XShapeCombineRectangles(
                dpy, ctypes.c_ulong(win), SHAPE_BOUNDING,
                0, 0, arr, len(rects), SHAPE_SET, UNSORTED,
            )
            xext.XShapeCombineRectangles(
                dpy, ctypes.c_ulong(win), SHAPE_CLIP,
                0, 0, arr, len(rects), SHAPE_SET, UNSORTED,
            )
        x11.XSync(dpy, 0)

        # If requested, force the compositor to re-evaluate the window
        # by unmapping and remapping the topmost ancestor. This makes
        # xcompmgr/fastcompmgr pick up the new bounding region on the
        # subsequent map event instead of caching the old rectangular
        # one until the next full screen refresh.
        if force_remap and chain:
            outer = chain[-1]
            x11.XUnmapWindow(dpy, ctypes.c_ulong(outer))
            x11.XSync(dpy, 0)
            x11.XMapWindow(dpy, ctypes.c_ulong(outer))
            # Trigger an Expose so the canvas redraws into the freshly
            # mapped (and now correctly-shaped) window.
            x11.XClearArea(
                dpy, ctypes.c_ulong(outer),
                0, 0, ctypes.c_uint(w), ctypes.c_uint(h), 1,
            )
            x11.XSync(dpy, 0)
    finally:
        x11.XCloseDisplay(dpy)


def cmd_widget() -> int:
    """Entry point for the widget subprocess. Reads PCM from stdin, draws UI."""
    try:
        import tkinter as tk
    except Exception as e:
        print(f"morvox-widget: tkinter import failed: {e}", file=sys.stderr)
        return 1

    import math
    import queue
    import threading

    chunk_bytes = LEVEL_SAMPLE_RATE * 2 * LEVEL_CHUNK_MS // 1000  # 960 bytes
    level_q: "queue.Queue[float]" = queue.Queue(maxsize=4)
    stop_flag = threading.Event()

    def reader() -> None:
        stdin = sys.stdin.buffer
        while not stop_flag.is_set():
            try:
                buf = stdin.read(chunk_bytes)
            except Exception:
                break
            if not buf:
                break
            rms = _compute_rms(buf)
            try:
                level_q.put_nowait(rms)
            except queue.Full:
                # Drop a stale sample, keep the freshest.
                try:
                    level_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    level_q.put_nowait(rms)
                except queue.Full:
                    pass

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    # ---- tk window ---------------------------------------------------------

    from .backends import BACKEND

    try:
        root = tk.Tk()
    except Exception as e:
        # tk.Tk() can fail on macOS if the user's Python wasn't built with
        # Tk, or DISPLAY is unset on Linux. Surface to widget.log.
        print(f"morvox-widget: tk.Tk() failed: {e}", file=sys.stderr)
        return 1
    root.title("morvox")
    # On macOS, prefer the MacWindowStyle borderless mode applied by
    # configure_widget_window over overrideredirect (which has rendering
    # bugs in Aqua Tk). On X11 we keep overrideredirect.
    if BACKEND.name != "macos":
        try:
            root.overrideredirect(True)
        except tk.TclError:
            pass
    try:
        BACKEND.configure_widget_window(root)
    except Exception as e:
        print(f"morvox-widget: configure_widget_window failed: {e}",
              file=sys.stderr)

    bg = "#1e1e1e"
    border = "#3c3c3c"
    text_color = "#e6e6e6"
    text_dim = "#888888"
    dot_active = "#e74c3c"
    dot_dim = "#5a2a26"
    bar_green = "#2ecc71"
    bar_yellow = "#f1c40f"
    bar_red = "#e74c3c"
    bar_off = "#2a2a2a"

    # The widget background is always opaque. On X11 the outer window is
    # shaped to a rounded rect by XShape; on macOS we accept square corners
    # because the previous transparency-based approach rendered the widget
    # invisible on most Aqua Tk builds.
    canvas_bg = bg

    root.configure(bg=canvas_bg)
    canvas = tk.Canvas(
        root,
        width=WIDGET_W,
        height=WIDGET_H,
        bg=canvas_bg,
        highlightthickness=0,
        bd=0,
    )
    canvas.pack(padx=0, pady=0)

    # Place bottom-center on the monitor containing the mouse cursor (or the
    # primary monitor if we can't tell). Falling back to the full virtual
    # screen would split the widget across monitors on multi-head setups.
    root.update_idletasks()
    mon_x, mon_y, mon_w, mon_h = _pick_monitor_geometry(
        root.winfo_screenwidth(), root.winfo_screenheight(),
    )
    x = mon_x + (mon_w - WIDGET_W) // 2
    y = mon_y + mon_h - WIDGET_H - WIDGET_BOTTOM_OFFSET
    # Clamp to keep the widget at least partly on-screen if the chosen
    # monitor geometry is bogus (e.g. pyobjc missing on macOS reporting a
    # too-small Tk-screen size).
    if y < mon_y:
        y = mon_y + max(0, mon_h - WIDGET_H - 20)
    if x < mon_x:
        x = mon_x
    root.geometry(f"{WIDGET_W}x{WIDGET_H}+{x}+{y}")
    if BACKEND.name == "windows":
        try:
            root.update_idletasks()
        except Exception:
            pass
        try:
            BACKEND.configure_widget_window(root)
        except Exception:
            pass
    # Visibility safety net: some macOS / Tk combos leave the window
    # withdrawn until something prods it. Schedule a deiconify+lift after
    # the event loop has had a chance to map the window. Cheap on Linux.
    def _ensure_visible() -> None:
        if BACKEND.name == "windows":
            return
        try:
            root.deiconify()
        except Exception:
            pass
        try:
            root.lift()
        except Exception:
            pass

    root.after(50, _ensure_visible)
    root.after(250, _ensure_visible)

    # Cut the four corners off so they're truly transparent (revealing
    # whatever's behind us) instead of showing as solid-color nubs. On X11
    # this uses the Shape extension; on macOS this enables transparency
    # and relies on the canvas-drawn rounded body above.
    #
    # Initial X11 application uses force_remap=True so compositors that
    # cache the window's shape at map time (xcompmgr/fastcompmgr)
    # re-evaluate it immediately. We also re-apply on <Map>/<Configure>
    # as a safety net.
    def _reshape(_evt=None):
        BACKEND.apply_rounded_corners(root, WIDGET_W, WIDGET_H, WIDGET_RADIUS)

    BACKEND.apply_rounded_corners(root, WIDGET_W, WIDGET_H, WIDGET_RADIUS,
                                  force_remap=True)
    root.bind("<Map>", _reshape, add="+")
    root.bind("<Configure>", _reshape, add="+")
    root.after_idle(_reshape)

    # ---- drawing -----------------------------------------------------------

    # Recording dot
    DOT_CX, DOT_CY, DOT_R = 22, WIDGET_H // 2, 7
    dot_id = canvas.create_oval(
        DOT_CX - DOT_R, DOT_CY - DOT_R,
        DOT_CX + DOT_R, DOT_CY + DOT_R,
        fill=dot_active, outline="",
    )

    # VU meter bars
    BAR_COUNT = 16
    BAR_W = 8
    BAR_GAP = 2
    BAR_H_MAX = 30
    BAR_AREA_X = 44
    BAR_AREA_Y = WIDGET_H // 2
    bar_ids = []
    for i in range(BAR_COUNT):
        bx = BAR_AREA_X + i * (BAR_W + BAR_GAP)
        bid = canvas.create_rectangle(
            bx, BAR_AREA_Y - BAR_H_MAX // 2,
            bx + BAR_W, BAR_AREA_Y + BAR_H_MAX // 2,
            fill=bar_off, outline="",
        )
        bar_ids.append(bid)

    # Spinner dots (hidden until transcribing)
    SPIN_COUNT = 4
    SPIN_R = 4
    SPIN_GAP = 14
    spin_total_w = (SPIN_COUNT - 1) * SPIN_GAP
    SPIN_BASE_X = BAR_AREA_X + (BAR_COUNT * (BAR_W + BAR_GAP) - BAR_GAP - spin_total_w) // 2
    SPIN_BASE_Y = BAR_AREA_Y
    spin_ids = []
    for i in range(SPIN_COUNT):
        sx = SPIN_BASE_X + i * SPIN_GAP
        sid = canvas.create_oval(
            sx - SPIN_R, SPIN_BASE_Y - SPIN_R,
            sx + SPIN_R, SPIN_BASE_Y + SPIN_R,
            fill=text_dim, outline="", state="hidden",
        )
        spin_ids.append(sid)

    # Status label (Transcribing… / No speech / etc.)
    status_label_id = canvas.create_text(
        BAR_AREA_X + (BAR_COUNT * (BAR_W + BAR_GAP)) // 2,
        BAR_AREA_Y - BAR_H_MAX // 2 - 10,
        text="", fill=text_color, font=("TkDefaultFont", 9),
        state="hidden",
    )

    # Timer
    timer_id = canvas.create_text(
        WIDGET_W - 12, BAR_AREA_Y,
        text="0:00", fill=text_color, anchor="e",
        font=("TkFixedFont", 11),
    )

    # ---- animation state ---------------------------------------------------

    start_ts = float(os.environ.get("MORVOX_WIDGET_START") or time.time())
    state = {"name": "recording", "level": 0.0, "t0": time.time()}

    def read_state_file() -> None:
        try:
            sf = _widget_state_file()
            if sf.exists():
                s = sf.read_text().strip()
                if s and s != state["name"]:
                    state["name"] = s
        except OSError:
            pass

    def on_sigusr1(_signum, _frame) -> None:
        # Just nudge; main loop will read the file.
        pass

    def on_sigterm(_signum, _frame) -> None:
        stop_flag.set()
        try:
            root.after(0, root.destroy)
        except Exception:
            os._exit(0)

    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, on_sigusr1)
    signal.signal(signal.SIGTERM, on_sigterm)

    def lerp_color(c1: str, c2: str, t: float) -> str:
        # c1, c2 like "#rrggbb"
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    frame_interval = max(1, int(1000 / WIDGET_FPS))

    def tick() -> None:
        read_state_file()
        now = time.time()

        # Drain queue; keep most recent level.
        latest = None
        try:
            while True:
                latest = level_q.get_nowait()
        except queue.Empty:
            pass

        # Smooth level: peak-hold with decay (matches plan).
        if latest is not None:
            # A small noise floor so silence stays at 0.
            if latest < 0.01:
                latest = 0.0
            # Boost a bit so quiet speech is visible (~0.05 RMS = mid bar).
            shaped = min(1.0, latest * 6.0)
            if shaped > state["level"]:
                state["level"] = shaped
            else:
                state["level"] *= 0.85

        # Common: timer
        elapsed = int(now - start_ts)
        mm, ss = divmod(max(0, elapsed), 60)
        timer_text = f"{mm}:{ss:02d}"

        sname = state["name"]

        if sname == "recording":
            # Pulsing dot
            pulse = 0.5 + 0.5 * math.sin((now - state["t0"]) * (2 * math.pi / 1.2))
            dot_color = lerp_color(dot_dim, dot_active, pulse)
            canvas.itemconfig(dot_id, fill=dot_color, outline="")
            # Bars
            lit = int(round(state["level"] * BAR_COUNT))
            for i, bid in enumerate(bar_ids):
                if i < lit:
                    if i < 14:
                        c = bar_green
                    elif i < 18:
                        c = bar_yellow
                    else:
                        c = bar_red
                else:
                    c = bar_off
                canvas.itemconfig(bid, fill=c)
                canvas.itemconfig(bid, state="normal")
            for sid in spin_ids:
                canvas.itemconfig(sid, state="hidden")
            canvas.itemconfig(status_label_id, state="hidden")
            canvas.itemconfig(timer_id, fill=text_color, text=timer_text)

        elif sname == "transcribing":
            # Hollow dot
            canvas.itemconfig(dot_id, fill=bg, outline=dot_active, width=2)
            # Hide bars; show spinner + label
            for bid in bar_ids:
                canvas.itemconfig(bid, state="hidden")
            for i, sid in enumerate(spin_ids):
                phase = (now - state["t0"]) * 4 + i * (math.pi / 2)
                offset = math.sin(phase) * 4
                # Move dot vertically
                sx = SPIN_BASE_X + i * SPIN_GAP
                cy = SPIN_BASE_Y + offset + 4
                canvas.coords(
                    sid,
                    sx - SPIN_R, cy - SPIN_R,
                    sx + SPIN_R, cy + SPIN_R,
                )
                canvas.itemconfig(sid, state="normal", fill=text_color)
            canvas.itemconfig(status_label_id, text="Transcribing…", state="normal")
            canvas.itemconfig(timer_id, fill=text_dim, text=timer_text)

        elif sname == "empty":
            canvas.itemconfig(dot_id, fill=bg, outline=text_dim, width=2)
            for bid in bar_ids:
                canvas.itemconfig(bid, state="hidden")
            for sid in spin_ids:
                canvas.itemconfig(sid, state="hidden")
            canvas.itemconfig(status_label_id, text="No speech detected", state="normal")
            canvas.itemconfig(timer_id, text="")
            # Auto-close after a short hold.
            if "_empty_at" not in state:
                state["_empty_at"] = now
            if now - state["_empty_at"] > 0.9:
                stop_flag.set()
                root.destroy()
                return

        elif sname == "done":
            stop_flag.set()
            root.destroy()
            return

        elif sname == "error":
            canvas.itemconfig(dot_id, fill=bar_red, outline="")
            for bid in bar_ids:
                canvas.itemconfig(bid, state="hidden")
            for sid in spin_ids:
                canvas.itemconfig(sid, state="hidden")
            canvas.itemconfig(status_label_id, text="Error", state="normal")
            canvas.itemconfig(timer_id, text="")
            if "_err_at" not in state:
                state["_err_at"] = now
            if now - state["_err_at"] > 1.2:
                stop_flag.set()
                root.destroy()
                return

        root.after(frame_interval, tick)

    root.after(frame_interval, tick)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_flag.set()
        # Best-effort cleanup of state files (parent may have already done it).
        try:
            _widget_pid_file().unlink(missing_ok=True)
        except OSError:
            pass

    return 0
