"""Trusted case worker: simulates one case of one submission in its own Python process.

The runner starts one worker per case. The worker reads a JSON request from standard input, builds the
scenario of the case with the scenario provider, and runs it with the simulator of core. The participant's
strategy runs in a separate participant process that the worker starts (see `remote`), so the case, the
scenario, the simulator, and the true state never share a process with participant code, and module state
never carries over between cases.
The worker writes a JSON result file; standard output and standard error belong to the participant process,
and the runner captures them separately.

    python -P -m spacecraft_ops_challenge.judge.worker RESULT.json < REQUEST.json
"""

import json
import os
import re
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spacecraft_ops_challenge.evaluation import evaluate
from spacecraft_ops_challenge.judge.cases import EvaluationCase, ScenarioProvider
from spacecraft_ops_challenge.judge.dependencies import Overlay
from spacecraft_ops_challenge.judge.remote import ParticipantProcess, ParticipantStopError, RemoteStrategy
from spacecraft_ops_challenge.simulation import run

_MISSING_MODULE = re.compile(r"^ModuleNotFoundError: No module named '([^']+)'", re.MULTILINE)


def missing_module(error_text: str) -> str | None:
    """Name of the module in the last `ModuleNotFoundError` of a traceback text, if any."""
    names = _MISSING_MODULE.findall(error_text)
    return names[-1] if names else None


def evaluate_case(
    submission_root: Path, case: EvaluationCase, provider: ScenarioProvider, overlay: Path | None = None
) -> dict[str, Any]:
    """Run the case with a fresh strategy from `submission_root` in a participant process; return the JSON result.

    Only this process loads the scenario provider. Only the participant process gets the packages of
    `overlay`, first on its import path. A completed case also reports the CPU time of the participant
    process (see `ParticipantProcess.finish`); other cases report `None`.
    """
    scenario = provider.build(case)
    env = dict(os.environ) if overlay is None else Overlay(overlay).environment()
    with ParticipantProcess(submission_root, env, overlay) as participant:
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
    """Entry point: evaluate the requested case, write the result file, and exit the process at once.

    Exiting at once keeps threads or exit handlers from delaying or changing the outcome.
    """
    (result_path,) = sys.argv[1:] if argv is None else argv
    request = json.loads(sys.stdin.read())
    overlay = Path(request["overlay"]) if request.get("overlay") else None
    try:
        case = EvaluationCase.from_dict(request["case"])
        provider = ScenarioProvider.from_dict(request["provider"])
        result = evaluate_case(Path(request["submission_root"]), case, provider, overlay)
    except Exception as error:
        detail = "".join(traceback.format_exception(error))
        result = {"status": "CRASHED", "detail": f"the trusted worker failed to evaluate the case:\n{detail}"}
        result |= {"missing_module": None, "participant_cpu_s": None}
    Path(result_path).write_text(json.dumps(result), encoding="utf-8")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
