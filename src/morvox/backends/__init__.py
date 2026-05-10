"""morvox.backends — backend selection and singleton."""

import os
import sys

from .linux import LinuxX11Backend
from .macos import MacOSBackend
from .windows import WindowsBackend


def _make_backend():
    override = os.environ.get("MORVOX_BACKEND")
    if override == "x11":
        return LinuxX11Backend()
    if override == "macos":
        return MacOSBackend()
    if override in ("windows", "win32"):
        return WindowsBackend()
    if sys.platform == "darwin":
        return MacOSBackend()
    if sys.platform == "win32":
        return WindowsBackend()
    return LinuxX11Backend()


BACKEND = _make_backend()
