import copy
import json
import tomllib
from importlib.resources import files

import pytest

from spacecraft_ops_challenge.judge.runner import CaseOutcome, CaseStatus
from spacecraft_ops_challenge.judge.scoring import (
    SCORING_CONFIG_VERSION,
    ZERO_SCORE,
    AccuracyParameters,
    CaseScore,
    CpuTimeParameters,
    DeclarationParameters,
    ScoreWeights,
    ScoringConfig,
    ScoringConfigError,
    score_case,
    suite_score,
)

DEFAULT_TOML = """\
version = 1
[accuracy]
tolerance_fraction = 0.1
[declaration]
undeclared_factor = 0.5
[weights]
base = 0.70
completion_time = 0.15
battery_margin = 0.10
cpu_time = 0.05
[cpu_time]
startup_allowance_s = 5.0
per_decision_cycle_s = 0.1
"""

CONFIG = ScoringConfig.from_toml(DEFAULT_TOML)
CPU_BUDGET_S = 5.0 + 0.1 * 21600.0 / 60.0
"""Budget of `metrics()`: start-up allowance plus 360 decision cycles."""


def metrics(reason="COMPLETION_DECLARED", **overrides):
    """Metrics of a 10 m/s, 21600 s problem with a 100 Wh nominal battery and a 20 Wh limit."""
    declared = reason == "COMPLETION_DECLARED"
    return {
        "termination_reason": reason,
        "end_time_s": 5400.0,
        "completion_declared": declared,
        "safe": True,
        "safety_violations": [],
        "target_delta_v_mps": 10.0,
        "delta_v_mps": 10.0,
        "delta_v_error_mps": 0.0,
        "completion_declared_time_s": 5400.0 if declared else None,
        "time_limit_s": 21600.0,
        "decision_period_s": 60.0,
        "nominal_battery_capacity_wh": 100.0,
        "min_battery_energy_limit_wh": 20.0,
        "min_battery_energy_wh": 60.0,
        "min_propulsion_temperature_c": 5.0,
        "max_propulsion_temperature_c": 40.0,
        "max_abs_wheel_momentum_nms": 1.5,
    } | overrides


def outcome(run_metrics=None, *, status=CaseStatus.COMPLETED, cpu_s=CPU_BUDGET_S / 2):
    return CaseOutcome("case", status, run_metrics, "", None, "", "", 1.0, cpu_s)


def test_default_config_is_the_shipped_file():
    assert ScoringConfig.default() == CONFIG
    assert CONFIG.accuracy == AccuracyParameters(tolerance_fraction=0.1)
    assert CONFIG.declaration == DeclarationParameters(undeclared_factor=0.5)
    assert CONFIG.weights == ScoreWeights(base=0.7, completion_time=0.15, battery_margin=0.1, cpu_time=0.05)
    assert CONFIG.cpu_time == CpuTimeParameters(startup_allowance_s=5.0, per_decision_cycle_s=0.1)
    shipped = files("spacecraft_ops_challenge.judge").joinpath("scoring.toml").read_text(encoding="utf-8")
    assert tomllib.loads(shipped) == CONFIG.to_dict()


def test_config_round_trips_through_dictionaries_json_and_files(tmp_path):
    data = CONFIG.to_dict()
    assert data["version"] == SCORING_CONFIG_VERSION
    assert list(data) == ["version", "accuracy", "declaration", "weights", "cpu_time"]
    assert ScoringConfig.from_dict(json.loads(json.dumps(data))) == CONFIG
    path = tmp_path / "scoring.toml"
    path.write_text(DEFAULT_TOML, encoding="utf-8")
    assert ScoringConfig.from_toml(path) == CONFIG
    assert ScoringConfig.from_toml(DEFAULT_TOML.encode()) == CONFIG


def test_a_missing_config_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        ScoringConfig.from_toml(tmp_path / "missing.toml")


