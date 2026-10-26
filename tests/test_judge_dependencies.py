import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from spacecraft_ops_challenge.judge import dependencies
from spacecraft_ops_challenge.judge.dependencies import (
    CORE_DISTRIBUTION,
    Decision,
    DependencyError,
    DependencyPlan,
    DependencyReport,
    InstallAttempt,
    InstalledDistribution,
    Overlay,
    RequirementDecision,
    base_constraints,
    decide,
    install_command,
    install_overlay,
    installed_distribution,
    parse_requirements,
    parse_sources,
    plan_dependencies,
    resolve_dependencies,
)

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
CORE_URL = "https://github.com/conjikidow/spacecraft-operations-challenge-core"
TOOLKIT_WHEEL = "file:///opt/wheels/toolkit-1.2.0-py3-none-any.whl"

PARTICIPANT_PYPROJECT = f"""
[project]
name = "participant"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "toolkit @ {TOOLKIT_WHEEL}",
    "numpy>=2.0",
    "pandas[excel]>=2.2",
    "polars>=1.20",
    "scikit-learn>=1.5",
    "pywin32>=306; sys_platform == 'win32'",
    "spacecraft-operations-challenge-core @ git+{CORE_URL}@v0.1.2",
    "private-helper @ file:///home/participant/wheels/private_helper-0.1-py3-none-any.whl",
]
""".encode()

INSTALLED = {
    "toolkit": InstalledDistribution("toolkit", "1.2.0", direct_url={"url": TOOLKIT_WHEEL, "archive_info": {}}),
    "numpy": InstalledDistribution("numpy", "2.2.6"),
    "pandas": InstalledDistribution("pandas", "2.3.0", requires=("numpy>=1.26", 'openpyxl>=3.1; extra == "excel"')),
    "polars": InstalledDistribution("polars", "1.0.0"),
    "spacecraft-operations-challenge-core": InstalledDistribution(
        "spacecraft-operations-challenge-core",
        "0.1.2",
        direct_url={
            "url": CORE_URL,
            "vcs_info": {
                "vcs": "git",
                "commit_id": "afbd421ce1e086eaf89539841c623f4ca9711e2a",
                "requested_revision": "v0.1.2",
            },
        },
    ),
}


def environment(name):
    return INSTALLED.get(name)


def decisions(plan):
    return {d.name: d.decision for d in plan.decisions}


def plan_of(data, env=environment):
    return plan_dependencies(parse_requirements(data), env, sources=parse_sources(data))


def test_representative_participant_pyproject():
    plan = plan_of(PARTICIPANT_PYPROJECT)
    assert decisions(plan) == {
        "toolkit": Decision.SATISFIED,
        "numpy": Decision.SATISFIED,
        "pandas": Decision.INSTALL,
        "polars": Decision.INSTALL,
        "scikit-learn": Decision.INSTALL,
        "pywin32": Decision.NOT_APPLICABLE,
        "spacecraft-operations-challenge-core": Decision.JUDGE_CONTROLLED,
        "private-helper": Decision.UNSUPPORTED,
    }
    assert plan.to_install == ("openpyxl>=3.1", "polars>=1.20", "scikit-learn>=1.5")
    # The installed pandas satisfies its own version requirement, so only its extra's dependency is installed.
    assert plan.to_keep == ("numpy>=2.0", "pandas>=2.2")
    reasons = {d.name: d.reason for d in plan.decisions}
    assert reasons["pandas"] == "its extras need openpyxl>=3.1"
    assert reasons["polars"] == "the evaluating environment has 1.0.0, which does not satisfy it"
    assert reasons["scikit-learn"] == "not installed in the evaluating environment"
    assert "local file" in reasons["private-helper"]
    assert reasons["spacecraft-operations-challenge-core"] == (
        "the evaluating environment uses its own core 0.1.2; the participant's reference matches it"
    )


