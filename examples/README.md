# Examples

These examples show how the strategy API behaves.
They run on a small toy problem defined in `toy_problem.py`,
which is deliberately different from the challenge problem and has loose limits.
They are not strategies for the challenge.

Run them from the repository root:

```sh
uv run python examples/timeline_basics.py
uv run python examples/telemetry_and_replanning.py
```

Each script prints the commands that executed, how the run ended, and the true delta-v.

## `timeline_basics.py`

`TimelineBasics` registers its whole command timeline in `initialize` and does not override `update`.
The simulation executes every command at its scheduled time without further callbacks.
It also shows that selecting the other thruster stops the first one,
and that commands with the same time execute in registration order.

## `telemetry_and_replanning.py`

`TelemetryAndReplanning` starts a thruster immediately with `execute` and schedules a tentative stop far in the future.
At each `update` it prints the telemetry it receives.
At 60 s it cancels the tentative stop by its identifier,
cancels everything from the current time onward with `cancel_from`, and registers a replacement plan that ends with `DeclareCompletion`.

## `toy_problem.py`

`toy_scenario()` builds the toy scenario, and `run_and_report(strategy)` runs a strategy on it and prints the result.
The strategy files import only the top-level `spacecraft_ops_challenge` package;
`toy_problem.py` also uses the simulation modules to build and run the scenario.
