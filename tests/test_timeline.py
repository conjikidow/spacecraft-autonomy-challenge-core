import math

import pytest

from spacecraft_autonomy_challenge.commands import (
    CommandError,
    DeclareCompletion,
    PropulsionMode,
    SetHeater,
    SetPropulsionMode,
)
from spacecraft_autonomy_challenge.timeline import Timeline

FIRE_1 = SetPropulsionMode(PropulsionMode.THRUSTER_1)
OFF = SetPropulsionMode(PropulsionMode.OFF)


def drain(timeline: Timeline, now_s: float) -> list:
    executed = []
    while (scheduled := timeline.pop_due(now_s)) is not None:
        executed.append(scheduled)
    return executed


def test_identifiers_are_sequential_from_one():
    timeline = Timeline()
    ids = [timeline.schedule(t, OFF, now_s=0.0) for t in (30.0, 10.0, 20.0)]
    assert ids == [1, 2, 3]


def test_pending_is_ordered_by_time():
    timeline = Timeline()
    timeline.schedule(30.0, OFF, now_s=0.0)
    timeline.schedule(10.0, FIRE_1, now_s=0.0)
    assert [s.time_s for s in timeline.pending()] == [10.0, 30.0]
    assert timeline.next_time_s() == 10.0


def test_same_time_commands_execute_in_registration_order():
    timeline = Timeline()
    first = timeline.schedule(10.0, FIRE_1, now_s=0.0)
    timeline.schedule(5.0, SetHeater(on=True), now_s=0.0)
    second = timeline.schedule(10.0, OFF, now_s=0.0)
    third = timeline.schedule(10.0, DeclareCompletion(), now_s=0.0)
    executed = drain(timeline, 10.0)
    assert [s.command_id for s in executed[1:]] == [first, second, third]


def test_pop_due_returns_only_commands_at_or_before_now():
    timeline = Timeline()
    timeline.schedule(10.0, FIRE_1, now_s=0.0)
    timeline.schedule(10.5, OFF, now_s=0.0)
    assert timeline.pop_due(9.999) is None
    assert [s.time_s for s in drain(timeline, 10.0)] == [10.0]
    assert timeline.next_time_s() == 10.5


def test_current_time_is_accepted_and_past_time_is_rejected():
    timeline = Timeline()
    timeline.schedule(100.0, FIRE_1, now_s=100.0)
    with pytest.raises(CommandError, match="past"):
        timeline.schedule(99.0, FIRE_1, now_s=100.0)


@pytest.mark.parametrize("bad_time", [math.nan, math.inf, -math.inf, "soon", None, True])
def test_invalid_times_are_rejected(bad_time):
    with pytest.raises(CommandError):
        Timeline().schedule(bad_time, FIRE_1, now_s=0.0)


def test_non_command_is_rejected():
    with pytest.raises(CommandError, match="not a command"):
        Timeline().schedule(1.0, "fire", now_s=0.0)


def test_cancel_removes_pending_command_once():
    timeline = Timeline()
    keep = timeline.schedule(10.0, FIRE_1, now_s=0.0)
    drop = timeline.schedule(20.0, OFF, now_s=0.0)
    assert timeline.cancel(drop) is True
    assert timeline.cancel(drop) is False
    assert [s.command_id for s in timeline.pending()] == [keep]


def test_cancel_of_executed_or_unknown_command_returns_false():
    timeline = Timeline()
    executed = timeline.schedule(10.0, FIRE_1, now_s=0.0)
    drain(timeline, 10.0)
    assert timeline.cancel(executed) is False
    assert timeline.cancel(999) is False


def test_identifiers_are_not_reused_after_cancel():
    timeline = Timeline()
    first = timeline.schedule(10.0, FIRE_1, now_s=0.0)
    timeline.cancel(first)
    assert timeline.schedule(10.0, FIRE_1, now_s=0.0) == first + 1


def test_cancel_from_is_inclusive_and_returns_ids_in_execution_order():
    timeline = Timeline()
    early = timeline.schedule(10.0, FIRE_1, now_s=0.0)
    late = timeline.schedule(30.0, OFF, now_s=0.0)
    boundary = timeline.schedule(20.0, OFF, now_s=0.0)
    assert timeline.cancel_from(20.0) == (boundary, late)
    assert [s.command_id for s in timeline.pending()] == [early]


def test_pending_snapshot_is_not_live():
    timeline = Timeline()
    timeline.schedule(10.0, FIRE_1, now_s=0.0)
    snapshot = timeline.pending()
    timeline.cancel_from(0.0)
    assert len(snapshot) == 1


def test_set_propulsion_mode_accepts_mode_names_and_rejects_unknown():
    assert SetPropulsionMode("THRUSTER_2").mode is PropulsionMode.THRUSTER_2
    with pytest.raises(CommandError):
        SetPropulsionMode("THRUSTER_3")


def test_set_heater_requires_bool():
    with pytest.raises(CommandError):
        SetHeater(on=1)