@pytest.mark.parametrize(
    "requirement",
    [f"toolkit[recommended] @ {TOOLKIT_WHEEL}", "lib[extra] @ git+https://example.com/lib.git@v1"],
)
def test_extras_of_installed_url_requirements_are_checked(requirement):
    installed = {
        "toolkit": InstalledDistribution(
            "toolkit", "1.2.0", requires=('ruff; extra == "recommended"',), direct_url={"url": TOOLKIT_WHEEL}
        ),
        "lib": InstalledDistribution(
            "lib",
            "1.0",
            requires=('extra-dependency; extra == "extra"',),
            direct_url={"url": "https://example.com/lib.git", "vcs_info": {"vcs": "git", "requested_revision": "v1"}},
        ),
    }
    decision = decide(Requirement(requirement), installed.get)
    assert decision.decision is Decision.INSTALL
    assert decision.reason.startswith("its extras need")
    # Only the missing dependencies are installed, not the package again from a URL that may not be reachable.
    assert decision.install in (("ruff",), ("extra-dependency",))
    satisfied = {**installed, "ruff": InstalledDistribution("ruff", "0.17.1")}
    satisfied["extra-dependency"] = InstalledDistribution("extra-dependency", "1.0")
    assert decide(Requirement(requirement), satisfied.get).decision is Decision.SATISFIED


def test_kept_constraints_carry_versions_and_markers_only():
    with_openpyxl = {**INSTALLED, "openpyxl": InstalledDistribution("openpyxl", "3.1.5")}
    pyproject = f"""[project]
dependencies = [
    "pandas[excel]>=2.2; python_version >= '3'",
    "numpy",
    "toolkit @ {TOOLKIT_WHEEL}",
]
""".encode()
    plan = plan_of(pyproject, with_openpyxl.get)
    assert [d.decision for d in plan.decisions] == [Decision.SATISFIED] * 3
    # The satisfied dependencies of requested extras are kept as well.
    assert plan.to_keep == ('pandas>=2.2; python_version >= "3"', "openpyxl>=3.1")


def test_extras_of_extras_keep_their_extras_and_urls():
    installed = {
        "parent": InstalledDistribution(
            "parent",
            "1.0",
            requires=(
                'child[feature]>=1; extra == "all"',
                'remote @ git+https://example.com/remote.git@v2 ; extra == "all"',
                'parent[base]; extra == "all"',
                'parent[all]; extra == "base"',
            ),
        ),
        "child": InstalledDistribution("child", "1.5", requires=('leaf>=2; extra == "feature"',)),
        "leaf": InstalledDistribution("leaf", "1.0"),
    }
    decision = decide(Requirement("parent[all]"), installed.get)
    assert decision.decision is Decision.INSTALL
    # child itself is fine; only its feature's leaf, and the remote package from its URL, are missing.
    assert decision.install == ("leaf>=2", str(Requirement("remote @ git+https://example.com/remote.git@v2")))


def test_unsupported_dependencies_of_extras_make_the_requirement_unsupported():
    installed = {
        "pkg": InstalledDistribution(
            "pkg", "1.0", requires=('helper @ file:///home/participant/helper-0.1-py3-none-any.whl ; extra == "x"',)
        )
    }
    decision = decide(Requirement("pkg[x]"), installed.get)
    assert decision.decision is Decision.UNSUPPORTED
    assert "helper@ file:///home/participant" in decision.reason.replace(" @ ", "@ ")
    assert "a local file of the participant's machine" in decision.reason


def test_dependencies_of_extras_with_markers_that_cannot_be_evaluated_are_unsupported():
    installed = {
        "pkg": InstalledDistribution("pkg", "1.0", requires=("leaf ; python_version ~= 'abc' and extra == 'x'",))
    }
    decision = decide(Requirement("pkg[x]"), installed.get)
    assert decision.decision is Decision.UNSUPPORTED
    assert "its environment marker cannot be evaluated" in decision.reason


def test_satisfied_extras_are_not_reinstalled():
    with_openpyxl = {**INSTALLED, "openpyxl": InstalledDistribution("openpyxl", "3.1.5")}
    assert decide(Requirement("pandas[excel]>=2.2"), with_openpyxl.get).decision is Decision.SATISFIED


@pytest.mark.parametrize(
    "requirement",
    [
        f"spacecraft-operations-challenge-core @ git+{CORE_URL}@v0.2.0",
        "spacecraft-operations-challenge-core>=0.2",
        "spacecraft_operations_challenge_core==0.0.1",
    ],
)
def test_core_is_judge_controlled_even_when_the_participant_asks_for_another(requirement):
    decision = decide(Requirement(requirement), environment)
    assert decision.decision is Decision.JUDGE_CONTROLLED
    assert decision.reason == (
        "the evaluating environment uses its own core 0.1.2; the participant's reference differs from it"
    )


def test_core_reference_by_commit_matches():
    requirement = Requirement(
        f"spacecraft-operations-challenge-core @ git+{CORE_URL}@afbd421ce1e086eaf89539841c623f4ca9711e2a"
    )
    assert decide(requirement, environment).reason.endswith("matches it")


