"""Simulation stepping engine and the `run` driver.

`Simulation` exposes the event loop described in `docs/simulation.md` as explicit steps:

    simulation = Simulation(scenario)
    telemetry = simulation.start()
    with simulation.decision() as commander:
        ...  # initialize
    while (telemetry := simulation.advance()) is not None:
        with simulation.decision() as commander:
            ...  # update
    result = simulation.result()

`run` drives a `Strategy` through these steps. Custom drivers can use the same steps directly.
"""

import math
import random
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from functools import partial

from spacecraft_ops_challenge.commands import Command, CommandError, DeclareCompletion, SetHeater, SetPropulsionMode
from spacecraft_ops_challenge.config import SimulationConfig
from spacecraft_ops_challenge.model import SafetyLimits, SpacecraftState, integrate
from spacecraft_ops_challenge.modifiers import effective_parameters, effective_rates, observe
from spacecraft_ops_challenge.results import RunResult, SafetyViolation, Termination, TerminationReason
from spacecraft_ops_challenge.scenario import Scenario
from spacecraft_ops_challenge.strategy import Commander, MissionBrief, Strategy
from spacecraft_ops_challenge.telemetry import Telemetry
from spacecraft_ops_challenge.timeline import CommandId, ScheduledCommand, Timeline


def check_safety(state: SpacecraftState, limits: SafetyLimits) -> tuple[SafetyViolation, ...]:
    """Safety violations of `state`, ordered by termination priority."""
    violations = []
    temperature_c = state.propulsion_temperature_c
    if temperature_c > limits.max_propulsion_temperature_c:
        violations.append(
            SafetyViolation(
                TerminationReason.THERMAL_VIOLATION,
                state.time_s,
                f"propulsion temperature {temperature_c:.3f} C above {limits.max_propulsion_temperature_c} C",
            )
        )
    if state.battery_energy_wh < limits.min_battery_energy_wh:
        violations.append(
            SafetyViolation(
                TerminationReason.BATTERY_DEPLETED,
                state.time_s,
                f"battery energy {state.battery_energy_wh:.3f} Wh below {limits.min_battery_energy_wh} Wh",
            )
        )
    if abs(state.wheel_momentum_nms) > limits.max_abs_wheel_momentum_nms:
        violations.append(
            SafetyViolation(
                TerminationReason.MOMENTUM_VIOLATION,
                state.time_s,
                f"wheel momentum {state.wheel_momentum_nms:.4f} Nms exceeds +/-{limits.max_abs_wheel_momentum_nms} Nms",
            )
        )
    return tuple(violations)


class LocalCommander:
    """`Commander` backed directly by a simulation's timeline in the same process."""

    def __init__(self, timeline: Timeline, now_s: float) -> None:
        self._timeline: Timeline | None = timeline
        self._now_s = now_s

    @property
    def now_s(self) -> float:
        """Current simulation time in seconds."""
        self._open_timeline()
        return self._now_s

    def schedule(self, time_s: float, command: Command) -> CommandId:
        """Register `command` for execution at `time_s`, which must not be earlier than `now_s`."""
        return self._open_timeline().schedule(time_s, command, now_s=self._now_s)

    def execute(self, command: Command) -> CommandId:
        """Register `command` for immediate execution, equivalent to `schedule(now_s, command)`."""
        return self.schedule(self._now_s, command)

    def cancel(self, command_id: CommandId) -> bool:
        """Cancel a pending command. Returns `False` if it is unknown, executed, or already canceled."""
        return self._open_timeline().cancel(command_id)

    def cancel_from(self, time_s: float) -> tuple[CommandId, ...]:
        """Cancel all pending commands scheduled at or after `time_s` and return their identifiers."""
        return self._open_timeline().cancel_from(time_s)

    def pending(self) -> tuple[ScheduledCommand, ...]:
        """Pending commands in execution order."""
        return self._open_timeline().pending()

    def close(self) -> None:
        """End the commanding window; every member raises `CommandError` afterwards."""
        self._timeline = None

    def _open_timeline(self) -> Timeline:
        if self._timeline is None:
            raise CommandError("this commander is only valid during the callback it was passed to")
        return self._timeline


