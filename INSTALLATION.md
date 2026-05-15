# Setup & installation

## Dependencies

### Linux / X11

- Python 3 (standard library only, including `tkinter` for the widget)
- `xdotool`
- `pulseaudio-utils` (provides `parecord` and `parec`) — works fine with
  PipeWire's pulse shim
- A `whisper-cli` binary from [whisper.cpp](https://github.com/ggerganov/whisper.cpp).
  morvox finds it at, in order: `$MORVOX_WHISPER_BIN`,
  `<whisper-dir>/build/bin/whisper-cli`, `<whisper-dir>/bin/whisper-cli`, or
  anywhere on `$PATH` (e.g. `brew install whisper-cpp`).

morvox auto-downloads its built-in `ggml-base.en.bin` model on first use and
caches it under `$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
If you pass a custom `--model`, that file must already exist.

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

If you don't want to set up `ydotoold`, install `wl-clipboard` only —
morvox will still copy the transcript to the clipboard and you can paste
with Ctrl+Shift+V.

### macOS

```sh
brew install ffmpeg whisper-cpp python-tk
```

`osascript` ships with macOS, so no separate install for keystroke
injection. `whisper-cpp` from Homebrew installs the `whisper-cli`
binary on `$PATH` (e.g. `/opt/homebrew/bin/whisper-cli`); morvox
discovers it there directly — no source build required. morvox
auto-downloads its built-in `ggml-base.en.bin` model on first use and caches
it under `$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
Custom `--model /path/to/ggml-base.en.bin` paths must already exist.

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

Install Python 3, `ffmpeg`, and `whisper-cli.exe`. The easiest package
manager path is Scoop:

```powershell
scoop install python ffmpeg whisper-cpp
```

If you do not use Scoop, install Python from python.org, install an
`ffmpeg` Windows build, and either put `whisper-cli.exe` on `%PATH%` or
set `%MORVOX_WHISPER_BIN%` to its full path.

morvox auto-downloads its built-in `ggml-base.en.bin` model on first use and
caches it under `$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
Custom `--model C:\path\to\ggml-base.en.bin` paths must already exist.

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

### Pointing morvox at your whisper.cpp build

morvox locates the whisper.cpp directory (used to find `whisper-cli`) in this
order:

1. `$MORVOX_WHISPER_DIR` if set
2. `~/.local/share/whisper.cpp` if it exists
3. On macOS: `/opt/homebrew/share/whisper.cpp`, then
   `/usr/local/share/whisper.cpp`
4. On Windows: `%LOCALAPPDATA%\whisper.cpp` if it exists
5. `~/soft/whisper.cpp` (legacy fallback)

The `whisper-cli` binary is resolved separately, in this order:

1. `$MORVOX_WHISPER_BIN` if set
2. `<whisper-dir>/build/bin/whisper-cli` if present
3. `<whisper-dir>/bin/whisper-cli` if present
4. On Windows: common CMake `.exe` locations such as
   `<whisper-dir>\build\bin\Release\whisper-cli.exe`
5. `whisper-cli` / `whisper-cli.exe` on `$PATH` (e.g. via
   `brew install whisper-cpp` or `scoop install whisper-cpp`)

Set either explicitly in your shell rc if your build lives elsewhere:

```sh
export MORVOX_WHISPER_DIR="$HOME/code/whisper.cpp"
export MORVOX_WHISPER_BIN="$HOME/code/whisper.cpp/build/bin/whisper-cli"
```

PowerShell equivalent:

```powershell
$env:MORVOX_WHISPER_DIR = "$env:LOCALAPPDATA\whisper.cpp"
$env:MORVOX_WHISPER_BIN = "$env:LOCALAPPDATA\whisper.cpp\build\bin\Release\whisper-cli.exe"
```

You can also bypass the managed default cache and pass the model directly with
`--model /path/to/ggml-base.en.bin`. Custom model paths are not
auto-downloaded.

## Installation

```sh
python -m pip install morvox

# isolated install with managed PATH shims
pipx install morvox
```

To install from a source checkout instead:

```sh
git clone https://github.com/morhook/morvox.git
cd morvox
python -m pip install .
```

## Hotkey configuration

morvox doesn't bind hotkeys itself; add a hotkey for your OS or desktop
environment.

### Linux hotkey (i3)

Add to `~/.config/i3/config` (the script does **not** touch your config):

```
bindsym $mod+grave exec --no-startup-id morvox
```

Reload i3 (`$mod+Shift+r`) and press `$mod+\`` to start/stop dictation.

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
