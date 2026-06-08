# Setup & installation

## Dependencies

### Linux / X11

- Python 3 plus the packaged `pywhispercpp` dependency installed by `pip`
- `xdotool`
- `pulseaudio-utils` (provides `parecord` and `parec`) — works fine with
  PipeWire's pulse shim

morvox auto-downloads its built-in model on first use and caches it under
`$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
English uses `ggml-base.en.bin`; non-English languages such as `morvox --lang es`
use `ggml-base.bin`. If you pass a custom `--model`, that file must already exist.

`pywhispercpp` ships binary wheels on the common end-user targets we care
about most: Linux x86_64/aarch64, Windows, and macOS arm64. On less common
Python/platform combinations `pip` may still fall back to a local build.

On Debian/Ubuntu, `tkinter` is in the `python3-tk` package; on Arch it
ships with `python`. If `tkinter` is missing, run with `--no-widget`
(morvox will print a one-time warning and continue without the widget).

If you use a third-party Python (asdf, pyenv, conda, ...) and the widget
never appears, check `$XDG_RUNTIME_DIR/morvox/widget.log` or
`/tmp/morvox-$UID/widget.log` — that interpreter is probably built without
`_tkinter`. Either install the system `python3-tk` and use the system
Python, or rebuild your managed Python with Tk support.

### Linux / Wayland

morvox auto-detects Wayland (`$WAYLAND_DISPLAY`) and uses a different
typing strategy because `xdotool type` silently no-ops on native Wayland
windows. In order of preference morvox tries:

1. **`wtype`** — uses `zwp_virtual_keyboard_v1`. Works on
   Sway/Hyprland/KWin/river. Does **not** work on GNOME/Mutter (the
   protocol isn't implemented).
2. **`ydotool`** — uses `/dev/uinput` and works on every compositor,
   including GNOME, but requires the `ydotoold` daemon to be running and
   your user to have access to `/dev/uinput` (typically via the `input`
   group).
3. **`wl-copy` clipboard fallback** — copies the transcript to the
   clipboard and synthesises Ctrl+Shift+V via whichever of `wtype` /
   `ydotool` is available. If neither can inject keystrokes, the
   transcript is left on the clipboard and you paste manually.

Recommended on **GNOME Wayland (Ubuntu default)**:

```sh
sudo apt install ydotool wl-clipboard python3-tk
sudo systemctl enable --now ydotoold        # provides the daemon
sudo usermod -aG input "$USER"              # then log out/in
```

If you trigger morvox from a **GNOME custom shortcut**, prefer launching it
through a shell with stdout/stderr redirected so the desktop shortcut does not
keep the transcription process attached:

```sh
/bin/sh -lc 'morvox >/dev/null 2>/dev/null'
```

If you run from a checkout instead of an installed `morvox` on `$PATH`, replace
`morvox` with the full path to the repo launcher script.

If you don't want to set up `ydotoold`, install `wl-clipboard` only —
morvox will still copy the transcript to the clipboard and you can paste
with Ctrl+Shift+V.

### macOS

```sh
brew install ffmpeg python-tk
```

`osascript` ships with macOS, so no separate install for keystroke
injection. morvox auto-downloads its built-in model on first use and caches it under
`$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
English uses `ggml-base.en.bin`; non-English languages such as `morvox --lang es`
use `ggml-base.bin`. Custom `--model /path/to/ggml-base.en.bin` paths must already exist.

`pywhispercpp` currently publishes macOS wheels for Apple Silicon. On Intel
macs, `pip install morvox` may still need to build the dependency locally.

Optional but recommended for accurate multi-monitor placement and
pointer detection:

```sh
pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa
```

Without PyObjC the widget falls back to Tk's primary-screen size.

#### macOS permissions (first run will fail without them)

- **Microphone** — required for `ffmpeg` capture. Grant the controlling
  terminal (Terminal.app, iTerm2, ...) microphone access in
  **System Settings -> Privacy & Security -> Microphone**.
- **Accessibility** — required for `osascript` to send keystrokes and
  switch frontmost apps. Grant the same terminal access in
  **System Settings -> Privacy & Security -> Accessibility**.

If keystrokes silently do nothing or you see error `-1743` /
"not allowed to send keystrokes", Accessibility hasn't been granted.

#### Listing audio input devices on macOS

The `--source` flag takes an avfoundation index (e.g. `:0`, `:1`). To
list devices:

