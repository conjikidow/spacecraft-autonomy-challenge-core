"""Building and safe extraction of a participant's `submission.zip`.

The archive mirrors the participant's project root. It holds the top-level `submission/` directory with the
entry point `submission/strategy.py:MyStrategy` and any supporting files. It may also hold the project's
`pyproject.toml` at the archive root, which lists the packages the submission needs. Other entries are skipped.
"""

import io
import os
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO

SUBMISSION_DIRNAME = "submission"
PYPROJECT_PATH = "pyproject.toml"
"""Location of the participant project's `pyproject.toml` inside `submission.zip`."""
STRATEGY_PATH = f"{SUBMISSION_DIRNAME}/strategy.py"
STRATEGY_CLASS = "MyStrategy"
DEFAULT_MAX_TOTAL_BYTES = 512 * 1024**2
"""Default limit on the total uncompressed size of the files of a submission."""

_COPY_CHUNK_BYTES = 1024 * 1024
_SKIPPED_DIRNAMES = frozenset({"__pycache__"})
_SKIPPED_SUFFIXES = frozenset({".pyc", ".pyo"})
_ENTRY_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_ENTRY_MODE = stat.S_IFREG | 0o644
_UNIX_SYSTEM = 3


class SubmissionError(ValueError):
    """Raised for an archive or a project that is not a valid submission."""


@dataclass(frozen=True, slots=True)
class Submission:
    """An extracted submission. `root` contains the `submission/` directory."""

    root: Path
    skipped_entries: tuple[str, ...] = ()
    """Archive entries outside `submission/`, which were not extracted, except `pyproject.toml`."""
    pyproject: bytes | None = None
    """Contents of `pyproject.toml` at the archive root, if present. It is not extracted."""

    @property
    def directory(self) -> Path:
        """The extracted `submission/` directory."""
        return self.root / SUBMISSION_DIRNAME

    @property
    def strategy_file(self) -> Path:
        """The entry-point file `submission/strategy.py`."""
        return self.root / STRATEGY_PATH


def _entry_parts(name: str) -> tuple[str, ...]:
    if "\\" in name:
        raise SubmissionError(f"entry {name!r} uses a backslash; archive paths must use '/'")
    path = PurePosixPath(name)
    if path.is_absolute() or (path.parts and ":" in path.parts[0]):
        raise SubmissionError(f"entry {name!r} has an absolute path")
    parts = tuple(part for part in path.parts if part != ".")
    if ".." in parts:
        raise SubmissionError(f"entry {name!r} leaves the archive directory")
    if not parts:
        raise SubmissionError(f"entry {name!r} has an empty path")
    return parts


def _entry_kind(info: zipfile.ZipInfo) -> str:
    """'dir' or 'file'. Symbolic links and other special files are rejected instead of followed."""
    if info.flag_bits & 0x1:
        raise SubmissionError(f"entry {info.filename!r} is encrypted; create the archive without a password")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type == stat.S_IFLNK:
        raise SubmissionError(f"entry {info.filename!r} is a symbolic link; replace it with a regular file")
    if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise SubmissionError(f"entry {info.filename!r} is not a regular file or directory")
    return "dir" if info.is_dir() or file_type == stat.S_IFDIR else "file"


def _raise(error: OSError) -> None:
    raise error


def _submission_files(submission_dir: Path) -> dict[str, Path]:
    """Map archive names to the files under `submission_dir`, rejecting symbolic links instead of following them."""
    files: dict[str, Path] = {}
    for directory, dirnames, filenames in os.walk(submission_dir, onerror=_raise):
        for name in dirnames:
            _check_not_symlink(submission_dir, Path(directory, name))
        for name in filenames:
            path = Path(directory, name)
            archive_name = _check_not_symlink(submission_dir, path)
            if Path(name).suffix in _SKIPPED_SUFFIXES:
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise SubmissionError(f"{archive_name} is not a regular file or directory")
            if "\\" in archive_name:
                raise SubmissionError(f"{archive_name} has a backslash in its name; rename it")
            files[archive_name] = path
        dirnames[:] = [name for name in dirnames if name not in _SKIPPED_DIRNAMES]
    return files


def _check_not_symlink(submission_dir: Path, path: Path) -> str:
    """The archive name of `path`. Raises `SubmissionError` if it is a symbolic link."""
    archive_name = f"{SUBMISSION_DIRNAME}/{path.relative_to(submission_dir).as_posix()}"
    if path.is_symlink():
        raise SubmissionError(f"{archive_name} is a symbolic link; replace it with a regular file or directory")
    return archive_name


