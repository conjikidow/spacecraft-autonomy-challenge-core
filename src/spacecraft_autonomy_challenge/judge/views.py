"""marimo views of result documents and dependency reports.

Requires marimo, which the `marimo` extra of `spacecraft-autonomy-challenge-core` provides.
"""

import html
from collections.abc import Mapping, Sequence
from decimal import Decimal

try:
    import marimo as mo
except ModuleNotFoundError as error:
    raise ImportError(
        "spacecraft_autonomy_challenge.judge.views requires marimo; "
        'install it with the extra "spacecraft-autonomy-challenge-core[marimo]"'
    ) from error

from spacecraft_autonomy_challenge.judge.dependencies import DependencyReport
from spacecraft_autonomy_challenge.judge.reporting import (
    EvaluationResult,
    _numeric_columns,
    case_rows,
    missing_modules,
    problem_outcomes,
    summary_rows,
)
from spacecraft_autonomy_challenge.judge.runner import CaseOutcome
from spacecraft_autonomy_challenge.judge.scoring import CaseScore, ScoringConfig

DEFAULT_MISSING_MODULE_HINT = (
    "Packages added with `uv add` must be listed in the project's `pyproject.toml`, which is packed into "
    "`submission.zip`, and modules of your own must be under `submission/`."
)


def _code(text: str) -> str:
    """`text` as inline code in Markdown, escaped so that it cannot end the code or add HTML."""
    return f"<code>{html.escape(text)}</code>"


def text_view(text: str) -> mo.Html:
    """`text` in a fixed-width font, escaped, with spaces and newlines kept and long lines wrapped.

    Unlike `marimo.plain_text`, which keeps long lines whole and can clip them, every line stays readable.
    Text longer than about 20 lines scrolls within that height instead of growing without limit.
    """
    style = "white-space: pre-wrap; overflow-wrap: anywhere; max-height: 20rem; overflow-y: auto"
    return mo.Html(f'<pre class="text-xs" style="{style}">{html.escape(text)}</pre>')


