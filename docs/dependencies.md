# Participant Packages

**English** | [日本語](dependencies.ja.md)

This page describes how the packages that a submission needs are reproduced (`spacecraft_ops_challenge.judge.dependencies`).
A submission lists them in the optional `pyproject.toml` of its archive (see [Submission Archives](submission.md)).

```python
from pathlib import Path

from spacecraft_ops_challenge.judge.dependencies import resolve_dependencies
from spacecraft_ops_challenge.judge.submission import extract_submission

submission = extract_submission("submission.zip", Path("work/extracted"))
report, overlay = resolve_dependencies(submission.pyproject, Path("work/overlay"))
env = None if overlay is None else overlay.environment()
```

The environment that evaluates the submission is never modified.
Each requirement is checked against it, and only what it lacks is installed into a separate directory, the `Overlay`.
Installing requires [uv](https://docs.astral.sh/uv/) on `PATH` at run time.
Without anything to install, uv is not needed.

`DependencyError`, a subclass of `ValueError`, is raised for a `pyproject.toml` that cannot be read,
for requirements that cannot be reproduced, and for a failed installation.

## Requirements

The requirements are the entries of `[project] dependencies` of the participant's `pyproject.toml`,
which `parse_requirements` reads.
Without a `pyproject.toml`, the submission runs in the evaluating environment as it is.

Each requirement gets one `Decision` against the evaluating environment:

| Decision | When |
|---|---|
| `NOT_APPLICABLE` | Its environment marker is false for the evaluating interpreter |
| `JUDGE_CONTROLLED` | It is `spacecraft-operations-challenge-core` |
| `SATISFIED` | The installed version and extras satisfy it, or it is installed from the same URL |
| `INSTALL` | It is missing, its version or extras are not satisfied, or it names another URL |
| `UNSUPPORTED` | It, its `[tool.uv.sources]` entry, or a dependency of a requested extra cannot be reproduced, or its environment marker cannot be evaluated |

- The evaluating environment always uses its own core package,
  and the reason says whether the participant's reference to the core matches it.
- A `file://` package counts as satisfied, whatever its path,
  if the evaluating environment has a package of that name that was itself installed from a local file.
  Otherwise it is installed if the file exists, and is `UNSUPPORTED` if not.
- A direct reference by a relative path, such as `helper @ ../helper`, is `UNSUPPORTED`,
  because the path would be resolved against the evaluating machine instead of the participant's project.
- URL requirements match only with the same subdirectory.
- For an installed package that lacks the dependencies of a requested extra, only those dependencies are installed.
  Dependencies of extras are decided like any other requirement.

`decide` makes the decision for one requirement, and `plan_dependencies` for all of them, in order, as a `DependencyPlan`.
Any `UNSUPPORTED` requirement stops `resolve_dependencies` with a message that names it and the reason.

## Sources from `[tool.uv.sources]`

`uv add` records a package from a source other than an index,
such as `uv add git+https://example.com/lib.git --tag v1`,
as a bare name in `[project] dependencies` and the source in `[tool.uv.sources]`
(see [Dependency sources](https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-sources) in the uv documentation).
Without the source, the name alone could resolve to an unrelated package of the same name on the default index.
`parse_sources` reads the entries, keyed by normalized package name, and the requirement of the same name uses its entry:

| Entry | Result |
|---|---|
| `{ git = URL }`, with at most one of `tag`, `branch`, or `rev`, and an optional `subdirectory` | `name[extras] @ git+URL@REVISION#subdirectory=SUBDIRECTORY ; marker` |
| `{ url = URL }`, with an optional `subdirectory` | `name[extras] @ URL#subdirectory=SUBDIRECTORY ; marker` |
| `{ path = ... }` or `{ workspace = ... }` | `UNSUPPORTED`: put that code under `submission/` or publish the package |
| `{ index = ... }` | `UNSUPPORTED`: the named index is not used, and the default index may provide a different package |
| A list of sources, or any other entry or key | `UNSUPPORTED` |

- The rewritten requirement keeps the extras and the environment marker of the original requirement.
  It drops a version specifier, which a URL requirement cannot carry.
- A `git` URL may start with `git+`.
  URLs must not contain whitespace, `;`, or `#`, and revisions and subdirectories must not contain `@`, `&`, or `?` either;
  such an entry is `UNSUPPORTED` rather than turned into a different requirement.
- An entry with a `marker` applies only if the marker is true for the evaluating interpreter;
  otherwise the requirement is decided as written.
- The decision of a rewritten requirement names the rewritten requirement, and its reason names the original one.
- The core requirement stays `JUDGE_CONTROLLED` whatever its source,
  and a requirement whose marker is false stays `NOT_APPLICABLE`.
- Entries for packages that `[project] dependencies` does not name are ignored.
- Two entries whose names normalize to the same package, such as `foo_bar` and `Foo-Bar`, raise `DependencyError`.

## Installing into the `Overlay`

The `INSTALL` requirements are installed once per submission with `uv pip install --target` into a new directory.
`install_overlay` does this, and `resolve_dependencies` calls it only when there is something to install.
uv runs with `--no-config`, so configuration files around the directory do not change the installation.
It runs with the environment variables given as `env`, or those of the current process by default.

- The first attempt is constrained to the versions of the packages that the evaluating environment installed from an index
  (`base_constraints`), so the `Overlay` does not shadow them with other versions.
- If that cannot be resolved, the installation is retried without these constraints.
- Both attempts are also constrained to the version requirements that the evaluating environment already satisfies,
  including dependencies of requested extras.
- An attempt that takes longer than `timeout_s` (default `DEFAULT_INSTALL_TIMEOUT_S`, 900 s) fails.

After the installation, `DependencyError` is raised if the `Overlay` contains a module of the core package
(`PROTECTED_MODULES`), or if it replaces a package that the participant's `pyproject.toml` names by URL
and the evaluating environment already has from that URL.

The returned `Overlay` holds the directory and the installer runs.
`Overlay.environment(base)` returns `base` (default: the current process environment) with the directory first on `PYTHONPATH`,
for the processes that run the participant's code;
their packages then take precedence over those of the evaluating environment.

## Reports

`resolve_dependencies(pyproject, target)` returns a `DependencyReport` and the `Overlay`, or `None` if nothing was installed.
The report holds the `DependencyPlan`, or `None` without a `pyproject.toml`, and every `InstallAttempt`.

`to_dict()` of the report, the plan, a decision (`RequirementDecision`), and an attempt returns JSON-serializable data,
and `from_dict` is its inverse.
The constraints and preserved packages of a decision, which only the installation uses, are not part of it.
