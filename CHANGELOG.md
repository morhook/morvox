# Changelog

All notable changes to this project will be documented in this file.

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
