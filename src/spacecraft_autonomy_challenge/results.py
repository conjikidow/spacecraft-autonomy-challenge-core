"""Run termination and run results."""

from dataclasses import dataclass
from enum import StrEnum

from spacecraft_autonomy_challenge.config import SimulationConfig
from spacecraft_autonomy_challenge.model import SpacecraftState
from spacecraft_autonomy_challenge.scenario import Scenario
from spacecraft_autonomy_challenge.telemetry import Telemetry
from spacecraft_autonomy_challenge.timeline import ScheduledCommand


class TerminationReason(StrEnum):
    """Why a run ended. Safety reasons are listed in the priority used when several occur at once."""

    COMPLETION_DECLARED = "COMPLETION_DECLARED"
    TIME_LIMIT = "TIME_LIMIT"
    THERMAL_VIOLATION = "THERMAL_VIOLATION"
    BATTERY_DEPLETED = "BATTERY_DEPLETED"
    MOMENTUM_VIOLATION = "MOMENTUM_VIOLATION"
    STRATEGY_ERROR = "STRATEGY_ERROR"
    INVALID_COMMAND = "INVALID_COMMAND"


@dataclass(frozen=True, slots=True)
class SafetyViolation:
    """A safety limit exceeded by the true state."""

    reason: TerminationReason
    time_s: float
    message: str


@dataclass(frozen=True, slots=True)
class Termination:
    """How and when a run ended. `detail` holds a message or traceback for failures."""

    reason: TerminationReason
    time_s: float
    detail: str = ""


@dataclass(frozen=True)
class RunResult:
    """Complete record of one run, including ground truth for evaluation.

    `trajectory` holds the true state at the start and at every event time, sampled after integration
    and before commands at that time execute. `final_state` additionally reflects those commands.
    """

    scenario: Scenario
    config: SimulationConfig
    seed: int
    termination: Termination
    safety_violations: tuple[SafetyViolation, ...]
    final_state: SpacecraftState
    trajectory: tuple[SpacecraftState, ...]
    telemetry: tuple[Telemetry, ...]
    executed_commands: tuple[ScheduledCommand, ...]
