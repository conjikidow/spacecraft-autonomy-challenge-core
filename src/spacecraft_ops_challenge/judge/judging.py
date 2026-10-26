"""Evaluation of one submission archive on one suite."""

import hashlib
import io
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from spacecraft_ops_challenge.judge.cases import ScenarioProvider, Suite
from spacecraft_ops_challenge.judge.dependencies import DependencyReport, resolve_dependencies
from spacecraft_ops_challenge.judge.public_scenarios import PROVIDER, public_suite
from spacecraft_ops_challenge.judge.runner import DEFAULT_CASE_TIMEOUT_S, CaseOutcome, run_suite
from spacecraft_ops_challenge.judge.submission import extract_submission


@dataclass(frozen=True, slots=True)
class SubmissionEvaluation:
    """Outcomes of every case of `suite` for one submission archive."""

    suite: Suite
    outcomes: tuple[CaseOutcome, ...]
    submission_sha256: str
    skipped_entries: tuple[str, ...]
    """Archive entries outside `submission/`, which were not extracted, except `pyproject.toml`."""
    dependencies: DependencyReport
    started_at: str
    """UTC start time in ISO 8601 format."""
    finished_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


_PROVIDER_CHECK_LOCK = threading.Lock()

# Settled once, before any scenario provider runs in this process, so that a provider that changes TMPDIR cannot
# choose where evaluations put their files.
tempfile.gettempdir()


def _check_provider(provider: ScenarioProvider, suite: Suite) -> dict[str, str]:
    """Check `provider` on every case of `suite`, and return the environment of this process from before.

    The provider runs in this process and may change its environment, which must reach neither the cases nor the
    installation of their packages, of this or of any other evaluation. The environment is therefore restored
    afterwards, and the lock keeps other evaluations from taking theirs while a check runs.
    """
    with _PROVIDER_CHECK_LOCK:
        env = dict(os.environ)
        try:
            provider.check(suite.cases)
        finally:
            os.environ.clear()
            os.environ.update(env)
    return env


def evaluate_submission(
    archive: bytes,
    suite: Suite,
    provider: ScenarioProvider,
    *,
    timeout_s: float = DEFAULT_CASE_TIMEOUT_S,
    on_status: Callable[[str], None] | None = None,
    on_case_done: Callable[[CaseOutcome], None] | None = None,
) -> SubmissionEvaluation:
    """Extract `archive` into a temporary directory, reproduce its packages, and run every case of `suite`.

    `provider` builds the scenario of each case; it is checked on every case first, so that a broken provider
    fails before the submission runs. Packages that the `pyproject.toml` of the archive names and the evaluating
    environment lacks are installed once into a temporary overlay shared by all cases. The temporary directory is
    removed afterwards. `on_status` receives short progress messages, and `on_case_done` each outcome as soon as it
    is available. Raises `CaseError` for a broken provider, `SubmissionError` for an invalid archive, and
    `DependencyError` for dependencies that cannot be reproduced.
    """
    env = _check_provider(provider, suite)
    started_at = _now()
    with tempfile.TemporaryDirectory(prefix="spacecraft-ops-submission-") as scratch:
        submission = extract_submission(io.BytesIO(archive), Path(scratch) / "root")
        if on_status is not None:
            on_status("Preparing the participant's packages")
        dependencies, overlay = resolve_dependencies(submission.pyproject, Path(scratch) / "overlay", env=env)
        if on_status is not None:
            on_status("Running cases")
        outcomes = run_suite(
            submission.root,
            suite.cases,
            provider,
            timeout_s=timeout_s,
            env=env,
            overlay=overlay,
            on_case_done=on_case_done,
        )
    return SubmissionEvaluation(
        suite=suite,
        outcomes=outcomes,
        submission_sha256=hashlib.sha256(archive).hexdigest(),
        skipped_entries=submission.skipped_entries,
        dependencies=dependencies,
        started_at=started_at,
        finished_at=_now(),
    )


def check_submission(
    archive: bytes,
    *,
    timeout_s: float = DEFAULT_CASE_TIMEOUT_S,
    on_status: Callable[[str], None] | None = None,
    on_case_done: Callable[[CaseOutcome], None] | None = None,
) -> SubmissionEvaluation:
    """Evaluate `archive` on the public scenarios: `evaluate_submission` with `public_suite()` and `PROVIDER`."""
    return evaluate_submission(
        archive, public_suite(), PROVIDER, timeout_s=timeout_s, on_status=on_status, on_case_done=on_case_done
    )
