"""Processes of a case: keep every process that a case starts below its trusted worker, and kill them all.

On Linux, the trusted worker becomes a child subreaper. A process whose parent exits is then reparented to the
worker instead of the init process, so every process that the participant's code starts stays a descendant of the
worker, even one that moved into a new session or process group. When the case ends, every descendant of the
worker is killed. Elsewhere, both functions do nothing, and only the process group of the worker is stopped. Where
the kernel refuses to make the worker a subreaper, a process whose parent exits leaves the descendants of the worker,
so only the process group of the worker can still stop it.
"""

import contextlib
import ctypes
import os
import signal
import sys
import time
from pathlib import Path

_PR_SET_CHILD_SUBREAPER = 36
_KILL_DEADLINE_S = 5.0
_POLL_INTERVAL_S = 0.01


def become_subreaper() -> bool:
    """Make the current process a child subreaper on Linux; return whether it is one."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        return ctypes.CDLL(None, use_errno=True).prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except (OSError, AttributeError):
        return False


def _live_children() -> dict[int, list[int]]:
    """PIDs of the processes that have not exited, by the PID of their parent; empty without `/proc`."""
    children: dict[int, list[int]] = {}
    try:
        entries = [entry for entry in Path("/proc").iterdir() if entry.name.isdigit()]
    except OSError:
        return children
    for entry in entries:
        try:
            # The command name in parentheses may contain anything, so split after its last parenthesis.
            state, parent = (entry / "stat").read_bytes().rsplit(b")", 1)[1].split()[:2]
        except (OSError, IndexError, ValueError):  # gone meanwhile
            continue
        if state not in (b"Z", b"X"):
            children.setdefault(int(parent), []).append(int(entry.name))
    return children


def kill_descendants(pid: int) -> None:
    """Kill every descendant of process `pid` with `SIGKILL` until none is left running; nothing without `/proc`.

    `pid` must not reap its children meanwhile, because it is stopped or is the calling process, so that its
    children that were killed stay zombies and their PIDs cannot be reused. A descendant whose parent was killed is
    then reparented to `pid` if it is a subreaper, and killed in the next round. Gives up after a few seconds.
    """
    deadline = time.monotonic() + _KILL_DEADLINE_S
    while True:
        children = _live_children()
        found, pending = [], list(children.get(pid, ()))
        while pending:
            descendant = pending.pop()
            found.append(descendant)
            pending += children.get(descendant, ())
        if not found or time.monotonic() >= deadline:
            return
        # Parents first, so that a parent is being killed before its child exits and could be reaped by it.
        for descendant in found:
            with contextlib.suppress(ProcessLookupError):
                os.kill(descendant, signal.SIGKILL)
        time.sleep(_POLL_INTERVAL_S)
