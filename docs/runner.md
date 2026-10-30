# Running Cases

**English** | [日本語](runner.ja.md)

This page describes how a submission is run on evaluation cases (`spacecraft_autonomy_challenge.judge.runner`).
Each case runs in its own pair of new processes, which keep the case away from the participant's code.
Running cases requires Linux or macOS; elsewhere `run_case` raises `RuntimeError`.

```python
from pathlib import Path

from spacecraft_autonomy_challenge.judge.public_scenarios import PROVIDER, public_suite
from spacecraft_autonomy_challenge.judge.runner import run_suite
from spacecraft_autonomy_challenge.judge.submission import extract_submission

submission = extract_submission("submission.zip", Path("work/extracted"))
for outcome in run_suite(submission.root, public_suite().cases, PROVIDER):
    print(outcome.case_id, outcome.status, outcome.metrics, outcome.participant_cpu_s)
```

`run_case(submission_root, case, provider)` runs one case and returns its `CaseOutcome`.
`run_suite(submission_root, cases, provider)` runs every case in order and returns their outcomes.
A failing case never stops the suite, and `on_case_done` is called with each outcome as soon as it is available.
Both take these keyword arguments:

| Argument | Meaning |
|---|---|
| `timeout_s` | Wall-clock limit of one case (default `DEFAULT_CASE_TIMEOUT_S`, 300 s) |
| `env` | Environment variables of the case processes (default: the current process environment); take it before any scenario provider runs in the calling process, since a provider may change the environment |
| `overlay` | An `Overlay` of participant packages (see [Participant Packages](dependencies.md)), or `None` |

Cases and scenario providers are described in [Evaluation Cases](judge.md).
[Evaluating Submissions](evaluating.md) describes how a whole archive is evaluated and its outcomes recorded.

## Two Processes per Case

Each case starts two new Python processes from the current interpreter:

```text
caller
└── trusted case worker: the case, its scenario, and the simulator
    └── participant process: submission/strategy.py:MyStrategy and its packages
```

The trusted case worker receives the case and the scenario provider on its standard input.
It builds the scenario with the provider and runs it with `run()` and `evaluate()` (see [Simulation](simulation.md)).
Its strategy forwards every callback to the participant process.
The participant process gets the worker's environment variables as they were before the provider ran,
so variables that the provider sets never reach it.
It writes its result to a file in a temporary directory apart from the participant's files.

The participant process loads `submission/strategy.py:MyStrategy` like `autonomy-challenge run`,
with `submission/` first on the import path, and creates one instance for the case.
It receives only what a strategy may see: the mission brief, telemetry, and the results of its commander requests.
It never receives the case id, the payload, the scenario provider, the scenario, its seed or modifiers,
or the true state, and it imports neither the module that defines cases nor the scenario provider.
It is started with Python's `-P` option, which keeps its working directory off the import path.
Its command-line arguments are the import root of the core package (appended to the import path),
the file descriptor of its socket, the directory of its copy of the submission,
and, with an `Overlay`, the overlay directory.
Its standard input is empty.

## Messages

The two processes talk over a dedicated socket pair, separate from standard output and standard error.
Each message is a JSON object, preceded by its length as a 4-byte big-endian integer,
and may be at most `MAX_MESSAGE_BYTES` (16 MiB) long.
A larger message is not sent; a commander result above the limit, such as a very long `pending()`,
reaches the strategy as `CommandError`.

- After loading the strategy, the participant process reports that it is ready, or the traceback of the load error.
- `initialize` carries the mission brief and the initial telemetry, and `update` carries the latest telemetry.
- During a callback, the participant's commander sends every request to the trusted worker,
  which performs it on its own commander and sends back the result,
  or the message of the `CommandError` that the participant then sees raised.
  The timeline semantics are therefore exactly those of [Commands and Timeline](timeline.md).
- At the end of a callback, the participant process reports that it returned, or the exception it raised.

A strategy exception or an uncaught `CommandError` ends the run as `STRATEGY_ERROR` or `INVALID_COMMAND`,
as in a local run, and the termination detail includes the participant's traceback.
A traceback longer than 100 000 characters keeps its first and last 50 000 characters.
A message that does not follow the protocol ends the case as `CRASHED`.

## Fresh State for Every Case

Module globals, caches, and class state of the participant's code never carry over between cases,
because every case has a new participant process.
Every case also runs on a fresh copy of the extracted files,
so files that the strategy writes or changes never reach later cases or the original files.
The working directory of the participant process is the directory of that copy, which contains `submission/`.

## Captured Output

The case processes run with `PYTHONUNBUFFERED=1`, so their output survives a crash or a timeout.
Their standard output and standard error are captured separately as `stdout` and `stderr` of the outcome.
What the trusted worker itself writes to its standard output and standard error is discarded,
including output, warnings, and subprocesses of the scenario provider, so the captured output is the participant's.
Each keeps at most `MAX_OUTPUT_BYTES` (100 000 bytes): the first and the last 50 000 bytes,
with a line `... [N bytes omitted] ...` in between.
The output is read while the case runs, so endless output cannot block it.

