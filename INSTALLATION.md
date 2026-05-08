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
- A whisper model, e.g. `<whisper-dir>/models/ggml-base.en.bin`

On Debian/Ubuntu, `tkinter` is in the `python3-tk` package; on Arch it
ships with `python`. If `tkinter` is missing, run with `--no-widget`
(morvox will print a one-time warning and continue without the widget).

If you use a third-party Python (asdf, pyenv, conda, ...) and the widget
never appears, check `/tmp/morvox/widget.log` — that interpreter is
probably built without `_tkinter`. Either install the system `python3-tk`
and use the system Python, or rebuild your managed Python with Tk
support.

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
discovers it there directly — no source build required. You still need
to supply a model: either pass `--model /path/to/ggml-base.en.bin` or
drop one under `~/.local/share/whisper.cpp/models/`.

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

### Pointing morvox at your whisper.cpp build

morvox locates the whisper.cpp directory (used to find the default
model) in this order:

1. `$MORVOX_WHISPER_DIR` if set
2. `~/.local/share/whisper.cpp` if it exists
3. On macOS: `/opt/homebrew/share/whisper.cpp`, then
   `/usr/local/share/whisper.cpp`
4. `~/soft/whisper.cpp` (legacy fallback)

The `whisper-cli` binary is resolved separately, in this order:

1. `$MORVOX_WHISPER_BIN` if set
2. `<whisper-dir>/build/bin/whisper-cli` if present
3. `<whisper-dir>/bin/whisper-cli` if present
4. `whisper-cli` on `$PATH` (e.g. via `brew install whisper-cpp`)

Set either explicitly in your shell rc if your build lives elsewhere:

```sh
export MORVOX_WHISPER_DIR="$HOME/code/whisper.cpp"
export MORVOX_WHISPER_BIN="$HOME/code/whisper.cpp/build/bin/whisper-cli"
```

You can also bypass the directory entirely and pass the model directly
with `--model /path/to/ggml-base.en.bin`.

## Installation

```sh
git clone https://github.com/morhook/morvox.git
cd morvox
chmod +x morvox

# optional: put it on your PATH
ln -s "$PWD/morvox" ~/.local/bin/morvox
```
