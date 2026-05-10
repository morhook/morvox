"""morvox.commands — --status and --cancel sub-commands."""

import argparse

from .recording import stop_recorder
from .state import (
    cleanup_state,
    close_widget,
    is_recording,
    pid_alive,
    read_pid,
)


def cmd_status() -> int:
    print("recording" if is_recording() else "idle")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    pid = read_pid()
    if pid is None or not pid_alive(pid):
        cleanup_state()
        close_widget()
        print("not recording")
        return 0
    stop_recorder(pid)
    cleanup_state(keep_temp=args.keep_temp)
    close_widget()
    print("cancelled")
    return 0
