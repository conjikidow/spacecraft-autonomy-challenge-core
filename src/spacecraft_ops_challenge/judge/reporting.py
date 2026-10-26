"""Aggregate statistics, report rows, and the result document of an evaluation.

Reports carry metrics and the scores of `spacecraft_ops_challenge.judge.scoring`. No pass threshold is applied, and
no case payloads are included: cases are identified by their ids, suites by a fingerprint.
"""

import json
import math
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from spacecraft_ops_challenge import __version__ as core_version
from spacecraft_ops_challenge.judge.dependencies import DependencyReport
from spacecraft_ops_challenge.judge.judging import SubmissionEvaluation
from spacecraft_ops_challenge.judge.runner import CaseOutcome, CaseStatus
from spacecraft_ops_challenge.judge.scoring import STRATEGY_FAILURES, CaseScore, ScoringConfig, score_case, suite_score

RESULT_FORMAT = "spacecraft-operations-challenge/result"
RESULT_FORMAT_VERSION = 1


class ResultFormatError(ValueError):
    """Raised for data that is not a result document of a supported format and version."""


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise TypeError(f"expected a non-negative integer, got {value!r}")
    return value


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool) or not math.isfinite(value):
        raise TypeError(f"expected a finite number or None, got {value!r}")
    return float(value)


def _score(value: object) -> float:
    score = _float(value)
    if not 0 <= score <= 100:  # also rejects NaN
        raise TypeError(f"a suite score is between 0 and 100, got {value!r}")
    return score


def _float(value: object) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise TypeError(f"expected a number, got {value!r}")
    return float(value)


def _counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected a mapping, got {value!r}")
    return {str(key): _count(count) for key, count in value.items()}


