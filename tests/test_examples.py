import ast
import runpy
import sys
from pathlib import Path

import pytest

from spacecraft_autonomy_challenge import DeclareCompletion, PropulsionMode, SetPropulsionMode, Strategy
from spacecraft_autonomy_challenge.challenge import problem as challenge_problem
from spacecraft_autonomy_challenge.results import TerminationReason
from spacecraft_autonomy_challenge.simulation import run

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
STRATEGY_FILES = ["timeline_basics.py", "telemetry_and_replanning.py"]
PLANNING_STRATEGIES = {
    "planning_internal_model.py": "PlanningInternalModel",
    "planning_external_file.py": "PlanningExternalFile",
}


@pytest.fixture
def examples(monkeypatch):
    """Import path and module cache as when running an example script from the repository root."""
    monkeypatch.setattr(sys, "path", [str(EXAMPLES), *sys.path])
    for module in ("toy_problem", "toy_planning"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    return lambda name: runpy.run_path(str(EXAMPLES / name))


@pytest.mark.parametrize("name", STRATEGY_FILES)
def test_example_strategies_import_only_the_top_level_package(name):
    tree = ast.parse((EXAMPLES / name).read_text())
    modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert modules <= {"spacecraft_autonomy_challenge", "toy_problem"}


def test_toy_problem_differs_from_the_challenge_problem(examples):
    toy = examples("toy_problem.py")["toy_scenario"]()
    assert toy.problem != challenge_problem()
    assert toy.problem.parameters != challenge_problem().parameters


@pytest.mark.parametrize("name", [*STRATEGY_FILES, *PLANNING_STRATEGIES])
def test_example_scripts_run(name, examples, capsys):
    runpy.run_path(str(EXAMPLES / name), run_name="__main__")
    assert "termination: COMPLETION_DECLARED" in capsys.readouterr().out


@pytest.mark.parametrize("engines", [("tamer",), ("aries",), ("tamer", "aries")])
@pytest.mark.parametrize("name", PLANNING_STRATEGIES)
def test_planning_examples_schedule_the_planned_burns(name, engines, examples, monkeypatch):
    for engine in engines:
        pytest.importorskip(f"up_{engine}")
    namespace = examples(name)
    monkeypatch.setattr(sys.modules["toy_planning"], "ENGINES", engines)
    result = run(namespace[PLANNING_STRATEGIES[name]](), examples("toy_problem.py")["toy_scenario"]())
    commands = [s.command for s in result.executed_commands]
    assert commands == [
        *[SetPropulsionMode(PropulsionMode.THRUSTER_1), SetPropulsionMode(PropulsionMode.OFF)] * 4,
        DeclareCompletion(),
    ]
    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED


def test_timeline_basics_schedules_everything_in_initialize(examples):
    namespace = examples("timeline_basics.py")
    strategy_class = namespace["TimelineBasics"]
    assert strategy_class.update is Strategy.update
    result = run(strategy_class(), examples("toy_problem.py")["toy_scenario"]())
    assert [s.time_s for s in result.executed_commands] == [10.0, 40.0, 60.0, 60.0, 90.0, 120.0]
    assert [s.command_id for s in result.executed_commands] == [1, 2, 3, 4, 5, 6]
    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED


def test_telemetry_and_replanning_replaces_the_tentative_stop(examples):
    namespace = examples("telemetry_and_replanning.py")
    result = run(namespace["TelemetryAndReplanning"](), examples("toy_problem.py")["toy_scenario"]())
    executed = [(s.time_s, s.command) for s in result.executed_commands]
    assert executed == [
        (0.0, SetPropulsionMode(PropulsionMode.THRUSTER_1)),
        (75.0, SetPropulsionMode(PropulsionMode.OFF)),
        (90.0, DeclareCompletion()),
    ]
    assert 2 not in {s.command_id for s in result.executed_commands}
