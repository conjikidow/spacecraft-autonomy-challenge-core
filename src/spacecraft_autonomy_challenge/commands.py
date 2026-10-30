"""Commands that a strategy can place on the spacecraft timeline."""

from dataclasses import dataclass
from enum import StrEnum


class CommandError(ValueError):
    """Raised synchronously when a strategy makes an invalid command or timeline request."""


class PropulsionMode(StrEnum):
    """Exclusive propulsion mode: at most one thruster fires at any time."""

    OFF = "OFF"
    THRUSTER_1 = "THRUSTER_1"
    THRUSTER_2 = "THRUSTER_2"


@dataclass(frozen=True, slots=True)
class SetPropulsionMode:
    """Select the propulsion mode. Selecting a thruster implicitly stops the other one."""

    mode: PropulsionMode

    def __post_init__(self) -> None:
        try:
            mode = PropulsionMode(self.mode)
        except ValueError as error:
            raise CommandError(f"unknown propulsion mode: {self.mode!r}") from error
        object.__setattr__(self, "mode", mode)


@dataclass(frozen=True, slots=True)
class SetHeater:
    """Switch the propulsion heater on or off."""

    on: bool

    def __post_init__(self) -> None:
        if not isinstance(self.on, bool):
            raise CommandError(f"heater state must be a bool, got {self.on!r}")


@dataclass(frozen=True, slots=True)
class SetMomentumDump:
    """Switch the momentum dump on or off.

    While it is on, the main thrusters do not fire and the wheel momentum moves toward zero.
    The dump switches itself off when the wheel momentum reaches zero.
    """

    on: bool

    def __post_init__(self) -> None:
        if not isinstance(self.on, bool):
            raise CommandError(f"momentum dump state must be a bool, got {self.on!r}")


@dataclass(frozen=True, slots=True)
class DeclareCompletion:
    """Declare that the strategy considers the maneuver complete.

    Executing this command ends the run. It says nothing about whether the maneuver succeeded.
    """


Command = SetPropulsionMode | SetHeater | SetMomentumDump | DeclareCompletion