def _static_table(rows: Sequence[Mapping[str, str]]) -> mo.Html:
    """`rows` as a plain table, escaped, as wide as its content and without the controls of `marimo.ui.table`."""
    if not rows:
        return mo.Html("")
    cell = 'style="text-align: left; padding: 0.2rem 1rem 0.2rem 0.5rem"'
    columns = list(rows[0])
    head = "".join(f"<th {cell}>{html.escape(column)}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td {cell}>{html.escape(row.get(column, ''))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    return mo.md(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


def results_view(
    result: EvaluationResult,
    *,
    stats: Sequence[mo.Html] = (),
    missing_module_hint: str = DEFAULT_MISSING_MODULE_HINT,
) -> mo.Html:
    """Suite score, summary statistics, per-case scores and metrics, failure details, and participant output.

    `stats`, such as `marimo.stat` elements, are shown below the suite score. The summary and the scores are shown
    as stored in `result`, never recomputed from its outcomes.
    """
    outcomes = result.outcomes
    heading = f"Suite {_code(result.suite_name)}"
    if result.participant is not None:
        heading += f", participant {_code(result.participant)}"
    score = mo.stat(f"{result.summary.score:.2f}", label="Score", caption="out of 100", bordered=True)
    sections = [
        mo.md(heading),
        mo.hstack(
            [mo.vstack([score, *stats]), _static_table(summary_rows(result.summary))],
            justify="start",
            align="start",
            gap=1.5,
            widths=[1, 2],
        ),
    ]
    missing = missing_modules(outcomes)
    if missing:
        names = ", ".join(_code(name) for name in missing)
        sections.append(
            mo.callout(
                mo.md(f"Modules not found: {names}. {missing_module_hint}"), kind="warn", title="Missing modules"
            )
        )
    sections.append(mo.md("### Cases"))
    if len(outcomes) < len(result.case_ids):
        sections.append(
            mo.md(
                f"{len(outcomes)} of {len(result.case_ids)} cases are shown; "
                "the score and the summary cover every case of the suite."
            )
        )
    sections += [
        _numeric_table(case_rows(outcomes, result.scores)),
        mo.accordion({"Score definition": scoring_view(result.scoring)}),
        mo.accordion({"Score components": score_view(outcomes, result.scores)}),
    ]
    problems = problem_outcomes(outcomes)
    if problems:
        sections.append(
            mo.accordion({f"Errors ({_cases(len(problems))})": mo.vstack([_problem_view(o) for o in problems])})
        )
    printed = [o for o in outcomes if o.stdout.strip() or o.stderr.strip()]
    if printed:
        sections.append(
            mo.accordion(
                {
                    f"Strategy output ({_cases(len(printed))})": mo.accordion(
                        {html.escape(o.case_id): output_view(o) for o in printed}, multiple=True
                    )
                }
            )
        )
    else:
        sections.append(mo.md("The strategy printed nothing."))
    return mo.vstack(sections)


def _numeric_table(rows: Sequence[Mapping[str, str]]) -> mo.Html:
    """`rows` as a table whose numeric columns are aligned to the right, so that their decimal points line up."""
    right = dict.fromkeys(_numeric_columns(rows), "right")
    return mo.ui.table(rows, selection=None, pagination=False, text_justify_columns=right or None)


def _cases(count: int) -> str:
    return f"{count} case" if count == 1 else f"{count} cases"


def _number(value: float) -> str:
    """`value` in positional notation, with the shortest digits that read back as `value`."""
    return f"{Decimal(repr(value)).normalize():f}"


def scoring_view(config: ScoringConfig) -> mo.Html:
    """The scoring formula with the parameters of `config`, and the definitions of its factors, terms, and inputs."""
    w = config.weights
    weights = [_number(v) for v in (w.base, w.completion_time, w.battery_margin, w.cpu_time)]
    tolerance = _number(config.accuracy.tolerance_fraction)
    undeclared = _number(config.declaration.undeclared_factor)
    startup = _number(config.cpu_time.startup_allowance_s)
    cycle = _number(config.cpu_time.per_decision_cycle_s)
    clip = r"\operatorname{clip}_{[0,1]}"
    return mo.md(
        rf"""
$$
\text{{case score}} = 100 \, g \, a \, d \,
({weights[0]} + {weights[1]}\,t + {weights[2]}\,b + {weights[3]}\,c),
\qquad
\text{{suite score}} = \text{{mean of the case scores}}
$$

| Symbol | Name | Definition |
|:--|:--|:--|
| $g$ | Gate | 1 if completed and safe without a strategy failure, else 0 |
| $a$ | Accuracy | $\max(0,\ 1 - \lvert e \rvert / ({tolerance}\,\Delta v_\mathrm{{target}}))$ |
| $d$ | Declaration | 1 if completion is declared, else {undeclared} |
| $t$ | Completion time | ${clip}(1 - t_\mathrm{{declared}} / T)$ if declared, else 0 |
| $b$ | Battery margin | ${clip}((E_\mathrm{{min}} - E_\mathrm{{lim}}) / (C_\mathrm{{nom}} - E_\mathrm{{lim}}))$ |
| $c$ | CPU time | $\min(1,\ B / \tau)$ with $B = ({startup} + {cycle}\,T / \Delta t)\,\mathrm{{s}}$ |

| Symbol | Quantity |
|:--|:--|
| $e$, $\Delta v_\mathrm{{target}}$ | Delta-v error and target delta-v |
| $t_\mathrm{{declared}}$, $T$, $\Delta t$ | Time of the completion declaration, time limit, and decision period |
| $E_\mathrm{{min}}$, $E_\mathrm{{lim}}$ | Minimum battery energy and its safety limit |
| $C_\mathrm{{nom}}$ | Nominal battery capacity |
| $\tau$ | CPU time of the strategy's process |
"""
    )


def score_view(outcomes: Sequence[CaseOutcome], scores: Sequence[CaseScore]) -> mo.Html:
    """Table of each case score, on the scale of the suite score, and of its factors and terms, from 0 to 1.

    `scores` are in the order of `outcomes`.
    """
    rows = [
        {
            "Case": outcome.case_id,
            "Score": f"{100 * score.value:.2f}",
            "Gate g": f"{score.gate:.0f}",
            "Accuracy a": f"{score.accuracy:.4f}",
            "Declaration d": f"{score.declaration:.4f}",
            "Completion time t": f"{score.completion_time:.4f}",
            "Battery margin b": f"{score.battery_margin:.4f}",
            "CPU time c": f"{score.cpu_time:.4f}",
        }
        for outcome, score in zip(outcomes, scores, strict=True)
    ]
    return _numeric_table(rows)


def _problem_view(outcome: CaseOutcome) -> mo.Html:
    parts = [mo.md(f"<strong>{html.escape(outcome.case_id)}</strong>: {_code(outcome.status.value)}")]
    if outcome.detail:
        parts.append(text_view(outcome.detail))
    if outcome.worker_error:
        parts += [mo.md("Trusted worker error"), text_view(outcome.worker_error)]
    return mo.vstack(parts)


def output_view(outcome: CaseOutcome) -> mo.Html:
    """Standard output and standard error of one case."""
    parts = []
    if outcome.stdout:
        parts += [mo.md("Standard output"), text_view(outcome.stdout)]
    if outcome.stderr:
        parts += [mo.md("Standard error"), text_view(outcome.stderr)]
    return mo.vstack(parts)


def dependencies_view(report: DependencyReport) -> mo.Html:
    """Which requirements of the participant's `pyproject.toml` were already satisfied, installed, or skipped."""
    if report.plan is None:
        return mo.md(
            "The submission has no `pyproject.toml`, so it ran with the packages of the evaluating environment."
        )
    installed = report.plan.to_install
    summary = (
        f"Installed for this submission only: {', '.join(_code(r) for r in installed)}."
        if installed
        else "Nothing was installed for this submission; the table shows why for each requirement."
        if report.plan.decisions
        else "It lists no requirements."
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
                        f"Installer output ({index})": text_view(attempt.output)
                        for index, attempt in enumerate(report.attempts, start=1)
                    },
                }
            ),
        ]
    )