class Simulation:
    """One run of a scenario. Owns the true state, the timeline, and the run record."""

    def __init__(self, scenario: Scenario, *, config: SimulationConfig | None = None, seed: int | None = None) -> None:
        self.scenario = scenario
        self.config = SimulationConfig() if config is None else config
        self.seed = scenario.seed if seed is None else seed
        self._problem = scenario.problem
        self._rng = random.Random(self.seed)
        self._state = self._problem.initial_state
        self._timeline = Timeline()
        self._trajectory = [self._state]
        self._telemetry: list[Telemetry] = []
        self._executed: list[ScheduledCommand] = []
        self._violations: list[SafetyViolation] = []
        self._termination: Termination | None = None
        self._grid_steps = 0
        self._decisions = 0
        self._started = False
        self._in_decision = False

    @property
    def brief(self) -> MissionBrief:
        """Participant-visible mission information."""
        return self.scenario.brief()

    @property
    def time_s(self) -> float:
        """Current simulation time."""
        return self._state.time_s

    @property
    def done(self) -> bool:
        """Whether the run has terminated."""
        return self._termination is not None

    @property
    def termination(self) -> Termination | None:
        """How the run ended, or `None` while it is running."""
        return self._termination

    def start(self) -> Telemetry | None:
        """Check the initial state and return telemetry at time 0, or `None` if the run already ended."""
        if self._started:
            raise RuntimeError("simulation already started")
        self._started = True
        self._check_safety()
        return None if self.done else self._observe()

    @contextmanager
    def decision(self) -> Iterator[Commander]:
        """Open a commanding window at the current time.

        Commands registered for the current time execute when the window closes without an exception.
        Otherwise they execute at the start of the next `advance`.
        """
        if not self._started or self.done or self._in_decision:
            raise RuntimeError("a decision window requires a started, running simulation and no open window")
        commander = LocalCommander(self._timeline, self.time_s)
        self._in_decision = True
        try:
            yield commander
        finally:
            commander.close()
            self._in_decision = False
        self._execute_due()

    def advance(self) -> Telemetry | None:
        """Run until the next decision time and return telemetry there, or `None` once the run has ended."""
        if not self._started or self._in_decision:
            raise RuntimeError("advance requires a started simulation and no open decision window")
        self._execute_due()
        while not self.done:
            if self.time_s >= self._problem.time_limit_s:
                self._terminate(TerminationReason.TIME_LIMIT)
                break
            next_time_s, is_decision = self._next_event()
            self._integrate_to(next_time_s)
            self._check_safety()
            self._execute_due()
            if is_decision and not self.done:
                return self._observe()
        return None

    def abort(self, reason: TerminationReason, detail: str = "") -> None:
        """Terminate the run because of a failure outside the simulation, such as a strategy error."""
        if not self.done:
            self._terminate(reason, detail)

    def result(self) -> RunResult:
        """Record of the finished run."""
        if self._termination is None:
            raise RuntimeError("the run has not terminated yet")
        return RunResult(
            scenario=self.scenario,
            config=self.config,
            seed=self.seed,
            termination=self._termination,
            safety_violations=tuple(self._violations),
            final_state=self._state,
            trajectory=tuple(self._trajectory),
            telemetry=tuple(self._telemetry),
            executed_commands=tuple(self._executed),
        )

    def _next_event(self) -> tuple[float, bool]:
        next_grid_s = (self._grid_steps + 1) * self.config.integration_step_s
        next_decision_s = (self._decisions + 1) * self._problem.decision_period_s
        candidates = [next_grid_s, next_decision_s, self._problem.time_limit_s]
        next_command_s = self._timeline.next_time_s()
        if next_command_s is not None:
            candidates.append(next_command_s)
        next_time_s = min(candidates)
        if _same_time(next_grid_s, next_time_s):
            self._grid_steps += 1
        is_decision = _same_time(next_decision_s, next_time_s)
        if is_decision:
            self._decisions += 1
        if _same_time(self._problem.time_limit_s, next_time_s):
            next_time_s = self._problem.time_limit_s
        return next_time_s, is_decision

    def _integrate_to(self, time_s: float) -> None:
        state = self._state
        parameters = effective_parameters(self._problem.parameters, state, self.scenario.modifiers, self._rng)
        rates = effective_rates(state, parameters, self.scenario.modifiers, self._rng)
        state = integrate(state, rates, time_s - state.time_s, parameters)
        self._state = replace(state, time_s=time_s)
        self._trajectory.append(self._state)

    def _check_safety(self) -> None:
        violations = check_safety(self._state, self._problem.limits)
        if violations:
            self._violations.extend(violations)
            self._terminate(violations[0].reason, violations[0].message)

    def _execute_due(self) -> None:
        while not self.done and (scheduled := self._timeline.pop_due(self.time_s)) is not None:
            self._executed.append(scheduled)
            match scheduled.command:
                case SetPropulsionMode(mode=mode):
                    self._state = replace(self._state, propulsion_mode=mode)
                case SetHeater(on=on):
                    self._state = replace(self._state, heater_on=on)
                case DeclareCompletion():
                    self._terminate(TerminationReason.COMPLETION_DECLARED)

    def _observe(self) -> Telemetry:
        telemetry = observe(self._state, self.scenario.modifiers, self._rng)
        self._telemetry.append(telemetry)
        return telemetry

    def _terminate(self, reason: TerminationReason, detail: str = "") -> None:
        self._termination = Termination(reason, self.time_s, detail)


def _same_time(a_s: float, b_s: float) -> bool:
    """Whether two times are equal up to floating-point error in multiples of the step sizes."""
    return math.isclose(a_s, b_s, rel_tol=1e-12, abs_tol=1e-9)


def run(
    strategy: Strategy,
    scenario: Scenario,
    *,
    config: SimulationConfig | None = None,
    seed: int | None = None,
) -> RunResult:
    """Run `strategy` on `scenario` and return the result. An `Exception` from the strategy ends the run."""
    simulation = Simulation(scenario, config=config, seed=seed)
    telemetry = simulation.start()
    if telemetry is not None:
        _decide(simulation, partial(strategy.initialize, simulation.brief, telemetry))
    while (telemetry := simulation.advance()) is not None:
        _decide(simulation, partial(strategy.update, telemetry))
    return simulation.result()


def _decide(simulation: Simulation, callback: Callable[[Commander], None]) -> None:
    try:
        with simulation.decision() as commander:
            callback(commander)
    except CommandError:
        simulation.abort(TerminationReason.INVALID_COMMAND, traceback.format_exc())
    except Exception:
        simulation.abort(TerminationReason.STRATEGY_ERROR, traceback.format_exc())
