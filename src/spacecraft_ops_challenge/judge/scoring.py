"""Scores of evaluated cases and suites, from run metrics, participant CPU time, and a scoring configuration.

The score of a case is a number from 0 to 1:

    gate * accuracy * declaration * (w_base + w_time * completion_time + w_battery * battery_margin + w_cpu * cpu_time)

and the score of a suite is 100 times the mean score of its cases. No pass threshold is applied.
"""

import math
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields
from importlib.resources import files
from pathlib import Path
from typing import Any

from spacecraft_ops_challenge.judge.runner import CaseOutcome, CaseStatus
from spacecraft_ops_challenge.results import TerminationReason

SCORING_CONFIG_VERSION = 1

_WEIGHT_SUM_TOLERANCE = 1e-9
STRATEGY_FAILURES = frozenset({TerminationReason.STRATEGY_ERROR.value, TerminationReason.INVALID_COMMAND.value})
"""Termination reasons of runs that ended because of the strategy, as their string values."""


class ScoringConfigError(ValueError):
    """Raised for a scoring configuration that is malformed, of another version, or out of range."""


def _check_finite(values: Mapping[str, object]) -> None:
    for name, value in values.items():
        if not isinstance(value, int | float) or isinstance(value, bool) or not _finite(value):
            raise ScoringConfigError(f"{name} must be a finite number, got {value!r}")


def _finite(value: float) -> bool:
    try:
        return math.isfinite(value)
    except OverflowError:  # an integer too large for a float
        return False


def _check_positive(section: object, *names: str) -> None:
    for name in names:
        if not getattr(section, name) > 0:
            raise ScoringConfigError(f"{name} must be positive, got {getattr(section, name)!r}")


@dataclass(frozen=True, slots=True)
class AccuracyParameters:
    """How fast the score falls with the delta-v error."""

    tolerance_fraction: float
    """Absolute delta-v error, as a fraction of the target delta-v, at which the accuracy factor reaches 0."""

    def __post_init__(self) -> None:
        _check_finite(asdict(self))
        _check_positive(self, "tolerance_fraction")


@dataclass(frozen=True, slots=True)
class DeclarationParameters:
    """How a run that did not declare completion is scored."""

    undeclared_factor: float
    """Declaration factor of a run that did not declare completion, from 0 to 1."""

    def __post_init__(self) -> None:
        _check_finite(asdict(self))
        if not 0 <= self.undeclared_factor <= 1:
            raise ScoringConfigError(f"undeclared_factor must be from 0 to 1, got {self.undeclared_factor!r}")


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    """Weights of the terms of the score. They are non-negative and sum to 1."""

    base: float
    completion_time: float
    battery_margin: float
    cpu_time: float

    def __post_init__(self) -> None:
        _check_finite(asdict(self))
        for field in fields(self):
            if getattr(self, field.name) < 0:
                raise ScoringConfigError(f"weight {field.name} must not be negative, got {getattr(self, field.name)!r}")
        total = math.fsum(getattr(self, field.name) for field in fields(self))
        if abs(total - 1) > _WEIGHT_SUM_TOLERANCE:
            raise ScoringConfigError(f"weights must sum to 1, got {total!r}")


@dataclass(frozen=True, slots=True)
class CpuTimeParameters:
    """CPU time budget of the participant process in one run."""

    startup_allowance_s: float
    """Budget for interpreter start-up and loading the strategy."""
    per_decision_cycle_s: float
    """Budget per decision cycle of the time limit."""

    def __post_init__(self) -> None:
        _check_finite(asdict(self))
        _check_positive(self, "startup_allowance_s", "per_decision_cycle_s")

    def budget_s(self, time_limit_s: float, decision_period_s: float) -> float:
        """CPU time budget of a run with the given time limit and decision period."""
        return self.startup_allowance_s + self.per_decision_cycle_s * time_limit_s / decision_period_s


_SECTIONS: Mapping[str, type] = {
    "accuracy": AccuracyParameters,
    "declaration": DeclarationParameters,
    "weights": ScoreWeights,
    "cpu_time": CpuTimeParameters,
}


