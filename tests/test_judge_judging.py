import hashlib
import json
import os
import tempfile

import pytest
from judge_support import DECLARE_AT_START, PROVIDER, case, zip_bytes

import spacecraft_ops_challenge
from spacecraft_ops_challenge.challenge import scenario_names
from spacecraft_ops_challenge.judge import judging
from spacecraft_ops_challenge.judge.cases import CaseError, ScenarioProvider, Suite
from spacecraft_ops_challenge.judge.dependencies import DependencyError
from spacecraft_ops_challenge.judge.judging import check_submission, evaluate_submission
from spacecraft_ops_challenge.judge.public_scenarios import public_suite
from spacecraft_ops_challenge.judge.reporting import EvaluationResult
from spacecraft_ops_challenge.judge.runner import CaseStatus
from spacecraft_ops_challenge.judge.submission import SubmissionError

SECRET_FACTOR = 0.123456
SUITE = Suite(
    "example",
    (
        case("case-001", 987654321, {"type": "ThrusterEfficiency", "thruster": "THRUSTER_1", "factor": SECRET_FACTOR}),
        case("case-002", 876543219),
    ),
)


def test_evaluate_submission_runs_every_case_and_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    archive = zip_bytes({"submission/strategy.py": DECLARE_AT_START, "extra.txt": "x"})
    seen = []

    def on_case_done(outcome):
        assert [path.name.startswith("spacecraft-ops-submission-") for path in tmp_path.iterdir()] == [True]
        seen.append(outcome)

    evaluation = evaluate_submission(archive, SUITE, PROVIDER, on_case_done=on_case_done)
    assert [o.case_id for o in evaluation.outcomes] == ["case-001", "case-002"]
    assert seen == list(evaluation.outcomes)
    assert all(o.status is CaseStatus.COMPLETED for o in evaluation.outcomes)
    assert evaluation.submission_sha256 == hashlib.sha256(archive).hexdigest()
    assert evaluation.skipped_entries == ("extra.txt",)
    assert evaluation.dependencies.plan is None
    assert evaluation.started_at <= evaluation.finished_at
    assert list(tmp_path.iterdir()) == []


def test_invalid_archives_raise_before_running(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with pytest.raises(SubmissionError):
        evaluate_submission(zip_bytes({"strategy.py": DECLARE_AT_START}), SUITE, PROVIDER)
    assert list(tmp_path.iterdir()) == []


def test_result_document_is_complete_and_hides_case_definitions():
    evaluation = evaluate_submission(zip_bytes({"submission/strategy.py": DECLARE_AT_START}), SUITE, PROVIDER)
    result = EvaluationResult.from_evaluation(evaluation, participant="Team A")
    text = result.to_json()
    document = json.loads(text)
    assert document == result.to_dict()
    assert EvaluationResult.from_json(text) == result
    assert document["participant"] == "Team A"
    assert document["suite"] == {
        "name": "example",
        "fingerprint": SUITE.fingerprint,
        "case_ids": ["case-001", "case-002"],
    }
    assert document["summary"]["cases"] == 2
    assert document["summary"]["completion_declared"] == 2
    assert [case["metrics"]["completion_declared"] for case in document["cases"]] == [True, True]
    assert document["core_version"] == spacecraft_ops_challenge.__version__
    for secret in (str(SECRET_FACTOR), "987654321", "876543219", "ThrusterEfficiency", "THRUSTER_1"):
        assert secret not in text


def test_the_pyproject_of_the_archive_names_the_packages():
    archive = zip_bytes(
        {
            "submission/strategy.py": DECLARE_AT_START,
            "pyproject.toml": "[project]\nname = 'example'\ndependencies = ['packaging>=20']\n",
        }
    )
    statuses = []
    evaluation = evaluate_submission(archive, SUITE, PROVIDER, on_status=statuses.append)
    assert evaluation.skipped_entries == ()
    assert [d.decision for d in evaluation.dependencies.plan.decisions] == ["SATISFIED"]
    assert statuses == ["Preparing the participant's packages", "Running cases"]
    result = EvaluationResult.from_evaluation(evaluation)
    assert result.to_dict()["dependencies"]["plan"]["decisions"][0]["requirement"] == "packaging>=20"
    loaded = EvaluationResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert loaded.to_dict() == result.to_dict()
    assert loaded.outcomes == result.outcomes


def test_unreproducible_dependencies_stop_the_evaluation():
    archive = zip_bytes(
        {
            "submission/strategy.py": DECLARE_AT_START,
            "pyproject.toml": "[project]\ndependencies = ['helper @ file:///nonexistent/helper-0.1-py3-none-any.whl']\n",
        }
    )
    with pytest.raises(DependencyError, match="cannot be reproduced"):
        evaluate_submission(archive, SUITE, PROVIDER, on_case_done=pytest.fail)


def test_a_broken_provider_fails_before_the_submission_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    broken = ScenarioProvider("judge_test_provider:failing", PROVIDER.paths)
    with pytest.raises(CaseError, match="failed for case 'case-001'"):
        evaluate_submission(b"not a zip archive", SUITE, broken)
    assert list(tmp_path.iterdir()) == []


def test_check_submission_runs_one_case_per_public_scenario():
    seen = []
    evaluation = check_submission(zip_bytes({"submission/strategy.py": DECLARE_AT_START}), on_case_done=seen.append)
    assert evaluation.suite == public_suite()
    assert [o.case_id for o in evaluation.outcomes] == list(scenario_names())
    assert seen == list(evaluation.outcomes)
    assert all(o.status is CaseStatus.COMPLETED for o in evaluation.outcomes)
    assert all(o.metrics["completion_declared"] for o in evaluation.outcomes)


def test_environment_changes_of_the_provider_check_do_not_reach_the_participant(monkeypatch):
    # Registered as unset, so that the variable that the provider exports is removed after the test.
    monkeypatch.setenv("JUDGE_TEST_HIDDEN", "")
    monkeypatch.delenv("JUDGE_TEST_HIDDEN")
    exporting = ScenarioProvider("judge_test_provider:exporting", PROVIDER.paths)
    reading = """
import os

from spacecraft_ops_challenge import DeclareCompletion, Strategy


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        print("hidden:", os.environ.get("JUDGE_TEST_HIDDEN"))
        commander.execute(DeclareCompletion())
"""
    evaluation = evaluate_submission(zip_bytes({"submission/strategy.py": reading}), SUITE, exporting)
    assert "JUDGE_TEST_HIDDEN" in os.environ  # the check in this process did export it
    assert all(outcome.stdout == "hidden: None\n" for outcome in evaluation.outcomes)


def test_dependency_installation_gets_the_environment_from_before_the_provider_check(monkeypatch):
    monkeypatch.setenv("JUDGE_TEST_HIDDEN", "")
    monkeypatch.delenv("JUDGE_TEST_HIDDEN")
    seen = {}
    real_resolve = judging.resolve_dependencies

    def resolve(*args, env=None, **kwargs):
        seen["env"] = env
        return real_resolve(*args, env=env, **kwargs)

    monkeypatch.setattr(judging, "resolve_dependencies", resolve)
    exporting = ScenarioProvider("judge_test_provider:exporting", PROVIDER.paths)
    evaluate_submission(zip_bytes({"submission/strategy.py": DECLARE_AT_START}), SUITE, exporting)
    assert "JUDGE_TEST_HIDDEN" in os.environ
    assert "JUDGE_TEST_HIDDEN" not in seen["env"]
