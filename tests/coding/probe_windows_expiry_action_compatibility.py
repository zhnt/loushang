"""Original expiry action/retries with POSIX effects and inert authority ports.

The real original numbered-record codec/scan/append and archive-envelope paths
run here. Windows ACL/handles, Product preview/recovery and native tree-member
deletion are bounded test ports; this is not native or Product acceptance.
"""

from __future__ import annotations

import importlib
import json
import os
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="uses POSIX descriptor ports"
)
FIXTURE = Path(__file__).with_name("fixtures") / "windows_expiry_action_v1.json"
CASES = (
    "success",
    "write_started_before",
    "write_started_after",
    "write_renamed_before",
    "write_renamed_after",
    "write_completed_before",
    "write_completed_after",
    "rename_before",
    "rename_after",
    "flush_after_rename",
    "members_before",
    "members_after",
    "files_delete_before",
    "files_delete_after",
    "manifest_delete_before",
    "manifest_delete_after",
    "root_delete_before",
    "root_delete_after",
    "recovery_failure",
    "manifest_tamper",
    "manifest_hardlink",
    "extra_tombstone_member",
    "reappeared_after_completion",
    "completed_with_stage",
    "staged_gap",
)


def _observe(case, base, monkeypatch):
    from loushang.coding.package_private_data_backup_expiry_records import (
        CodingArchPrivateDataBackupExpiryConfirmationV1 as Confirmation,
    )
    from loushang.coding.package_private_data_backup_expiry_records import (
        CodingArchPrivateDataBackupExpiryPlanV1 as Plan,
    )
    from loushang.coding.package_private_data_backup_expiry_records import (
        CodingArchPrivateDataBackupExpiryReceiptV1 as Receipt,
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataMemberV1 as Member,
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataTargetSnapshotV1 as Snapshot,
    )
    from loushang.coding.package_private_data_windows_archive_snapshot import (
        CodingWindowsArchBackupArchiveSnapshotV1 as Archive,
    )
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1
    from loushang.harness.resources.packages._tree_observation import metadata_identity
    from loushang.harness.resources.packages.plugin_lifecycle.records import (
        canonical_json_bytes,
    )

    owner = importlib.import_module(
        "loushang.coding.package_private_data_windows_backup_expiry_owner"
    )
    journal = importlib.import_module(
        "loushang.coding.package_private_data_windows_backup_expiry_journal"
    )
    native = importlib.import_module(
        "loushang.harness.resources.packages._private_tree_windows"
    )
    archive_io = importlib.import_module(
        "loushang.harness.plugin_management._private_data_backup_windows"
    )
    cls = journal.CodingWindowsArchBackupExpiryTransaction
    migrated = hasattr(cls, "execute_expiry")
    core = (
        importlib.import_module(
            "loushang.harness.plugin_management._private_data_expiry_windows"
        )
        if migrated
        else owner
    )
    engines = {core, archive_io, native} if migrated else {owner}
    trace, opened = [], {}
    used = [False]
    parent, state = base / "backups", base / "state"
    parent.mkdir(parents=True)
    state.mkdir()
    backup_id = "b" * 64
    archive_path = parent / backup_id
    files_path = archive_path / "files"
    files_path.mkdir(parents=True)
    (files_path / "report.txt").write_bytes(b"frozen result\n")
    manifest_path = archive_path / "manifest.json"
    manifest_path.write_bytes(b'{"receipt":"frozen"}\n')

    def name(path):
        value = Path(path).name
        return "<TOMB>" if value.startswith(".expiring-") else value

    def fault(point):
        if case == point and not used[0]:
            used[0] = True
            raise OSError(point + " interrupted")

    def capture(path, *, expected_root):
        trace.append(["capture", name(path)])
        identity = metadata_identity(path.stat())
        assert identity[:2] == expected_root
        members = tuple(
            Member(
                p.name,
                "file",
                metadata_identity(p.stat()),
                sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(path.iterdir())
        )
        return Snapshot("e" * 64, identity, members)

    files = capture(files_path, expected_root=metadata_identity(files_path.stat())[:2])
    manifest = Member(
        "manifest.json",
        "file",
        metadata_identity(manifest_path.stat()),
        sha256(manifest_path.read_bytes()).hexdigest(),
    )
    archive = Archive("d" * 64, metadata_identity(archive_path.stat()), files, manifest)
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "c" * 64, "coding.arch.default"
    )
    plan = Plan(
        key,
        backup_id,
        "arch-backup:" + backup_id,
        "present:" + "f" * 64,
        "arch-restore-confirm:" + "a" * 64,
        "1" * 64,
        "present:" + "2" * 64,
        1,
        archive.root_identity,
        archive.target_id,
    )
    confirmation = Confirmation.create(
        plan, actor_id="local-operator:test", policy_revision="test:1"
    )
    event = journal.CodingWindowsArchBackupExpiryEventV1(
        1, "confirmed", plan, confirmation
    )
    saved = {
        "arch-backup-expiry-00000001.json": canonical_json_bytes(event.to_dict())
        + b"\n"
    }
    if case == "staged_gap":
        saved["arch-backup-expiry-00000003.json.stage"] = b"unpublished"
    trace.clear()

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

    def open_dir(path, *, dir_fd=None, **kwargs):
        resolved = Path(path) if dir_fd is None else opened[dir_fd] / str(path)
        fd = os.open(path, os.O_RDONLY, dir_fd=dir_fd)
        opened[fd] = resolved
        trace.append(["open", name(resolved)])
        return fd

    real_close = os.close

    def close(fd):
        if fd in opened:
            trace.append(["close", name(opened.pop(fd))])
        real_close(fd)

    def directory_identity(fd):
        trace.append(["identity", name(opened[fd])])
        metadata = os.fstat(fd)
        return metadata.st_dev, metadata.st_ino

    def require_directory(fd, expected, acl):
        trace.append(["require-directory", name(opened[fd])])
        assert metadata_identity(os.fstat(fd))[:2] == expected

    def inspect(path):
        trace.append(["inspect", name(path)])
        value = path.stat()
        return value.st_dev, value.st_ino

    def listdir(fd):
        trace.append(["list", name(opened[fd])])
        return tuple(saved) if opened[fd] == state else os.listdir(fd)

    def stat_at(fd, child):
        trace.append(["stat", name(child)])
        return os.stat(child, dir_fd=fd, follow_symlinks=False)

    def flush(fd):
        trace.append(["flush", name(opened[fd])])
        if opened[fd] == parent:
            fault("flush_after_rename")

    def rename(parent_fd, fd, destination, *, expected_identity):
        trace.append("rename")
        assert metadata_identity(os.fstat(fd)) == expected_identity
        fault("rename_before")
        source = opened[fd]
        target = opened[parent_fd] / destination
        os.rename(source, target)
        for key_fd, path in tuple(opened.items()):
            if path == source or source in path.parents:
                opened[key_fd] = target / path.relative_to(source)
        fault("rename_after")
        if case == "extra_tombstone_member":
            (target / "intruder.txt").write_text("unclaimed")

    def delete(fd, *, expected_identity, directory):
        path = opened[fd]
        category = (
            "files"
            if path.name == "files"
            else "manifest"
            if path.name == "manifest.json"
            else "root"
        )
        trace.append(["delete", category])
        fault(category + "_delete_before")
        if directory:
            path.rmdir()
        else:
            path.unlink()
        fault(category + "_delete_after")

    def remove_members(path, members, original):
        trace.append("members")
        fault("members_before")
        for member in members:
            assert (path / member.relative_path).read_bytes() == b"frozen result\n"
            (path / member.relative_path).unlink()
        fault("members_after")

    def read(path, **kwargs):
        trace.append(["read", path.name, kwargs])
        return saved.get(path.name)

    def write(path, payload, **kwargs):
        phase = json.loads(payload)["phase"]
        trace.append(["write", path.name, phase, kwargs])
        fault("write_" + phase + "_before")
        saved[path.name] = payload
        saved.pop(path.name + ".stage", None)
        if phase == "completed":
            if case == "reappeared_after_completion":
                archive_path.mkdir()
            if case == "completed_with_stage":
                saved["arch-backup-expiry-00000005.json.stage"] = b"unpublished"
        fault("write_" + phase + "_after")

    def preflight(*args):
        trace.append("preflight")
        return archive

    def recovery(*args):
        trace.append("recovery")
        fault("recovery_failure")

    layout, product = SimpleNamespace(), SimpleNamespace(state_root=state)

    @contextmanager
    def transaction(self):
        trace.append("transaction-enter")
        fd = open_dir(state)
        restore = SimpleNamespace(
            state_fd=fd, _require_active=lambda: trace.append("active")
        )
        try:
            yield cls(layout, product, restore)
        finally:
            close(fd)
            trace.append("transaction-exit")

    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(
        journal.CodingWindowsArchBackupExpiryJournal, "__post_init__", lambda self: None
    )
    monkeypatch.setattr(
        journal.CodingWindowsArchBackupExpiryJournal, "transaction", transaction
    )
    receipt_io = getattr(cls, "_receipt_io", None)
    if receipt_io is None:
        monkeypatch.setattr(journal, "windows_listdir_at", listdir)
        monkeypatch.setattr(journal, "read_windows_private_receipt", read)
        monkeypatch.setattr(journal, "write_windows_private_receipt", write)
    else:
        monkeypatch.setattr(core, "windows_listdir_at", listdir)
        monkeypatch.setattr(
            type(receipt_io),
            "read_private_receipt",
            lambda self, path, **kwargs: read(path, **kwargs),
        )
        monkeypatch.setattr(
            type(receipt_io),
            "write_private_receipt",
            lambda self, path, payload, **kwargs: write(path, payload, **kwargs),
        )
    monkeypatch.setattr(
        journal.CodingWindowsArchPrivateDataBackupExpiryPreview,
        "__post_init__",
        lambda self: None,
    )
    monkeypatch.setattr(
        journal.CodingWindowsArchPrivateDataBackupExpiryPreview,
        "_preview_locked",
        lambda self, *args: trace.append("journal-preview") or plan,
    )
    binding = cls if migrated else owner.CodingWindowsArchPrivateDataBackupExpiryOwner
    monkeypatch.setattr(binding, "_require_pre_effect_archive", preflight)
    monkeypatch.setattr(binding, "_require_recovery_authority", recovery)
    monkeypatch.setattr(
        journal if migrated else owner, "backup_parent", lambda *_: parent
    )
    for engine in engines:
        for symbol, value in (
            ("WindowsPrivateDirectoryAcl", ACL),
            ("open_windows_directory", open_dir),
            ("windows_listdir_at", listdir),
            ("windows_stat_at", stat_at),
            ("inspect_windows_product_private_directory_identity", inspect),
            ("windows_flush_directory", flush),
            ("windows_rename_open_directory_at", rename),
            ("windows_delete_open_entry", delete),
            (
                "open_windows_deletion_entry_at",
                lambda fd, child, **kwargs: open_dir(child, dir_fd=fd),
            ),
            ("windows_regular_file_stream_names", lambda fd: ("::$DATA",)),
        ):
            if hasattr(engine, symbol):
                monkeypatch.setattr(engine, symbol, value)
    if migrated:
        profile = cls._archive_io
        monkeypatch.setattr(
            cls,
            "_archive_io",
            replace(
                profile,
                capture=lambda path, expected: capture(path, expected_root=expected),
            ),
        )
        io = type(cls._tree_io)
        monkeypatch.setattr(
            io, "directory_identity", lambda self, fd: directory_identity(fd)
        )
        monkeypatch.setattr(
            io, "require_directory", lambda self, *args: require_directory(*args)
        )
        monkeypatch.setattr(
            io, "remove_members", lambda self, *args: remove_members(*args)
        )
        monkeypatch.setattr(
            io, "require_simple_metadata", lambda self, *args, **kwargs: None
        )
    else:
        for symbol, value in (
            ("_directory_identity", directory_identity),
            ("_require_directory", require_directory),
            ("_remove_members", remove_members),
            ("_capture_windows_target_snapshot", capture),
            ("_require_simple_windows_metadata", lambda *args, **kwargs: None),
        ):
            monkeypatch.setattr(owner, symbol, value)
    if case == "manifest_tamper":
        before = manifest_path.stat()
        manifest_path.write_bytes(b'{"receipt":"tamper"}\n')
        os.utime(manifest_path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert metadata_identity(manifest_path.stat()) == manifest.identity
    if case == "manifest_hardlink":
        os.link(manifest_path, base / "external-manifest-link")

    outcomes = []
    actor = owner.CodingWindowsArchPrivateDataBackupExpiryOwner(layout, product)
    for attempt in range(3):
        trace.append(["attempt", attempt])
        try:
            result = actor.expire(plan, confirmation)
            assert result == Receipt.create(plan, confirmation)
            outcomes.append("receipt")
        except (ValueError, OSError) as error:
            outcomes.append(
                {
                    "error": type(error).__name__,
                    "message": str(error).replace(str(base), "<ROOT>"),
                }
            )
        assert not opened, opened
    if case == "success":
        assert outcomes == ["receipt"] * 3
        assert [
            json.loads(v)["phase"]
            for k, v in sorted(saved.items())
            if k.endswith(".json")
        ] == ["confirmed", "started", "renamed", "completed"]
    return {
        "outcomes": outcomes,
        "trace": trace,
        "phases": {
            k: json.loads(v)["phase"] for k, v in saved.items() if k.endswith(".json")
        },
        "staged": sorted(k for k in saved if k.endswith(".stage")),
        "remaining": sorted(
            "/".join(name(part) for part in p.relative_to(base).parts)
            for p in base.rglob("*")
        ),
    }


@pytest.mark.parametrize("case", CASES)
def test_original_expiry_action(case, tmp_path, monkeypatch):
    assert (
        _observe(case, tmp_path / "run", monkeypatch)
        == json.loads(FIXTURE.read_text())[case]
    )
