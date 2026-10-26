"""Participant strategy process: runs `MyStrategy` for one case, apart from the trusted simulator.

The trusted case worker starts this process with the participant's packages first on the import path and
talks to it over a dedicated socket. The process only ever receives what a strategy may see: the mission
brief, telemetry, and the results of commander requests. It never imports the case definitions.

    python -P -m spacecraft_ops_challenge.judge.participant SOCKET_FD SUBMISSION_ROOT [OVERLAY]
"""

import operator
import os
import site
import socket
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from spacecraft_ops_challenge import CommandError, CommandId, ScheduledCommand, Strategy
from spacecraft_ops_challenge.cli import load_strategy
from spacecraft_ops_challenge.commands import Command
from spacecraft_ops_challenge.judge.protocol import (
    Channel,
    ChannelClosedError,
    JSONValue,
    MessageTooLargeError,
    decode_brief,
    decode_scheduled,
    decode_telemetry,
    encode_command,
)
from spacecraft_ops_challenge.judge.submission import STRATEGY_CLASS, STRATEGY_PATH

_CLOSED = "this commander is only valid during the callback it was passed to"


def _command_id_argument(command_id: object) -> int | float | None:
    """A JSON-compatible id that core compares exactly as it would the original, or `None` if none can match.

    Core finds the command by `==`, so ids of other numeric types, such as NumPy integers, `Decimal`, or
    `Fraction`, are sent as the `int` they compare equal to.
    """
    if isinstance(command_id, int | float):
        return command_id
    for convert in (operator.index, int, _real_part):
        try:
            candidate = convert(command_id)  # type: ignore[arg-type]
        except (TypeError, ValueError, ArithmeticError):
            continue
        if candidate is not None and command_id == candidate:
            return candidate
    return None


def _real_part(value: object) -> int | None:
    """The integer value of a complex number without imaginary part, or `None`."""
    return int(value.real) if isinstance(value, complex) and value.imag == 0 and value.real.is_integer() else None


def _time_argument(time_s: object) -> float | int | str:
    """A JSON-compatible form of a time argument that core validates exactly as it would the original."""
    if isinstance(time_s, bool | int | float | str):
        return time_s
    try:
        return float(time_s)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise CommandError(f"time must be a number of seconds, got {time_s!r}") from None


class RemoteCommander:
    """`Commander` that forwards every request to the commander of the trusted simulator.

    Like the core commander, it is valid only during the callback it was passed to.
    """

    def __init__(self, channel: Channel, now_s: float) -> None:
        self._channel: Channel | None = channel
        self._now_s = now_s

    @property
    def now_s(self) -> float:
        """Current simulation time in seconds."""
        self._open_channel()
        return self._now_s

    def schedule(self, time_s: float, command: Command) -> CommandId:
        """Register `command` for execution at `time_s`, which must not be earlier than `now_s`."""
        channel = self._open_channel()
        try:
            encoded = encode_command(command)
        except TypeError as error:
            raise CommandError(str(error)) from None
        return CommandId(self._call(channel, "schedule", time_s=_time_argument(time_s), command=encoded))

    def execute(self, command: Command) -> CommandId:
        """Register `command` for immediate execution, equivalent to `schedule(now_s, command)`."""
        return self.schedule(self._now_s, command)

    def cancel(self, command_id: CommandId) -> bool:
        """Cancel a pending command. Returns `False` if it is unknown, executed, or already canceled."""
        channel = self._open_channel()
        argument = _command_id_argument(command_id)
        if argument is None:
            return False
        return self._call(channel, "cancel", command_id=argument)

    def cancel_from(self, time_s: float) -> tuple[CommandId, ...]:
        """Cancel all pending commands scheduled at or after `time_s` and return their identifiers."""
        channel = self._open_channel()
        return tuple(CommandId(i) for i in self._call(channel, "cancel_from", time_s=_time_argument(time_s)))

    def pending(self) -> tuple[ScheduledCommand, ...]:
        """Pending commands in execution order."""
        channel = self._open_channel()
        return tuple(decode_scheduled(s) for s in self._call(channel, "pending"))

    def close(self) -> None:
        """End the commanding window; every member raises `CommandError` afterwards."""
        self._channel = None

    def _open_channel(self) -> Channel:
        if self._channel is None:
            raise CommandError(_CLOSED)
        return self._channel

    @staticmethod
    def _call(channel: Channel, method: str, **arguments: JSONValue) -> JSONValue:
        try:
            channel.send({"type": "call", "method": method, **arguments})
        except MessageTooLargeError as error:  # an argument that core would also reject, but huge
            raise CommandError(f"the request is too large: {error}") from None
        reply = channel.receive()
        if reply["type"] == "command_error":
            raise CommandError(reply["message"])
        if reply["type"] != "return":
            raise RuntimeError(f"unexpected reply from the trusted worker: {reply['type']!r}")
        return reply["value"]


