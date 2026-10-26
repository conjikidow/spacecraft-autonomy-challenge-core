import copy
import json

import pytest

from spacecraft_ops_challenge.judge.cases import EvaluationCase, Suite
from spacecraft_ops_challenge.judge.dependencies import DependencyReport
from spacecraft_ops_challenge.judge.judging import SubmissionEvaluation
from spacecraft_ops_challenge.judge.reporting import (
    RESULT_FORMAT,
    RESULT_FORMAT_VERSION,
    EvaluationResult,
    ResultFormatError,
    SuiteSummary,
    case_rows,
    missing_modules,
    problem_outcomes,
    summarize,
    summary_rows,
)
from spacecraft_ops_challenge.judge.runner import CaseOutcome, CaseStatus


def metrics(reason="COMPLETION_DECLARED", *, safe=True, error=0.0):
    return {
        "termination_reason": reason,
        "end_time_s": 1000.0,
        "completion_declared": reason == "COMPLETION_DECLARED",
        "safe": safe,
        "safety_violations": [],
        "target_delta_v_mps": 10.0,
        "delta_v_mps": 10.0 + error,
        "delta_v_error_mps": error,
        "completion_declared_time_s": 1000.0 if reason == "COMPLETION_DECLARED" else None,
        "time_limit_s": 21600.0,
        "min_battery_energy_wh": 50.0,
        "min_propulsion_temperature_c": 5.0,
        "max_propulsion_temperature_c": 40.0,
        "max_abs_wheel_momentum_nms": 1.5,
    }


def outcome(case_id, status=CaseStatus.COMPLETED, run_metrics=None, missing_module=None):
    cpu_s = 0.25 if run_metrics is not None else None
    return CaseOutcome(case_id, status, run_metrics, "detail", missing_module, "out", "err", 0.5, cpu_s)


OUTCOMES = (
    outcome("a", run_metrics=metrics(error=0.1)),
    outcome("b", run_metrics=metrics(error=-0.3)),
    outcome("c", run_metrics=metrics("TIME_LIMIT", error=-2.0)),
    outcome("d", run_metrics=metrics("THERMAL_VIOLATION", safe=False, error=-5.0)),
    outcome("e", run_metrics=metrics("STRATEGY_ERROR", error=-10.0)),
    outcome("f", CaseStatus.LOAD_ERROR, missing_module="scipy"),
    outcome("g", CaseStatus.TIMEOUT),
)


def test_summary_counts_and_statistics():
    summary = summarize(OUTCOMES)
    assert summary.cases == 7
    assert summary.completed == 5
    assert summary.not_completed == 2
    assert summary.safe == 4
    assert summary.completion_declared == 2
    assert summary.safe_and_completion_declared == 2
    assert summary.strategy_failures == 1
    assert summary.termination_reasons == {
        "COMPLETION_DECLARED": 2,
        "STRATEGY_ERROR": 1,
        "THERMAL_VIOLATION": 1,
        "TIME_LIMIT": 1,
    }
    assert summary.statuses == {"COMPLETED": 5, "LOAD_ERROR": 1, "TIMEOUT": 1}
    assert summary.mean_abs_delta_v_error_mps == pytest.approx((0.1 + 0.3 + 2.0 + 5.0 + 10.0) / 5)
    assert summary.median_abs_delta_v_error_mps == pytest.approx(2.0)
    assert summary.mean_abs_delta_v_error_safe_declared_mps == pytest.approx(0.2)
    assert summary.median_abs_delta_v_error_safe_declared_mps == pytest.approx(0.2)
    assert SuiteSummary.from_dict(json.loads(json.dumps(summary.to_dict()))) == summary


def test_summary_without_completed_runs_has_no_statistics():
    summary = summarize([outcome("x", CaseStatus.CRASHED)])
    assert summary.mean_abs_delta_v_error_mps is None
    assert summary.median_abs_delta_v_error_safe_declared_mps is None
    assert SuiteSummary.from_dict(summary.to_dict()) == summary
    rows = {row["Statistic"]: row["Value"] for row in summary_rows(summary)}
    assert rows["Mean |delta-v error|, completed runs"] == "-"
    assert rows["Not completed (load error, crash, timeout)"] == "1"


