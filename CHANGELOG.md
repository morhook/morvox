# Changelog

All notable changes to this project will be documented in this file.

## [2.2.2] - 2026-06-08

### Fixed

- Fix duplicate text in the widget live preview by transcribing only newly-captured audio and de-duplicating the window seam, instead of re-transcribing and re-appending a sliding window.

### Documentation

- Add labwc/XFCE4 Wayland hotkey setup section and emphasize asdf shim Python in INSTALLATION.md / README.md.

## [2.2.1] - 2026-06-01

### Fixed

- Fix Hyprland multi-monitor widget placement by using XWayland/Xrandr coordinates for Tk windows while preserving Hyprland focused-monitor ordering.
- Avoid X11 Shape forced remap on Wayland so compositors do not recenter or hide the widget.

### Diagnostics

- Log selected monitor and widget geometry to `widget.log` for future placement debugging.

## [2.2.0] - 2026-06-01

### Added

- Support Hyprland widget placement by ordering Linux Wayland monitors from Hyprland's focused output metadata.

### Fixed

- Place the Linux Wayland widget on the focused wlroots output, including XFCE Wayland/labwc, using Wayland output metadata instead of X11 pointer coordinates.

## [2.1.2] - 2026-05-29

### Fixed

- Place the Linux widget on Sway's focused output instead of relying on XWayland monitor or pointer coordinates.

## [2.1.1] - 2026-05-24

### Fixed

- Prevent the Linux Wayland widget from keeping focus before transcript insertion, fixing automatic typing/paste on XFCE Wayland.

## [2.1.0] - 2026-05-24

### Added

- Support XFCE Wayland sessions by detecting Wayland before `xdotool getactivewindow` and using the current focused Wayland window for insertion.

## [2.0.0] - 2026-05-21

### Changed

- Replaced the external `whisper-cli` runtime dependency with the Python `pywhispercpp` package for both final transcription and live widget preview.
- Installation docs now point users at the packaged Python dependency instead of a separate whisper.cpp binary build.

## [1.4.0] - 2026-05-16

### Added

- Live widget transcription preview that runs during recording and grows upward above the VU meter.

### Changed

- The widget now keeps the last preview text visible while the final full-recording transcription runs.

## [1.3.2] - 2026-05-16

### Added

- `--version` CLI flag to print the morvox program version and exit.

## [1.3.1] - 2026-05-16

### Changed

- Documentation now recommends launching morvox from GNOME Wayland custom shortcuts via `/bin/sh -lc 'morvox >/dev/null 2>/dev/null'` to avoid occasional transcription hangups.
- Installation and troubleshooting docs now call out the detached launcher form for checkout-based runs as well.

## [1.3.0] - 2026-05-16

### Added

- GitHub Actions release workflow to build and publish distributions to PyPI on version tag pushes.

### Changed

- Releases now use PyPI Trusted Publishing via the repository's `pypi` GitHub environment.
- The release workflow now fails early if the pushed `v*` tag does not match the package version in `pyproject.toml`.

## [1.2.0] - 2026-05-16

### Added

- `--lang` as an alias for `--language`.
- Automatic multilingual built-in model download and selection for non-English languages such as `morvox --lang es`.

### Changed

- The managed default Whisper model now uses `ggml-base.en.bin` for English and `ggml-base.bin` for non-English languages.
- Documentation now covers the multilingual built-in model behavior and `--lang` usage.

## [1.1.0] - 2026-05-15

### Added

- Auto-download for the built-in `ggml-base.en.bin` whisper model when it is missing.
- Managed default model caching under `$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
- Download fallback to Python stdlib networking when `curl` is unavailable.

### Changed

- The built-in default model path is now morvox-managed instead of being derived from the whisper.cpp install directory.
- Custom `--model` paths remain manual and are not auto-downloaded.
