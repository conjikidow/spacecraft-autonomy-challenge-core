"""Scenario definitions: everything needed to configure one simulation run."""

from dataclasses import dataclass

from spacecraft_ops.model import SafetyLimits, SpacecraftParameters, SpacecraftState
from spacecraft_ops.modifiers import Modifier
from spacecraft_ops.strategy import MissionBrief


@dataclass(frozen=True)
class Scenario:
    """One configured run: nominal model, initial state, limits, goal, timing, modifiers, and seed.

    `parameters` is the published nominal model. Deviations from it are expressed through `modifiers`,
    which strategies never see.
    """

    name: str
    parameters: SpacecraftParameters
    initial_state: SpacecraftState
    limits: SafetyLimits
    target_delta_v_mps: float
    time_limit_s: float
    integration_step_s: float
    decision_period_s: float
    modifiers: tuple[Modifier, ...] = ()
    seed: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "modifiers", tuple(self.modifiers))
        if self.initial_state.time_s != 0.0:
            raise ValueError("initial_state.time_s must be 0")
        if self.target_delta_v_mps < 0:
            raise ValueError("target_delta_v_mps must not be negative")
        for name in ("time_limit_s", "integration_step_s", "decision_period_s"):
            if not getattr(self, name) > 0:
                raise ValueError(f"{name} must be positive")

    def brief(self) -> MissionBrief:
        """Participant-visible projection. Omits the name, description, modifiers, and seed."""
        return MissionBrief(
            target_delta_v_mps=self.target_delta_v_mps,
            time_limit_s=self.time_limit_s,
            decision_period_s=self.decision_period_s,
            limits=self.limits,
            nominal_parameters=self.parameters,
        )
