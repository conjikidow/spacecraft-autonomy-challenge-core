# Spacecraft Autonomy Challenge: Core

[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat)](LICENSE)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)

**English** | [日本語](README.ja.md)

Python package for the Spacecraft Autonomy Challenge.
You write a strategy that operates a simulated spacecraft:
it reads telemetry and schedules commands
so that the spacecraft accumulates a target delta-v without violating thermal, power, or momentum limits.

The package provides the strategy API, a small parameterized reference simulator,
the challenge problem with its public scenarios, per-run evaluation metrics, and a command-line runner.
The spacecraft model is a generic toy model and does not represent any particular spacecraft or mission.
The distribution name is `spacecraft-autonomy-challenge-core` and the import package is `spacecraft_autonomy_challenge`.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)
- Linux or macOS for evaluating submissions (see [Running Cases](docs/runner.md))

Beyond the Python standard library, the package depends only on [packaging](https://packaging.pypa.io/) at run time.
The optional `marimo` extra adds [marimo](https://marimo.io) for the result views.

## Installation

Add the package to another uv project from Git, optionally pinned with `--tag` or `--rev`:

```sh
uv add git+https://github.com/conjikidow/spacecraft-autonomy-challenge-core
```

To use the result views, add it with the `marimo` extra instead (see [Result Views](docs/views.md)):

```sh
uv add "spacecraft-autonomy-challenge-core[marimo] @ git+https://github.com/conjikidow/spacecraft-autonomy-challenge-core"
```

## Quick Start

List the challenge scenarios and run an API example from the repository root:

```sh
uv run autonomy-challenge scenarios
uv run python examples/timeline_basics.py
```

The examples run on a small toy problem and show how the API behaves; see [examples/](examples/README.md).

## Writing a Strategy

Subclass `Strategy` and override `initialize`, `update`, or both:

```python
from spacecraft_autonomy_challenge import Commander, MissionBrief, SetHeater, Strategy, Telemetry


class MyStrategy(Strategy):
    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        print(brief.target_delta_v_mps, brief.time_limit_s)
        commander.schedule(600.0, SetHeater(on=True))

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        print(telemetry)
```

Run it on a challenge scenario with `uv run autonomy-challenge run my_strategy.py:MyStrategy`.
The command prints how the run ended and its metrics.
See [Writing a Strategy](docs/strategy.md) for the full API.

## Command-Line Runner

```text
autonomy-challenge run STRATEGY [--scenario NAME] [--seed N] [--json]
autonomy-challenge scenarios
autonomy-challenge pack [PROJECT_DIR] [-o FILE]
autonomy-challenge check [SUBMISSION] [--timeout SECONDS] [--scoring TOML] [--json]
```

`python -m spacecraft_autonomy_challenge` is equivalent to `autonomy-challenge`.

### `run` and `scenarios`

`run` runs a strategy on one challenge scenario and prints its metrics, and `scenarios` lists the challenge scenarios.

`STRATEGY` is `FILE.py:CLASS` or `MODULE:CLASS`, where `CLASS` is a `Strategy` subclass
with a constructor that takes no arguments.
For a file, its directory is put first on the import path, so a strategy can be split across several modules.
For a module, the current directory is put on the import path.

`--scenario` selects a challenge scenario (default `nominal`), `--seed` overrides the scenario seed,
and `--json` prints the metrics as JSON.
With `--json`, anything the strategy prints goes to standard error, so standard output stays valid JSON.

| Exit status | Meaning |
|---|---|
| 0 | The run finished, whether or not the target was reached |
| 1 | The strategy raised an exception or made an invalid timeline request during the run |
| 2 | Usage error, such as a strategy or scenario that cannot be found |
| 130 | Interrupted, for example with Ctrl-C |

### `pack` and `check`

These commands work on a project directory that contains `submission/strategy.py` with the strategy class `MyStrategy`
(see [Submission Archives](docs/submission.md)).

`pack` builds `submission.zip` from `PROJECT_DIR` (default: the current directory)
and writes it to `FILE` (default: `submission.zip` in the current directory).
An existing `FILE` is replaced.
`FILE` must not be inside the `submission/` directory of the project.
`pack` prints the path, size, SHA-256, and number of entries of the archive.

`check` evaluates a submission on the public scenarios, one case per scenario,
in the same way as any evaluation of a submission archive (see [Evaluating Submissions](docs/evaluating.md)).
`SUBMISSION` is a project directory (default: the current directory), which is packed in memory exactly like `pack`,
or a `submission.zip` file, which is read as it is.
`--timeout` sets the wall-clock limit of one case (default 300 s),
and `--scoring` reads the scoring configuration from a TOML file instead of the shipped one (see [Scoring](docs/scoring.md)).
Progress goes to standard error.
`check` then prints the `SUBMISSION` path and the SHA-256 of the archive,
the archive entries that were skipped and the packages that were installed for the submission, if any;
the suite score and the other summary statistics,
and a table of the cases with its numeric columns aligned to the right;
details of the cases that did not complete or ended with a strategy failure;
the modules that the submission failed to import;
and the last lines that the strategy printed to standard output and standard error in each case.
`--json` prints the JSON result document instead.

| Exit status | Meaning |
|---|---|
| 0 | `pack` wrote the archive; `check` completed every case without a strategy error or an invalid command, whatever the scores |
| 1 | `check` only: a case did not load, crashed, or timed out, or its run ended with a strategy error or an invalid command |
| 2 | Usage error, such as an invalid project or archive, packages that cannot be reproduced, an invalid scoring configuration, or a file that cannot be read or written |
| 130 | Interrupted, for example with Ctrl-C; the processes of the running case are stopped |

## Documentation

- [Writing a Strategy](docs/strategy.md): strategy lifecycle, mission brief, and commander
- [Commands and Timeline](docs/timeline.md): command types and timeline ordering rules
- [Spacecraft Model](docs/spacecraft-model.md): state, dynamics, telemetry, and modifiers
- [Simulation](docs/simulation.md): problems, scenarios, order of events, termination, and run results
- [Challenge Problem](docs/challenge.md): the challenge problem and its public scenarios
- [Evaluation](docs/evaluation.md): per-run metrics
- [Submission Archives](docs/submission.md): building and extracting `submission.zip`
- [Evaluation Cases](docs/judge.md): evaluation cases, suites, and scenario providers
- [Participant Packages](docs/dependencies.md): reproducing the packages that a submission needs with uv
- [Running Cases](docs/runner.md): running a submission on each case in separate trusted and participant processes
- [Evaluating Submissions](docs/evaluating.md): evaluating a submission archive, summary statistics, and JSON result documents
- [Scoring](docs/scoring.md): the scoring formula and its configuration
- [Result Views](docs/views.md): marimo views of result documents and dependency reports

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
