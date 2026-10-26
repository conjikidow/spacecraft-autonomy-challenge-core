"""Reproduction of the packages that a participant's project needs, on top of the evaluating environment.

The participant's `pyproject.toml` lists the packages of their project in `[project] dependencies`, with any
sources that uv records for them in `[tool.uv.sources]`. The evaluating environment is never replaced by it.
Each requirement is checked against the running environment instead, and only requirements that it does not
satisfy are installed with uv, into a temporary per-submission overlay directory. The overlay is meant to be put
first on the import path of the processes that run the participant's code, ahead of the environment's own
packages. The core package is always the evaluating environment's own.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from importlib import metadata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit
from urllib.request import url2pathname

from packaging.markers import Marker
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

CORE_DISTRIBUTION = "spacecraft-operations-challenge-core"
PROTECTED_MODULES = frozenset({"spacecraft_ops_challenge"})
"""Top-level modules of the core package, which the overlay must never provide."""
DEFAULT_INSTALL_TIMEOUT_S = 900.0


class DependencyError(ValueError):
    """Raised for a `pyproject.toml` that cannot be read or dependencies that cannot be reproduced."""


class Decision(StrEnum):
    """What happens to one participant requirement in the evaluating environment."""

    SATISFIED = "SATISFIED"
    """The evaluating environment already satisfies it."""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    """Its environment marker is false for the evaluating interpreter."""
    JUDGE_CONTROLLED = "JUDGE_CONTROLLED"
    """The core package: the evaluating environment's own version is used."""
    INSTALL = "INSTALL"
    """Missing or incompatible; installed into the overlay."""
    UNSUPPORTED = "UNSUPPORTED"
    """Cannot be reproduced, such as a local file that the evaluating machine does not have."""


@dataclass(frozen=True, slots=True)
class InstalledDistribution:
    """What the planner needs to know about one installed distribution."""

    name: str
    version: str
    requires: tuple[str, ...] = ()
    """`Requires-Dist` entries of its metadata."""
    direct_url: Mapping[str, Any] | None = None
    """Contents of its `direct_url.json` (PEP 610), if it was installed from a URL."""


type Environment = Callable[[str], InstalledDistribution | None]
"""Looks up an installed distribution by its canonical name."""


def installed_distribution(name: str) -> InstalledDistribution | None:
    """The distribution `name` of the running interpreter, or `None` if it is not installed."""
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    direct_url = distribution.read_text("direct_url.json")
    return InstalledDistribution(
        name=canonicalize_name(distribution.metadata["Name"] or name),
        version=distribution.version,
        requires=tuple(distribution.requires or ()),
        direct_url=json.loads(direct_url) if direct_url else None,
    )


