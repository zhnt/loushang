"""Original POSIX expiry action with real files, Journal and inert admission.

No Product authorization is granted by these preview/recovery test ports.
Wire identities are validated against the real per-run plan and confirmation;
only scope, checkpoint, error and file-effect observations are frozen.
"""

from __future__ import annotations

import importlib
import json
import os
from contextlib import contextmanager
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="real POSIX expiry IO")
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
    "remove_before",
    "remove_after",
    "members_after",
    "recovery_failure",
    "extra_tombstone_member",
    "reappeared_after_completion",
)
FIXTURE = Path(__file__).with_name("fixtures") / "posix_expiry_action_v1.json"


def observe(case, base, monkeypatch):
    from loushang.coding.package_private_data_backup_expiry_journal import (
        CodingArchPrivateDataBackupExpiryJournal as Journal,
    )
    from loushang.coding.package_private_data_backup_expiry_records import (
        CodingArchPrivateDataBackupExpiryConfirmationV1 as Confirmation,
    )
    from loushang.coding.package_private_data_backup_expiry_records import (
        CodingArchPrivateDataBackupExpiryPlanV1 as Plan,
    )
    from loushang.coding.package_private_data_backup_expiry_records import (
        CodingArchPrivateDataBackupExpiryReceiptV1 as Receipt,
    )
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1

    code = importlib.import_module("loushang.coding.package_private_data_backup_expiry")
    cls = code.CodingArchPrivateDataBackupExpiryOwner
    core = (
        importlib.import_module(
            "loushang.harness.plugin_management.private_data_backup"
        )
        if hasattr(code, "execute_posix_expiry")
        else code
    )
    base.mkdir(mode=0o700)
    parent, state = base / "backups", base / "state"
    parent.mkdir(mode=0o700)
    state.mkdir(mode=0o700)
    backup_id = "b" * 64
    archive_path = parent / backup_id
    archive_path.mkdir(mode=0o700)
    (archive_path / "files").mkdir(mode=0o700)
    (archive_path / "files" / "report.txt").write_bytes(b"original evidence\n")
    (archive_path / "files" / "report.txt").chmod(0o600)
    (archive_path / "manifest.json").write_bytes(b'{"frozen":"manifest"}\n')
    (archive_path / "manifest.json").chmod(0o600)
    archive = code._capture_target_snapshot(archive_path, private_base=base)
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "c" * 64, "coding.arch.default"
    )
    plan = Plan(
        key,
        backup_id,
        "arch-backup:" + backup_id,
        "present:" + "d" * 64,
        "arch-restore-confirm:" + "e" * 64,
        "f" * 64,
        "present:" + "a" * 64,
        1,
        archive.root_identity,
        archive.target_id,
    )
    confirmation = Confirmation.create(
        plan, actor_id="operator:test", policy_revision="test:1"
    )
    journal = Journal(state)
    assert (
        journal.confirm(
            plan,
            actor_id=confirmation.actor_id,
            policy_revision=confirmation.policy_revision,
        )
        == confirmation
    )
    trace = []
    used = [False]
    opened = {}

    def name(value):
        part = Path(value).name
        return "<TOMB>" if part.startswith(".expiring-") else part

    def fault(point):
        if case == point and not used[0]:
            used[0] = True
            raise OSError(point + " interrupted")

    real_open, real_close, real_stat = os.open, os.close, os.fstat
    real_dup = os.dup
    real_rename = core._rename_directory_noreplace
    remove_name = "remove_expiry_tombstone" if core is not code else "_remove_tombstone"
    real_remove = getattr(core, remove_name)
    real_append = Journal._append
    io_type = type(code._private_io)
    real_members = io_type.remove_members

    def open_fd(path, flags, mode=0o777, *, dir_fd=None):
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        opened[fd] = name(path)
        return fd

    def close_fd(fd):
        opened.pop(fd, None)
        return real_close(fd)

    def dup_fd(fd):
        duplicate = real_dup(fd)
        opened[duplicate] = opened.get(fd, "borrowed")
        return duplicate

    @contextmanager
    def offline(self):
        trace.append("offline-enter")
        try:
            yield
        finally:
            trace.append("offline-exit")

    def pre_effect(self, p):
        trace.append("pre-effect")
        assert p == plan
        observed = code._capture_target_snapshot(archive_path, private_base=base)
        assert observed == archive
        return observed

    def recovery(self, p):
        trace.append("recovery")
        assert p == plan
        fault("recovery_failure")

    def append(self, event):
        trace.append(["append", event.phase])
        fault("write_" + event.phase + "_before")
        real_append(self, event)
        if event.phase == "completed" and case == "reappeared_after_completion":
            archive_path.mkdir(mode=0o700)
        fault("write_" + event.phase + "_after")

    def rename(*args, **kwargs):
        trace.append("rename")
        fault("rename_before")
        real_rename(*args, **kwargs)
        if case == "extra_tombstone_member":
            target = parent / args[3]
            (target / "intruder").write_bytes(b"unclaimed")
            (target / "intruder").chmod(0o600)
        fault("rename_after")

    def remove(*args, **kwargs):
        trace.append("remove")
        fault("remove_before")
        result = real_remove(*args, **kwargs)
        fault("remove_after")
        return result

    def members(self, *args):
        trace.append("members")
        result = real_members(self, *args)
        fault("members_after")
        return result

    monkeypatch.setattr(os, "open", open_fd)
    monkeypatch.setattr(os, "close", close_fd)
    monkeypatch.setattr(os, "dup", dup_fd)
    monkeypatch.setattr(
        code.CodingArchPrivateDataDeletionPreview, "__post_init__", lambda self: None
    )
    monkeypatch.setattr(code.CodingArchPrivateDataDeletionPreview, "_offline", offline)
    monkeypatch.setattr(cls, "_require_pre_effect_plan", pre_effect)
    monkeypatch.setattr(cls, "_require_recovery_authority", recovery)
    monkeypatch.setattr(code, "_backup_parent", lambda layout, k: parent)
    monkeypatch.setattr(Journal, "_append", append)
    monkeypatch.setattr(core, "_rename_directory_noreplace", rename)
    monkeypatch.setattr(core, remove_name, remove)
    monkeypatch.setattr(io_type, "remove_members", members)
    owner = cls(
        SimpleNamespace(private_data_base=base), SimpleNamespace(state_root=state)
    )
    outcomes = []
    for attempt in range(3):
        trace.append(["attempt", attempt])
        try:
            result = owner.expire(plan, confirmation)
            assert result == Receipt.create(plan, confirmation)
            outcomes.append("receipt")
        except (ValueError, OSError) as error:
            outcomes.append(
                {
                    "error": type(error).__name__,
                    "message": str(error).replace(str(base), "<ROOT>"),
                }
            )
        live = []
        for fd in tuple(opened):
            try:
                real_stat(fd)
            except OSError:
                opened.pop(fd, None)
            else:
                live.append(opened[fd])
        assert not live, live
    records = journal.events()
    assert all(e.plan == plan and e.confirmation == confirmation for e in records)
    assert all(e.archive == archive for e in records if e.phase != "confirmed")
    if case == "success":
        assert outcomes == ["receipt"] * 3
        assert [e.phase for e in records] == [
            "confirmed",
            "started",
            "renamed",
            "completed",
        ]
    return {
        "outcomes": outcomes,
        "trace": trace,
        "phases": [e.phase for e in records],
        "remaining": sorted(
            "/".join(name(x) for x in p.relative_to(parent).parts)
            for p in parent.rglob("*")
        ),
        "owner_fields": [f.name for f in fields(cls)],
        "owner_slots": list(cls.__slots__),
    }


@pytest.mark.parametrize("case", CASES)
def test_original_posix_expiry_action(case, tmp_path, monkeypatch):
    assert (
        observe(case, tmp_path / "run", monkeypatch)
        == json.loads(FIXTURE.read_text())[case]
    )
