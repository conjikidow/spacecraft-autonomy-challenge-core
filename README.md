# spacecraft-operations-challenge-core

[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)

Python package for a spacecraft operations challenge.
The distribution name is `spacecraft-operations-challenge-core` and the import package is `spacecraft_ops`.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)

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
