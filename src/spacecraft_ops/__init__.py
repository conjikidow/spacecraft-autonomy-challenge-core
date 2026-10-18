"""Python package for a spacecraft operations challenge.

The top-level package exports the strategy-facing API. Simulation, scenario, and result types are
imported from their submodules.
"""

from importlib.metadata import version

from spacecraft_ops.commands import CommandError, CompleteMission, PropulsionMode, SetHeater, SetPropulsionMode
from spacecraft_ops.model import SafetyLimits, SpacecraftParameters, ThrusterParameters
from spacecraft_ops.strategy import Commander, MissionBrief, Strategy
from spacecraft_ops.telemetry import Telemetry
from spacecraft_ops.timeline import CommandId, ScheduledCommand

__version__ = version("spacecraft-operations-challenge-core")

__all__ = [
    "CommandError",
    "CommandId",
    "Commander",
    "CompleteMission",
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
