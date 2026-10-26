"""Helpers shared by the tests of `spacecraft_ops_challenge.judge`."""

import atexit
import io
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path

from spacecraft_ops_challenge.judge.cases import EvaluationCase, ScenarioProvider

PROVIDER_SOURCE = """
from spacecraft_ops_challenge.challenge import problem
from spacecraft_ops_challenge.modifiers import TelemetryBias, ThrusterEfficiency
from spacecraft_ops_challenge.scenario import Scenario

TYPES = {"ThrusterEfficiency": ThrusterEfficiency, "TelemetryBias": TelemetryBias}


def build_scenario(payload):
    modifiers = tuple(
        TYPES[spec["type"]](**{name: value for name, value in spec.items() if name != "type"})
        for spec in payload.get("modifiers", ())
    )
    return Scenario(name=payload.get("name", "case"), problem=problem(), modifiers=modifiers, seed=payload["seed"])


def failing(payload):
    raise RuntimeError("the provider failed")


def exporting(payload):
    import os

    os.environ["JUDGE_TEST_HIDDEN"] = f"seed-{payload['seed']}"
    return build_scenario(payload)


def exiting(payload):
    raise SystemExit("bad configuration")


def noisy(payload):
    import os
    import subprocess
    import sys
    import warnings

    print("provider stdout: secret", payload["seed"])
    os.write(1, b"provider descriptor: secret\\n")
    os.write(2, b"provider descriptor: secret\\n")
    subprocess.run([sys.executable, "-c", "print('provider child: secret')"], check=True)
    print("provider stderr: secret", file=sys.stderr)
    warnings.warn("provider warning: secret", stacklevel=1)
    return build_scenario(payload)


def not_a_scenario(payload):
    return "not a scenario"
"""

# A provider that is not installed, as a scenario provider of an organizer typically is.
_PROVIDER_DIR = Path(tempfile.mkdtemp(prefix="judge-test-provider-"))
atexit.register(shutil.rmtree, _PROVIDER_DIR, ignore_errors=True)
(_PROVIDER_DIR / "judge_test_provider.py").write_text(PROVIDER_SOURCE)
PROVIDER = ScenarioProvider("judge_test_provider:build_scenario", (str(_PROVIDER_DIR),))


def case(case_id, seed=0, *modifiers, **payload):
    """A case for the test provider; each modifier is a dictionary with the `type` of a core modifier."""
    return EvaluationCase.of(case_id, {"seed": seed, "modifiers": list(modifiers), **payload})


DECLARE_AT_START = """
from spacecraft_ops_challenge import DeclareCompletion, Strategy


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        commander.execute(DeclareCompletion())
"""


def zip_bytes(files: Mapping[str, str | bytes], *, symlinks: Mapping[str, str] | None = None) -> bytes:
    """A ZIP archive with the given regular files and symbolic links."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            archive.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    return buffer.getvalue()
