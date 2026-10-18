from collections.abc import Callable

import pytest

from spacecraft_ops.commands import PropulsionMode
from spacecraft_ops.model import SafetyLimits, SpacecraftParameters, SpacecraftState, ThrusterParameters
from spacecraft_ops.scenario import Scenario


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
        min_propulsion_temperature_c=-50.0,
        max_propulsion_temperature_c=150.0,
        min_battery_energy_wh=0.0,
        max_abs_wheel_momentum_nms=100.0,
    )


@pytest.fixture
def make_scenario(parameters, limits, make_state) -> Callable[..., Scenario]:
    """Factory for small test scenarios: 1 s integration step, 60 s decision period, 600 s time limit."""

    def factory(**overrides: object) -> Scenario:
        values: dict[str, object] = {
            "name": "test",
            "parameters": parameters,
            "initial_state": make_state(),
            "limits": limits,
            "target_delta_v_mps": 1.0,
            "time_limit_s": 600.0,
            "integration_step_s": 1.0,
            "decision_period_s": 60.0,
        }
        return Scenario(**(values | overrides))

    return factory
