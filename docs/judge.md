# Evaluation Cases

**English** | [日本語](judge.ja.md)

This page describes evaluation cases, suites, and scenario providers (`spacecraft_ops_challenge.judge.cases`),
and the scenario provider for the public scenarios (`spacecraft_ops_challenge.judge.public_scenarios`).
They define the scenarios that a submission is evaluated on.

```python
from spacecraft_ops_challenge.judge.cases import EvaluationCase, ScenarioProvider, Suite

suite = Suite("example", (EvaluationCase.of("case-001", {"seed": 1}), EvaluationCase.of("case-002", {"seed": 2})))
provider = ScenarioProvider("my_cases.provider:build_scenario", paths=("path/to/directory/of/my_cases",))
provider.check(suite.cases)
scenario = provider.build(suite.cases[0])
```

Whoever evaluates submissions can define their own cases and scenario provider.
Invalid cases, suites, and providers raise `CaseError`, a subclass of `ValueError`.

## Evaluation Cases

An `EvaluationCase` is a stable id together with a payload, a mapping of JSON data.
The payload is opaque: only the scenario provider gives it a meaning.

- `EvaluationCase.of(case_id, payload)` builds a case from a JSON-compatible mapping.
- `EvaluationCase(case_id, payload_json)` builds a case from a JSON string.
- `payload` returns a fresh copy of the payload, so changing it does not change the case.
- `to_dict()` returns `{"id": ..., "payload": ...}`, and `EvaluationCase.from_dict` is its inverse.

The case id must be a non-empty string.
The payload must be a mapping of finite JSON data: `NaN` and infinities are rejected.

The payload is stored as canonical JSON in `payload_json`, with sorted keys and without whitespace.
Cases are therefore immutable and hashable,
and two cases with the same id and equal payloads are equal regardless of the order of their keys.

## Suites

A `Suite` is a named, ordered collection of cases.
The ids of its cases must be unique.

`fingerprint` is the SHA-256 of the canonical JSON of the case ids and payloads, as a hexadecimal string.
It identifies the exact cases, including their order, without revealing them.
The name of the suite is not part of the fingerprint.

## Scenario Providers

A scenario provider is a module-level function that takes a payload and returns a `Scenario`
(see [Simulation](simulation.md)).
A `ScenarioProvider` names it as `module:function`.
Its `paths` are directories added to the import path when the provider is loaded, for code that is not installed;
they are stored as absolute paths.

| Name | Meaning |
|---|---|
| `ScenarioProvider.from_callable(function)` | The provider of a module-level function, with the directory that contains its top-level package as `paths` |
| `load()` | Imports the function, with `paths` appended to the import path of the current process |
| `build(case)` | The scenario of `case`; `CaseError` if the function does not return a `Scenario` |
| `check(cases)` | Builds the scenario of every case once, so that a broken provider fails early |
| `to_dict()` | `{"target": ..., "paths": [...]}`; `ScenarioProvider.from_dict` is its inverse |

`load` raises `CaseError` if the module or the function is not found, or if the target is not callable.
`check` also turns any other exception of the provider into a `CaseError` that names the failing case.
A target that does not have the form `module:function` raises `CaseError`,
and so does `from_callable` for a function that is not defined at the top level of an importable module,
such as one in `__main__`.

## Public Scenarios

`spacecraft_ops_challenge.judge.public_scenarios` evaluates on the public scenarios of the challenge
(see [Challenge Problem](challenge.md)), for trying an evaluation without cases of your own.

```python
from spacecraft_ops_challenge.judge.public_scenarios import PROVIDER, public_suite

suite = public_suite()
scenarios = [PROVIDER.build(case) for case in suite.cases]
```

- `PROVIDER` is the scenario provider `spacecraft_ops_challenge.judge.public_scenarios:build_scenario`.
- A payload is `{"scenario": name}` or `{"scenario": name, "seed": seed}`;
  `name` is one of `scenario_names()`, and a `seed` that is not `None` replaces the seed of the scenario.
- `public_suite()` returns the suite `public` with one case per public scenario, whose id is the scenario name.
