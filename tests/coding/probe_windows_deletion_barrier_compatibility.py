"""Deletion barrier observations; Product/native facts are inert ports."""

import importlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from loushang.coding.package_private_data_backup_expiry_records import (
    CodingArchPrivateDataBackupExpiryPlanV1,
)
from loushang.coding.package_private_data_restore_records import (
    CodingArchPrivateDataRestorePlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1

CASES = (
    "empty",
    "foreign_only",
    "deleted",
    "latest_started",
    "latest_wrong_target",
    "latest_no_receipt",
    "latest_retained",
    "foreign_later",
    "latest_other_id",
)


def observe(case, patch):
    journal = importlib.import_module(
        "loushang.coding.package_private_data_windows_restore_journal"
    )
    code = importlib.import_module(
        "loushang.coding.package_private_data_windows_backup_expiry_recovery"
    )
    key = PluginInstallationKeyV1("coding", "workspace", "scope", "coding.arch.default")
    foreign = PluginInstallationKeyV1(
        "coding", "workspace", "other", "coding.arch.default"
    )
    backup = "a" * 64
    deleted_id = "deletion:current"
    trace = []
    opened = set()
    root = Path.cwd() / "inert" / "restored"

    def event(
        key=key,
        phase="completed",
        target="present:source",
        receipt=True,
        disposition="deleted",
        identifier=deleted_id,
    ):
        return NS(
            plan=NS(installation_key=key),
            phase=phase,
            target=NS(target_id=target),
            receipt=NS(disposition=disposition, receipt_id=identifier)
            if receipt
            else None,
        )

    base = event()
    histories = {
        "empty": (),
        "foreign_only": (event(key=foreign),),
        "deleted": (base,),
        "latest_started": (base, event(phase="started")),
        "latest_wrong_target": (base, event(target="present:other")),
        "latest_no_receipt": (base, event(receipt=False)),
        "latest_retained": (base, event(disposition="retained")),
        "foreign_later": (base, event(key=foreign)),
        "latest_other_id": (base, event(identifier="deletion:other")),
    }
    events = histories[case]
    restore_plan = CodingArchPrivateDataRestorePlanV1(
        key, backup, deleted_id, "present:source", 7, "absent"
    )
    latest = journal._latest_deletion_receipt(events, restore_plan)
    plan = CodingArchPrivateDataBackupExpiryPlanV1(
        key,
        backup,
        "arch-backup:" + backup,
        "present:source",
        "arch-restore-confirm:fixed",
        "c" * 64,
        "present:restored",
        7,
        (8, 9, 10, 11, 12),
        "present:archive",
    )
    confirmation = NS(
        confirmation_id=plan.confirmation_id,
        installation_key=key,
        backup_id=backup,
        deletion_receipt_id=deleted_id,
        restore_completion_digest=plan.restore_completion_digest,
        restored_target_id=plan.restored_target_id,
        restore_id="restore:fixed",
    )

    class Deletion:
        def __init__(self, *args):
            trace.append("deletion:init")

        def events(self):
            trace.append("deletion:events")
            return events

        def _close(self):
            trace.append("deletion:close")

    class Restore:
        state_fd = 20

        def _require_active(self):
            trace.append("restore:active")

        def _scan_confirmations(self):
            trace.append("restore:confirmations")
            return (confirmation,), None

        def events(self):
            trace.append("restore:events")
            return (
                NS(phase="started", restore_id="restore:fixed"),
                NS(
                    phase="completed",
                    installation_key=key,
                    backup_id=backup,
                    deletion_receipt_id=deleted_id,
                    restore_id="restore:fixed",
                    record_digest=plan.restore_completion_digest,
                ),
            )

        def publication_for(self, *args):
            trace.append("restore:publication")
            return NS(parent_identity=(1, 2), stage_identity=(3, 4, 5, 6, 7))

    class ACL:
        def __enter__(self):
            trace.append("acl:enter")
            return self

        def __exit__(self, *args):
            trace.append("acl:exit")

        def validate(self, fd):
            assert fd == 10
            trace.append("acl:validate")

    def open_directory(path, **kwargs):
        assert path == root.parent and kwargs == dict(
            share_delete=False, read_control=True
        )
        trace.append("open")
        opened.add(10)
        return 10

    @contextmanager
    def closing(fd):
        try:
            yield fd
        finally:
            opened.remove(fd)
            trace.append("close")

    def names(fd):
        assert fd in opened
        trace.append("listdir")
        return (root.name,)

    patch.setattr(code, "coding_arch_installation_private_data_root", lambda *a: root)
    patch.setattr(code, "CodingWindowsArchPrivateDataDeletionTransaction", Deletion)
    native = importlib.import_module(
        "loushang.harness.resources.packages._private_tree_windows"
    )
    patch.setattr(native, "WindowsPrivateDirectoryAcl", ACL)
    patch.setattr(
        code, "inspect_windows_product_private_directory_identity", lambda path: (1, 2)
    )
    patch.setattr(native, "open_windows_directory", open_directory)
    patch.setattr(native, "closing_descriptor", closing)
    patch.setattr(type(code._native_io), "directory_identity", lambda _io, fd: (1, 2))
    patch.setattr(native, "windows_listdir_at", names)
    patch.setattr(
        code, "inspect_coding_windows_arch_installation_root", lambda *a, **k: (3, 4)
    )
    patch.setattr(
        code,
        "_capture_windows_target_snapshot",
        lambda *a, **k: NS(
            root_identity=(3, 4, 5, 6, 7), target_id=plan.restored_target_id
        ),
    )
    product = NS(
        state_root=root.parent / "state",
        desired_state=NS(
            snapshot=lambda: NS(
                inventory_revision=7,
                installation=lambda key: NS(
                    latest_instance_revision_ref="selected",
                    selection=NS(desired_state="absent"),
                ),
            )
        ),
    )
    error = None
    try:
        code.require_windows_arch_backup_expiry_recovery_authority(
            NS(), product, Restore(), plan
        )
    except Exception as exc:
        error = [type(exc).__name__, str(exc)]
    return dict(latest=latest, trace=trace, error=error, unclosed=sorted(opened))


@pytest.mark.parametrize("case", CASES)
def test_original_windows_deletion_barrier(case, monkeypatch):
    expected = json.loads(
        (
            Path(__file__).parent / "fixtures" / "windows_deletion_barriers_v1.json"
        ).read_text()
    )
    assert observe(case, monkeypatch) == expected[case]
