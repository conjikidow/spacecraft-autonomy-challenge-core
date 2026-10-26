"""The process boundary between the trusted case worker and the participant's strategy process."""

import contextlib
import importlib.util
import io
import json
import os
import textwrap
from pathlib import Path

import pytest
from judge_support import PROVIDER, case

from spacecraft_ops_challenge.evaluation import evaluate
from spacecraft_ops_challenge.judge.dependencies import Overlay
from spacecraft_ops_challenge.judge.runner import CaseStatus, run_case
from spacecraft_ops_challenge.simulation import run

HAS_PROC = Path("/proc").is_dir()

SECRET_ID = "secret-case-7731"
SECRET_SEED = 918273645
SECRET_FACTOR = 0.4321
SECRET_CASE = case(
    SECRET_ID,
    SECRET_SEED,
    {"type": "ThrusterEfficiency", "thruster": "THRUSTER_1", "factor": SECRET_FACTOR, "onset_time_s": 600.0},
    {"type": "TelemetryBias", "channel": "battery_energy_wh", "bias": -2.5},
    name=SECRET_ID,
)

INTROSPECTING = f"""
import gc
import inspect
import json
import sys

from spacecraft_ops_challenge import DeclareCompletion, Strategy

HIDDEN_TYPES = {{
    "EvaluationCase", "ScenarioProvider", "Scenario", "Simulation", "SpacecraftState", "Problem", "RunResult",
    "ThrusterEfficiency", "TelemetryBias", "Timeline",
}}
SECRETS = ({SECRET_ID!r}, {SECRET_SEED!r}, {SECRET_FACTOR!r})


def scan(value, found, seen, depth=0):
    if id(value) in seen or depth > 4:
        return
    seen.add(id(value))
    if type(value).__name__ in HIDDEN_TYPES:
        found.append("object " + type(value).__name__)
    if isinstance(value, (str, int, float)) and not isinstance(value, bool) and value in SECRETS:
        found.append("value " + repr(value))
    if isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, (list, tuple, set, frozenset)):
        children = list(value)
    else:
        children = list(getattr(value, "__dict__", {{}}).values())
        children += [getattr(value, n, None) for n in getattr(type(value), "__slots__", ())]
    for child in children:
        scan(child, found, seen, depth + 1)


def findings():
    found, seen = [], set()
    frames = [info.frame for info in inspect.stack()]
    frame = sys._getframe()
    while frame is not None:
        frames.append(frame)
        frame = frame.f_back
    for frame in frames:
        scan(frame.f_locals, found, seen)
        if frame.f_globals is globals():
            continue  # this probe's own constants
        for name, value in frame.f_globals.items():
            if not name.startswith("__"):
                scan(value, found, seen)
    for obj in gc.get_objects():
        if type(obj).__name__ in HIDDEN_TYPES:
            found.append("gc " + type(obj).__name__)
    found += [
        "module " + name
        for name in sys.modules
        if name.startswith("spacecraft_ops_challenge.judge.")
        and name.rsplit(".", 1)[1] in ("cases", "public_scenarios", "dependencies", "worker", "remote", "runner")
    ]
    found += [
        "module " + name for name in sys.modules if name == "judge_test_provider"
    ]
    return sorted(set(found))


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        print(json.dumps(findings()))

    def update(self, telemetry, commander):
        print(json.dumps(findings()))
        commander.execute(DeclareCompletion())
"""