def _changed(change):
    data = copy.deepcopy(CONFIG.to_dict())
    change(data)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d.update(version=2), "unsupported scoring configuration version 2"),
        (lambda d: d.update(version=True), "unsupported scoring configuration version"),
        (lambda d: d.update(version="1"), "unsupported scoring configuration version"),
        (lambda d: d.pop("version"), "unsupported scoring configuration version None"),
        (lambda d: d.update(extra={}), "unknown keys in the scoring configuration: extra"),
        (lambda d: d.pop("cpu_time"), "missing keys in the scoring configuration: cpu_time"),
        (lambda d: d.update(weights=0.7), "section weights must be a table"),
        (lambda d: d["accuracy"].update(tolerance=0.1), "unknown keys in section accuracy: tolerance"),
        (lambda d: d["weights"].pop("cpu_time"), "missing keys in section weights: cpu_time"),
        (lambda d: d["accuracy"].update(tolerance_fraction=0.0), "tolerance_fraction must be positive"),
        (lambda d: d["accuracy"].update(tolerance_fraction=-0.1), "tolerance_fraction must be positive"),
        (lambda d: d["accuracy"].update(tolerance_fraction="0.1"), "tolerance_fraction must be a finite number"),
        (lambda d: d["accuracy"].update(tolerance_fraction=True), "tolerance_fraction must be a finite number"),
        (lambda d: d["accuracy"].update(tolerance_fraction=float("inf")), "must be a finite number"),
        (lambda d: d["accuracy"].update(tolerance_fraction=float("nan")), "must be a finite number"),
        (lambda d: d["declaration"].update(undeclared_factor=1.5), "undeclared_factor must be from 0 to 1"),
        (lambda d: d["declaration"].update(undeclared_factor=-0.1), "undeclared_factor must be from 0 to 1"),
        (lambda d: d["weights"].update(base=0.8), "weights must sum to 1"),
        (lambda d: d["weights"].update(base=0.75, cpu_time=-0.05), "weight cpu_time must not be negative"),
        (lambda d: d["cpu_time"].update(startup_allowance_s=0.0), "startup_allowance_s must be positive"),
        (lambda d: d["cpu_time"].update(per_decision_cycle_s=-1.0), "per_decision_cycle_s must be positive"),
    ],
)
def test_invalid_configs_are_rejected(change, message):
    with pytest.raises(ScoringConfigError, match=message):
        ScoringConfig.from_dict(_changed(change))


def test_weights_are_checked_with_a_small_tolerance():
    assert ScoreWeights(base=0.1, completion_time=0.2, battery_margin=0.3, cpu_time=0.4).base == 0.1
    assert ScoreWeights(base=1.0 + 1e-12, completion_time=0.0, battery_margin=0.0, cpu_time=0.0).base > 1
    with pytest.raises(ScoringConfigError, match="weights must sum to 1"):
        ScoreWeights(base=1.0 + 1e-6, completion_time=0.0, battery_margin=0.0, cpu_time=0.0)
    assert DeclarationParameters(undeclared_factor=0).undeclared_factor == 0
    assert DeclarationParameters(undeclared_factor=1).undeclared_factor == 1


@pytest.mark.parametrize(
    "text",
    [
        "version = ",
        "version = 2\n" + DEFAULT_TOML.split("\n", 1)[1],
        DEFAULT_TOML + "[extra]\nvalue = 1\n",
        DEFAULT_TOML.replace("cpu_time = 0.05", "cpu_time = 0.05\ncpu = 0.0"),
        b"\xff",
        "[]",
    ],
)
def test_invalid_toml_is_rejected(text):
    with pytest.raises(ScoringConfigError):
        ScoringConfig.from_toml(text)


def test_scoring_config_error_is_a_value_error():
    assert issubclass(ScoringConfigError, ValueError)
    with pytest.raises(ScoringConfigError, match="must be a mapping"):
        ScoringConfig.from_dict([])