```sh
ffmpeg -f avfoundation -list_devices true -i ""
```

The default (`:0`) is usually the system default input.

### Windows 11

Install Python 3 and `ffmpeg`. The easiest package manager path is Scoop:

```powershell
scoop install python ffmpeg
```

If you do not use Scoop, install Python from python.org, install an
`ffmpeg` Windows build, then install morvox with `pip` or `pipx`.

morvox auto-downloads its built-in model on first use and caches it under
`$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
English uses `ggml-base.en.bin`; non-English languages such as `morvox --lang es`
use `ggml-base.bin`. Custom `--model C:\path\to\ggml-base.en.bin` paths must already exist.

#### Windows permissions

- **Microphone** — required for `ffmpeg` capture (WASAPI or DirectShow).
  Grant desktop apps microphone access in
  **Settings -> Privacy & security -> Microphone**.
- **Elevated/admin windows** — Windows blocks normal processes from typing
  into elevated apps. If the target app is running as administrator, run
  morvox from an elevated terminal too.
- **Focused-window typing** — on Windows 11, morvox types into whichever
  window is focused when transcription finishes. It tries several automatic
  paste methods first, then falls back to direct typing, and only leaves
  the transcript on the clipboard if all insertion methods are blocked.
  Detailed insertion traces are appended to `%LOCALAPPDATA%\morvox\whisper.log`.

#### Listing audio input devices on Windows

The `--source` flag takes a WASAPI or DirectShow device name. To list
devices:

```powershell
ffmpeg -list_devices true -f wasapi -i dummy
ffmpeg -list_devices true -f dshow -i dummy   # fallback if WASAPI unavailable
```

By default morvox auto-detects the available API and uses the first
audio capture device reported by the system.

You can also bypass the managed default cache and pass the model directly with
`--model /path/to/ggml-base.en.bin`. Custom model paths are not
auto-downloaded. The language flag is available as `--lang` or `--language`.
Use the same flags on both toggle presses; morvox does not persist them between
start and stop.

## Installation

```sh
python -m pip install morvox

# isolated install with managed PATH shims
pipx install morvox

# verify the CLI is installed and report its version
morvox --version
```

To install from a source checkout instead:

```sh
git clone https://github.com/morhook/morvox.git
cd morvox
python -m pip install .

# or run directly from the checkout
./morvox --version
```

## Hotkey configuration

morvox doesn't bind hotkeys itself; add a hotkey for your OS or desktop
environment.

If `morvox` works from your terminal but fails from a desktop hotkey, the
launcher is often using a different `PATH` or a different Python interpreter.
Depending on your Python setup (`asdf`, `pyenv`, `venv`, system Python, ...),
you may need to launch morvox with the same Python version/environment where
you installed it. In the terminal where morvox works, run `which python` or
`which python3` to see which interpreter/environment you should use for the
hotkey or helper script.

### Linux hotkey (i3)

Add to `~/.config/i3/config` (the script does **not** touch your config):

```
bindsym $mod+grave exec --no-startup-id morvox
```

Reload i3 (`$mod+Shift+r`) and press `$mod+\`` to start/stop dictation.

If you installed morvox under asdf and the bare `morvox` command is not on i3's
`PATH`, point the bind at the asdf shim Python and run morvox as a module:

```
bindsym $mod+grave exec --no-startup-id /home/youruser/.asdf/shims/python -m morvox
```

### Linux hotkey (GNOME)

For **Settings -> Keyboard -> Keyboard Shortcuts -> Custom Shortcuts**, use:

```sh
/bin/sh -lc 'morvox >/dev/null 2>/dev/null'
```

On GNOME Wayland this detached form avoids occasional transcription hangups when
launched from the desktop shortcut UI. If you run from a checkout instead of an
installed `morvox` on `$PATH`, replace `morvox` with the full path to the repo
launcher script.

If you installed morvox under asdf and the bare `morvox` command is not on the
shortcut's `PATH`, name the asdf shim Python explicitly and run morvox as a
module:

```sh
/bin/sh -lc '/home/youruser/.asdf/shims/python -m morvox >/dev/null 2>/dev/null'
```

### Linux hotkey (labwc / XFCE4 Wayland)

labwc is the wlroots compositor used by **XFCE4-on-Wayland**. It reads its
keybindings from `~/.config/xfce4/labwc/rc.xml` (the XFCE4 Wayland session) or
`~/.config/labwc/rc.xml` (standalone labwc). morvox does **not** touch this file.

