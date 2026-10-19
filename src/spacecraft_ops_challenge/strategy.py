"""Participant-facing strategy interface.

A strategy sees only `MissionBrief`, `Telemetry`, and a `Commander`. It never receives simulator objects
or the true spacecraft state. See `docs/strategy.md`.
"""

from dataclasses import dataclass
from typing import Protocol

from spacecraft_ops_challenge.commands import Command
from spacecraft_ops_challenge.model import SafetyLimits, SpacecraftParameters
from spacecraft_ops_challenge.telemetry import Telemetry
from spacecraft_ops_challenge.timeline import CommandId, ScheduledCommand


@dataclass(frozen=True, slots=True)
class MissionBrief:
    """Public mission information given to a strategy before autonomous operation starts."""

    target_delta_v_mps: float
    time_limit_s: float
    decision_period_s: float
    limits: SafetyLimits
    nominal_parameters: SpacecraftParameters
    """Published nominal model. The actual spacecraft may deviate from it."""


class Commander(Protocol):
    """Interface through which a strategy affects the spacecraft.

    A commander is valid only during the strategy callback it was passed to; afterwards every member
    raises `CommandError`. No command executes while the callback runs. Commands scheduled for the
    current time execute right after the callback returns, before simulation time advances.
    Requests are plain data (times, commands, and identifiers), so implementations may forward them
    to a simulator in the same process or elsewhere.
    """

    @property
    def now_s(self) -> float:
        """Current simulation time in seconds."""
        ...

    def schedule(self, time_s: float, command: Command) -> CommandId:
        """Register `command` for execution at `time_s`, which must not be earlier than `now_s`."""
        ...

    def execute(self, command: Command) -> CommandId:
        """Register `command` for immediate execution, equivalent to `schedule(now_s, command)`."""
        ...

    def cancel(self, command_id: CommandId) -> bool:
        """Cancel a pending command. Returns `False` if it is unknown, executed, or already canceled."""
        ...

    def cancel_from(self, time_s: float) -> tuple[CommandId, ...]:
        """Cancel all pending commands scheduled at or after `time_s` and return their identifiers."""
        ...

    def pending(self) -> tuple[ScheduledCommand, ...]:
        """Pending commands in execution order."""
        ...


class Strategy:
    """Base class for participant strategies. Override either or both callbacks."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        """Called once at simulation time 0, before autonomous operation starts."""

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        """Called at every decision time `k * brief.decision_period_s` for `k >= 1` until the run ends."""
