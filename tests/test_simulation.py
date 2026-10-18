import contextlib
import random
from dataclasses import replace

import pytest

from spacecraft_ops.commands import CommandError, DeclareCompletion, PropulsionMode, SetHeater, SetPropulsionMode
from spacecraft_ops.config import SimulationConfig
from spacecraft_ops.model import SpacecraftState
from spacecraft_ops.modifiers import Modifier, TelemetryBias
from spacecraft_ops.results import TerminationReason
from spacecraft_ops.simulation import Simulation, run
from spacecraft_ops.strategy import Strategy
from spacecraft_ops.telemetry import Telemetry

FIRE_1 = SetPropulsionMode(PropulsionMode.THRUSTER_1)
FIRE_2 = SetPropulsionMode(PropulsionMode.THRUSTER_2)
OFF = SetPropulsionMode(PropulsionMode.OFF)
ACCELERATION_MPS2 = 0.002


class Scripted(Strategy):
    """Test strategy driven by optional callables; records every argument it receives."""

    def __init__(self, on_initialize=None, on_update=None):
        self.on_initialize = on_initialize
        self.on_update = on_update
        self.received = []
        self.update_times = []

    def initialize(self, brief, telemetry, commander):
        self.received.extend([brief, telemetry])
        if self.on_initialize:
            self.on_initialize(commander)

    def update(self, telemetry, commander):
        self.received.append(telemetry)
        self.update_times.append(telemetry.time_s)
        if self.on_update:
            self.on_update(telemetry, commander)


class Noise(Modifier):
    def modify_telemetry(self, telemetry, state, rng):
        return replace(telemetry, propulsion_temperature_c=telemetry.propulsion_temperature_c + rng.gauss(0.0, 1.0))


def schedule_all(*items):
    def on_initialize(commander):
        for time_s, command in items:
            commander.schedule(time_s, command)

    return on_initialize


def test_fixed_strategy_runs_entirely_from_initialize(make_scenario):
    strategy = Scripted(schedule_all((100.0, FIRE_1), (200.0, OFF), (300.0, DeclareCompletion())))
    result = run(strategy, make_scenario())
    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert result.termination.time_s == 300.0
    assert result.final_state.delta_v_mps == pytest.approx(100.0 * ACCELERATION_MPS2)
    assert [s.time_s for s in result.executed_commands] == [100.0, 200.0, 300.0]


def test_base_strategy_with_no_overrides_runs_to_time_limit(make_scenario):
    result = run(Strategy(), make_scenario())
    assert result.termination.reason is TerminationReason.TIME_LIMIT
    assert result.termination.time_s == 600.0


def test_commands_execute_at_exact_times_off_the_integration_and_decision_grids(make_scenario):
    strategy = Scripted(schedule_all((25.3, FIRE_1), (37.8, OFF)))
    result = run(strategy, make_scenario(decision_period_s=60.0), config=SimulationConfig(integration_step_s=10.0))
    assert result.final_state.delta_v_mps == pytest.approx(12.5 * ACCELERATION_MPS2)
    assert {25.3, 37.8} <= {s.time_s for s in result.trajectory}


def test_integration_step_and_decision_period_are_independent(make_scenario):
    strategy = Scripted()
    scenario = make_scenario(decision_period_s=100.0, time_limit_s=600.0)
    result = run(strategy, scenario, config=SimulationConfig(integration_step_s=7.0))
    assert strategy.update_times == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]
    times = [s.time_s for s in result.trajectory]
    assert times[:4] == [0.0, 7.0, 14.0, 21.0]
    assert 100.0 in times
    assert len(times) == len(set(times))


def test_immediate_command_in_update_executes_before_time_advances(make_scenario):
    def on_update(telemetry, commander):
        if telemetry.time_s == 60.0:
            commander.execute(FIRE_1)

    strategy = Scripted(on_update=on_update)
    run(strategy, make_scenario(time_limit_s=120.0))
    at_60, at_120 = strategy.received[2:4]
    assert at_60.propulsion_mode is PropulsionMode.OFF
    assert at_120.propulsion_mode is PropulsionMode.THRUSTER_1
    assert at_120.delta_v_mps == pytest.approx(60.0 * ACCELERATION_MPS2)


def test_immediate_command_in_initialize_executes_at_time_zero(make_scenario):
    result = run(Scripted(lambda commander: commander.execute(FIRE_2)), make_scenario(time_limit_s=10.0))
    assert result.executed_commands[0].time_s == 0.0
    assert result.final_state.wheel_momentum_nms == pytest.approx(-0.1)


