"""Python package for the Spacecraft Autonomy Challenge.

The top-level package exports the strategy-facing API. Simulation, scenario, and result types are
imported from their submodules.
"""

from importlib.metadata import version

from spacecraft_autonomy_challenge.commands import (
    CommandError,
    DeclareCompletion,
    PropulsionMode,
    SetHeater,
    SetMomentumDump,
    SetPropulsionMode,
)
from spacecraft_autonomy_challenge.model import SafetyLimits, SpacecraftParameters, ThrusterParameters
from spacecraft_autonomy_challenge.strategy import Commander, MissionBrief, Strategy
from spacecraft_autonomy_challenge.telemetry import Telemetry
from spacecraft_autonomy_challenge.timeline import CommandId, ScheduledCommand

__version__ = version("spacecraft-autonomy-challenge-core")

__all__ = [
    "CommandError",
    "CommandId",
    "Commander",
    "DeclareCompletion",
    "MissionBrief",
    "PropulsionMode",
    "SafetyLimits",
    "ScheduledCommand",
    "SetHeater",
    "SetMomentumDump",
    "SetPropulsionMode",
    "SpacecraftParameters",
    "Strategy",
    "Telemetry",
    "ThrusterParameters",
    "__version__",
]