def test_markers_are_evaluated_for_the_evaluating_interpreter():
    current = f"{sys.version_info.major}.{sys.version_info.minor}"
    assert decide(Requirement(f"scikit-learn; python_version == '{current}'"), environment).decision is (
        Decision.INSTALL
    )
    assert decide(Requirement(f"numpy; python_version != '{current}'"), environment).decision is (
        Decision.NOT_APPLICABLE
    )


def test_local_files_present_in_the_evaluating_environment_can_be_installed(tmp_path):
    wheel = tmp_path / "helper-0.1-py3-none-any.whl"
    wheel.write_bytes(b"")
    decision = decide(Requirement(f"helper @ {wheel.as_uri()}"), environment)
    assert decision.decision is Decision.INSTALL


@pytest.mark.parametrize("requirement", ["helper @ ../helper", "helper @ file:../helper", "helper @ ./dist/h.whl"])
def test_relative_direct_references_are_unsupported(requirement):
    decision = decide(Requirement(requirement), {}.get)
    assert decision.decision is Decision.UNSUPPORTED
    assert "a relative path of the participant's project" in decision.reason


def test_installed_local_files_are_satisfied_whatever_their_path():
    other_build = "file:///opt/other-wheels/toolkit-1.1.0-py3-none-any.whl"
    assert decide(Requirement(f"toolkit @ {other_build}"), environment).decision is Decision.SATISFIED


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git+https://example.com/lib.git@v1", Decision.SATISFIED),
        ("git+https://example.com/lib.git@abc123", Decision.SATISFIED),
        ("git+https://example.com/lib.git@v2", Decision.INSTALL),
        ("https://example.com/lib-1.0-py3-none-any.whl", Decision.INSTALL),
    ],
)
def test_url_requirements_compare_the_installed_source(url, expected):
    installed = InstalledDistribution(
        "lib",
        "1.0",
        direct_url={
            "url": "https://example.com/lib.git",
            "vcs_info": {"vcs": "git", "commit_id": "abc123", "requested_revision": "v1"},
        },
    )
    assert decide(Requirement(f"lib @ {url}"), {"lib": installed}.get).decision is expected


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("#subdirectory=packages/a", Decision.SATISFIED),
        ("#subdirectory=packages/b", Decision.INSTALL),
        ("", Decision.INSTALL),
    ],
)
def test_url_requirements_compare_the_subdirectory(fragment, expected):
    installed = InstalledDistribution(
        "a",
        "1.0",
        direct_url={
            "url": "https://example.com/mono.git",
            "subdirectory": "packages/a",
            "vcs_info": {"vcs": "git", "requested_revision": "v1"},
        },
    )
    requirement = Requirement(f"a @ git+https://example.com/mono.git@v1{fragment}")
    assert decide(requirement, {"a": installed}.get).decision is expected


def test_archive_url_requirement_matches_ignoring_the_hash_fragment():
    url = "https://example.com/lib-1.0-py3-none-any.whl"
    installed = InstalledDistribution("lib", "1.0", direct_url={"url": url, "archive_info": {}})
    requirement = Requirement(f"lib @ {url}#sha256=0123")
    assert decide(requirement, {"lib": installed}.get).decision is Decision.SATISFIED


def test_installed_distribution_reads_the_running_environment():
    core = installed_distribution(CORE_DISTRIBUTION)
    assert core is not None
    assert core.name == CORE_DISTRIBUTION
    assert core.version == tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    assert installed_distribution("surely-not-an-installed-distribution") is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"[project\n", "cannot be read"),
        (b"\xff", "cannot be read"),
        (b"[project]\ndependencies = 'numpy'\n", "must be a list of strings"),
        (b"project = 'invalid'\n", "must be a table"),
        (b"[project]\ndependencies = ['numpy >>> 1']\n", "invalid requirement"),
    ],
)
def test_invalid_pyprojects(data, message):
    with pytest.raises(DependencyError, match=message):
        parse_requirements(data)


def test_pyproject_without_dependencies():
    assert parse_requirements(b"[project]\nname = 'x'\n") == ()
    assert parse_requirements(b"") == ()


# uv source tables, see https://docs.astral.sh/uv/concepts/projects/dependencies/#dependency-sources


