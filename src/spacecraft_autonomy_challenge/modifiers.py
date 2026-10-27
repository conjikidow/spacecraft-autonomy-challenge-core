"""Extension hooks that change simulation behavior without changing the participant API.

Scenarios apply modifiers in order. Each hook receives the true state, so effects can depend on time or state.
Modifiers should be stateless; randomness during a run must come from the provided seeded `rng`.
Custom `Modifier` subclasses can be defined outside this package.
"""

import random
import typing
from collections.abc import Sequence
from dataclasses import dataclass, replace

from spacecraft_autonomy_challenge.commands import PropulsionMode
from spacecraft_autonomy_challenge.model import SpacecraftParameters, SpacecraftState, StateRates, compute_rates
from spacecraft_autonomy_challenge.telemetry import Telemetry


class Modifier:
    """Base class for modifiers. Override any subset of the hooks; the defaults change nothing."""

    def modify_parameters(
        self,
        parameters: SpacecraftParameters,
        state: SpacecraftState,
        rng: random.Random,
    ) -> SpacecraftParameters:
        """Return the effective parameters at `state.time_s`."""
        return parameters

    def modify_rates(
        self,
        rates: StateRates,
        state: SpacecraftState,
        parameters: SpacecraftParameters,
        rng: random.Random,
    ) -> StateRates:
        """Return state rates after this modifier's effect, e.g. an unexpected coupling."""
        return rates

    def modify_telemetry(self, telemetry: Telemetry, state: SpacecraftState, rng: random.Random) -> Telemetry:
        """Return telemetry after this modifier's effect, e.g. sensor bias or noise."""
        return telemetry


def effective_parameters(
    nominal: SpacecraftParameters,
    state: SpacecraftState,
    modifiers: Sequence[Modifier],
    rng: random.Random,
) -> SpacecraftParameters:
    """Apply all parameter hooks to the nominal parameters."""
    parameters = nominal
    for modifier in modifiers:
        parameters = modifier.modify_parameters(parameters, state, rng)
    return parameters


def effective_rates(
    state: SpacecraftState,
    parameters: SpacecraftParameters,
    modifiers: Sequence[Modifier],
    rng: random.Random,
) -> StateRates:
    """Compute nominal rates and apply all rate hooks."""
    rates = compute_rates(state, parameters)
    for modifier in modifiers:
        rates = modifier.modify_rates(rates, state, parameters, rng)
    return rates


def nominal_telemetry(state: SpacecraftState) -> Telemetry:
    """Ideal observation of the true state, before any modifier effects."""
    return Telemetry(
        time_s=state.time_s,
        delta_v_mps=state.delta_v_mps,
        propulsion_temperature_c=state.propulsion_temperature_c,
        battery_energy_wh=state.battery_energy_wh,
        wheel_momentum_nms=state.wheel_momentum_nms,
        heater_on=state.heater_on,
        propulsion_mode=state.propulsion_mode,
    )


def observe(state: SpacecraftState, modifiers: Sequence[Modifier], rng: random.Random) -> Telemetry:
    """Sample telemetry from the true state and apply all telemetry hooks."""
    telemetry = nominal_telemetry(state)
    for modifier in modifiers:
        telemetry = modifier.modify_telemetry(telemetry, state, rng)
    return telemetry


@dataclass(frozen=True)
class ThrusterEfficiency(Modifier):
    """Scale one thruster's acceleration by `factor` from `onset_time_s` onward."""

    thruster: PropulsionMode
    factor: float
    onset_time_s: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "thruster", PropulsionMode(self.thruster))
        if self.thruster is PropulsionMode.OFF:
            raise ValueError("thruster must be THRUSTER_1 or THRUSTER_2")
        if self.factor < 0:
            raise ValueError("factor must not be negative")

    def modify_parameters(
        self,
        parameters: SpacecraftParameters,
        state: SpacecraftState,
        rng: random.Random,
    ) -> SpacecraftParameters:
        if state.time_s < self.onset_time_s:
            return parameters
        name = "thruster_1" if self.thruster is PropulsionMode.THRUSTER_1 else "thruster_2"
        thruster = getattr(parameters, name)
        degraded = replace(thruster, acceleration_mps2=thruster.acceleration_mps2 * self.factor)
        return replace(parameters, **{name: degraded})


BIASABLE_TELEMETRY_CHANNELS = frozenset(
    name for name, hint in typing.get_type_hints(Telemetry).items() if hint is float and name != "time_s"
)


@dataclass(frozen=True)
class TelemetryBias(Modifier):
    """Add a constant `bias` to one numeric telemetry channel."""

    channel: str
    bias: float

    def __post_init__(self) -> None:
        if self.channel not in BIASABLE_TELEMETRY_CHANNELS:
            raise ValueError(f"channel must be one of {sorted(BIASABLE_TELEMETRY_CHANNELS)}, got {self.channel!r}")

    def modify_telemetry(self, telemetry: Telemetry, state: SpacecraftState, rng: random.Random) -> Telemetry:
        return replace(telemetry, **{self.channel: getattr(telemetry, self.channel) + self.bias})
