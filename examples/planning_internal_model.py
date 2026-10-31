"""Build a planning model in Python with Unified Planning, and schedule the plan it gives.

Run from the repository root with `uv run python examples/planning_internal_model.py`.
"""

from unified_planning.model.metrics import MinimizeMakespan
from unified_planning.shortcuts import (
    GE,
    BoolType,
    DurativeAction,
    EndTiming,
    Fluent,
    IntType,
    OneshotPlanner,
    Problem,
    StartTiming,
    get_environment,
)

from spacecraft_autonomy_challenge import (
    Commander,
    DeclareCompletion,
    MissionBrief,
    PropulsionMode,
    SetPropulsionMode,
    Strategy,
    Telemetry,
)

CHUNK_S = 30
CHUNKS = 4
# Engines that can plan with durations. An engine that cannot handle the problem fails the whole
# parallel call, so list only such engines; those not installed on this platform are left out below.
ENGINES = ("tamer", "aries")


def toy_model() -> Problem:
    """The same model as `toy_burn.anml`: burn in chunks, one at a time, until enough chunks are done."""
    idle = Fluent("idle", BoolType())
    chunks = Fluent("chunks", IntType())
    burn = DurativeAction("burn")
    burn.set_fixed_duration(CHUNK_S)
    burn.add_condition(StartTiming(), idle)
    burn.add_effect(StartTiming(), idle, False)
    burn.add_effect(EndTiming(), idle, True)
    burn.add_increase_effect(EndTiming(), chunks, 1)

    problem = Problem("toy_burn")
    problem.add_fluent(idle, default_initial_value=True)
    problem.add_fluent(chunks, default_initial_value=0)
    problem.add_action(burn)
    problem.add_goal(GE(chunks, CHUNKS))
    return problem


class PlanningInternalModel(Strategy):
    """Plans once in `initialize` from a model built in code."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        problem = toy_model()
        # With a quality metric, the first plan ends the parallel call; without one, it waits for every engine.
        problem.add_quality_metric(MinimizeMakespan())

        environment = get_environment()
        environment.credits_stream = None  # Keeps the credits of the engines out of the output.
        names = [name for name in ENGINES if name in environment.factory.engines]
        if not names:
            raise RuntimeError(f"none of the planning engines {ENGINES} is installed")
        with OneshotPlanner(names=names) as planner:
            result = planner.solve(problem)
        if result.plan is None:
            raise RuntimeError(f"no plan: {result.status.name}")
        print(f"{result.engine_name}: {result.status.name}")

        end_s = 0.0
        for start, _action, duration in result.plan.timed_actions:
            commander.schedule(float(start), SetPropulsionMode(PropulsionMode.THRUSTER_1))
            commander.schedule(float(start + duration), SetPropulsionMode(PropulsionMode.OFF))
            end_s = max(end_s, float(start + duration))
        commander.schedule(end_s + brief.decision_period_s, DeclareCompletion())


if __name__ == "__main__":
    from toy_problem import run_and_report

    run_and_report(PlanningInternalModel())
