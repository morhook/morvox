"""morvox.constants — path resolution and compile-time constants."""

import os
import shutil
import sys


def _resolve_whisper_dir() -> str:
    """Locate the whisper.cpp install directory.

    Resolution order:
      1. $MORVOX_WHISPER_DIR (if set)
      2. ~/.local/share/whisper.cpp (if it exists)
      3. On macOS: Homebrew prefixes (/opt/homebrew/share, /usr/local/share)
      4. On Windows: %LOCALAPPDATA%\\whisper.cpp if it exists
      5. ~/soft/whisper.cpp (legacy fallback)
    """
    env = os.environ.get("MORVOX_WHISPER_DIR")
    if env:
        return os.path.expanduser(env)
    home = os.path.expanduser("~")
    primary = os.path.join(home, ".local", "share", "whisper.cpp")
    if os.path.isdir(primary):
        return primary
    if sys.platform == "darwin":
        for cand in ("/opt/homebrew/share/whisper.cpp",
                     "/usr/local/share/whisper.cpp"):
            if os.path.isdir(cand):
                return cand
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            primary_win = os.path.join(local, "whisper.cpp")
            if os.path.isdir(primary_win):
                return primary_win
    return os.path.join(home, "soft", "whisper.cpp")


def _resolve_whisper_bin(whisper_dir: str) -> str:
    """Locate the whisper-cli binary.

    Resolution order:
      1. $MORVOX_WHISPER_BIN (if set, trusted as-is after expanduser)
      2. <whisper_dir>/build/bin/whisper-cli (if present and executable)
      3. <whisper_dir>/bin/whisper-cli (if present and executable)
      4. On Windows: Release/Debug .exe build locations
      5. shutil.which("whisper-cli") (e.g. Homebrew install on $PATH)
      6. Legacy fallback: <whisper_dir>/build/bin/whisper-cli (so the
         existing diagnostic still points at a meaningful path).
    """
    env = os.environ.get("MORVOX_WHISPER_BIN")
    if env:
        return os.path.expanduser(env)
    names = ["whisper-cli.exe"] if sys.platform == "win32" else ["whisper-cli"]
    candidates = []
    for name in names:
        candidates.extend([
            os.path.join(whisper_dir, "build", "bin", name),
            os.path.join(whisper_dir, "bin", name),
        ])
        if sys.platform == "win32":
            candidates.extend([
                os.path.join(whisper_dir, "build", "bin", "Release", name),
                os.path.join(whisper_dir, "build", "bin", "Debug", name),
                os.path.join(whisper_dir, "build", "src", "Release", name),
            ])
    for cand in candidates:
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    on_path = shutil.which("whisper-cli.exe") if sys.platform == "win32" else None
    if on_path is None:
        on_path = shutil.which("whisper-cli")
    if on_path is not None:
        return on_path
    suffix = "whisper-cli.exe" if sys.platform == "win32" else "whisper-cli"
    return os.path.join(whisper_dir, "build", "bin", suffix)


def _default_state_dir() -> str:
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/morvox")
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
        if base:
            return os.path.join(base, "morvox")
        return os.path.expanduser("~/AppData/Local/morvox")
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        return os.path.join(runtime_dir, "morvox")
    uid = str(os.getuid()) if hasattr(os, "getuid") else "unknown"
    return os.path.join("/tmp", f"morvox-{uid}")


WHISPER_DIR = _resolve_whisper_dir()
WHISPER_BIN = _resolve_whisper_bin(WHISPER_DIR)
DEFAULT_MODEL = os.path.join(WHISPER_DIR, "models", "ggml-base.en.bin")
STATE_DIR = os.environ.get("MORVOX_STATE_DIR") or _default_state_dir()

# Widget audio/UI tuning.
LEVEL_SAMPLE_RATE = 16000
LEVEL_CHUNK_MS = 30           # how often to compute RMS
WIDGET_FPS = 30
WIDGET_W = 280
WIDGET_H = 60
WIDGET_RADIUS = 20            # corner radius for the rounded body
WIDGET_BOTTOM_OFFSET = 60     # px above screen bottom (clears i3bar)

# Noise tokens whisper sometimes outputs for empty/silent input.
_NOISE_TOKENS = {
    "[blank_audio]",
    "[ silence ]",
    "(silence)",
    "[silence]",
    "[music]",
    "[ music ]",
    "(baby crying)",
    "[baby crying]",
    "(baby cooing)",
    "(barking)",
    "[barking]",
    "(crying)",
    "[crying]",
}

APP_NAME = "morvox"
