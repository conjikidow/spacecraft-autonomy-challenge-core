"""Register a whole command timeline in `initialize` and never use `update`.

Run from the repository root with `uv run python examples/timeline_basics.py`.
"""

from spacecraft_ops_challenge import (
    Commander,
    DeclareCompletion,
    MissionBrief,
    PropulsionMode,
    SetHeater,
    SetPropulsionMode,
    Strategy,
    Telemetry,
)


class TimelineBasics(Strategy):
    """Schedules every command at time 0; the simulation executes each one at its scheduled time."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        commander.schedule(10.0, SetPropulsionMode(PropulsionMode.THRUSTER_1))
        # Selecting the other thruster implicitly stops the first one.
        commander.schedule(40.0, SetPropulsionMode(PropulsionMode.THRUSTER_2))
        commander.schedule(60.0, SetPropulsionMode(PropulsionMode.OFF))
        # Commands with the same time execute in the order they were registered.
        commander.schedule(60.0, SetHeater(on=True))
        commander.schedule(90.0, SetHeater(on=False))
        commander.schedule(120.0, DeclareCompletion())

        for scheduled in commander.pending():
            print(f"pending: {scheduled.time_s:6.1f} s  #{scheduled.command_id}  {scheduled.command}")


if __name__ == "__main__":
    from toy_problem import run_and_report

    run_and_report(TimelineBasics())
