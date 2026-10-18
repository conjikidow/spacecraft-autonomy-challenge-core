from collections.abc import Callable

import pytest

from spacecraft_ops.commands import PropulsionMode
from spacecraft_ops.model import SpacecraftParameters, SpacecraftState, ThrusterParameters


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
