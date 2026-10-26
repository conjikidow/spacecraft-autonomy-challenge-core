import sys

import pytest
from judge_support import PROVIDER, case

from spacecraft_ops_challenge.challenge import scenario, scenario_names
from spacecraft_ops_challenge.judge import public_scenarios
from spacecraft_ops_challenge.judge.cases import CaseError, EvaluationCase, ScenarioProvider, Suite
from spacecraft_ops_challenge.modifiers import ThrusterEfficiency
from spacecraft_ops_challenge.scenario import Scenario


@pytest.fixture(autouse=True)
def _restore_import_state(monkeypatch):
    """Undo what loading a provider adds to the import path and the module cache."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    sys.modules.pop("judge_test_provider", None)


def module_level_factory(payload):
    return public_scenarios.build_scenario(payload)


def test_cases_are_immutable_and_keep_their_payload():
    payload = {"b": [1, 2.5, {"c": None}], "a": "x"}
    evaluation_case = EvaluationCase.of("one", payload)
    payload["b"].append(3)
    assert evaluation_case.payload == {"a": "x", "b": [1, 2.5, {"c": None}]}
    evaluation_case.payload["a"] = "changed"
    assert evaluation_case.payload["a"] == "x"
    assert evaluation_case == EvaluationCase.of("one", {"a": "x", "b": [1, 2.5, {"c": None}]})
    assert hash(evaluation_case) == hash(EvaluationCase.from_dict(evaluation_case.to_dict()))
    with pytest.raises(AttributeError):
        evaluation_case.case_id = "two"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("case_id", "payload", "message"),
    [
        ("", {}, "non-empty string"),
        ("x", [1], "must be a mapping"),
        ("x", {"value": float("nan")}, "finite JSON data"),
        ("x", {"value": object()}, "finite JSON data"),
    ],
)
def test_invalid_cases(case_id, payload, message):
    with pytest.raises(CaseError, match=message):
        EvaluationCase.of(case_id, payload)


def test_direct_construction_validates_and_canonicalizes_the_payload():
    assert EvaluationCase("x", '{ "b": 1, "a": [1, 2] }') == EvaluationCase.of("x", {"a": [1, 2], "b": 1})
    assert EvaluationCase("x", '{"b":1,"a":2}').payload_json == '{"a":2,"b":1}'
    for payload_json, message in (("not json", "must be JSON"), ("[1]", "must be a mapping"), ('{"v": NaN}', "NaN")):
        with pytest.raises(CaseError, match=message):
            EvaluationCase("x", payload_json)


def test_cases_from_dict_need_an_id_and_a_payload():
    with pytest.raises(CaseError, match="needs an 'id' and a 'payload'"):
        EvaluationCase.from_dict({"id": "x"})


def test_suite_fingerprint_identifies_the_exact_cases():
    first = Suite("s", (EvaluationCase.of("a", {"x": 1, "y": 2}), EvaluationCase.of("b", {})))
    assert (
        first.fingerprint
        == Suite("s", (EvaluationCase.of("a", {"y": 2, "x": 1}), EvaluationCase.of("b", {}))).fingerprint
    )
    assert (
        first.fingerprint
        != Suite("s", (EvaluationCase.of("a", {"x": 1, "y": 3}), EvaluationCase.of("b", {}))).fingerprint
    )
    assert first.fingerprint != Suite("s", tuple(reversed(first.cases))).fingerprint
    assert len(first.fingerprint) == 64


def test_suite_case_ids_are_unique():
    with pytest.raises(CaseError, match="duplicate case ids: a"):
        Suite("s", [EvaluationCase.of("a", {}), EvaluationCase.of("a", {"other": True})])


@pytest.mark.parametrize("target", ["module", "module:", ":function", ""])
def test_provider_targets_name_a_module_and_a_function(target):
    with pytest.raises(CaseError, match="'module:function'"):
        ScenarioProvider(target)


def test_provider_builds_scenarios_from_its_paths():
    built = PROVIDER.build(case("x", 5, {"type": "ThrusterEfficiency", "thruster": "THRUSTER_2", "factor": 0.7}))
    assert isinstance(built, Scenario)
    assert built.seed == 5
    assert built.modifiers == (ThrusterEfficiency("THRUSTER_2", factor=0.7),)
    assert ScenarioProvider.from_dict(PROVIDER.to_dict()) == PROVIDER


def test_provider_errors_are_case_errors():
    paths = PROVIDER.paths
    with pytest.raises(CaseError, match="cannot import the scenario provider 'no_such_module:f'"):
        ScenarioProvider("no_such_module:f").load()
    with pytest.raises(CaseError, match="cannot import"):
        ScenarioProvider("judge_test_provider:missing", paths).load()
    with pytest.raises(CaseError, match="is not callable"):
        ScenarioProvider("judge_test_provider:TYPES", paths).load()
    with pytest.raises(CaseError, match="returned str for case 'x'"):
        ScenarioProvider("judge_test_provider:not_a_scenario", paths).build(case("x"))
    with pytest.raises(CaseError, match="failed for case 'x': RuntimeError"):
        ScenarioProvider("judge_test_provider:failing", paths).check([case("x")])
    PROVIDER.check([case("x"), case("y", 1)])


def test_provider_from_a_module_level_callable():
    provider = ScenarioProvider.from_callable(module_level_factory)
    assert provider.target == "test_judge_cases:module_level_factory"
    assert provider.build(EvaluationCase.of("n", {"scenario": "nominal"})) == scenario("nominal")
    with pytest.raises(CaseError, match="not a module-level function"):
        ScenarioProvider.from_callable(lambda payload: None)


def test_public_suite_has_one_case_per_public_scenario():
    suite = public_scenarios.public_suite()
    assert [c.case_id for c in suite.cases] == list(scenario_names())
    assert [c.payload for c in suite.cases] == [{"scenario": name} for name in scenario_names()]
    public_scenarios.PROVIDER.check(suite.cases)


@pytest.mark.parametrize("name", scenario_names())
def test_public_scenarios_provider_builds_the_named_scenario(name):
    assert public_scenarios.PROVIDER.build(EvaluationCase.of(name, {"scenario": name})) == scenario(name)
    assert public_scenarios.PROVIDER.build(EvaluationCase.of(name, {"scenario": name, "seed": None})) == scenario(name)


def test_public_scenarios_provider_overrides_the_seed():
    built = public_scenarios.PROVIDER.build(EvaluationCase.of("x", {"scenario": "thruster-degradation", "seed": 9}))
    assert built.seed == 9
    assert built.modifiers == scenario("thruster-degradation").modifiers


def test_public_scenarios_provider_target_imports():
    assert public_scenarios.PROVIDER.paths == ()
    assert public_scenarios.PROVIDER.load() is public_scenarios.build_scenario