def test_cpu_budget():
    assert CONFIG.cpu_time.budget_s(21600.0, 60.0) == pytest.approx(CPU_BUDGET_S) == pytest.approx(41.0)


def test_a_perfect_run_scores_every_term():
    score = score_case(outcome(metrics()), CONFIG)
    assert score.gate == 1.0
    assert score.accuracy == 1.0
    assert score.declaration == 1.0
    assert score.completion_time == pytest.approx(0.75)
    assert score.battery_margin == pytest.approx(0.5)
    assert score.cpu_time == 1.0
    assert score.value == pytest.approx(0.70 + 0.15 * 0.75 + 0.10 * 0.5 + 0.05 * 1.0)


@pytest.mark.parametrize(
    "run_metrics",
    [
        metrics("THERMAL_VIOLATION", safe=False),
        metrics(safe=False),
        metrics("STRATEGY_ERROR"),
        metrics("INVALID_COMMAND"),
    ],
)
def test_unsafe_runs_and_strategy_failures_score_0(run_metrics):
    score = score_case(outcome(run_metrics), CONFIG)
    assert score.gate == 0.0
    assert score.value == 0.0
    assert score.accuracy == 1.0
    assert score.cpu_time == 1.0


@pytest.mark.parametrize("status", [CaseStatus.LOAD_ERROR, CaseStatus.CRASHED, CaseStatus.TIMEOUT])
def test_cases_without_metrics_score_0(status):
    assert score_case(outcome(status=status, cpu_s=None), CONFIG) == ZERO_SCORE
    assert ZERO_SCORE.value == ZERO_SCORE.gate == ZERO_SCORE.cpu_time == 0.0


def test_a_status_other_than_completed_closes_the_gate():
    assert score_case(outcome(metrics(), status=CaseStatus.CRASHED), CONFIG).value == 0.0


@pytest.mark.parametrize(
    ("error_mps", "accuracy"),
    [(0.0, 1.0), (0.25, 0.75), (-0.25, 0.75), (0.5, 0.5), (-1.0, 0.0), (1.0, 0.0), (3.0, 0.0)],
)
def test_accuracy_falls_linearly_to_the_tolerance(error_mps, accuracy):
    score = score_case(outcome(metrics(delta_v_error_mps=error_mps, delta_v_mps=10.0 + error_mps)), CONFIG)
    assert score.accuracy == pytest.approx(accuracy)
    assert score.value == pytest.approx(accuracy * score_case(outcome(metrics()), CONFIG).value)


def test_declaring_completion_early_with_a_large_error_scores_0():
    early = metrics(
        end_time_s=0.0,
        completion_declared_time_s=0.0,
        delta_v_mps=0.0,
        delta_v_error_mps=-10.0,
        min_battery_energy_wh=80.0,
    )
    score = score_case(outcome(early), CONFIG)
    assert score.gate == 1.0
    assert score.completion_time == 1.0
    assert score.accuracy == 0.0
    assert score.value == 0.0


def test_a_zero_target_needs_an_exact_delta_v():
    assert score_case(outcome(metrics(target_delta_v_mps=0.0, delta_v_error_mps=0.0)), CONFIG).accuracy == 1.0
    assert score_case(outcome(metrics(target_delta_v_mps=0.0, delta_v_error_mps=0.01)), CONFIG).accuracy == 0.0


def test_undeclared_runs_get_the_undeclared_factor_and_no_time_credit():
    score = score_case(outcome(metrics("TIME_LIMIT", end_time_s=21600.0)), CONFIG)
    assert score.gate == 1.0
    assert score.declaration == 0.5
    assert score.completion_time == 0.0
    assert score.value == pytest.approx(0.5 * (0.70 + 0.10 * 0.5 + 0.05 * 1.0))


@pytest.mark.parametrize(("declared_s", "term"), [(0.0, 1.0), (10800.0, 0.5), (21600.0, 0.0)])
def test_completion_time_term(declared_s, term):
    run_metrics = metrics(end_time_s=declared_s, completion_declared_time_s=declared_s)
    assert score_case(outcome(run_metrics), CONFIG).completion_time == pytest.approx(term)


