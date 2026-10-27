"""Participant-visible telemetry, kept separate from the true spacecraft state."""

from dataclasses import dataclass

from spacecraft_autonomy_challenge.commands import PropulsionMode


@dataclass(frozen=True, slots=True)
class Telemetry:
    """One snapshot of observations available to a strategy.

    Values may differ from the true state when a scenario adds sensor or estimation effects.
    """

    time_s: float
    delta_v_mps: float
    propulsion_temperature_c: float
    battery_energy_wh: float
    wheel_momentum_nms: float
    heater_on: bool
    propulsion_mode: PropulsionMode
