# AGENTS.md

## What this repo is
Python 3 CLI packaged as `src/morvox/` with a thin `./morvox` entry-point
launcher (no extension). Stdlib only (aside from platform-specific optional
deps). No package manifest, no virtualenv, no tests, no lint/format/CI config.
"Install" = `chmod +x morvox` and symlink onto `$PATH`.

User-facing docs: `README.md`, `INSTALLATION.md`. Treat code as the
source of truth when they conflict.

## Editing the script

### Module layout

```
morvox                    ← thin shebang launcher (adds src/ to sys.path)
src/morvox/
  __init__.py
  __main__.py             ← build_parser(), main(), __main__ guard
  constants.py            ← _resolve_whisper_dir/bin, _default_state_dir, constants
  state.py                ← state-dir helpers, process/widget coordination
  widget.py               ← spawn_widget(), cmd_widget(), _apply_rounded_shape()
  recording.py            ← cmd_start(), cmd_stop(), cmd_recorder(), finalize_recording()
  commands.py             ← cmd_status(), cmd_cancel()
  backends/
    __init__.py           ← _make_backend(), BACKEND singleton
    linux.py              ← LinuxX11Backend
    macos.py              ← MacOSBackend
    windows.py            ← WindowsBackend
```

### Key pointers
- Two platform backends live side by side: `LinuxX11Backend`
  (`src/morvox/backends/linux.py`) and `MacOSBackend`
  (`src/morvox/backends/macos.py`). Selected via `$MORVOX_BACKEND`
  (`x11`|`macos`) or auto-detected by `_make_backend`
  (`src/morvox/backends/__init__.py`). Any change to capture / window
  focus / typing must be applied to both, plus the Linux-Wayland fallback
  chain inside the X11 backend (`wtype` -> `ydotool` -> `wl-copy`
  clipboard with Ctrl+Shift+V).
- `--widget` is a hidden internal flag (`argparse.SUPPRESS`,
  `src/morvox/__main__.py`). morvox re-execs itself with it to spawn the
  Tk widget subprocess. Do not delete the branch in `main()` or `cmd_widget`.
- Whisper paths resolve via `_resolve_whisper_dir` /
  `_resolve_whisper_bin` (`src/morvox/constants.py`) using
  `$MORVOX_WHISPER_DIR`, `$MORVOX_WHISPER_BIN`,
  `~/.local/share/whisper.cpp`, Homebrew prefixes, then
  `~/soft/whisper.cpp` (legacy). Don't hardcode paths.
- State dir is platform-specific: `$XDG_RUNTIME_DIR/morvox` on Linux,
  falling back to `/tmp/morvox-$UID`; `~/Library/Caches/morvox` on macOS.
  Honor `$MORVOX_STATE_DIR`.
  Toggle state lives in `rec.pid`; stale PIDs are auto-reaped
  (`is_recording`, `src/morvox/state.py`).

### Import rules
- `backends/linux.py` and `backends/macos.py` import from `state` lazily
  to avoid circular imports (since `state` imports `BACKEND` lazily from
  `backends`).
- `backends/windows.py` similarly imports `state` helpers and `constants`
  inside function bodies.
- `widget.py` imports `BACKEND` lazily inside function bodies.
- Backend-specific code that needs `_apply_rounded_shape` (X11 Shape mask)
  imports it from `widget` inside the method body.
- `recording.py` imports `spawn_widget` from `widget` at module level
  (safe because `widget` imports `BACKEND` lazily).

## Verifying changes
There is no test suite. Default checks:
- Syntax: `python3 -c "import ast; ast.parse(open('morvox').read())"`
- All modules: `for f in $(find src/morvox -name '*.py'); do python3 -c "import ast; ast.parse(open('$f').read())"; done`
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
- No package manifest, no `setup.py`, no `pyproject.toml`. The thin
  `morvox` launcher at the repo root adds `src/` to `sys.path` at
  runtime.
- Backend imports from `state`/`widget`/`constants` use lazy (function-
  body) imports to avoid circular dependency chains.
- `.gitignore` only excludes `__pycache__`. Don't commit state-dir
  artefacts or replacement screenshots without intent.
