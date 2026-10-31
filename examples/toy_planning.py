"""Solve a planning problem with several engines at once, and turn the plan into commands.

The planning examples import this module, as a strategy can import any module next to it.
"""

from unified_planning.model.metrics import MinimizeMakespan
from unified_planning.plans import TimeTriggeredPlan
from unified_planning.shortcuts import OneshotPlanner, Problem, get_environment

from spacecraft_autonomy_challenge import Commander, DeclareCompletion, PropulsionMode, SetPropulsionMode

# Engines that can plan with durations. An engine that cannot handle the problem fails the whole
# parallel call, so list only such engines; those not installed on this platform are left out below.
ENGINES = ("tamer", "aries")


def solve(problem: Problem) -> TimeTriggeredPlan:
    """Run the installed engines in parallel and return the plan of the first one that solves `problem`."""
    environment = get_environment()
    environment.credits_stream = None  # Keeps the credits of the engines out of the output.
    names = [name for name in ENGINES if name in environment.factory.engines]
    if not names:
        raise RuntimeError(f"none of the planning engines {ENGINES} is installed")
    # With a quality metric, the first plan ends the parallel call; without one, it waits for every engine.
    problem.add_quality_metric(MinimizeMakespan())
    with OneshotPlanner(names=names) as planner:
        result = planner.solve(problem)
    if result.plan is None:
        raise RuntimeError(f"no plan: {result.status.name}")
    print(f"{result.engine_name}: {result.status.name}")
    return result.plan


def schedule_burns(plan: TimeTriggeredPlan, commander: Commander, decision_period_s: float) -> None:
    """Schedule each planned burn on one thruster, then declare completion."""
    end_s = 0.0
    for start, _action, duration in plan.timed_actions:
        commander.schedule(float(start), SetPropulsionMode(PropulsionMode.THRUSTER_1))
        commander.schedule(float(start + duration), SetPropulsionMode(PropulsionMode.OFF))
        end_s = max(end_s, float(start + duration))
    commander.schedule(end_s + decision_period_s, DeclareCompletion())
