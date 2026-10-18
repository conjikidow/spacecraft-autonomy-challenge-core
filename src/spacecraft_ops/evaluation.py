"""Per-run evaluation metrics computed from the ground truth of a run."""

from dataclasses import dataclass
from typing import Any

from spacecraft_ops.results import RunResult, SafetyViolation, TerminationReason


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Metrics of one run, computed from the true states rather than from telemetry.

    Extremes are taken over the trajectory and the final state.
    """

    termination_reason: TerminationReason
    end_time_s: float
    completed: bool
    """Whether the run ended with `MISSION_COMPLETE`."""
    safe: bool
    """Whether no safety limit was violated."""
    safety_violations: tuple[SafetyViolation, ...]
    target_delta_v_mps: float
    delta_v_mps: float
    """True delta-v at the end of the run."""
    delta_v_error_mps: float
    """Achieved minus target delta-v."""
    completion_time_s: float | None
    """Termination time if the run completed, otherwise `None`."""
    time_limit_s: float
    min_battery_energy_wh: float
    min_propulsion_temperature_c: float
    max_propulsion_temperature_c: float
    max_abs_wheel_momentum_nms: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary of all metrics."""
        return {
            "termination_reason": self.termination_reason.value,
            "end_time_s": self.end_time_s,
            "completed": self.completed,
            "safe": self.safe,
            "safety_violations": [
                {"reason": violation.reason.value, "time_s": violation.time_s, "message": violation.message}
                for violation in self.safety_violations
            ],
            "target_delta_v_mps": self.target_delta_v_mps,
            "delta_v_mps": self.delta_v_mps,
            "delta_v_error_mps": self.delta_v_error_mps,
            "completion_time_s": self.completion_time_s,
            "time_limit_s": self.time_limit_s,
            "min_battery_energy_wh": self.min_battery_energy_wh,
            "min_propulsion_temperature_c": self.min_propulsion_temperature_c,
            "max_propulsion_temperature_c": self.max_propulsion_temperature_c,
            "max_abs_wheel_momentum_nms": self.max_abs_wheel_momentum_nms,
        }


@dataclass(frozen=True, slots=True)
class ScoreWeights:
    """Relative weights of the accuracy and time terms of `reference_score`."""

    accuracy: float = 0.8
    time: float = 0.2

    def __post_init__(self) -> None:
        if self.accuracy < 0 or self.time < 0:
            raise ValueError("weights must not be negative")
        if self.accuracy + self.time <= 0:
            raise ValueError("weights must have a positive sum")


def evaluate(result: RunResult) -> RunMetrics:
    """Compute the metrics of a run from its ground truth."""
    states = (*result.trajectory, result.final_state)
    reason = result.termination.reason
    completed = reason is TerminationReason.MISSION_COMPLETE
    scenario = result.scenario
    return RunMetrics(
        termination_reason=reason,
        end_time_s=result.termination.time_s,
        completed=completed,
        safe=not result.safety_violations,
        safety_violations=result.safety_violations,
        target_delta_v_mps=scenario.target_delta_v_mps,
        delta_v_mps=result.final_state.delta_v_mps,
        delta_v_error_mps=result.final_state.delta_v_mps - scenario.target_delta_v_mps,
        completion_time_s=result.termination.time_s if completed else None,
        time_limit_s=scenario.time_limit_s,
        min_battery_energy_wh=min(state.battery_energy_wh for state in states),
        min_propulsion_temperature_c=min(state.propulsion_temperature_c for state in states),
        max_propulsion_temperature_c=max(state.propulsion_temperature_c for state in states),
        max_abs_wheel_momentum_nms=max(abs(state.wheel_momentum_nms) for state in states),
    )


def reference_score(metrics: RunMetrics, weights: ScoreWeights = ScoreWeights()) -> float:  # noqa: B008
    """Simple configurable score in [0, 1] for comparing runs locally.

    The score is 0 unless the run completed safely. Otherwise it is the weighted mean of an accuracy term,
    `max(0, 1 - |delta_v_error| / target)`, and a time term, `max(0, 1 - completion_time / time_limit)`.
    """
    if not (metrics.completed and metrics.safe) or metrics.completion_time_s is None:
        return 0.0
    if metrics.target_delta_v_mps == 0:
        accuracy = 1.0 if metrics.delta_v_error_mps == 0 else 0.0
    else:
        accuracy = max(0.0, 1.0 - abs(metrics.delta_v_error_mps) / metrics.target_delta_v_mps)
    time = max(0.0, 1.0 - metrics.completion_time_s / metrics.time_limit_s)
    score = (weights.accuracy * accuracy + weights.time * time) / (weights.accuracy + weights.time)
    return min(1.0, max(0.0, score))
