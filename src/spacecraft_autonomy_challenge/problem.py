"""Problem definitions: the fixed task that every scenario of a problem shares."""

from dataclasses import dataclass

from spacecraft_autonomy_challenge.model import SafetyLimits, SpacecraftParameters, SpacecraftState
from spacecraft_autonomy_challenge.strategy import MissionBrief


@dataclass(frozen=True, slots=True)
class Problem:
    """Nominal spacecraft, initial state, safety limits, goal, and timing of an operations task."""

    parameters: SpacecraftParameters
    """Published nominal model of the spacecraft."""
    initial_state: SpacecraftState
    limits: SafetyLimits
    target_delta_v_mps: float
    time_limit_s: float
    decision_period_s: float

    def __post_init__(self) -> None:
        if self.initial_state.time_s != 0.0:
            raise ValueError("initial_state.time_s must be 0")
        if self.target_delta_v_mps < 0:
            raise ValueError("target_delta_v_mps must not be negative")
        for name in ("time_limit_s", "decision_period_s"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be positive")

    def brief(self) -> MissionBrief:
        """Information given to a strategy before autonomous operation starts."""
        return MissionBrief(
            target_delta_v_mps=self.target_delta_v_mps,
            time_limit_s=self.time_limit_s,
            decision_period_s=self.decision_period_s,
            limits=self.limits,
            nominal_parameters=self.parameters,
        )