COMMANDER_TOUR = """
import json
from decimal import Decimal
from fractions import Fraction

from spacecraft_ops_challenge import (
    CommandError, DeclareCompletion, PropulsionMode, SetHeater, SetPropulsionMode, Strategy,
)


def log(*items):
    print(json.dumps(items))


def described(pending):
    return [type(pending).__name__] + [
        [type(s).__name__, type(s.command_id).__name__, s.command_id, s.time_s, repr(s.command)] for s in pending
    ]


class IndexOnly:
    def __init__(self, value):
        self.value = value

    def __index__(self):
        return self.value


class Integral(IndexOnly):
    def __eq__(self, other):
        return self.value == other

    def __hash__(self):
        return hash(self.value)


def attempt(name, request):
    try:
        log(name, repr(request()))
    except CommandError as error:
        log(name, "CommandError", str(error))


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        self.saved = commander
        log("now", commander.now_s)
        ids = [
            commander.schedule(120.0, SetPropulsionMode(PropulsionMode.THRUSTER_1)),
            commander.execute(SetHeater(on=True)),
            commander.schedule(600, SetHeater(on=False)),
            commander.schedule(900.0, SetPropulsionMode(PropulsionMode.OFF)),
            commander.schedule(3000.0, DeclareCompletion()),
        ]
        log("ids", ids, [type(i).__name__ for i in ids])
        log("pending", described(commander.pending()))
        log("cancel", commander.cancel(ids[2]), commander.cancel(ids[2]), commander.cancel(999), commander.cancel("x"))
        extra = commander.schedule(2000.0, SetHeater(on=True))
        log("cancel ids", commander.cancel(IndexOnly(extra)), commander.cancel(Integral(extra)), commander.cancel(1.0))
        others = [commander.schedule(2100.0 + i, SetHeater(on=True)) for i in range(4)]
        log(
            "numeric ids",
            commander.cancel(Decimal(others[0])),
            commander.cancel(Fraction(others[1], 1)),
            commander.cancel(complex(others[2], 0)),
            commander.cancel(str(others[3])),
            commander.cancel(Decimal(others[3]) + Decimal("0.5")),
        )
        canceled = commander.cancel_from(800.0)
        log("cancel_from", type(canceled).__name__, canceled, commander.cancel_from(5000))
        log("pending", described(commander.pending()))
        attempt("past", lambda: commander.schedule(-1.0, SetHeater(on=True)))
        attempt("nan", lambda: commander.schedule(float("nan"), DeclareCompletion()))
        attempt("bool", lambda: commander.schedule(True, DeclareCompletion()))
        attempt("text time", lambda: commander.schedule("130", SetHeater(on=False)))
        attempt("not a command", lambda: commander.schedule(5.0, "heater on"))
        attempt("bad cancel_from", lambda: commander.cancel_from("soon"))
        commander.schedule(1500.0, DeclareCompletion())

    def update(self, telemetry, commander):
        if telemetry.time_s == 60.0:
            attempt("stale now_s", lambda: self.saved.now_s)
            attempt("stale schedule", lambda: self.saved.schedule(100.0, DeclareCompletion()))
            attempt("stale pending", self.saved.pending)
            log("update", commander.now_s, described(commander.pending()))
"""


def submit(make_submission, source):
    return make_submission({"strategy.py": source}).root


