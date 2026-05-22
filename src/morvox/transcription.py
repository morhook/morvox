"""morvox.transcription — shared pywhispercpp helpers."""

from pathlib import Path


_PREVIEW_MODELS: dict[tuple[str, str, int], object] = {}


def _import_backend():
    try:
        import numpy as np
        from pywhispercpp.model import Model
        from pywhispercpp.utils import redirect_stderr
    except ImportError as e:
        raise RuntimeError(
            "pywhispercpp is not installed. Reinstall morvox so its Python "
            "dependencies are available."
        ) from e
    return np, Model, redirect_stderr


def _normalize_language(language: str) -> str:
    return (language or "en").strip() or "en"


def _new_model(model_path: str,
               language: str,
               threads: int):
    _, Model, _ = _import_backend()
    return Model(
        str(Path(model_path).expanduser()),
        n_threads=max(1, threads),
        language=_normalize_language(language),
        no_context=True,
        print_progress=False,
        print_realtime=False,
        print_timestamps=False,
        redirect_whispercpp_logs_to=False,
    )


def _segments_to_text(segments) -> str:
    parts = []
    for segment in segments:
        text = getattr(segment, "text", "")
        if text:
            parts.append(text)
    return "\n".join(parts)


def transcribe_file(media_path: str,
                    model_path: str,
                    language: str,
                    threads: int,
                    log_path: str | Path | None = None) -> str:
    _, _, redirect_stderr = _import_backend()
    target = str(log_path) if log_path is not None else None
    with redirect_stderr(target):
        model = _new_model(model_path, language, threads)
        segments = model.transcribe(str(media_path))
    return _segments_to_text(segments)


def transcribe_pcm_data(pcm_data: bytes,
                        model_path: str,
                        language: str,
                        threads: int) -> str:
    np, _, redirect_stderr = _import_backend()
    if not pcm_data:
        return ""

    key = (str(Path(model_path).expanduser()), _normalize_language(language), max(1, threads))
    model = _PREVIEW_MODELS.get(key)
    if model is None:
        with redirect_stderr(None):
            model = _new_model(key[0], key[1], key[2])
        _PREVIEW_MODELS[key] = model

    audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)
    if audio.size == 0:
        return ""
    audio /= 32768.0

    with redirect_stderr(None):
        segments = model.transcribe(audio)
    return _segments_to_text(segments)
