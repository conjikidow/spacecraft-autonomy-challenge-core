"""Read a planning model from an ANML file next to the strategy, and schedule the plan it gives.

Run from the repository root with `uv run python examples/planning_external_file.py`.
"""

from pathlib import Path

from toy_planning import schedule_burns, solve
from unified_planning.io import ANMLReader

from spacecraft_autonomy_challenge import Commander, MissionBrief, Strategy, Telemetry

# Built from the location of this file, because the working directory differs during an evaluation.
MODEL_FILE = Path(__file__).with_name("toy_burn.anml")


class PlanningExternalFile(Strategy):
    """Plans once in `initialize` from a model in a separate file."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        problem = ANMLReader().parse_problem(str(MODEL_FILE))
        schedule_burns(solve(problem), commander, brief.decision_period_s)


if __name__ == "__main__":
    from toy_problem import run_and_report

    run_and_report(PlanningExternalFile())