def test_sources_are_keyed_by_canonical_name():
    data = b"""[tool.uv.sources]
My_Lib = { git = "https://example.com/lib.git" }
"""
    assert parse_sources(data) == {"my-lib": {"git": "https://example.com/lib.git"}}
    assert parse_sources(b"[project]\n") == {}


@pytest.mark.parametrize(
    "data", [b"tool = 1\n", b"[tool]\nuv = 1\n", b"[tool.uv]\nsources = []\n", b"[tool.uv.sources\n"]
)
def test_invalid_source_tables(data):
    with pytest.raises(DependencyError):
        parse_sources(data)


def test_template_like_pyproject_uses_the_core_source():
    pyproject = f"""[project]
dependencies = ["spacecraft-operations-challenge-core", "numpy>=2"]

[tool.uv.sources]
spacecraft-operations-challenge-core = {{ git = "{CORE_URL}", tag = "v0.1.2" }}
""".encode()
    plan = plan_of(pyproject)
    core, numpy = plan.decisions
    assert core.decision is Decision.JUDGE_CONTROLLED
    assert core.requirement == str(Requirement(f"spacecraft-operations-challenge-core @ git+{CORE_URL}@v0.1.2"))
    assert core.reason == (
        "the evaluating environment uses its own core 0.1.2; the participant's reference matches it "
        "(rewritten from spacecraft-operations-challenge-core by [tool.uv.sources])"
    )
    assert numpy.decision is Decision.SATISFIED
    assert plan.to_install == ()

    other_tag = pyproject.replace(b"v0.1.2", b"v0.2.0")
    assert (
        plan_of(other_tag)
        .decisions[0]
        .reason.startswith(
            "the evaluating environment uses its own core 0.1.2; the participant's reference differs from it"
        )
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('{ git = "https://example.com/lib.git" }', "lib[cli] @ git+https://example.com/lib.git"),
        ('{ git = "https://example.com/lib.git", tag = "v1" }', "lib[cli] @ git+https://example.com/lib.git@v1"),
        ('{ git = "https://example.com/lib.git", branch = "main" }', "lib[cli] @ git+https://example.com/lib.git@main"),
        (
            '{ git = "https://example.com/lib.git", rev = "abc123" }',
            "lib[cli] @ git+https://example.com/lib.git@abc123",
        ),
        (
            '{ git = "https://example.com/mono.git", tag = "v1", subdirectory = "libs/lib" }',
            "lib[cli] @ git+https://example.com/mono.git@v1#subdirectory=libs/lib",
        ),
        (
            '{ git = "git+https://example.com/lib.git", tag = "v1" }',
            "lib[cli] @ git+https://example.com/lib.git@v1",
        ),
        (
            '{ url = "https://example.com/lib-1.0.tar.gz" }',
            "lib[cli] @ https://example.com/lib-1.0.tar.gz",
        ),
        (
            '{ url = "https://example.com/mono.tar.gz", subdirectory = "libs/lib" }',
            "lib[cli] @ https://example.com/mono.tar.gz#subdirectory=libs/lib",
        ),
        (
            '{ git = "https://example.com/lib.git", marker = "python_version >= \'3\'" }',
            "lib[cli] @ git+https://example.com/lib.git",
        ),
    ],
)
def test_git_and_url_sources_become_url_requirements(source, expected):
    pyproject = f"""[project]
dependencies = ["lib[cli]>=1; python_version >= '3'"]

[tool.uv.sources]
lib = {source}
""".encode()
    (decision,) = plan_of(pyproject, {}.get).decisions
    assert decision.decision is Decision.INSTALL
    assert decision.requirement == str(Requirement(f"{expected} ; python_version >= '3'"))
    assert decision.reason.endswith(""" (rewritten from lib[cli]>=1; python_version >= "3" by [tool.uv.sources])""")


def test_a_source_with_a_false_marker_does_not_apply():
    pyproject = b"""[project]
dependencies = ["numpy>=2"]

[tool.uv.sources]
numpy = { git = "https://example.com/numpy.git", marker = "python_version < '3'" }
"""
    (decision,) = plan_of(pyproject).decisions
    assert decision.decision is Decision.SATISFIED
    assert decision.requirement == "numpy>=2"
    assert decision.reason == "the evaluating environment has 2.2.6"
    local_elsewhere = decide(Requirement("numpy"), environment, source={"path": ".", "marker": "python_version < '3'"})
    assert local_elsewhere.decision is Decision.SATISFIED


