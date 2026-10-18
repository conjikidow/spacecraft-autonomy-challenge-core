# python-repository-template

[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![prek](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/j178/prek/master/docs/assets/badge-v0.json)](https://github.com/j178/prek)

This is a template repository for Python projects.

## GitHub Actions Permissions Setup

The version-bump workflow creates pull requests, which requires the following setting to be enabled:

1. Go to the **Settings** tab of your repository.
2. On the left-hand menu, select **Actions/General**.
3. Under the **Workflow permissions** section, enable **`Allow GitHub Actions to create and approve pull requests`**.
4. Save the changes.

## Project Name Setup

Replace `project-name` with your project name in the following files:

- `pyproject.toml`

  ```toml
  [project]
  name = "project-name"  # Replace with your project name
  version = "0.1.0"
  description = "Add your description here"
  readme = "README.md"
  requires-python = ">=3.13"
  dependencies = []
  ```

- `.bumpversion.toml`

  ```toml
  [[tool.bumpversion.files]]
  filename = "uv.lock"
  search = 'name = "project-name"\nversion = "{current_version}"'  # Replace with your project name
  replace = 'name = "project-name"\nversion = "{new_version}"'     # Replace with your project name
  regex = true
  ```

## Pre-commit Hooks Setup

This template recommends using [`prek`](https://prek.j178.dev) (a faster, drop-in alternative to [`pre-commit`](https://pre-commit.com)).

Install `prek` by following its [installation guide](https://prek.j178.dev/installation/), then install the hooks:

```sh
prek install
```

If you prefer `pre-commit`, [install it](https://pre-commit.com/#install) and run:

```sh
pre-commit install
```

The hook types to install are set by `default_install_hook_types` in `.pre-commit-config.yaml`.

## Commit Message Linting with Commitizen

This template repository enforces [Conventional Commits](https://www.conventionalcommits.org) in pre-commit hooks and CI,
so your commit messages must follow that format.

You can maintain Conventional Commits manually, but automation tools such as Commitizen or cz-git can help.
Any tool is fine, but this repository uses [commitizen-tools/commitizen](https://github.com/commitizen-tools/commitizen)
for checks, so it is recommended.

Install Commitizen:

```sh
uv tool install commitizen
```

Use Commitizen instead of `git commit`:

```sh
cz commit
```

For more details, see [Commitizen documentation](https://commitizen-tools.github.io/commitizen).

## Version Bumping by Labels

This repository is configured to automatically bump the version
when a pull request is merged with one of the following labels:

- `update::major`
- `update::minor`
- `update::patch`

Simply add one of these labels to your pull request before merging.
A new pull request for the version bump will be automatically created.

The version number is managed via the `.bumpversion.toml` file in the repository root.
For more details, see [conjikidow/bump-version-action](https://github.com/conjikidow/bump-version-action).
