"""marimo views of result documents and dependency reports.

Requires marimo, which the `marimo` extra of `spacecraft-operations-challenge-core` provides.
"""

from collections.abc import Sequence

try:
    import marimo as mo
except ModuleNotFoundError as error:
    raise ImportError(
        "spacecraft_ops_challenge.judge.views requires marimo; "
        'install it with the extra "spacecraft-operations-challenge-core[marimo]"'
    ) from error

from spacecraft_ops_challenge.judge.dependencies import DependencyReport
from spacecraft_ops_challenge.judge.reporting import (
    EvaluationResult,
    case_rows,
    missing_modules,
    problem_outcomes,
    summary_rows,
)
from spacecraft_ops_challenge.judge.runner import CaseOutcome
from spacecraft_ops_challenge.judge.scoring import CaseScore

DEFAULT_MISSING_MODULE_HINT = (
    "Packages added with `uv add` must be listed in the project's `pyproject.toml`, which is packed into "
    "`submission.zip`, and modules of your own must be under `submission/`."
)


def results_view(result: EvaluationResult, *, missing_module_hint: str = DEFAULT_MISSING_MODULE_HINT) -> mo.Html:
    """Suite score, summary statistics, per-case scores and metrics, failure details, and participant output.

    The summary and the scores are shown as stored in `result`, never recomputed from its outcomes.
    """
    outcomes = result.outcomes
    heading = f"Suite `{result.suite_name}`"
    if result.participant is not None:
        heading += f", participant `{result.participant}`"
    sections = [
        mo.md(heading),
        mo.stat(f"{result.summary.score:.2f}", label="Score", caption="out of 100", bordered=True),
    ]
    missing = missing_modules(outcomes)
    if missing:
        names = ", ".join(f"`{name}`" for name in missing)
        sections.append(
            mo.callout(
                mo.md(f"Modules not found: {names}. {missing_module_hint}"), kind="warn", title="Missing modules"
            )
        )
    sections += [
        mo.md("### Summary"),
        mo.ui.table(summary_rows(result.summary), selection=None, pagination=False, show_download=False),
        mo.md("### Cases"),
    ]
    if len(outcomes) < len(result.case_ids):
        sections.append(
            mo.md(
                f"{len(outcomes)} of {len(result.case_ids)} cases are shown; "
                "the score and the summary cover every case of the suite."
            )
        )
    sections += [
        mo.ui.table(case_rows(outcomes, result.scores), selection=None, pagination=False),
        mo.md(
            "Case scores are shown on the scale of the suite score, from 0 to 100. "
            "The score of a case is the product of the gate (a completed, safe run without a strategy failure), "
            "the accuracy factor, and the declaration factor with a weighted sum of a base term and the "
            "completion time, battery margin, and CPU time terms, each from 0 to 1. "
            "The suite score is the mean score of all its cases, and no pass threshold is applied."
        ),
        mo.accordion({"Score components": score_view(outcomes, result.scores)}),
    ]
    problems = problem_outcomes(outcomes)
    if problems:
        sections.append(
            mo.accordion({f"Errors ({_cases(len(problems))})": mo.vstack([_problem_view(o) for o in problems])})
        )
    printed = [o for o in outcomes if o.stdout or o.stderr]
    if printed:
        sections.append(
            mo.accordion(
                {
                    f"Strategy output ({_cases(len(printed))})": mo.accordion(
                        {o.case_id: output_view(o) for o in printed}, multiple=True
                    )
                }
            )
        )
    else:
        sections.append(mo.md("The strategy printed nothing."))
    return mo.vstack(sections)


def _cases(count: int) -> str:
    return f"{count} case" if count == 1 else f"{count} cases"


def score_view(outcomes: Sequence[CaseOutcome], scores: Sequence[CaseScore]) -> mo.Html:
    """Table of each case score, on the scale of the suite score, and of its factors and terms, from 0 to 1.

    `scores` are in the order of `outcomes`.
    """
    rows = [
        {
            "Case": outcome.case_id,
            "Score": f"{100 * score.value:.2f}",
            "Gate": f"{score.gate:.0f}",
            "Accuracy": f"{score.accuracy:.4f}",
            "Declaration": f"{score.declaration:.4f}",
            "Completion time": f"{score.completion_time:.4f}",
            "Battery margin": f"{score.battery_margin:.4f}",
            "CPU time": f"{score.cpu_time:.4f}",
        }
        for outcome, score in zip(outcomes, scores, strict=True)
    ]
    return mo.ui.table(rows, selection=None, pagination=False)


def _problem_view(outcome: CaseOutcome) -> mo.Html:
    parts = [mo.md(f"**{outcome.case_id}**: `{outcome.status}`")]
    if outcome.detail:
        parts.append(mo.plain_text(outcome.detail))
    if outcome.worker_error:
        parts += [mo.md("Trusted worker error"), mo.plain_text(outcome.worker_error)]
    return mo.vstack(parts)


def output_view(outcome: CaseOutcome) -> mo.Html:
    """Standard output and standard error of one case."""
    parts = []
    if outcome.stdout:
        parts += [mo.md("Standard output"), mo.plain_text(outcome.stdout)]
    if outcome.stderr:
        parts += [mo.md("Standard error"), mo.plain_text(outcome.stderr)]
    return mo.vstack(parts)


def dependencies_view(report: DependencyReport) -> mo.Html:
    """Which requirements of the participant's `pyproject.toml` were already satisfied, installed, or skipped."""
    if report.plan is None:
        return mo.md(
            "The submission has no `pyproject.toml`, so it ran with the packages of the evaluating environment."
        )
    installed = report.plan.to_install
    summary = (
        f"Installed for this submission only: {', '.join(f'`{r}`' for r in installed)}."
        if installed
        else "Nothing was installed for this submission; the table shows why for each requirement."
    )
    return mo.vstack(
        [
            mo.md(f"Packages from the submission's `pyproject.toml`. {summary}"),
            mo.accordion(
                {
                    f"Requirements ({len(report.plan.decisions)})": mo.ui.table(
                        [
                            {"Requirement": d.requirement, "Decision": d.decision.value, "Reason": d.reason}
                            for d in report.plan.decisions
                        ],
                        selection=None,
                        pagination=False,
                    ),
                    **{
                        f"Installer output ({index})": mo.plain_text(attempt.output)
                        for index, attempt in enumerate(report.attempts, start=1)
                    },
                }
            ),
        ]
    )
