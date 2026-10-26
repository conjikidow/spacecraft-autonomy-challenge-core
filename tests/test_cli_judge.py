import hashlib
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest
from judge_support import DECLARE_AT_START

from spacecraft_ops_challenge.challenge import scenario_names
from spacecraft_ops_challenge.cli import EXIT_OK, EXIT_STRATEGY_FAILURE, EXIT_USAGE, main
from spacecraft_ops_challenge.judge.reporting import EvaluationResult
from spacecraft_ops_challenge.judge.submission import build_submission

RAISING = """
from spacecraft_ops_challenge import Strategy


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        print("printed before failing")
        raise RuntimeError("boom")
"""


def make_project(root: Path, strategy: str = DECLARE_AT_START) -> Path:
    (root / "submission").mkdir(parents=True)
    (root / "submission" / "strategy.py").write_text(textwrap.dedent(strategy))
    return root


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "project")


def test_pack_writes_the_archive_and_describes_it(project, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "submission.zip").write_bytes(b"stale")
    assert main(["pack", str(project)]) == EXIT_OK
    archive = (tmp_path / "submission.zip").read_bytes()
    assert archive == build_submission(project)
    with zipfile.ZipFile(tmp_path / "submission.zip") as zip_file:
        assert zip_file.namelist() == ["submission/strategy.py"]
    out = capsys.readouterr().out
    assert "submission.zip" in out
    assert f"{len(archive)} bytes" in out
    assert hashlib.sha256(archive).hexdigest() in out
    assert "entries:  1" in out


def test_pack_defaults_to_the_current_directory(project, monkeypatch):
    monkeypatch.chdir(project)
    assert main(["pack", "-o", "out.zip"]) == EXIT_OK
    assert (project / "out.zip").read_bytes() == build_submission(project)


def test_pack_refuses_an_output_inside_the_submission_directory(project, monkeypatch, capsys):
    monkeypatch.chdir(project / "submission")
    assert main(["pack", "..", "-o", "submission.zip"]) == EXIT_USAGE
    assert main(["pack", str(project), "-o", str(project / "submission" / "nested" / "out.zip")]) == EXIT_USAGE
    assert "must not be inside" in capsys.readouterr().err
    assert sorted(path.name for path in (project / "submission").iterdir()) == ["strategy.py"]


def test_pack_reports_an_invalid_project(tmp_path, capsys):
    assert main(["pack", str(tmp_path), "-o", str(tmp_path / "out.zip")]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err
    assert not (tmp_path / "out.zip").exists()


def test_check_runs_the_public_scenarios_on_a_project(project, capsys):
    assert main(["check", str(project)]) == EXIT_OK
    captured = capsys.readouterr()
    assert f"[2/2] {scenario_names()[1]}: COMPLETED (score " in captured.err
    assert "Score:" in captured.out
    assert "COMPLETION_DECLARED" in captured.out
    assert "Problems" not in captured.out


def test_check_reads_an_archive_and_prints_json(project, tmp_path, capsys):
    archive = tmp_path / "submission.zip"
    archive.write_bytes(build_submission(project))
    assert main(["check", str(archive), "--json", "--timeout", "60"]) == EXIT_OK
    captured = capsys.readouterr()
    result = EvaluationResult.from_json(captured.out)
    assert result.case_ids == tuple(scenario_names())
    assert result.submission_sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert "[1/2]" in captured.err


def test_check_exits_with_failure_for_a_strategy_that_raises(tmp_path, capsys):
    assert main(["check", str(make_project(tmp_path, RAISING))]) == EXIT_STRATEGY_FAILURE
    out = capsys.readouterr().out
    assert "Problems" in out
    assert "COMPLETED (STRATEGY_ERROR)" in out
    assert "RuntimeError: boom" in out
    assert "printed before failing" in out


def test_check_points_out_missing_modules(tmp_path, capsys):
    project = make_project(tmp_path, "import missing_helper_module_xyz\n" + DECLARE_AT_START)
    assert main(["check", str(project)]) == EXIT_STRATEGY_FAILURE
    out = capsys.readouterr().out
    assert "LOAD_ERROR" in out
    assert "Missing modules: missing_helper_module_xyz" in out


def test_check_usage_errors(project, tmp_path, capsys):
    bad_scoring = tmp_path / "scoring.toml"
    bad_scoring.write_text("not = [toml\n")
    assert main(["check", str(tmp_path / "empty")]) == EXIT_USAGE
    (tmp_path / "empty").mkdir()
    assert main(["check", str(tmp_path / "empty")]) == EXIT_USAGE
    assert main(["check", str(project), "--scoring", str(bad_scoring)]) == EXIT_USAGE
    assert main(["check", str(project), "--scoring", str(tmp_path / "missing.toml")]) == EXIT_USAGE
    assert main(["check", str(bad_scoring)]) == EXIT_USAGE
    err = capsys.readouterr().err
    assert err.count("error:") == 5
    assert "[1/" not in err


def test_check_rejects_a_non_positive_timeout(project, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["check", str(project), "--timeout", "0"])
    assert exit_info.value.code == EXIT_USAGE


def test_importing_the_cli_does_not_import_the_evaluation_modules():
    code = (
        "import sys, spacecraft_ops_challenge.cli; "
        "print(sorted(m for m in sys.modules if m.startswith('spacecraft_ops_challenge.judge')))"
    )
    output = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert output.strip() == "[]"
