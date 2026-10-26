"""Helpers shared by the tests of `spacecraft_ops_challenge.judge`."""

import io
import stat
import zipfile
from collections.abc import Mapping

DECLARE_AT_START = """
from spacecraft_ops_challenge import DeclareCompletion, Strategy


class MyStrategy(Strategy):
    def initialize(self, brief, telemetry, commander):
        commander.execute(DeclareCompletion())
"""


def zip_bytes(files: Mapping[str, str | bytes], *, symlinks: Mapping[str, str] | None = None) -> bytes:
    """A ZIP archive with the given regular files and symbolic links."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            archive.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, target)
    return buffer.getvalue()
