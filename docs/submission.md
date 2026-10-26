# Submission Archives

**English** | [日本語](submission.ja.md)

This page describes submission archives (`spacecraft_ops_challenge.judge.submission`).
A submission archive, `submission.zip`, packs a strategy together with its supporting files.

```python
from pathlib import Path

from spacecraft_ops_challenge.judge.submission import build_submission, extract_submission

Path("submission.zip").write_bytes(build_submission("."))
submission = extract_submission("submission.zip", Path("extracted"))
print(submission.strategy_file, submission.pyproject is not None)
```

On the command line, `spacecraft-ops-challenge pack` builds `submission.zip` from a project directory
(see the [README](../README.md#command-line-runner)).

## Archive Layout

The archive mirrors the root of the project it was built from:

| Entry | Meaning |
|---|---|
| `submission/strategy.py` | Entry point; it defines the strategy class `MyStrategy` |
| `submission/...` | Any supporting files, such as further modules, data, or model files |
| `pyproject.toml` | Optional `pyproject.toml` of the project, which lists the packages the submission needs (see [Participant Packages](dependencies.md)) |

The constants `SUBMISSION_DIRNAME`, `STRATEGY_PATH`, `STRATEGY_CLASS`, and `PYPROJECT_PATH` hold these names.

## Building an Archive

`build_submission(project_dir)` returns the bytes of a `submission.zip` built from a project directory:

- Every file under `project_dir/submission/` is added as `submission/<relative path>`.
- `__pycache__` directories and `.pyc` and `.pyo` files are left out.
- `project_dir/pyproject.toml` is added as `pyproject.toml` if it is a regular file.
- Nothing else in the project directory is added, and empty directories are not stored.

`SubmissionError` is raised for an invalid project:

- `submission/strategy.py` is missing.
- `submission/` itself, anything inside it, or `pyproject.toml` is a symbolic link; links are rejected instead of followed.
- A file inside `submission/` is not a regular file, such as a named pipe.
- The files together exceed `max_total_bytes` (default `DEFAULT_MAX_TOTAL_BYTES`, 512 MiB).

A file that cannot be read raises `OSError`.

The archive is deterministic.
Its entries are sorted, compressed with `ZIP_DEFLATED`,
and stored with a fixed timestamp (1980-01-01 00:00:00) and fixed permissions.
Identical file contents therefore give identical bytes and SHA-256 hashes, regardless of file timestamps and permissions.
`extract_submission` accepts every archive that `build_submission` returns.

## Extracting an Archive

`extract_submission(archive, destination)` validates an archive and extracts its `submission/` directory into `destination`.
`archive` is a path or a binary file object, and `destination` must be empty or not exist yet.
Every entry is validated before anything is written.

`SubmissionError` is raised, and nothing is written, for an invalid archive:

- An entry has an absolute path, a drive letter, a `..` component, or a backslash.
- An entry is a symbolic link or another special file, even outside `submission/`.
- An entry is encrypted.
- An entry that would be extracted, or `pyproject.toml` at the root, appears more than once,
  or its name is also used as a directory.
- The archive has no `submission/strategy.py`.
- The archive is not a valid ZIP archive.
- The extracted files would exceed `max_total_bytes` (default `DEFAULT_MAX_TOTAL_BYTES`) in total uncompressed size.

If an entry turns out to be corrupt while it is extracted, such as a bad checksum,
`SubmissionError` is raised and the files already written are removed.

Entries outside `submission/` and files directly at the archive root are skipped, with one exception:
`pyproject.toml` at the archive root is read but not extracted.
The size limit counts every extracted file and `pyproject.toml`.

The returned `Submission` has these fields and properties:

| Name | Meaning |
|---|---|
| `root` | The resolved `destination`, which contains `submission/` |
| `skipped_entries` | Names of the entries that were skipped |
| `pyproject` | Contents of `pyproject.toml` at the archive root, or `None` |
| `directory` | The extracted `submission/` directory |
| `strategy_file` | The extracted `submission/strategy.py` |
