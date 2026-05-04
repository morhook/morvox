# morvox

A tiny push-to-talk-style voice-to-text widget for i3/X11.

One command (`morvox`) that toggles:

1. **First press** → starts recording from the default mic with `parecord`,
   remembers the currently focused window, and shows a "Recording…"
   notification.
2. **Second press** → stops the recorder, transcribes the clip with
   `whisper-cli` (whisper.cpp), re-focuses the original window, and types
   the transcription via `xdotool type`.

## What it does

- Records 16 kHz mono WAV (whisper.cpp's native input) via `parecord`.
- Saves the focused window id at start so the transcript ends up in the
  same window even if focus has changed by the time you stop.
- Cleans whisper output: collapses newlines/whitespace into single spaces
  so multi-sentence dictation is typed inline.
- Filters common whisper "noise" tokens (`[BLANK_AUDIO]`, `[silence]`,
  `[Music]`, …) and shows an "Empty recording" notification instead of
  typing them.
- Stale-lock safe: a leftover PID file whose process is dead is treated
  as "not recording".

## Dependencies

Required:

- Python 3 (standard library only)
- `xdotool`
- `pulseaudio-utils` (provides `parecord`) — works fine with PipeWire's
  pulse shim
- A built [whisper.cpp](https://github.com/ggerganov/whisper.cpp) — the
  `whisper-cli` binary at `<whisper-dir>/build/bin/whisper-cli`
- A whisper model, e.g. `<whisper-dir>/models/ggml-base.en.bin`

Optional:

- `libnotify-bin` (provides `notify-send`) — used for desktop
  notifications; the script silently skips them if missing.

### Pointing morvox at your whisper.cpp build

morvox locates whisper.cpp in this order:

1. `$MORVOX_WHISPER_DIR` if set
2. `~/.local/share/whisper.cpp` if it exists
3. `~/soft/whisper.cpp` (legacy fallback)

Set it explicitly in your shell rc if your build lives elsewhere:

```sh
export MORVOX_WHISPER_DIR="$HOME/code/whisper.cpp"
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

## Usage

```sh
# toggle (start, then stop+transcribe+type)
./morvox

# status (for i3blocks / polybar)
./morvox --status        # prints "recording" or "idle"

# abort an in-flight recording without transcribing
./morvox --cancel

# keep the wav/txt around for debugging
./morvox --keep-temp

# use a different model / source / typing speed
./morvox --model /path/to/ggml-tiny.en.bin
./morvox --source alsa_input.usb-Maono_Maonocaster…
./morvox --threads 8
./morvox --type-delay 5
```

State files live in `/tmp/morvox/` (override with the
`MORVOX_STATE_DIR` env var):

- `rec.pid` — recorder PID
- `target_window` — saved focused window id
- `rec.wav` / `rec.txt` — audio + transcript
- `parecord.log` / `whisper.log` — diagnostic logs

By default these are deleted after a successful type. Pass `--keep-temp`
to keep them.

## i3 keybinding

Add to `~/.config/i3/config` (the script does **not** touch your config);
adjust the path to wherever you installed `morvox`:

```
bindsym $mod+grave exec --no-startup-id ~/.local/bin/morvox
```

Reload i3 (`$mod+Shift+r`) and press `$mod+\`` to start/stop dictation.

## Troubleshooting

- **No audio recorded / empty wav**
  Check the active sources: `pactl list short sources`. Pass an explicit
  source with `--source <NAME>`. Inspect `/tmp/morvox/parecord.log`.

- **Text typed into wrong window**
  The originally focused window may have been destroyed before you
  stopped recording. The script falls back to typing into whatever is
  currently focused and prints a warning to stderr.

- **Whisper too slow**
  Use a smaller model — `ggml-tiny.en.bin` is roughly 5× faster than
  `base.en` with a small accuracy hit. Increase `--threads` up to your
  physical core count.

- **Nothing is typed and notification says "Empty recording"**
  Whisper produced only a noise token (e.g. `[BLANK_AUDIO]`). Speak
  closer to the mic or check input gain.

- **Notifications missing**
  Install `libnotify-bin` (Debian/Ubuntu) or `libnotify` (Arch). The
  script works fine without it; you just lose the popups.

## License

MIT — see [LICENSE](LICENSE).
