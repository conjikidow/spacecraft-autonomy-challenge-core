"""Messages between the trusted case worker and the participant's strategy process.

Messages are JSON objects, each framed by its length as a 4-byte big-endian integer, on a dedicated socket.
Only participant-visible data is encoded here: the mission brief, telemetry, commands, scheduled commands,
command ids, and times. This module imports nothing but the public API of core, so the participant process
can use it without loading the trusted modules of the evaluation.
"""

import json
import selectors
import socket
from dataclasses import asdict
from typing import Any

from spacecraft_ops_challenge import (
    CommandId,
    DeclareCompletion,
    MissionBrief,
    PropulsionMode,
    SafetyLimits,
    ScheduledCommand,
    SetHeater,
    SetPropulsionMode,
    SpacecraftParameters,
    Telemetry,
    ThrusterParameters,
)
from spacecraft_ops_challenge.commands import Command

type JSONValue = bool | int | float | str | list[JSONValue] | dict[str, JSONValue] | None

MAX_MESSAGE_BYTES = 16 * 1024**2
_HEADER_BYTES = 4


class ChannelClosedError(Exception):
    """Raised when the other side closed the connection."""


class ProtocolError(Exception):
    """Raised for a message that does not follow the protocol."""


class MessageTooLargeError(ProtocolError):
    """Raised for a message to send that exceeds `MAX_MESSAGE_BYTES`; nothing is sent."""


class Channel:
    """Framed JSON messages over a connected stream socket."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock

    def send(self, message: dict[str, Any]) -> None:
        """Send one message. Raises `ChannelClosedError` if the other side is gone and `MessageTooLargeError` for
        a message above `MAX_MESSAGE_BYTES`, which is not sent.
        """
        data = json.dumps(message).encode()
        if len(data) > MAX_MESSAGE_BYTES:
            raise MessageTooLargeError(f"message of {len(data)} bytes exceeds the limit of {MAX_MESSAGE_BYTES}")
        try:
            self._sock.sendall(len(data).to_bytes(_HEADER_BYTES, "big") + data)
        except OSError as error:
            raise ChannelClosedError(str(error)) from error

    def receive(self) -> dict[str, Any]:
        """Receive one message. Raises `ChannelClosedError` at the end of the stream and `ProtocolError` for garbage."""
        length = int.from_bytes(self._read(_HEADER_BYTES), "big")
        if length > MAX_MESSAGE_BYTES:
            raise ProtocolError(f"message of {length} bytes exceeds the limit of {MAX_MESSAGE_BYTES}")
        try:
            message = json.loads(self._read(length))
        except (ValueError, RecursionError) as error:
            raise ProtocolError(f"message is not JSON: {error}") from error
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            raise ProtocolError("message is not an object with a type")
        return message

    def readable(self, timeout_s: float) -> bool:
        """Whether a message, the end of the stream, or an error can be read within `timeout_s`."""
        # A selector, unlike select.select, also works for file descriptors of 1024 and above.
        with selectors.DefaultSelector() as selector:
            selector.register(self._sock, selectors.EVENT_READ)
            return bool(selector.select(timeout_s))

    def close(self) -> None:
        """Close the connection."""
        self._sock.close()

    def _read(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            try:
                chunk = self._sock.recv(size - len(data))
            except OSError as error:
                raise ChannelClosedError(str(error)) from error
            if not chunk:
                raise ChannelClosedError("the connection was closed")
            data += chunk
        return bytes(data)


def encode_brief(brief: MissionBrief) -> dict[str, Any]:
    """JSON form of a mission brief."""
    return asdict(brief)


def decode_brief(data: dict[str, Any]) -> MissionBrief:
    """Inverse of `encode_brief`."""
    parameters = dict(data["nominal_parameters"])
    for name in ("thruster_1", "thruster_2"):
        parameters[name] = ThrusterParameters(**parameters[name])
    return MissionBrief(
        target_delta_v_mps=data["target_delta_v_mps"],
        time_limit_s=data["time_limit_s"],
        decision_period_s=data["decision_period_s"],
        limits=SafetyLimits(**data["limits"]),
        nominal_parameters=SpacecraftParameters(**parameters),
    )


def encode_telemetry(telemetry: Telemetry) -> dict[str, Any]:
    """JSON form of telemetry."""
    data = asdict(telemetry)
    data["propulsion_mode"] = telemetry.propulsion_mode.value
    return data


def decode_telemetry(data: dict[str, Any]) -> Telemetry:
    """Inverse of `encode_telemetry`."""
    return Telemetry(**{**data, "propulsion_mode": PropulsionMode(data["propulsion_mode"])})


def encode_command(command: Command) -> dict[str, Any]:
    """JSON form of a command. Raises `TypeError` for anything else."""
    match command:
        case SetPropulsionMode(mode=mode):
            return {"command": "SetPropulsionMode", "mode": mode.value}
        case SetHeater(on=on):
            return {"command": "SetHeater", "on": on}
        case DeclareCompletion():
            return {"command": "DeclareCompletion"}
    raise TypeError(f"not a command: {command!r}")


def decode_command(data: dict[str, Any]) -> Command:
    """Inverse of `encode_command`. Raises `ProtocolError` for an unknown command."""
    match data:
        case {"command": "SetPropulsionMode", "mode": str(mode)}:
            return SetPropulsionMode(PropulsionMode(mode))
        case {"command": "SetHeater", "on": bool(on)}:
            return SetHeater(on)
        case {"command": "DeclareCompletion"}:
            return DeclareCompletion()
    raise ProtocolError(f"unknown command {data!r}")


def encode_scheduled(scheduled: ScheduledCommand) -> dict[str, Any]:
    """JSON form of a scheduled command."""
    command = encode_command(scheduled.command)
    return {"command_id": scheduled.command_id, "time_s": scheduled.time_s, "command": command}


def decode_scheduled(data: dict[str, Any]) -> ScheduledCommand:
    """Inverse of `encode_scheduled`."""
    return ScheduledCommand(CommandId(data["command_id"]), data["time_s"], decode_command(data["command"]))
