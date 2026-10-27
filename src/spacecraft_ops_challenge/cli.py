"""Command-line runner: `spacecraft-ops-challenge run`, `scenarios`, `pack`, and `check`.

Exit status of `run`: 0 when the run finished, 1 when the strategy raised an exception or made an invalid
timeline request, and 2 for usage errors such as a strategy that cannot be loaded. `check` exits with 1 when a
case did not complete or ended with a strategy failure.

The participant process imports `load_strategy` from this module, so the evaluation modules are imported
only inside the handlers of `pack` and `check`.
"""

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import io
import json
import re
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from spacecraft_ops_challenge.challenge import scenario as challenge_scenario
from spacecraft_ops_challenge.challenge import scenario_names
from spacecraft_ops_challenge.evaluation import RunMetrics, evaluate
from spacecraft_ops_challenge.results import RunResult, TerminationReason
from spacecraft_ops_challenge.simulation import run
from spacecraft_ops_challenge.strategy import Strategy

if TYPE_CHECKING:
    from spacecraft_ops_challenge.judge.reporting import EvaluationResult
    from spacecraft_ops_challenge.judge.runner import CaseOutcome

EXIT_OK = 0
EXIT_STRATEGY_FAILURE = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

_FAILURE_REASONS = frozenset({TerminationReason.STRATEGY_ERROR, TerminationReason.INVALID_COMMAND})


class StrategyLoadError(Exception):
    """Raised when a strategy specification cannot be resolved to a `Strategy` subclass."""


def load_strategy(spec: str) -> Strategy:
    """Instantiate the strategy named by `spec`, written as `TARGET:CLASS`.

    `TARGET` is a path to a Python file or a dotted module name. For a file, its directory is put first
    on the import path so the file can import sibling modules. For a module name, the current directory
    is put on the import path. `CLASS` must be a `Strategy` subclass that takes no constructor arguments.

    Modules imported by the strategy stay cached in `sys.modules`, so load one strategy per process.
    """
    target, separator, class_name = spec.rpartition(":")
    if not separator or not target or not class_name:
        raise StrategyLoadError(f"expected TARGET:CLASS, got {spec!r}")
    try:
        if target.endswith(".py") or Path(target).is_file():
            module = _import_file(Path(target))
        else:
            _prepend_import_path(Path.cwd())
            module = importlib.import_module(target)
    except Exception as error:
        raise StrategyLoadError(f"cannot import {target!r}: {error}") from error
    strategy_class = getattr(module, class_name, None)
    if not (isinstance(strategy_class, type) and issubclass(strategy_class, Strategy)):
        raise StrategyLoadError(f"{class_name!r} in {target!r} is not a Strategy subclass")
    try:
        return strategy_class()
    except Exception as error:
        raise StrategyLoadError(f"cannot instantiate {class_name!r}: {error}") from error


def _import_file(path: Path) -> object:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    _prepend_import_path(path.parent)
    module_name = "_spacecraft_ops_challenge_strategy_" + re.sub(r"\W", "_", str(path))
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _prepend_import_path(directory: Path) -> None:
    entry = str(directory.resolve())
    if entry not in sys.path:
        sys.path.insert(0, entry)


def format_summary(result: RunResult, metrics: RunMetrics) -> str:
    """Human-readable summary of one run."""
    declared_at = "-" if metrics.completion_declared_time_s is None else f"{metrics.completion_declared_time_s:.1f} s"
    rows = [
        ("scenario", f"{result.scenario.name} (seed {result.seed})"),
        ("termination", f"{metrics.termination_reason} at {metrics.end_time_s:.1f} s"),
        ("completion declared", str(metrics.completion_declared)),
        ("safe", str(metrics.safe)),
        (
            "delta-v",
            f"{metrics.delta_v_mps:.4f} m/s "
            f"(target {metrics.target_delta_v_mps:.4f}, error {metrics.delta_v_error_mps:+.4f})",
        ),
        ("declaration time", declared_at),
        ("min battery energy", f"{metrics.min_battery_energy_wh:.2f} Wh"),
        (
            "temperature range",
            f"{metrics.min_propulsion_temperature_c:.2f} .. {metrics.max_propulsion_temperature_c:.2f} C",
        ),
        ("max |wheel momentum|", f"{metrics.max_abs_wheel_momentum_nms:.4f} Nms"),
    ]
    rows.extend(("violation", violation.message) for violation in metrics.safety_violations)
    return "\n".join(f"{label + ':':<22}{value}" for label, value in rows)