@pytest.mark.parametrize(
    "change",
    [
        {"cases": None},
        {"safe": True},
        {"statuses": ["COMPLETED"]},
        {"termination_reasons": {"TIME_LIMIT": 1.5}},
        {"mean_abs_delta_v_error_mps": "0.1"},
    ],
)
def test_malformed_summaries_are_rejected(change):
    with pytest.raises(ValueError, match="not a suite summary"):
        SuiteSummary.from_dict(summarize(OUTCOMES).to_dict() | change)


def test_incomplete_summaries_are_rejected():
    data = summarize(OUTCOMES).to_dict()
    del data["safe"]
    with pytest.raises(ValueError, match="not a suite summary"):
        SuiteSummary.from_dict(data)


def test_case_rows_show_metrics_and_never_a_verdict():
    rows = case_rows(OUTCOMES)
    assert rows[0]["Delta-v error [m/s]"] == "+0.1000"
    assert rows[0]["CPU [s]"] == "0.25"
    assert rows[3]["Safe"] == "no"
    assert rows[5]["Status"] == "LOAD_ERROR"
    assert rows[5]["Termination"] == "-"
    assert rows[5]["CPU [s]"] == "-"
    assert len({tuple(row) for row in rows}) == 1
    text = json.dumps(rows).upper()
    assert "PASS" not in text
    assert "FAIL" not in text


def test_problem_outcomes_and_missing_modules():
    assert [o.case_id for o in problem_outcomes(OUTCOMES)] == ["e", "f", "g"]
    assert missing_modules(OUTCOMES) == ("scipy",)


SUITE = Suite("example", tuple(EvaluationCase.of(o.case_id, {"secret": o.case_id * 3}) for o in OUTCOMES))
EVALUATION = SubmissionEvaluation(
    suite=SUITE,
    outcomes=OUTCOMES,
    submission_sha256="0" * 64,
    skipped_entries=("README.md",),
    dependencies=DependencyReport(plan=None),
    started_at="2026-01-01T00:00:00+00:00",
    finished_at="2026-01-01T00:01:00+00:00",
)


def test_result_records_the_evaluation_without_payloads():
    result = EvaluationResult.from_evaluation(EVALUATION, participant="Team A")
    assert result.summary == summarize(OUTCOMES)
    assert result.case_ids == ("a", "b", "c", "d", "e", "f", "g")
    document = result.to_dict()
    assert list(document) == [
        "format",
        "format_version",
        "participant",
        "submission",
        "dependencies",
        "suite",
        "core_version",
        "started_at",
        "finished_at",
        "summary",
        "cases",
    ]
    assert document["format"] == RESULT_FORMAT
    assert document["format_version"] == RESULT_FORMAT_VERSION
    assert document["submission"] == {"sha256": "0" * 64, "skipped_entries": ["README.md"]}
    assert document["suite"]["fingerprint"] == SUITE.fingerprint
    assert "aaa" not in json.dumps(document)
    assert "score" not in json.dumps(document).lower()
    assert EvaluationResult.from_evaluation(EVALUATION).participant is None


def test_results_round_trip_through_dictionaries_and_json():
    result = EvaluationResult.from_evaluation(EVALUATION, participant="Team A")
    assert EvaluationResult.from_dict(result.to_dict()) == result
    assert EvaluationResult.from_dict(json.loads(json.dumps(result.to_dict()))) == result
    text = result.to_json()
    assert text.endswith("}\n")
    assert json.loads(text) == result.to_dict()
    assert EvaluationResult.from_json(text) == result
    assert EvaluationResult.from_json(text.encode()) == result
    assert EvaluationResult.from_json(json.dumps(result.to_dict(), separators=(",", ":"))) == result


