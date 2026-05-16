# Changelog

All notable changes to this project will be documented in this file.

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