MAX_DETAIL_CHARS = 100_000
"""Tracebacks sent to the trusted worker keep at most this many characters, from the start and the end."""


def _detail(error: BaseException) -> str:
    """The traceback of `error`, shortened so that its message always fits the protocol's size limit."""
    text = "".join(traceback.format_exception(error))
    if len(text) <= MAX_DETAIL_CHARS:
        return text
    half = MAX_DETAIL_CHARS // 2
    return f"{text[:half]}\n... [{len(text) - 2 * half} characters omitted] ...\n{text[-half:]}"


def _failure(kind: str, error: BaseException) -> dict[str, Any]:
    return {"type": "failed", "kind": kind, "detail": _detail(error)}


def _callback(channel: Channel, strategy: Strategy, message: dict[str, Any]) -> dict[str, Any]:
    """Run one strategy callback and return the message that reports how it ended."""
    commander = RemoteCommander(channel, message["now_s"])
    try:
        if message["type"] == "initialize":
            strategy.initialize(decode_brief(message["brief"]), decode_telemetry(message["telemetry"]), commander)
        else:
            strategy.update(decode_telemetry(message["telemetry"]), commander)
    except CommandError as error:
        return _failure("command_error", error)
    except Exception as error:
        return _failure("exception", error)
    except BaseException as error:  # SystemExit, KeyboardInterrupt, and anything else that is not an Exception
        return _failure("exit", error)
    finally:
        commander.close()
    return {"type": "done"}


def serve(channel: Channel, submission_root: Path) -> None:
    """Load a fresh strategy, report whether that worked, and run callbacks until the trusted worker disconnects."""
    try:
        strategy = load_strategy(f"{submission_root / STRATEGY_PATH}:{STRATEGY_CLASS}")
    except BaseException as error:  # StrategyLoadError, or SystemExit and the like raised while importing
        channel.send({"type": "load_error", "detail": _detail(error)})
        return
    channel.send({"type": "ready"})
    while True:
        try:
            message = channel.receive()
        except ChannelClosedError:
            return
        if message["type"] not in ("initialize", "update"):
            raise RuntimeError(f"unexpected message from the trusted worker: {message['type']!r}")
        report = _callback(channel, strategy, message)
        channel.send(report)
        if report.get("kind") == "exit":
            return


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point: serve one case, then exit the process at once.

    Exiting at once keeps threads or exit handlers that the participant's code left behind from delaying
    the end of the case.
    """
    fd, submission_root, *overlay = sys.argv[1:] if argv is None else argv
    if overlay:
        # Already first on the path through PYTHONPATH; this also processes the overlay's .pth files.
        site.addsitedir(overlay[0])
    sock = socket.socket(fileno=int(fd))
    # Keep processes that the strategy starts from holding the trusted worker's end of the connection open.
    sock.set_inheritable(False)
    channel = Channel(sock)
    try:
        serve(channel, Path(submission_root))
    except ChannelClosedError:
        pass
    except BaseException:
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
