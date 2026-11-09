"""Original restore effects with POSIX handles and inert Windows authority ports.

These observations exercise the full original restore action and retry, not
Windows ACL security, native handle rename semantics or Product admission.
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
    os.name != "posix", reason="portable restore observations use POSIX descriptor ports"
)

FIXTURE = Path(__file__).with_name("fixtures") / "windows_restore_effects_v1.json"
CASES = (
    "success",
    "copy_before",
    "copy_after",
    "stage_flush",
    "intent",
    "publication_before",
    "publication_after",
    "rename_before",
    "rename_after",
    "parent_flush",
    "root_receipt",
    "complete_before",
    "complete_after",
    "foreign_stage",
    "unclaimed_root",
    "archive_changed",
    "stage_changed",
    "stage_identity_changed",
    "parent_changed",
    "publication_parent_changed",
    "stage_disappeared",
    "published_root_changed",
    "published_stage_debt",
)


def _observe(case, base, monkeypatch):
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataMemberV1 as Member,
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataTargetSnapshotV1 as Snapshot,
    )
    from loushang.coding.package_private_data_restore_records import (
        CodingArchPrivateDataRestorePlanV1,
    )
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1
    from loushang.harness.resources.packages._tree_observation import metadata_identity

    owner_module = importlib.import_module(
        "loushang.coding.package_private_data_windows_restore_owner"
    )
    adapter = importlib.import_module(
        "loushang.coding.package_private_data_windows_restore_journal"
    )
    core = importlib.import_module(
        "loushang.harness.plugin_management._private_data_restore_windows"
    )
    archive = importlib.import_module(
        "loushang.harness.plugin_management._private_data_backup_windows"
    )
    native = importlib.import_module(
        "loushang.harness.resources.packages._private_tree_windows"
    )
    cls = adapter.CodingWindowsArchPrivateDataRestoreTransaction
    migrated = hasattr(cls, "execute_restore")
    phase_owner = core if migrated else owner_module
    archive_owner = archive if migrated else owner_module
    native_owner = native if migrated else owner_module
    binding_owner = adapter if migrated else owner_module
    trace, opened = [], {}
    used_fault = [False]
    publication, completed = [None], [False]
    root = base / "private" / "restored"
    root.parent.mkdir(parents=True)
    backup = base / "backups"
    backup_id = "b" * 64
    files = backup / backup_id / "files"
    files.mkdir(parents=True)
    (files / "report.txt").write_bytes(b"original report\n")
    stage_name = ".arch-restore-" + "a" * 64 + ".staging"
    stage = root.parent / stage_name

    def name(path):
        path = Path(path)
        if path == root.parent:
            return "private"
        if path == backup:
            return "backups"
        return path.name

    def fault(point):
        if point == case and not used_fault[0]:
            used_fault[0] = True
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

    source = capture(files, expected_root=metadata_identity(files.stat())[:2])
    trace.clear()
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "c" * 64, "coding.arch.default"
    )
    plan = CodingArchPrivateDataRestorePlanV1(
        key, backup_id, "deletion:original", source.target_id, 1, "absent"
    )
    started = SimpleNamespace(phase="started", restore_id="restore:" + "a" * 64)
    txn = cls(SimpleNamespace(), SimpleNamespace(state_root=base), 7)

    class ACL:
        def __init__(self, **kwargs):
            self.kind = "inherit" if kwargs.get("inherit_children") else "exact"
            trace.append(["acl", self.kind])

        def __enter__(self):
            trace.append(["acl-enter", self.kind])
            return self

        def validate(self, fd):
            trace.append(["validate", opened[fd]])

        def __exit__(self, kind, value, tb):
            trace.append(
                ["acl-exit", self.kind, None if kind is None else kind.__name__]
            )

    def open_directory(path, *, dir_fd=None, **kwargs):
        fd = os.open(path, os.O_RDONLY, dir_fd=dir_fd)
        opened[fd] = name(path)
        trace.append(["open", opened[fd]])
        return fd

    real_close = os.close

    def close(fd):
        if fd in opened:
            trace.append(["close", opened.pop(fd)])
        real_close(fd)

    def directory_identity(fd):
        trace.append(["identity", opened[fd]])
        value = os.fstat(fd)
        return (value.st_dev, value.st_ino)

    def inspect_parent(path):
        trace.append(["inspect", name(path)])
        value = path.stat()
        return (0, 0) if case == "parent_changed" else (value.st_dev, value.st_ino)

    def listdir(fd):
        trace.append(["list", opened[fd]])
        return os.listdir(fd)

    def flush(fd):
        trace.append(["flush", opened[fd]])
        fault("stage_flush" if opened[fd] == stage_name else "parent_flush")

    def create(parent_fd, stage_name, acl):
        trace.append("create-stage")
        os.mkdir(stage_name, dir_fd=parent_fd)
        return open_directory(stage_name, dir_fd=parent_fd)

    def copy(files_path, archived, stage_fd, exact, inherit):
        trace.append("copy")
        fault("copy_before")
        destination = stage / "report.txt"
        if destination.exists():
            if destination.read_bytes() != (files_path / "report.txt").read_bytes():
                raise ValueError("test copy port retained different bytes")
        else:
            destination.write_bytes((files_path / "report.txt").read_bytes())
        fault("copy_after")
        if case == "archive_changed":
            (files_path / "report.txt").write_bytes(b"changed\n")
        if case == "stage_changed":
            destination.write_bytes(b"wrong\n")

    def intent(*args, **kwargs):
        trace.append("generation-intent")
        assert stage_name not in opened.values(), "intent must follow stage close"
        fault("intent")
        return 2

    def prepare(self, event, plan, source, generation, identity):
        trace.append("publication")
        fault("publication_before")
        parent = root.parent.stat()
        publication[0] = SimpleNamespace(
            stage_name=stage_name,
            stage_identity=identity,
            generation_number=generation,
            parent_identity=(parent.st_dev, parent.st_ino),
            plan_fingerprint=plan.fingerprint,
        )
        if case == "publication_parent_changed":
            publication[0].parent_identity = (0, 0)
        if case == "stage_disappeared":
            (stage / "report.txt").unlink()
            stage.rmdir()
            raise OSError("publication interrupted after disappearing stage")
        fault("publication_after")
        return publication[0]

    def rename(parent_fd, fd, destination, *, expected_identity):
        trace.append("rename")
        assert metadata_identity(os.fstat(fd)) == expected_identity
        fault("rename_before")
        os.rename(stage_name, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        fault("rename_after")

    def deletion_open(parent_fd, child, **kwargs):
        fd = open_directory(child, dir_fd=parent_fd)
        if case == "stage_identity_changed":
            (stage / "extra.txt").write_bytes(b"extra")
        return fd

    def publish_root(*args, **kwargs):
        trace.append("root-receipt")
        fault("root_receipt")
        if case == "published_root_changed":
            (root / "report.txt").write_bytes(b"changed\n")
        if case == "published_stage_debt":
            (root.parent / ".arch-restore-other").mkdir(exist_ok=True)

    def complete(self, *args):
        trace.append("complete")
        fault("complete_before")
        completed[0] = True
        fault("complete_after")

    def current(self, candidate):
        trace.append("current-plan")
        return source

    def begin(self, candidate):
        trace.append("begin")
        return (
            SimpleNamespace(phase="completed", restore_id=started.restore_id)
            if completed[0]
            else started
        )

    def get_publication(self, *args, **kwargs):
        trace.append(["publication-for", kwargs.get("recover_stage", False)])
        return publication[0]

    @contextmanager
    def transaction(self):
        trace.append("transaction-enter")
        try:
            yield txn
        finally:
            trace.append("transaction-exit")

    monkeypatch.setattr(os, "close", close)
    monkeypatch.setattr(
        owner_module, "CodingWindowsArchPrivateDataReadPreview", lambda *_: None
    )
    monkeypatch.setattr(
        owner_module.CodingWindowsArchPrivateDataRestoreJournal,
        "transaction",
        transaction,
    )
    monkeypatch.setattr(
        owner_module.CodingWindowsArchPrivateDataRestoreJournal,
        "__post_init__",
        lambda self: None,
    )
    for module in {owner_module, adapter}:
        monkeypatch.setattr(
            module, "coding_arch_installation_private_data_root", lambda *_: root
        )
    monkeypatch.setattr(adapter, "backup_parent", lambda *_: backup)
    if not migrated:
        monkeypatch.setattr(owner_module, "backup_parent", lambda *_: backup)
    for module in {phase_owner, archive_owner, native_owner}:
        for symbol, value in (
            ("WindowsPrivateDirectoryAcl", ACL),
            ("open_windows_directory", open_directory),
            ("windows_listdir_at", listdir),
        ):
            monkeypatch.setattr(module, symbol, value)
        if hasattr(module, "inspect_windows_product_private_directory_identity"):
            monkeypatch.setattr(
                module,
                "inspect_windows_product_private_directory_identity",
                inspect_parent,
            )
        if hasattr(module, "windows_flush_directory"):
            monkeypatch.setattr(module, "windows_flush_directory", flush)
    monkeypatch.setattr(
        binding_owner, "_prepare_windows_arch_restore_generation_intent", intent
    )
    monkeypatch.setattr(
        binding_owner, "_publish_windows_arch_restored_root_receipt", publish_root
    )
    for method, value in (
        ("_require_plan_current", current),
        ("begin", begin),
        ("events", lambda self: (started,)),
        ("publication_for", get_publication),
        ("prepare_publication", prepare),
        ("complete", complete),
    ):
        monkeypatch.setattr(cls, method, value)
    if migrated:
        monkeypatch.setattr(adapter, "_capture_windows_target_snapshot", capture)
        monkeypatch.setattr(
            adapter,
            "_archive_io",
            replace(
                adapter._archive_io,
                capture=lambda path, expected: capture(path, expected_root=expected),
            ),
        )
        io = type(cls._tree_io)
        monkeypatch.setattr(
            io, "directory_identity", lambda self, fd: directory_identity(fd)
        )
        monkeypatch.setattr(
            io, "open_or_create_directory", lambda self, *args: create(*args)
        )
        monkeypatch.setattr(io, "copy_members", lambda self, *args: copy(*args))
        monkeypatch.setattr(
            io,
            "require_simple_metadata",
            lambda self, *_args, **_kwargs: trace.append("simple"),
        )
        monkeypatch.setattr(
            io,
            "require_no_named_directory_streams",
            lambda self, *_: trace.append("streams"),
        )
    else:
        for symbol, value in (
            ("_capture_windows_target_snapshot", capture),
            ("_directory_identity", directory_identity),
            ("_open_or_create_directory", create),
            ("_copy_members", copy),
            (
                "_require_simple_windows_metadata",
                lambda *_args, **_kwargs: trace.append("simple"),
            ),
            ("_require_no_named_directory_streams", lambda *_: trace.append("streams")),
        ):
            monkeypatch.setattr(owner_module, symbol, value)
    monkeypatch.setattr(native_owner, "windows_rename_open_directory_at", rename)
    monkeypatch.setattr(native_owner, "open_windows_deletion_entry_at", deletion_open)
    if case == "foreign_stage":
        (root.parent / ".arch-restore-other").mkdir()
    if case == "unclaimed_root":
        root.mkdir()
    owner = owner_module.CodingWindowsArchPrivateDataRestoreOwner(
        SimpleNamespace(), SimpleNamespace(state_root=base)
    )
    outcomes = []
    for attempt in range(3):
        trace.append(["attempt", attempt])
        try:
            result = owner.restore(plan)
            outcomes.append(
                {
                    "disposition": result.disposition,
                    "restore_id": result.restore_id,
                    "backup_id": result.backup_id,
                }
            )
        except (ValueError, OSError) as error:
            outcomes.append(
                {
                    "error": type(error).__name__,
                    "message": str(error).replace(str(base), "<ROOT>"),
                }
            )
        assert not opened, opened
    assert "begin" in trace
    if case == "success":
        assert [o.get("disposition") for o in outcomes] == [
            "restored",
            "already_present",
            "already_present",
        ]
    return {
        "outcomes": outcomes,
        "trace": trace,
        "files": {
            str(p.relative_to(base)): p.read_text()
            for p in sorted(base.rglob("*"))
            if p.is_file()
        },
        "directories": [
            str(p.relative_to(base)) for p in sorted(base.rglob("*")) if p.is_dir()
        ],
    }


@pytest.mark.parametrize("case", CASES)
def test_original_restore_effects(case, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())
    assert _observe(case, tmp_path / "run", monkeypatch) == expected[case]
