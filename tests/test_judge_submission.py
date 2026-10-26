import io
import os
import stat
import zipfile
from pathlib import Path

import pytest
from judge_support import DECLARE_AT_START, zip_bytes

from spacecraft_ops_challenge.judge.submission import SubmissionError, build_submission, extract_submission


def extract(tmp_path, archive, **kwargs):
    return extract_submission(io.BytesIO(archive), tmp_path / "out", **kwargs)


def extracted_files(root):
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def test_valid_submission_with_supporting_files(tmp_path):
    archive = zip_bytes(
        {
            "submission/strategy.py": DECLARE_AT_START,
            "submission/planner/domain.pddl": "(define (domain d))",
            "submission/model.anml": "action a();",
            "submission/weights.bin": bytes(range(256)),
            "submission/config/settings.yaml": "a: 1\n",
            "__MACOSX/submission/._strategy.py": b"\0",
            "README.txt": "notes",
        }
    )
    submission = extract(tmp_path, archive)
    assert submission.root == (tmp_path / "out").resolve()
    assert submission.strategy_file.read_text() == DECLARE_AT_START
    assert (submission.directory / "weights.bin").read_bytes() == bytes(range(256))
    assert extracted_files(submission.root) == [
        "submission/config/settings.yaml",
        "submission/model.anml",
        "submission/planner/domain.pddl",
        "submission/strategy.py",
        "submission/weights.bin",
    ]
    assert submission.skipped_entries == ("__MACOSX/submission/._strategy.py", "README.txt")


def test_directory_entries_are_accepted(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("submission/", "")
        archive.writestr("submission/data/", "")
        archive.writestr("submission/strategy.py", DECLARE_AT_START)
    submission = extract(tmp_path, buffer.getvalue())
    assert (submission.directory / "data").is_dir()


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ({"strategy.py": DECLARE_AT_START}, "no submission/strategy.py"),
        ({"submission/main.py": DECLARE_AT_START}, "no submission/strategy.py"),
        ({"submission/strategy.py/": ""}, "no submission/strategy.py"),
        ({"submission/strategy.py": "", "submission/../../escape.py": ""}, "leaves the archive directory"),
        ({"submission/strategy.py": "", "../escape.py": ""}, "leaves the archive directory"),
        ({"submission/strategy.py": "", "/etc/escape.py": ""}, "absolute path"),
        ({"submission/strategy.py": "", "C:/escape.py": ""}, "absolute path"),
        ({"submission/strategy.py": "", "submission\\..\\escape.py": ""}, "backslash"),
    ],
)
def test_invalid_archives_are_rejected_before_anything_is_written(tmp_path, files, message):
    with pytest.raises(SubmissionError, match=message):
        extract(tmp_path, zip_bytes(files))
    assert not any((tmp_path / "out").iterdir())
    assert not (tmp_path / "escape.py").exists()


def test_symbolic_links_are_rejected_instead_of_followed(tmp_path):
    (tmp_path / "secret.txt").write_text("secret")
    archive = zip_bytes({"submission/strategy.py": ""}, symlinks={"submission/link.txt": "../../secret.txt"})
    with pytest.raises(SubmissionError, match="symbolic link"):
        extract(tmp_path, archive)
    assert not any((tmp_path / "out").iterdir())


def test_symbolic_links_outside_submission_are_rejected_too(tmp_path):
    archive = zip_bytes({"submission/strategy.py": ""}, symlinks={"other/link": "/etc/passwd"})
    with pytest.raises(SubmissionError, match="symbolic link"):
        extract(tmp_path, archive)


def test_duplicate_entries_are_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("submission/strategy.py", "a")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("submission/strategy.py", "b")
    with pytest.raises(SubmissionError, match="more than once"):
        extract(tmp_path, buffer.getvalue())


def test_size_limit(tmp_path):
    archive = zip_bytes({"submission/strategy.py": "", "submission/big.bin": b"0" * 1000})
    with pytest.raises(SubmissionError, match="exceed 999 bytes"):
        extract(tmp_path, archive, max_total_bytes=999)


def test_not_a_zip_archive(tmp_path):
    with pytest.raises(SubmissionError, match="not a valid ZIP archive"):
        extract(tmp_path, b"not a zip")


