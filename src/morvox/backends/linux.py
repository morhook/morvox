"""morvox.backends.linux — LinuxX11Backend (also handles Wayland fallback chain)."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..constants import LEVEL_CHUNK_MS


def _is_wayland_session() -> bool:
    return (
        bool(os.environ.get("WAYLAND_DISPLAY")) or
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )


def _is_sway_session() -> bool:
    return bool(os.environ.get("SWAYSOCK"))


def _is_hyprland_session() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"))


class LinuxX11Backend:
    name = "x11"

    def required_tools(self) -> list[str]:
        if _is_wayland_session():
            return ["parecord"]

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
        if _is_wayland_session():
            return "wayland-current-focus"

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
        # into whatever is currently focused. Close the morvox widget first;
        # compositors such as XFCE Wayland may otherwise leave focus on the
        # Tk/XWayland widget, causing injection to go nowhere useful.
        if _is_wayland_session():
            from ..state import close_widget
            close_widget()
            time.sleep(min(max(timeout, 0.0), 0.2))
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
        is_wayland = _is_wayland_session()

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

        if shutil.which("xdotool"):
            subprocess.run(
                ["xdotool", "type",
                 "--delay", str(delay_ms),
                 "--clearmodifiers",
                 "--", text],
                check=True,
            )
            return

        raise RuntimeError(
            "no text injection tool available; install wtype, ydotool, "
            "wl-clipboard, or xdotool"
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

    def _sway_monitors(self) -> list[tuple[int, int, int, int]]:
        try:
            out = subprocess.run(
                ["swaymsg", "-t", "get_outputs"],
                capture_output=True, text=True, check=True, timeout=2,
            ).stdout
            data = json.loads(out or "[]")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError, json.JSONDecodeError):
            return []

        result: list[tuple[bool, tuple[int, int, int, int]]] = []
        if not isinstance(data, list):
            return []
        for output in data:
            if not isinstance(output, dict):
                continue
            if not output.get("active", False):
                continue
            rect = output.get("rect")
            if not isinstance(rect, dict):
                continue
            try:
                x = int(rect.get("x", 0))
                y = int(rect.get("y", 0))
                w = int(rect.get("width", 0))
                h = int(rect.get("height", 0))
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            result.append((bool(output.get("focused", False)), (x, y, w, h)))

        result.sort(key=lambda item: not item[0])
        return [geometry for _, geometry in result]

    def _hyprland_monitor_names(self) -> list[str]:
        try:
            out = subprocess.run(
                ["hyprctl", "-j", "monitors"],
                capture_output=True, text=True, check=True, timeout=2,
            ).stdout
            data = json.loads(out or "[]")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError, json.JSONDecodeError):
            return []

        result: list[tuple[bool, str]] = []
        if not isinstance(data, list):
            return []
        for output in data:
            if not isinstance(output, dict):
                continue
            if bool(output.get("disabled", False)):
                continue
            name = str(output.get("name") or "").strip()
            if name:
                result.append((bool(output.get("focused", False)), name))

        result.sort(key=lambda item: not item[0])
        return [name for _, name in result]

    def _wlr_randr_monitors(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        try:
            out = subprocess.run(
                ["wlr-randr"],
                capture_output=True, text=True, check=True, timeout=2,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError):
            return []

        result: list[tuple[str, tuple[int, int, int, int]]] = []
        current: dict[str, object] | None = None

        def flush() -> None:
            if not current:
                return
            name = str(current.get("name") or "")
            pos = current.get("pos")
            size = current.get("size")
            if not name or not isinstance(pos, tuple) or not isinstance(size, tuple):
                return
            x, y = pos
            w, h = size
            scale = float(current.get("scale") or 1.0)
            if scale > 0:
                w = round(w / scale)
                h = round(h / scale)
            if w > 0 and h > 0:
                result.append((name, (x, y, w, h)))

        for line in out.splitlines():
            if line and not line.startswith(" "):
                flush()
                current = {"name": line.split(None, 1)[0]}
                continue
            if current is None:
                continue
            stripped = line.strip()
            m = re.match(r"Position:\s*(-?\d+)\s*,\s*(-?\d+)", stripped)
            if m:
                current["pos"] = (int(m.group(1)), int(m.group(2)))
                continue
            m = re.match(r"(\d+)x(\d+)\s+px,.*\bcurrent\b", stripped)
            if m:
                current["size"] = (int(m.group(1)), int(m.group(2)))
                continue
            m = re.match(r"Scale:\s*([0-9.]+)", stripped)
            if m:
                try:
                    current["scale"] = float(m.group(1))
                except ValueError:
                    pass

        flush()
        return result

    def _wlroots_active_output_names(self) -> list[str]:
        try:
            import ctypes
            import ctypes.util
        except ImportError:
            return []

        libname = ctypes.util.find_library("wayland-client")
        if not libname:
            return []
        try:
            wl = ctypes.CDLL(libname)
        except OSError:
            return []

        class WlArray(ctypes.Structure):
            _fields_ = [
                ("size", ctypes.c_size_t),
                ("alloc", ctypes.c_size_t),
                ("data", ctypes.c_void_p),
            ]

        class WlMessage(ctypes.Structure):
            pass

        class WlInterface(ctypes.Structure):
            pass

        WlMessage._fields_ = [
            ("name", ctypes.c_char_p),
            ("signature", ctypes.c_char_p),
            ("types", ctypes.POINTER(ctypes.POINTER(WlInterface))),
        ]
        WlInterface._fields_ = [
            ("name", ctypes.c_char_p),
            ("version", ctypes.c_int),
            ("method_count", ctypes.c_int),
            ("methods", ctypes.POINTER(WlMessage)),
            ("event_count", ctypes.c_int),
            ("events", ctypes.POINTER(WlMessage)),
        ]

        wl.wl_display_connect.argtypes = [ctypes.c_char_p]
        wl.wl_display_connect.restype = ctypes.c_void_p
        wl.wl_display_disconnect.argtypes = [ctypes.c_void_p]
        wl.wl_display_roundtrip.argtypes = [ctypes.c_void_p]
        wl.wl_display_roundtrip.restype = ctypes.c_int
        wl.wl_proxy_add_listener.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        wl.wl_proxy_add_listener.restype = ctypes.c_int
        try:
            wl.wl_proxy_marshal_flags.restype = ctypes.c_void_p
            wl.wl_proxy_get_version.argtypes = [ctypes.c_void_p]
            wl.wl_proxy_get_version.restype = ctypes.c_uint32
            wl.wl_proxy_get_id.argtypes = [ctypes.c_void_p]
            wl.wl_proxy_get_id.restype = ctypes.c_uint32
        except AttributeError:
            return []

        try:
            wl_output_interface = WlInterface.in_dll(wl, "wl_output_interface")
            wl_registry_interface = WlInterface.in_dll(wl, "wl_registry_interface")
        except ValueError:
            return []

        handle_events = (WlMessage * 8)()
        manager_events = (WlMessage * 2)()
        handle_interface = WlInterface(
            b"zwlr_foreign_toplevel_handle_v1", 3, 0, None, 8, handle_events,
        )
        manager_types = (ctypes.POINTER(WlInterface) * 1)(
            ctypes.pointer(handle_interface),
        )
        manager_events[0] = WlMessage(b"toplevel", b"n", manager_types)
        manager_events[1] = WlMessage(b"finished", b"", None)

        output_type = (ctypes.POINTER(WlInterface) * 1)(
            ctypes.pointer(wl_output_interface),
        )
        array_type = (ctypes.POINTER(WlInterface) * 1)(None)
        parent_type = (ctypes.POINTER(WlInterface) * 1)(
            ctypes.pointer(handle_interface),
        )
        handle_events[0] = WlMessage(b"title", b"s", None)
        handle_events[1] = WlMessage(b"app_id", b"s", None)
        handle_events[2] = WlMessage(b"output_enter", b"o", output_type)
        handle_events[3] = WlMessage(b"output_leave", b"o", output_type)
        handle_events[4] = WlMessage(b"state", b"a", array_type)
        handle_events[5] = WlMessage(b"done", b"", None)
        handle_events[6] = WlMessage(b"closed", b"", None)
        handle_events[7] = WlMessage(b"parent", b"?o", parent_type)

        manager_interface = WlInterface(
            b"zwlr_foreign_toplevel_manager_v1", 3, 0, None, 2, manager_events,
        )

        state: dict[str, object] = {
            "outputs": {},
            "manager": None,
            "toplevels": [],
            "callbacks": [],
        }

        GlobalCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
        )
        GlobalRemoveCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        )
        OutputGeometryCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32,
            ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32,
            ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int32,
        )
        OutputModeCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_int32, ctypes.c_int32, ctypes.c_int32,
        )
        OutputDoneCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
        OutputScaleCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32,
        )
        OutputNameCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
        )
        OutputDescriptionCb = OutputNameCb
        ManagerToplevelCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        )
        ManagerFinishedCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
        HandleStringCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p,
        )
        HandleOutputCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        )
        HandleStateCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(WlArray),
        )
        HandleNoArgCb = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
        HandleParentCb = ctypes.CFUNCTYPE(
            None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        )

        class RegistryListener(ctypes.Structure):
            _fields_ = [("global", GlobalCb), ("global_remove", GlobalRemoveCb)]

        class OutputListener(ctypes.Structure):
            _fields_ = [
                ("geometry", OutputGeometryCb),
                ("mode", OutputModeCb),
                ("done", OutputDoneCb),
                ("scale", OutputScaleCb),
                ("name", OutputNameCb),
                ("description", OutputDescriptionCb),
            ]

        class ManagerListener(ctypes.Structure):
            _fields_ = [("toplevel", ManagerToplevelCb), ("finished", ManagerFinishedCb)]

        class HandleListener(ctypes.Structure):
            _fields_ = [
                ("title", HandleStringCb),
                ("app_id", HandleStringCb),
                ("output_enter", HandleOutputCb),
                ("output_leave", HandleOutputCb),
                ("state", HandleStateCb),
                ("done", HandleNoArgCb),
                ("closed", HandleNoArgCb),
                ("parent", HandleParentCb),
            ]

        def output_id(output) -> int:
            return int(wl.wl_proxy_get_id(output))

        def add_listener(proxy, listener) -> int:
            return wl.wl_proxy_add_listener(proxy, ctypes.byref(listener), None)

        def display_get_registry(display):
            return wl.wl_proxy_marshal_flags(
                ctypes.c_void_p(display), ctypes.c_uint32(1),
                ctypes.cast(ctypes.pointer(wl_registry_interface), ctypes.c_void_p),
                ctypes.c_uint32(wl.wl_proxy_get_version(display)),
                ctypes.c_uint32(0), ctypes.c_void_p(0),
            )

        def registry_bind(registry, name, interface, version):
            return wl.wl_proxy_marshal_flags(
                ctypes.c_void_p(registry), ctypes.c_uint32(0),
                ctypes.cast(ctypes.pointer(interface), ctypes.c_void_p),
                ctypes.c_uint32(version), ctypes.c_uint32(0),
                ctypes.c_uint32(name), ctypes.c_char_p(interface.name),
                ctypes.c_uint32(version), ctypes.c_void_p(0),
            )

        def on_output_name(_data, output, name) -> None:
            outputs = state["outputs"]
            assert isinstance(outputs, dict)
            outputs[output_id(output)] = name.decode(errors="replace")

        def on_toplevel(_data, _manager, toplevel) -> None:
            info = {"active": False, "outputs": []}
            toplevels = state["toplevels"]
            assert isinstance(toplevels, list)
            toplevels.append(info)

            def on_output_enter(_data2, _handle, output) -> None:
                outputs = info["outputs"]
                assert isinstance(outputs, list)
                oid = output_id(output)
                if oid not in outputs:
                    outputs.append(oid)

            def on_output_leave(_data2, _handle, output) -> None:
                outputs = info["outputs"]
                assert isinstance(outputs, list)
                oid = output_id(output)
                if oid in outputs:
                    outputs.remove(oid)

            def on_state(_data2, _handle, values) -> None:
                arr = values.contents
                count = arr.size // ctypes.sizeof(ctypes.c_uint32)
                if not arr.data or count <= 0:
                    info["active"] = False
                    return
                nums = ctypes.cast(
                    arr.data, ctypes.POINTER(ctypes.c_uint32 * count),
                ).contents
                info["active"] = 2 in nums

            listener = HandleListener(
                HandleStringCb(lambda _d, _h, _s: None),
                HandleStringCb(lambda _d, _h, _s: None),
                HandleOutputCb(on_output_enter),
                HandleOutputCb(on_output_leave),
                HandleStateCb(on_state),
                HandleNoArgCb(lambda _d, _h: None),
                HandleNoArgCb(lambda _d, _h: None),
                HandleParentCb(lambda _d, _h, _p: None),
            )
            callbacks = state["callbacks"]
            assert isinstance(callbacks, list)
            callbacks.append(listener)
            add_listener(toplevel, listener)

        output_listener = OutputListener(
            OutputGeometryCb(lambda *_args: None),
            OutputModeCb(lambda *_args: None),
            OutputDoneCb(lambda *_args: None),
            OutputScaleCb(lambda *_args: None),
            OutputNameCb(on_output_name),
            OutputDescriptionCb(lambda *_args: None),
        )

        def on_global(_data, registry, name, interface, version) -> None:
            iface = interface.decode(errors="replace")
            if iface == "wl_output":
                output = registry_bind(
                    registry, name, wl_output_interface, min(int(version), 4),
                )
                add_listener(output, output_listener)
            elif iface == "zwlr_foreign_toplevel_manager_v1":
                manager = registry_bind(
                    registry, name, manager_interface, min(int(version), 3),
                )
                state["manager"] = manager
                add_listener(manager, manager_listener)

        registry_listener = RegistryListener(
            GlobalCb(on_global), GlobalRemoveCb(lambda *_args: None),
        )
        manager_listener = ManagerListener(
            ManagerToplevelCb(on_toplevel), ManagerFinishedCb(lambda *_args: None),
        )
        callbacks = state["callbacks"]
        assert isinstance(callbacks, list)
        callbacks.extend([output_listener, registry_listener, manager_listener])

        display = wl.wl_display_connect(None)
        if not display:
            return []
        try:
            registry = display_get_registry(display)
            if not registry:
                return []
            if add_listener(registry, registry_listener) != 0:
                return []
            if wl.wl_display_roundtrip(display) < 0:
                return []
            if wl.wl_display_roundtrip(display) < 0:
                return []
            manager = state["manager"]
            if not manager:
                return []
            for _ in range(3):
                if wl.wl_display_roundtrip(display) < 0:
                    return []
            outputs = state["outputs"]
            toplevels = state["toplevels"]
            assert isinstance(outputs, dict)
            assert isinstance(toplevels, list)
            result: list[str] = []
            for info in toplevels:
                if not info.get("active"):
                    continue
                for oid in info.get("outputs", set()):
                    name = outputs.get(oid)
                    if name and name not in result:
                        result.append(name)
            return result
        except Exception:
            return []
        finally:
            wl.wl_display_disconnect(display)

    def _xrandr_monitors(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        try:
            out = subprocess.run(
                ["xrandr", "--query"],
                capture_output=True, text=True, check=True, timeout=2,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError, OSError):
            return []
        result: list[tuple[str, tuple[int, int, int, int]]] = []
        pat = re.compile(
            r"^(\S+)\s+connected(?:\s+primary)?\s+"
            r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)",
            re.MULTILINE,
        )
        for m in pat.finditer(out):
            name = m.group(1)
            w, h, x, y = (int(m.group(i)) for i in (2, 3, 4, 5))
            result.append((name, (x, y, w, h)))
        return result

    def pointer_xy(self) -> tuple[int, int] | None:
        if _is_wayland_session():
            return None
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
        if _is_sway_session():
            sway_monitors = self._sway_monitors()
            if sway_monitors:
                return sway_monitors

        if _is_wayland_session():
            wlr_monitors = self._wlr_randr_monitors()
            if wlr_monitors:
                names = self._hyprland_monitor_names() if _is_hyprland_session() else []
                names = names or self._wlroots_active_output_names()
                if names:
                    by_name = dict(wlr_monitors)
                    ordered = [by_name[name] for name in names if name in by_name]
                    ordered += [geometry for name, geometry in wlr_monitors
                                if name not in names]
                    if ordered:
                        return ordered
                return [geometry for _, geometry in wlr_monitors]

        xrandr_monitors = self._xrandr_monitors()
        if _is_hyprland_session() and xrandr_monitors:
            names = self._hyprland_monitor_names()
            if names:
                by_name = dict(xrandr_monitors)
                ordered = [by_name[name] for name in names if name in by_name]
                ordered += [geometry for name, geometry in xrandr_monitors
                            if name not in names]
                if ordered:
                    return ordered

        return [geometry for _, geometry in xrandr_monitors]

    # ---- widget chrome ----

    def configure_widget_window(self, tk_root) -> None:
        try:
            tk_root.attributes("-topmost", True)
        except Exception:
            pass
        if _is_wayland_session():
            # Under Wayland, Tk runs through XWayland. Marking that window as
            # a notification lets compositors apply notification placement
            # policy, and some move it to another output when it resizes.
            return
        try:
            tk_root.attributes("-type", "dock")
        except Exception:
            pass

    def apply_rounded_corners(self, tk_root, w: int, h: int, r: int,
                              force_remap: bool = False) -> None:
        from ..widget import _apply_rounded_shape
        _apply_rounded_shape(tk_root, w, h, r, force_remap=force_remap)
