"""Parameterized toy spacecraft model: parameters, safety limits, true state, and dynamics.

The model is intentionally simple. Units are part of every field name, for example
seconds (`_s`), meters per second (`_mps`), meters per second squared (`_mps2`), degrees Celsius (`_c`),
watts (`_w`), watt-hours (`_wh`), joules per kelvin (`_j_per_k`), and newton-meter-seconds (`_nms`).
"""

from dataclasses import dataclass, replace

from spacecraft_ops.commands import PropulsionMode

SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class ThrusterParameters:
    """Behavior of one thruster while it fires."""

    acceleration_mps2: float
    """Rate at which accumulated delta-v grows."""
    power_w: float
    """Electrical load."""
    heat_w: float
    """Heat delivered to the propulsion thermal node."""
    wheel_momentum_rate_nms_per_s: float
    """Signed rate of change of the scalar wheel momentum."""


@dataclass(frozen=True, slots=True)
class SpacecraftParameters:
    """Physical parameters of the reference spacecraft model."""

    thruster_1: ThrusterParameters
    thruster_2: ThrusterParameters
    power_generation_w: float
    bus_load_w: float
    heater_power_w: float
    """Electrical load of the heater; all of it becomes heat in the propulsion node."""
    battery_capacity_wh: float
    heat_capacity_j_per_k: float
    """Heat capacity of the lumped propulsion thermal node."""
    thermal_conductance_w_per_k: float
    """Conductance of passive cooling toward the sink temperature."""
    sink_temperature_c: float

    def __post_init__(self) -> None:
        if self.battery_capacity_wh <= 0:
            raise ValueError("battery_capacity_wh must be positive")
        if self.heat_capacity_j_per_k <= 0:
            raise ValueError("heat_capacity_j_per_k must be positive")
        if self.thermal_conductance_w_per_k < 0:
            raise ValueError("thermal_conductance_w_per_k must not be negative")

    def thruster(self, mode: PropulsionMode) -> ThrusterParameters | None:
        """Parameters of the thruster selected by `mode`, or `None` when propulsion is off."""
        match mode:
            case PropulsionMode.THRUSTER_1:
                return self.thruster_1
            case PropulsionMode.THRUSTER_2:
                return self.thruster_2
            case PropulsionMode.OFF:
                return None


@dataclass(frozen=True, slots=True)
class SafetyLimits:
    """Hard limits on the true state. Leaving them terminates the run."""

    min_propulsion_temperature_c: float
    max_propulsion_temperature_c: float
    min_battery_energy_wh: float
    max_abs_wheel_momentum_nms: float

    def __post_init__(self) -> None:
        if self.min_propulsion_temperature_c >= self.max_propulsion_temperature_c:
            raise ValueError("min_propulsion_temperature_c must be below max_propulsion_temperature_c")
        if self.max_abs_wheel_momentum_nms <= 0:
            raise ValueError("max_abs_wheel_momentum_nms must be positive")


@dataclass(frozen=True, slots=True)
class SpacecraftState:
    """True internal spacecraft state. Never passed to strategies."""

    time_s: float
    delta_v_mps: float
    propulsion_temperature_c: float
    battery_energy_wh: float
    wheel_momentum_nms: float
    heater_on: bool
    propulsion_mode: PropulsionMode


@dataclass(frozen=True, slots=True)
class StateRates:
    """Time derivatives of the continuous state variables."""

    delta_v_rate_mps2: float
    temperature_rate_c_per_s: float
    net_power_w: float
    wheel_momentum_rate_nms_per_s: float


def compute_rates(state: SpacecraftState, parameters: SpacecraftParameters) -> StateRates:
    """Nominal state rates for the current state and effective parameters."""
    thruster = parameters.thruster(state.propulsion_mode)
    heater_power_w = parameters.heater_power_w if state.heater_on else 0.0
    thruster_power_w = thruster.power_w if thruster else 0.0
    thruster_heat_w = thruster.heat_w if thruster else 0.0

    cooling_w = parameters.thermal_conductance_w_per_k * (
        state.propulsion_temperature_c - parameters.sink_temperature_c
    )
    net_heat_w = heater_power_w + thruster_heat_w - cooling_w
    net_power_w = parameters.power_generation_w - parameters.bus_load_w - heater_power_w - thruster_power_w

    return StateRates(
        delta_v_rate_mps2=thruster.acceleration_mps2 if thruster else 0.0,
        temperature_rate_c_per_s=net_heat_w / parameters.heat_capacity_j_per_k,
        net_power_w=net_power_w,
        wheel_momentum_rate_nms_per_s=thruster.wheel_momentum_rate_nms_per_s if thruster else 0.0,
    )


def integrate(
    state: SpacecraftState,
    rates: StateRates,
    duration_s: float,
    parameters: SpacecraftParameters,
) -> SpacecraftState:
    """Advance `state` by `duration_s` with one explicit Euler step.

    Battery energy above the capacity is discarded. Energy is not clamped at zero,
    so depletion remains visible to the safety checks.
    """
    battery_energy_wh = state.battery_energy_wh + rates.net_power_w * duration_s / SECONDS_PER_HOUR
    return replace(
        state,
        time_s=state.time_s + duration_s,
        delta_v_mps=state.delta_v_mps + rates.delta_v_rate_mps2 * duration_s,
        propulsion_temperature_c=state.propulsion_temperature_c + rates.temperature_rate_c_per_s * duration_s,
        battery_energy_wh=min(battery_energy_wh, parameters.battery_capacity_wh),
        wheel_momentum_nms=state.wheel_momentum_nms + rates.wheel_momentum_rate_nms_per_s * duration_s,
    )