def test_destination_must_be_empty(tmp_path):
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "existing").write_text("")
    with pytest.raises(ValueError, match="not empty"):
        extract(tmp_path, zip_bytes({"submission/strategy.py": ""}))


def test_pyproject_is_read_but_not_extracted(tmp_path):
    archive = zip_bytes(
        {
            "submission/strategy.py": DECLARE_AT_START,
            "submission/pyproject.toml": "[tool.local]\n",
            "pyproject.toml": "[project]\ndependencies = []\n",
            "uv.lock": "x",
            "other/pyproject.toml": "x",
        }
    )
    submission = extract(tmp_path, archive)
    assert submission.pyproject == b"[project]\ndependencies = []\n"
    assert submission.skipped_entries == ("uv.lock", "other/pyproject.toml")
    assert extracted_files(submission.root) == ["submission/pyproject.toml", "submission/strategy.py"]


def test_a_pyproject_directory_entry_is_skipped(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("submission/strategy.py", "")
        archive.writestr("pyproject.toml/", "")
    submission = extract(tmp_path, buffer.getvalue())
    assert submission.pyproject is None
    assert submission.skipped_entries == ("pyproject.toml/",)


def test_archive_without_pyproject(tmp_path):
    assert extract(tmp_path, zip_bytes({"submission/strategy.py": ""})).pyproject is None


def test_encrypted_entries_are_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("submission/strategy.py")
        archive.writestr(info, DECLARE_AT_START)
    data = bytearray(buffer.getvalue())
    # Set the encryption flag in the local file header and in the central directory entry.
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = data.index(signature) + offset
        data[position] |= 0x1
    with pytest.raises(SubmissionError, match="encrypted"):
        extract(tmp_path, bytes(data))
    assert not any((tmp_path / "out").iterdir())


def test_pyproject_counts_toward_the_size_limit(tmp_path):
    archive = zip_bytes({"submission/strategy.py": "", "pyproject.toml": "x" * 1000})
    with pytest.raises(SubmissionError, match="exceed 999 bytes"):
        extract(tmp_path, archive, max_total_bytes=999)


def test_duplicate_pyprojects_are_rejected(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("submission/strategy.py", "")
        archive.writestr("pyproject.toml", "a")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("pyproject.toml", "b")
    with pytest.raises(SubmissionError, match="more than once"):
        extract(tmp_path, buffer.getvalue())


def test_entries_that_are_both_a_file_and_a_directory_are_rejected_before_writing(tmp_path):
    archive = zip_bytes({"submission/strategy.py": "", "submission/data": "x", "submission/data/inner.txt": "y"})
    with pytest.raises(SubmissionError, match="'submission/data' is both a file and a directory"):
        extract(tmp_path, archive)
    assert not any((tmp_path / "out").iterdir())


@pytest.mark.parametrize("directory_first", [True, False])
def test_a_file_and_a_directory_entry_of_the_same_name_are_rejected(tmp_path, directory_first):
    buffer = io.BytesIO()
    entries = [("submission/data/", ""), ("submission/data", "x")]
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("submission/strategy.py", "")
        for name, content in entries if directory_first else reversed(entries):
            archive.writestr(name, content)
    with pytest.raises(SubmissionError, match="'submission/data' is both a file and a directory"):
        extract(tmp_path, buffer.getvalue())
    assert not any((tmp_path / "out").iterdir())


def test_corrupt_contents_leave_nothing_behind(tmp_path):
    payload = b"x" * 5000
    archive = bytearray(
        zip_bytes(
            {"submission/a.txt": "first", "submission/strategy.py": DECLARE_AT_START, "submission/z.bin": payload}
        )
    )
    # Flip a byte of the last file's stored data: the headers stay valid, but its checksum no longer matches.
    position = archive.rindex(payload[:100]) + 10
    archive[position] ^= 0xFF
    with pytest.raises(SubmissionError, match="not a valid ZIP archive: Bad CRC-32"):
        extract(tmp_path, bytes(archive))
    assert not any((tmp_path / "out").iterdir())


def test_corrupt_compressed_data_leaves_nothing_behind(tmp_path):
    payload = bytes(range(256)) * 40
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("submission/strategy.py", DECLARE_AT_START)
        zip_file.writestr("submission/z.bin", payload)
    archive = bytearray(buffer.getvalue())
    # Garble the start of the last entry's compressed stream, so that decompressing it fails.
    with zipfile.ZipFile(io.BytesIO(bytes(archive))) as zip_file:
        info = zip_file.getinfo("submission/z.bin")
    data_start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    archive[data_start : data_start + 8] = b"\xff" * 8
    with pytest.raises(SubmissionError, match="not a valid ZIP archive"):
        extract(tmp_path, bytes(archive))
    assert not any((tmp_path / "out").iterdir())


def test_build_size_limit_is_checked_on_the_data_read(tmp_path, monkeypatch):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START, "grows.bin": b"x"})
    read_bytes = Path.read_bytes

    def grown(self):
        return read_bytes(self) * 1000 if self.name == "grows.bin" else read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", grown)
    with pytest.raises(SubmissionError, match="exceed"):
        build_submission(project, max_total_bytes=500)


