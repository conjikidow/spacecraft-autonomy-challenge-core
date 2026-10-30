# Scoring

**English** | [日本語](scoring.ja.md)

This page describes how evaluated cases and suites are scored (`spacecraft_autonomy_challenge.judge.scoring`).
A score depends only on the status and the run metrics of a case (see [Evaluation](evaluation.md)),
the CPU time of its participant process (see [Running Cases](runner.md)), and a scoring configuration.

```python
from pathlib import Path

from spacecraft_autonomy_challenge.judge.judging import check_submission
from spacecraft_autonomy_challenge.judge.scoring import ScoringConfig, score_case, suite_score

config = ScoringConfig.default()
evaluation = check_submission(Path("submission.zip").read_bytes(), scoring=config)
scores = [score_case(outcome, config) for outcome in evaluation.outcomes]
print(suite_score(scores))
```

## Case Score

The score $s$ of one case is a number from 0 to 1:

$$
s = g \cdot a \cdot d \cdot
\left( w_\mathrm{base} + w_\mathrm{time} \, t + w_\mathrm{battery} \, b + w_\mathrm{cpu} \, c \right)
$$

The gate $g$, the accuracy factor $a$, and the declaration factor $d$ multiply the whole score.
The weights $w$ come from the configuration, are non-negative, and sum to 1,
so the weighted sum of the base term and the terms $t$, $b$, and $c$ is at most 1.
Every factor and term is from 0 to 1.

| Symbol | `CaseScore` field | Definition |
|---|---|---|
| $g$ | `gate` | 1 if the case status is `COMPLETED`, the metric `safe` is true, and the termination reason is neither `STRATEGY_ERROR` nor `INVALID_COMMAND`; otherwise 0 |
| $a$ | `accuracy` | $\max\left(0, 1 - \lvert e \rvert / e_\mathrm{tol}\right)$ with the delta-v error $e$ and the tolerance $e_\mathrm{tol} = f_\mathrm{tol} \cdot \Delta v_\mathrm{target}$ |
| $d$ | `declaration` | 1 if the run declared completion, otherwise the undeclared factor $f_\mathrm{undeclared}$ |
| $t$ | `completion_time` | $\left(T - t_\mathrm{declared}\right) / \left(T - t_\mathrm{ref}\right)$, clipped to the range from 0 to 1, if the run declared completion, otherwise 0 |
| $b$ | `battery_margin` | $\left(E_\mathrm{min} - E_\mathrm{limit}\right) / \left(C_\mathrm{nominal} - E_\mathrm{limit}\right)$, clipped to the range from 0 to 1 |
| $c$ | `cpu_time` | $\min\left(1, B / \tau\right)$ with the CPU time $\tau$ of the participant process and the budget $B = B_\mathrm{startup} + B_\mathrm{cycle} \cdot T / \Delta t$ |

The quantities come from the run metrics and the outcome:

| Symbol | Source |
|---|---|
| $e$ | `delta_v_error_mps` |
| $\Delta v_\mathrm{target}$ | `target_delta_v_mps` |
| $t_\mathrm{declared}$ | `completion_declared_time_s` |
| $T$ | `time_limit_s` |
| $t_\mathrm{ref}$ | `completion_time.reference_time_s` of the configuration; 0 without it or if it is not below $T$ |
| $\Delta t$ | `decision_period_s` |
| $E_\mathrm{min}$ | `min_battery_energy_wh` |
| $E_\mathrm{limit}$ | `min_battery_energy_limit_wh` |
| $C_\mathrm{nominal}$ | `nominal_battery_capacity_wh` |
| $\tau$ | `participant_cpu_s` of the `CaseOutcome` |

The battery margin is measured against the nominal capacity and the safety limit,
which are what the mission brief gives a strategy.
The completion time term is 1 for a declaration at the reference time or earlier, and falls linearly to 0 at the time limit;
with $t_\mathrm{ref} = 0$ it is $1 - t_\mathrm{declared} / T$.

Some cases need a closer look:

- A case without metrics (status `LOAD_ERROR`, `CRASHED`, or `TIMEOUT`) scores 0, and every factor and term is 0.
- Declaring completion early does not help by itself:
  if the delta-v error is at least $e_\mathrm{tol}$, the accuracy factor and the score are 0.
- If $\tau$ is `None`, which includes a completed run whose CPU time could not be measured, $c = 0$.
  If $\tau$ is 0, $c = 1$.
- $\tau$ counts processes that the participant process starts only as described in [Running Cases](runner.md):
  a process still running when the participant process exits is not counted.
- If the target delta-v is 0, $a$ is 1 for an error of exactly 0 and 0 otherwise.
- $t$ is clipped to $[0, 1]$; $t = 0$ if $T \le 0$, and $c = 0$ if $\Delta t \le 0$.
- If $C_\mathrm{nominal}$ is not above $E_\mathrm{limit}$, $b = 0$.

For a completed run, every factor and term is computed even when the gate is 0, so that a score of 0 can be explained.

## Suite Score

The score of a suite is a number from 0 to 100:

$$
S = \frac{100}{N} \sum_{i=1}^{N} s_i
$$

where $N$ is the number of cases of the suite and $s_i$ the score of case $i$.
Cases without metrics count with $s_i = 0$.
No pass threshold is applied.

## Configuration