def test_adaptive_strategy_schedules_commands_during_later_updates(make_scenario):
    def on_update(telemetry, commander):
        if telemetry.time_s == 60.0:
            commander.schedule(90.0, FIRE_1)
            commander.schedule(100.0, OFF)
        if telemetry.time_s == 120.0 and telemetry.delta_v_mps > 0:
            commander.execute(DeclareCompletion())

    result = run(Scripted(on_update=on_update), make_scenario())
    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert result.termination.time_s == 120.0
    assert result.final_state.delta_v_mps == pytest.approx(10.0 * ACCELERATION_MPS2)


def test_adaptive_strategy_cancels_a_preplanned_command(make_scenario):
    planned = []

    def on_initialize(commander):
        planned.append(commander.schedule(100.0, FIRE_1))

    def on_update(telemetry, commander):
        if telemetry.time_s == 60.0:
            assert commander.cancel(planned[0]) is True

    result = run(Scripted(on_initialize, on_update), make_scenario(time_limit_s=200.0))
    assert result.executed_commands == ()
    assert result.final_state.delta_v_mps == 0.0


def test_adaptive_strategy_replaces_future_timeline(make_scenario):
    def on_initialize(commander):
        commander.schedule(100.0, FIRE_1)
        commander.schedule(500.0, OFF)

    def on_update(telemetry, commander):
        if telemetry.time_s == 120.0:
            commander.cancel_from(commander.now_s)
            commander.execute(FIRE_2)
            commander.schedule(140.0, OFF)
            assert [s.command for s in commander.pending()] == [FIRE_2, OFF]

    result = run(Scripted(on_initialize, on_update), make_scenario(time_limit_s=600.0))
    assert [s.command for s in result.executed_commands] == [FIRE_1, FIRE_2, OFF]
    assert result.final_state.wheel_momentum_nms == pytest.approx(0.2 - 0.2)
    assert result.final_state.delta_v_mps == pytest.approx(40.0 * ACCELERATION_MPS2)


def test_same_time_commands_execute_in_registration_order(make_scenario):
    on_then_off = run(Scripted(schedule_all((10.0, FIRE_1), (10.0, OFF))), make_scenario(time_limit_s=20.0))
    off_then_on = run(Scripted(schedule_all((10.0, OFF), (10.0, FIRE_1))), make_scenario(time_limit_s=20.0))
    assert on_then_off.final_state.propulsion_mode is PropulsionMode.OFF
    assert off_then_on.final_state.propulsion_mode is PropulsionMode.THRUSTER_1


def test_switching_thrusters_is_exclusive(make_scenario):
    strategy = Scripted(schedule_all((0.0, FIRE_1), (100.0, FIRE_2), (200.0, OFF)))
    result = run(strategy, make_scenario(time_limit_s=300.0))
    assert result.final_state.delta_v_mps == pytest.approx(200.0 * ACCELERATION_MPS2)
    assert result.final_state.wheel_momentum_nms == pytest.approx(0.0, abs=1e-12)


def test_commands_after_complete_mission_at_same_time_do_not_execute(make_scenario):
    strategy = Scripted(schedule_all((50.0, DeclareCompletion()), (50.0, SetHeater(on=True))))
    result = run(strategy, make_scenario())
    assert [type(s.command) for s in result.executed_commands] == [DeclareCompletion]
    assert result.final_state.heater_on is False


def test_update_is_not_called_after_completion(make_scenario):
    strategy = Scripted(schedule_all((60.0, DeclareCompletion())))
    run(strategy, make_scenario())
    assert strategy.update_times == []


def test_time_limit_is_inclusive_for_commands_and_decisions(make_scenario):
    strategy = Scripted(schedule_all((600.0, DeclareCompletion())))
    result = run(strategy, make_scenario(time_limit_s=600.0))
    assert result.termination.reason is TerminationReason.COMPLETION_DECLARED
    assert strategy.update_times[-1] == 540.0

    strategy = Scripted()
    result = run(strategy, make_scenario(time_limit_s=600.0))
    assert result.termination.reason is TerminationReason.TIME_LIMIT
    assert strategy.update_times[-1] == 600.0


def test_strategy_receives_telemetry_and_brief_but_never_true_state(make_scenario):
    strategy = Scripted(schedule_all((0.0, FIRE_1)))
    scenario = make_scenario(modifiers=[TelemetryBias("delta_v_mps", 0.5)], time_limit_s=120.0)
    result = run(strategy, scenario)
    brief, *telemetry = strategy.received
    assert brief == scenario.brief()
    assert all(type(t) is Telemetry for t in telemetry)
    assert not any(isinstance(item, SpacecraftState) for item in strategy.received)
    assert telemetry[-1].delta_v_mps == pytest.approx(result.final_state.delta_v_mps + 0.5)


