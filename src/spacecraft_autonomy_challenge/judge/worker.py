"""Trusted case worker: simulates one case of one submission in its own Python process.

The runner starts one worker per case. The worker reads a JSON request from standard input, builds the
scenario of the case with the scenario provider, and runs it with the simulator of core. The participant's
strategy runs in a separate participant process that the worker starts (see `remote`), so the case, the
scenario, the simulator, and the true state never share a process with participant code, and module state
never carries over between cases.
The worker writes a JSON result file; standard output and standard error belong to the participant process,
and the runner captures them separately.

    python -P -m spacecraft_autonomy_challenge.judge.worker RESULT.json < REQUEST.json
"""

import json
import os
import re
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spacecraft_autonomy_challenge.evaluation import evaluate
from spacecraft_autonomy_challenge.judge.cases import EvaluationCase, ScenarioProvider
from spacecraft_autonomy_challenge.judge.dependencies import Overlay
from spacecraft_autonomy_challenge.judge.processes import become_subreaper, kill_descendants
from spacecraft_autonomy_challenge.judge.remote import ParticipantProcess, ParticipantStopError, RemoteStrategy
from spacecraft_autonomy_challenge.simulation import run

_MISSING_MODULE = re.compile(r"^ModuleNotFoundError: No module named '([^']+)'", re.MULTILINE)


def missing_module(error_text: str) -> str | None:
    """Name of the module in the last `ModuleNotFoundError` of a traceback text, if any."""
    names = _MISSING_MODULE.findall(error_text)
    return names[-1] if names else None


def evaluate_case(
    submission_root: Path,
    case: EvaluationCase,
    provider: ScenarioProvider,
    overlay: Path | None = None,
    *,
    output: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Run the case with a fresh strategy from `submission_root` in a participant process; return the JSON result.

    Only this process loads the scenario provider. Only the participant process gets the packages of
    `overlay`, first on its import path. A completed case also reports the CPU time of the participant
    process (see `ParticipantProcess.finish`); other cases report `None`.
    """
    # Taken before the provider runs, so that whatever it puts into the environment never reaches the participant.
    base_env = dict(os.environ)
    scenario = provider.build(case)
    env = base_env if overlay is None else Overlay(overlay).environment(base_env)
    with ParticipantProcess(submission_root, env, overlay, output=output) as participant:
        try:
            load_error = participant.wait_ready()
            if load_error is not None:
                return _failed("LOAD_ERROR", load_error)
            result = run(RemoteStrategy(participant), scenario)
        except ParticipantStopError as stop:
            return _failed("CRASHED", str(stop))
        participant_cpu_s = participant.finish()
    detail = result.termination.detail
    return {
        "status": "COMPLETED",
        "metrics": evaluate(result).to_dict(),
        "detail": detail,
        "missing_module": missing_module(detail),
        "participant_cpu_s": participant_cpu_s,
    }


def _failed(status: str, detail: str) -> dict[str, Any]:
    """JSON result of a case that produced no metrics."""
    return {"status": status, "detail": detail, "missing_module": missing_module(detail), "participant_cpu_s": None}


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point: evaluate the requested case, kill the processes left, write the result file, and exit at once.

    On Linux, this process is a child subreaper, so the processes left are all processes that the case started and
    that are still running, including those that the participant process started (see `processes`). Exiting at once
    keeps threads or exit handlers from delaying or changing the outcome.
    """
    (result_path,) = sys.argv[1:] if argv is None else argv
    become_subreaper()
    request = json.loads(sys.stdin.read())
    # The runner captures the participant's output from the pipes on this process's descriptors 1 and 2. Keep them
    # for the participant process and point this process's own descriptors at the null device, so that what the
    # trusted side writes, including subprocesses and native code of the scenario provider, is discarded.
    output = (os.dup(1), os.dup(2))
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)
    overlay = Path(request["overlay"]) if request.get("overlay") else None
    try:
        case = EvaluationCase.from_dict(request["case"])
        provider = ScenarioProvider.from_dict(request["provider"])
        result = evaluate_case(Path(request["submission_root"]), case, provider, overlay, output=output)
    except BaseException as error:
        # The traceback may show the scenario provider and data of the case, so the participant-visible detail
        # names the exception type only.
        result = {
            "status": "CRASHED",
            "detail": f"the trusted worker failed to evaluate the case ({type(error).__name__})",
            "missing_module": None,
            "participant_cpu_s": None,
            "worker_error": "".join(traceback.format_exception(error)),
        }
    kill_descendants(os.getpid())
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")
    sys.__stdout__.flush()
    sys.__stderr__.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