def build_submission(project_dir: str | Path, *, max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES) -> bytes:
    """Pack the `submission/` directory of `project_dir` and its `pyproject.toml` into a `submission.zip`.

    Files under `submission/` keep their paths relative to `project_dir`; `__pycache__` directories and
    `.pyc` and `.pyo` files are left out. `pyproject.toml` is added at the archive root if it is a regular
    file. The archive is deterministic: the same contents always give the same bytes, whatever the
    timestamps and permissions of the files.
    Raises `SubmissionError` for a missing `submission/strategy.py`, a symbolic link, which is rejected instead
    of followed, or files whose total size exceeds `max_total_bytes`, and `OSError` for a file that cannot be
    read. `extract_submission` accepts every archive this function returns.
    """
    project_dir = Path(project_dir)
    submission_dir = project_dir / SUBMISSION_DIRNAME
    if submission_dir.is_symlink():
        raise SubmissionError(f"{SUBMISSION_DIRNAME}/ is a symbolic link; replace it with a directory")
    if not submission_dir.is_dir():
        raise SubmissionError(f"{project_dir} has no {SUBMISSION_DIRNAME}/ directory")
    files = _submission_files(submission_dir)
    if STRATEGY_PATH not in files:
        raise SubmissionError(f"{STRATEGY_PATH} is missing")
    pyproject = project_dir / PYPROJECT_PATH
    if pyproject.is_symlink():
        raise SubmissionError(f"{PYPROJECT_PATH} is a symbolic link; replace it with a regular file")
    if pyproject.is_file():
        files[PYPROJECT_PATH] = pyproject

    # Checked before anything is read, so that an oversized file is rejected without loading it.
    if sum(path.lstat().st_size for path in files.values()) > max_total_bytes:
        raise SubmissionError(f"the submission files exceed {max_total_bytes} bytes")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in sorted(files):
            data = files[name].read_bytes()
            info = zipfile.ZipInfo(name, date_time=_ENTRY_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = _UNIX_SYSTEM
            info.external_attr = _ENTRY_MODE << 16
            archive.writestr(info, data)
    return buffer.getvalue()


def _write(zip_file: zipfile.ZipFile, planned: list[tuple[zipfile.ZipInfo, tuple[str, ...], str]], root: Path) -> None:
    for info, parts, kind in planned:
        target = root.joinpath(*parts)
        if not target.resolve().is_relative_to(root):
            raise SubmissionError(f"entry {info.filename!r} leaves the extraction directory")
        if kind == "dir":
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zip_file.open(info) as source, target.open("xb") as sink:
            while chunk := source.read(_COPY_CHUNK_BYTES):
                sink.write(chunk)


def _clear(directory: Path) -> None:
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def extract_submission(
    archive: str | Path | IO[bytes],
    destination: Path,
    *,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> Submission:
    """Validate `archive` and extract its `submission/` directory into the empty directory `destination`.

    Every entry is validated before anything is written: absolute paths, `..` components, symbolic links,
    and special files are rejected. Entries outside `submission/` are skipped; `pyproject.toml` at the archive
    root is read into `Submission.pyproject` instead.
    Raises `SubmissionError` for an invalid archive.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError(f"destination {destination} is not empty")
    root = destination.resolve()
    try:
        with zipfile.ZipFile(archive) as zip_file:
            planned: list[tuple[zipfile.ZipInfo, tuple[str, ...], str]] = []
            skipped: list[str] = []
            files: set[tuple[str, ...]] = set()
            total_bytes = 0
            pyproject_info = None
            for info in zip_file.infolist():
                parts = _entry_parts(info.filename)
                kind = _entry_kind(info)
                is_pyproject = kind == "file" and "/".join(parts) == PYPROJECT_PATH
                if not is_pyproject and (parts[0] != SUBMISSION_DIRNAME or (kind == "file" and len(parts) == 1)):
                    skipped.append(info.filename)
                    continue
                if kind == "file":
                    if parts in files:
                        raise SubmissionError(f"entry {info.filename!r} appears more than once")
                    files.add(parts)
                total_bytes += info.file_size
                if total_bytes > max_total_bytes:
                    raise SubmissionError(f"the extracted files would exceed {max_total_bytes} bytes")
                if is_pyproject:
                    pyproject_info = info
                else:
                    planned.append((info, parts, kind))
            directories = {parts[:depth] for _, parts, _ in planned for depth in range(1, len(parts))}
            directories |= {parts for _, parts, kind in planned if kind == "dir"}
            conflicts = sorted("/".join(parts) for parts in files & directories)
            if conflicts:
                raise SubmissionError(f"entry {conflicts[0]!r} is both a file and a directory")
            if tuple(STRATEGY_PATH.split("/")) not in files:
                raise SubmissionError(
                    f"the archive has no {STRATEGY_PATH}; zip the {SUBMISSION_DIRNAME}/ directory itself, "
                    f"so that its files are under {SUBMISSION_DIRNAME}/ in the archive"
                )
            try:
                _write(zip_file, planned, root)
                pyproject = None if pyproject_info is None else zip_file.read(pyproject_info)
            except BaseException:
                # Corrupt contents, such as a bad checksum, show only while reading: leave nothing behind.
                _clear(root)
                raise
    except zipfile.BadZipFile as error:
        raise SubmissionError(f"not a valid ZIP archive: {error}") from error
    except (FileExistsError, IsADirectoryError, NotADirectoryError) as error:
        raise SubmissionError(f"conflicting archive entries: {error}") from error
    return Submission(root=root, skipped_entries=tuple(skipped), pyproject=pyproject)
