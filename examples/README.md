# Examples

**English** | [日本語](README.ja.md)

These examples show how the strategy API behaves.
They run on a small toy problem defined in `toy_problem.py`,
which is deliberately different from the challenge problem and has loose limits.
They are not strategies for the challenge.

Run them from the repository root:

```sh
uv run python examples/timeline_basics.py
uv run python examples/telemetry_and_replanning.py
uv run python examples/planning_internal_model.py
uv run python examples/planning_external_file.py
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

## `planning_internal_model.py` and `planning_external_file.py`

These two strategies get their plan from a planning engine through [Unified Planning](https://unified-planning.readthedocs.io/).
Both solve the same abstract model, which only counts chunks of burning; it knows nothing about the spacecraft.
`planning_internal_model.py` builds the model in Python.
`planning_external_file.py` reads it from `toy_burn.anml`, using a path built from `Path(__file__)`.
`ANMLReader().parse_problem_string(text)` reads a model from a string instead,
and `PDDLReader` in `unified_planning.io` reads PDDL files.

`toy_planning.py` holds what they share, and they import it as a module next to them.
`solve` passes the names of several engines to `OneshotPlanner(names=...)`,
which runs them in parallel processes.
It adds a quality metric to the problem, because the call then returns the first plan;
without a metric, it waits for every engine to finish.
It uses the engines that are installed, because `up-tamer` has no packages for arm64 and `up-aries` covers more platforms.

The repository's development environment already has these packages.
To use them in a submission, add them to your project and put the files you need under `submission/`:

```sh
uv add unified-planning up-aries "up-tamer; platform_machine == 'x86_64'"
```

With version 1.3.0 of `unified-planning`, keep the following in mind:

- If one of the named engines cannot handle the problem, or is not installed, the whole call fails,
  even if another engine could solve it.
  So name only engines that suit your problem.
- `timeout` of `solve` has no effect with `OneshotPlanner(names=...)`, however many engines are named.
  If no engine finishes, the strategy waits until the time limit of the case, so keep the model small.
- The plan that returns first is not necessarily the best one, even with a quality metric.
- A warning that it cannot establish whether an engine can solve the problem is only a warning;
  that engine may still solve it.

## `toy_problem.py`

`toy_scenario()` builds the toy scenario, and `run_and_report(strategy)` runs a strategy on it and prints the result.
`timeline_basics.py` and `telemetry_and_replanning.py` import only the top-level `spacecraft_autonomy_challenge` package;
`toy_problem.py` also uses the simulation modules to build and run the scenario.