def test_installed_git_source_is_satisfied():
    installed = InstalledDistribution(
        "lib",
        "1.0",
        direct_url={"url": "https://example.com/lib.git", "vcs_info": {"vcs": "git", "requested_revision": "v1"}},
    )
    pyproject = b"""[project]
dependencies = ["lib"]

[tool.uv.sources]
lib = { git = "https://example.com/lib.git", tag = "v1" }
"""
    plan = plan_of(pyproject, {"lib": installed}.get)
    assert decisions(plan) == {"lib": Decision.SATISFIED}
    assert plan.to_preserve == ("lib",)


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ('{ path = "../helper" }', 'its [tool.uv.sources] entry { path = "../helper" } is a local path'),
        ('{ path = "../helper", editable = true }', "is a local path, which cannot be reproduced"),
        ("{ workspace = true }", "its [tool.uv.sources] entry { workspace = true } is a workspace member"),
        ('{ index = "private" }', 'its [tool.uv.sources] entry { index = "private" } names a package index'),
        (
            '[{ git = "https://example.com/a.git", marker = "sys_platform == \'linux\'" }, '
            '{ git = "https://example.com/b.git", marker = "sys_platform != \'linux\'" }]',
            "its [tool.uv.sources] entry lists several sources",
        ),
        ('"https://example.com/lib.git"', "its [tool.uv.sources] entry is not a table"),
        ("{ editable = true }", "is not a git or URL source"),
        (
            '{ git = "https://example.com/lib.git", tag = "v1", branch = "main" }',
            "sets more than one of 'rev', 'tag', and 'branch'",
        ),
        ('{ git = "https://example.com/lib.git", lfs = true }', "has keys that are not supported: lfs"),
        ('{ url = "https://example.com/lib.tar.gz", extra = "cli" }', "has keys that are not supported: extra"),
        ('{ git = "https://example.com/lib.git", tag = 1 }', "has an invalid 'tag'"),
        ('{ git = "https://example.com/lib.git", marker = "nonsense" }', "is invalid"),
        ('{ git = "https://example.com/lib.git", marker = "python_version ~= \'abc\'" }', "is invalid"),
        ('{ git = "https://example.com/lib.git", tag = "v1 ; sys_platform == \'none\'" }', "has an invalid 'tag'"),
        ('{ git = "https://example.com/lib.git", tag = "v1#subdirectory=other" }', "has an invalid 'tag'"),
        ("{ git = \"https://example.com/lib.git ; sys_platform == 'none'\" }", "has an invalid 'git'"),
        ('{ git = "https://example.com/lib.git", subdirectory = "a&egg=b" }', "has an invalid 'subdirectory'"),
        ('{ url = "https://example.com/lib.tar.gz#egg=other" }', "has an invalid 'url'"),
    ],
)
def test_unsupported_sources(source, reason):
    pyproject = f"""[project]
dependencies = ["lib>=1"]

[tool.uv.sources]
lib = {source}
""".encode()
    (decision,) = plan_of(pyproject, {}.get).decisions
    assert decision.decision is Decision.UNSUPPORTED
    assert decision.requirement == "lib>=1"
    assert reason in decision.reason
    assert decision.reason.startswith("its [tool.uv.sources] entry ")


def test_local_sources_advise_the_participant():
    decision = decide(Requirement("helper"), {}.get, source={"path": "../helper"})
    assert decision.reason.endswith("put that code under submission/ or publish the package")


def test_a_source_for_a_url_requirement_is_unsupported():
    decision = decide(
        Requirement("lib @ https://example.com/lib.tar.gz"), {}.get, source={"git": "https://example.com/lib.git"}
    )
    assert decision.decision is Decision.UNSUPPORTED
    assert decision.reason.endswith("is given for a requirement that already names a URL")


def test_unsupported_sources_of_core_or_inapplicable_requirements_do_not_matter():
    core = decide(Requirement(CORE_DISTRIBUTION), environment, source={"path": "../core"})
    assert core.decision is Decision.JUDGE_CONTROLLED
    other_platform = decide(Requirement("pywin32; sys_platform == 'nonexistent'"), environment, source={"path": "."})
    assert other_platform.decision is Decision.NOT_APPLICABLE


def test_sources_for_other_packages_are_ignored():
    pyproject = b"""[project]
dependencies = ["numpy>=2"]

[tool.uv.sources]
helper = { path = "../helper" }
"""
    assert decisions(plan_of(pyproject)) == {"numpy": Decision.SATISFIED}


