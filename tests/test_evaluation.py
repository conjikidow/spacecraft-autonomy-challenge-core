import json
from dataclasses import replace

import pytest

from spacecraft_ops.commands import DeclareCompletion, PropulsionMode, SetPropulsionMode
from spacecraft_ops.evaluation import RunMetrics, evaluate
from spacecraft_ops.results import TerminationReason
from spacecraft_ops.simulation import run
from spacecraft_ops.strategy import Strategy

FIRE_1 = SetPropulsionMode(PropulsionMode.THRUSTER_1)
OFF = SetPropulsionMode(PropulsionMode.OFF)
ACCELERATION_MPS2 = 0.002


class Fixed(Strategy):
    """Fire thruster 1 from `start_s` to `stop_s`, then declare completion at `complete_s` (if given)."""

    def __init__(self, start_s=0.0, stop_s=500.0, complete_s=500.0):
        self.start_s = start_s
        self.stop_s = stop_s
        self.complete_s = complete_s

    def initialize(self, brief, telemetry, commander):
        commander.schedule(self.start_s, FIRE_1)
        commander.schedule(self.stop_s, OFF)
        if self.complete_s is not None:
            commander.schedule(self.complete_s, DeclareCompletion())


def metrics_of(strategy, scenario):
    return evaluate(run(strategy, scenario))


def test_declared_completion_safe_run(make_scenario):
    metrics = metrics_of(Fixed(), make_scenario())
    assert metrics.termination_reason is TerminationReason.COMPLETION_DECLARED
    assert metrics.completion_declared
    assert metrics.safe
    assert metrics.safety_violations == ()
    assert metrics.end_time_s == 500.0
    assert metrics.completion_declared_time_s == 500.0
    assert metrics.time_limit_s == 600.0
    assert metrics.target_delta_v_mps == 1.0
    assert metrics.delta_v_mps == pytest.approx(1.0)
    assert metrics.delta_v_error_mps == pytest.approx(0.0, abs=1e-9)


def test_unsafe_run(make_scenario, limits):
    scenario = make_scenario(limits=replace(limits, max_propulsion_temperature_c=21.0))
    metrics = metrics_of(Fixed(), scenario)
    assert metrics.termination_reason is TerminationReason.THERMAL_VIOLATION
    assert not metrics.safe
    assert not metrics.completion_declared
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


def test_completion_declared_time_none_when_not_declared(make_scenario):
    metrics = metrics_of(Fixed(complete_s=None), make_scenario())
    assert metrics.termination_reason is TerminationReason.TIME_LIMIT
    assert not metrics.completion_declared
    assert metrics.completion_declared_time_s is None
    assert metrics.end_time_s == 600.0


def test_declaring_completion_at_start_exposes_shortfall(make_scenario):
    metrics = metrics_of(Fixed(start_s=0.0, stop_s=0.0, complete_s=0.0), make_scenario())
    assert metrics.completion_declared
    assert metrics.completion_declared_time_s == 0.0
    assert metrics.delta_v_mps == 0.0
    assert metrics.delta_v_error_mps == -metrics.target_delta_v_mps


def test_to_dict_is_json_serializable(make_scenario, limits):
    for scenario in (make_scenario(), make_scenario(limits=replace(limits, max_propulsion_temperature_c=21.0))):
        metrics = metrics_of(Fixed(), scenario)
        data = json.loads(json.dumps(metrics.to_dict()))
        assert data["termination_reason"] == metrics.termination_reason.value
        assert data["completion_declared"] is metrics.completion_declared
        assert data["completion_declared_time_s"] == metrics.completion_declared_time_s
        assert [v["reason"] for v in data["safety_violations"]] == [v.reason.value for v in metrics.safety_violations]
        assert set(data) == set(RunMetrics.__dataclass_fields__)