def make_project(root, files, *, pyproject=None):
    """A project directory with the given files relative to `submission/` and an optional `pyproject.toml`."""
    for name, content in files.items():
        path = root / "submission" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)
    if pyproject is not None:
        (root / "pyproject.toml").write_text(pyproject)
    return root


def archive_names(archive):
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
        return zip_file.namelist()


def test_built_archive_round_trips(tmp_path):
    project = make_project(
        tmp_path / "project",
        {"strategy.py": DECLARE_AT_START, "planner/domain.pddl": "(define (domain d))", "weights.bin": bytes(256)},
        pyproject="[project]\nname = 'p'\n",
    )
    (project / "README.md").write_text("notes")
    archive = build_submission(project)
    assert archive_names(archive) == [
        "pyproject.toml",
        "submission/planner/domain.pddl",
        "submission/strategy.py",
        "submission/weights.bin",
    ]
    submission = extract(tmp_path, archive)
    assert submission.strategy_file.read_text() == DECLARE_AT_START
    assert (submission.directory / "weights.bin").read_bytes() == bytes(256)
    assert submission.pyproject == b"[project]\nname = 'p'\n"
    assert submission.skipped_entries == ()
    assert extracted_files(submission.root) == [
        "submission/planner/domain.pddl",
        "submission/strategy.py",
        "submission/weights.bin",
    ]


def test_built_archive_is_deterministic(tmp_path):
    files = {"strategy.py": DECLARE_AT_START, "b/data.txt": "b", "a.txt": "a"}
    first = make_project(tmp_path / "first", files, pyproject="[project]\n")
    second = make_project(tmp_path / "second", dict(reversed(files.items())), pyproject="[project]\n")
    archive = build_submission(first)
    assert build_submission(first) == archive
    for path in [*second.rglob("*"), second]:
        os.utime(path, (1_000_000_000, 1_000_000_000))
    (second / "submission" / "a.txt").chmod(0o600)
    assert build_submission(second) == archive
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
        for info in zip_file.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_DEFLATED
            assert info.external_attr >> 16 == stat.S_IFREG | 0o644


def test_bytecode_caches_are_left_out(tmp_path):
    project = make_project(
        tmp_path / "project",
        {
            "strategy.py": DECLARE_AT_START,
            "__pycache__/strategy.cpython-312.pyc": b"\0",
            "helpers/__pycache__/util.cpython-312.pyc": b"\0",
            "helpers/util.py": "",
            "helpers/old.pyc": b"\0",
            "helpers/old.pyo": b"\0",
        },
    )
    assert archive_names(build_submission(project)) == ["submission/helpers/util.py", "submission/strategy.py"]


def test_a_symbolic_link_to_the_submission_directory_is_rejected(tmp_path):
    make_project(tmp_path / "real", {"strategy.py": DECLARE_AT_START})
    (tmp_path / "project").mkdir()
    (tmp_path / "project" / "submission").symlink_to(tmp_path / "real" / "submission")
    with pytest.raises(SubmissionError, match=r"submission/ is a symbolic link"):
        build_submission(tmp_path / "project")


