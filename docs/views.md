# Result Views

**English** | [日本語](views.ja.md)

This page describes the [marimo](https://marimo.io) views of result documents and dependency reports
(`spacecraft_autonomy_challenge.judge.views`).

## Installation

The views need marimo, which the optional `marimo` extra of this package provides:

```sh
uv add "spacecraft-autonomy-challenge-core[marimo] @ git+https://github.com/conjikidow/spacecraft-autonomy-challenge-core"
```

Importing `spacecraft_autonomy_challenge.judge.views` without marimo raises `ImportError`, with a message that names `spacecraft-autonomy-challenge-core[marimo]`.
The rest of the package does not need marimo.

## Usage

Each view returns a `marimo.Html` element, to be shown as the output of a notebook cell:

```python
from pathlib import Path

import marimo as mo

from spacecraft_autonomy_challenge.judge.reporting import EvaluationResult
from spacecraft_autonomy_challenge.judge.views import dependencies_view, results_view

result = EvaluationResult.from_json(Path("result.json").read_bytes())
mo.vstack([results_view(result), dependencies_view(result.dependencies)])
```

See [Evaluating Submissions](evaluating.md) for how a result document is created.

## Views

| Function | Shows |
|---|---|
| `results_view(result, *, stats=(), missing_module_hint=DEFAULT_MISSING_MODULE_HINT)` | An `EvaluationResult`: suite score, summary, cases, score definition, score components, errors, and strategy output |
| `scoring_view(config)` | The scoring formula with the parameters of a `ScoringConfig`, and the definitions of its factors, terms, and inputs |
| `dependencies_view(report)` | A `DependencyReport`: how the packages of the participant's `pyproject.toml` were reproduced |
| `score_view(outcomes, scores)` | A table of each `CaseScore`: the score on the scale of the suite score and its factors and terms, with `scores` in the order of `outcomes` |
| `output_view(outcome)` | Standard output and standard error of one `CaseOutcome` |
| `text_view(text)` | Plain text in a fixed-width font, with spaces and newlines kept and long lines wrapped; text longer than about 20 lines scrolls within that height |

`results_view` shows, from top to bottom:

1. The suite name and the participant name if there is one.
2. Side by side: on the left, the suite score out of 100 with the elements of `stats` below it;
   on the right, the summary of `summary_rows(result.summary)` as a plain table.
3. A warning that lists the modules that the submission failed to import (see `missing_modules`), if any, followed by `missing_module_hint`.
4. The case table of `case_rows(result.outcomes, result.scores)`.
   If the result has fewer outcomes than `case_ids`, a note says how many of the cases are shown.
5. The `scoring_view` of `result.scoring` in a collapsed section.
6. The score components of `score_view` in a collapsed section.
   Case scores appear on the scale of the suite score, from 0 to 100, and their factors and terms from 0 to 1.
7. The status and detail of each outcome of `problem_outcomes` in a collapsed section,
   with the `worker_error` of the outcome when it is present.
8. The standard output and standard error of each case that printed anything in a collapsed section,
   or a note that the strategy printed nothing.

The summary and the scores are shown as stored in the result and never recomputed from its outcomes.
A filtered result document works as well: a `participant` of `None`, fewer outcomes than `case_ids`,
empty `stdout`, `stderr`, and `detail`, and no `worker_error` leave out the corresponding parts.

`DEFAULT_MISSING_MODULE_HINT` says that packages added with `uv add` must be listed in the project's `pyproject.toml`,
which is packed into `submission.zip`, and that modules of one's own must be under `submission/`.
Pass another `missing_module_hint` to replace it.

`stats` adds figures that the result itself does not hold, such as `marimo.stat` elements with a score computed elsewhere;
without them, the suite score stands alone on the left.

`scoring_view` shows the formulas of [Scoring](scoring.md) with the weights and parameters of the configuration filled in,
so a result shows the configuration that scored it.
It writes the case score on the scale of the suite score, from 0 to 100, as the tables show it,
and leaves the cases of [Scoring](scoring.md) that need a closer look to that page.

`dependencies_view` says that the submission ran with the packages of the evaluating environment if it has no `pyproject.toml`.
Otherwise it lists the requirements installed for the submission only,
the decision for each requirement with its reason (see [Participant Packages](dependencies.md)),
and the output of each run of the installer.

The views show standard output, standard error, failure details, worker errors, and installer output with `text_view`,
so long lines wrap instead of being cut off, and text longer than about 20 lines scrolls within that height.
`text_view` escapes the text, so it cannot add HTML.
