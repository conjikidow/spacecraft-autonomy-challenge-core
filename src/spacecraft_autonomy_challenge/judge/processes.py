"""Processes of a case: keep every process that a case starts below its trusted worker, and kill them all.

On Linux, the trusted worker becomes a child subreaper. A process whose parent exits is then reparented to the
worker instead of the init process, so every process that the participant's code starts stays a descendant of the
worker, even one that moved into a new session or process group. When the case ends, every descendant of the
worker is killed. Elsewhere, both functions do nothing, and only the process group of the worker is stopped. Where
the kernel refuses to make the worker a subreaper, a process whose parent exits leaves the descendants of the worker,
so only the process group of the worker can still stop it.
"""

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


def _stat(pid: int | str) -> tuple[bytes, int, bytes] | None:
    """State, parent PID, and start time of a process, from `/proc`; `None` if it is gone."""
    try:
        # The command name in parentheses may contain anything, so split after its last parenthesis.
        fields = Path(f"/proc/{pid}/stat").read_bytes().rsplit(b")", 1)[1].split()
        return fields[0], int(fields[1]), fields[19]
    except (OSError, IndexError, ValueError):
        return None


def _live_children() -> dict[int, list[tuple[int, bytes]]]:
    """PIDs and start times of the processes that have not exited, by the PID of their parent; empty without `/proc`."""
    children: dict[int, list[tuple[int, bytes]]] = {}
    try:
        entries = [entry.name for entry in Path("/proc").iterdir() if entry.name.isdigit()]
    except OSError:
        return children
    for entry in entries:
        stat = _stat(entry)
        if stat is not None and stat[0] not in (b"Z", b"X"):
            children.setdefault(stat[1], []).append((int(entry), stat[2]))
    return children


def _kill(pid: int, started: bytes) -> None:
    """Kill process `pid` with `SIGKILL` if it is still the process that started at `started`.

    The process is held by a pidfd while its start time is checked and while it is signalled, so that a PID that
    another process reuses is never signalled. Without pidfds, a PID reused right after the check could still be.
    """
    try:
        pidfd = os.pidfd_open(pid)
    except ProcessLookupError:
        return
    except (AttributeError, OSError):
        pidfd = None
    try:
        stat = _stat(pid)
        if stat is not None and stat[2] == started:
            if pidfd is None:
                os.kill(pid, signal.SIGKILL)
            else:
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        if pidfd is not None:
            os.close(pidfd)


def kill_descendants(pid: int) -> None:
    """Kill every descendant of process `pid` with `SIGKILL` until none is left running; nothing without `/proc`.

    Each descendant is identified by its PID and start time, so a process that exits and whose PID is reused
    meanwhile is not killed. A descendant whose parent was killed is reparented to `pid` if it is a subreaper, and
    killed in the next round. Gives up after a few seconds.
    """
    deadline = time.monotonic() + _KILL_DEADLINE_S
    while True:
        children = _live_children()
        found, pending = [], list(children.get(pid, ()))
        while pending:
            descendant = pending.pop()
            found.append(descendant)
            pending += children.get(descendant[0], ())
        if not found or time.monotonic() >= deadline:
            return
        for descendant, started in found:
            _kill(descendant, started)
        time.sleep(_POLL_INTERVAL_S)
