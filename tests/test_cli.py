import json
import textwrap
from pathlib import Path

import pytest

from spacecraft_ops.cli import EXIT_OK, EXIT_STRATEGY_FAILURE, EXIT_USAGE, StrategyLoadError, load_strategy, main
from spacecraft_ops.strategy import Strategy

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def write(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source))
    return path


@pytest.fixture
def idle_strategy_file(tmp_path):
    return write(
        tmp_path / "cli_idle_strategy.py",
        """
        from spacecraft_ops import CompleteMission, Strategy

        class Idle(Strategy):
            def initialize(self, brief, telemetry, commander):
                commander.schedule(120.0, CompleteMission())
        """,
    )


def test_load_strategy_from_file_with_sibling_module(tmp_path):
    write(tmp_path / "cli_plan_helpers.py", "COMPLETE_AT_S = 60.0\n")
    write(
        tmp_path / "cli_multi_file_strategy.py",
        """
        from cli_plan_helpers import COMPLETE_AT_S
        from spacecraft_ops import CompleteMission, Strategy

        class MultiFile(Strategy):
            complete_at_s = COMPLETE_AT_S
        """,
    )
    strategy = load_strategy(f"{tmp_path / 'cli_multi_file_strategy.py'}:MultiFile")
    assert isinstance(strategy, Strategy)
    assert strategy.complete_at_s == 60.0


def test_load_strategy_from_module_in_current_directory(tmp_path, monkeypatch):
    package = tmp_path / "cli_strategy_package"
    package.mkdir()
    write(package / "__init__.py", "")
    write(package / "policy.py", "from spacecraft_ops import Strategy\n\nclass Policy(Strategy):\n    pass\n")
    monkeypatch.chdir(tmp_path)
    assert type(load_strategy("cli_strategy_package.policy:Policy")).__name__ == "Policy"


@pytest.mark.parametrize(
    "spec",
    ["no_separator", ":Missing", "missing_module_xyz:Strategy", "json:JSONDecoder", "json:missing"],
)
def test_load_strategy_rejects_bad_specs(spec):
    with pytest.raises(StrategyLoadError):
        load_strategy(spec)


def test_run_prints_summary_and_exits_ok(idle_strategy_file, capsys):
    assert main(["run", f"{idle_strategy_file}:Idle"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "MISSION_COMPLETE at 120.0 s" in out
    assert "reference score" in out


def test_run_emits_json(idle_strategy_file, capsys):
    assert main(["run", f"{idle_strategy_file}:Idle", "--json", "--seed", "5"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario"] == "nominal"
    assert payload["seed"] == 5
    assert payload["metrics"]["termination_reason"] == "MISSION_COMPLETE"
    assert 0.0 <= payload["reference_score"] <= 1.0


def test_strategy_error_exits_with_failure_and_prints_traceback(tmp_path, capsys):
    path = write(
        tmp_path / "cli_failing_strategy.py",
        """
        from spacecraft_ops import Strategy

        class Failing(Strategy):
            def update(self, telemetry, commander):
                raise RuntimeError("boom")
        """,
    )
    assert main(["run", f"{path}:Failing"]) == EXIT_STRATEGY_FAILURE
    captured = capsys.readouterr()
    assert "STRATEGY_ERROR" in captured.out
    assert "RuntimeError: boom" in captured.err


def test_usage_errors_exit_with_usage_status(idle_strategy_file, capsys):
    assert main(["run", "missing_module_xyz:Strategy"]) == EXIT_USAGE
    assert main(["run", f"{idle_strategy_file}:Idle", "--scenario", "unknown"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_scenarios_lists_reference_scenarios(capsys):
    assert main(["scenarios"]) == EXIT_OK
    assert "nominal" in capsys.readouterr().out


@pytest.mark.parametrize("spec", ["fixed_sequence.py:FixedSequenceStrategy", "reactive.py:ReactiveStrategy"])
def test_examples_run_through_the_cli(spec, capsys):
    assert main(["run", f"{EXAMPLES / spec}"]) == EXIT_OK
    assert "MISSION_COMPLETE" in capsys.readouterr().out
