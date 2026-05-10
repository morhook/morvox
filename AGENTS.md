# AGENTS.md

## What this repo is
Single-file Python 3 CLI: `./morvox` (no extension, stdlib only). No
package manifest, no virtualenv, no tests, no lint/format/CI config.
"Install" = `chmod +x morvox` and symlink onto `$PATH`.

User-facing docs: `README.md`, `INSTALLATION.md`. Treat code as the
source of truth when they conflict.

## Editing the script
- The entire program is `morvox` (~1700 lines). Edit it as Python 3.
- Two platform backends live side by side: `LinuxX11Backend`
  (`morvox:261`) and `MacOSBackend` (`morvox:530`). Selected via
  `$MORVOX_BACKEND` (`x11`|`macos`) or auto-detected by `_make_backend`
  (`morvox:691`). Any change to capture / window focus / typing must
  be applied to both, plus the Linux-Wayland fallback chain inside the
  X11 backend (`wtype` -> `ydotool` -> `wl-copy` clipboard with
  Ctrl+Shift+V).
- `--widget` is a hidden internal flag (`argparse.SUPPRESS`,
  `morvox:1683`). morvox re-execs itself with it to spawn the Tk
  widget subprocess. Do not delete the branch in `main()` or
  `cmd_widget` (`morvox:1271`).
- Whisper paths resolve via `_resolve_whisper_dir` /
  `_resolve_whisper_bin` (`morvox:21`, `morvox:45`) using
  `$MORVOX_WHISPER_DIR`, `$MORVOX_WHISPER_BIN`,
  `~/.local/share/whisper.cpp`, Homebrew prefixes, then
  `~/soft/whisper.cpp` (legacy). Don't hardcode paths.
- State dir is platform-specific: `$XDG_RUNTIME_DIR/morvox` on Linux,
  falling back to `/tmp/morvox-$UID`; `~/Library/Caches/morvox` on macOS.
  Honor `$MORVOX_STATE_DIR`.
  Toggle state lives in `rec.pid`; stale PIDs are auto-reaped
  (`is_recording`, `morvox:240`).

## Verifying changes
There is no test suite. Default checks:
- Syntax: `python3 -c "import ast; ast.parse(open('morvox').read())"`
- CLI wiring: `./morvox --help`

You can run `./morvox` in an agent session to "smoke test" — it
toggles recording, opens the mic, and types into whatever window is
focused, but that's not something we will mind. It's better than 
start making the user test and never end. Use `./morvox --status` 
and `./morvox --cancel` to probe state safely. For deeper debugging, 
run with `--keep-temp` and read the logs in the state dir 
(`parecord.log`, `whisper.log`, `widget.log`).

## Conventions
- Stdlib only. Match surrounding style and existing type-hint usage;
  don't introduce a formatter (black/ruff/isort) or reflow the file.
- Optional `pyobjc-framework-Quartz` / `pyobjc-framework-Cocoa` are
  detected lazily on macOS for multi-monitor widget placement; never
  make them hard dependencies.
- Keep the script a single self-contained `#!/usr/bin/env python3`
  executable — no package layout, no `__init__.py`, no extra modules.
- `.gitignore` only excludes `__pycache__`. Don't commit state-dir
  artefacts or replacement screenshots without intent.
