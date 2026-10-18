# spacecraft-operations-challenge-core

[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)

Python package for a spacecraft operations challenge.
You write a strategy that operates a simulated spacecraft:
it reads telemetry and schedules commands
so that the spacecraft accumulates a target delta-v without violating thermal, power, or momentum limits.

The package provides the strategy API, a small parameterized reference simulator,
reference scenarios, per-run evaluation metrics, and a command-line runner.
The spacecraft model is a generic toy model and does not represent any particular spacecraft or mission.
The distribution name is `spacecraft-operations-challenge-core` and the import package is `spacecraft_ops`.

The project is in early development (version 0.1.0); the API may still change.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)

The package has no runtime dependencies beyond the Python standard library.

## Installation

Add the package to another uv project from Git, optionally pinned to a tag or commit:

```sh
uv add "spacecraft-operations-challenge-core @ git+https://github.com/conjikidow/spacecraft-operations-challenge-core"
```

## Quick Start

List the reference scenarios and run an example strategy from the repository root:

```sh
uv run spacecraft-ops scenarios
uv run spacecraft-ops run examples/reactive.py:ReactiveStrategy --scenario thruster-degradation
```

The output summarizes how the run ended and its metrics:

```text
scenario:             thruster-degradation (seed 0)
termination:          MISSION_COMPLETE at 13640.0 s
completed:            True
safe:                 True
delta-v:              10.0000 m/s (target 10.0000, error +0.0000)
completion time:      13640.0 s
min battery energy:   65.67 Wh
temperature range:    20.00 .. 52.04 C
max |wheel momentum|: 4.0000 Nms
reference score:      0.8737
```

## Writing a Strategy

Subclass `Strategy` and override `initialize`, `update`, or both:

```python
from spacecraft_ops import Commander, MissionBrief, PropulsionMode, SetPropulsionMode, Strategy, Telemetry


class MyStrategy(Strategy):
    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        commander.execute(SetPropulsionMode(PropulsionMode.THRUSTER_1))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        if telemetry.propulsion_temperature_c > 50.0:
            commander.execute(SetPropulsionMode(PropulsionMode.OFF))
```

Run it with `uv run spacecraft-ops run my_strategy.py:MyStrategy`.
See [examples/](examples/README.md) for an open-loop and a closed-loop strategy.

## Command-Line Runner

```text
spacecraft-ops run STRATEGY [--scenario NAME] [--seed N] [--json]
spacecraft-ops scenarios
```

`STRATEGY` is `FILE.py:CLASS` or `MODULE:CLASS`, where `CLASS` is a `Strategy` subclass
with a constructor that takes no arguments.
For a file, its directory is put first on the import path, so a strategy can be split across several modules.
For a module, the current directory is put on the import path.

`--scenario` selects a reference scenario (default `nominal`), `--seed` overrides the scenario seed,
and `--json` prints the metrics as JSON.
`python -m spacecraft_ops` is equivalent to `spacecraft-ops`.

| Exit status | Meaning |
|---|---|
| 0 | The run finished, whether or not the mission succeeded |
| 1 | The strategy raised an exception or made an invalid timeline request |
| 2 | Usage error, such as a strategy or scenario that cannot be found |

## Documentation

- [Writing a Strategy](docs/strategy.md): strategy lifecycle, mission brief, and commander
- [Commands and Timeline](docs/timeline.md): command types and timeline ordering rules
- [Spacecraft Model](docs/spacecraft-model.md): state, dynamics, telemetry, and modifiers
- [Simulation](docs/simulation.md): scenarios, order of events, termination, and run results
- [Reference Scenarios](docs/reference-scenarios.md): the built-in scenarios
- [Evaluation](docs/evaluation.md): per-run metrics and the reference score

## Development

Install the project and its development dependencies:

```sh
uv sync
```

Run the tests:

```sh
uv run pytest
```

Install and run the Git hooks with [`prek`](https://prek.j178.dev):

```sh
prek install
prek run --all-files
```

Build the wheel and the source distribution into `dist/`:

```sh
uv build
```

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org), checked by Commitizen in the hooks.

## Versioning

Merging a pull request labeled `update::major`, `update::minor`, or `update::patch`
makes the `bump-version` workflow open a version-bump pull request.
Merging that pull request creates the `vX.Y.Z` tag and a GitHub Release.
The workflow needs **Allow GitHub Actions to create and approve pull requests** enabled
under **Settings > Actions > General > Workflow permissions**.
