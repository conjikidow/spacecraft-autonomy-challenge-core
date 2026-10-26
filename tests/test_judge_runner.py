import json
import os
import re
import signal
import time
from pathlib import Path

import pytest
from judge_support import DECLARE_AT_START, PROVIDER, case

from spacecraft_ops_challenge.judge import runner
from spacecraft_ops_challenge.judge.cases import ScenarioProvider
from spacecraft_ops_challenge.judge.dependencies import Overlay
from spacecraft_ops_challenge.judge.runner import CaseOutcome, CaseStatus, run_case, run_suite


def process_is_running(pid):
    """Whether `pid` is alive and not a zombie, waiting briefly for a killed process to be reaped."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):  # gone, or reaped while being read
            return False
        if state == "Z":
            return False
        time.sleep(0.05)
    return True


CASES = (
    case("case-1", 1),
    case("case-2", 2, {"type": "ThrusterEfficiency", "thruster": "THRUSTER_1", "factor": 0.5}),
    case("case-3", 3, {"type": "TelemetryBias", "channel": "delta_v_mps", "bias": 0.5}),
)

FIRE_THEN_DECLARE = """
from spacecraft_ops_challenge import DeclareCompletion, PropulsionMode, SetPropulsionMode, Strategy


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        commander.execute(SetPropulsionMode(PropulsionMode.THRUSTER_1))
        commander.schedule(1200.0, DeclareCompletion())
"""

MODULE_STATE = """
import os

import helper
from spacecraft_ops_challenge import DeclareCompletion, Strategy

CALLS = 0


class MyStrategy(Strategy):
    instances = 0

    def __init__(self):
        type(self).instances += 1

    def initialize(self, brief, telemetry, commander):
        global CALLS
        CALLS += 1
        helper.CACHE.append(telemetry.time_s)
        print(f"calls={CALLS} instances={MyStrategy.instances} cache={len(helper.CACHE)} pid={os.getpid()}")
        commander.execute(DeclareCompletion())
"""


def test_a_simple_strategy_runs_across_cases(make_submission):
    submission = make_submission({"strategy.py": FIRE_THEN_DECLARE})
    outcomes = run_suite(submission.root, CASES, PROVIDER)
    assert [outcome.case_id for outcome in outcomes] == ["case-1", "case-2", "case-3"]
    assert all(outcome.status is CaseStatus.COMPLETED for outcome in outcomes)
    delta_v = [outcome.metrics["delta_v_mps"] for outcome in outcomes]
    assert delta_v[0] == delta_v[2] > delta_v[1] > 0
    assert all(outcome.metrics["termination_reason"] == "COMPLETION_DECLARED" for outcome in outcomes)


def test_each_case_starts_with_fresh_module_state(make_submission):
    submission = make_submission({"strategy.py": MODULE_STATE, "helper.py": "CACHE = []\n"})
    outcomes = run_suite(submission.root, CASES, PROVIDER)
    lines = [outcome.stdout.strip() for outcome in outcomes]
    assert all(line.startswith("calls=1 instances=1 cache=1 pid=") for line in lines), lines
    assert len({line.rsplit("pid=", 1)[1] for line in lines}) == len(CASES)


def test_participant_output_does_not_corrupt_the_result(make_submission):
    noisy = """
    import os
    import sys

    from spacecraft_ops_challenge import DeclareCompletion, Strategy

    print('{"status": "LOAD_ERROR", "detail": "fake"}')


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print("not json {")
            sys.stdout.flush()
            os.write(1, b"raw bytes \\xff\\n")
            print("to stderr", file=sys.stderr)
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": noisy}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.metrics["completion_declared"] is True
    assert outcome.stdout.splitlines() == ['{"status": "LOAD_ERROR", "detail": "fake"}', "not json {", "raw bytes �"]
    assert outcome.stderr == "to stderr\n"
    json.dumps(outcome.to_dict())