@dataclass(frozen=True, slots=True)
class ScoringConfig:
    """Parameters of the scoring formula, read from TOML or from the dictionary of `to_dict`."""

    accuracy: AccuracyParameters
    declaration: DeclarationParameters
    weights: ScoreWeights
    cpu_time: CpuTimeParameters

    @classmethod
    def default(cls) -> "ScoringConfig":
        """The configuration shipped with this package as `spacecraft_ops_challenge/judge/scoring.toml`."""
        return cls.from_toml(files("spacecraft_ops_challenge.judge").joinpath("scoring.toml").read_bytes())

    @classmethod
    def from_toml(cls, data: bytes | str | Path) -> "ScoringConfig":
        """Read a configuration from TOML: UTF-8 bytes, text, or the path of a file.

        Raises `ScoringConfigError` for text that is not TOML or does not describe a configuration, and `OSError`
        for a file that cannot be read.
        """
        if isinstance(data, Path):
            data = data.read_bytes()
        try:
            text = data.decode() if isinstance(data, bytes) else data
            return cls.from_dict(tomllib.loads(text))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
            raise ScoringConfigError(f"a scoring configuration must be UTF-8 TOML: {error}") from None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoringConfig":
        """Inverse of `to_dict`. Raises `ScoringConfigError` for data that does not describe a configuration.

        Every section and key is required, and keys that the format does not define are rejected.
        """
        if not isinstance(data, Mapping):
            raise ScoringConfigError(f"a scoring configuration must be a mapping, got {type(data).__name__}")
        version = data.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version != SCORING_CONFIG_VERSION:
            raise ScoringConfigError(
                f"unsupported scoring configuration version {version!r}; this version reads {SCORING_CONFIG_VERSION}"
            )
        _check_keys("the scoring configuration", data, {"version", *_SECTIONS})
        sections = {}
        for name, section_type in _SECTIONS.items():
            section = data[name]
            if not isinstance(section, Mapping):
                raise ScoringConfigError(f"section {name} must be a table, got {section!r}")
            _check_keys(f"section {name}", section, {field.name for field in fields(section_type)})
            sections[name] = section_type(**section)
        return cls(**sections)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the configuration, in the layout of the TOML file."""
        return {"version": SCORING_CONFIG_VERSION} | {name: asdict(getattr(self, name)) for name in _SECTIONS}


def _check_keys(where: str, data: Mapping[str, Any], expected: set[str]) -> None:
    if unknown := sorted(str(key) for key in set(data) - expected):
        raise ScoringConfigError(f"unknown keys in {where}: {', '.join(unknown)}")
    if missing := sorted(expected - set(data)):
        raise ScoringConfigError(f"missing keys in {where}: {', '.join(missing)}")


@dataclass(frozen=True, slots=True)
class CaseScore:
    """Score of one case with the factors and terms it is made of, each from 0 to 1.

    `value` is `gate * accuracy * declaration * (weighted sum of the base, completion_time, battery_margin, and
    cpu_time terms)`. A case without metrics has every component 0.
    """

    value: float
    gate: float
    """1 for a completed, safe run that did not end with a strategy failure, otherwise 0."""
    accuracy: float
    declaration: float
    completion_time: float
    battery_margin: float
    cpu_time: float

    def to_dict(self) -> dict[str, float]:
        """JSON-serializable dictionary of the score."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseScore":
        """Inverse of `to_dict`. Raises `ValueError` for data that does not describe a case score."""
        try:
            if not isinstance(data, Mapping):
                raise TypeError(f"expected a mapping, got {data!r}")
            values = {field.name: data[field.name] for field in fields(cls)}
            for name, value in values.items():
                if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= value <= 1:
                    raise TypeError(f"{name} must be a number from 0 to 1, got {value!r}")
            return cls(**{name: float(value) for name, value in values.items()})
        except (KeyError, TypeError) as error:
            raise ValueError(f"not a case score: {error!r}") from None


ZERO_SCORE = CaseScore(
    value=0.0, gate=0.0, accuracy=0.0, declaration=0.0, completion_time=0.0, battery_margin=0.0, cpu_time=0.0
)
"""Score of a case without metrics."""


def _clip(value: float) -> float:
    return min(1.0, max(0.0, value))


def score_case(outcome: CaseOutcome, config: ScoringConfig) -> CaseScore:
    """Score of `outcome` under `config`.

    It reads the status, the metrics, and the participant CPU time of the outcome only. Every factor and term is
    computed even when the gate is 0, so that the score can be explained.
    """
    m = outcome.metrics
    if m is None:
        return ZERO_SCORE
    gate = (
        outcome.status is CaseStatus.COMPLETED
        and m["safe"] is True
        and m["termination_reason"] not in STRATEGY_FAILURES
    )
    tolerance_mps = config.accuracy.tolerance_fraction * m["target_delta_v_mps"]
    error_mps = abs(m["delta_v_error_mps"])
    accuracy = max(0.0, 1 - error_mps / tolerance_mps) if tolerance_mps > 0 else float(error_mps == 0)
    declared = m["completion_declared"] is True
    declaration = 1.0 if declared else config.declaration.undeclared_factor
    declared_at_s, time_limit_s = m["completion_declared_time_s"], m["time_limit_s"]
    completion_time = (
        _clip(1 - declared_at_s / time_limit_s) if declared and declared_at_s is not None and time_limit_s > 0 else 0.0
    )
    battery_span_wh = m["nominal_battery_capacity_wh"] - m["min_battery_energy_limit_wh"]
    battery_margin = (
        _clip((m["min_battery_energy_wh"] - m["min_battery_energy_limit_wh"]) / battery_span_wh)
        if battery_span_wh > 0
        else 0.0
    )
    cpu_s = outcome.participant_cpu_s
    if cpu_s is None or m["decision_period_s"] <= 0:
        cpu_time = 0.0
    elif cpu_s <= 0:
        cpu_time = 1.0
    else:
        cpu_time = min(1.0, config.cpu_time.budget_s(m["time_limit_s"], m["decision_period_s"]) / cpu_s)
    weights = config.weights
    weighted = _clip(
        weights.base
        + weights.completion_time * completion_time
        + weights.battery_margin * battery_margin
        + weights.cpu_time * cpu_time
    )
    return CaseScore(
        value=float(gate) * accuracy * declaration * weighted,
        gate=float(gate),
        accuracy=accuracy,
        declaration=declaration,
        completion_time=completion_time,
        battery_margin=battery_margin,
        cpu_time=cpu_time,
    )


def suite_score(scores: Iterable[CaseScore]) -> float:
    """Score of a suite from 0 to 100: 100 times the mean `value` of the scores of all its cases, 0 without any."""
    values = [score.value for score in scores]
    return 100 * math.fsum(values) / len(values) if values else 0.0
