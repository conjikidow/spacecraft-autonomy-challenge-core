import random
from dataclasses import replace

import pytest

from spacecraft_ops.commands import PropulsionMode
from spacecraft_ops.model import SpacecraftState, StateRates
from spacecraft_ops.modifiers import (
    Modifier,
    TelemetryBias,
    ThrusterEfficiency,
    effective_parameters,
    effective_rates,
    nominal_telemetry,
    observe,
)
from spacecraft_ops.telemetry import Telemetry


def test_base_modifier_changes_nothing(parameters, make_state):
    rng = random.Random(0)
    state = make_state(propulsion_mode=PropulsionMode.THRUSTER_1)
    assert effective_parameters(parameters, state, [Modifier()], rng) == parameters
    assert observe(state, [Modifier()], rng) == nominal_telemetry(state)


def test_nominal_telemetry_is_a_separate_type_with_true_values(make_state):
    state = make_state(delta_v_mps=1.5, wheel_momentum_nms=-0.3)
    telemetry = nominal_telemetry(state)
    assert type(telemetry) is Telemetry
    assert not isinstance(telemetry, SpacecraftState)
    assert (telemetry.delta_v_mps, telemetry.wheel_momentum_nms) == (1.5, -0.3)


def test_thruster_efficiency_applies_from_onset_to_one_thruster_only(parameters, make_state):
    modifier = ThrusterEfficiency(PropulsionMode.THRUSTER_1, factor=0.5, onset_time_s=100.0)
    rng = random.Random(0)
    before = effective_parameters(parameters, make_state(time_s=99.0), [modifier], rng)
    after = effective_parameters(parameters, make_state(time_s=100.0), [modifier], rng)
    assert before == parameters
    assert after.thruster_1.acceleration_mps2 == pytest.approx(parameters.thruster_1.acceleration_mps2 / 2)
    assert after.thruster_1.power_w == parameters.thruster_1.power_w
    assert after.thruster_2 == parameters.thruster_2


def test_thruster_efficiency_accepts_mode_names(parameters, make_state):
    modifier = ThrusterEfficiency("THRUSTER_1", factor=0.5)
    after = effective_parameters(parameters, make_state(), [modifier], random.Random(0))
    assert after.thruster_1.acceleration_mps2 == pytest.approx(parameters.thruster_1.acceleration_mps2 / 2)
    assert after.thruster_2 == parameters.thruster_2


@pytest.mark.parametrize(("thruster", "factor"), [(PropulsionMode.OFF, 0.5), ("OFF", 0.5), ("bogus", 0.5)])
def test_thruster_efficiency_rejects_invalid_thruster(thruster, factor):
    with pytest.raises(ValueError, match=r"THRUSTER|bogus"):
        ThrusterEfficiency(thruster, factor=factor)


def test_thruster_efficiency_rejects_negative_factor():
    with pytest.raises(ValueError, match="factor"):
        ThrusterEfficiency(PropulsionMode.THRUSTER_2, factor=-0.1)


def test_telemetry_bias_changes_observation_but_not_true_state(make_state):
    state = make_state(propulsion_temperature_c=20.0)
    telemetry = observe(state, [TelemetryBias("propulsion_temperature_c", 3.0)], random.Random(0))
    assert telemetry.propulsion_temperature_c == 23.0
    assert state.propulsion_temperature_c == 20.0


@pytest.mark.parametrize("channel", ["time_s", "heater_on", "propulsion_mode", "fuel"])
def test_telemetry_bias_rejects_unknown_or_non_numeric_channel(channel):
    with pytest.raises(ValueError, match="channel"):
        TelemetryBias(channel, 1.0)


def test_modifiers_compose_in_order(make_state):
    class Double(Modifier):
        def modify_telemetry(self, telemetry: Telemetry, state: SpacecraftState, rng: random.Random) -> Telemetry:
            return replace(telemetry, delta_v_mps=telemetry.delta_v_mps * 2)

    state = make_state(delta_v_mps=1.0)
    rng = random.Random(0)
    assert observe(state, [TelemetryBias("delta_v_mps", 1.0), Double()], rng).delta_v_mps == 4.0
    assert observe(state, [Double(), TelemetryBias("delta_v_mps", 1.0)], rng).delta_v_mps == 3.0


def test_custom_rate_modifier_can_add_unexpected_coupling(parameters, make_state):
    class HeaterTorque(Modifier):
        def modify_rates(self, rates: StateRates, state: SpacecraftState, parameters, rng) -> StateRates:
            if not state.heater_on:
                return rates
            return replace(rates, wheel_momentum_rate_nms_per_s=rates.wheel_momentum_rate_nms_per_s + 0.001)

    rates = effective_rates(make_state(heater_on=True), parameters, [HeaterTorque()], random.Random(0))
    assert rates.wheel_momentum_rate_nms_per_s == 0.001
