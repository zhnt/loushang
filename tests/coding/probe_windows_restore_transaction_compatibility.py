"""Old restore transaction observations; inert ports do not confer authority."""
from __future__ import annotations

import importlib
import inspect
import json
import os
import stat
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURE = Path(__file__).with_name("fixtures") / "windows_restore_transaction_v1.json"


def _outcome(operation, root):
    try:
        value = operation()
        return {"returned": value.to_dict() if hasattr(value, "to_dict") else value}
    except Exception as error:
        def describe(current, depth=0):
            if current is None or depth > 5:
                return None
            return {
                "type": type(current).__module__ + "." + type(current).__qualname__,
                "message": str(current).replace(str(root), "<ROOT>"),
                "cause": describe(current.__cause__, depth + 1),
                "context": describe(current.__context__, depth + 1),
            }
        return {"raised": describe(error)}


def _observe(case, root, monkeypatch):
    from loushang.coding.package_legacy_windows_receipt import (
        CodingWindowsPrivateReceiptError,
        write_windows_private_receipt,
    )
    from loushang.coding.package_private_data_backup_records import (
        CodingArchPrivateDataBackupReceiptV1,
    )
    from loushang.coding.package_private_data_deletion_preview import (
        CodingArchPrivateDataTargetSnapshotV1,
    )
    from loushang.coding.package_private_data_restore_records import (
        CodingArchPrivateDataRestorePlanV1,
    )
    from loushang.harness.plugin_management.records import PluginInstallationKeyV1
    from loushang.harness.resources.packages.plugin_lifecycle.records import (
        canonical_json_bytes,
    )

    module = importlib.import_module("loushang.coding.package_private_data_windows_restore_journal")
    cls = module.CodingWindowsArchPrivateDataRestoreTransaction
    transaction = cls(SimpleNamespace(), SimpleNamespace(state_root=root), 7)
    native_io = getattr(cls, "_receipt_io", None)
    engine = importlib.import_module("loushang.harness.plugin_management._private_data_restore_windows") if native_io else module
    archive_engine = importlib.import_module("loushang.harness.plugin_management._private_data_backup_windows")
    archive_candidate = hasattr(archive_engine.WindowsPrivateArchiveIO, "read_restore_source")
    trace, saved, descriptors = [], {}, []
    published = [False]
    proof_active = [False]
    root_path = root / "restored"
    key = PluginInstallationKeyV1("coding", "workspace", "workspace:" + "a" * 64, "coding.arch.default")
    source = CodingArchPrivateDataTargetSnapshotV1(sha256(b"source").hexdigest(), (1, 2, stat.S_IFDIR | 0o700, 0, 1), ())
    restored = CodingArchPrivateDataTargetSnapshotV1(sha256(b"restored").hexdigest(), (9, 10, stat.S_IFDIR | 0o700, 0, 1), ())
    plan = CodingArchPrivateDataRestorePlanV1(key, "b" * 64, "deletion:original", source.target_id, 1, "absent")
    receipt = CodingArchPrivateDataBackupReceiptV1(key, source.target_id, plan.backup_id, 0, 0, "arch-backup:" + plan.backup_id)
    write_cap = inspect.signature(write_windows_private_receipt).parameters["maximum_bytes"].default
    fault = [None]

    class ACL:
        def __init__(self, **kwargs):
            trace.append(["acl", kwargs])
        def __enter__(self):
            trace.append("acl-enter")
            return self
        def validate(self, descriptor):
            trace.append("acl-validate")
        def __exit__(self, kind, value, tb):
            trace.append(["acl-exit", None if kind is None else kind.__name__])

    def inspect_parent(path):
        trace.append("inspect-parent")
        if case == "archive_parent_changed" or (proof_active[0] and case == "parent_changed"):
            return (17, 18)
        if case == "archive_final_parent_changed" and trace.count("inspect-parent") > 1:
            return (17, 18)
        return (7, 8)

    def open_directory(path, **kwargs):
        trace.append(["open-parent", kwargs])
        descriptor = os.open(root, os.O_RDONLY)
        descriptors.append(descriptor)
        return descriptor

    def directory_identity(descriptor):
        trace.append("held-parent")
        return (17, 18) if case in {"held_parent_changed", "archive_held_parent_changed"} else (7, 8)

    def names(descriptor):
        trace.append("list")
        if case.startswith("archive_"):
            return ("foreign.staging",) if case == "archive_stage_debt" else ()
        return tuple(saved) + ((root_path.name,) if published[0] and case != "root_missing" else ()) + ((".arch-restore-foreign",) if case == "stage_debt" else ())

    def capture(path, *, expected_root):
        trace.append(["capture", "stage" if path.name.endswith(".staging") else "root", list(expected_root)])
        return replace(restored, root_identity=(9, 10, stat.S_IFDIR | 0o700, 1, 1)) if proof_active[0] and case == "captured_root_changed" else restored

    def current(plan_value):
        trace.append("current-plan")
        return source

    def bound(*args, **kwargs):
        trace.append("bound-root")
        return None if case == "completion_root_absent" else (17, 18) if proof_active[0] and case == "bound_root_changed" else restored.root_identity[:2]

    def read(path, *, maximum_bytes, allow_unpublished_stage=False):
        trace.append(["read", path.name, maximum_bytes, allow_unpublished_stage])
        return saved.get(path.name)

    def write(path, payload, **kwargs):
        assert kwargs.get("maximum_bytes", write_cap) == write_cap
        trace.append(["write", path.name, write_cap, len(payload), sha256(payload).hexdigest()])
        if fault[0] == "before":
            raise CodingWindowsPrivateReceiptError("publication interrupted")
        if fault[0] != "unpublished":
            saved[path.name] = payload
        if fault[0] == "after":
            raise CodingWindowsPrivateReceiptError("publication interrupted after save")

    monkeypatch.setattr(module, "coding_arch_installation_private_data_root", lambda *args: root_path)
    monkeypatch.setattr(module, "inspect_coding_windows_arch_installation_root", bound)
    monkeypatch.setattr(module, "_capture_windows_target_snapshot", capture)
    if not case.startswith("archive_"):
        monkeypatch.setattr(cls, "_require_plan_current", lambda self, value: current(value))
    for name, value in (("WindowsPrivateDirectoryAcl", ACL), ("open_windows_directory", open_directory), ("windows_listdir_at", names), ("inspect_windows_product_private_directory_identity", inspect_parent)):
        monkeypatch.setattr(engine, name, value)
    if native_io:
        native_tree = importlib.import_module("loushang.harness.resources.packages._private_tree_windows")
        monkeypatch.setattr(native_tree, "WindowsPrivateDirectoryAcl", ACL)
        monkeypatch.setattr(native_tree, "open_windows_directory", open_directory)
        monkeypatch.setattr(type(native_io), "read_private_receipt", lambda self, *args, **kwargs: read(*args, **kwargs))
        monkeypatch.setattr(type(native_io), "write_private_receipt", lambda self, *args, **kwargs: write(*args, **kwargs))
        monkeypatch.setattr(type(cls._tree_io), "directory_identity", lambda self, fd: directory_identity(fd))
    else:
        monkeypatch.setattr(module, "read_windows_private_receipt", read)
        monkeypatch.setattr(module, "write_windows_private_receipt", write)
        monkeypatch.setattr(module, "_directory_identity", directory_identity)

    def scenario():
        if case == "closed":
            transaction._close()
            return transaction.events()
        if case.startswith("archive_"):
            backend = archive_engine if archive_candidate else module
            for name, value in (("WindowsPrivateDirectoryAcl", ACL), ("open_windows_directory", open_directory), ("windows_listdir_at", names), ("inspect_windows_product_private_directory_identity", inspect_parent)):
                monkeypatch.setattr(backend, name, value)
            monkeypatch.setattr(module, "backup_parent", lambda *_args: root)

            def manifest(*args):
                trace.append("read-manifest")
                if case == "archive_read_failure":
                    raise OSError("manifest read interrupted")
                return (replace(receipt, installation_key=replace(key, scope_id="workspace:" + "c" * 64)), source) if case == "archive_foreign_key" else (receipt, replace(source, root_path_digest="f" * 64)) if case == "archive_foreign_source" else (receipt, source)

            def verify(*args):
                trace.append("verify-archive")
                if case == "archive_verify_failure":
                    raise OSError("archive verify interrupted")

            if archive_candidate:
                profile = module._archive_io
                monkeypatch.setattr(type(profile.io), "directory_identity", lambda self, fd: directory_identity(fd))
                monkeypatch.setattr(type(profile), "read_manifest", lambda self, *args: manifest(*args))
                monkeypatch.setattr(type(profile), "verify_archive", lambda self, *args: verify(*args))
            else:
                monkeypatch.setattr(module, "_read_archive_manifest", manifest)
                monkeypatch.setattr(module, "_verify_archive", verify)
            return transaction._verify_plan_archive(plan)

        if case == "invalid_plan_state":
            return transaction.begin(replace(plan, target_state="same_bytes"))
        if case == "publication_oversized":
            monkeypatch.setattr(cls if native_io else module, "_publication_max_bytes" if native_io else "_PUBLICATION_MAX_BYTES", 1)
        started = transaction.begin(plan)
        if case.startswith("publication_"):
            fault[0] = {"publication_write_before": "before", "publication_write_after": "after", "publication_unpublished": "unpublished"}.get(case)
        publication = transaction.prepare_publication(started, plan, source, 2, restored.root_identity)
        if case.startswith("publication_"):
            if case == "publication_wrong_digest":
                saved[transaction._publication_path(started).name] = canonical_json_bytes(replace(publication, started_digest="e" * 64).to_dict()) + b"\n"
            if case == "publication_invalid_json":
                saved[transaction._publication_path(started).name] = b"{invalid}\n"
            return transaction.publication_for(started, plan)
        published[0] = True
        if case == "completion_write_after":
            fault[0] = "after"
        transaction.complete(started, plan, source)
        if case == "completed_revision":
            return transaction.completed_plan_revision_for(replace(plan, desired_inventory_revision=2))
        if case in {"parent_changed", "held_parent_changed", "root_missing", "stage_debt", "bound_root_changed", "captured_root_changed"}:
            proof_active[0] = True
            return transaction._completed_restore(plan)
        if case.startswith("confirmation_"):
            fault[0] = {"confirmation_write_before": "before", "confirmation_write_after": "after", "confirmation_unpublished": "unpublished"}.get(case)
        confirmation = transaction.confirm_restore(plan)
        if case == "confirmation_stale":
            return transaction.verify_confirmation(plan, "unknown-confirmation")
        assert transaction.confirm_restore(plan) == confirmation
        return transaction.verify_confirmation(plan, confirmation.confirmation_id)

    result = _outcome(scenario, root)
    # Unknown publication outcomes are followed by reads, never blind re-execution.
    if case in {"confirmation_write_after", "completion_write_after"}:
        write_count = sum(isinstance(row, list) and row[0] == "write" for row in trace)
        if case == "confirmation_write_after":
            value = next(json.loads(raw) for name, raw in saved.items() if name.startswith(module._CONFIRM_PREFIX))
            result["queried"] = _outcome(lambda: transaction.verify_confirmation(plan, value["confirmationId"]), root)
        else:
            result["queried"] = _outcome(lambda: [event.to_dict() for event in transaction.events()], root)
        assert sum(isinstance(row, list) and row[0] == "write" for row in trace) == write_count
    transaction._close()
    closed = []
    for fd in descriptors:
        try:
            os.fstat(fd)
        except OSError:
            closed.append(True)
        else:
            closed.append(False)
    assert all(closed)
    return {"result": result, "trace": trace, "saved": dict(sorted((name, raw.decode()) for name, raw in saved.items())), "parent_fds_closed": closed}


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text())["cases"], ids=lambda case: case["name"])
def test_original_windows_restore_transaction(case, tmp_path, monkeypatch):
    assert _observe(case["name"], tmp_path, monkeypatch) == case["expected"]
