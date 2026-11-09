"""Original archive observation with real POSIX descriptors and inert native ports."""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="real POSIX descriptor ports"
)
FIXTURE = Path(__file__).with_name("fixtures") / "windows_archive_snapshot_v1.json"
CASES = (
    "success",
    "held_parent_changed",
    "final_parent_changed",
    "archive_open_failure",
    "manifest_read_failure",
    "read_and_final_parent_failure",
    "files_changed",
    "archive_visible_changed",
    "member_projection_failure",
    "archive_projection_failure",
    "files_close_failure",
    "manifest_close_failure",
    "parent_close_failure",
    "manifest_tamper",
    "manifest_hardlink",
    "named_manifest_stream",
    "extra_member",
    "late_manifest_hardlink",
    "late_named_stream",
    "late_manifest_tamper",
)


def _observe(case, base, monkeypatch):
    from loushang.coding.package_private_data_backup_records import (
        CodingArchPrivateDataBackupReceiptV1,
        backup_id,
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataMemberV1 as Member,
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataTargetSnapshotV1 as Snapshot,
    )
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1
    from loushang.harness.resources.packages._tree_observation import metadata_identity

    code = importlib.import_module(
        "loushang.coding.package_private_data_windows_archive_snapshot"
    )
    backup = importlib.import_module(
        "loushang.coding.package_private_data_windows_backup"
    )
    engine = importlib.import_module(
        "loushang.harness.plugin_management._private_data_backup_windows"
    )
    native = importlib.import_module(
        "loushang.harness.resources.packages._private_tree_windows"
    )
    migrated = hasattr(engine.WindowsPrivateArchiveIO, "capture_archive")
    trace, opened = [], {}
    verifies, captures, manifest_opens, inspections = [0], [0], [0], [0]
    parent = base / "backups"
    parent.mkdir(parents=True)
    original = base / "source"
    original.mkdir()
    (original / "report.txt").write_bytes(b"same report\n")

    def capture(path, *, expected_root):
        value = metadata_identity(path.stat())
        assert value[:2] == expected_root
        members = tuple(
            Member(
                p.name,
                "file",
                metadata_identity(p.stat()),
                sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(path.iterdir())
        )
        return Snapshot(sha256(os.fsencode(str(path))).hexdigest(), value, members)

    source = capture(original, expected_root=metadata_identity(original.stat())[:2])
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "c" * 64, "coding.arch.default"
    )
    name_value = backup_id(key, source)
    receipt = CodingArchPrivateDataBackupReceiptV1(
        key,
        source.target_id,
        name_value,
        1,
        len(b"same report\n"),
        "arch-backup:" + name_value,
    )
    archive_path = parent / name_value
    files = archive_path / "files"
    files.mkdir(parents=True)
    (files / "report.txt").write_bytes(b"same report\n")
    profile = backup._archive_io
    manifest_path = archive_path / "manifest.json"
    manifest_raw = profile.codec.encode(key, source, receipt)
    manifest_path.write_bytes(manifest_raw)

    def name(path):
        part = Path(path).name
        return "<BACKUP>" if part == name_value else part

    def observed_capture(path, *, expected_root):
        trace.append(["capture", name(path)])
        captures[0] += 1
        result = capture(path, expected_root=expected_root)
        if case == "files_changed" and captures[0] == 2:
            result = replace(
                result, members=(replace(result.members[0], content_sha256="f" * 64),)
            )
        return result

    class ACL:
        def __init__(self, **kwargs):
            trace.append(["acl", kwargs])

        def __enter__(self):
            trace.append("acl-enter")
            return self

        def validate(self, fd, **kwargs):
            trace.append(["validate", name(opened[fd]), kwargs])

        def __exit__(self, kind, value, tb):
            trace.append(["acl-exit", None if kind is None else kind.__name__])

    def directory(path, *, dir_fd=None, **kwargs):
        trace.append(["open-dir", name(path)])
        if case == "archive_open_failure" and str(path) == name_value:
            raise OSError("archive open interrupted")
        resolved = Path(path) if dir_fd is None else opened[dir_fd] / str(path)
        fd = os.open(path, os.O_RDONLY, dir_fd=dir_fd)
        opened[fd] = resolved
        return fd

    def regular(fd, child, **kwargs):
        trace.append(["open-file", child])
        descriptor = os.open(child, os.O_RDONLY, dir_fd=fd)
        opened[descriptor] = opened[fd] / child
        manifest_opens[0] += 1
        if manifest_opens[0] == 2:
            if case == "late_manifest_hardlink":
                os.link(manifest_path, base / "late-link")
            if case == "late_manifest_tamper":
                old = manifest_path.stat()
                manifest_path.write_bytes(b" " + manifest_raw[1:])
                os.utime(manifest_path, ns=(old.st_atime_ns, old.st_mtime_ns))
        return descriptor

    real_close, real_read = os.close, os.read

    def close(fd):
        path = opened.pop(fd, None)
        real_close(fd)
        if path is not None:
            trace.append(["close", name(path)])
            if (
                (case == "files_close_failure" and path.name == "files")
                or (
                    case == "manifest_close_failure"
                    and path.name == "manifest.json"
                    and manifest_opens[0] == 2
                )
                or (case == "parent_close_failure" and path == parent)
            ):
                raise OSError(name(path) + " close interrupted")

    def read(fd, maximum):
        path = opened.get(fd)
        if path is not None and path.name == "manifest.json":
            trace.append(["read", maximum])
            if case in {"manifest_read_failure", "read_and_final_parent_failure"}:
                raise OSError("manifest read interrupted")
        return real_read(fd, maximum)

    def inspect(path):
        trace.append(["inspect", name(path)])
        inspections[0] += 1
        if inspections[0] == 2 and case in {
            "final_parent_changed",
            "read_and_final_parent_failure",
        }:
            return (0, 0)
        value = path.stat()
        return value.st_dev, value.st_ino

    def identity(fd):
        trace.append(["identity", name(opened[fd])])
        value = os.fstat(fd)
        return (
            (0, 0)
            if case == "held_parent_changed" and opened[fd] == parent
            else (value.st_dev, value.st_ino)
        )

    def simple(metadata, *, directory):
        trace.append(["simple", directory])

    def same(current, before, *, directory):
        trace.append(["same", directory])

    def no_streams(fd):
        trace.append(["directory-streams", name(opened[fd])])

    def streams(fd):
        trace.append(["file-streams", name(opened[fd])])
        return (
            ("::$DATA", ":foreign:$DATA")
            if case == "named_manifest_stream"
            or (case == "late_named_stream" and manifest_opens[0] == 2)
            else ("::$DATA",)
        )

    def visible(fd, child):
        trace.append(["stat", name(child)])
        value = os.stat(child, dir_fd=fd, follow_symlinks=False)
        if (
            case == "archive_visible_changed"
            and child == name_value
            and verifies[0] == 2
        ):
            return SimpleNamespace(
                st_dev=value.st_dev,
                st_ino=value.st_ino,
                st_mode=value.st_mode,
                st_size=value.st_size,
                st_mtime_ns=value.st_mtime_ns + 1,
            )
        return value

    def names(fd):
        trace.append(["list", name(opened[fd])])
        return os.listdir(fd)

    real_verify = engine.WindowsPrivateArchiveIO.verify_archive

    def verify(self, *args):
        verifies[0] += 1
        trace.append(["verify", verifies[0]])
        return real_verify(self, *args)

    old_member, old_archive = (
        code.CodingArchPrivateDataMemberV1,
        code.CodingWindowsArchBackupArchiveSnapshotV1,
    )

    class TracedMember(old_member):
        __slots__ = ()

        def __post_init__(self):
            trace.append("project-member")
            if case == "member_projection_failure":
                raise ValueError("member projection rejected")
            super().__post_init__()

    class TracedArchive(old_archive):
        __slots__ = ()

        def __post_init__(self):
            trace.append("project-archive")
            if case == "archive_projection_failure":
                raise ValueError("archive projection rejected")
            super().__post_init__()

    monkeypatch.setattr(code, "CodingArchPrivateDataMemberV1", TracedMember)
    monkeypatch.setattr(code, "CodingWindowsArchBackupArchiveSnapshotV1", TracedArchive)
    monkeypatch.setattr(code, "backup_parent", lambda *_: parent)
    profile = replace(
        profile,
        capture=lambda path, expected: observed_capture(path, expected_root=expected),
    )
    monkeypatch.setattr(backup, "_archive_io", profile)
    if migrated:
        monkeypatch.setattr(code, "_archive_io", profile)
    else:
        for symbol, value in (
            ("_directory_identity", identity),
            ("_capture_windows_target_snapshot", observed_capture),
            ("_require_no_named_directory_streams", no_streams),
            ("_require_simple_windows_metadata", simple),
            ("_require_same_windows_metadata", same),
        ):
            monkeypatch.setattr(code, symbol, value)
    io = type(profile.io)
    monkeypatch.setattr(io, "directory_identity", lambda self, fd: identity(fd))
    monkeypatch.setattr(
        io, "require_simple_metadata", lambda self, *a, **kw: simple(*a, **kw)
    )
    monkeypatch.setattr(
        io, "require_same_metadata", lambda self, *a, **kw: same(*a, **kw)
    )
    monkeypatch.setattr(
        io, "require_no_named_directory_streams", lambda self, fd: no_streams(fd)
    )
    monkeypatch.setattr(engine.WindowsPrivateArchiveIO, "verify_archive", verify)
    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(os, "read", read)
    for module in {engine, native} if migrated else {code, engine, native}:
        for symbol, value in (
            ("WindowsPrivateDirectoryAcl", ACL),
            ("open_windows_directory", directory),
            ("open_windows_regular_file_at", regular),
            ("inspect_windows_product_private_directory_identity", inspect),
            ("windows_stat_at", visible),
            ("windows_listdir_at", names),
            ("windows_regular_file_stream_names", streams),
        ):
            if hasattr(module, symbol):
                monkeypatch.setattr(module, symbol, value)
    if case == "manifest_tamper":
        manifest_path.write_bytes(b"{}\n")
    if case == "manifest_hardlink":
        os.link(manifest_path, base / "external-link")
    if case == "extra_member":
        (archive_path / "foreign").write_text("unclaimed")

    try:
        result = code.capture_windows_arch_backup_archive(
            SimpleNamespace(), key, name_value, source, receipt
        )
        assert result.root_identity == metadata_identity(archive_path.stat())
        assert result.files == capture(
            files, expected_root=metadata_identity(files.stat())[:2]
        )
        assert result.manifest.identity == metadata_identity(manifest_path.stat())
        assert result.manifest.content_sha256 == sha256(manifest_raw).hexdigest()
        assert (
            result.target_id
            == "present:"
            + sha256(
                b"loushang.coding-arch-windows-backup-archive/v1\0"
                + backup.canonical_json_bytes(result.to_dict())
            ).hexdigest()
        )
        outcome = {"result": "exact_snapshot", "manifest_bytes": len(manifest_raw)}
    except (OSError, ValueError) as error:

        def describe(value, depth=0):
            if value is None or depth > 4:
                return None
            return {
                "type": type(value).__name__,
                "message": str(value).replace(str(base), "<ROOT>"),
                "cause": describe(value.__cause__, depth + 1),
                "context": describe(value.__context__, depth + 1),
            }

        outcome = {"raised": describe(error)}
    assert not opened, opened
    if case == "success":
        assert outcome.get("result") == "exact_snapshot", outcome
    # Raw manifest length contains real inode/time/path values; exact values and
    # digest were asserted above, not compared across unrelated temporary roots.
    outcome.pop("manifest_bytes", None)
    return {
        "outcome": outcome,
        "trace": trace,
        "verifies": verifies[0],
        "captures": captures[0],
    }


@pytest.mark.parametrize("case", CASES)
def test_original_archive_snapshot(case, tmp_path, monkeypatch):
    assert (
        _observe(case, tmp_path / "run", monkeypatch)
        == json.loads(FIXTURE.read_text())[case]
    )