def test_brief_does_not_depend_on_scenario_identity_modifiers_or_seed(make_scenario):
    plain = make_scenario()
    other = make_scenario(name="other", description="other", modifiers=[TelemetryBias("delta_v_mps", 1.0)], seed=42)
    assert plain.brief() == other.brief()


def test_pre_scheduled_command_executes_before_the_decision_at_the_same_time(make_scenario):
    strategy = Scripted(schedule_all((60.0, FIRE_1)))
    run(strategy, make_scenario(time_limit_s=60.0))
    assert strategy.received[-1].time_s == 60.0
    assert strategy.received[-1].propulsion_mode is PropulsionMode.THRUSTER_1


def test_decision_at_time_limit_is_not_skipped_by_float_error(make_scenario):
    strategy = Scripted()
    scenario = make_scenario(decision_period_s=0.1, time_limit_s=0.3)
    result = run(strategy, scenario, config=SimulationConfig(integration_step_s=0.05))
    assert strategy.update_times == pytest.approx([0.1, 0.2, 0.3])
    assert result.termination.reason is TerminationReason.TIME_LIMIT
    assert result.termination.time_s == 0.3


def test_commands_from_a_failed_window_execute_at_next_advance_without_a_zero_length_step(make_scenario):
    simulation = Simulation(make_scenario(time_limit_s=60.0))
    simulation.start()
    with contextlib.suppress(ZeroDivisionError), simulation.decision() as commander:
        commander.execute(FIRE_1)
        raise ZeroDivisionError
    while simulation.advance() is not None:
        pass
    result = simulation.result()
    times = [s.time_s for s in result.trajectory]
    assert len(times) == len(set(times))
    assert result.executed_commands[0].time_s == 0.0
    assert result.final_state.delta_v_mps == pytest.approx(60.0 * ACCELERATION_MPS2)


def test_runs_are_repeatable_for_a_seed_and_vary_across_seeds(make_scenario):
    scenario = make_scenario(modifiers=[Noise()])
    first = run(Scripted(schedule_all((0.0, FIRE_1))), scenario, seed=7)
    second = run(Scripted(schedule_all((0.0, FIRE_1))), scenario, seed=7)
    other = run(Scripted(schedule_all((0.0, FIRE_1))), scenario, seed=8)
    assert first == second
    assert first.telemetry != other.telemetry
    assert first.trajectory == other.trajectory


def test_scenario_seed_is_used_by_default(make_scenario):
    assert run(Strategy(), make_scenario(seed=3, time_limit_s=60.0)).seed == 3


@pytest.mark.parametrize(
    ("limit_overrides", "initial_command", "reason"),
    [
        ({"max_propulsion_temperature_c": 21.0}, FIRE_1, TerminationReason.THERMAL_VIOLATION),
        ({"min_battery_energy_wh": 49.99}, FIRE_1, TerminationReason.BATTERY_DEPLETED),
        ({"max_abs_wheel_momentum_nms": 0.5}, FIRE_2, TerminationReason.MOMENTUM_VIOLATION),
    ],
)
def test_safety_violations_terminate_the_run(make_scenario, limits, limit_overrides, initial_command, reason):
    scenario = make_scenario(limits=replace(limits, **limit_overrides))
    result = run(Scripted(lambda commander: commander.execute(initial_command)), scenario)
    assert result.termination.reason is reason
    assert 0.0 < result.termination.time_s < 600.0
    assert [v.reason for v in result.safety_violations] == [reason]


def test_cold_thruster_does_not_fire_until_heated_and_cold_is_not_a_violation(make_scenario, make_state):
    scenario = make_scenario(initial_state=make_state(propulsion_temperature_c=-51.0), time_limit_s=180.0)
    strategy = Scripted(schedule_all((0.0, FIRE_1), (0.0, SetHeater(on=True))))
    result = run(strategy, scenario)
    at_60, at_120 = strategy.received[2:4]
    assert at_60.propulsion_mode is PropulsionMode.THRUSTER_1
    assert at_60.delta_v_mps == 0.0
    assert at_120.delta_v_mps > 0.0
    assert result.termination.reason is TerminationReason.TIME_LIMIT
    assert not result.safety_violations


