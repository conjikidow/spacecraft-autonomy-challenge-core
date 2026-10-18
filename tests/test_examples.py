import importlib.util
from pathlib import Path

import pytest

from spacecraft_ops.challenge import scenario as reference_scenario
from spacecraft_ops.results import TerminationReason
from spacecraft_ops.simulation import Simulation, run
from spacecraft_ops.strategy import Strategy

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SMALL_ERROR_MPS = 1e-6


def load_example(name):
    spec = importlib.util.spec_from_file_location(f"example_{name}", EXAMPLES / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixed_sequence():
    return load_example("fixed_sequence").FixedSequenceStrategy()


def reactive():
    return load_example("reactive").ReactiveStrategy()


def delta_v_error(result):
    return abs(result.final_state.delta_v_mps - result.scenario.problem.target_delta_v_mps)


@pytest.mark.parametrize("make_strategy", [fixed_sequence, reactive])
def test_examples_complete_nominal_safely(make_strategy):
    scenario = reference_scenario("nominal")
    result = run(make_strategy(), scenario)
    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert not result.safety_violations
    assert delta_v_error(result) < SMALL_ERROR_MPS
    assert result.termination.time_s < 0.75 * scenario.problem.time_limit_s


def test_fixed_sequence_schedules_everything_in_initialize():
    strategy = fixed_sequence()
    assert type(strategy).update is Strategy.update

    simulation = Simulation(reference_scenario("nominal"))
    telemetry = simulation.start()
    with simulation.decision() as commander:
        strategy.initialize(simulation.brief, telemetry, commander)
        planned = {scheduled.command_id for scheduled in commander.pending()}
    while (telemetry := simulation.advance()) is not None:
        with simulation.decision() as commander:
            strategy.update(telemetry, commander)
    result = simulation.result()

    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert {scheduled.command_id for scheduled in result.executed_commands} == planned


def test_reactive_adapts_to_thruster_degradation_while_fixed_sequence_does_not():
    scenario = reference_scenario("thruster-degradation")
    reactive_result = run(reactive(), scenario)
    fixed_result = run(fixed_sequence(), scenario)

    assert reactive_result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert not reactive_result.safety_violations
    assert delta_v_error(reactive_result) < SMALL_ERROR_MPS

    assert fixed_result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert delta_v_error(fixed_result) > 0.05 * scenario.problem.target_delta_v_mps


@pytest.mark.parametrize("make_strategy", [fixed_sequence, reactive])
@pytest.mark.parametrize("name", ["nominal", "thruster-degradation"])
def test_example_runs_are_deterministic(make_strategy, name):
    first = run(make_strategy(), reference_scenario(name))
    second = run(make_strategy(), reference_scenario(name))
    assert first.termination == second.termination
    assert first.trajectory == second.trajectory
    assert first.executed_commands == second.executed_commands


def test_reactive_cancels_planned_stops():
    result = run(reactive(), reference_scenario("nominal"))
    executed = [scheduled.command_id for scheduled in result.executed_commands]
    assert len(executed) < max(executed)
