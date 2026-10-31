"""Read a planning model from an ANML file next to the strategy, and schedule the plan it gives.

Run from the repository root with `uv run python examples/planning_external_file.py`.
"""

from pathlib import Path

from unified_planning.io import ANMLReader
from unified_planning.model.metrics import MinimizeMakespan
from unified_planning.shortcuts import OneshotPlanner, get_environment

from spacecraft_autonomy_challenge import (
    Commander,
    DeclareCompletion,
    MissionBrief,
    PropulsionMode,
    SetPropulsionMode,
    Strategy,
    Telemetry,
)

# Built from the location of this file, because the working directory differs during an evaluation.
MODEL_FILE = Path(__file__).with_name("toy_burn.anml")
# Engines that can plan with durations. An engine that cannot handle the problem fails the whole
# parallel call, so list only such engines; those not installed on this platform are left out below.
ENGINES = ("tamer", "aries")


class PlanningExternalFile(Strategy):
    """Plans once in `initialize` from a model in a separate file."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        problem = ANMLReader().parse_problem(str(MODEL_FILE))
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

    run_and_report(PlanningExternalFile())
