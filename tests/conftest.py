from collections.abc import Callable
from dataclasses import fields

import pytest

from spacecraft_ops_challenge.commands import PropulsionMode
from spacecraft_ops_challenge.model import SafetyLimits, SpacecraftParameters, SpacecraftState, ThrusterParameters
from spacecraft_ops_challenge.problem import Problem
from spacecraft_ops_challenge.scenario import Scenario


@pytest.fixture
def parameters() -> SpacecraftParameters:
    """Symmetric test parameters with round numbers for hand-checkable expectations."""
    return SpacecraftParameters(
        thruster_1=ThrusterParameters(
            acceleration_mps2=0.002, power_w=30.0, heat_w=40.0, wheel_momentum_rate_nms_per_s=0.01
        ),
        thruster_2=ThrusterParameters(
            acceleration_mps2=0.002, power_w=30.0, heat_w=40.0, wheel_momentum_rate_nms_per_s=-0.01
        ),
        power_generation_w=60.0,
        bus_load_w=40.0,
        heater_power_w=10.0,
        battery_capacity_wh=100.0,
        heat_capacity_j_per_k=2000.0,
        thermal_conductance_w_per_k=0.5,
        sink_temperature_c=-10.0,
        min_firing_temperature_c=-50.0,
    )


@pytest.fixture
def make_state() -> Callable[..., SpacecraftState]:
    """Factory for true states with defaults that keep every quantity well inside typical limits."""

    def factory(**overrides: object) -> SpacecraftState:
        values: dict[str, object] = {
            "time_s": 0.0,
            "delta_v_mps": 0.0,
            "propulsion_temperature_c": 20.0,
            "battery_energy_wh": 50.0,
            "wheel_momentum_nms": 0.0,
            "heater_on": False,
            "propulsion_mode": PropulsionMode.OFF,
        }
        return SpacecraftState(**(values | overrides))

    return factory


@pytest.fixture
def limits() -> SafetyLimits:
    """Limits wide enough that short test runs stay safe unless a test narrows them."""
    return SafetyLimits(
        max_propulsion_temperature_c=150.0,
        min_battery_energy_wh=0.0,
        max_abs_wheel_momentum_nms=100.0,
    )


PROBLEM_FIELDS = frozenset(field.name for field in fields(Problem))


@pytest.fixture
def make_scenario(parameters, limits, make_state) -> Callable[..., Scenario]:
    """Factory for small test scenarios: 60 s decision period and 600 s time limit.

    Keyword arguments named like `Problem` fields override the problem; the rest override the scenario.
    """

    def factory(**overrides: object) -> Scenario:
        problem_values: dict[str, object] = {
            "parameters": parameters,
            "initial_state": make_state(),
            "limits": limits,
            "target_delta_v_mps": 1.0,
            "time_limit_s": 600.0,
            "decision_period_s": 60.0,
        }
        problem_values |= {key: value for key, value in overrides.items() if key in PROBLEM_FIELDS}
        scenario_values = {"name": "test"} | {k: v for k, v in overrides.items() if k not in PROBLEM_FIELDS}
        return Scenario(problem=Problem(**problem_values), **scenario_values)

    return factory
