# Simulation

This page describes problems (`spacecraft_ops.problem`), scenarios (`spacecraft_ops.scenario`),
simulation settings (`spacecraft_ops.config`), the simulation (`spacecraft_ops.simulation`),
and run results (`spacecraft_ops.results`).

## Problem

A `Problem` is the fixed task that all of its scenarios share:

| Field | Meaning |
|---|---|
| `parameters` | Published nominal `SpacecraftParameters` |
| `initial_state` | `SpacecraftState` at time 0 |
| `limits` | `SafetyLimits` |
| `target_delta_v_mps` | Delta-v goal |
| `time_limit_s` | Time at which the run ends |
| `decision_period_s` | Period of strategy updates |

`problem.brief()` returns the `MissionBrief` given to the strategy.

## Scenario

A `Scenario` is one variant of a problem:

| Field | Meaning |
|---|---|
| `name`, `description` | Identification |
| `problem` | The `Problem` |
| `modifiers` | `Modifier` sequence applied during the run |
| `seed` | Seed of the run's random number generator |

A scenario without modifiers behaves exactly as the nominal model.
`scenario.brief()` is the brief of its problem, so every scenario of a problem looks the same to a strategy.

## Simulation Settings

`SimulationConfig` holds settings that affect numerical accuracy only.
Its single field, `integration_step_s`, is the maximum step of the explicit Euler integrator and defaults to 1 s.
Strategies never see it.

## Running a Strategy

```python
from spacecraft_ops.simulation import run

result = run(MyStrategy(), scenario)
print(result.termination.reason, result.final_state.delta_v_mps)
```

`run(strategy, scenario, config=None, seed=None)` uses the default `SimulationConfig` when `config` is `None`
and overrides the scenario seed when `seed` is given.
An `Exception` raised by the strategy does not propagate out of `run`; it ends the run instead.

## Time

Three time scales are independent:

- The integration step: the maximum step of the explicit Euler integrator.
- The decision period: the interval between `update` calls.
- Command times: any time chosen by the strategy.

The integrator splits its step at command and decision times, so commands take effect at exactly their scheduled time.
Integration grid points, decision times, and the time limit are compared with a small tolerance,
so floating-point error in multiples such as `3 * 0.1` does not skip a decision.

## Order of Events

At every event time `t` the simulation:

1. Integrates the true state up to `t`, applying the modifiers' parameter and rate hooks.
2. Checks the safety limits against the true state; a violation ends the run.
3. Executes pending commands due at `t` in timeline order; `DeclareCompletion` ends the run.
4. At a decision time, samples telemetry through the modifiers' telemetry hooks, calls `update`,
   and executes the commands it registered for `t`.
5. Ends the run with `TIME_LIMIT` if `t` has reached the time limit.
   Commands and the decision at exactly the time limit still take effect.
   Commands scheduled after the time limit never execute.

The next event time is the earliest of the next integration step, the next decision time,
the next pending command, and the time limit.

At time 0 the simulation checks the initial state, samples telemetry, calls `initialize`, and executes immediate commands.

## Termination

| `TerminationReason` | Cause |
|---|---|
| `COMPLETION_DECLARED` | A `DeclareCompletion` command executed; the strategy declared completion, which does not imply success |
| `TIME_LIMIT` | The time limit was reached |
| `THERMAL_VIOLATION` | Propulsion temperature left the allowed range |
| `BATTERY_DEPLETED` | Battery energy fell below the minimum |
| `MOMENTUM_VIOLATION` | Absolute wheel momentum exceeded the maximum |
| `STRATEGY_ERROR` | The strategy raised an exception |
| `INVALID_COMMAND` | The strategy raised an uncaught `CommandError` |

When several safety limits are violated at once, all violations are recorded and the reason follows the order of this table.

## Run Result

`RunResult` contains:

- `scenario`, `config`, and `seed`
- `termination`: reason, time, and detail (a message or traceback)
- `safety_violations`
- `final_state`
- `trajectory`: the true state at time 0 and at every event time, sampled after integration and before commands
- `telemetry`: every telemetry sample given to the strategy
- `executed_commands`

## Stepping Interface

`Simulation` exposes the same loop as explicit steps, for drivers other than `run`:

```python
from spacecraft_ops.config import SimulationConfig
from spacecraft_ops.simulation import Simulation

simulation = Simulation(scenario, config=SimulationConfig(), seed=0)
telemetry = simulation.start()
with simulation.decision() as commander:
    commander.execute(command)
while (telemetry := simulation.advance()) is not None:
    with simulation.decision() as commander:
        ...
result = simulation.result()
```

- `start()` returns the telemetry at time 0, or `None` if the initial state violates a limit.
- `decision()` opens a commanding window at the current time and yields a `LocalCommander`;
  commands for the current time execute when it closes.
  If the window exits with an exception, they execute at the start of the next `advance()` instead.
- `advance()` runs to the next decision time and returns its telemetry, or `None` once the run has ended.
- `abort(reason, detail)` ends the run from outside, for example after a strategy error.
- `result()` returns the `RunResult` after the run has ended.
