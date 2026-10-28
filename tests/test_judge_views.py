import subprocess
import sys
from dataclasses import replace

import marimo as mo
import pytest

from spacecraft_autonomy_challenge.judge.dependencies import (
    Decision,
    DependencyPlan,
    DependencyReport,
    InstallAttempt,
    RequirementDecision,
)
from spacecraft_autonomy_challenge.judge.reporting import EvaluationResult, summarize
from spacecraft_autonomy_challenge.judge.runner import CaseOutcome, CaseStatus
from spacecraft_autonomy_challenge.judge.scoring import ScoringConfig, score_case
from spacecraft_autonomy_challenge.judge.views import (
    DEFAULT_MISSING_MODULE_HINT,
    dependencies_view,
    output_view,
    results_view,
    score_view,
    scoring_view,
    text_view,
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
        "Score definition",
        "Not completed (load error, crash, timeout)",
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


def test_results_view_shows_stats_below_the_suite_score():
    html = results_view(FULL, stats=[mo.stat("28.61", label="Subset", caption="extra")]).text
    assert html.index(f"{FULL.summary.score:.2f}") < html.index("28.61") < html.index("Statistic")
    assert "Subset" in html


def test_numeric_columns_of_the_tables_are_aligned_to_the_right():
    html = results_view(FULL).text
    case_table = html[html.index("data-text-justify-columns") :]
    assert "&quot;Score&quot;:&quot;right&quot;" in case_table
    assert "&quot;CPU [s]&quot;:&quot;right&quot;" in case_table
    assert "&quot;Case&quot;:&quot;right&quot;" not in html
    assert "&quot;Status&quot;:&quot;right&quot;" not in html
    assert "&quot;Accuracy a&quot;:&quot;right&quot;" in score_view(FULL.outcomes, FULL.scores).text


def test_results_view_shows_the_summary_as_a_plain_table():
    html = results_view(FULL).text
    assert ">Statistic</th>" in html
    assert ">Mean |delta-v error|, completed runs</td>" in html


def test_scoring_view_shows_the_parameters_of_the_configuration():
    config = ScoringConfig.from_dict(
        ScoringConfig.default().to_dict()
        | {
            "accuracy": {"tolerance_fraction": 0.123456789},
            "declaration": {"undeclared_factor": 0.3},
            "weights": {"base": 0.4, "completion_time": 0.3, "battery_margin": 0.2, "cpu_time": 0.1},
            "cpu_time": {"startup_allowance_s": 7.0, "per_decision_cycle_s": 1e-5},
        }
    )
    html = scoring_view(config).text
    for expected in (r"0.4 + 0.3\,t + 0.2\,b + 0.1\,c", "0.123456789", "else 0.3", "7 + 0.00001"):
        assert expected in html
    assert "e-05" not in html


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
    code = "import sys\nsys.modules['marimo'] = None\nimport spacecraft_autonomy_challenge.judge.views\n"
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert "ImportError" in completed.stderr
    assert "spacecraft-autonomy-challenge-core[marimo]" in completed.stderr


def test_participant_strings_are_escaped():
    hostile = "x` <script>alert(1)</script> `y"
    outcome = CaseOutcome("<b>case</b>", CaseStatus.LOAD_ERROR, None, "", hostile, "", "", 0.1, None)
    hostile_result = result([outcome], participant=hostile, case_ids=("<b>case</b>",))
    summary = replace(hostile_result.summary, termination_reasons={hostile: 1})
    html = results_view(replace(hostile_result, summary=summary)).text
    assert "<script>" not in html
    assert "<b>case</b>" not in html
    assert "Termination: x` &lt;script&gt;" in html
    plan = DependencyPlan((RequirementDecision(hostile, "x", Decision.INSTALL, "missing"),))
    assert "<script>" not in dependencies_view(DependencyReport(plan)).text


def test_whitespace_output_counts_as_nothing_printed():
    outcome = CaseOutcome("a", CaseStatus.TIMEOUT, None, "", None, "\n\n", " ", 0.1, None)
    assert "The strategy printed nothing." in results_view(result([outcome], case_ids=("a",))).text


def test_dependencies_view_without_requirements():
    assert "It lists no requirements." in dependencies_view(DependencyReport(DependencyPlan(()))).text


WRAPPED = (
    '<pre class="text-xs" style="white-space: pre-wrap; overflow-wrap: anywhere; max-height: 20rem; overflow-y: auto">'
)


def test_text_view_wraps_and_escapes_text():
    html = text_view("a <script>x</script> & \"q\" 'r'\n  indented").text
    assert html.startswith(WRAPPED)
    assert "<script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt; &amp; &quot;q&quot; &#x27;r&#x27;\n  indented" in html


def test_participant_output_uses_text_view():
    outcome = CaseOutcome("a", CaseStatus.CRASHED, None, "detail", None, "out\n", "err\n", 0.1, None, "worker")
    assert output_view(outcome).text.count(WRAPPED) == 2
    assert results_view(result([outcome])).text.count(WRAPPED) == 4
    attempt = InstallAttempt(("uv",), 0, "installed ok")
    plan = DependencyPlan((RequirementDecision("x", "x", Decision.INSTALL, "missing"),))
    assert WRAPPED + "installed ok" in dependencies_view(DependencyReport(plan, attempts=(attempt,))).text