@pytest.mark.parametrize("target_is_directory", [True, False])
def test_symbolic_links_inside_the_submission_are_rejected(tmp_path, target_is_directory):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START})
    target = tmp_path / "outside"
    if target_is_directory:
        target.mkdir()
    else:
        target.write_text("secret")
    (project / "submission" / "nested").mkdir()
    (project / "submission" / "nested" / "link").symlink_to(target, target_is_directory=target_is_directory)
    with pytest.raises(SubmissionError, match=r"submission/nested/link is a symbolic link"):
        build_submission(project)


def test_a_symbolic_link_as_the_strategy_is_rejected(tmp_path):
    project = make_project(tmp_path / "project", {"real.py": DECLARE_AT_START})
    (project / "submission" / "strategy.py").symlink_to(project / "submission" / "real.py")
    with pytest.raises(SubmissionError, match=r"submission/strategy.py is a symbolic link"):
        build_submission(project)


@pytest.mark.parametrize("files", [{"main.py": DECLARE_AT_START}, {"strategy.py/inner.py": ""}])
def test_a_missing_strategy_is_rejected(tmp_path, files):
    project = make_project(tmp_path / "project", files)
    with pytest.raises(SubmissionError, match=r"submission/strategy.py is missing"):
        build_submission(project)


def test_a_missing_submission_directory_is_rejected(tmp_path):
    with pytest.raises(SubmissionError, match=r"has no submission/ directory"):
        build_submission(tmp_path)


def test_a_missing_pyproject_is_left_out(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START})
    archive = build_submission(project)
    assert archive_names(archive) == ["submission/strategy.py"]
    assert extract(tmp_path, archive).pyproject is None


def test_a_pyproject_directory_is_left_out(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START})
    (project / "pyproject.toml").mkdir()
    assert archive_names(build_submission(project)) == ["submission/strategy.py"]


def test_a_symbolic_link_as_the_pyproject_is_rejected(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START})
    (tmp_path / "real.toml").write_text("[project]\n")
    (project / "pyproject.toml").symlink_to(tmp_path / "real.toml")
    with pytest.raises(SubmissionError, match=r"pyproject.toml is a symbolic link"):
        build_submission(project)


def test_special_files_are_rejected(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START})
    os.mkfifo(project / "submission" / "pipe")
    with pytest.raises(SubmissionError, match=r"submission/pipe is not a regular file or directory"):
        build_submission(project)


def test_build_size_limit(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": "", "big.bin": b"0" * 900}, pyproject="x" * 100)
    archive = build_submission(project, max_total_bytes=1000)
    assert extract(tmp_path, archive, max_total_bytes=1000).pyproject == b"x" * 100
    with pytest.raises(SubmissionError, match="exceed 999 bytes"):
        build_submission(project, max_total_bytes=999)


def test_unreadable_files_raise_os_error(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START, "secret.txt": "x"})
    secret = project / "submission" / "secret.txt"
    secret.chmod(0)
    try:
        if os.access(secret, os.R_OK):
            pytest.skip("file permissions are not enforced for this user")
        with pytest.raises(PermissionError):
            build_submission(project)
    finally:
        secret.chmod(0o644)


def test_build_size_limit_is_checked_before_reading(tmp_path, monkeypatch):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START, "big.bin": b"x" * 100})

    def fail(self):
        raise AssertionError("files must not be read when the limit is exceeded")

    monkeypatch.setattr(Path, "read_bytes", fail)
    with pytest.raises(SubmissionError, match="exceed"):
        build_submission(project, max_total_bytes=50)


def test_a_backslash_in_a_file_name_is_rejected(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START, "a\\b.txt": "x"})
    with pytest.raises(SubmissionError, match="backslash"):
        build_submission(project)


def test_unreadable_directories_raise_os_error(tmp_path):
    project = make_project(tmp_path / "project", {"strategy.py": DECLARE_AT_START, "data/x.txt": "x"})
    data = project / "submission" / "data"
    data.chmod(0)
    try:
        if os.access(data, os.R_OK):
            pytest.skip("file permissions are not enforced for this user")
        with pytest.raises(PermissionError):
            build_submission(project)
    finally:
        data.chmod(0o755)
