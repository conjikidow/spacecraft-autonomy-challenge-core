# Evaluating Submissions

**English** | [日本語](evaluating.ja.md)

This page describes how a whole submission archive is evaluated on a suite (`spacecraft_ops_challenge.judge.judging`),
and how the outcomes are summarized and recorded as a JSON result document (`spacecraft_ops_challenge.judge.reporting`).

```python
from pathlib import Path

from spacecraft_ops_challenge.judge.judging import check_submission
from spacecraft_ops_challenge.judge.reporting import EvaluationResult

evaluation = check_submission(Path("submission.zip").read_bytes())
result = EvaluationResult.from_evaluation(evaluation, participant="example")
print(result.summary)
Path("result.json").write_text(result.to_json(), encoding="utf-8")
```

## Evaluating an Archive

`evaluate_submission(archive, suite, provider)` evaluates the bytes of a `submission.zip` on every case of `suite`:

1. It builds the scenario of every case once with `provider.check`,
   so that a broken provider fails before the submission runs.
   The check runs in the calling process, one evaluation at a time,
   and the environment variables of the process are restored afterwards;
   the packages and the cases get the environment from before the check.
2. It extracts the archive into a temporary directory (see [Submission Archives](submission.md)).
3. It reproduces the packages that the `pyproject.toml` of the archive names, if there is one,
   in an overlay shared by all cases (see [Participant Packages](dependencies.md)).
4. It runs every case in order with `run_suite` (see [Running Cases](runner.md)).

The temporary directory, including the overlay, is removed afterwards.
`check_submission(archive)` does the same on the public scenarios: it is `evaluate_submission` with `public_suite()`
and the scenario provider `PROVIDER` (see [Evaluation Cases](judge.md)).

Both take these keyword arguments:

| Argument | Meaning |
|---|---|
| `timeout_s` | Wall-clock limit of one case (default `DEFAULT_CASE_TIMEOUT_S`, 300 s) |
| `on_status` | Called with a short progress message before the packages are prepared and before the cases run |
| `on_case_done` | Called with each `CaseOutcome` as soon as it is available |

They raise `CaseError` for a broken scenario provider, `SubmissionError` for an invalid archive,
and `DependencyError` for packages that cannot be reproduced; no case runs in these situations.
A case that fails does not raise: it appears in the outcomes with its status.

Both return a `SubmissionEvaluation` with these fields:

| Field | Meaning |
|---|---|
| `suite` | The `Suite` that was evaluated |
| `outcomes` | The `CaseOutcome` of every case, in the order of the suite |
| `submission_sha256` | The SHA-256 of the archive bytes, as a hexadecimal string |
| `skipped_entries` | Archive entries that were not extracted: those outside `submission/`, except `pyproject.toml` |
| `dependencies` | The `DependencyReport` of the participant's packages |
| `started_at`, `finished_at` | UTC times in ISO 8601 format, to the second |

## Summary Statistics

`summarize(outcomes)` returns a `SuiteSummary` over the outcomes of one suite:

| Field | Meaning |
|---|---|
| `cases` | Number of outcomes |
| `completed` | Cases that produced run metrics |
| `not_completed` | Cases that did not load, crashed, or timed out |
| `safe` | Completed runs that were safe |
| `completion_declared` | Completed runs that declared completion |
| `safe_and_completion_declared` | Completed runs that were safe and declared completion |
| `strategy_failures` | Completed runs that ended with `STRATEGY_ERROR` or `INVALID_COMMAND` |
| `termination_reasons` | Number of completed runs per termination reason |
| `statuses` | Number of cases per `CaseStatus` |
| `mean_abs_delta_v_error_mps`, `median_abs_delta_v_error_mps` | Mean and median of the absolute delta-v error over completed runs, or `None` without any |
| `mean_abs_delta_v_error_safe_declared_mps`, `median_abs_delta_v_error_safe_declared_mps` | The same over runs that were safe and declared completion, or `None` without any |