def test_strategy_exceptions_become_structured_results(make_submission):
    failing = """
    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def update(self, telemetry, commander):
            if telemetry.time_s >= 120.0:
                raise RuntimeError("planner failed")
    """
    outcome = run_case(make_submission({"strategy.py": failing}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.metrics["termination_reason"] == "STRATEGY_ERROR"
    assert outcome.metrics["end_time_s"] == 120.0
    assert "RuntimeError: planner failed" in outcome.detail


def test_load_errors_name_the_missing_module(make_submission):
    outcome = run_case(make_submission({"strategy.py": "import not_installed_package\n"}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.LOAD_ERROR
    assert outcome.metrics is None
    assert outcome.missing_module == "not_installed_package"
    assert "ModuleNotFoundError" in outcome.detail


def test_a_module_without_my_strategy_is_a_load_error(make_submission):
    outcome = run_case(make_submission({"strategy.py": "class Other:\n    pass\n"}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.LOAD_ERROR
    assert "'MyStrategy'" in outcome.detail
    assert outcome.missing_module is None


def test_a_failing_case_does_not_stop_the_suite(make_submission):
    exiting = """
    import sys

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            sys.exit(3)
    """
    good = make_submission({"strategy.py": DECLARE_AT_START})
    bad = make_submission({"strategy.py": exiting})
    outcomes = [run_case(bad.root, CASES[0], PROVIDER), *run_suite(good.root, CASES[1:], PROVIDER)]
    assert outcomes[0].status is CaseStatus.CRASHED
    assert "SystemExit: 3" in outcomes[0].detail
    assert [o.status for o in outcomes[1:]] == [CaseStatus.COMPLETED, CaseStatus.COMPLETED]


def test_a_hard_exit_is_reported_as_a_crash(make_submission):
    hard_exit = """
    import os

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print("leaving")
            os._exit(7)
    """
    outcome = run_case(make_submission({"strategy.py": hard_exit}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail == "the strategy process exited with status 7"
    assert outcome.stdout == "leaving\n"


def test_cases_time_out(make_submission):
    slow = """
    import time

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print("started", flush=True)
            time.sleep(60)
    """
    outcome = run_case(make_submission({"strategy.py": slow}).root, CASES[0], PROVIDER, timeout_s=5.0)
    assert outcome.status is CaseStatus.TIMEOUT
    assert outcome.metrics is None
    assert outcome.stdout == "started\n"
    assert outcome.duration_s < 30


def test_submission_files_are_found_like_the_template_runner(make_submission):
    reading = """
    from pathlib import Path

    from spacecraft_ops_challenge import DeclareCompletion, Strategy

    from planner.core import plan


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print(plan(), (Path(__file__).parent / "data.txt").read_text(), Path("submission/data.txt").exists())
            commander.execute(DeclareCompletion())
    """
    submission = make_submission(
        {
            "strategy.py": reading,
            "planner/__init__.py": "",
            "planner/core.py": "def plan():\n    return 'planned'\n",
            "data.txt": "payload",
        }
    )
    outcome = run_case(submission.root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED, outcome.detail
    assert outcome.stdout == "planned payload True\n"


def test_long_output_is_shortened(make_submission):
    chatty = """
    from spacecraft_ops_challenge import DeclareCompletion, Strategy

    print("x" * 300_000)


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": chatty}).root, CASES[0], PROVIDER)
    assert re.search(r"\n\.\.\. \[200001 bytes omitted\] \.\.\.\n", outcome.stdout)
    assert outcome.stdout.startswith("x" * 50_000 + "\n...")
    assert outcome.stdout.endswith("]" + " ...\n" + "x" * 49_999 + "\n")


def test_endless_output_is_bounded_while_it_is_read(make_submission):
    endless = """
    import sys

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            while True:
                sys.stdout.write("y" * 65536)
    """
    outcome = run_case(make_submission({"strategy.py": endless}).root, CASES[0], PROVIDER, timeout_s=5.0)
    assert outcome.status is CaseStatus.TIMEOUT
    assert len(outcome.stdout) < 101_000
    omitted = int(re.search(r"\[(\d+) bytes omitted\]", outcome.stdout).group(1))
    assert omitted > 1_000_000


def test_overlay_packages_come_before_the_environment_packages(make_submission, tmp_path):
    overlay = tmp_path / "overlay"
    (overlay / "typing_extensions").mkdir(parents=True)
    (overlay / "typing_extensions" / "__init__.py").write_text("SOURCE = 'overlay'\n")
    (overlay / "participant_only.py").write_text("VALUE = 42\n")
    (tmp_path / "linked").mkdir()
    (tmp_path / "linked" / "linked_module.py").write_text("VALUE = 'linked'\n")
    (overlay / "extra.pth").write_text(f"{tmp_path / 'linked'}\n")
    importing = """
    import subprocess
    import sys

    import linked_module
    import participant_only
    import typing_extensions
    from spacecraft_ops_challenge import DeclareCompletion, Strategy

    child = "import participant_only; print(participant_only.VALUE)"


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            inherited = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True).stdout.strip()
            print(typing_extensions.SOURCE, participant_only.VALUE, linked_module.VALUE, inherited)
            commander.execute(DeclareCompletion())
    """
    submission = make_submission({"strategy.py": importing})
    without = run_case(submission.root, CASES[0], PROVIDER)
    assert without.status is CaseStatus.LOAD_ERROR
    assert without.missing_module == "linked_module"
    outcome = run_case(submission.root, CASES[0], PROVIDER, overlay=Overlay(overlay))
    assert outcome.status is CaseStatus.COMPLETED, outcome.detail
    assert outcome.stdout == "overlay 42 linked 42\n"


def test_threads_left_running_do_not_hold_up_a_finished_case(make_submission):
    lingering = """
    import threading
    import time

    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            threading.Thread(target=time.sleep, args=(60,)).start()
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": lingering}).root, CASES[0], PROVIDER, timeout_s=30.0)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.duration_s < 20


@pytest.mark.skipif(not Path("/proc").is_dir(), reason="needs /proc to inspect processes")
@pytest.mark.parametrize("stdio", ["inherited", "detached"])
def test_processes_left_behind_are_stopped_when_the_case_ends(make_submission, stdio):
    orphaning = f"""
    import subprocess
    import sys

    from spacecraft_ops_challenge import DeclareCompletion, Strategy

    STDIO = {{"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}}


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            options = STDIO if "{stdio}" == "detached" else {{}}
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], **options)
            print(child.pid, flush=True)
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": orphaning}).root, CASES[0], PROVIDER, timeout_s=30.0)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.duration_s < 20
    assert not process_is_running(int(outcome.stdout))


def test_the_request_is_not_where_the_strategy_can_read_it(make_submission):
    inspecting = """
    import json
    import os
    import sys
    from pathlib import Path

    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            files = sorted(str(p.relative_to(Path.cwd())) for p in Path.cwd().rglob("*.py"))
            print(json.dumps([sys.argv[1:], sys.stdin.read(), dict(os.environ), files]))
            commander.execute(DeclareCompletion())
    """
    hidden = case("hidden-id-58213", 7, {"type": "ThrusterEfficiency", "thruster": "THRUSTER_2", "factor": 0.5})
    outcome = run_case(make_submission({"strategy.py": inspecting}).root, hidden, PROVIDER)
    arguments, stdin, environment, files = json.loads(outcome.stdout)
    socket_fd, submission_root = arguments
    assert socket_fd.isdigit()
    assert Path(submission_root).name == "root"
    assert stdin == ""
    assert files == ["submission/strategy.py"]
    for secret in ("hidden-id-58213", "ThrusterEfficiency", "THRUSTER_2", "result.json"):
        assert secret not in outcome.stdout
    assert environment["PYTHONUNBUFFERED"] == "1"


def test_worker_failures_become_structured_results(make_submission):
    broken = case("broken", 1, {"type": "NoSuchModifier"})
    outcome = run_case(make_submission({"strategy.py": DECLARE_AT_START}).root, broken, PROVIDER)
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail == "the trusted worker failed to evaluate the case (KeyError)"
    assert "NoSuchModifier" not in outcome.detail + outcome.stdout + outcome.stderr
    assert "KeyError: 'NoSuchModifier'" in outcome.worker_error


def test_a_helper_outside_the_session_holding_the_output_does_not_block(make_submission):
    escaping = """
    import subprocess
    import sys

    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            helper = [sys.executable, "-c", "import time; time.sleep(60)"]
            print(subprocess.Popen(helper, start_new_session=True).pid, flush=True)
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": escaping}).root, CASES[0], PROVIDER, timeout_s=30.0)
    try:
        assert outcome.status is CaseStatus.COMPLETED
        assert outcome.duration_s < 15
    finally:
        os.kill(int(outcome.stdout.split()[0]), signal.SIGKILL)


def test_files_written_by_the_strategy_do_not_reach_later_cases(make_submission):
    caching = """
    from pathlib import Path

    from spacecraft_ops_challenge import DeclareCompletion, Strategy

    CACHE = Path(__file__).parent / "cache.txt"


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print("cached" if CACHE.exists() else "fresh")
            CACHE.write_text("state")
            Path(__file__).write_text("raise RuntimeError('replaced')")
            commander.execute(DeclareCompletion())
    """
    submission = make_submission({"strategy.py": caching})
    original = submission.strategy_file.read_text()
    outcomes = run_suite(submission.root, CASES, PROVIDER)
    assert [outcome.stdout for outcome in outcomes] == ["fresh\n"] * len(CASES)
    assert not (submission.directory / "cache.txt").exists()
    assert submission.strategy_file.read_text() == original


def test_a_result_written_after_the_deadline_does_not_count(make_submission, monkeypatch):
    # The worker finishes quickly, but the runner only learns of it after the deadline.
    monkeypatch.setattr(runner, "_has_exited", lambda process: False)
    outcome = run_case(make_submission({"strategy.py": DECLARE_AT_START}).root, CASES[0], PROVIDER, timeout_s=2.0)
    assert outcome.status is CaseStatus.TIMEOUT
    assert outcome.metrics is None


BURN_CPU = """
import time

from spacecraft_ops_challenge import DeclareCompletion, Strategy


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        end = time.process_time() + 0.3
        while time.process_time() < end:
            pass
        commander.execute(DeclareCompletion())
"""


@pytest.mark.skipif(not hasattr(os, "wait4"), reason="needs os.wait4 to measure the participant process")
def test_the_cpu_time_of_the_participant_process_is_recorded(make_submission):
    quick = run_case(make_submission({"strategy.py": DECLARE_AT_START}).root, CASES[0], PROVIDER)
    burning = run_case(make_submission({"strategy.py": BURN_CPU}).root, CASES[0], PROVIDER)
    assert quick.status is burning.status is CaseStatus.COMPLETED
    assert 0.0 <= quick.participant_cpu_s < 0.25
    assert burning.participant_cpu_s >= 0.3
    assert burning.participant_cpu_s > quick.participant_cpu_s + 0.2


def test_cases_without_a_completed_run_have_no_cpu_time(make_submission):
    hard_exit = """
    import os

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            os._exit(7)
    """
    slow = """
    import time

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            time.sleep(60)
    """
    crashed = run_case(make_submission({"strategy.py": hard_exit}).root, CASES[0], PROVIDER)
    timed_out = run_case(make_submission({"strategy.py": slow}).root, CASES[0], PROVIDER, timeout_s=3.0)
    load_error = run_case(make_submission({"strategy.py": "import not_installed_package\n"}).root, CASES[0], PROVIDER)
    assert [crashed.status, timed_out.status, load_error.status] == [
        CaseStatus.CRASHED,
        CaseStatus.TIMEOUT,
        CaseStatus.LOAD_ERROR,
    ]
    assert crashed.participant_cpu_s is timed_out.participant_cpu_s is load_error.participant_cpu_s is None


def test_outcomes_round_trip_through_json(make_submission):
    completed = run_case(make_submission({"strategy.py": DECLARE_AT_START}).root, CASES[0], PROVIDER)
    failed = run_case(make_submission({"strategy.py": "import not_installed_package\n"}).root, CASES[0], PROVIDER)
    for outcome in (completed, failed):
        assert CaseOutcome.from_dict(json.loads(json.dumps(outcome.to_dict()))) == outcome
    assert CaseOutcome.from_dict(completed.to_dict()).status is CaseStatus.COMPLETED


@pytest.mark.parametrize(
    "change",
    [
        {"status": "PASSED"},
        {"metrics": [1, 2]},
        {"duration_s": None},
        {"duration_s": "1.5"},
        {"duration_s": True},
        {"participant_cpu_s": "fast"},
        {"case_id": None},
        {"detail": 3},
        {"stdout": []},
        {"missing_module": 1},
        {"worker_error": 1},
    ],
)
def test_malformed_outcomes_are_rejected(change):
    data = {
        "case_id": "case-1",
        "status": "COMPLETED",
        "metrics": {},
        "detail": "",
        "missing_module": None,
        "stdout": "",
        "stderr": "",
        "duration_s": 1.0,
        "participant_cpu_s": 0.5,
    }
    assert CaseOutcome.from_dict(data).participant_cpu_s == 0.5
    with pytest.raises(ValueError, match="not a case outcome"):
        CaseOutcome.from_dict(data | change)
    del data["stdout"]
    with pytest.raises(ValueError, match="not a case outcome"):
        CaseOutcome.from_dict(data)


def test_output_of_the_scenario_provider_does_not_reach_the_participant_output(make_submission):
    provider = ScenarioProvider("judge_test_provider:noisy", PROVIDER.paths)
    printing = """
    import sys

    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print("strategy stdout")
            print("strategy stderr", file=sys.stderr)
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": printing}).root, CASES[0], provider)
    assert outcome.status is CaseStatus.COMPLETED
    assert "strategy stdout" in outcome.stdout
    assert "strategy stderr" in outcome.stderr
    assert "secret" not in outcome.stdout + outcome.stderr


def test_a_participant_that_does_not_exit_after_the_run_reports_no_cpu_time(make_submission):
    lingering = """
    import time

    from spacecraft_ops_challenge import DeclareCompletion, Strategy
    from spacecraft_ops_challenge.judge import protocol


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            commander.execute(DeclareCompletion())
            # Never notice that the trusted worker closed the connection after the run.
            protocol.Channel.receive = lambda self: time.sleep(60)
    """
    outcome = run_case(make_submission({"strategy.py": lingering}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.participant_cpu_s is None
    assert 5.0 <= outcome.duration_s < 15.0


def test_a_scenario_provider_that_exits_still_leaves_a_result(make_submission):
    provider = ScenarioProvider("judge_test_provider:exiting", PROVIDER.paths)
    outcome = run_case(make_submission({"strategy.py": DECLARE_AT_START}).root, CASES[0], provider)
    assert outcome.status is CaseStatus.CRASHED
    assert outcome.detail == "the trusted worker failed to evaluate the case (SystemExit)"
    assert "bad configuration" in outcome.worker_error
    assert "bad configuration" not in outcome.stdout + outcome.stderr


def test_environment_changes_of_the_scenario_provider_do_not_reach_the_participant(make_submission):
    provider = ScenarioProvider("judge_test_provider:exporting", PROVIDER.paths)
    reading = """
    import os

    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print("hidden:", os.environ.get("JUDGE_TEST_HIDDEN"))
            commander.execute(DeclareCompletion())
    """
    outcome = run_case(make_submission({"strategy.py": reading}).root, CASES[0], provider)
    assert outcome.status is CaseStatus.COMPLETED
    assert "hidden: None" in outcome.stdout


def test_huge_strategy_errors_are_shortened_instead_of_breaking_the_protocol(make_submission):
    raising = """
    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            raise ValueError("x" * 20_000_000)
    """
    outcome = run_case(make_submission({"strategy.py": raising}).root, CASES[0], PROVIDER)
    assert outcome.status is CaseStatus.COMPLETED
    assert outcome.metrics["termination_reason"] == "STRATEGY_ERROR"
    assert "characters omitted" in outcome.detail
    assert len(outcome.detail) < 200_000


def test_huge_load_errors_are_shortened(make_submission):
    outcome = run_case(
        make_submission({"strategy.py": "raise ImportError('y' * 20_000_000)\n"}).root, CASES[0], PROVIDER
    )
    assert outcome.status is CaseStatus.LOAD_ERROR
    assert "characters omitted" in outcome.detail


def test_cases_need_a_posix_platform(make_submission, monkeypatch):
    submission = make_submission({"strategy.py": DECLARE_AT_START})
    monkeypatch.setattr(runner.os, "name", "nt")
    with pytest.raises(RuntimeError, match="requires Linux or macOS"):
        run_case(submission.root, CASES[0], PROVIDER)


def test_an_interrupted_case_stops_its_processes(make_submission, monkeypatch):
    sleeping = """
    import time

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            time.sleep(60)
    """
    submission = make_submission({"strategy.py": sleeping})
    started = []
    original_popen = runner.subprocess.Popen

    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        started.append(process)
        return process

    deadline = time.monotonic() + 1.0

    def interrupted(process):
        if time.monotonic() > deadline:  # the strategy is sleeping by now
            raise KeyboardInterrupt
        return False

    monkeypatch.setattr(runner.subprocess, "Popen", popen)
    monkeypatch.setattr(runner, "_has_exited", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_case(submission.root, CASES[0], PROVIDER)
    (worker,) = started
    assert worker.returncode is not None
    # The worker led its own process group, which held the participant process as well.
    for _ in range(100):
        try:
            os.killpg(worker.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("processes of the interrupted case are still running")


def test_a_relative_overlay_path_is_resolved_against_the_caller(make_submission, tmp_path, monkeypatch):
    (tmp_path / "overlay").mkdir()
    (tmp_path / "overlay" / "participant_only.py").write_text("VALUE = 42\n")
    importing = """
    import participant_only
    from spacecraft_ops_challenge import DeclareCompletion, Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            print(participant_only.VALUE)
            commander.execute(DeclareCompletion())
    """
    submission = make_submission({"strategy.py": importing})
    monkeypatch.chdir(tmp_path)
    outcome = run_case(submission.root, CASES[0], PROVIDER, overlay=Overlay(Path("overlay")))
    assert outcome.status is CaseStatus.COMPLETED, outcome.detail
    assert outcome.stdout == "42\n"


def test_other_base_exceptions_end_the_case_at_once(make_submission):
    odd = """
    import threading
    import time

    from spacecraft_ops_challenge import Strategy


    class Odd(BaseException):
        pass


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            threading.Thread(target=time.sleep, args=(60,)).start()
            raise Odd("odd")
    """
    outcome = run_case(make_submission({"strategy.py": odd}).root, CASES[0], PROVIDER, timeout_s=30.0)
    assert outcome.status is CaseStatus.CRASHED
    assert "Odd" in outcome.detail
    assert outcome.duration_s < 10.0


def test_deeply_nested_messages_are_protocol_errors(make_submission):
    nesting = """
    import os
    import sys
    import time

    from spacecraft_ops_challenge import Strategy


    class MyStrategy(Strategy):
        def initialize(self, brief, telemetry, commander):
            data = b"[" * 200_000
            os.write(int(sys.argv[1]), len(data).to_bytes(4, "big") + data)
            time.sleep(30)
    """
    outcome = run_case(make_submission({"strategy.py": nesting}).root, CASES[0], PROVIDER, timeout_s=20.0)
    assert outcome.status is CaseStatus.CRASHED
    assert "broke the protocol" in outcome.detail
    assert outcome.worker_error is None
