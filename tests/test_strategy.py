import spacecraft_ops.strategy as strategy_module
from spacecraft_ops.commands import Command, PropulsionMode, SetPropulsionMode
from spacecraft_ops.modifiers import nominal_telemetry
from spacecraft_ops.simulation import LocalCommander, Simulation
from spacecraft_ops.strategy import Commander, Strategy
from spacecraft_ops.timeline import CommandId, ScheduledCommand


class RecordingCommander:
    """Minimal `Commander` that records requests instead of talking to a simulation."""

    def __init__(self, now_s: float) -> None:
        self.now_s = now_s
        self.requests: list[tuple[str, object]] = []
        self._next_id = 1

    def schedule(self, time_s: float, command: Command) -> CommandId:
        self.requests.append(("schedule", (time_s, command)))
        self._next_id += 1
        return CommandId(self._next_id - 1)

    def execute(self, command: Command) -> CommandId:
        return self.schedule(self.now_s, command)

    def cancel(self, command_id: CommandId) -> bool:
        self.requests.append(("cancel", command_id))
        return True

    def cancel_from(self, time_s: float) -> tuple[CommandId, ...]:
        self.requests.append(("cancel_from", time_s))
        return ()

    def pending(self) -> tuple[ScheduledCommand, ...]:
        return ()


class Replanning(Strategy):
    def initialize(self, brief, telemetry, commander: Commander) -> None:
        self.stop = commander.schedule(commander.now_s + 100.0, SetPropulsionMode(PropulsionMode.OFF))
        commander.execute(SetPropulsionMode(PropulsionMode.THRUSTER_1))

    def update(self, telemetry, commander: Commander) -> None:
        commander.cancel(self.stop)
        commander.cancel_from(commander.now_s)


def test_strategies_can_be_driven_by_any_commander_implementation(make_scenario, make_state):
    scenario = make_scenario()
    commander = RecordingCommander(now_s=0.0)
    strategy = Replanning()
    strategy.initialize(scenario.brief(), nominal_telemetry(make_state()), commander)
    commander.now_s = 60.0
    strategy.update(nominal_telemetry(make_state(time_s=60.0)), commander)
    assert [kind for kind, _ in commander.requests] == ["schedule", "schedule", "cancel", "cancel_from"]
    assert commander.requests[2] == ("cancel", 1)


def test_strategy_module_does_not_depend_on_simulator_internals():
    assert not hasattr(strategy_module, "Timeline")
    assert not hasattr(strategy_module, "LocalCommander")


def test_simulation_passes_a_local_commander(make_scenario):
    simulation = Simulation(make_scenario())
    simulation.start()
    with simulation.decision() as commander:
        assert isinstance(commander, LocalCommander)
