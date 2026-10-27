import json
import sys
import textwrap
from pathlib import Path

import pytest

from spacecraft_ops_challenge.cli import (
    EXIT_OK,
    EXIT_STRATEGY_FAILURE,
    EXIT_USAGE,
    StrategyLoadError,
    load_strategy,
    main,
)
from spacecraft_ops_challenge.strategy import Strategy


@pytest.fixture(autouse=True)
def isolated_imports(monkeypatch):
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(sys, "modules", dict(sys.modules))


def write(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source))
    return path


@pytest.fixture
def idle_strategy_file(tmp_path):
    return write(
        tmp_path / "cli_idle_strategy.py",
        """
        from spacecraft_ops_challenge import DeclareCompletion, Strategy

        class Idle(Strategy):
            def initialize(self, brief, telemetry, commander):
                commander.schedule(120.0, DeclareCompletion())
        """,
    )


def test_load_strategy_from_file_with_sibling_module(tmp_path):
    write(tmp_path / "cli_plan_helpers.py", "COMPLETE_AT_S = 60.0\n")
    write(
        tmp_path / "cli_multi_file_strategy.py",
        """
        from cli_plan_helpers import COMPLETE_AT_S
        from spacecraft_ops_challenge import DeclareCompletion, Strategy

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
    write(package / "policy.py", "from spacecraft_ops_challenge import Strategy\n\nclass Policy(Strategy):\n    pass\n")
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
    assert "COMPLETION_DECLARED at 120.0 s" in out
    assert "completion declared:" in out


def test_run_emits_json(idle_strategy_file, capsys):
    assert main(["run", f"{idle_strategy_file}:Idle", "--json", "--seed", "5"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["scenario"] == "nominal"
    assert payload["seed"] == 5
    assert payload["metrics"]["termination_reason"] == "COMPLETION_DECLARED"
    assert payload["metrics"]["completion_declared"] is True
    assert payload["metrics"]["time_limit_s"] == 21600.0
    assert payload["metrics"]["decision_period_s"] == 60.0
    assert payload["metrics"]["nominal_battery_capacity_wh"] == 100.0
    assert payload["metrics"]["min_battery_energy_limit_wh"] == 10.0


def test_json_output_stays_valid_when_the_strategy_prints(tmp_path, capsys):
    path = write(
        tmp_path / "cli_printing_strategy.py",
        """
        from spacecraft_ops_challenge import DeclareCompletion, Strategy

        print("printed while loading")

        class Printing(Strategy):
            def initialize(self, brief, telemetry, commander):
                print("printed in initialize")
                commander.schedule(120.0, DeclareCompletion())

            def update(self, telemetry, commander):
                print("printed in update")
        """,
    )
    assert main(["run", f"{path}:Printing", "--json"]) == EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out)["metrics"]["completion_declared"] is True
    for text in ("printed while loading", "printed in initialize", "printed in update"):
        assert text in captured.err


def test_text_output_keeps_strategy_prints_on_stdout(tmp_path, capsys):
    path = write(
        tmp_path / "cli_text_printing_strategy.py",
        """
        from spacecraft_ops_challenge import DeclareCompletion, Strategy

        class Printing(Strategy):
            def initialize(self, brief, telemetry, commander):
                print("printed in initialize")
                commander.schedule(60.0, DeclareCompletion())
        """,
    )
    assert main(["run", f"{path}:Printing"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.index("printed in initialize") < out.index("termination:")


def test_strategy_error_exits_with_failure_and_prints_traceback(tmp_path, capsys):
    path = write(
        tmp_path / "cli_failing_strategy.py",
        """
        from spacecraft_ops_challenge import Strategy

        class Failing(Strategy):
            def update(self, telemetry, commander):
                raise RuntimeError("boom")
        """,
    )
    assert main(["run", f"{path}:Failing"]) == EXIT_STRATEGY_FAILURE
    captured = capsys.readouterr()
    assert "STRATEGY_ERROR" in captured.out
    assert "RuntimeError: boom" in captured.err


def test_invalid_command_exits_with_failure(tmp_path, capsys):
    path = write(
        tmp_path / "cli_invalid_strategy.py",
        """
        from spacecraft_ops_challenge import DeclareCompletion, Strategy

        class Invalid(Strategy):
            def update(self, telemetry, commander):
                commander.schedule(telemetry.time_s - 1.0, DeclareCompletion())
        """,
    )
    assert main(["run", f"{path}:Invalid"]) == EXIT_STRATEGY_FAILURE
    assert "INVALID_COMMAND" in capsys.readouterr().out


def test_unsafe_run_still_exits_ok_and_lists_violations(tmp_path, capsys):
    path = write(
        tmp_path / "cli_unsafe_strategy.py",
        """
        from spacecraft_ops_challenge import PropulsionMode, SetPropulsionMode, Strategy

        class SingleThruster(Strategy):
            def initialize(self, brief, telemetry, commander):
                commander.execute(SetPropulsionMode(PropulsionMode.THRUSTER_1))
        """,
    )
    assert main(["run", f"{path}:SingleThruster"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "MOMENTUM_VIOLATION" in out
    assert "violation:" in out


def test_strategy_file_named_like_an_imported_module_does_not_shadow_it(tmp_path):
    write(
        tmp_path / "spacecraft_ops_challenge.py",
        """
        from spacecraft_ops_challenge import Strategy

        class Shadow(Strategy):
            pass
        """,
    )
    assert type(load_strategy(f"{tmp_path / 'spacecraft_ops_challenge.py'}:Shadow")).__name__ == "Shadow"


def test_usage_errors_exit_with_usage_status(idle_strategy_file, capsys):
    assert main(["run", "missing_module_xyz:Strategy"]) == EXIT_USAGE
    assert main(["run", f"{idle_strategy_file}:Idle", "--scenario", "unknown"]) == EXIT_USAGE
    assert "error:" in capsys.readouterr().err


def test_scenarios_lists_challenge_scenarios(capsys):
    assert main(["scenarios"]) == EXIT_OK
    assert "nominal" in capsys.readouterr().out
