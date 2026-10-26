"""Scenario provider for the public scenarios, for trying an evaluation without cases of your own.

A payload names a public scenario and may override its seed: `{"scenario": "nominal", "seed": 7}`.
"""

from dataclasses import replace
from typing import Any

from spacecraft_ops_challenge.challenge import scenario, scenario_names
from spacecraft_ops_challenge.judge.cases import EvaluationCase, ScenarioProvider, Suite
from spacecraft_ops_challenge.scenario import Scenario

PROVIDER = ScenarioProvider("spacecraft_ops_challenge.judge.public_scenarios:build_scenario")


def build_scenario(payload: dict[str, Any]) -> Scenario:
    """The public scenario named by the payload, with its seed overridden if the payload gives one."""
    built = scenario(payload["scenario"])
    return built if payload.get("seed") is None else replace(built, seed=payload["seed"])


def public_suite() -> Suite:
    """A suite with one case per public scenario."""
    return Suite("public", tuple(EvaluationCase.of(name, {"scenario": name}) for name in scenario_names()))