@dataclass(frozen=True, slots=True)
class RequirementDecision:
    """The decision for one participant requirement and why it was made."""

    requirement: str
    name: str
    decision: Decision
    reason: str
    install: tuple[str, ...] = ()
    """What to install for an `INSTALL` decision, if not the requirement itself, e.g. only missing extras."""
    constraints: tuple[str, ...] = ()
    """Constraints of what is already satisfied, including dependencies of extras, that the overlay must keep."""
    preserved: tuple[str, ...] = ()
    """Satisfied packages installed from a URL: no constraint pins them, so the overlay must not provide them."""

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the decision."""
        return {
            "requirement": self.requirement,
            "name": self.name,
            "decision": self.decision.value,
            "reason": self.reason,
            "install": list(self.install),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequirementDecision":
        """Inverse of `to_dict`; `constraints` and `preserved` are not part of it and come back empty."""
        return cls(
            requirement=data["requirement"],
            name=data["name"],
            decision=Decision(data["decision"]),
            reason=data["reason"],
            install=tuple(data.get("install", ())),
        )


@dataclass(frozen=True, slots=True)
class DependencyPlan:
    """Decisions for every requirement of a participant's `pyproject.toml`."""

    decisions: tuple[RequirementDecision, ...]

    @property
    def to_install(self) -> tuple[str, ...]:
        """Requirements to install into the overlay."""
        return tuple(
            requirement
            for d in self.decisions
            if d.decision is Decision.INSTALL
            for requirement in (d.install or (d.requirement,))
        )

    @property
    def to_keep(self) -> tuple[str, ...]:
        """Constraints that installing the overlay must keep satisfied: what the environment already satisfies.

        Constraints carry the name, versions, and marker of a requirement only, without extras.
        """
        return tuple(dict.fromkeys(constraint for d in self.decisions for constraint in d.constraints))

    @property
    def to_preserve(self) -> tuple[str, ...]:
        """Names of satisfied packages installed from a URL, which the overlay must not replace."""
        return tuple(dict.fromkeys(name for d in self.decisions for name in d.preserved))

    @property
    def unsupported(self) -> tuple[RequirementDecision, ...]:
        """Requirements that cannot be reproduced."""
        return tuple(d for d in self.decisions if d.decision is Decision.UNSUPPORTED)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the plan."""
        return {"decisions": [d.to_dict() for d in self.decisions]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyPlan":
        """Inverse of `to_dict`."""
        return cls(tuple(RequirementDecision.from_dict(d) for d in data["decisions"]))


def _load_pyproject(data: bytes) -> dict[str, Any]:
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError) as error:
        raise DependencyError(f"the participant pyproject.toml cannot be read: {error!r}") from error


def parse_requirements(data: bytes) -> tuple[Requirement, ...]:
    """Requirements in `[project] dependencies` of a `pyproject.toml`."""
    project = _load_pyproject(data).get("project", {})
    if not isinstance(project, dict):
        raise DependencyError("[project] of the participant pyproject.toml must be a table")
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(isinstance(entry, str) for entry in dependencies):
        raise DependencyError("[project] dependencies of the participant pyproject.toml must be a list of strings")
    requirements = []
    for entry in dependencies:
        try:
            requirements.append(Requirement(entry))
        except (InvalidRequirement, RecursionError) as error:
            raise DependencyError(
                f"invalid requirement {entry!r} in the participant pyproject.toml: {error}"
            ) from error
    return tuple(requirements)


def parse_sources(data: bytes) -> dict[str, object]:
    """Entries of `[tool.uv.sources]` of a `pyproject.toml`, by canonical package name."""
    sources: Any = _load_pyproject(data)
    for key in ("tool", "uv", "sources"):
        sources = sources.get(key, {})
        if not isinstance(sources, dict):
            raise DependencyError("[tool.uv.sources] of the participant pyproject.toml must be a table")
    by_name: dict[str, object] = {}
    for name, source in sources.items():
        canonical = canonicalize_name(name)
        if canonical in by_name:
            raise DependencyError(f"[tool.uv.sources] of the participant pyproject.toml names {canonical!r} twice")
        by_name[canonical] = source
    return by_name


class _UnsupportedSourceError(Exception):
    """A `[tool.uv.sources]` entry that cannot be reproduced; the message is the reason."""


_GIT_KEYS = frozenset({"git", "rev", "tag", "branch", "subdirectory", "marker"})
_URL_KEYS = frozenset({"url", "subdirectory", "marker"})
_LOCAL_ADVICE = "put that code under submission/ or publish the package"


def _describe(source: Mapping[str, Any]) -> str:
    """`source` written as a TOML inline table."""
    return "{ " + ", ".join(f"{key} = {json.dumps(value, default=str)}" for key, value in source.items()) + " }"


_URL_UNSAFE = frozenset(" \t\n;#")
_PART_UNSAFE = _URL_UNSAFE | frozenset("@&?")


def _string(source: Mapping[str, Any], key: str, unsafe: frozenset[str] = frozenset()) -> str | None:
    """The string value of `key`, which must not contain the characters `unsafe`, or `None` if it is absent.

    The values become part of a requirement string, where characters such as `;` and `#` would start an
    environment marker or a URL fragment.
    """
    value = source.get(key)
    if value is not None and (not isinstance(value, str) or not value or unsafe.intersection(value)):
        raise _UnsupportedSourceError(f"has an invalid {key!r}")
    return value


def _source_url(source: Mapping[str, Any]) -> str:
    """The PEP 508 URL of a git or URL source."""
    if "git" in source:
        unknown = sorted(source.keys() - _GIT_KEYS)
        url = f"git+{(_string(source, 'git', _URL_UNSAFE) or '').removeprefix('git+')}"
        revisions = [revision for key in ("tag", "branch", "rev") if (revision := _string(source, key, _PART_UNSAFE))]
        if len(revisions) > 1:
            raise _UnsupportedSourceError("sets more than one of 'rev', 'tag', and 'branch'")
        url += "".join(f"@{revision}" for revision in revisions)
    else:
        unknown = sorted(source.keys() - _URL_KEYS)
        url = _string(source, "url", _URL_UNSAFE) or ""
    if unknown:
        raise _UnsupportedSourceError(f"has keys that are not supported: {', '.join(unknown)}")
    subdirectory = _string(source, "subdirectory", _PART_UNSAFE)
    return f"{url}#subdirectory={subdirectory}" if subdirectory else url


def _apply_source(requirement: Requirement, source: object) -> Requirement:
    """`requirement` installed from its `[tool.uv.sources]` entry, as a PEP 508 URL requirement.

    Returns `requirement` itself if the marker of the entry is false for the evaluating interpreter. Raises
    `_UnsupportedSourceError` for an entry that cannot be reproduced. The URL requirement drops any version
    specifier, which a URL requirement cannot carry.
    """
    if isinstance(source, list):
        raise _UnsupportedSourceError("lists several sources, which are not supported")
    if not isinstance(source, dict):
        raise _UnsupportedSourceError("is not a table")
    try:
        return _apply_source_table(requirement, source)
    except (ValueError, KeyError, RecursionError) as error:  # invalid or unevaluable markers or requirements
        raise _UnsupportedSourceError(f"{_describe(source)} is invalid: {error}") from None
    except _UnsupportedSourceError as error:
        raise _UnsupportedSourceError(f"{_describe(source)} {error}") from None


def _apply_source_table(requirement: Requirement, source: Mapping[str, Any]) -> Requirement:
    if "marker" in source and not Marker(_string(source, "marker") or "").evaluate({"extra": ""}):
        return requirement
    if "path" in source or "workspace" in source:
        kind = "a local path" if "path" in source else "a workspace member"
        raise _UnsupportedSourceError(f"is {kind}, which cannot be reproduced; {_LOCAL_ADVICE}")
    if "index" in source:
        raise _UnsupportedSourceError(
            "names a package index that is not used here, and the default index may provide a different package "
            "of the same name; remove the entry if the default index provides the package"
        )
    if "git" not in source and "url" not in source:
        raise _UnsupportedSourceError("is not a git or URL source")
    if requirement.url:
        raise _UnsupportedSourceError("is given for a requirement that already names a URL")
    url = _source_url(source)
    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    marker = f" ; {requirement.marker}" if requirement.marker is not None else ""
    rewritten = Requirement(f"{requirement.name}{extras} @ {url}{marker}")
    if rewritten.url != url or str(rewritten.marker) != str(requirement.marker):
        raise _UnsupportedSourceError("cannot be written as a requirement URL")
    return rewritten


def _without_fragment(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(fragment=""))


def _installed_urls(direct_url: Mapping[str, Any]) -> set[str]:
    """Requirement URLs that describe how a distribution was installed."""
    url = direct_url.get("url", "")
    vcs_info = direct_url.get("vcs_info")
    if not vcs_info:
        return {_without_fragment(url)}
    base = f"{vcs_info.get('vcs', 'git')}+{url}"
    revisions = {vcs_info.get("requested_revision"), vcs_info.get("commit_id")}
    return {base} | {f"{base}@{revision}" for revision in revisions if revision}


def _installed_from(url: str, direct_url: Mapping[str, Any]) -> bool:
    """Whether the requirement URL `url` names the source recorded in `direct_url`, including its subdirectory."""
    subdirectories = parse_qs(urlsplit(url).fragment).get("subdirectory", [None])
    return _without_fragment(url) in _installed_urls(direct_url) and subdirectories[0] == direct_url.get("subdirectory")


def _installed_from_local_file(distribution: InstalledDistribution) -> bool:
    direct_url = distribution.direct_url or {}
    return urlsplit(str(direct_url.get("url", ""))).scheme == "file" and "vcs_info" not in direct_url


def _local_path(url: str) -> Path:
    return Path(url2pathname(urlsplit(url).path))


def _satisfies(requirement: Requirement, distribution: InstalledDistribution) -> bool:
    try:
        return requirement.specifier.contains(Version(distribution.version), prereleases=True)
    except (InvalidVersion, InvalidSpecifier):
        return False


type _Visited = frozenset[tuple[str, frozenset[str]]]


def _key(requirement: Requirement) -> tuple[str, frozenset[str]]:
    return canonicalize_name(requirement.name), frozenset(requirement.extras)


@dataclass(slots=True)
class _Extras:
    """What the requested extras of an installed package need."""

    missing: list[str] = field(default_factory=list)
    """What to install."""
    unsupported: list[str] = field(default_factory=list)
    """Dependencies that cannot be reproduced, with the reason."""
    constraints: list[str] = field(default_factory=list)
    """Constraints of the satisfied dependencies, which installing the overlay must keep satisfied."""
    preserved: list[str] = field(default_factory=list)
    """Satisfied dependencies installed from a URL, which the overlay must not provide."""


def _version_constraint(requirement: Requirement) -> tuple[str, ...]:
    """The constraint form of a version requirement: name, versions, and marker, without extras."""
    if requirement.url is not None or not requirement.specifier:
        return ()
    marker = f"; {requirement.marker}" if requirement.marker is not None else ""
    return (f"{requirement.name}{requirement.specifier}{marker}",)


def _extras(
    requirement: Requirement, distribution: InstalledDistribution, environment: Environment, visited: _Visited
) -> _Extras:
    """The dependencies of the requested extras, each decided like any other requirement.

    Dependencies of an extra keep their own extras and URLs. `visited` stops extras that refer to each other.
    """
    visited |= {_key(requirement)}
    result = _Extras()
    for extra in sorted(requirement.extras):
        for entry in distribution.requires:
            try:
                dependency = Requirement(entry)
            except InvalidRequirement:
                continue
            marker = dependency.marker
            try:
                if marker is None or not marker.evaluate({"extra": extra}) or marker.evaluate({"extra": ""}):
                    continue
            except (ValueError, KeyError) as error:  # a comparison or a variable that cannot be evaluated here
                result.unsupported.append(f"{entry} (its environment marker cannot be evaluated: {error})")
                continue
            dependency.marker = None
            if _key(dependency) in visited:
                continue
            decision = _decide(dependency, environment, visited)
            if decision.decision is Decision.UNSUPPORTED:
                result.unsupported.append(f"{decision.requirement} ({decision.reason})")
            elif decision.decision is Decision.INSTALL:
                result.missing += [
                    item for item in decision.install or (decision.requirement,) if item not in result.missing
                ]
            result.constraints += [c for c in decision.constraints if c not in result.constraints]
            result.preserved += [name for name in decision.preserved if name not in result.preserved]
    return result


def _core_reason(requirement: Requirement, core: InstalledDistribution | None) -> str:
    if core is None:
        return "the evaluating environment supplies its own core package"
    if requirement.url:
        matches = core.direct_url is not None and _installed_from(requirement.url, core.direct_url)
    else:
        matches = _satisfies(requirement, core)
    verdict = "matches" if matches else "differs from"
    return f"the evaluating environment uses its own core {core.version}; the participant's reference {verdict} it"


def decide(
    requirement: Requirement, environment: Environment = installed_distribution, *, source: object = None
) -> RequirementDecision:
    """Decide what to do with one participant requirement in the evaluating environment.

    `source` is the requirement's `[tool.uv.sources]` entry, if any. A git or URL source turns the requirement
    into a URL requirement; any other source makes it `UNSUPPORTED`, unless the requirement is not applicable or
    is the core package.
    """
    if source is None:
        return _decide(requirement, environment, frozenset())
    try:
        sourced = _apply_source(requirement, source)
    except _UnsupportedSourceError as error:
        decision = _decide(requirement, environment, frozenset())
        if decision.decision in {Decision.NOT_APPLICABLE, Decision.JUDGE_CONTROLLED}:
            return decision
        return RequirementDecision(
            str(requirement), decision.name, Decision.UNSUPPORTED, f"its [tool.uv.sources] entry {error}"
        )
    decision = _decide(sourced, environment, frozenset())
    if sourced is requirement:
        return decision
    return replace(decision, reason=f"{decision.reason} (rewritten from {requirement} by [tool.uv.sources])")


def _decide(requirement: Requirement, environment: Environment, visited: _Visited) -> RequirementDecision:
    name = canonicalize_name(requirement.name)

    def _decision(
        decision: Decision,
        reason: str,
        install: tuple[str, ...] = (),
        constraints: tuple[str, ...] = (),
        preserved: tuple[str, ...] = (),
    ) -> RequirementDecision:
        return RequirementDecision(str(requirement), name, decision, reason, install, constraints, preserved)

    def _installed(installed: InstalledDistribution, reason: str) -> RequirementDecision:
        """The decision for an installed package, which may still lack dependencies of requested extras."""
        extras = _extras(requirement, installed, environment, visited)
        constraints = (*_version_constraint(requirement), *extras.constraints)
        preserved = (*((name,) if requirement.url else ()), *extras.preserved)
        if extras.unsupported:
            return _decision(Decision.UNSUPPORTED, f"its extras need {', '.join(extras.unsupported)}")
        if extras.missing:
            missing = tuple(extras.missing)
            reason = f"its extras need {', '.join(missing)}"
            return _decision(Decision.INSTALL, reason, missing, constraints, preserved)
        return _decision(Decision.SATISFIED, reason, (), constraints, preserved)

    try:
        applicable = requirement.marker is None or requirement.marker.evaluate({"extra": ""})
    except (ValueError, KeyError) as error:  # a comparison or a variable that cannot be evaluated here
        return _decision(Decision.UNSUPPORTED, f"its environment marker cannot be evaluated: {error}")
    if not applicable:
        return _decision(Decision.NOT_APPLICABLE, "its environment marker is false for the evaluating Python")
    installed = environment(name)
    if name == CORE_DISTRIBUTION:
        return _decision(Decision.JUDGE_CONTROLLED, _core_reason(requirement, installed))

    if requirement.url:
        url = urlsplit(requirement.url)
        if not url.scheme or (url.scheme == "file" and not _local_path(requirement.url).is_absolute()):
            return _decision(
                Decision.UNSUPPORTED,
                "a relative path of the participant's project, which cannot be reproduced; "
                "put that code under submission/ or publish the package",
            )
        if url.scheme == "file":
            # Only a package that was itself installed from a local file can stand in for another local build.
            if installed is not None and _installed_from_local_file(installed):
                return _installed(
                    installed, f"a local package already installed in the evaluating environment ({installed.version})"
                )
            try:
                present = _local_path(requirement.url).exists()
            except OSError as error:  # e.g. a directory that the evaluating user cannot read
                return _decision(Decision.UNSUPPORTED, f"a local file that cannot be read here: {error}")
            if not present:
                return _decision(
                    Decision.UNSUPPORTED,
                    "a local file of the participant's machine that the evaluating machine does not have; "
                    "publish the package or put its code under submission/",
                )
            return _decision(Decision.INSTALL, "a local file that is not installed in the evaluating environment")
        if (
            installed is not None
            and installed.direct_url is not None
            and _installed_from(requirement.url, installed.direct_url)
        ):
            return _installed(installed, f"installed from the same URL ({installed.version})")
        return _decision(
            Decision.INSTALL, "a URL requirement that the evaluating environment has not installed from that URL"
        )

    if installed is None:
        return _decision(Decision.INSTALL, "not installed in the evaluating environment")
    if not _satisfies(requirement, installed):
        return _decision(
            Decision.INSTALL, f"the evaluating environment has {installed.version}, which does not satisfy it"
        )
    return _installed(installed, f"the evaluating environment has {installed.version}")


def plan_dependencies(
    requirements: Iterable[Requirement],
    environment: Environment = installed_distribution,
    *,
    sources: Mapping[str, object] | None = None,
) -> DependencyPlan:
    """Decisions for every requirement, in order; `sources` maps canonical names to `[tool.uv.sources]` entries."""
    sources = {} if sources is None else sources
    return DependencyPlan(
        tuple(
            decide(requirement, environment, source=sources.get(canonicalize_name(requirement.name)))
            for requirement in requirements
        )
    )


def base_constraints(
    exclude: Iterable[str], distributions: Iterable[metadata.Distribution] | None = None
) -> tuple[str, ...]:
    """`name==version` pins of the environment's index-installed distributions, except the names in `exclude`.

    Installing with these constraints keeps the overlay from shadowing the environment's packages with other
    versions. Distributions installed from a URL are left out because an index cannot provide them.
    """
    excluded = {canonicalize_name(name) for name in exclude}
    pins = {}
    for distribution in metadata.distributions() if distributions is None else distributions:
        name = distribution.metadata["Name"]
        if not name or canonicalize_name(name) in excluded or distribution.read_text("direct_url.json"):
            continue
        pins.setdefault(canonicalize_name(name), f"{canonicalize_name(name)}=={distribution.version}")
    return tuple(pins[name] for name in sorted(pins))


def find_uv() -> str:
    """Path of the `uv` executable used to install the overlay."""
    uv = shutil.which("uv")
    if uv is None:
        raise DependencyError("installing participant packages requires uv, which is not on PATH")
    return uv


def install_command(
    uv: str, target: Path, requirements_file: Path, *, python: str, constraints_file: Path | None = None
) -> list[str]:
    """Command that installs the requirements of `requirements_file` into the directory `target`."""
    command = [
        uv,
        "pip",
        "install",
        "--target",
        str(target),
        "--python",
        python,
        "--no-progress",
        # Configuration files around the working directory must not change what the plan decided.
        "--no-config",
        "--requirements",
        str(requirements_file),
    ]
    if constraints_file is not None:
        command += ["--constraints", str(constraints_file)]
    return command


@dataclass(frozen=True, slots=True)
class InstallAttempt:
    """One run of the installer."""

    command: tuple[str, ...]
    returncode: int
    output: str

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the attempt."""
        return {"command": list(self.command), "returncode": self.returncode, "output": self.output}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InstallAttempt":
        """Inverse of `to_dict`."""
        return cls(tuple(data["command"]), data["returncode"], data["output"])


