"""Read telemetry in `update`, then cancel and replace scheduled commands.

Run from the repository root with `uv run python examples/telemetry_and_replanning.py`.
"""

from spacecraft_autonomy_challenge import (
    Commander,
    CommandId,
    DeclareCompletion,
    MissionBrief,
    PropulsionMode,
    SetPropulsionMode,
    Strategy,
    Telemetry,
)

REPLAN_AT_S = 60.0


class TelemetryAndReplanning(Strategy):
    """Starts with a tentative plan, then replaces it at a later update."""

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        self.decision_period_s = brief.decision_period_s
        # An immediate command executes right after this callback returns.
        commander.execute(SetPropulsionMode(PropulsionMode.THRUSTER_1))
        # A tentative stop far in the future; its identifier allows canceling it later.
        self.tentative_stop: CommandId = commander.schedule(500.0, SetPropulsionMode(PropulsionMode.OFF))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        print(
            f"update at {telemetry.time_s:5.1f} s: mode={telemetry.propulsion_mode}, "
            f"delta-v={telemetry.delta_v_mps:.3f} m/s, temperature={telemetry.propulsion_temperature_c:.2f} C"
        )
        if telemetry.time_s != REPLAN_AT_S:
            return

        # Cancel one command by its identifier.
        print(f"cancel #{self.tentative_stop}: {commander.cancel(self.tentative_stop)}")
        # Or cancel everything from a time onward, then register a replacement plan.
        commander.cancel_from(commander.now_s)
        commander.schedule(commander.now_s + 15.0, SetPropulsionMode(PropulsionMode.OFF))
        commander.schedule(commander.now_s + self.decision_period_s, DeclareCompletion())


if __name__ == "__main__":
    from toy_problem import run_and_report

    run_and_report(TelemetryAndReplanning())
