"""Numerical settings of the simulator, kept separate from the problem definition."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Settings that affect numerical accuracy only. Strategies never see them."""

    integration_step_s: float = 1.0
    """Maximum step of the explicit Euler integrator."""

    def __post_init__(self) -> None:
        if not self.integration_step_s > 0:
            raise ValueError("integration_step_s must be positive")
