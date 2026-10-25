# Commands and Timeline

**English** | [日本語](timeline.ja.md)

This page describes the command types in `spacecraft_ops_challenge.commands` and the timeline in `spacecraft_ops_challenge.timeline`.

## Commands

| Command | Effect |
|---|---|
| `SetPropulsionMode(mode)` | Selects the propulsion mode: `PropulsionMode.OFF`, `THRUSTER_1`, or `THRUSTER_2` |
| `SetHeater(on)` | Switches the propulsion heater on (`True`) or off (`False`) |
| `DeclareCompletion()` | Declares that the strategy considers the maneuver complete, which ends the run; it says nothing about success |

The propulsion mode is exclusive: selecting one thruster implicitly stops the other,
so both thrusters never fire at the same time.

Commands are immutable dataclasses.
`SetPropulsionMode` also accepts a mode name such as `"THRUSTER_1"`.
Invalid values raise `CommandError`, a subclass of `ValueError`.

## Timeline

A `Timeline` holds commands scheduled for future execution.
Times are seconds of simulation time.

| Method | Behavior |
|---|---|
| `schedule(time_s, command, now_s=...)` | Registers `command` for `time_s` and returns its `CommandId` |
| `cancel(command_id)` | Removes a pending command and returns `True`; returns `False` if it is unknown, executed, or canceled |
| `cancel_from(time_s)` | Cancels every pending command scheduled at or after `time_s` and returns their identifiers |
| `pending()` | Returns a tuple of the pending `ScheduledCommand` objects in execution order |
| `next_time_s()` | Returns the time of the next pending command, or `None` |
| `pop_due(now_s)` | Removes and returns the next command due at or before `now_s`, or `None` |

### Rules

- `schedule` raises `CommandError` if `time_s` is earlier than `now_s`, not finite, or not a number,
  or if the command is not one of the command types.
- A command may be scheduled for exactly `now_s`.
- Command identifiers are positive integers assigned sequentially from 1 in registration order and are never reused.
- Commands execute in order of time; commands with equal times execute in registration order.
- `cancel` never raises for identifiers that are not pending.
- `cancel_from` is inclusive: a command scheduled exactly at `time_s` is canceled.
