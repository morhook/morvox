"""morvox.constants — path resolution and runtime constants."""

import os
import sys

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


def _default_model_dir() -> str:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return os.path.join(os.path.expanduser(cache_home), "morvox", "models")
    return os.path.join(os.path.expanduser("~"), ".cache", "morvox", "models")


def default_model_for_language(language: str) -> str:
    normalized = (language or "en").strip().lower()
    name = DEFAULT_MODEL_MULTI_NAME if normalized != "en" else DEFAULT_MODEL_EN_NAME
    return os.path.join(DEFAULT_MODEL_DIR, name)


def default_model_url_for_language(language: str) -> str:
    normalized = (language or "en").strip().lower()
    return DEFAULT_MODEL_MULTI_URL if normalized != "en" else DEFAULT_MODEL_EN_URL

DEFAULT_MODEL_DIR = _default_model_dir()
DEFAULT_MODEL_EN_NAME = "ggml-base.en.bin"
DEFAULT_MODEL_MULTI_NAME = "ggml-base.bin"
DEFAULT_MODEL_EN_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
)
DEFAULT_MODEL_MULTI_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
)
DEFAULT_MODEL = default_model_for_language("en")
STATE_DIR = os.environ.get("MORVOX_STATE_DIR") or _default_state_dir()

# Widget audio/UI tuning.
LEVEL_SAMPLE_RATE = 16000
LEVEL_CHUNK_MS = 30           # how often to compute RMS
WIDGET_FPS = 30
WIDGET_W = 280
WIDGET_H = 60
WIDGET_RADIUS = 20            # corner radius for the rounded body
WIDGET_BOTTOM_OFFSET = 60     # px above screen bottom (clears i3bar)
WIDGET_PREVIEW_INTERVAL = 2.5
WIDGET_PREVIEW_WINDOW_SECONDS = 7
# How much already-transcribed audio to re-feed at the front of each preview
# pass so word boundaries survive the seam between non-overlapping windows.
WIDGET_PREVIEW_OVERLAP_SECONDS = 1.0
WIDGET_PREVIEW_MAX_LINES = 6
WIDGET_PREVIEW_PADDING = 12
WIDGET_PREVIEW_GAP = 8

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