`to_dict()` returns JSON-serializable data, and `SuiteSummary.from_dict` is its inverse;
`from_dict` raises `ValueError` for data that does not describe a summary.

For display in a table, `summary_rows(summary)` and `case_rows(outcomes)` return rows of human-readable strings.
`case_rows` has one row per case with its status, termination reason, main metrics, wall-clock duration,
and CPU time of the participant process; a value that is not available shows as `-`.
`problem_outcomes(outcomes)` returns the outcomes worth a closer look:
cases that did not complete and completed runs that ended with a strategy failure.
`missing_modules(outcomes)` returns the sorted names of the modules that the submission failed to import.

No score, success policy, or pass threshold is applied anywhere:
the summary and the rows report counts and metrics only.

## Result Documents

An `EvaluationResult` is the record of one evaluation, complete enough to aggregate results without rerunning them.
`EvaluationResult.from_evaluation(evaluation, participant=None)` creates it from a `SubmissionEvaluation`,
with `summarize` over all its outcomes as `summary` and the version of this package as `core_version`.
`participant` is an optional name for whoever submitted the archive.

The record identifies cases only by their ids and the suite by its fingerprint: case payloads are never included.
It can be stored, loaded again, or handed to someone else:

| Method | Meaning |
|---|---|
| `to_dict(include_worker_errors=False)` | The result document as a JSON-serializable dictionary |
| `EvaluationResult.from_dict(data)` | Inverse of `to_dict` |
| `to_json(include_worker_errors=False)` | The result document as JSON text, indented by two spaces and ending with a newline |
| `EvaluationResult.from_json(text)` | Inverse of `to_json`; accepts `str` or `bytes` in any JSON layout |

The document is a JSON object with these keys:

| Key | Meaning |
|---|---|
| `format` | Always `RESULT_FORMAT`, `"spacecraft-operations-challenge/result"` |
| `format_version` | Always `RESULT_FORMAT_VERSION`, currently `1` |
| `participant` | The participant name, or `null` |
| `submission` | `{"sha256": ..., "skipped_entries": [...]}` of the archive |
| `dependencies` | `DependencyReport.to_dict()` (see [Participant Packages](dependencies.md)) |
| `suite` | `{"name": ..., "fingerprint": ..., "case_ids": [...]}` with the ids of every case of the suite, in order |
| `core_version` | The version of this package that ran the evaluation |
| `started_at`, `finished_at` | UTC times in ISO 8601 format |
| `summary` | `SuiteSummary.to_dict()` |
| `cases` | `CaseOutcome.to_dict()` of each outcome (see [Running Cases](runner.md)), without `worker_error` unless `include_worker_errors` is true |

A document may have been filtered before it is loaded, for example to leave out details for another reader.
Besides `worker_error`, the installer commands and output in `dependencies` show paths of the evaluating machine.
`from_dict` therefore accepts a `participant` of `null`, fewer `cases` than `case_ids`,
empty strings for `stdout`, `stderr`, and `detail`, and cases without `worker_error`.
The `cases` must still be distinct cases of the suite, in the order of `case_ids`,
with metrics exactly for `COMPLETED` cases, and the counts of the summary must not be negative.
The stored `summary` is authoritative: it is read as it is and never recomputed from `cases`.

`from_dict` and `from_json` raise `ResultFormatError`, a subclass of `ValueError`,
for a document of another `format` or `format_version`, for text that is not JSON, for numbers that are not finite,
and for missing keys or values of the wrong type in the document, its `summary`, its `cases`,
and the metrics of the cases that the report functions read.
The dependency report is checked for its structure only.
Keys that the format does not define are ignored.

Loading a document and calling `to_dict()` again gives the same document,
with `include_worker_errors=True` if the document has `worker_error` in its cases.
The constraints and preserved packages of the dependency decisions are not part of the document
(see [Participant Packages](dependencies.md)), so a loaded result can differ from the original in those alone.
