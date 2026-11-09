"""Original POSIX Journal bytes, ordering and recovery over real local files.

The archive metadata is an inert valid DTO; this proves Journal behavior, not
physical archive or Product authorization.
"""

from __future__ import annotations

import importlib
import inspect
import json
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="POSIX Journal probe")
CASES = (
    "empty_read",
    "complete_replays",
    "other_actor",
    "begin_without_confirm",
    "begin_different_archive",
    "stale_checkpoint",
    "out_of_order",
    "invalid_phase",
    "completed_other_actor",
    "completed_other_plan",
    "repeat_backup",
    "read_partial",
    "write_repairs_partial",
    "duplicate_before_bad_schema",
    "capacity_after_open",
    "bytes_after_open",
    "unsafe_parent_before_invalid_phase",
    "unsafe_parent_read",
    "confirm_factory_before_parent",
    "append_before",
    "append_after",
    "event_factory_failure",
    "receipt_factory_failure",
    "live_float_version",
)
FIXTURE = Path(__file__).with_name("fixtures") / "posix_expiry_journal_v1.json"


def observe(case, base, monkeypatch):
    mod = importlib.import_module(
        "loushang.coding.package_private_data_backup_expiry_journal"
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataTargetSnapshotV1,
    )
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1

    root = base / "state"
    root.mkdir(mode=0o700, parents=True)
    archive = CodingArchPrivateDataTargetSnapshotV1(
        "a" * 64, (1, 2, stat.S_IFDIR | 0o700, 0, 3), ()
    )
    key = PluginInstallationKeyV1(
        "coding", "workspace", "probe-scope", "coding.arch.default"
    )
    plan = mod.CodingArchPrivateDataBackupExpiryPlanV1(
        key,
        "b" * 64,
        "arch-backup:" + "b" * 64,
        "present:" + "c" * 64,
        "arch-restore-confirm:" + "d" * 64,
        "e" * 64,
        "present:" + "f" * 64,
        3,
        archive.root_identity,
        archive.target_id,
    )
    owner = mod.CodingArchPrivateDataBackupExpiryJournal(root)
    results = []

    def call(name, *args, **kwargs):
        try:
            value = getattr(owner, name)(*args, **kwargs)
        except Exception as error:

            def describe(exc, depth=0):
                if exc is None or depth == 4:
                    return None
                return {
                    "type": type(exc).__name__,
                    "text": str(exc).replace(str(base), "$BASE"),
                    "code": getattr(exc, "code", None),
                    "cause": describe(exc.__cause__, depth + 1),
                    "context": describe(exc.__context__, depth + 1),
                    "suppress_context": exc.__suppress_context__,
                }

            results.append({"error": describe(error)})
            return None
        if isinstance(value, tuple):
            results.append([item.to_dict() for item in value])
        else:
            results.append(value.to_dict())
        return value

    def confirm(current=plan, actor="operator:one"):
        return call("confirm", current, actor_id=actor, policy_revision="policy:1")

    def fail(*args, **kwargs):
        raise RuntimeError("injected record factory failure")

    if case == "empty_read":
        call("events")
    elif case in {"unsafe_parent_before_invalid_phase", "unsafe_parent_read"}:
        root.chmod(0o755)
        call("advance", None, "invalid") if case.endswith("invalid_phase") else call(
            "events"
        )
    elif case == "confirm_factory_before_parent":
        root.chmod(0o755)
        confirm(actor=" ")
    elif case == "begin_without_confirm":
        confirmation = mod.CodingArchPrivateDataBackupExpiryConfirmationV1.create(
            plan, actor_id="operator:one", policy_revision="policy:1"
        )
        call("begin", plan, confirmation, archive)
    elif case == "event_factory_failure":
        monkeypatch.setattr(mod, "CodingArchPrivateDataBackupExpiryEventV1", fail)
        confirm()
    elif case in {"append_before", "append_after"}:
        original = owner._journal.append

        def append(event):
            if case == "append_after":
                original(event)
            raise OSError("injected append failure")

        monkeypatch.setattr(owner._journal, "append", append)
        confirm()
        call("events")
    else:
        confirmation = confirm()
        if case in {"read_partial", "write_repairs_partial"}:
            owner.path.write_bytes(owner.path.read_bytes() + b'{"partial":')
            call("events") if case == "read_partial" else confirm()
        elif case == "duplicate_before_bad_schema":
            raw = owner.path.read_bytes().replace(
                b'"revision": 1', b'"revision": 1, "revision": 1'
            )
            owner.path.write_bytes(raw + b'{"unknown": true}\n')
            call("events")
        elif case == "other_actor":
            confirm(actor="operator:two")
        elif case == "capacity_after_open":
            monkeypatch.setattr(mod, "_MAX_RECORDS", 1)
            call("begin", plan, confirmation, archive)
        elif case == "bytes_after_open":
            monkeypatch.setattr(mod, "_MAX_BYTES", 1)
            call("events")
        else:
            started = call("begin", plan, confirmation, archive)
            if case == "begin_different_archive":
                call(
                    "begin",
                    plan,
                    confirmation,
                    replace(archive, root_path_digest="9" * 64),
                )
            elif case == "stale_checkpoint":
                call("advance", replace(started, revision=9), "renamed")
            elif case == "out_of_order":
                call("advance", started, "completed")
            elif case == "invalid_phase":
                call("advance", started, "invalid")
            else:
                renamed = call("advance", started, "renamed")
                if case == "receipt_factory_failure":
                    monkeypatch.setattr(
                        mod.CodingArchPrivateDataBackupExpiryReceiptV1, "create", fail
                    )
                    call("advance", renamed, "completed")
                else:
                    if case == "live_float_version":
                        renamed = replace(renamed, record_version=1.0)
                    completed = call("advance", renamed, "completed")
                    if case == "completed_other_actor":
                        confirm(actor="operator:two")
                    elif case == "completed_other_plan":
                        confirm(replace(plan, desired_inventory_revision=4))
                    elif case == "repeat_backup":
                        later = replace(
                            plan,
                            backup_id="9" * 64,
                            backup_receipt_id="arch-backup:" + "9" * 64,
                        )
                        later_confirmation = confirm(later)
                        later_start = call("begin", later, later_confirmation, archive)
                        later_renamed = call("advance", later_start, "renamed")
                        call("advance", later_renamed, "completed")
                        confirm()
                    else:
                        confirm()
                        call("begin", plan, confirmation, archive)
                        call("advance", completed, "completed")
                        call("events")
                        reopened = mod.CodingArchPrivateDataBackupExpiryJournal(root)
                        results.append([item.to_dict() for item in reopened.events()])
    return {
        "results": results,
        "files": {
            p.name: p.read_bytes().hex() for p in sorted(root.iterdir()) if p.is_file()
        },
        "file_modes": {
            p.name: stat.S_IMODE(p.stat().st_mode)
            for p in sorted(root.iterdir())
            if p.is_file()
        },
        "instance_fields": sorted(vars(owner)),
        "constructor": str(
            inspect.signature(mod.CodingArchPrivateDataBackupExpiryJournal)
        ),
    }


@pytest.mark.parametrize("case", CASES)
def test_original_posix_expiry_journal(case, tmp_path, monkeypatch):
    expected = json.loads(FIXTURE.read_text())
    assert observe(case, tmp_path / case, monkeypatch) == expected[case]
