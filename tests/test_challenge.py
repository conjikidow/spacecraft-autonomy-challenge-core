import pytest

from spacecraft_ops_challenge.challenge import problem, scenario, scenario_names
from spacecraft_ops_challenge.commands import PropulsionMode
from spacecraft_ops_challenge.modifiers import ThrusterEfficiency
from spacecraft_ops_challenge.simulation import check_safety


def test_registry_lists_public_scenarios():
    assert scenario_names() == ("nominal", "thruster-degradation")
    for name in scenario_names():
        assert scenario(name).name == name


def test_unknown_scenario_raises_key_error_listing_names():
    with pytest.raises(KeyError, match=r"nominal.*thruster-degradation"):
        scenario("missing")


def test_all_scenarios_share_the_challenge_problem():
    for name in scenario_names():
        built = scenario(name)
        assert built.problem == problem()
        assert built.brief() == problem().brief()
        assert built.description


def test_initial_state_is_within_limits():
    challenge = problem()
    assert not check_safety(challenge.initial_state, challenge.limits)


def test_scenarios_are_built_fresh_and_equal():
    assert scenario("nominal") == scenario("nominal")


def test_nominal_thrusters_are_symmetric():
    parameters = problem().parameters
    thruster_1, thruster_2 = parameters.thruster_1, parameters.thruster_2
    assert thruster_1.acceleration_mps2 == thruster_2.acceleration_mps2
    assert thruster_1.power_w == thruster_2.power_w
    assert thruster_1.heat_w == thruster_2.heat_w
    assert thruster_1.wheel_momentum_rate_nms_per_s == -thruster_2.wheel_momentum_rate_nms_per_s > 0


def test_nominal_has_no_modifiers():
    assert scenario("nominal").modifiers == ()


def test_thruster_degradation_degrades_thruster_1_partway():
    built = scenario("thruster-degradation")
    (modifier,) = built.modifiers
    assert isinstance(modifier, ThrusterEfficiency)
    assert modifier.thruster is PropulsionMode.THRUSTER_1
    assert 0.0 < modifier.factor < 1.0
    assert 0.0 < modifier.onset_time_s < built.problem.time_limit_s