class FakeDistribution:
    def __init__(self, name, version, direct_url=None):
        self.metadata = {"Name": name}
        self.version = version
        self._direct_url = direct_url

    def read_text(self, filename):
        return self._direct_url if filename == "direct_url.json" else None


def test_base_constraints_pin_index_installed_packages():
    distributions = [
        FakeDistribution("NumPy", "2.2.6"),
        FakeDistribution("numpy", "1.0.0"),
        FakeDistribution("Pandas", "2.3.0"),
        FakeDistribution("toolkit", "1.2.0", direct_url='{"url": "file:///x.whl"}'),
        FakeDistribution("polars", "1.0.0"),
    ]
    assert base_constraints(["polars"], distributions) == ("numpy==2.2.6", "pandas==2.3.0")


def test_install_command():
    command = install_command(
        "/bin/uv", Path("/tmp/overlay"), Path("/tmp/req.txt"), python="/py", constraints_file=Path("/tmp/c.txt")
    )
    assert command == [
        "/bin/uv",
        "pip",
        "install",
        "--target",
        "/tmp/overlay",
        "--python",
        "/py",
        "--no-progress",
        "--no-config",
        "--requirements",
        "/tmp/req.txt",
        "--constraints",
        "/tmp/c.txt",
    ]
    assert "--constraints" not in install_command("/bin/uv", Path("/o"), Path("/r"), python="/py")


class FakeInstaller:
    """Records installer calls and answers with the given return codes."""

    def __init__(self, *returncodes, create=()):
        self.returncodes = list(returncodes)
        self.create = create
        self.calls = []

    def __call__(self, command, **kwargs):
        target = Path(command[command.index("--target") + 1])
        requirements = Path(command[command.index("--requirements") + 1]).read_text()
        constraints = None
        if "--constraints" in command:
            constraints = Path(command[command.index("--constraints") + 1]).read_text()
        self.calls.append({"command": command, "requirements": requirements, "constraints": constraints, **kwargs})
        returncode = self.returncodes.pop(0)
        if returncode == 0:
            for name in self.create:
                (target / name).mkdir()
        return subprocess.CompletedProcess(command, returncode, stdout=f"exit {returncode}")


def test_install_overlay_constrains_to_the_environment_packages(tmp_path):
    installer = FakeInstaller(0, create=["sklearn"])
    overlay = install_overlay(
        ["scikit-learn>=1.5", "polars>=1.20"],
        tmp_path / "overlay",
        uv="/bin/uv",
        python="/py",
        constraints=["numpy==2.2.6"],
        run=installer,
    )
    assert overlay.path == tmp_path / "overlay"
    assert (overlay.path / "sklearn").is_dir()
    (call,) = installer.calls
    assert call["command"][:4] == ["/bin/uv", "pip", "install", "--target"]
    assert call["requirements"] == "scikit-learn>=1.5\npolars>=1.20\n"
    assert call["constraints"] == "numpy==2.2.6\n"
    assert call["cwd"] == tmp_path
    assert call["check"] is False
    assert [attempt.returncode for attempt in overlay.attempts] == [0]


