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
    completion_declared: bool
    """Whether the run ended because the strategy executed `DeclareCompletion`.

    Declaring completion is not success.
    Judge the outcome from fields such as `safe` and `delta_v_error_mps`.
    """
    safe: bool
    """Whether no safety limit was violated."""
    safety_violations: tuple[SafetyViolation, ...]
    target_delta_v_mps: float
    delta_v_mps: float
    """True delta-v at the end of the run."""
    delta_v_error_mps: float
    """Achieved minus target delta-v."""
    completion_declared_time_s: float | None
    """Time at which completion was declared, otherwise `None`."""
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
            "completion_declared": self.completion_declared,
            "safe": self.safe,
            "safety_violations": [
                {"reason": violation.reason.value, "time_s": violation.time_s, "message": violation.message}
                for violation in self.safety_violations
            ],
            "target_delta_v_mps": self.target_delta_v_mps,
            "delta_v_mps": self.delta_v_mps,
            "delta_v_error_mps": self.delta_v_error_mps,
            "completion_declared_time_s": self.completion_declared_time_s,
            "time_limit_s": self.time_limit_s,
            "min_battery_energy_wh": self.min_battery_energy_wh,
            "min_propulsion_temperature_c": self.min_propulsion_temperature_c,
            "max_propulsion_temperature_c": self.max_propulsion_temperature_c,
            "max_abs_wheel_momentum_nms": self.max_abs_wheel_momentum_nms,
        }


def evaluate(result: RunResult) -> RunMetrics:
    """Compute the metrics of a run from its ground truth."""
    states = (*result.trajectory, result.final_state)
    reason = result.termination.reason
    completion_declared = reason is TerminationReason.COMPLETION_DECLARED
    scenario = result.scenario
    return RunMetrics(
        termination_reason=reason,
        end_time_s=result.termination.time_s,
        completion_declared=completion_declared,
        safe=not result.safety_violations,
        safety_violations=result.safety_violations,
        target_delta_v_mps=scenario.problem.target_delta_v_mps,
        delta_v_mps=result.final_state.delta_v_mps,
        delta_v_error_mps=result.final_state.delta_v_mps - scenario.problem.target_delta_v_mps,
        completion_declared_time_s=result.termination.time_s if completion_declared else None,
        time_limit_s=scenario.problem.time_limit_s,
        min_battery_energy_wh=min(state.battery_energy_wh for state in states),
        min_propulsion_temperature_c=min(state.propulsion_temperature_c for state in states),
        max_propulsion_temperature_c=max(state.propulsion_temperature_c for state in states),
        max_abs_wheel_momentum_nms=max(abs(state.wheel_momentum_nms) for state in states),
    )
