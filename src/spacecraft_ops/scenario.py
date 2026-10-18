"""Scenarios: a problem together with deviations from its nominal behavior."""

from dataclasses import dataclass

from spacecraft_ops.modifiers import Modifier
from spacecraft_ops.problem import Problem
from spacecraft_ops.strategy import MissionBrief


@dataclass(frozen=True)
class Scenario:
    """One variant of a problem: modifiers applied during the run and the seed of its random number generator.

    A scenario without modifiers behaves exactly as the problem's nominal model. Strategies never see the
    modifiers, the seed, or the scenario's name and description.
    """

    name: str
    problem: Problem
    modifiers: tuple[Modifier, ...] = ()
    seed: int = 0
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "modifiers", tuple(self.modifiers))

    def brief(self) -> MissionBrief:
        """Information given to a strategy; identical for every scenario of the same problem."""
        return self.problem.brief()