def test_install_overlay_resolves_a_relative_target(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    installer = FakeInstaller(0)
    overlay = install_overlay(
        ["polars"], Path("work/overlay"), uv="/bin/uv", python="/py", constraints=[], run=installer
    )
    (call,) = installer.calls
    command = call["command"]
    assert overlay.path == tmp_path / "work" / "overlay"
    assert call["cwd"] == tmp_path / "work"
    assert command[command.index("--target") + 1] == str(tmp_path / "work" / "overlay")
    assert Path(command[command.index("--requirements") + 1]).is_absolute()


def test_install_overlay_excludes_requested_packages_from_the_default_constraints(tmp_path, monkeypatch):
    seen = {}

    def fake_constraints(exclude):
        seen["exclude"] = list(exclude)
        return ("numpy==2.2.6",)

    monkeypatch.setattr(dependencies, "base_constraints", fake_constraints)
    install_overlay(["Polars>=1.20", "pandas[excel]>=2"], tmp_path / "o", uv="/bin/uv", run=FakeInstaller(0))
    assert seen["exclude"] == ["Polars", "pandas"]


def test_install_overlay_retries_without_constraints(tmp_path):
    installer = FakeInstaller(1, 0)
    overlay = install_overlay(["polars>=1.20"], tmp_path / "o", uv="/bin/uv", constraints=["numpy==1.0"], run=installer)
    assert [call["constraints"] for call in installer.calls] == ["numpy==1.0\n", None]
    assert [attempt.returncode for attempt in overlay.attempts] == [1, 0]


def test_participant_requirements_constrain_both_attempts(tmp_path):
    installer = FakeInstaller(1, 0)
    install_overlay(
        ["needs-numpy-2"], tmp_path / "o", uv="/bin/uv", constraints=["numpy==1.26.4"], keep=["numpy<2"], run=installer
    )
    assert [call["constraints"] for call in installer.calls] == ["numpy<2\nnumpy==1.26.4\n", "numpy<2\n"]


def test_install_overlay_failure_is_a_clear_error(tmp_path):
    with pytest.raises(DependencyError, match="installing participant packages failed:\nexit 2"):
        install_overlay(["polars>=1.20"], tmp_path / "o", uv="/bin/uv", constraints=[], run=FakeInstaller(1, 2))


def test_install_overlay_never_replaces_the_core(tmp_path):
    installer = FakeInstaller(0, create=["spacecraft_ops_challenge"])
    with pytest.raises(DependencyError, match=r"replace modules of the core package: spacecraft_ops_challenge$"):
        install_overlay(["helper"], tmp_path / "o", uv="/bin/uv", constraints=[], run=installer)


def test_install_overlay_never_replaces_core_modules_given_as_files(tmp_path):
    def installer(command, **kwargs):
        target = Path(command[command.index("--target") + 1])
        (target / "spacecraft_ops_challenge.py").write_text("")
        (target / "unrelated.py").write_text("")
        return subprocess.CompletedProcess(command, 0, stdout="")

    with pytest.raises(DependencyError, match=r"spacecraft_ops_challenge$"):
        install_overlay(["helper"], tmp_path / "o", uv="/bin/uv", constraints=[], run=installer)


def test_install_overlay_never_replaces_packages_kept_from_a_url(tmp_path):
    installer = FakeInstaller(0, create=["toolkit-1.2.0.dist-info", "polars-1.20.0.dist-info"])
    with pytest.raises(DependencyError, match=r"already has from it: toolkit$"):
        install_overlay(
            ["polars>=1.20"], tmp_path / "o", uv="/bin/uv", constraints=[], preserve=["Toolkit"], run=installer
        )
    installer = FakeInstaller(0, create=["polars-1.20.0.dist-info"])
    install_overlay(["polars>=1.20"], tmp_path / "p", uv="/bin/uv", constraints=[], preserve=["toolkit"], run=installer)


def test_install_overlay_timeout(tmp_path):
    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(DependencyError, match="longer than 5 s"):
        install_overlay(["helper"], tmp_path / "o", uv="/bin/uv", constraints=[], timeout_s=5, run=slow)


def test_missing_uv_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(dependencies.shutil, "which", lambda name: None)
    with pytest.raises(DependencyError, match="requires uv"):
        dependencies.find_uv()


def test_overlay_comes_first_on_the_python_path(tmp_path):
    overlay = Overlay(tmp_path)
    assert overlay.environment({"PATH": "/bin"})["PYTHONPATH"] == str(tmp_path)
    assert overlay.environment({"PYTHONPATH": "/other"})["PYTHONPATH"] == f"{tmp_path}{os.pathsep}/other"


def test_resolve_without_a_pyproject_uses_the_evaluating_environment(tmp_path):
    report, overlay = resolve_dependencies(None, tmp_path / "o", install=pytest.fail)
    assert report.plan is None
    assert overlay is None
    assert report.to_dict() == {"plan": None, "installed": [], "attempts": []}


def test_resolve_skips_installation_when_everything_is_satisfied(tmp_path):
    pyproject = f'[project]\ndependencies = ["numpy>=2", "toolkit @ {TOOLKIT_WHEEL}"]\n'.encode()
    report, overlay = resolve_dependencies(pyproject, tmp_path / "o", environment=environment, install=pytest.fail)
    assert overlay is None
    assert report.plan.to_install == ()


def test_resolve_installs_the_missing_requirements(tmp_path):
    calls = []

    def install(requirements, target, *, keep, preserve):
        calls.append((requirements, target, keep, preserve))
        return Overlay(target, (InstallAttempt(("uv",), 0, "ok"),))

    pyproject = f'[project]\ndependencies = ["numpy>=2", "scikit-learn>=1.5", "toolkit @ {TOOLKIT_WHEEL}"]\n'.encode()
    report, overlay = resolve_dependencies(pyproject, tmp_path / "o", environment=environment, install=install)
    assert calls == [(("scikit-learn>=1.5",), tmp_path / "o", ("numpy>=2",), ("toolkit",))]
    assert overlay == Overlay(tmp_path / "o", (InstallAttempt(("uv",), 0, "ok"),))
    assert report.attempts == overlay.attempts
    assert report.to_dict()["installed"] == ["scikit-learn>=1.5"]


def test_resolve_installs_git_sources_as_url_requirements(tmp_path):
    calls = []

    def install(requirements, target, *, keep, preserve):
        calls.append(requirements)
        return Overlay(target)

    pyproject = b"""[project]
dependencies = ["lib"]

[tool.uv.sources]
lib = { git = "https://example.com/lib.git", tag = "v1" }
"""
    resolve_dependencies(pyproject, tmp_path / "o", environment=environment, install=install)
    assert calls == [(str(Requirement("lib @ git+https://example.com/lib.git@v1")),)]


def test_resolve_rejects_unreproducible_requirements_before_installing(tmp_path):
    with pytest.raises(DependencyError, match=r"private-helper ?@ file:///home/participant"):
        resolve_dependencies(PARTICIPANT_PYPROJECT, tmp_path / "o", environment=environment, install=pytest.fail)


def test_reports_round_trip_through_json():
    plan = plan_of(PARTICIPANT_PYPROJECT.replace(b'    "private-helper', b'    # "private-helper'))
    report = DependencyReport(
        plan, (InstallAttempt(("uv", "pip", "install"), 1, "failed"), InstallAttempt(("uv",), 0, ""))
    )
    restored = DependencyReport.from_dict(json.loads(json.dumps(report.to_dict())))
    assert restored.to_dict() == report.to_dict()
    assert restored.attempts == report.attempts
    assert restored.plan.to_install == plan.to_install
    # Constraints and preserved packages are not part of the dictionary.
    assert restored.plan.to_keep == ()
    assert restored.plan.to_preserve == ()
    assert DependencyReport.from_dict(DependencyReport(None).to_dict()) == DependencyReport(None)


def test_decisions_without_constraints_round_trip_exactly():
    decision = RequirementDecision("pkg[x]", "pkg", Decision.INSTALL, "its extras need leaf", ("leaf",))
    assert RequirementDecision.from_dict(decision.to_dict()) == decision
    plan = DependencyPlan((decision,))
    assert DependencyPlan.from_dict(plan.to_dict()) == plan
    attempt = InstallAttempt(("uv", "pip"), 2, "error")
    assert InstallAttempt.from_dict(attempt.to_dict()) == attempt


def test_a_marker_that_cannot_be_evaluated_is_unsupported():
    decision = decide(Requirement("lib; python_version ~= 'abc'"), {}.get)
    assert decision.decision is Decision.UNSUPPORTED
    assert "its environment marker cannot be evaluated" in decision.reason


def test_sources_that_name_a_package_twice_are_rejected():
    pyproject = b"""[project]
dependencies = ["foo-bar"]

[tool.uv.sources]
foo_bar = { git = "https://example.com/a.git" }
Foo-Bar = { git = "https://example.com/b.git" }
"""
    with pytest.raises(DependencyError, match="names 'foo-bar' twice"):
        parse_sources(pyproject)


def test_sources_with_toml_dates_are_unsupported():
    pyproject = b"""[project]
dependencies = ["lib"]

[tool.uv.sources]
lib = { git = 2026-01-01 }
"""
    (decision,) = plan_of(pyproject, {}.get).decisions
    assert decision.decision is Decision.UNSUPPORTED
    assert 'git = "2026-01-01"' in decision.reason


def test_a_package_installed_from_an_index_does_not_stand_in_for_a_local_file(tmp_path):
    from_index = {"toolkit": InstalledDistribution("toolkit", "1.0")}
    missing = decide(Requirement("toolkit @ file:///nowhere/toolkit-1.0-py3-none-any.whl"), from_index.get)
    assert missing.decision is Decision.UNSUPPORTED
    wheel = tmp_path / "toolkit-1.0-py3-none-any.whl"
    wheel.write_bytes(b"")
    present = decide(Requirement(f"toolkit @ {wheel.as_uri()}"), from_index.get)
    assert present.decision is Decision.INSTALL
