# Changelog

All notable changes to this project will be documented in this file.

## [1.1.0] - 2026-05-15

### Added

- Auto-download for the built-in `ggml-base.en.bin` whisper model when it is missing.
- Managed default model caching under `$XDG_CACHE_HOME/morvox/models/` or `~/.cache/morvox/models/`.
- Download fallback to Python stdlib networking when `curl` is unavailable.

### Changed

- The built-in default model path is now morvox-managed instead of being derived from the whisper.cpp install directory.
- Custom `--model` paths remain manual and are not auto-downloaded.
