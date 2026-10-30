# Writing a Strategy

**English** | [日本語](strategy.ja.md)

A strategy operates the spacecraft by scheduling commands on its timeline.
It receives only a `MissionBrief`, `Telemetry`, and a `Commander`; it never sees the true spacecraft state.
All of these are exported from the top-level `spacecraft_autonomy_challenge` package.

```python
from spacecraft_autonomy_challenge import Commander, MissionBrief, SetHeater, Strategy, Telemetry


class MyStrategy(Strategy):
    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        self.heater_command = commander.schedule(600.0, SetHeater(on=True))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        print(telemetry.time_s, telemetry.heater_on)
        if telemetry.time_s >= 300.0:
            commander.cancel(self.heater_command)
```

## Lifecycle

1. `initialize(brief, telemetry, commander)` is called once at simulation time 0.
2. `update(telemetry, commander)` is called at every decision time `k * brief.decision_period_s` for `k >= 1`
   until the run ends.

The `telemetry` passed to `update` is sampled before the commands that `update` registers execute.
It reflects the state at that time after the previously scheduled commands,
and the earliest telemetry that can show the effect of a registered command is the next call's.
See [Order of Events](simulation.md#order-of-events).

Both callbacks are optional.
A strategy that follows a fixed command sequence can schedule the whole sequence in `initialize` and leave `update` empty;
scheduled commands execute at their times without any further callbacks.
An adaptive strategy can schedule and cancel commands during `update`.

## Mission Brief

`MissionBrief` contains the target delta-v, the time limit, the decision period, the `SafetyLimits`,
the nominal `SpacecraftParameters` (`nominal_parameters`),
and the ideal `Telemetry` of the nominal initial state (`nominal_initial_telemetry`).
The actual spacecraft may deviate from the nominal parameters and the nominal initial state,
and telemetry may deviate from the true state;
strategies can only infer such deviations from telemetry.

## Commander

`Commander` is an interface (a `typing.Protocol`).
A strategy should rely only on the members below.
The simulation passes `spacecraft_autonomy_challenge.simulation.LocalCommander`,
which works directly on its timeline in the same process.
All requests and results are plain data: times, commands, command identifiers, and `ScheduledCommand` values.

| Member | Behavior |
|---|---|
| `now_s` | Current simulation time in seconds |
| `schedule(time_s, command)` | Registers a command for `time_s` (not earlier than `now_s`) and returns its `CommandId` |
| `execute(command)` | Same as `schedule(now_s, command)` |
| `cancel(command_id)` | Cancels a pending command; returns whether it was pending |
| `cancel_from(time_s)` | Cancels all pending commands at or after `time_s`; returns their identifiers |
| `pending()` | Returns the pending commands in execution order |

`cancel_from(now_s)` followed by new `schedule` calls replaces the rest of the timeline.

A commander is valid only during the callback it was passed to; using any of its members later raises `CommandError`.
No command executes while a callback runs.
Commands scheduled for `now_s` execute right after the callback returns, before simulation time advances.

See [Commands and Timeline](timeline.md) for the command types and ordering rules.

## Errors

- An invalid request, such as a time in the past, raises `CommandError`.
  A strategy may catch it and continue.
- An uncaught `CommandError` ends the run with `INVALID_COMMAND`.
- Any other uncaught exception ends the run with `STRATEGY_ERROR`.
