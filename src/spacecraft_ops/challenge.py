"""Public problem definition of the challenge and its public scenarios.

The numbers are provisional placeholders for the toy spacecraft model. See `docs/challenge.md`.
"""

from collections.abc import Callable

from spacecraft_ops.commands import PropulsionMode
from spacecraft_ops.model import SafetyLimits, SpacecraftParameters, SpacecraftState, ThrusterParameters
from spacecraft_ops.modifiers import ThrusterEfficiency
from spacecraft_ops.problem import Problem
from spacecraft_ops.scenario import Scenario


def problem() -> Problem:
    """The challenge problem shared by all of its scenarios."""
    return Problem(
        parameters=SpacecraftParameters(
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
            min_firing_temperature_c=0.0,
        ),
        initial_state=SpacecraftState(
            time_s=0.0,
            delta_v_mps=0.0,
            propulsion_temperature_c=20.0,
            battery_energy_wh=80.0,
            wheel_momentum_nms=0.0,
            heater_on=False,
            propulsion_mode=PropulsionMode.OFF,
        ),
        limits=SafetyLimits(
            max_propulsion_temperature_c=60.0,
            min_battery_energy_wh=10.0,
            max_abs_wheel_momentum_nms=5.0,
        ),
        target_delta_v_mps=10.0,
        time_limit_s=21600.0,
        decision_period_s=60.0,
    )


def _nominal() -> Scenario:
    return Scenario(
        name="nominal",
        problem=problem(),
        description="The spacecraft behaves exactly as the nominal model.",
    )


def _thruster_degradation() -> Scenario:
    return Scenario(
        name="thruster-degradation",
        problem=problem(),
        modifiers=(ThrusterEfficiency(PropulsionMode.THRUSTER_1, factor=0.8, onset_time_s=3600.0),),
        description="Thruster 1 loses part of its acceleration partway through the run.",
    )


_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "nominal": _nominal,
    "thruster-degradation": _thruster_degradation,
}


def scenario_names() -> tuple[str, ...]:
    """Names of the public scenarios."""
    return tuple(_SCENARIOS)


def scenario(name: str) -> Scenario:
    """Build the public scenario called `name`. Raises `KeyError` for unknown names."""
    try:
        factory = _SCENARIOS[name]
    except KeyError:
        raise KeyError(f"unknown scenario {name!r}; available: {', '.join(_SCENARIOS)}") from None
    return factory()