def _run_command(args: argparse.Namespace) -> int:
    # With --json, whatever the strategy prints goes to stderr so that stdout stays valid JSON.
    strategy_output = contextlib.redirect_stdout(sys.stderr) if args.json else contextlib.nullcontext()
    with strategy_output:
        try:
            scenario = challenge_scenario(args.scenario)
            strategy = load_strategy(args.strategy)
        except (KeyError, StrategyLoadError) as error:
            print(f"error: {error.args[0] if error.args else error}", file=sys.stderr)
            return EXIT_USAGE
        result = run(strategy, scenario, seed=args.seed)
    metrics = evaluate(result)

    if args.json:
        payload = {
            "scenario": scenario.name,
            "seed": result.seed,
            "metrics": metrics.to_dict(),
            "termination_detail": result.termination.detail,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_summary(result, metrics))
        if result.termination.detail and metrics.termination_reason in _FAILURE_REASONS:
            print(result.termination.detail, file=sys.stderr)
    return EXIT_STRATEGY_FAILURE if metrics.termination_reason in _FAILURE_REASONS else EXIT_OK


def _scenarios_command(args: argparse.Namespace) -> int:
    for name in scenario_names():
        description = challenge_scenario(name).description
        print(f"{name}: {description}" if description else name)
    return EXIT_OK