The parameters of the formula are not fixed in the code.
A `ScoringConfig` holds them in four sections and an optional fifth section, read from TOML.
This package ships the following configuration as `spacecraft_autonomy_challenge/judge/scoring.toml`:

```toml
version = 1

[accuracy]
tolerance_fraction = 0.075

[declaration]
undeclared_factor = 0.5

[weights]
base = 0.65
completion_time = 0.30
battery_margin = 0.03
cpu_time = 0.02

[cpu_time]
startup_allowance_s = 5.0
per_decision_cycle_s = 0.1

[completion_time]
reference_time_s = 10660.0
```

| Key | Symbol | Meaning | Shipped value |
|---|---|---|---|
| `version` | | Version of the configuration format; must be 1 | `1` |
| `accuracy.tolerance_fraction` | $f_\mathrm{tol}$ | Absolute delta-v error, as a fraction of the target delta-v, at which the accuracy factor reaches 0 | `0.075` |
| `declaration.undeclared_factor` | $f_\mathrm{undeclared}$ | Declaration factor of a run that did not declare completion | `0.5` |
| `weights.base` | $w_\mathrm{base}$ | Weight of the base term | `0.65` |
| `weights.completion_time` | $w_\mathrm{time}$ | Weight of the completion time term | `0.30` |
| `weights.battery_margin` | $w_\mathrm{battery}$ | Weight of the battery margin term | `0.03` |
| `weights.cpu_time` | $w_\mathrm{cpu}$ | Weight of the CPU time term | `0.02` |
| `cpu_time.startup_allowance_s` | $B_\mathrm{startup}$ | CPU time budget for interpreter start-up and loading the strategy, in seconds | `5.0` |
| `cpu_time.per_decision_cycle_s` | $B_\mathrm{cycle}$ | CPU time budget per decision cycle of the time limit, in seconds | `0.1` |
| `completion_time.reference_time_s` | $t_\mathrm{ref}$ | Completion time at which the completion time term reaches 1, in seconds | `10660.0` |

With the shipped values and the challenge problem (a time limit of 21320 s and a decision period of 60 s),
the CPU time budget is $5 + 0.1 \cdot 21320 / 60 \approx 40.5$ seconds,
and the completion time term is $(21320 - t_\mathrm{declared}) / 10660$, clipped to the range from 0 to 1.
The reference time $t_\mathrm{ref}$ is the fastest nominal completion time among the reference runs,
and the time limit $T$ is twice $t_\mathrm{ref}$.

A configuration must satisfy these rules:

- Every section and key is required, except the section `completion_time`,
  and keys and sections that the format does not define are rejected.
  Without the section `completion_time`, there is no reference time, and `to_dict()` leaves the section out.
- Every value is a finite number.
- The weights are non-negative and sum to 1, within $10^{-9}$.
- `tolerance_fraction`, `startup_allowance_s`, and `per_decision_cycle_s` are positive.
- `undeclared_factor` is from 0 to 1.
- `reference_time_s` is not negative.

A configuration that breaks them raises `ScoringConfigError`, a subclass of `ValueError`.

### Loading a Configuration

| Method | Meaning |
|---|---|
| `ScoringConfig.default()` | The shipped configuration |
| `ScoringConfig.from_toml(data)` | A configuration from a `Path` to a TOML file, TOML text as `str`, or UTF-8 TOML as `bytes` |
| `ScoringConfig.from_dict(data)` | A configuration from a dictionary in the layout of the TOML file |
| `to_dict()` | The configuration as a JSON-serializable dictionary in the layout of the TOML file |

`from_toml` also raises `ScoringConfigError` for data that is not UTF-8 TOML, and `OSError` for a file that cannot be read.
To evaluate with another configuration, pass it to `evaluate_submission` or `check_submission`:

```python
config = ScoringConfig.from_toml(Path("my-scoring.toml"))
evaluation = check_submission(archive, scoring=config)
```

Without `scoring`, both use `ScoringConfig.default()`.

## Functions

`score_case(outcome, config)` returns the `CaseScore` of one `CaseOutcome`, with these fields:

| Field | Meaning |
|---|---|
| `value` | The score $s$ |
| `gate` | $g$ |
| `accuracy` | $a$ |
| `declaration` | $d$ |
| `completion_time` | $t$ |
| `battery_margin` | $b$ |
| `cpu_time` | $c$ |

`to_dict()` returns these fields as a dictionary, and `CaseScore.from_dict` is its inverse;
`from_dict` raises `ValueError` for data that does not describe a case score,
including values outside the range from 0 to 1.
`ZERO_SCORE` is the score of a case without metrics.

`suite_score(scores)` returns the suite score $S$ from the `CaseScore` of every case of a suite, or 0 without any.

## Where Scores Appear

- `SubmissionEvaluation.scoring` is the configuration of the evaluation (see [Evaluating Submissions](evaluating.md)).
- `SuiteSummary.score` is the suite score, and `summary_rows` shows it first, with two decimals.
- `EvaluationResult.scores` holds the `CaseScore` of each outcome,
  and `case_rows(outcomes, scores)` shows 100 times its value, on the scale of the suite score, in the `Score` column.
- In a result document, `scoring` holds the configuration, `summary.score` the suite score,
  and the `score` of each entry of `cases` its `CaseScore`.
  A filtered document that leaves out cases keeps the score of every case it keeps and the stored suite score.