@dataclass(frozen=True, slots=True)
class Overlay:
    """A directory of participant packages, meant to come first on the import path of the participant's code."""

    path: Path
    attempts: tuple[InstallAttempt, ...] = ()

    def environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """`base` (default: the current process environment) with the overlay first on `PYTHONPATH`."""
        env = dict(os.environ if base is None else base)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (str(self.path), env.get("PYTHONPATH"))))
        return env


type Runner = Callable[..., subprocess.CompletedProcess[str]]


def install_overlay(
    requirements: Sequence[str],
    target: Path,
    *,
    uv: str | None = None,
    python: str = sys.executable,
    constraints: Sequence[str] | None = None,
    keep: Sequence[str] = (),
    preserve: Sequence[str] = (),
    timeout_s: float = DEFAULT_INSTALL_TIMEOUT_S,
    env: Mapping[str, str] | None = None,
    run: Runner = subprocess.run,
) -> Overlay:
    """Install `requirements` into the new directory `target` without touching the evaluating environment.

    The installation is first constrained to the versions of the environment's packages (default:
    `base_constraints`), and retried without them if that fails. The requirements in `keep`, which
    the participant's `pyproject.toml` also states, constrain both attempts, so the overlay never violates them.
    The overlay must not provide the distributions named in `preserve`, which are installed from a URL. Raises
    `DependencyError` if the installation fails or would replace the core package.
    """
    if not requirements:
        raise ValueError("nothing to install")
    # Absolute, because the installer runs in `workdir` and would resolve relative paths against it again.
    target = Path(target).resolve()
    target.mkdir(parents=True)
    # The installer's files and working directory are private to this call, so that calls for targets in the same
    # directory never read each other's files.
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-install-", dir=target.parent) as private:
        workdir = Path(private)
        uv = find_uv() if uv is None else uv
        requirements_file = workdir / "overlay-requirements.txt"
        requirements_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")
        if constraints is None:
            constraints = base_constraints(Requirement(entry).name for entry in requirements)
        constraints_file = workdir / "overlay-constraints.txt"
        constraints_file.write_text("".join(f"{pin}\n" for pin in (*keep, *constraints)), encoding="utf-8")
        kept_file = workdir / "overlay-kept.txt"
        if keep:
            kept_file.write_text("".join(f"{requirement}\n" for requirement in keep), encoding="utf-8")

        attempts = []
        for constrained in (True, False):
            command = install_command(
                uv,
                target,
                requirements_file,
                python=python,
                constraints_file=constraints_file if constrained else (kept_file if keep else None),
            )
            try:
                completed = run(
                    command,
                    cwd=workdir,
                    env=None if env is None else dict(env),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise DependencyError(f"installing participant packages took longer than {timeout_s:g} s") from error
            attempts.append(InstallAttempt(tuple(command), completed.returncode, completed.stdout or ""))
            if completed.returncode == 0:
                break
            shutil.rmtree(target)
            target.mkdir()
        else:
            raise DependencyError(f"installing participant packages failed:\n{attempts[-1].output}")
        shadowed = sorted({entry.name.split(".")[0] for entry in target.iterdir()} & PROTECTED_MODULES)
        if shadowed:
            raise DependencyError(
                f"the participant packages would replace modules of the core package: {', '.join(shadowed)}"
            )
        installed = {
            canonicalize_name(entry.name.removesuffix(".dist-info").rpartition("-")[0])
            for entry in target.glob("*.dist-info")
        }
        replaced = sorted(installed & {canonicalize_name(name) for name in preserve})
        if replaced:
            raise DependencyError(
                "the participant packages would replace packages that the participant's pyproject.toml names by URL "
                f"and the evaluating environment already has from it: {', '.join(replaced)}"
            )
        return Overlay(target, tuple(attempts))


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """How the participant's packages were reproduced for one submission."""

    plan: DependencyPlan | None
    """`None` without a `pyproject.toml`: the submission runs in the evaluating environment as it is."""
    attempts: tuple[InstallAttempt, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dictionary of the report."""
        return {
            "plan": None if self.plan is None else self.plan.to_dict(),
            "installed": [] if self.plan is None else list(self.plan.to_install),
            "attempts": [attempt.to_dict() for attempt in self.attempts],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DependencyReport":
        """Inverse of `to_dict`; `installed` follows from the plan and is not read."""
        plan = data["plan"]
        return cls(
            plan=None if plan is None else DependencyPlan.from_dict(plan),
            attempts=tuple(InstallAttempt.from_dict(attempt) for attempt in data.get("attempts", ())),
        )


def resolve_dependencies(
    pyproject: bytes | None,
    target: Path,
    *,
    environment: Environment = installed_distribution,
    install: Callable[..., Overlay] = install_overlay,
    env: Mapping[str, str] | None = None,
) -> tuple[DependencyReport, Overlay | None]:
    """Plan the participant's `pyproject.toml` and install what the environment lacks into an overlay at `target`.

    Raises `DependencyError` for an unreadable `pyproject.toml`, requirements that cannot be reproduced, or a
    failed installation.
    """
    if pyproject is None:
        return DependencyReport(plan=None), None
    plan = plan_dependencies(parse_requirements(pyproject), environment, sources=parse_sources(pyproject))
    if plan.unsupported:
        details = "\n".join(f"- {d.requirement}: {d.reason}" for d in plan.unsupported)
        raise DependencyError(f"some participant requirements cannot be reproduced:\n{details}")
    if not plan.to_install:
        return DependencyReport(plan), None
    overlay = install(plan.to_install, target, keep=plan.to_keep, preserve=plan.to_preserve, env=env)
    return DependencyReport(plan, overlay.attempts), overlay