@dataclass(frozen=True, slots=True)
class SuiteSummary:
    """Counts and statistics over the outcomes of one suite."""

    cases: int
    completed: int
    """Cases that produced run metrics."""
    not_completed: int
    """Cases that did not load, crashed, or timed out."""
    safe: int
    completion_declared: int
    safe_and_completion_declared: int
    strategy_failures: int
    """Completed runs that ended with `STRATEGY_ERROR` or `INVALID_COMMAND`."""
    termination_reasons: Mapping[str, int]
    statuses: Mapping[str, int]
    mean_abs_delta_v_error_mps: float | None
    """Over completed runs, or `None` without any."""
    median_abs_delta_v_error_mps: float | None
    mean_abs_delta_v_error_safe_declared_mps: float | None
    """Over runs that were safe and declared completion, or `None` without any."""
    median_abs_delta_v_error_safe_declared_mps: float | None
    score: float
    """Score of the suite from 0 to 100 (see `suite_score`)."""

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the summary."""
        data = asdict(self)
        data["termination_reasons"] = dict(self.termination_reasons)
        data["statuses"] = dict(self.statuses)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SuiteSummary":
        """Inverse of `to_dict`. Raises `ValueError` for data that does not describe a summary."""
        try:
            return cls(
                cases=_count(data["cases"]),
                completed=_count(data["completed"]),
                not_completed=_count(data["not_completed"]),
                safe=_count(data["safe"]),
                completion_declared=_count(data["completion_declared"]),
                safe_and_completion_declared=_count(data["safe_and_completion_declared"]),
                strategy_failures=_count(data["strategy_failures"]),
                termination_reasons=_counts(data["termination_reasons"]),
                statuses=_counts(data["statuses"]),
                mean_abs_delta_v_error_mps=_optional_float(data["mean_abs_delta_v_error_mps"]),
                median_abs_delta_v_error_mps=_optional_float(data["median_abs_delta_v_error_mps"]),
                mean_abs_delta_v_error_safe_declared_mps=_optional_float(
                    data["mean_abs_delta_v_error_safe_declared_mps"]
                ),
                median_abs_delta_v_error_safe_declared_mps=_optional_float(
                    data["median_abs_delta_v_error_safe_declared_mps"]
                ),
                score=_score(data["score"]),
            )
        except (KeyError, TypeError, OverflowError) as error:
            raise ValueError(f"not a suite summary: {error!r}") from None


def _mean_median(values: Sequence[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    return statistics.fmean(values), statistics.median(values)


def summarize(outcomes: Iterable[CaseOutcome], scoring: ScoringConfig | None = None) -> SuiteSummary:
    """Aggregate the outcomes of one suite, scored with `scoring`, `ScoringConfig.default()` if it is `None`."""
    outcomes = tuple(outcomes)
    scoring = ScoringConfig.default() if scoring is None else scoring
    metrics = [outcome.metrics for outcome in outcomes if outcome.metrics is not None]
    safe_declared = [m for m in metrics if m["safe"] and m["completion_declared"]]
    errors = [abs(m["delta_v_error_mps"]) for m in metrics]
    errors_safe_declared = [abs(m["delta_v_error_mps"]) for m in safe_declared]
    mean, median = _mean_median(errors)
    mean_safe_declared, median_safe_declared = _mean_median(errors_safe_declared)
    return SuiteSummary(
        cases=len(outcomes),
        completed=len(metrics),
        not_completed=len(outcomes) - len(metrics),
        safe=sum(1 for m in metrics if m["safe"]),
        completion_declared=sum(1 for m in metrics if m["completion_declared"]),
        safe_and_completion_declared=len(safe_declared),
        strategy_failures=sum(1 for m in metrics if m["termination_reason"] in STRATEGY_FAILURES),
        termination_reasons=dict(sorted(Counter(m["termination_reason"] for m in metrics).items())),
        statuses=dict(sorted(Counter(outcome.status.value for outcome in outcomes).items())),
        mean_abs_delta_v_error_mps=mean,
        median_abs_delta_v_error_mps=median,
        mean_abs_delta_v_error_safe_declared_mps=mean_safe_declared,
        median_abs_delta_v_error_safe_declared_mps=median_safe_declared,
        score=suite_score(score_case(outcome, scoring) for outcome in outcomes),
    )


def summary_rows(summary: SuiteSummary) -> list[dict[str, str]]:
    """Human-readable rows of a summary for a table."""

    def _error(value: float | None) -> str:
        return "-" if value is None else f"{value:.4f} m/s"

    rows = [
        ("Score", f"{summary.score:.2f}"),
        ("Cases", str(summary.cases)),
        ("Completed runs", str(summary.completed)),
        ("Not completed (load error, crash, timeout)", str(summary.not_completed)),
        ("Safe", str(summary.safe)),
        ("Completion declared", str(summary.completion_declared)),
        ("Safe and completion declared", str(summary.safe_and_completion_declared)),
        ("Strategy errors or invalid commands", str(summary.strategy_failures)),
        ("Mean |delta-v error|, completed runs", _error(summary.mean_abs_delta_v_error_mps)),
        ("Median |delta-v error|, completed runs", _error(summary.median_abs_delta_v_error_mps)),
        ("Mean |delta-v error|, safe and declared", _error(summary.mean_abs_delta_v_error_safe_declared_mps)),
        ("Median |delta-v error|, safe and declared", _error(summary.median_abs_delta_v_error_safe_declared_mps)),
    ]
    rows += [(f"Termination: {reason}", str(count)) for reason, count in summary.termination_reasons.items()]
    return [{"Statistic": label, "Value": value} for label, value in rows]


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def case_rows(outcomes: Iterable[CaseOutcome], scores: Iterable[CaseScore]) -> list[dict[str, str]]:
    """Human-readable per-case rows of scores and metrics for a table, with `scores` in the order of `outcomes`.

    Cases without metrics show their status and score only.
    """
    rows = []
    for outcome, score in zip(outcomes, scores, strict=True):
        m = outcome.metrics
        row = {"Case": outcome.case_id, "Status": outcome.status.value, "Score": f"{score.value:.4f}"}
        if m is None:
            row |= dict.fromkeys(
                (
                    "Termination",
                    "Declared",
                    "Safe",
                    "Delta-v error [m/s]",
                    "End time [s]",
                    "Min battery [Wh]",
                    "Temperature [C]",
                    "Max |wheel| [Nms]",
                ),
                "-",
            )
        else:
            row |= {
                "Termination": m["termination_reason"],
                "Declared": _yes_no(m["completion_declared"]),
                "Safe": _yes_no(m["safe"]),
                "Delta-v error [m/s]": f"{m['delta_v_error_mps']:+.4f}",
                "End time [s]": f"{m['end_time_s']:.1f}",
                "Min battery [Wh]": f"{m['min_battery_energy_wh']:.2f}",
                "Temperature [C]": (
                    f"{m['min_propulsion_temperature_c']:.2f} to {m['max_propulsion_temperature_c']:.2f}"
                ),
                "Max |wheel| [Nms]": f"{m['max_abs_wheel_momentum_nms']:.4f}",
            }
        row["Duration [s]"] = f"{outcome.duration_s:.1f}"
        row["CPU [s]"] = "-" if outcome.participant_cpu_s is None else f"{outcome.participant_cpu_s:.2f}"
        rows.append(row)
    return rows


def missing_modules(outcomes: Iterable[CaseOutcome]) -> tuple[str, ...]:
    """Sorted names of modules that the submission failed to import in any case."""
    return tuple(sorted({o.missing_module for o in outcomes if o.missing_module}))


def problem_outcomes(outcomes: Iterable[CaseOutcome]) -> tuple[CaseOutcome, ...]:
    """Outcomes worth showing details for: cases that did not complete or ended with a strategy failure."""
    return tuple(
        o
        for o in outcomes
        if o.status is not CaseStatus.COMPLETED
        or (o.metrics is not None and o.metrics["termination_reason"] in STRATEGY_FAILURES)
    )


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected a string, got {value!r}")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"expected a list, got {value!r}")
    return tuple(_string(item) for item in value)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"expected a mapping, got {value!r}")
    return value


_METRIC_TYPES: Mapping[str, type | tuple[type, ...]] = {
    "termination_reason": str,
    "completion_declared": bool,
    "safe": bool,
    "delta_v_error_mps": (int, float),
    "end_time_s": (int, float),
    "min_battery_energy_wh": (int, float),
    "min_propulsion_temperature_c": (int, float),
    "max_propulsion_temperature_c": (int, float),
    "max_abs_wheel_momentum_nms": (int, float),
    "target_delta_v_mps": (int, float),
    "completion_declared_time_s": (int, float, type(None)),
    "time_limit_s": (int, float),
    "decision_period_s": (int, float),
    "nominal_battery_capacity_wh": (int, float),
    "min_battery_energy_limit_wh": (int, float),
}
"""Metrics that the report and scoring functions read, with their JSON types."""


def _outcome(data: Mapping[str, Any]) -> CaseOutcome:
    """`CaseOutcome.from_dict`, which also checks the metrics that the report and scoring functions read."""
    outcome = CaseOutcome.from_dict(data)
    if (outcome.metrics is not None) != (outcome.status is CaseStatus.COMPLETED):
        raise ValueError(f"case {outcome.case_id!r} has metrics if and only if it is COMPLETED")
    for name, expected in _METRIC_TYPES.items() if outcome.metrics is not None else ():
        value = outcome.metrics.get(name)
        if not isinstance(value, expected) or (expected is not bool and isinstance(value, bool)):
            raise TypeError(f"metric {name} of case {outcome.case_id!r} must be {expected}, got {value!r}")
        if isinstance(value, int | float) and not isinstance(value, bool) and not math.isfinite(value):
            raise TypeError(f"metric {name} of case {outcome.case_id!r} is not finite: {value!r}")
    for value in (outcome.duration_s, outcome.participant_cpu_s):
        if value is not None and not math.isfinite(value):
            raise TypeError(f"times of case {outcome.case_id!r} must be finite, got {value!r}")
    return outcome


def _check_case_ids(case_ids: Sequence[str], outcomes: Sequence[CaseOutcome]) -> None:
    """Require unique case ids and outcomes of cases of the suite, in suite order, each at most once."""
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("the case ids of the suite must be unique")
    positions = {case_id: index for index, case_id in enumerate(case_ids)}
    indices = [positions.get(outcome.case_id) for outcome in outcomes]
    if None in indices or indices != sorted(set(indices)):
        raise ValueError("the cases must be distinct cases of the suite, in the order of its case ids")


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a finite number")


def _case_dict(outcome: CaseOutcome, *, include_worker_errors: bool) -> dict[str, Any]:
    data = outcome.to_dict()
    if not include_worker_errors:
        del data["worker_error"]
    return data


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Record of one evaluation, complete enough to aggregate without rerunning it.

    Cases appear by id and the suite by its fingerprint; case payloads are left out. `to_dict` and `to_json`
    produce the result document, and `from_dict` and `from_json` read it back. A document may have been filtered
    before it was handed over: `participant` may be `None`, `outcomes` may cover only some of `case_ids`, and the
    captured output and details may be empty. `summary`, including the suite score, and `scores` are stored with
    the document and never recomputed from `outcomes`.
    """

    participant: str | None
    submission_sha256: str
    skipped_entries: tuple[str, ...]
    """Archive entries outside `submission/`, which were not extracted, except `pyproject.toml`."""
    dependencies: DependencyReport
    suite_name: str
    suite_fingerprint: str
    case_ids: tuple[str, ...]
    """Ids of every case of the suite, in order."""
    core_version: str
    """Version of the core package that ran the evaluation."""
    started_at: str
    """UTC start time in ISO 8601 format."""
    finished_at: str
    scoring: ScoringConfig
    """Configuration that scored the outcomes."""
    summary: SuiteSummary
    outcomes: tuple[CaseOutcome, ...]
    scores: tuple[CaseScore, ...]
    """Score of each outcome, in the order of `outcomes`."""

    @classmethod
    def from_evaluation(cls, evaluation: SubmissionEvaluation, *, participant: str | None = None) -> "EvaluationResult":
        """The record of `evaluation`, with the summary and the scores of all its outcomes."""
        return cls(
            participant=participant,
            submission_sha256=evaluation.submission_sha256,
            skipped_entries=evaluation.skipped_entries,
            dependencies=evaluation.dependencies,
            suite_name=evaluation.suite.name,
            suite_fingerprint=evaluation.suite.fingerprint,
            case_ids=tuple(case.case_id for case in evaluation.suite.cases),
            core_version=core_version,
            started_at=evaluation.started_at,
            finished_at=evaluation.finished_at,
            scoring=evaluation.scoring,
            summary=summarize(evaluation.outcomes, evaluation.scoring),
            outcomes=evaluation.outcomes,
            scores=tuple(score_case(outcome, evaluation.scoring) for outcome in evaluation.outcomes),
        )

    def to_dict(self, *, include_worker_errors: bool = False) -> dict[str, Any]:
        """The result document as a JSON-serializable dictionary.

        `worker_error` of the cases is left out unless `include_worker_errors` is true, because it may show the
        scenario provider and data of the case.
        """
        return {
            "format": RESULT_FORMAT,
            "format_version": RESULT_FORMAT_VERSION,
            "participant": self.participant,
            "submission": {"sha256": self.submission_sha256, "skipped_entries": list(self.skipped_entries)},
            "dependencies": self.dependencies.to_dict(),
            "suite": {"name": self.suite_name, "fingerprint": self.suite_fingerprint, "case_ids": list(self.case_ids)},
            "core_version": self.core_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "scoring": self.scoring.to_dict(),
            "summary": self.summary.to_dict(),
            "cases": [
                _case_dict(outcome, include_worker_errors=include_worker_errors) | {"score": score.to_dict()}
                for outcome, score in zip(self.outcomes, self.scores, strict=True)
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationResult":
        """Inverse of `to_dict`. Raises `ResultFormatError` for another format or version, or malformed data."""
        if not isinstance(data, Mapping):
            raise ResultFormatError(f"a result document must be a JSON object, got {type(data).__name__}")
        if data.get("format") != RESULT_FORMAT:
            raise ResultFormatError(f"not a result document: format is {data.get('format')!r}, not {RESULT_FORMAT!r}")
        version = data.get("format_version")
        if not isinstance(version, int) or isinstance(version, bool) or version != RESULT_FORMAT_VERSION:
            raise ResultFormatError(
                f"unsupported result format version {version!r}; this version reads {RESULT_FORMAT_VERSION}"
            )
        try:
            participant = data["participant"]
            submission, suite = _mapping(data["submission"]), _mapping(data["suite"])
            cases = data["cases"]
            if not isinstance(cases, list):
                raise TypeError(f"cases must be a list, got {cases!r}")
            cases = [_mapping(case) for case in cases]
            outcomes = tuple(_outcome(case) for case in cases)
            _check_case_ids(_strings(suite["case_ids"]), outcomes)
            return cls(
                participant=None if participant is None else _string(participant),
                submission_sha256=_string(submission["sha256"]),
                skipped_entries=_strings(submission["skipped_entries"]),
                dependencies=DependencyReport.from_dict(_mapping(data["dependencies"])),
                suite_name=_string(suite["name"]),
                suite_fingerprint=_string(suite["fingerprint"]),
                case_ids=_strings(suite["case_ids"]),
                core_version=_string(data["core_version"]),
                started_at=_string(data["started_at"]),
                finished_at=_string(data["finished_at"]),
                scoring=ScoringConfig.from_dict(_mapping(data["scoring"])),
                summary=SuiteSummary.from_dict(_mapping(data["summary"])),
                outcomes=outcomes,
                scores=tuple(CaseScore.from_dict(_mapping(case["score"])) for case in cases),
            )
        except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
            raise ResultFormatError(f"malformed result document: {error!r}") from None

    def to_json(self, *, include_worker_errors: bool = False) -> str:
        """The result document as JSON text, indented by two spaces and ending with a newline (see `to_dict`)."""
        return json.dumps(self.to_dict(include_worker_errors=include_worker_errors), indent=2, allow_nan=False) + "\n"

    @classmethod
    def from_json(cls, text: str | bytes) -> "EvaluationResult":
        """Inverse of `to_json`; accepts any JSON layout. Raises `ResultFormatError` for text that is not one."""
        try:
            data = json.loads(text, parse_constant=_reject_constant)
        except (ValueError, RecursionError) as error:
            raise ResultFormatError(f"a result document must be JSON: {error}") from None
        return cls.from_dict(data)