## Outcomes

A `CaseOutcome` has these fields:

| Field | Meaning |
|---|---|
| `case_id` | The id of the case |
| `status` | A `CaseStatus` (see below) |
| `metrics` | `RunMetrics.to_dict()` of the run (see [Evaluation](evaluation.md)) for a completed case, otherwise `None` |
| `detail` | The termination detail of the run, such as a strategy traceback, or the reason the case did not complete |
| `missing_module` | The module named by a `ModuleNotFoundError` in `detail`, if any |
| `stdout`, `stderr` | The captured output |
| `duration_s` | Wall-clock time of the case, in seconds |
| `participant_cpu_s` | CPU time of the participant process, in seconds (see below), or `None` |
| `worker_error` | The traceback of a failure of the trusted worker itself, or `None` |

| `CaseStatus` | Meaning |
|---|---|
| `COMPLETED` | The run ended, normally or through a strategy error; `metrics` is available |
| `LOAD_ERROR` | `submission/strategy.py:MyStrategy` could not be imported or instantiated |
| `CRASHED` | The run produced no metrics: the strategy raised `SystemExit` or `KeyboardInterrupt`, its process exited or broke the protocol, or the trusted worker failed to evaluate the case |
| `TIMEOUT` | The case exceeded `timeout_s` |

When the trusted worker itself fails, for example because the scenario provider raises an exception,
`detail` names only the type of the exception, since its traceback may show the provider and data of the case.
The traceback is in `worker_error`, for whoever runs the evaluation.

`to_dict()` returns JSON-serializable data, and `CaseOutcome.from_dict` is its inverse.
`from_dict` raises `ValueError` for data that does not describe an outcome.

## CPU Time of the Participant Process

`participant_cpu_s` is the user plus system CPU time of the participant process.
After a completed run, the trusted worker closes the connection, the participant process exits,
and the worker reaps it with `os.wait4`, which reports the time.

- It includes all threads of the participant process and everything that process did,
  from interpreter start-up and loading the strategy to the last callback,
  including its side of encoding and decoding the messages.
- It excludes the trusted worker and the simulator.
  While the participant process waits for them, it uses no CPU time.
- On Linux, a process that the participant process started is included only if it ended and was waited for,
  by the participant process itself or by another included process, before the participant process exited.
  Processes still running when the participant process exits are not included.

It is `None` for `LOAD_ERROR`, `CRASHED`, and `TIMEOUT` cases,
if the participant process does not exit within 5 s after the run, and on platforms without `os.wait4`.

## Time Limits and Cleanup

`timeout_s` limits the wall-clock time of the whole case, including interpreter start-up and loading the strategy.
A case that exceeds it is `TIMEOUT`, even if the trusted worker writes a result while it is being stopped.

Both processes exit right after their work, so threads or exit handlers left behind cannot delay a case.
When a case ends, normally, through a crash, through a failure of the trusted worker, or at the time limit,
the processes that it started and that are still running are stopped, including every process that the strategy started.

- On Linux, the trusted worker is a child subreaper: a process whose parent exits is reparented to the worker
  instead of the init process.
  Every process that the strategy starts therefore remains a descendant of the trusted worker,
  even one that it moves into a new session or process group.
  The trusted worker kills all its descendants with `SIGKILL` before it exits.
  At the time limit, or when `run_case` is interrupted, `run_case` suspends the trusted worker with `SIGSTOP`
  and then kills them.
  A process whose parent exits during the case remains a zombie under the trusted worker until the case ends.
- The trusted worker also starts in a new session, and the participant process is part of its process group.
  When the trusted worker exits or the time limit is reached, every process remaining in that process group is stopped.
  On other platforms, on Linux without `/proc` or where the kernel refuses to make the trusted worker a subreaper,
  and when the trusted worker itself is killed by something else, this is all that is stopped,
  so a process that the strategy moves into a new session or process group may survive the case.

Only processes of the case are stopped: neither the process that runs the cases nor other cases,
including cases that it runs at the same time, are affected.
Killing gives up after 5 s against processes that keep starting new ones.
Stopped processes other than the trusted worker, such as the participant process, are reaped by the init process.
In a container, run an init process that reaps orphaned processes, for example with `docker run --init`,
so that they do not remain as zombies.

## Participant Packages

With an `Overlay`, only the participant process gets it, first on `PYTHONPATH`.
The participant process also processes the `.pth` files in the overlay directory,
and processes that the strategy starts inherit `PYTHONPATH`.
The trusted worker runs with the packages of the current environment alone,
so even an overlay that provides a module of the core package cannot replace the trusted side.

## What the Boundary Means

The separate processes keep the case and the simulator out of ordinary introspection by the participant's code.
They are an architectural boundary, not a sandbox against hostile code:
the participant process runs as the same user, with the same file system access, as the code that runs the cases.
Nor are its memory, processes, or open files limited, apart from the wall-clock limit and the captured output;
limit them for the whole evaluating environment, for example with the resource limits of a container.
