"""Suite runner: one fresh trusted case worker, with its own participant process, per case.

Each case starts a new trusted worker in the evaluating environment, which starts a new participant process for
the strategy. Module globals, caches, and class state of the participant's code therefore never leak from one
case into the next, and the participant's code never shares a process with the case and its scenario. This is
an architectural boundary, not a sandbox against hostile code.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, Any

from spacecraft_autonomy_challenge.judge.cases import EvaluationCase, ScenarioProvider
from spacecraft_autonomy_challenge.judge.dependencies import Overlay
from spacecraft_autonomy_challenge.judge.processes import kill_descendants
from spacecraft_autonomy_challenge.judge.remote import PACKAGE_ROOT

DEFAULT_CASE_TIMEOUT_S = 300.0
"""Wall-clock limit of one case, including interpreter start-up and loading the strategy."""

MAX_OUTPUT_BYTES = 100_000
"""Captured standard output and standard error each keep at most this many bytes, from the start and the end."""

_POLL_INTERVAL_S = 0.01
_READER_JOIN_TIMEOUT_S = 5.0

_BOOTSTRAP = (
    "import sys; sys.path.append(sys.argv.pop(1)); "
    "from spacecraft_autonomy_challenge.judge.worker import main; main(sys.argv[1:])"
)


class CaseStatus(StrEnum):
    """Whether a case produced run metrics, and why not otherwise."""

    COMPLETED = "COMPLETED"
    """The run ended normally or through a strategy error; metrics are available."""
    LOAD_ERROR = "LOAD_ERROR"
    """`submission/strategy.py:MyStrategy` could not be imported or instantiated."""
    CRASHED = "CRASHED"
    """The run produced no metrics: the strategy stopped its process, or the trusted worker failed."""
    TIMEOUT = "TIMEOUT"
    """The case exceeded its wall-clock limit."""


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """Result of one case. `metrics` is `RunMetrics.to_dict()` of core, present for completed cases."""

    case_id: str
    status: CaseStatus
    metrics: Mapping[str, Any] | None
    detail: str
    """Termination detail of the run (such as a strategy traceback) or the reason the case did not complete."""
    missing_module: str | None
    """Module named by a `ModuleNotFoundError` in `detail`, if any."""
    stdout: str
    stderr: str
    duration_s: float
    participant_cpu_s: float | None
    """User plus system CPU time of the participant process in seconds, as `os.wait4` reports it when the process
    exits after a completed run; `None` for other cases.

    It covers all threads of the participant process and everything it did, from interpreter start-up and loading
    the strategy to the last callback, but not the trusted worker or the simulator. On Linux, a process that the
    participant process started counts only if it ended and was waited for, by the participant process or by a
    counted process, before the participant process exited. It is also `None` if the participant process did not
    exit within a few seconds after the run, or on platforms without `os.wait4`.
    """
    worker_error: str | None = None
    """Traceback of a failure of the trusted worker itself, for whoever runs the evaluation.

    It may show the scenario provider and data of the case, so it is kept apart from `detail`, which names only
    the type of the exception in that case.
    """

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the outcome."""
        return {
            "case_id": self.case_id,
            "status": self.status.value,
            "metrics": None if self.metrics is None else dict(self.metrics),
            "detail": self.detail,
            "missing_module": self.missing_module,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_s": self.duration_s,
            "participant_cpu_s": self.participant_cpu_s,
            "worker_error": self.worker_error,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseOutcome":
        """Inverse of `to_dict`. Raises `ValueError` for data that does not describe an outcome."""
        try:
            metrics, cpu_s = data["metrics"], data["participant_cpu_s"]
            if metrics is not None and not isinstance(metrics, Mapping):
                raise TypeError(f"metrics must be a mapping or None, got {metrics!r}")
            return cls(
                case_id=_text(data, "case_id"),
                status=CaseStatus(data["status"]),
                metrics=metrics,
                detail=_text(data, "detail"),
                missing_module=_optional_text(data, "missing_module"),
                stdout=_text(data, "stdout"),
                stderr=_text(data, "stderr"),
                duration_s=_number(data["duration_s"]),
                participant_cpu_s=None if cpu_s is None else _number(cpu_s),
                worker_error=_optional_text(data, "worker_error"),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"not a case outcome: {error!r}") from None


def _text(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string, got {value!r}")
    return value


def _optional_text(data: Mapping[str, Any], key: str) -> str | None:
    return None if data.get(key) is None else _text(data, key)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"expected a number, got {value!r}")
    return float(value)


class _CappedOutput:
    """Reads a stream to its end on a thread, keeping only its first and last bytes."""

    def __init__(self, stream: IO[bytes], limit: int = MAX_OUTPUT_BYTES) -> None:
        self._stream = stream
        self._half = limit // 2
        self._head = bytearray()
        self._tail = bytearray()
        self._total = 0
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        # The thread owns the stream: a process that escaped the cleanup of the case may hold the pipe open
        # long after the case, and closing the stream from another thread would block until it lets go.
        with self._stream:
            while chunk := self._stream.read1(65536):
                with self._lock:
                    self._total += len(chunk)
                    room = self._half - len(self._head)
                    self._head += chunk[:room]
                    self._tail += chunk[room:] if room > 0 else chunk
                    del self._tail[: -self._half]

    def text(self) -> str:
        """The text captured so far, with a marker where bytes were left out."""
        with self._lock:
            omitted = self._total - len(self._head) - len(self._tail)
            head = self._head.decode("utf-8", errors="replace")
            tail = self._tail.decode("utf-8", errors="replace")
        return f"{head}\n... [{omitted} bytes omitted] ...\n{tail}" if omitted else head + tail


def _has_exited(process: subprocess.Popen[bytes]) -> bool:
    """Whether the process has exited, where possible without reaping it, so its PID cannot be reused yet.

    `os.waitid` is missing on some platforms, such as macOS; there the process is reaped, which leaves a short
    window in which its process group id could in principle be reused.
    """
    if not hasattr(os, "waitid"):
        return process.poll() is not None
    return os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None


def _kill_case_processes(process: subprocess.Popen[bytes]) -> None:
    """Stop the worker and every process of its case, before the worker is reaped.

    A worker that has not been reaped is stopped first, so that it reaps no children while its descendants are
    killed (see `processes`). Then the worker and every process remaining in its process group are killed, which
    is all that is stopped on platforms without `/proc`.
    """
    try:
        if os.name == "posix":
            if process.returncode is None:  # otherwise its PID may belong to another process by now
                os.kill(process.pid, signal.SIGSTOP)
                kill_descendants(process.pid)
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass


def worker_command(result_path: Path) -> list[str]:
    """Command line of a worker process, which uses the current interpreter and reads its request from stdin."""
    return [sys.executable, "-P", "-c", _BOOTSTRAP, PACKAGE_ROOT, str(result_path)]


def run_case(
    submission_root: Path,
    case: EvaluationCase,
    provider: ScenarioProvider,
    *,
    timeout_s: float = DEFAULT_CASE_TIMEOUT_S,
    env: Mapping[str, str] | None = None,
    overlay: Overlay | None = None,
) -> CaseOutcome:
    """Evaluate `case` on a fresh copy of the extracted submission at `submission_root` in a new case worker.

    Only the trusted worker receives the case and loads `provider` to build its scenario. Files that the
    strategy writes never reach later cases. The trusted worker runs with `env` as
    its environment (default: the current process environment); its participant process runs the strategy with the
    copy of `submission_root` as its working directory, the same environment, and the packages of `overlay`
    in front of the packages of the environment. Their output is unbuffered, so it survives a crash or a timeout. When
    the case ends, every process that it started and that is still running is killed: on Linux, the worker kills
    its descendants before it exits, and on a timeout the runner kills them (see `processes`). In addition, the
    worker's whole process group is stopped, which is all that is stopped on platforms without `/proc`.
    Raises `RuntimeError` on platforms other than Linux and macOS, where the participant process cannot be
    connected to the trusted worker.
    """
    if os.name != "posix":
        raise RuntimeError("running cases requires Linux or macOS")
    with (
        tempfile.TemporaryDirectory(prefix="spacecraft-autonomy-case-", ignore_cleanup_errors=True) as scratch,
        tempfile.TemporaryDirectory(prefix="spacecraft-autonomy-result-", ignore_cleanup_errors=True) as results,
    ):
        root = Path(scratch) / "root"
        shutil.copytree(submission_root, root, symlinks=True)
        result_path = Path(results) / "result.json"
        request = {
            "submission_root": str(root),
            "case": case.to_dict(),
            "provider": provider.to_dict(),
            # Absolute: the worker and the participant process run in other directories.
            "overlay": None if overlay is None else str(overlay.path.resolve()),
        }
        worker_env = dict(os.environ if env is None else env)
        worker_env["PYTHONUNBUFFERED"] = "1"
        started = time.monotonic()
        # Not a context manager: Popen.__exit__ would close the output streams that the readers own.
        process = subprocess.Popen(
            worker_command(result_path),
            cwd=results,
            env=worker_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = _CappedOutput(process.stdout), _CappedOutput(process.stderr)
        try:
            try:
                with process.stdin:
                    process.stdin.write(json.dumps(request).encode())
            except BrokenPipeError:
                pass
            while not (exited := _has_exited(process)) and time.monotonic() - started < timeout_s:
                time.sleep(_POLL_INTERVAL_S)
            timed_out = not exited
        finally:
            # Also when waiting is interrupted, e.g. by KeyboardInterrupt: the worker runs in its own session, so
            # nothing else would stop it, and the time limit is enforced only here.
            _kill_case_processes(process)
            process.wait()
        readers_deadline = time.monotonic() + _READER_JOIN_TIMEOUT_S
        for output in (stdout, stderr):
            output.thread.join(max(0.0, readers_deadline - time.monotonic()))
        duration_s = time.monotonic() - started
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            result = None

    if timed_out:
        # A result that the worker wrote while it was being stopped does not count.
        status, detail = CaseStatus.TIMEOUT, f"the case exceeded its limit of {timeout_s:g} s"
        result = None
    elif result is not None:
        status, detail = CaseStatus(result["status"]), result["detail"]
    else:
        status = CaseStatus.CRASHED
        detail = f"the worker exited with status {process.returncode} without a result"
    return CaseOutcome(
        case_id=case.case_id,
        status=status,
        metrics=None if result is None else result.get("metrics"),
        detail=detail,
        missing_module=None if result is None else result["missing_module"],
        stdout=stdout.text(),
        stderr=stderr.text(),
        duration_s=duration_s,
        participant_cpu_s=None if result is None else result["participant_cpu_s"],
        worker_error=None if result is None else result.get("worker_error"),
    )


def run_suite(
    submission_root: Path,
    cases: Iterable[EvaluationCase],
    provider: ScenarioProvider,
    *,
    timeout_s: float = DEFAULT_CASE_TIMEOUT_S,
    env: Mapping[str, str] | None = None,
    overlay: Overlay | None = None,
    on_case_done: Callable[[CaseOutcome], None] | None = None,
) -> tuple[CaseOutcome, ...]:
    """Evaluate every case in order, each in its own worker process.

    A failing case never stops the suite. `on_case_done` is called after each case, for example to report
    progress.
    """
    outcomes = []
    for case in cases:
        outcome = run_case(submission_root, case, provider, timeout_s=timeout_s, env=env, overlay=overlay)
        outcomes.append(outcome)
        if on_case_done is not None:
            on_case_done(outcome)
    return tuple(outcomes)
