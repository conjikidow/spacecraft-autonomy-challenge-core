from dataclasses import replace

import pytest

from spacecraft_autonomy_challenge.commands import PropulsionMode
from spacecraft_autonomy_challenge.model import SafetyLimits, compute_rates, integrate


def test_thrusters_have_symmetric_thrust_power_and_heat(parameters, make_state):
    rates_1 = compute_rates(make_state(propulsion_mode=PropulsionMode.THRUSTER_1), parameters)
    rates_2 = compute_rates(make_state(propulsion_mode=PropulsionMode.THRUSTER_2), parameters)
    assert rates_1.delta_v_rate_mps2 == rates_2.delta_v_rate_mps2 > 0
    assert rates_1.net_power_w == rates_2.net_power_w
    assert rates_1.temperature_rate_c_per_s == rates_2.temperature_rate_c_per_s


def test_thrusters_have_opposite_wheel_momentum_effects(parameters, make_state):
    rates_1 = compute_rates(make_state(propulsion_mode=PropulsionMode.THRUSTER_1), parameters)
    rates_2 = compute_rates(make_state(propulsion_mode=PropulsionMode.THRUSTER_2), parameters)
    assert rates_1.wheel_momentum_rate_nms_per_s == 0.01
    assert rates_2.wheel_momentum_rate_nms_per_s == -0.01


def test_propulsion_off_produces_no_thrust_or_momentum_change(parameters, make_state):
    rates = compute_rates(make_state(), parameters)
    assert rates.delta_v_rate_mps2 == 0.0
    assert rates.wheel_momentum_rate_nms_per_s == 0.0


def test_exclusive_mode_means_only_the_selected_thruster_contributes(parameters, make_state):
    distinct = replace(parameters, thruster_1=replace(parameters.thruster_1, acceleration_mps2=1.0, power_w=1.0))
    rates = compute_rates(make_state(propulsion_mode=PropulsionMode.THRUSTER_2), distinct)
    assert rates.delta_v_rate_mps2 == distinct.thruster_2.acceleration_mps2
    assert rates.net_power_w == 60.0 - 40.0 - distinct.thruster_2.power_w


@pytest.mark.parametrize(
    ("heater_on", "mode", "expected_net_power_w"),
    [
        (False, PropulsionMode.OFF, 20.0),
        (True, PropulsionMode.OFF, 10.0),
        (False, PropulsionMode.THRUSTER_1, -10.0),
        (True, PropulsionMode.THRUSTER_2, -20.0),
    ],
)
def test_power_balance(parameters, make_state, heater_on, mode, expected_net_power_w):
    rates = compute_rates(make_state(heater_on=heater_on, propulsion_mode=mode), parameters)
    assert rates.net_power_w == pytest.approx(expected_net_power_w)


def test_battery_energy_integrates_net_power_in_watt_hours(parameters, make_state):
    start = make_state(heater_on=True, propulsion_mode=PropulsionMode.THRUSTER_1)
    end = integrate(start, compute_rates(start, parameters), 3600.0, parameters)
    assert end.battery_energy_wh == pytest.approx(50.0 - 20.0)
    assert end.time_s == 3600.0


def test_battery_energy_is_capped_at_capacity_but_not_clamped_at_zero(parameters, make_state):
    full = make_state(battery_energy_wh=99.0)
    assert integrate(full, compute_rates(full, parameters), 3600.0, parameters).battery_energy_wh == 100.0
    empty = make_state(battery_energy_wh=1.0, propulsion_mode=PropulsionMode.THRUSTER_1)
    assert integrate(empty, compute_rates(empty, parameters), 3600.0, parameters).battery_energy_wh < 0.0


def test_passive_cooling_toward_sink(parameters, make_state):
    rates = compute_rates(make_state(propulsion_temperature_c=30.0), parameters)
    assert rates.temperature_rate_c_per_s == pytest.approx(-0.5 * 40.0 / 2000.0)


def test_heater_and_propulsion_raise_temperature(parameters, make_state):
    assert compute_rates(make_state(propulsion_temperature_c=-10.0), parameters).temperature_rate_c_per_s == 0.0
    heater = compute_rates(make_state(propulsion_temperature_c=-10.0, heater_on=True), parameters)
    firing = compute_rates(
        make_state(propulsion_temperature_c=-10.0, propulsion_mode=PropulsionMode.THRUSTER_1), parameters
    )
    assert heater.temperature_rate_c_per_s == pytest.approx(10.0 / 2000.0)
    assert firing.temperature_rate_c_per_s == pytest.approx(40.0 / 2000.0)


def test_integration_updates_temperature_with_one_euler_step(parameters, make_state):
    start = make_state(propulsion_temperature_c=30.0, heater_on=True, propulsion_mode=PropulsionMode.THRUSTER_1)
    end = integrate(start, compute_rates(start, parameters), 100.0, parameters)
    expected_rate_c_per_s = (10.0 + 40.0 - 0.5 * (30.0 - -10.0)) / 2000.0
    assert end.propulsion_temperature_c == pytest.approx(30.0 + expected_rate_c_per_s * 100.0)


def test_integration_advances_delta_v_and_momentum(parameters, make_state):
    start = make_state(propulsion_mode=PropulsionMode.THRUSTER_2)
    end = integrate(start, compute_rates(start, parameters), 100.0, parameters)
    assert end.delta_v_mps == pytest.approx(0.2)
    assert end.wheel_momentum_nms == pytest.approx(-1.0)
    assert end.propulsion_mode is PropulsionMode.THRUSTER_2


@pytest.mark.parametrize(
    "overrides",
    [{"battery_capacity_wh": 0.0}, {"heat_capacity_j_per_k": 0.0}, {"thermal_conductance_w_per_k": -1.0}],
)
def test_parameters_reject_invalid_values(parameters, overrides):
    with pytest.raises(ValueError, match="must"):
        replace(parameters, **overrides)


def test_safety_limits_reject_non_positive_momentum_limit():
    with pytest.raises(ValueError, match="must"):
        SafetyLimits(max_propulsion_temperature_c=50.0, min_battery_energy_wh=0.0, max_abs_wheel_momentum_nms=0.0)


@pytest.mark.parametrize("mode", [PropulsionMode.THRUSTER_1, PropulsionMode.THRUSTER_2])
def test_thruster_below_min_firing_temperature_contributes_nothing(parameters, make_state, mode):
    cold = make_state(propulsion_temperature_c=parameters.min_firing_temperature_c - 0.1, propulsion_mode=mode)
    off = make_state(propulsion_temperature_c=parameters.min_firing_temperature_c - 0.1)
    assert compute_rates(cold, parameters) == compute_rates(off, parameters)


def test_thruster_fires_at_min_firing_temperature(parameters, make_state):
    state = make_state(
        propulsion_temperature_c=parameters.min_firing_temperature_c, propulsion_mode=PropulsionMode.THRUSTER_1
    )
    assert compute_rates(state, parameters).delta_v_rate_mps2 == parameters.thruster_1.acceleration_mps2
