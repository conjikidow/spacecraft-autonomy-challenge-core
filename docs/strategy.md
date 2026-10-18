# Writing a Strategy

A strategy operates the spacecraft by scheduling commands on its timeline.
It receives only a `MissionBrief`, `Telemetry`, and a `Commander`; it never sees the true spacecraft state.
All of these are exported from the top-level `spacecraft_ops` package.

```python
from spacecraft_ops import Commander, MissionBrief, PropulsionMode, SetPropulsionMode, Strategy, Telemetry


class MyStrategy(Strategy):
    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        commander.schedule(600.0, SetPropulsionMode(PropulsionMode.THRUSTER_1))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        if telemetry.propulsion_temperature_c > 50.0:
            commander.execute(SetPropulsionMode(PropulsionMode.OFF))
```

## Lifecycle

1. `initialize(brief, telemetry, commander)` is called once at simulation time 0.
2. `update(telemetry, commander)` is called at every decision time `k * brief.decision_period_s` for `k >= 1`
   until the run ends.

Both callbacks are optional.
A strategy that follows a fixed command sequence can schedule the whole sequence in `initialize` and leave `update` empty;
scheduled commands execute at their times without any further callbacks.
An adaptive strategy can schedule and cancel commands during `update`.

## Mission Brief

`MissionBrief` contains the target delta-v, the time limit, the decision period, the `SafetyLimits`, and the nominal `SpacecraftParameters`.
The actual spacecraft may deviate from the nominal parameters, and telemetry may deviate from the true state;
strategies can only infer such deviations from telemetry.

## Commander

| Member | Behavior |
|---|---|
| `now_s` | Current simulation time in seconds |
| `schedule(time_s, command)` | Registers a command for `time_s` (not earlier than `now_s`) and returns its `CommandId` |
| `execute(command)` | Same as `schedule(now_s, command)` |
| `cancel(command_id)` | Cancels a pending command; returns whether it was pending |
| `cancel_from(time_s)` | Cancels all pending commands at or after `time_s`; returns their identifiers |
| `pending()` | Returns the pending commands in execution order |

`cancel_from(now_s)` followed by new `schedule` calls replaces the rest of the timeline.

A commander is valid only during the callback it was passed to; using it later raises `CommandError`.
No command executes while a callback runs.
Commands scheduled for `now_s` execute right after the callback returns, before simulation time advances.

See [Commands and Timeline](timeline.md) for the command types and ordering rules.

## Errors

- An invalid request, such as a time in the past, raises `CommandError`.
  A strategy may catch it and continue.
- An uncaught `CommandError` ends the run with `INVALID_COMMAND`.
- Any other uncaught exception ends the run with `STRATEGY_ERROR`.
