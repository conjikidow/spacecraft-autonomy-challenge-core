"""Command-line runner: `spacecraft-ops run STRATEGY` and `spacecraft-ops scenarios`.

Exit status: 0 when the run finished, 1 when the strategy raised an exception or made an invalid
timeline request, and 2 for usage errors such as a strategy that cannot be loaded.
"""

import argparse
import importlib
import importlib.util
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from spacecraft_ops.evaluation import RunMetrics, evaluate, reference_score
from spacecraft_ops.reference import reference_scenario, reference_scenario_names
from spacecraft_ops.results import RunResult, TerminationReason
from spacecraft_ops.simulation import run
from spacecraft_ops.strategy import Strategy

EXIT_OK = 0
EXIT_STRATEGY_FAILURE = 1
EXIT_USAGE = 2

_FAILURE_REASONS = frozenset({TerminationReason.STRATEGY_ERROR, TerminationReason.INVALID_COMMAND})


class StrategyLoadError(Exception):
    """Raised when a strategy specification cannot be resolved to a `Strategy` subclass."""


def load_strategy(spec: str) -> Strategy:
    """Instantiate the strategy named by `spec`, written as `TARGET:CLASS`.

    `TARGET` is a path to a Python file or a dotted module name. For a file, its directory is put first
    on the import path so the file can import sibling modules. For a module name, the current directory
    is put on the import path. `CLASS` must be a `Strategy` subclass that takes no constructor arguments.
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
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _prepend_import_path(directory: Path) -> None:
    entry = str(directory.resolve())
    if entry not in sys.path:
        sys.path.insert(0, entry)


def format_summary(result: RunResult, metrics: RunMetrics, score: float) -> str:
    """Human-readable summary of one run."""
    completion = "-" if metrics.completion_time_s is None else f"{metrics.completion_time_s:.1f} s"
    rows = [
        ("scenario", f"{result.scenario.name} (seed {result.seed})"),
        ("termination", f"{metrics.termination_reason} at {metrics.end_time_s:.1f} s"),
        ("completed", str(metrics.completed)),
        ("safe", str(metrics.safe)),
        (
            "delta-v",
            f"{metrics.delta_v_mps:.4f} m/s "
            f"(target {metrics.target_delta_v_mps:.4f}, error {metrics.delta_v_error_mps:+.4f})",
        ),
        ("completion time", completion),
        ("min battery energy", f"{metrics.min_battery_energy_wh:.2f} Wh"),
        (
            "temperature range",
            f"{metrics.min_propulsion_temperature_c:.2f} .. {metrics.max_propulsion_temperature_c:.2f} C",
        ),
        ("max |wheel momentum|", f"{metrics.max_abs_wheel_momentum_nms:.4f} Nms"),
        ("reference score", f"{score:.4f}"),
    ]
    rows.extend(("violation", violation.message) for violation in metrics.safety_violations)
    return "\n".join(f"{label + ':':<22}{value}" for label, value in rows)


def _run_command(args: argparse.Namespace) -> int:
    try:
        scenario = reference_scenario(args.scenario)
        strategy = load_strategy(args.strategy)
    except (KeyError, StrategyLoadError) as error:
        print(f"error: {error.args[0] if error.args else error}", file=sys.stderr)
        return EXIT_USAGE

    result = run(strategy, scenario, seed=args.seed)
    metrics = evaluate(result)
    score = reference_score(metrics)

    if args.json:
        payload = {
            "scenario": scenario.name,
            "seed": result.seed,
            "metrics": metrics.to_dict(),
            "reference_score": score,
            "termination_detail": result.termination.detail,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_summary(result, metrics, score))
        if result.termination.detail and metrics.termination_reason in _FAILURE_REASONS:
            print(result.termination.detail, file=sys.stderr)
    return EXIT_STRATEGY_FAILURE if metrics.termination_reason in _FAILURE_REASONS else EXIT_OK


def _scenarios_command(args: argparse.Namespace) -> int:
    for name in reference_scenario_names():
        description = reference_scenario(name).description
        print(f"{name}: {description}" if description else name)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """Argument parser of the `spacecraft-ops` command."""
    parser = argparse.ArgumentParser(prog="spacecraft-ops", description="Run strategies on reference scenarios.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run_parser = subcommands.add_parser("run", help="run a strategy on a reference scenario and print metrics")
    run_parser.add_argument("strategy", help="strategy as FILE.py:CLASS or MODULE:CLASS")
    run_parser.add_argument("--scenario", default="nominal", help="reference scenario name (default: nominal)")
    run_parser.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    run_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    run_parser.set_defaults(handler=_run_command)

    scenarios_parser = subcommands.add_parser("scenarios", help="list reference scenarios")
    scenarios_parser.set_defaults(handler=_scenarios_command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of the `spacecraft-ops` command."""
    args = build_parser().parse_args(argv)
    return args.handler(args)