def test_simultaneous_violations_are_all_recorded_and_prioritized(make_scenario, limits, make_state):
    scenario = make_scenario(
        initial_state=make_state(propulsion_temperature_c=200.0, wheel_momentum_nms=500.0),
        limits=limits,
    )
    strategy = Scripted()
    result = run(strategy, scenario)
    assert result.termination.reason is TerminationReason.THERMAL_VIOLATION
    assert result.termination.time_s == 0.0
    assert [v.reason for v in result.safety_violations] == [
        TerminationReason.THERMAL_VIOLATION,
        TerminationReason.MOMENTUM_VIOLATION,
    ]
    assert strategy.received == []


def test_strategy_exception_terminates_with_strategy_error(make_scenario):
    def on_update(telemetry, commander):
        raise ZeroDivisionError("boom")

    result = run(Scripted(on_update=on_update), make_scenario())
    assert result.termination.reason is TerminationReason.STRATEGY_ERROR
    assert result.termination.time_s == 60.0
    assert "ZeroDivisionError: boom" in result.termination.detail


def test_past_command_terminates_with_invalid_command(make_scenario):
    def on_update(telemetry, commander):
        commander.schedule(telemetry.time_s - 1.0, FIRE_1)

    result = run(Scripted(on_update=on_update), make_scenario())
    assert result.termination.reason is TerminationReason.INVALID_COMMAND
    assert "past" in result.termination.detail


def test_commander_is_invalid_outside_its_callback(make_scenario):
    kept = []

    def on_update(telemetry, commander):
        if kept:
            kept[0].execute(FIRE_1)
        kept.append(commander)

    result = run(Scripted(on_update=on_update), make_scenario())
    assert result.termination.reason is TerminationReason.INVALID_COMMAND
    assert result.termination.time_s == 120.0
    with pytest.raises(CommandError):
        kept[0].pending()
    with pytest.raises(CommandError):
        _ = kept[0].now_s


def test_caught_command_error_does_not_end_the_run(make_scenario):
    def on_update(telemetry, commander):
        with contextlib.suppress(CommandError):
            commander.schedule(-1.0, FIRE_1)

    assert run(Scripted(on_update=on_update), make_scenario()).termination.reason is TerminationReason.TIME_LIMIT


def test_stepper_can_be_driven_without_a_strategy(make_scenario):
    simulation = Simulation(make_scenario(time_limit_s=180.0))
    telemetry = simulation.start()
    assert telemetry.time_s == 0.0
    with simulation.decision() as commander:
        commander.execute(FIRE_1)
    observed = []
    while (telemetry := simulation.advance()) is not None:
        observed.append(telemetry.time_s)
        with simulation.decision():
            pass
    assert observed == [60.0, 120.0, 180.0]
    assert simulation.result().final_state.delta_v_mps == pytest.approx(180.0 * ACCELERATION_MPS2)


def test_stepper_rejects_out_of_order_calls(make_scenario):
    simulation = Simulation(make_scenario())
    with pytest.raises(RuntimeError):
        simulation.advance()
    simulation.start()
    with pytest.raises(RuntimeError):
        simulation.start()
    with pytest.raises(RuntimeError):
        simulation.result()


def test_scenario_validates_timing(make_scenario, make_state):
    for overrides in ({"decision_period_s": -1.0}, {"time_limit_s": 0.0}):
        with pytest.raises(ValueError, match="positive"):
            make_scenario(**overrides)
    with pytest.raises(ValueError, match="time_s"):
        make_scenario(initial_state=make_state(time_s=5.0))


def test_noise_modifier_draws_only_from_the_seeded_rng(make_scenario):
    scenario = make_scenario(modifiers=[Noise()], time_limit_s=120.0)
    result = run(Strategy(), scenario, seed=1)
    true_temperature_c = {s.time_s: s.propulsion_temperature_c for s in result.trajectory}
    noise = [t.propulsion_temperature_c - true_temperature_c[t.time_s] for t in result.telemetry]
    rng = random.Random(1)
    assert noise == pytest.approx([rng.gauss(0.0, 1.0) for _ in result.telemetry])


def test_simulation_config_is_validated_defaulted_and_recorded(make_scenario):
    with pytest.raises(ValueError, match="positive"):
        SimulationConfig(integration_step_s=0.0)
    assert run(Strategy(), make_scenario(time_limit_s=60.0)).config == SimulationConfig()
    config = SimulationConfig(integration_step_s=5.0)
    assert run(Strategy(), make_scenario(time_limit_s=60.0), config=config).config is config