def _pack_command(args: argparse.Namespace) -> int:
    from spacecraft_ops_challenge.judge.submission import SUBMISSION_DIRNAME, SubmissionError, build_submission

    output = Path(args.output)
    try:
        submission_dir = (Path(args.project_dir) / SUBMISSION_DIRNAME).resolve()
        inside = output.resolve().is_relative_to(submission_dir)
    except (OSError, RuntimeError) as error:  # RuntimeError: a symbolic link loop
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    if inside:
        print(f"error: the output {output} must not be inside {submission_dir}", file=sys.stderr)
        return EXIT_USAGE
    try:
        archive = build_submission(args.project_dir)
        output.write_bytes(archive)
    except (SubmissionError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
        entries = len(zip_file.infolist())
    print(f"{'wrote:':<10}{output}")
    print(f"{'size:':<10}{len(archive)} bytes")
    print(f"{'sha256:':<10}{hashlib.sha256(archive).hexdigest()}")
    print(f"{'entries:':<10}{entries}")
    return EXIT_OK


_OUTPUT_TAIL_LINES = 20


def _format_table(rows: Sequence[Mapping[str, str]]) -> str:
    """Rows of strings as a plain-text table with a header line."""
    if not rows:
        return ""
    columns = list(rows[0])
    widths = {column: max(len(column), *(len(row[column]) for row in rows)) for column in columns}
    lines = ["  ".join(column.ljust(widths[column]) for column in columns).rstrip()]
    lines += ["  ".join(row[column].ljust(widths[column]) for column in columns).rstrip() for row in rows]
    return "\n".join(lines)


def _indented_tail(text: str) -> str:
    lines = text.rstrip("\n").splitlines()
    omitted = len(lines) - _OUTPUT_TAIL_LINES
    shown = [f"    ({omitted} earlier lines omitted)"] if omitted > 0 else []
    return "\n".join(shown + [f"    {line}".rstrip() for line in lines[-_OUTPUT_TAIL_LINES:]])


def format_check_report(source: str, result: "EvaluationResult") -> str:
    """Human-readable report of a `check` run: summary, per-case table, problems, and participant output."""
    from spacecraft_ops_challenge.judge.reporting import case_rows, missing_modules, problem_outcomes, summary_rows

    lines = [f"{'Submission:':<12}{source}", f"{'SHA-256:':<12}{result.submission_sha256}"]
    if result.skipped_entries:
        lines.append(f"{'Skipped:':<12}{', '.join(result.skipped_entries)}")
    plan = result.dependencies.plan
    if plan is not None and plan.to_install:
        lines.append(f"{'Installed:':<12}{', '.join(plan.to_install)}")

    statistics = summary_rows(result.summary)
    width = max(len(row["Statistic"]) for row in statistics) + 2
    lines += ["", "Summary"]
    lines += [f"  {row['Statistic'] + ':':<{width}}{row['Value']}" for row in statistics]
    lines += ["", "Cases", _format_table(case_rows(result.outcomes, result.scores))]

    problems = problem_outcomes(result.outcomes)
    if problems:
        lines += ["", "Problems"]
        for outcome in problems:
            reason = "" if outcome.metrics is None else f" ({outcome.metrics['termination_reason']})"
            lines.append(f"  {outcome.case_id}: {outcome.status.value}{reason}")
            if outcome.detail:
                lines.append(_indented_tail(outcome.detail))
            if outcome.worker_error:
                lines += ["    worker error:", _indented_tail(outcome.worker_error)]

    modules = missing_modules(result.outcomes)
    if modules:
        lines += [
            "",
            f"Missing modules: {', '.join(modules)}",
            "  Packages added with uv add must be listed in pyproject.toml next to submission/;",
            "  your own modules must be inside submission/.",
        ]

    printed = [
        (o.case_id, name, text)
        for o in result.outcomes
        for name, text in (("stdout", o.stdout), ("stderr", o.stderr))
        if text.strip()
    ]
    if printed:
        lines += ["", f"Participant output (last {_OUTPUT_TAIL_LINES} lines of each stream)"]
        for case_id, name, text in printed:
            lines += [f"  {case_id} {name}:", _indented_tail(text)]
    return "\n".join(lines)


def _check_command(args: argparse.Namespace) -> int:
    from spacecraft_ops_challenge.judge.cases import CaseError
    from spacecraft_ops_challenge.judge.dependencies import DependencyError
    from spacecraft_ops_challenge.judge.judging import check_submission
    from spacecraft_ops_challenge.judge.public_scenarios import public_suite
    from spacecraft_ops_challenge.judge.reporting import EvaluationResult, problem_outcomes
    from spacecraft_ops_challenge.judge.runner import DEFAULT_CASE_TIMEOUT_S
    from spacecraft_ops_challenge.judge.scoring import ScoringConfig, ScoringConfigError, score_case
    from spacecraft_ops_challenge.judge.submission import SubmissionError, build_submission

    source = Path(args.submission)
    total = len(public_suite().cases)
    done = 0
    try:
        scoring = ScoringConfig.default() if args.scoring is None else ScoringConfig.from_toml(Path(args.scoring))
        archive = build_submission(source) if source.is_dir() else source.read_bytes()

        def on_case_done(outcome: "CaseOutcome") -> None:
            nonlocal done
            done += 1
            score = 100 * score_case(outcome, scoring).value
            print(f"[{done}/{total}] {outcome.case_id}: {outcome.status.value} (score {score:.2f})", file=sys.stderr)

        evaluation = check_submission(
            archive,
            timeout_s=DEFAULT_CASE_TIMEOUT_S if args.timeout is None else args.timeout,
            scoring=scoring,
            on_status=lambda message: print(message, file=sys.stderr),
            on_case_done=on_case_done,
        )
    except (SubmissionError, DependencyError, CaseError, ScoringConfigError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    result = EvaluationResult.from_evaluation(evaluation)
    if args.json:
        print(result.to_json(), end="")
    else:
        print(format_check_report(str(source), result))
    return EXIT_STRATEGY_FAILURE if problem_outcomes(result.outcomes) else EXIT_OK


def _positive_seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = float("nan")
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"expected a positive number of seconds, got {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of the `spacecraft-ops-challenge` command."""
    parser = argparse.ArgumentParser(
        prog="spacecraft-ops-challenge", description="Run strategies on the challenge scenarios."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    run_parser = subcommands.add_parser("run", help="run a strategy on a challenge scenario and print metrics")
    run_parser.add_argument("strategy", help="strategy as FILE.py:CLASS or MODULE:CLASS")
    run_parser.add_argument("--scenario", default="nominal", help="challenge scenario name (default: nominal)")
    run_parser.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    run_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    run_parser.set_defaults(handler=_run_command)

    scenarios_parser = subcommands.add_parser("scenarios", help="list the challenge scenarios")
    scenarios_parser.set_defaults(handler=_scenarios_command)

    pack_parser = subcommands.add_parser("pack", help="pack a project into a submission archive")
    pack_parser.add_argument(
        "project_dir",
        nargs="?",
        default=".",
        metavar="PROJECT_DIR",
        help="project with a submission/ directory (default: .)",
    )
    pack_parser.add_argument(
        "-o",
        "--output",
        default="submission.zip",
        metavar="FILE",
        help="archive to write, replaced if it exists (default: submission.zip)",
    )
    pack_parser.set_defaults(handler=_pack_command)

    check_parser = subcommands.add_parser("check", help="evaluate a submission on the public scenarios")
    check_parser.add_argument(
        "submission",
        nargs="?",
        default=".",
        metavar="SUBMISSION",
        help="project directory or submission archive (default: .)",
    )
    check_parser.add_argument(
        "--timeout",
        type=_positive_seconds,
        default=None,
        metavar="SECONDS",
        help="wall-clock limit of one case (default: 300)",
    )
    check_parser.add_argument("--scoring", metavar="TOML", help="scoring configuration (default: the shipped one)")
    check_parser.add_argument("--json", action="store_true", help="print the result document as JSON")
    check_parser.set_defaults(handler=_check_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the `spacecraft-ops-challenge` command."""
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
