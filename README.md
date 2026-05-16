# morvox

An awesome push-to-talk-style voice-to-text widget for everyone.

One command (`morvox`) that toggles:

1. **First press** → starts recording from the default mic, remembers the
   currently focused window/app, and shows a "Recording…" widget.
2. **Second press** → stops the recorder, transcribes the clip with
   `whisper-cli` (whisper.cpp), and types the transcription into your
   target app.

On first use, morvox auto-downloads its built-in base Whisper model if it is
missing: English uses `ggml-base.en.bin`, while non-English languages such as
`--lang es` use the multilingual `ggml-base.bin`.

> **Note:** Windows 11 has a built-in dictation tool — press `Win+H` to open it. macOS has System Dictation built in too, accessible via **System Settings → Keyboard → Dictation** (typically triggered by double-pressing `Fn`). morvox is an alternative: it runs a local [whisper.cpp](https://github.com/ggerganov/whisper.cpp) model entirely offline, gives you a visual VU-meter widget, and wires into any hotkey manager you already use.

morvox auto-selects a platform backend:

- **Linux** — uses `parecord` for capture and `xdotool` for window
  control + keystroke injection. We also support wayland. 
- **macOS** — uses `ffmpeg` (avfoundation) for capture and `osascript`
  (System Events) for window focus + keystrokes.
- **Windows 11** — uses `ffmpeg` (WASAPI) for capture and Win32 APIs for
  keystroke injection. On Windows, morvox inserts into the window that is
  focused when transcription finishes: it tries several automatic clipboard
  paste methods first, then direct Unicode typing, and only leaves the
  transcript on the clipboard if all insertion methods are blocked.

You can force a backend with `MORVOX_BACKEND=x11`, `MORVOX_BACKEND=macos`,
or `MORVOX_BACKEND=windows`.

## Table of Contents

- [Epistemology](#epistemology)
- [Screenshots](#screenshots)
- [What it does](#what-it-does)
- [Setup & installation](https://github.com/morhook/morvox/blob/main/INSTALLATION.md)
  - [Dependencies](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#dependencies)
  - [Installation](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#installation)
  - [Hotkey configuration](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#hotkey-configuration)
    - [Linux hotkey (i3)](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#linux-hotkey-i3)
    - [macOS hotkey](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#macos-hotkey)
      - [skhd](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#skhd)
      - [Hammerspoon](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#hammerspoon)
    - [Windows hotkey](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#windows-hotkey)
- [Usage](#usage)
- [The widget](#the-widget)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Epistemology

The name is based on morhook and voice. mor-vox. I know, if I explain the joke, it's not funny. Don't judge me.

## Screenshots

![capturing on a terminal](https://raw.githubusercontent.com/morhook/morvox/main/screenshot-terminal.png)
![capturing on vscode](https://raw.githubusercontent.com/morhook/morvox/main/screenshot-vscode.png)
![capturing on opencode](https://raw.githubusercontent.com/morhook/morvox/main/screenshot-opencode.png)
![morvox recording inside opencode](https://raw.githubusercontent.com/morhook/morvox/main/screenshot-opencode-chicago-95-xfce.png)

## What it does

- It wraps whisper-cli and shows a VU meter on the user interface. You need to add the hotkey configuration on your OS/Desktop Environment.
- The built-in default model is cached under `$XDG_CACHE_HOME/morvox/models/`
  or `~/.cache/morvox/models/` and is downloaded automatically on first use.
  `en` uses `ggml-base.en.bin`; other languages use `ggml-base.bin`.

## Setup & installation

Setup, dependencies, install steps, and hotkey configuration are in
[`INSTALLATION.md`](https://github.com/morhook/morvox/blob/main/INSTALLATION.md).

## Usage

```sh
# print the installed or checkout version
morvox --version

# toggle (start, then stop+transcribe+type)
morvox

# fallback if you prefer module execution
python -m morvox

# status (for i3blocks / polybar)
morvox --status        # prints "recording" or "idle"

# abort an in-flight recording without transcribing
morvox --cancel

# keep the wav/txt around for debugging
morvox --keep-temp

# use a different model / source / typing speed
morvox --model /path/to/ggml-tiny.en.bin
morvox --lang es
morvox --source alsa_input.usb-Maono_Maonocaster…
morvox --threads 8
morvox --type-delay 5

# disable the floating widget (headless / SSH / debugging)
morvox --no-widget
```

When you use toggle-time options such as `--lang es`, invoke `morvox` with the
same flags on both presses.

From a source checkout, you can still run `./morvox` before installing,
including `./morvox --version`.

If you use the built-in managed model, morvox downloads it on first use to
`$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
English uses `ggml-base.en.bin`; non-English languages such as `--lang es`
use `ggml-base.bin`. Custom `--model` paths are not auto-downloaded and must
already exist.

State files live in `$XDG_RUNTIME_DIR/morvox/` on Linux, falling back to
`/tmp/morvox-$UID/` when `$XDG_RUNTIME_DIR` is unset;
`~/Library/Caches/morvox/` on macOS; and `%LOCALAPPDATA%\morvox\` on
Windows. Override with the `MORVOX_STATE_DIR` env var:

- `rec.pid` — recorder PID
- `target_window` — saved focused window id
- `rec.wav` / `rec.txt` — audio + transcript
- `parecord.log` / `whisper.log` — diagnostic logs

By default these are deleted after a successful type. Pass `--keep-temp`
to keep them.

## The widget

While recording, morvox shows a small borderless window centred near the
bottom of the screen. It contains:

- a pulsing red dot (recording indicator),
- a live VU meter that reacts to your microphone level,
- an elapsed-time counter.

When you stop recording, the meter is replaced by a "Transcribing…"
spinner that stays visible until whisper finishes and the transcript has
been typed. If whisper produced only silence the widget briefly shows
"No speech detected" instead.

The widget is a self-spawned subprocess of `morvox` (uses Python's
stdlib `tkinter`). Its stderr is written to the platform state dir's
`widget.log` for debugging. On Linux/X11 it uses
`_NET_WM_WINDOW_TYPE_DOCK` so i3 won't try to tile it. On Wayland-only
sessions without XWayland, or on hosts without `$DISPLAY`, the widget is
skipped silently.

To disable the widget entirely (e.g. on a headless machine or over SSH),
pass `--no-widget`.

## Troubleshooting

- **No audio recorded / empty wav (Linux)**
  Check the active sources: `pactl list short sources`. Pass an explicit
  source with `--source <NAME>`. Inspect
  `$XDG_RUNTIME_DIR/morvox/parecord.log` or `/tmp/morvox-$UID/parecord.log`.

- **No audio recorded / empty wav (macOS)**
  List devices with `ffmpeg -f avfoundation -list_devices true -i ""`
  and pass an explicit `--source :<idx>`. Inspect
  `~/Library/Caches/morvox/parecord.log`. If ffmpeg complains about
  permissions, grant the terminal Microphone access.

- **No audio recorded / empty wav (Windows)**
  List audio devices with `ffmpeg -list_devices true -f wasapi -i dummy`
  (or `ffmpeg -list_devices true -f dshow -i dummy` if your ffmpeg build
  lacks WASAPI) and pass an explicit `--source "<device name>"`. Inspect
  `%LOCALAPPDATA%\morvox\parecord.log`. If ffmpeg cannot access the
  microphone, check **Settings -> Privacy & security -> Microphone**.

- **Text typed into wrong window**
  On Linux and macOS, the originally focused window/app may have been
  destroyed before you stopped recording. morvox falls back to typing
  into whatever is currently focused and prints a warning to stderr. On
  Windows, morvox intentionally types into the window that is focused
  when transcription finishes.

- **Linux Wayland: nothing is typed (GNOME/Ubuntu)**
  GNOME/Mutter doesn't implement the `wtype` keyboard protocol and
  `xdotool` is a no-op against native Wayland windows. Either set up
  `ydotoold` (`sudo systemctl enable --now ydotoold` and add your user
  to the `input` group), or install `wl-clipboard` so the transcript
  lands on your clipboard for manual Ctrl+Shift+V. If you launch morvox
  from a GNOME custom shortcut, prefer `/bin/sh -lc 'morvox >/dev/null
  2>/dev/null'` to avoid occasional transcription hangups; replace
  `morvox` with your checkout path if needed. See
  [`INSTALLATION.md` (Linux / Wayland)](https://github.com/morhook/morvox/blob/main/INSTALLATION.md#linux--wayland).

- **Linux: widget never appears (asdf/pyenv/conda Python)**
  The widget runs as a Python subprocess and needs `tkinter`. Many
  third-party Python builds ship without it. Check
  `$XDG_RUNTIME_DIR/morvox/widget.log` or `/tmp/morvox-$UID/widget.log` for
  `No module named 'tkinter'`. Install `python3-tk` and run morvox under the
  system Python, rebuild your managed Python with Tk support, or use
  `--no-widget` to silence the warning.

- **macOS: keystrokes silently do nothing**
  Accessibility permission isn't granted. **System Settings → Privacy &
  Security → Accessibility** → enable your terminal app.

- **Windows: text does not type into an elevated app**
  Windows blocks lower-integrity processes from injecting keystrokes into
  elevated/admin windows. Run morvox from an elevated terminal too, or type
  into a non-elevated app.

- **Windows: transcript only appears on the clipboard**
  On Windows 11, morvox first tries several automatic paste methods into the
  currently focused window and then falls back to direct typing. If all of
  those are blocked by the app or OS policy, morvox leaves the transcript on
  the clipboard so you can paste it manually. Inspect
  `%LOCALAPPDATA%\morvox\whisper.log` for a `windows-insert:` trace showing
  which insertion path ran and what failed.

- **Whisper too slow**
  Use a smaller model — `ggml-tiny.en.bin` is roughly 5× faster than
  `base.en` with a small accuracy hit. Increase `--threads` up to your
  physical core count.

- **Default model keeps re-downloading unexpectedly**
  The built-in model cache lives under `$XDG_CACHE_HOME/morvox/models/` or
  `~/.cache/morvox/models/`. If your environment sets `XDG_CACHE_HOME` to a
  temporary location, point it at a persistent cache directory.

- **Nothing is typed and notification says "Empty recording"**
  Whisper produced only a noise token (e.g. `[BLANK_AUDIO]`). Speak
  closer to the mic or check input gain.

## License

MIT — see [LICENSE](https://github.com/morhook/morvox/blob/main/LICENSE).
