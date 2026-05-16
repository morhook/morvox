"""morvox.__main__ — argparse wiring, CLI dispatch, and entry-point main()."""

import argparse
import os
import sys

from . import __version__
from .constants import DEFAULT_MODEL
from .state import _state, is_recording, read_pid, _pid_file
from .commands import cmd_cancel, cmd_status
from .recording import cmd_recorder, cmd_start, cmd_stop
from .widget import cmd_widget


def build_parser() -> argparse.ArgumentParser:
    default_threads = max(1, (os.cpu_count() or 2) // 2)
    p = argparse.ArgumentParser(
        prog="morvox",
        description=(
            "Toggle audio capture and transcribe with whisper.cpp, then type the "
            "transcription into a backend-selected target window."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help=("Path to whisper.cpp ggml model "
                         f"(default managed cache: {DEFAULT_MODEL})"))
    p.add_argument("--lang", "--language", dest="language", default="en",
                   help="Whisper language code (default: en)")
    p.add_argument("--threads", type=int, default=default_threads,
                   help=f"Whisper thread count (default: {default_threads})")
    p.add_argument("--source", default=None,
                   help="Audio source/device name (default: system default)")
    p.add_argument("--type-delay", type=int, default=1,
                   help="Delay between typed characters in ms (default: 1)")
    p.add_argument("--keep-temp", action="store_true",
                   help="Keep temporary files after typing (default: delete)")
    p.add_argument("--no-widget", action="store_true",
                   help="Disable the live recording widget (headless mode)")
    p.add_argument("--target-window", default=None, metavar="HANDLE",
                   help=("Use a pre-captured target window handle "
                         "(useful for hotkey launchers that steal focus)"))

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true",
                      help="Print 'recording' or 'idle' and exit")
    mode.add_argument("--cancel", action="store_true",
                      help="Cancel any active recording without transcribing/typing")
    # Internal entry point used when morvox spawns its own GUI subprocess.
    mode.add_argument("--widget", action="store_true",
                      help=argparse.SUPPRESS)
    mode.add_argument("--recorder", action="store_true",
                      help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = argv if argv is not None else sys.argv[1:]
    args = parser.parse_args(raw_argv)
    args.model_explicit = any(arg == "--model" or arg.startswith("--model=") for arg in raw_argv)

    # Ensure state dir exists for any sub-action.
    _state()

    if args.widget:
        return cmd_widget()
    if args.recorder:
        return cmd_recorder(args)
    if args.status:
        return cmd_status()
    if args.cancel:
        return cmd_cancel(args)

    # Toggle behavior.
    if is_recording():
        return cmd_stop(args)
    else:
        # Clean any stale leftovers from a previous failed run before starting.
        if read_pid() is not None and not is_recording():
            _pid_file().unlink(missing_ok=True)
        return cmd_start(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
