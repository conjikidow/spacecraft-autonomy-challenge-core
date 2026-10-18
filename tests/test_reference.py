import pytest

from spacecraft_ops.commands import PropulsionMode, SetHeater, SetPropulsionMode
from spacecraft_ops.modifiers import ThrusterEfficiency
from spacecraft_ops.reference import (
    nominal_initial_state,
    nominal_limits,
    nominal_parameters,
    reference_scenario,
    reference_scenario_names,
)
from spacecraft_ops.results import TerminationReason
from spacecraft_ops.simulation import check_safety, run
from spacecraft_ops.strategy import Strategy

FIRE_1 = SetPropulsionMode(PropulsionMode.THRUSTER_1)
FIRE_2 = SetPropulsionMode(PropulsionMode.THRUSTER_2)


class Scheduled(Strategy):
    """Schedules a fixed list of `(time_s, command)` pairs at time 0."""

    def __init__(self, *items):
        self.items = items

    def initialize(self, brief, telemetry, commander):
        for time_s, command in self.items:
            commander.schedule(time_s, command)


def test_registry_lists_reference_scenarios():
    assert reference_scenario_names() == ("nominal", "thruster-degradation")
    for name in reference_scenario_names():
        assert reference_scenario(name).name == name


def test_unknown_scenario_raises_key_error_listing_names():
    with pytest.raises(KeyError, match=r"nominal.*thruster-degradation"):
        reference_scenario("missing")


def test_reference_scenarios_share_the_nominal_configuration():
    for name in reference_scenario_names():
        scenario = reference_scenario(name)
        assert scenario.parameters == nominal_parameters()
        assert scenario.limits == nominal_limits()
        assert scenario.initial_state == nominal_initial_state()
        assert scenario.brief().nominal_parameters == nominal_parameters()
        assert scenario.description
        assert not check_safety(scenario.initial_state, scenario.limits)


def test_reference_scenarios_are_built_fresh_and_equal():
    assert reference_scenario("nominal") == reference_scenario("nominal")


def test_nominal_thrusters_are_symmetric():
    parameters = nominal_parameters()
    thruster_1, thruster_2 = parameters.thruster_1, parameters.thruster_2
    assert thruster_1.acceleration_mps2 == thruster_2.acceleration_mps2
    assert thruster_1.power_w == thruster_2.power_w
    assert thruster_1.heat_w == thruster_2.heat_w
    assert thruster_1.wheel_momentum_rate_nms_per_s == -thruster_2.wheel_momentum_rate_nms_per_s > 0


def test_nominal_has_no_modifiers():
    assert reference_scenario("nominal").modifiers == ()


def test_thruster_degradation_degrades_thruster_1_partway():
    scenario = reference_scenario("thruster-degradation")
    (modifier,) = scenario.modifiers
    assert isinstance(modifier, ThrusterEfficiency)
    assert modifier.thruster is PropulsionMode.THRUSTER_1
    assert 0.0 < modifier.factor < 1.0
    assert 0.0 < modifier.onset_time_s < scenario.time_limit_s


def test_continuous_single_thruster_firing_violates_momentum_limit():
    scenario = reference_scenario("nominal")
    result = run(Scheduled((0.0, FIRE_1)), scenario)
    assert result.termination.reason is TerminationReason.MOMENTUM_VIOLATION
    assert result.final_state.delta_v_mps < scenario.target_delta_v_mps


def test_continuous_alternating_firing_overheats():
    scenario = reference_scenario("nominal")
    switches = [(time_s, FIRE_1 if index % 2 == 0 else FIRE_2) for index, time_s in enumerate(range(0, 21600, 1000))]
    result = run(Scheduled(*switches), scenario)
    assert result.termination.reason is TerminationReason.THERMAL_VIOLATION
    assert result.final_state.propulsion_temperature_c > scenario.limits.max_propulsion_temperature_c
    assert result.final_state.delta_v_mps < scenario.target_delta_v_mps
    assert all(
        abs(state.wheel_momentum_nms) < scenario.limits.max_abs_wheel_momentum_nms / 2 for state in result.trajectory
    )


def test_idle_without_heater_undercools():
    scenario = reference_scenario("nominal")
    result = run(Strategy(), scenario)
    assert result.termination.reason is TerminationReason.THERMAL_VIOLATION
    assert result.final_state.propulsion_temperature_c < scenario.limits.min_propulsion_temperature_c
    assert result.termination.time_s < scenario.time_limit_s


def test_idle_with_heater_stays_safe_until_time_limit():
    result = run(Scheduled((0.0, SetHeater(True))), reference_scenario("nominal"))
    assert result.termination.reason is TerminationReason.TIME_LIMIT
    assert not result.safety_violations
