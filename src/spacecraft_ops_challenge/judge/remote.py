"""Trusted side of the participant strategy process: start it and drive it as a core `Strategy`.

The trusted case worker keeps the case, its scenario, and the simulator. The participant's code runs in a child
process that only receives participant-visible data over a dedicated socket (see `protocol`). Its standard
output and standard error are those of the case worker, which the runner captures.
"""

import os
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

import spacecraft_ops_challenge
from spacecraft_ops_challenge import Commander, CommandError, MissionBrief, Strategy, Telemetry
from spacecraft_ops_challenge.judge.protocol import (
    Channel,
    ChannelClosedError,
    JSONValue,
    ProtocolError,
    decode_command,
    encode_brief,
    encode_scheduled,
    encode_telemetry,
)

PACKAGE_ROOT = str(Path(spacecraft_ops_challenge.__file__).resolve().parent.parent)
"""Import root of the core package, appended (not prepended) to the import path of the case processes."""

_PARTICIPANT_BOOTSTRAP = (
    "import sys; sys.path.append(sys.argv.pop(1)); "
    "from spacecraft_ops_challenge.judge.participant import main; main(sys.argv[1:])"
)
_EXIT_WAIT_S = 5.0
_POLL_INTERVAL_S = 0.05


class ParticipantError(Exception):
    """The participant's callback raised an exception; core ends the run with `STRATEGY_ERROR`."""


class ParticipantCommandError(CommandError):
    """The participant's callback raised `CommandError`; core ends the run with `INVALID_COMMAND`."""


class ParticipantStopError(BaseException):
    """The participant process stopped, exited, or broke the protocol. Core does not catch it."""


class ParticipantProcess:
    """A participant strategy process for one case, connected through a socket pair."""

    def __init__(self, submission_root: Path, env: Mapping[str, str], overlay: Path | None = None) -> None:
        trusted, participant = socket.socketpair()
        command = [sys.executable, "-P", "-c", _PARTICIPANT_BOOTSTRAP, PACKAGE_ROOT]
        command += [str(participant.fileno()), str(submission_root)]
        if overlay is not None:
            command.append(str(overlay))
        with participant:
            self.process = subprocess.Popen(
                command,
                cwd=submission_root,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                pass_fds=(participant.fileno(),),
            )
        self.channel = Channel(trusted)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Disconnect and stop the process."""
        self.channel.close()
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()

    def finish(self) -> float | None:
        """Disconnect, let the process exit on its own, and return its CPU time in seconds.

        The CPU time is the user plus system time that `os.wait4` reports when it reaps the process. It is
        `None` if the process does not exit within a few seconds, was already reaped, or the platform has no
        `os.wait4`; the process is then left for `close` to stop.
        """
        self.channel.close()
        if not hasattr(os, "wait4"):
            return None
        deadline = time.monotonic() + _EXIT_WAIT_S
        while self.process.returncode is None:
            try:
                pid, status, usage = os.wait4(self.process.pid, os.WNOHANG)
            except ChildProcessError:
                return None
            if pid:
                self.process.returncode = os.waitstatus_to_exitcode(status)
                return usage.ru_utime + usage.ru_stime
            if time.monotonic() >= deadline:
                return None
            time.sleep(_POLL_INTERVAL_S)
        return None

    def receive(self) -> dict[str, Any]:
        """Next message from the process. Raises `ParticipantStopError` if it is gone or breaks the protocol.

        The process is watched while waiting, because a process that it forked may keep the connection open
        after it exited.
        """
        while not self.channel.readable(_POLL_INTERVAL_S):
            if self.process.poll() is not None:
                raise ParticipantStopError(self._exit_description())
        try:
            return self.channel.receive()
        except ChannelClosedError:
            raise ParticipantStopError(self._exit_description()) from None
        except ProtocolError as error:
            raise ParticipantStopError(f"the strategy process broke the protocol: {error}") from None

    def send(self, message: dict[str, Any]) -> None:
        """Send a message. Raises `ParticipantStopError` if the process is gone."""
        try:
            self.channel.send(message)
        except ChannelClosedError:
            raise ParticipantStopError(self._exit_description()) from None

    def wait_ready(self) -> str | None:
        """Wait until the strategy is loaded. Returns `None`, or the traceback if it could not be loaded."""
        message = self.receive()
        if message["type"] == "ready":
            return None
        if message["type"] == "load_error":
            return str(message["detail"])
        raise ParticipantStopError(f"the strategy process sent an unexpected {message['type']!r} message")

    def _exit_description(self) -> str:
        try:
            returncode = self.process.wait(_EXIT_WAIT_S)
        except subprocess.TimeoutExpired:
            return "the strategy process closed its connection"
        return f"the strategy process exited with status {returncode}"


def _serve_call(commander: Commander, message: dict[str, Any]) -> JSONValue:
    """Perform one commander request of the participant on the real commander."""
    match message.get("method"):
        case "schedule":
            return commander.schedule(message["time_s"], decode_command(message["command"]))
        case "cancel":
            return commander.cancel(message["command_id"])
        case "cancel_from":
            return list(commander.cancel_from(message["time_s"]))
        case "pending":
            return [encode_scheduled(scheduled) for scheduled in commander.pending()]
    raise ProtocolError(f"unknown commander method {message.get('method')!r}")


class RemoteStrategy(Strategy):
    """Core `Strategy` whose callbacks run in a participant process.

    While a callback runs, the participant's commander requests are performed on the commander that core
    passed to the callback, so the timeline semantics are exactly those of core.
    """

    def __init__(self, participant: ParticipantProcess) -> None:
        self._participant = participant

    def initialize(self, brief: MissionBrief, telemetry: Telemetry, commander: Commander) -> None:
        """Run the participant's `initialize` with the brief and the initial telemetry."""
        message = {"brief": encode_brief(brief), "telemetry": encode_telemetry(telemetry)}
        self._callback("initialize", message, commander)

    def update(self, telemetry: Telemetry, commander: Commander) -> None:
        """Run the participant's `update` with the latest telemetry."""
        self._callback("update", {"telemetry": encode_telemetry(telemetry)}, commander)

    def _callback(self, kind: str, message: dict[str, Any], commander: Commander) -> None:
        participant = self._participant
        participant.send({"type": kind, "now_s": commander.now_s, **message})
        while True:
            reply = participant.receive()
            if reply["type"] == "call":
                try:
                    participant.send({"type": "return", "value": _serve_call(commander, reply)})
                except CommandError as error:
                    participant.send({"type": "command_error", "message": str(error)})
                except (ProtocolError, KeyError, TypeError, ValueError) as error:
                    raise ParticipantStopError(f"the strategy process sent a malformed request: {error!r}") from None
            elif reply["type"] == "done":
                return
            elif reply["type"] == "failed":
                self._raise_failure(reply)
            else:
                raise ParticipantStopError(f"the strategy process sent an unexpected {reply['type']!r} message")

    @staticmethod
    def _raise_failure(reply: dict[str, Any]) -> None:
        detail = str(reply.get("detail", ""))
        match reply.get("kind"):
            case "command_error":
                raise ParticipantCommandError(f"the strategy raised CommandError:\n{detail}") from None
            case "exception":
                raise ParticipantError(f"the strategy raised an exception:\n{detail}") from None
            case "exit":
                raise ParticipantStopError(f"the strategy stopped the run:\n{detail}") from None
        raise ParticipantStopError(f"the strategy process reported an unknown failure {reply.get('kind')!r}")
