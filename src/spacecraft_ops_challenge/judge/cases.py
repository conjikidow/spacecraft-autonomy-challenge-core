"""Evaluation cases, suites, and the scenario providers that turn cases into scenarios.

A case is an id plus an opaque JSON payload. Only a scenario provider, a function that maps a payload to
a `Scenario`, gives the payload its meaning; to everything else, the payload is opaque.
"""

import hashlib
import importlib
import json
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spacecraft_ops_challenge.scenario import Scenario

type ScenarioFactory = Callable[[dict[str, Any]], Scenario]


class CaseError(ValueError):
    """Raised for an invalid case, suite, or scenario provider."""


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise CaseError(f"case payloads must be finite JSON data: {error}") from error


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not finite JSON data")


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One case: a stable id and an opaque JSON payload for the scenario provider."""

    case_id: str
    payload_json: str
    """The payload as canonical JSON, which keeps the case immutable and hashable."""

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or not self.case_id:
            raise CaseError("case id must be a non-empty string")
        try:
            payload = json.loads(self.payload_json, parse_constant=_reject_constant)
        except (TypeError, ValueError) as error:
            raise CaseError(f"payload of case {self.case_id!r} must be JSON: {error}") from error
        if not isinstance(payload, dict):
            raise CaseError(f"payload of case {self.case_id!r} must be a mapping")
        object.__setattr__(self, "payload_json", _canonical_json(payload))

    @classmethod
    def of(cls, case_id: str, payload: Mapping[str, Any]) -> "EvaluationCase":
        """Build a case from a JSON-compatible mapping."""
        if not isinstance(payload, Mapping):
            raise CaseError(f"payload of case {case_id!r} must be a mapping")
        return cls(case_id, _canonical_json(dict(payload)))

    @property
    def payload(self) -> dict[str, Any]:
        """A fresh copy of the payload."""
        return json.loads(self.payload_json)

    def to_dict(self) -> dict[str, Any]:
        """JSON form of the case."""
        return {"id": self.case_id, "payload": self.payload}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationCase":
        """Inverse of `to_dict`."""
        try:
            return cls.of(data["id"], data["payload"])
        except (KeyError, TypeError) as error:
            raise CaseError(f"a case needs an 'id' and a 'payload', got {data!r}") from error


@dataclass(frozen=True, slots=True)
class Suite:
    """A named, ordered collection of cases with unique ids."""

    name: str
    cases: tuple[EvaluationCase, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        ids = [case.case_id for case in self.cases]
        duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
        if duplicates:
            raise CaseError(f"duplicate case ids: {', '.join(duplicates)}")

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the canonical cases; identifies the exact cases without revealing them."""
        canonical = _canonical_json([[case.case_id, case.payload] for case in self.cases])
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ScenarioProvider:
    """A scenario factory named as `module:function`, importable once `paths` are on the import path.

    The provider is imported by name, so it must be a module-level function.
    """

    target: str
    paths: tuple[str, ...] = ()
    """Directories added to the import path when the provider is loaded, e.g. for code that is not installed."""

    def __post_init__(self) -> None:
        module, separator, function = self.target.partition(":")
        if not separator or not module or not function:
            raise CaseError(f"a scenario provider is named as 'module:function', got {self.target!r}")
        object.__setattr__(self, "paths", tuple(str(Path(path).resolve()) for path in self.paths))

    @classmethod
    def from_callable(cls, factory: ScenarioFactory) -> "ScenarioProvider":
        """The provider of a module-level function, importable from the directory of its top-level package."""
        module = sys.modules.get(factory.__module__)
        if module is None or factory.__qualname__ != factory.__name__ or factory.__module__ == "__main__":
            raise CaseError(f"{factory!r} is not a module-level function of an importable module")
        top_level = sys.modules[factory.__module__.partition(".")[0]]
        location = getattr(top_level, "__file__", None)
        if location is None:
            raise CaseError(f"cannot locate the module of {factory!r}")
        root = Path(location).resolve().parent
        if Path(location).name == "__init__.py":
            root = root.parent
        return cls(f"{factory.__module__}:{factory.__name__}", (str(root),))

    def load(self) -> ScenarioFactory:
        """Import the factory, with `paths` added to the end of the import path of this process."""
        for path in self.paths:
            if path not in sys.path:
                sys.path.append(path)
        module_name, _, function_name = self.target.partition(":")
        try:
            factory = getattr(importlib.import_module(module_name), function_name)
        except (ImportError, AttributeError) as error:
            raise CaseError(f"cannot import the scenario provider {self.target!r}: {error}") from error
        if not callable(factory):
            raise CaseError(f"the scenario provider {self.target!r} is not callable")
        return factory

    def build(self, case: EvaluationCase) -> Scenario:
        """The scenario of `case`. Raises `CaseError` if the provider does not return a `Scenario`."""
        scenario = self.load()(case.payload)
        if not isinstance(scenario, Scenario):
            raise CaseError(f"the scenario provider returned {type(scenario).__name__} for case {case.case_id!r}")
        return scenario

    def check(self, cases: Iterable[EvaluationCase]) -> None:
        """Build the scenario of every case once, so that a broken provider fails before any submission runs."""
        for case in cases:
            try:
                self.build(case)
            except CaseError:
                raise
            except Exception as error:
                raise CaseError(f"the scenario provider failed for case {case.case_id!r}: {error!r}") from error

    def to_dict(self) -> dict[str, Any]:
        """JSON form of the provider."""
        return {"target": self.target, "paths": list(self.paths)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScenarioProvider":
        """Inverse of `to_dict`."""
        return cls(data["target"], tuple(data.get("paths", ())))
