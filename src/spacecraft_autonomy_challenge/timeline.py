"""Timeline of scheduled commands, ordered by execution time and then by registration order.

See `docs/timeline.md` for the command semantics.
"""

import math
from bisect import insort
from dataclasses import dataclass
from typing import NewType

from spacecraft_autonomy_challenge.commands import Command, CommandError

CommandId = NewType("CommandId", int)
"""Identifier of a scheduled command, unique within a run and assigned sequentially from 1."""


@dataclass(frozen=True, slots=True)
class ScheduledCommand:
    """A command registered on the timeline for execution at `time_s`."""

    command_id: CommandId
    time_s: float
    command: Command


def _execution_order(scheduled: ScheduledCommand) -> tuple[float, int]:
    return (scheduled.time_s, scheduled.command_id)


class Timeline:
    """Pending commands ordered by execution time, then by registration order."""

    def __init__(self) -> None:
        self._pending: list[ScheduledCommand] = []
        self._next_id = 1

    def schedule(self, time_s: float, command: Command, *, now_s: float) -> CommandId:
        """Register `command` for `time_s`, which must be finite and not earlier than `now_s`."""
        if not isinstance(command, Command):
            raise CommandError(f"not a command: {command!r}")
        time_s = _as_time(time_s)
        if time_s < now_s:
            raise CommandError(f"cannot schedule a command in the past: {time_s} s < now {now_s} s")
        command_id = CommandId(self._next_id)
        self._next_id += 1
        insort(self._pending, ScheduledCommand(command_id, time_s, command), key=_execution_order)
        return command_id

    def cancel(self, command_id: CommandId) -> bool:
        """Cancel a pending command. Returns `False` if it is unknown, executed, or already canceled."""
        for index, scheduled in enumerate(self._pending):
            if scheduled.command_id == command_id:
                del self._pending[index]
                return True
        return False

    def cancel_from(self, time_s: float) -> tuple[CommandId, ...]:
        """Cancel all pending commands scheduled at or after `time_s` and return their identifiers."""
        time_s = _as_time(time_s)
        canceled = tuple(s.command_id for s in self._pending if s.time_s >= time_s)
        self._pending = [s for s in self._pending if s.time_s < time_s]
        return canceled

    def pending(self) -> tuple[ScheduledCommand, ...]:
        """Pending commands in execution order."""
        return tuple(self._pending)

    def next_time_s(self) -> float | None:
        """Time of the next pending command, or `None` if nothing is pending."""
        return self._pending[0].time_s if self._pending else None

    def pop_due(self, now_s: float) -> ScheduledCommand | None:
        """Remove and return the next command due at or before `now_s`, or `None` if none is due."""
        if self._pending and self._pending[0].time_s <= now_s:
            return self._pending.pop(0)
        return None


def _as_time(time_s: float) -> float:
    if isinstance(time_s, bool):
        raise CommandError(f"time must be a number of seconds, got {time_s!r}")
    try:
        value = float(time_s)
    except (TypeError, ValueError) as error:
        raise CommandError(f"time must be a number of seconds, got {time_s!r}") from error
    if not math.isfinite(value):
        raise CommandError(f"time must be finite, got {time_s!r}")
    return value
