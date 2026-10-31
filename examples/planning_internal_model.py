"""Build a planning model in Python with Unified Planning, and schedule the plan it gives.

Run from the repository root with `uv run python examples/planning_internal_model.py`.
"""

from toy_planning import schedule_burns, solve
from unified_planning.shortcuts import GE, BoolType, DurativeAction, EndTiming, Fluent, IntType, Problem, StartTiming

from spacecraft_autonomy_challenge import Commander, MissionBrief, Strategy, Telemetry

CHUNK_S = 30
CHUNKS = 4


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
        schedule_burns(solve(toy_model()), commander, brief.decision_period_s)


if __name__ == "__main__":
    from toy_problem import run_and_report

    run_and_report(PlanningInternalModel())