def test_filtered_documents_load_and_keep_their_stored_summary():
    result = EvaluationResult.from_evaluation(EVALUATION, participant="Team A")
    document = result.to_dict()
    document["participant"] = None
    document["cases"] = [
        case | {"stdout": "", "stderr": "", "detail": ""} for case in document["cases"] if case["case_id"] in ("a", "b")
    ]
    without_worker_error = json.loads(json.dumps(document))
    for case in without_worker_error["cases"]:
        del case["worker_error"]
    assert EvaluationResult.from_dict(without_worker_error).to_dict() == document
    loaded = EvaluationResult.from_json(json.dumps(document))
    assert loaded.participant is None
    assert [o.case_id for o in loaded.outcomes] == ["a", "b"]
    assert all(o.stdout == o.stderr == o.detail == "" for o in loaded.outcomes)
    assert loaded.case_ids == result.case_ids
    assert loaded.summary == result.summary != summarize(loaded.outcomes)
    assert loaded.to_dict() == document


def test_other_formats_and_versions_are_rejected():
    document = EvaluationResult.from_evaluation(EVALUATION).to_dict()
    for format_name in ("other/result", None):
        with pytest.raises(ResultFormatError, match="not a result document"):
            EvaluationResult.from_dict(document | {"format": format_name})
    for version in (2, 0, "1", 1.0, True, None):
        with pytest.raises(ResultFormatError, match="unsupported result format version"):
            EvaluationResult.from_dict(document | {"format_version": version})
    without_format = dict(document)
    del without_format["format"]
    with pytest.raises(ResultFormatError):
        EvaluationResult.from_dict(without_format)


def _set(document, path, value):
    *parents, key = path
    target = document
    for parent in parents:
        target = target[parent]
    if value is _DELETE:
        del target[key]
    else:
        target[key] = value


_DELETE = object()


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("participant",), 42),
        (("participant",), _DELETE),
        (("submission",), "0" * 64),
        (("submission", "sha256"), None),
        (("submission", "skipped_entries"), "README.md"),
        (("dependencies",), None),
        (("dependencies", "plan"), _DELETE),
        (("suite", "case_ids"), [1, 2]),
        (("suite", "fingerprint"), _DELETE),
        (("core_version",), None),
        (("started_at",), _DELETE),
        (("summary",), []),
        (("summary", "cases"), "7"),
        (("cases",), {}),
        (("cases", 0), "a"),
        (("cases", 0, "status"), "PASSED"),
        (("cases", 0, "stdout"), _DELETE),
    ],
)
def test_malformed_documents_are_rejected(path, value):
    document = copy.deepcopy(EvaluationResult.from_evaluation(EVALUATION).to_dict())
    _set(document, path, value)
    with pytest.raises(ResultFormatError, match="malformed result document"):
        EvaluationResult.from_dict(document)


@pytest.mark.parametrize("text", ["", "{", "[]", "null", '"result"', b"\xff"])
def test_text_that_is_not_a_result_document_is_rejected(text):
    with pytest.raises(ResultFormatError):
        EvaluationResult.from_json(text)


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["summary"].update(mean_abs_delta_v_error_mps=10**400),
        lambda d: d["cases"][0].update(duration_s=10**400),
        lambda d: d["cases"][0].update(metrics={}),
        lambda d: d["cases"][0]["metrics"].update(termination_reason=5),
        lambda d: d["cases"][0]["metrics"].update(delta_v_error_mps="x"),
        lambda d: d["cases"][0]["metrics"].update(safe=1),
        lambda d: d["cases"][0]["metrics"].update(end_time_s=True),
    ],
)
def test_malformed_values_are_format_errors(change):
    document = EvaluationResult.from_evaluation(EVALUATION).to_dict()
    assert document["cases"][0]["metrics"] is not None
    change(document)
    with pytest.raises(ResultFormatError):
        EvaluationResult.from_json(json.dumps(document))


def test_deeply_nested_json_is_a_format_error():
    with pytest.raises(ResultFormatError):
        EvaluationResult.from_json("[" * 100_000 + "]" * 100_000)
