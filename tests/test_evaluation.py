import json
from dataclasses import replace

import pytest

from spacecraft_ops.commands import CompleteMission, PropulsionMode, SetPropulsionMode
from spacecraft_ops.evaluation import RunMetrics, ScoreWeights, evaluate, reference_score
from spacecraft_ops.results import TerminationReason
from spacecraft_ops.simulation import run
from spacecraft_ops.strategy import Strategy

FIRE_1 = SetPropulsionMode(PropulsionMode.THRUSTER_1)
OFF = SetPropulsionMode(PropulsionMode.OFF)
ACCELERATION_MPS2 = 0.002


class Fixed(Strategy):
    """Fire thruster 1 from `start_s` to `stop_s`, then complete the mission at `complete_s` (if given)."""

    def __init__(self, start_s=0.0, stop_s=500.0, complete_s=500.0):
        self.start_s = start_s
        self.stop_s = stop_s
        self.complete_s = complete_s

    def initialize(self, brief, telemetry, commander):
        commander.schedule(self.start_s, FIRE_1)
        commander.schedule(self.stop_s, OFF)
        if self.complete_s is not None:
            commander.schedule(self.complete_s, CompleteMission())


def metrics_of(strategy, scenario):
    return evaluate(run(strategy, scenario))


def test_completed_safe_run(make_scenario):
    metrics = metrics_of(Fixed(), make_scenario())
    assert metrics.termination_reason is TerminationReason.MISSION_COMPLETE
    assert metrics.completed
    assert metrics.safe
    assert metrics.safety_violations == ()
    assert metrics.end_time_s == 500.0
    assert metrics.completion_time_s == 500.0
    assert metrics.time_limit_s == 600.0
    assert metrics.target_delta_v_mps == 1.0
    assert metrics.delta_v_mps == pytest.approx(1.0)
    assert metrics.delta_v_error_mps == pytest.approx(0.0, abs=1e-9)


def test_unsafe_run(make_scenario, limits):
    scenario = make_scenario(limits=replace(limits, max_propulsion_temperature_c=21.0))
    metrics = metrics_of(Fixed(), scenario)
    assert metrics.termination_reason is TerminationReason.THERMAL_VIOLATION
    assert not metrics.safe
    assert not metrics.completed
    assert len(metrics.safety_violations) >= 1
    assert metrics.safety_violations[0].reason is TerminationReason.THERMAL_VIOLATION


def test_extremes_come_from_trajectory(make_scenario):
    result = run(Fixed(stop_s=200.0, complete_s=400.0), make_scenario())
    metrics = evaluate(result)
    states = (*result.trajectory, result.final_state)
    assert metrics.max_propulsion_temperature_c == max(s.propulsion_temperature_c for s in states)
    assert metrics.min_battery_energy_wh == min(s.battery_energy_wh for s in states)
    assert metrics.max_abs_wheel_momentum_nms == pytest.approx(0.01 * 200.0)
    assert metrics.min_propulsion_temperature_c == 20.0
    assert metrics.max_propulsion_temperature_c > 20.0
    assert metrics.max_propulsion_temperature_c > result.final_state.propulsion_temperature_c


def test_error_sign(make_scenario):
    under = metrics_of(Fixed(stop_s=250.0, complete_s=250.0), make_scenario())
    over = metrics_of(Fixed(stop_s=550.0, complete_s=550.0), make_scenario())
    assert under.delta_v_error_mps == pytest.approx(-0.5)
    assert over.delta_v_error_mps == pytest.approx(0.1)


def test_completion_time_none_when_not_completed(make_scenario):
    metrics = metrics_of(Fixed(complete_s=None), make_scenario())
    assert metrics.termination_reason is TerminationReason.TIME_LIMIT
    assert not metrics.completed
    assert metrics.completion_time_s is None
    assert metrics.end_time_s == 600.0


def test_score_zero_for_unsafe_or_incomplete(make_scenario, limits):
    unsafe = metrics_of(Fixed(), make_scenario(limits=replace(limits, max_propulsion_temperature_c=21.0)))
    incomplete = metrics_of(Fixed(complete_s=None), make_scenario())
    assert reference_score(unsafe) == 0.0
    assert reference_score(incomplete) == 0.0


def test_score_of_exact_run(make_scenario):
    metrics = metrics_of(Fixed(), make_scenario())
    assert reference_score(metrics) == pytest.approx(0.8 * 1.0 + 0.2 * (1.0 - 500.0 / 600.0))


def test_score_ordering(make_scenario):
    exact = reference_score(metrics_of(Fixed(), make_scenario()))
    inaccurate = reference_score(metrics_of(Fixed(stop_s=450.0, complete_s=450.0), make_scenario()))
    assert exact > inaccurate
    slow = reference_score(metrics_of(Fixed(start_s=100.0, stop_s=600.0 - 1.0, complete_s=599.0), make_scenario()))
    fast = reference_score(metrics_of(Fixed(), make_scenario()))
    assert fast > slow


def test_score_with_zero_target(make_scenario):
    scenario = make_scenario(target_delta_v_mps=0.0)
    exact = metrics_of(Fixed(stop_s=0.0, complete_s=0.0), scenario)
    off = metrics_of(Fixed(stop_s=10.0, complete_s=10.0), scenario)
    assert exact.delta_v_error_mps == 0.0
    assert reference_score(exact, ScoreWeights(accuracy=1.0, time=0.0)) == 1.0
    assert reference_score(off, ScoreWeights(accuracy=1.0, time=0.0)) == 0.0


def test_score_is_clamped_to_unit_interval(make_scenario):
    metrics = metrics_of(Fixed(stop_s=590.0, complete_s=590.0), make_scenario(target_delta_v_mps=0.1))
    assert 0.0 <= reference_score(metrics) <= 1.0


def test_custom_weights(make_scenario):
    metrics = metrics_of(Fixed(), make_scenario())
    assert reference_score(metrics, ScoreWeights(accuracy=1.0, time=0.0)) == pytest.approx(1.0)
    assert reference_score(metrics, ScoreWeights(accuracy=0.0, time=3.0)) == pytest.approx(1.0 - 500.0 / 600.0)


def test_weights_validation():
    with pytest.raises(ValueError, match="negative"):
        ScoreWeights(accuracy=-0.1, time=1.0)
    with pytest.raises(ValueError, match="negative"):
        ScoreWeights(accuracy=1.0, time=-0.1)
    with pytest.raises(ValueError, match="positive sum"):
        ScoreWeights(accuracy=0.0, time=0.0)
    assert ScoreWeights().accuracy == 0.8
    assert ScoreWeights().time == 0.2


def test_to_dict_is_json_serializable(make_scenario, limits):
    for scenario in (make_scenario(), make_scenario(limits=replace(limits, max_propulsion_temperature_c=21.0))):
        metrics = metrics_of(Fixed(), scenario)
        data = json.loads(json.dumps(metrics.to_dict()))
        assert data["termination_reason"] == metrics.termination_reason.value
        assert data["completed"] is metrics.completed
        assert data["completion_time_s"] == metrics.completion_time_s
        assert [v["reason"] for v in data["safety_violations"]] == [v.reason.value for v in metrics.safety_violations]
        assert set(data) == set(RunMetrics.__dataclass_fields__)