def run_locally(source, spec, tmp_path):
    """Run the strategy in this process with core, as the reference for the remote behavior."""
    path = tmp_path / "local_strategy.py"
    path.write_text(textwrap.dedent(source))
    module_spec = importlib.util.spec_from_file_location("local_strategy", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = run(module.MyStrategy(), PROVIDER.build(spec))
    return output.getvalue(), result


def test_participant_introspection_finds_no_hidden_case_data(make_submission, tmp_path):
    outcome = run_case(submit(make_submission, INTROSPECTING), SECRET_CASE, PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED, outcome.detail
    assert [json.loads(line) for line in outcome.stdout.splitlines()] == [[], []]


def test_the_introspection_probe_does_find_hidden_data_in_one_process(tmp_path):
    output, _ = run_locally(INTROSPECTING, SECRET_CASE, tmp_path)
    first = json.loads(output.splitlines()[0])
    assert "object Scenario" in first
    assert "object Simulation" in first
    assert f"value {SECRET_SEED!r}" in first


def test_participant_runs_in_its_own_process(make_submission):
    reporting = """
    import json
    import os
    from pathlib import Path

    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            parent = Path(f"/proc/{os.getppid()}/cmdline")
            cmdline = parent.read_bytes().decode(errors="replace") if parent.exists() else ""
            print(json.dumps([os.getpid(), os.getppid(), cmdline]))
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(submit(make_submission, reporting), SECRET_CASE, PROVIDER)
    pid, parent_pid, parent_cmdline = json.loads(outcome.stdout)
    assert pid != parent_pid
    assert os.getpid() not in (pid, parent_pid)
    if HAS_PROC:
        assert "spacecraft_ops_challenge.judge.worker" in parent_cmdline


def test_remote_commander_matches_the_core_commander(make_submission, tmp_path):
    spec = case("tour", 3)
    outcome = run_case(submit(make_submission, COMMANDER_TOUR), spec, PROVIDER)
    local_output, local_result = run_locally(COMMANDER_TOUR, spec, tmp_path)
    assert outcome.status is CaseStatus.COMPLETED, outcome.detail
    assert outcome.stdout == local_output
    assert outcome.metrics == evaluate(local_result).to_dict()
    log = {entry[0]: entry[1:] for entry in map(json.loads, outcome.stdout.splitlines())}
    assert log["now"] == [0.0]
    assert log["cancel"] == [True, False, False, False]
    assert log["cancel ids"] == [False, True, True]
    assert log["numeric ids"] == [True, True, True, False, False]
    assert log["past"] == ["CommandError", "cannot schedule a command in the past: -1.0 s < now 0.0 s"]
    assert log["not a command"] == ["CommandError", "not a command: 'heater on'"]
    assert log["stale now_s"] == ["CommandError", "this commander is only valid during the callback it was passed to"]
    assert outcome.metrics["completion_declared_time_s"] == 1500.0


def test_uncaught_command_errors_end_the_run_as_invalid_command(make_submission):
    invalid = """
    from spacecraft_ops_challenge import SetHeater, Strategy


    class MyStrategy(Strategy):
        def update(self, telemetry, commander):
            commander.schedule(telemetry.time_s - 1.0, SetHeater(on=True))
    """
    outcome = run_case(submit(make_submission, invalid), SECRET_CASE, PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.metrics["termination_reason"] == "INVALID_COMMAND"
    assert outcome.metrics["end_time_s"] == 60.0
    assert "cannot schedule a command in the past: 59.0 s < now 60.0 s" in outcome.detail
    assert 'strategy.py", line 7, in update' in outcome.detail


def test_strategy_exceptions_keep_the_participant_traceback(make_submission):
    failing = """
    from spacecraft_ops_challenge import Strategy


    def plan():
        raise ValueError("no feasible plan")


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            plan()
    """
    outcome = run_case(submit(make_submission, failing), SECRET_CASE, PROVIDER)
    assert outcome.metrics["termination_reason"] == "STRATEGY_ERROR"
    assert outcome.metrics["end_time_s"] == 0.0
    assert 'strategy.py", line 11, in initialize' in outcome.detail
    assert 'strategy.py", line 6, in plan' in outcome.detail
    assert "ValueError: no feasible plan" in outcome.detail


def test_keyboard_interrupt_in_a_callback_is_a_crash(make_submission):
    interrupting = """
    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def update(self, telemetry, commander):
            raise KeyboardInterrupt
    """
    outcome = run_case(submit(make_submission, interrupting), SECRET_CASE, PROVIDER)
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail.startswith("the strategy stopped the run:")
    assert "KeyboardInterrupt" in outcome.detail


@pytest.mark.parametrize("where", ["import", "update"])
def test_a_hard_exit_of_the_participant_leaves_the_worker_running(make_submission, where):
    exiting = f"""
    import os

    from spacecraft_ops_challenge import Strategy

    if {where!r} == "import":
        os._exit(9)


    class MyStrategy(Strategy):
        def update(self, telemetry, commander):
            print("leaving at", telemetry.time_s, flush=True)
            os._exit(9)
    """
    outcome = run_case(submit(make_submission, exiting), SECRET_CASE, PROVIDER)
    # The trusted worker survived: it reported the exit as a structured result.
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail == "the strategy process exited with status 9"
    assert outcome.stdout == ("leaving at 60.0\n" if where == "update" else "")


def test_malformed_messages_from_the_participant_end_the_case(make_submission):
    corrupting = """
    import os
    import sys
    import time

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            os.write(int(sys.argv[1]), b"\\xff\\xff\\xff\\xffgarbage")
            time.sleep(60)
    """
    outcome = run_case(submit(make_submission, corrupting), SECRET_CASE, PROVIDER, timeout_s=30.0)
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail.startswith("the strategy process broke the protocol: message of")
    assert outcome.duration_s < 20


def make_overlay(tmp_path):
    overlay = tmp_path / "overlay"
    overlay.mkdir()
    (overlay / "participant_package.py").write_text("VALUE = 'from the overlay'\n")
    marker = "import os, pathlib; pathlib.Path(os.environ['MARKER_DIR'], str(os.getpid())).touch()\n"
    (overlay / "marker.pth").write_text(marker)
    markers = tmp_path / "markers"
    markers.mkdir()
    return overlay, markers


def test_only_the_participant_process_gets_the_overlay(make_submission, tmp_path):
    overlay, markers = make_overlay(tmp_path)
    importing = """
    import json
    import os
    from pathlib import Path

    import participant_package
    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            environ = Path(f"/proc/{os.getppid()}/environ")
            entries = environ.read_bytes().split(b"\\0") if environ.exists() else []
            parent_path = [e.decode().split("=", 1)[1] for e in entries if e.startswith(b"PYTHONPATH=")]
            print(json.dumps([participant_package.VALUE, os.getpid(), os.getppid(), parent_path]))
            commander.execute(DeclareCompletion())
    """
    env = {**os.environ, "MARKER_DIR": str(markers)}
    outcome = run_case(submit(make_submission, importing), SECRET_CASE, PROVIDER, env=env, overlay=Overlay(overlay))
    assert outcome.status is CaseStatus.COMPLETED, outcome.detail
    value, pid, parent_pid, parent_path = json.loads(outcome.stdout)
    assert value == "from the overlay"
    # Only the participant process processed the overlay's .pth file.
    assert sorted(path.name for path in markers.iterdir()) == [str(pid)]
    if HAS_PROC:
        assert all(str(overlay) not in entry for entry in parent_path)
    assert parent_pid != pid


def test_an_overlay_cannot_replace_the_trusted_worker(make_submission, tmp_path):
    overlay, _ = make_overlay(tmp_path)
    (overlay / "marker.pth").unlink()
    fake = overlay / "spacecraft_ops_challenge" / "judge"
    fake.mkdir(parents=True)
    (fake.parent / "__init__.py").write_text("")
    (fake / "__init__.py").write_text("")
    (fake / "participant.py").write_text("def main(argv):\n    print('fake participant')\n")
    outcome = run_case(submit(make_submission, "raise SystemExit\n"), SECRET_CASE, PROVIDER, overlay=Overlay(overlay))
    # A fake core package in the overlay only reaches the participant process; the real trusted worker still
    # reports the outcome.
    assert outcome.stdout == "fake participant\n"
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail == "the strategy process exited with status 0"


def test_a_forked_child_holding_the_connection_does_not_hide_the_participant_exit(make_submission):
    forking = """
    import os
    import time

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            if os.fork() == 0:
                time.sleep(60)
                os._exit(0)
            os._exit(5)
    """
    outcome = run_case(submit(make_submission, forking), SECRET_CASE, PROVIDER, timeout_s=30.0)
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail == "the strategy process exited with status 5"
    assert outcome.duration_s < 20
