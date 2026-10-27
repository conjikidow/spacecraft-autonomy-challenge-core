import json
import socket

import pytest

from spacecraft_ops_challenge import (
    CommandId,
    DeclareCompletion,
    PropulsionMode,
    ScheduledCommand,
    SetHeater,
    SetPropulsionMode,
    Telemetry,
)
from spacecraft_ops_challenge.challenge import problem
from spacecraft_ops_challenge.judge import protocol
from spacecraft_ops_challenge.judge.protocol import (
    MAX_MESSAGE_BYTES,
    Channel,
    ChannelClosedError,
    ProtocolError,
    decode_brief,
    decode_command,
    decode_scheduled,
    decode_telemetry,
    encode_brief,
    encode_command,
    encode_scheduled,
    encode_telemetry,
)


@pytest.fixture
def channels():
    left, right = socket.socketpair()
    with left, right:
        yield Channel(left), Channel(right)


def test_messages_round_trip(channels):
    sender, receiver = channels
    message = {"type": "update", "value": [1, 2.5, None, True, {"nested": "x"}], "nan": float("inf")}
    sender.send(message)
    sender.send({"type": "second"})
    assert receiver.receive() == message
    assert receiver.receive() == {"type": "second"}


def test_closed_channel(channels):
    sender, receiver = channels
    sender.close()
    with pytest.raises(ChannelClosedError):
        receiver.receive()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ((MAX_MESSAGE_BYTES + 1).to_bytes(4, "big"), "exceeds the limit"),
        (b"\x00\x00\x00\x03{x}", "not JSON"),
        (b"\x00\x00\x00\x02[]", "not an object with a type"),
        (b'\x00\x00\x00\x0b{"type": 1}', "not an object with a type"),
    ],
)
def test_malformed_messages(data, message):
    left, right = socket.socketpair()
    with left, right:
        left.sendall(data)
        with pytest.raises(ProtocolError, match=message):
            Channel(right).receive()


def test_brief_and_telemetry_round_trip_exactly():
    brief = problem().brief()
    assert decode_brief(json.loads(json.dumps(encode_brief(brief)))) == brief
    telemetry = Telemetry(0.1, 1 / 3, -7.25, 79.999, -0.0002, True, PropulsionMode.THRUSTER_2)
    assert decode_telemetry(json.loads(json.dumps(encode_telemetry(telemetry)))) == telemetry
    assert encode_telemetry(telemetry)["propulsion_mode"] == "THRUSTER_2"


@pytest.mark.parametrize(
    "command",
    [SetPropulsionMode(PropulsionMode.THRUSTER_1), SetHeater(on=False), DeclareCompletion()],
)
def test_commands_round_trip(command):
    assert decode_command(json.loads(json.dumps(encode_command(command)))) == command
    scheduled = ScheduledCommand(CommandId(3), 120.5, command)
    assert decode_scheduled(json.loads(json.dumps(encode_scheduled(scheduled)))) == scheduled


def test_unknown_commands():
    with pytest.raises(TypeError, match="not a command: 'heater on'"):
        encode_command("heater on")
    with pytest.raises(ProtocolError, match="unknown command"):
        decode_command({"command": "SelfDestruct"})
    with pytest.raises(ProtocolError, match="unknown command"):
        decode_command({"command": "SetHeater", "on": "yes"})


def test_messages_above_the_limit_are_not_sent(monkeypatch):
    sender, receiver = socket.socketpair()
    with sender, receiver:
        monkeypatch.setattr(protocol, "MAX_MESSAGE_BYTES", 10)
        with pytest.raises(protocol.MessageTooLargeError):
            protocol.Channel(sender).send({"type": "x" * 20})
        assert not protocol.Channel(receiver).readable(0.01)