Add `<keybind>` entries inside the `<keyboard>` block. The example below mirrors
a typical setup: toggle dictation, a Spanish variant, and a cancel binding.

```xml
<keybind key="W-bar">
  <action name="Execute" command="/home/youruser/.asdf/shims/python -m morvox" />
</keybind>
<keybind key="W-S-bar">
  <action name="Execute" command="/home/youruser/.asdf/shims/python -m morvox --lang=es" />
</keybind>
<keybind key="W-S-Escape">
  <action name="Execute" command="/home/youruser/.asdf/shims/python -m morvox --cancel" />
</keybind>
```

`W-bar` is Super+`|` (i.e. Super+Shift+backslash). After editing `rc.xml`,
reload labwc with `labwc -r` (or `kill -SIGHUP $(pidof labwc)`).

The example uses the **absolute** asdf shim path on purpose: labwc's `Execute`
runs commands with a minimal environment and does not expand `~`, so you must
name the same Python interpreter that installed morvox in full. Find yours with
`asdf which python`. If you installed morvox into the system Python or a venv
instead, substitute that interpreter's absolute path.

labwc is wlroots-based, so the `wtype` typing backend works out of the box; see
[Linux / Wayland](#linux--wayland) for the full `wtype` -> `ydotool` ->
`wl-copy` fallback chain and the packages it needs.

### Linux scripts in overall vs asdf vs venv etc
 
If you trigger morvox from any helper script, prefer the installed
`morvox` command from the same Python environment where you ran `pip install
morvox`. A plain command often works:

```sh
morvox
```

If the script does not inherit the same `PATH` as your shell, call the
interpreter you installed morvox into and run it as a module instead. Inspect
that interpreter first in the terminal where morvox already works.

With **asdf** (the most common case), ask asdf for the shim path and name it in
full:

```sh
asdf which python   # e.g. /home/youruser/.asdf/shims/python
# then use that path in your hotkey/script command, e.g.
/home/youruser/.asdf/shims/python -m morvox
```

For a non-asdf setup, `which python` / `which python3` reports the interpreter
to use:

```sh
which python3
# then paste that path into your hotkey command, e.g.
/full/path/to/python3 -m morvox
```

or, with a virtualenv:

```sh
/path/to/venv/bin/python -m morvox
```

If you are running from a checkout instead of an installed package, then use
the repo launcher path or the intended interpreter explicitly.

### macOS hotkey

Pair morvox with a hotkey daemon.

#### skhd

```sh
brew install skhd
brew services start skhd
```

Add to `~/.config/skhd/skhdrc`:

```
cmd - 0x32 : morvox
```

`0x32` is the backtick (`` ` ``) keycode. Reload skhd
(`skhd --reload`) and press `Cmd+\`` to toggle.

#### Hammerspoon

```lua
hs.hotkey.bind({"cmd"}, "`", function()
  hs.execute("/bin/sh -lc 'morvox'", true)
end)
```

### Windows hotkey

Pair morvox with a hotkey tool such as AutoHotkey v2.

```powershell
winget install --id AutoHotkey.AutoHotkey --source winget --exact
```

Example `morvox.ahk` using `Ctrl+Alt+``:

```ahk
#Requires AutoHotkey v2.0
#SingleInstance Force
#UseHook
^!sc029::
{
    target := WinGetID("A")
    KeyWait "sc029"
    KeyWait "Ctrl"
    KeyWait "Alt"
    EnvSet "MORVOX_TARGET_WINDOW", target
    Run 'morvox', , 'Hide'
}
```

Capturing `WinGetID("A")` before `Run` is harmless, but on Windows 11 morvox now
types into whichever window is focused when transcription finishes. `^!sc029`
binds Ctrl+Alt plus the physical grave key by scan code, avoiding AutoHotkey's
backtick-escape ambiguity. The `KeyWait` calls prevent held hotkey state from
leaking into morvox's later keystroke injection. Adjust the path to wherever you
installed morvox if it is not already on your `PATH`.

Avoid binding morvox to `Win+`` unless you have disabled or changed Windows
Terminal's global quake-mode shortcut (`Show/hide quake window`) in Windows
Terminal settings. Windows Terminal uses `Win+`` by default on many installs and
can hide the terminal window before or alongside AutoHotkey.
