"""Public reference scenarios for the toy spacecraft model.

All numbers are placeholders chosen so that every safety limit matters for a plausible plan.
See `docs/reference-scenarios.md`.
"""

from collections.abc import Callable

from spacecraft_ops.commands import PropulsionMode
from spacecraft_ops.model import SafetyLimits, SpacecraftParameters, SpacecraftState, ThrusterParameters
from spacecraft_ops.modifiers import ThrusterEfficiency
from spacecraft_ops.scenario import Scenario

TARGET_DELTA_V_MPS = 10.0
TIME_LIMIT_S = 21600.0
INTEGRATION_STEP_S = 1.0
DECISION_PERIOD_S = 60.0
DEGRADATION_FACTOR = 0.8
DEGRADATION_ONSET_S = 3600.0


def nominal_parameters() -> SpacecraftParameters:
    """Symmetric nominal model shared by all reference scenarios."""
    return SpacecraftParameters(
        thruster_1=ThrusterParameters(
            acceleration_mps2=0.001, power_w=30.0, heat_w=40.0, wheel_momentum_rate_nms_per_s=0.002
        ),
        thruster_2=ThrusterParameters(
            acceleration_mps2=0.001, power_w=30.0, heat_w=40.0, wheel_momentum_rate_nms_per_s=-0.002
        ),
        power_generation_w=60.0,
        bus_load_w=40.0,
        heater_power_w=10.0,
        battery_capacity_wh=100.0,
        heat_capacity_j_per_k=2000.0,
        thermal_conductance_w_per_k=0.5,
        sink_temperature_c=-10.0,
    )


def nominal_limits() -> SafetyLimits:
    """Safety limits shared by all reference scenarios."""
    return SafetyLimits(
        min_propulsion_temperature_c=0.0,
        max_propulsion_temperature_c=60.0,
        min_battery_energy_wh=10.0,
        max_abs_wheel_momentum_nms=5.0,
    )


def nominal_initial_state() -> SpacecraftState:
    """Initial true state shared by all reference scenarios."""
    return SpacecraftState(
        time_s=0.0,
        delta_v_mps=0.0,
        propulsion_temperature_c=20.0,
        battery_energy_wh=80.0,
        wheel_momentum_nms=0.0,
        heater_on=False,
        propulsion_mode=PropulsionMode.OFF,
    )


def _nominal() -> Scenario:
    return Scenario(
        name="nominal",
        parameters=nominal_parameters(),
        initial_state=nominal_initial_state(),
        limits=nominal_limits(),
        target_delta_v_mps=TARGET_DELTA_V_MPS,
        time_limit_s=TIME_LIMIT_S,
        integration_step_s=INTEGRATION_STEP_S,
        decision_period_s=DECISION_PERIOD_S,
        description="The spacecraft behaves exactly as the nominal model.",
    )


def _thruster_degradation() -> Scenario:
    return Scenario(
        name="thruster-degradation",
        parameters=nominal_parameters(),
        initial_state=nominal_initial_state(),
        limits=nominal_limits(),
        target_delta_v_mps=TARGET_DELTA_V_MPS,
        time_limit_s=TIME_LIMIT_S,
        integration_step_s=INTEGRATION_STEP_S,
        decision_period_s=DECISION_PERIOD_S,
        modifiers=(ThrusterEfficiency(PropulsionMode.THRUSTER_1, DEGRADATION_FACTOR, DEGRADATION_ONSET_S),),
        description="Thruster 1 loses part of its acceleration partway through the run.",
    )


_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "nominal": _nominal,
    "thruster-degradation": _thruster_degradation,
}


def reference_scenario_names() -> tuple[str, ...]:
    """Names of all reference scenarios."""
    return tuple(_SCENARIOS)


def reference_scenario(name: str) -> Scenario:
    """Build the reference scenario called `name`. Raises `KeyError` for unknown names."""
    try:
        factory = _SCENARIOS[name]
    except KeyError:
        raise KeyError(f"unknown reference scenario {name!r}; available: {', '.join(_SCENARIOS)}") from None
    return factory()
