"""Python package for the Spacecraft Operations Challenge.

The top-level package exports the strategy-facing API. Simulation, scenario, and result types are
imported from their submodules.
"""

from importlib.metadata import version

from spacecraft_ops_challenge.commands import (
    CommandError,
    DeclareCompletion,
    PropulsionMode,
    SetHeater,
    SetPropulsionMode,
)
from spacecraft_ops_challenge.model import SafetyLimits, SpacecraftParameters, ThrusterParameters
from spacecraft_ops_challenge.strategy import Commander, MissionBrief, Strategy
from spacecraft_ops_challenge.telemetry import Telemetry
from spacecraft_ops_challenge.timeline import CommandId, ScheduledCommand

__version__ = version("spacecraft-operations-challenge-core")

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
    "SetPropulsionMode",
    "SpacecraftParameters",
    "Strategy",
    "Telemetry",
    "ThrusterParameters",
    "__version__",
]
