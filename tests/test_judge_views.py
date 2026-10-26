import subprocess
import sys
from dataclasses import replace

import pytest

from spacecraft_ops_challenge.judge.dependencies import (
    Decision,
    DependencyPlan,
    DependencyReport,
    InstallAttempt,
    RequirementDecision,
)
from spacecraft_ops_challenge.judge.reporting import EvaluationResult, summarize
from spacecraft_ops_challenge.judge.runner import CaseOutcome, CaseStatus
from spacecraft_ops_challenge.judge.scoring import ScoringConfig, score_case
from spacecraft_ops_challenge.judge.views import (
    DEFAULT_MISSING_MODULE_HINT,
    dependencies_view,
    results_view,
    score_view,
)

METRICS = {
    "termination_reason": "COMPLETION_DECLARED",
    "end_time_s": 1000.0,
    "completion_declared": True,
    "safe": True,
    "safety_violations": [],
    "target_delta_v_mps": 10.0,
    "delta_v_mps": 10.1,
    "delta_v_error_mps": 0.1,
    "completion_declared_time_s": 1000.0,
    "time_limit_s": 21600.0,
    "decision_period_s": 60.0,
    "nominal_battery_capacity_wh": 100.0,
    "min_battery_energy_limit_wh": 20.0,
    "min_battery_energy_wh": 50.0,
    "min_propulsion_temperature_c": 5.0,
    "max_propulsion_temperature_c": 40.0,
    "max_abs_wheel_momentum_nms": 1.5,
}


def result(outcomes, *, participant="example", case_ids=None):
    scoring = ScoringConfig.default()
    return EvaluationResult(
        participant=participant,
        submission_sha256="0" * 64,
        skipped_entries=(),
        dependencies=DependencyReport(plan=None),
        suite_name="public",
        suite_fingerprint="f" * 64,
        case_ids=tuple(o.case_id for o in outcomes) if case_ids is None else case_ids,
        core_version="0.0.0",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
        scoring=scoring,
        summary=summarize(outcomes, scoring),
        outcomes=tuple(outcomes),
        scores=tuple(score_case(o, scoring) for o in outcomes),
    )


FULL = result(
    [
        CaseOutcome("a", CaseStatus.COMPLETED, METRICS, "", None, "", "", 1.0, 0.5),
        CaseOutcome("b", CaseStatus.LOAD_ERROR, None, "Traceback ...", "scipy", "printed\n", "", 0.1, None),
        CaseOutcome("c", CaseStatus.CRASHED, None, "RuntimeError", None, "", "warning\n", 0.1, None, "Traceback x"),
    ]
)


def test_results_view_renders_a_full_result():
    html = results_view(FULL, missing_module_hint="Provide it.").text
    for expected in (
        "public",
        "example",
        f"{FULL.summary.score:.2f}",
        "Missing modules",
        "scipy",
        "Provide it.",
        "Score components",
        "Errors (2 cases)",
        "Trusted worker error",
        "Traceback x",
        "Strategy output (2 cases)",
        "no pass threshold",
        "printed",
        "warning",
        f"{100 * FULL.scores[0].value:.2f}",
        f"{FULL.scores[0].accuracy:.4f}",
    ):
        assert expected in html
    assert "cases are shown" not in html


def test_results_view_uses_the_default_hint():
    assert "`submission/`" in DEFAULT_MISSING_MODULE_HINT
    assert "submission/" in results_view(FULL).text


def test_results_view_shows_the_stored_summary():
    stored = replace(FULL, summary=replace(FULL.summary, score=12.34))
    assert "12.34" in results_view(stored).text


def test_results_view_renders_a_filtered_result():
    outcomes = [CaseOutcome("a", CaseStatus.TIMEOUT, None, "", None, "", "", 0.1, None)]
    html = results_view(result(outcomes, participant=None, case_ids=("a", "b", "c"))).text
    for expected in ("1 of 3 cases are shown", "Errors (1 case)", "The strategy printed nothing."):
        assert expected in html
    assert "participant" not in html
    assert "Missing modules" not in html
    assert "Trusted worker error" not in html


def test_score_view_requires_a_score_per_outcome():
    with pytest.raises(ValueError, match="zip"):
        score_view(FULL.outcomes, FULL.scores[:1])


def test_dependencies_view_without_a_plan():
    html = dependencies_view(DependencyReport(plan=None)).text
    assert "pyproject.toml" in html
    assert "packages of the evaluating environment" in html


def test_dependencies_view_with_a_plan():
    plan = DependencyPlan(
        (
            RequirementDecision("numpy>=2", "numpy", Decision.SATISFIED, "the environment has 2.2.6"),
            RequirementDecision("polars>=1.20", "polars", Decision.INSTALL, "not installed"),
        )
    )
    html = dependencies_view(DependencyReport(plan, attempts=(InstallAttempt(("uv",), 0, "installed ok"),))).text
    for expected in (
        "Installed for this submission only",
        "polars&gt;=1.20",
        "Requirements (2)",
        "Installer output (1)",
    ):
        assert expected in html


def test_dependencies_view_with_nothing_to_install():
    plan = DependencyPlan((RequirementDecision("numpy", "numpy", Decision.SATISFIED, "installed"),))
    html = dependencies_view(DependencyReport(plan)).text
    assert "Nothing was installed for this submission" in html
    assert "Installer output" not in html


def test_import_without_marimo_names_the_extra():
    code = "import sys\nsys.modules['marimo'] = None\nimport spacecraft_ops_challenge.judge.views\n"
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "ImportError" in completed.stderr
    assert "spacecraft-operations-challenge-core[marimo]" in completed.stderr
