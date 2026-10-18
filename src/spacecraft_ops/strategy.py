"""Participant-facing strategy interface.

A strategy sees only `MissionBrief`, `Telemetry`, and a `Commander`. It never receives simulator objects
or the true spacecraft state. See `docs/strategy.md`.
"""

from dataclasses import dataclass

from spacecraft_ops.commands import Command, CommandError
from spacecraft_ops.model import SafetyLimits, SpacecraftParameters
from spacecraft_ops.telemetry import Telemetry
from spacecraft_ops.timeline import CommandId, ScheduledCommand, Timeline


@dataclass(frozen=True, slots=True)
class MissionBrief:
    """Public mission information given to a strategy before autonomous operation starts."""

    target_delta_v_mps: float
    time_limit_s: float
    decision_period_s: float
    limits: SafetyLimits
    nominal_parameters: SpacecraftParameters
    """Published nominal model. The actual spacecraft may deviate from it."""


class Commander:
    """Access to the spacecraft timeline, valid only during the strategy callback it was passed to.

    No command executes while the callback runs. Commands scheduled for the current time execute
    right after the callback returns, before simulation time advances.
    """

    def __init__(self, timeline: Timeline, now_s: float) -> None:
        self._timeline = timeline
        self._now_s = now_s
        self._open = True

    @property
    def now_s(self) -> float:
        """Current simulation time in seconds."""
        return self._now_s

    def schedule(self, time_s: float, command: Command) -> CommandId:
        """Register `command` for execution at `time_s`, which must not be earlier than `now_s`."""
        self._ensure_open()
        return self._timeline.schedule(time_s, command, now_s=self._now_s)

    def execute(self, command: Command) -> CommandId:
        """Register `command` for immediate execution, equivalent to `schedule(now_s, command)`."""
        return self.schedule(self._now_s, command)

    def cancel(self, command_id: CommandId) -> bool:
        """Cancel a pending command. Returns `False` if it is unknown, executed, or already canceled."""
        self._ensure_open()
        return self._timeline.cancel(command_id)

    def cancel_from(self, time_s: float) -> tuple[CommandId, ...]:
        """Cancel all pending commands scheduled at or after `time_s` and return their identifiers."""
        self._ensure_open()
        return self._timeline.cancel_from(time_s)

    def pending(self) -> tuple[ScheduledCommand, ...]:
        """Pending commands in execution order."""
        self._ensure_open()
        return self._timeline.pending()

    def close(self) -> None:
        """End the commanding window. Called by the simulation when the callback returns."""
        self._open = False

    def _ensure_open(self) -> None:
        if not self._open:
            raise CommandError("this commander is only valid during the callback it was passed to")


class Strategy:
    """Base class for participant strategies. Override either or both callbacks."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        """Called once at simulation time 0, before autonomous operation starts."""

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        """Called at every decision time `k * brief.decision_period_s` for `k >= 1` until the run ends."""