@pytest.mark.parametrize(
    ("min_battery_wh", "term"),
    [(20.0, 0.0), (15.0, 0.0), (60.0, 0.5), (100.0, 1.0), (120.0, 1.0)],
)
def test_battery_margin_is_clipped_to_0_and_1(min_battery_wh, term):
    score = score_case(outcome(metrics(min_battery_energy_wh=min_battery_wh)), CONFIG)
    assert score.battery_margin == pytest.approx(term)


def test_battery_margin_without_a_span_is_0():
    run_metrics = metrics(nominal_battery_capacity_wh=20.0, min_battery_energy_wh=20.0)
    assert score_case(outcome(run_metrics), CONFIG).battery_margin == 0.0


@pytest.mark.parametrize(
    ("cpu_s", "term"),
    [
        (None, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (CPU_BUDGET_S, 1.0),
        (2 * CPU_BUDGET_S, 0.5),
        (10 * CPU_BUDGET_S, 0.1),
    ],
)
def test_cpu_time_term(cpu_s, term):
    score = score_case(outcome(metrics(), cpu_s=cpu_s), CONFIG)
    assert score.cpu_time == pytest.approx(term)
    full = score_case(outcome(metrics()), CONFIG).value
    assert score.value == pytest.approx(full - 0.05 * (1.0 - term))


def test_cpu_budget_scales_with_decision_cycles():
    run_metrics = metrics(
        time_limit_s=600.0, decision_period_s=30.0, end_time_s=300.0, completion_declared_time_s=300.0
    )
    assert score_case(outcome(run_metrics, cpu_s=14.0), CONFIG).cpu_time == pytest.approx((5.0 + 0.1 * 20) / 14.0)


def test_weights_and_parameters_come_from_the_config():
    data = CONFIG.to_dict()
    data["weights"] = {"base": 0.0, "completion_time": 0.0, "battery_margin": 1.0, "cpu_time": 0.0}
    data["declaration"]["undeclared_factor"] = 0.0
    config = ScoringConfig.from_dict(data)
    assert score_case(outcome(metrics()), config).value == pytest.approx(0.5)
    assert score_case(outcome(metrics("TIME_LIMIT")), config).value == 0.0


def test_suite_score_is_100_times_the_mean_over_all_cases():
    full = score_case(outcome(metrics()), CONFIG)
    scores = [full, ZERO_SCORE, score_case(outcome(metrics("TIME_LIMIT")), CONFIG)]
    assert suite_score(scores) == pytest.approx(100 * (full.value + scores[2].value) / 3)
    assert suite_score(iter([full])) == pytest.approx(100 * full.value)
    assert suite_score([ZERO_SCORE, ZERO_SCORE]) == 0.0
    assert suite_score([]) == 0.0
    perfect = CaseScore(1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    assert suite_score([perfect, perfect]) == 100.0


def test_case_scores_round_trip_and_reject_malformed_data():
    score = score_case(outcome(metrics()), CONFIG)
    assert CaseScore.from_dict(json.loads(json.dumps(score.to_dict()))) == score
    assert list(score.to_dict()) == [
        "value",
        "gate",
        "accuracy",
        "declaration",
        "completion_time",
        "battery_margin",
        "cpu_time",
    ]
    assert CaseScore.from_dict(score.to_dict() | {"gate": 1}).gate == 1.0
    for change in ({"value": 1.5}, {"value": -0.1}, {"gate": True}, {"cpu_time": None}, {"accuracy": "1"}):
        with pytest.raises(ValueError, match="not a case score"):
            CaseScore.from_dict(score.to_dict() | change)
    data = score.to_dict()
    del data["declaration"]
    with pytest.raises(ValueError, match="not a case score"):
        CaseScore.from_dict(data)
    with pytest.raises(ValueError, match="not a case score"):
        CaseScore.from_dict([])
