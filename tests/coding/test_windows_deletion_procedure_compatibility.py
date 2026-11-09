"""Old deletion owner and concrete transaction with inert Product/native ports.

Actual phase, codec, append, replay and receipt methods run. This does not
construct a trusted Product or exercise Windows handles; effect/proof glue has
separate real-POSIX-FD observations.
"""

from __future__ import annotations

import inspect
import json
import stat
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from loushang.coding import package_private_data_windows_deletion_journal as journal
from loushang.coding import package_private_data_windows_deletion_owner as module
from loushang.coding.package_legacy_windows_receipt import write_windows_private_receipt
from loushang.coding.package_private_data_deletion_journal import (
    CodingArchPrivateDataDeletionEventV1,
)
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.harness.plugin_management.private_data_deletion import (
    PluginPrivateDataDeletionConfirmationV1,
    PluginPrivateDataDeletionPlanV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

CASES = (
    "present",
    "absent",
    "replay",
    "start_write_after",
    "rename_write_after",
    "complete_write_after",
    "remove_after",
    "authority_missing",
    "not_removed",
    "no_history",
    "stale_target",
    "foreign_pending",
    "recreated",
    "unpublished_start",
    "direct_staged_start",
    "direct_staged_mismatch",
)
FIXTURE = Path(__file__).with_name("fixtures") / "windows_deletion_procedure_v1.json"


def observe(case, directory):
    directory.mkdir()
    root = directory / "arch"
    state_root = Path("/unused-deletion-state")
    trace, saved, attempts = [], {}, []
    live = 0
    fired = False
    tombstone = False
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "a" * 64, "coding.arch.default"
    )
    target = CodingArchPrivateDataTargetSnapshotV1(
        "b" * 64, None if case == "absent" else (1, 2, stat.S_IFDIR | 0o700, 0, 3), ()
    )
    plan = PluginPrivateDataDeletionPlanV1(
        key, "coding.arch.private-data:windows-v1", target.target_id
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        plan.fingerprint, "arch-delete:procedure"
    )
    started = CodingArchPrivateDataDeletionEventV1(
        1, "started", plan, confirmation, target
    )
    prefix = journal._EVENT_PREFIX

    def name(revision):
        return f"{prefix}{revision:08d}.json"

    if case == "foreign_pending":
        other = replace(confirmation, confirmation_id="arch-delete:other")
        saved[name(1)] = (
            canonical_json_bytes(replace(started, confirmation=other).to_dict()) + b"\n"
        )
    if case in {"unpublished_start", "direct_staged_start", "direct_staged_mismatch"}:
        saved[name(1) + ".stage"] = (canonical_json_bytes(started.to_dict()) + b"\n")[
            :20
        ]

    def fault(phase):
        nonlocal fired
        selected = {
            "start_write_after": "started",
            "rename_write_after": "renamed",
            "complete_write_after": "completed",
        }.get(case)
        if phase == selected and not fired:
            fired = True
            raise OSError("injected:published-" + phase)

    def capture(_owner, selected_key, *, allow_pending=False):
        assert live == 1 and selected_key == key
        trace.append(["capture", allow_pending])
        return (
            replace(target, root_path_digest="c" * 64)
            if case == "stale_target"
            else target
        )

    class State:
        def snapshot(self):
            assert live == 1
            trace.append("desired")
            return self

        def installation(self, selected_key):
            assert selected_key == key
            return SimpleNamespace(
                latest_instance_revision_ref=None if case == "no_history" else object(),
                selection=SimpleNamespace(
                    desired_state="installed_enabled"
                    if case == "not_removed"
                    else "absent"
                ),
            )

    def is_confirmed(selected_plan, selected_confirmation):
        assert (
            live == 1
            and selected_plan == plan
            and selected_confirmation == confirmation
        )
        trace.append("confirmation")
        return case != "authority_missing"

    proof_owner = SimpleNamespace(
        layout=object(),
        product=SimpleNamespace(desired_state=State()),
        is_confirmed=is_confirmed,
    )

    def tombstone_proof(_owner, event, *, present):
        assert _owner is proof_owner and live == 1 and event.target == target
        trace.append(["tombstone_proof", present])
        assert tombstone == present

    def staged_proof(_owner, selected_key, selected_target):
        assert (
            _owner is proof_owner
            and selected_key == key
            and selected_target == target
            and live == 1
        )
        trace.append("staged_proof")
        if case == "direct_staged_mismatch":
            raise ValueError("Windows Coding Arch deletion target changed")

    def list_names(fd):
        assert fd == 7 and live == 1
        trace.append("list")
        return tuple(saved)

    def read(path, *, maximum_bytes, allow_unpublished_stage=False):
        assert path.parent == state_root and live == 1 and not allow_unpublished_stage
        trace.append(["read", path.name, maximum_bytes])
        return saved.get(path.name)

    def write(
        path,
        payload,
        *,
        maximum_bytes=inspect.signature(write_windows_private_receipt)
        .parameters["maximum_bytes"]
        .default,
    ):
        assert path.parent == state_root and live == 1
        trace.append(["write", path.name, maximum_bytes, payload.hex()])
        saved.pop(path.name + ".stage", None)
        saved[path.name] = payload
        fault(json.loads(payload)["phase"])

    def read_native(_io, *args, **kwargs):
        return read(*args, **kwargs)

    def write_native(_io, *args, **kwargs):
        return write(*args, **kwargs)

    @contextmanager
    def transaction():
        nonlocal live
        assert live == 0
        live = 1
        trace.append("guard_enter")
        value = journal.CodingWindowsArchPrivateDataDeletionTransaction(
            state_root, 7, proof_owner
        )
        try:
            yield value
        finally:
            value._close()
            trace.append("guard_exit")
            live = 0

    def native_effect(selected_root, event, tx, confirmations):
        nonlocal tombstone, fired
        assert (
            selected_root == root
            and event == started
            and confirmations is proof_owner
            and live == 1
        )
        trace.append("effect")
        if target.root_identity is None:
            assert capture(proof_owner, key, allow_pending=True) == target
            return "already_absent"
        tombstone = True
        tx.record_renamed(event)
        if case == "remove_after" and not fired:
            fired = True
            raise OSError("injected:partial-effect")
        tombstone = False
        if case == "recreated":
            root.mkdir()
        return "deleted"

    owner = object.__new__(module.CodingWindowsArchPrivateDataDeletionOwner)
    object.__setattr__(owner, "layout", object())
    object.__setattr__(owner, "product", object())

    def result(operation):
        try:
            value = operation()
            return None if value is None else value.to_dict()
        except Exception as error:
            assert not isinstance(
                error, (AssertionError, AttributeError, KeyError, TypeError)
            ), error
            return {
                "error": type(error).__name__,
                "message": str(error),
                "cause": None
                if error.__cause__ is None
                else type(error.__cause__).__name__,
            }

    with ExitStack() as stack:
        for target_module, attr, value in (
            (
                module,
                "coding_arch_installation_private_data_root",
                lambda _layout, _key: root,
            ),
            (
                journal,
                "coding_arch_installation_private_data_root",
                lambda _layout, _key: root,
            ),
            (
                module,
                "CodingWindowsArchPrivateDataConfirmationOwner",
                lambda _layout, _product: proof_owner,
            ),
            (module, "_capture_current_target", capture),
            (journal, "_capture_current_target", capture),
            (journal, "_require_staged_start_target_unchanged", staged_proof),
            (journal, "_require_windows_tombstone", tombstone_proof),
            (module, "_delete_started", native_effect),
        ):
            stack.enter_context(patch.object(target_module, attr, value))
        stack.enter_context(
            patch.object(
                type(owner),
                "_journal",
                property(lambda _self: SimpleNamespace(transaction=transaction)),
            )
        )
        profile = getattr(
            journal.CodingWindowsArchPrivateDataDeletionTransaction, "_receipt_io", None
        )
        if profile is None:
            for attr, value in {
                "windows_listdir_at": list_names,
                "read_windows_private_receipt": read,
                "write_windows_private_receipt": write,
            }.items():
                stack.enter_context(patch.object(journal, attr, value))
        else:
            native = __import__(
                "loushang.harness.plugin_management._private_data_deletion_windows",
                fromlist=["windows_listdir_at"],
            )
            stack.enter_context(patch.object(native, "windows_listdir_at", list_names))
            stack.enter_context(
                patch.object(type(profile), "read_private_receipt", read_native)
            )
            stack.enter_context(
                patch.object(type(profile), "write_private_receipt", write_native)
            )
        for _attempt in range(
            2
            if case
            in {
                "replay",
                "start_write_after",
                "rename_write_after",
                "complete_write_after",
                "remove_after",
            }
            else 1
        ):
            if case.startswith("direct_staged"):

                def accept_start():
                    with transaction() as tx:
                        return tx.record_start(plan, confirmation, target)

                accepted = result(accept_start)
            else:
                accepted = result(lambda: owner.delete_confirmed(plan, confirmation))
            queried = result(lambda: owner.receipt_for(plan, confirmation))
            attempts.append({"accept": accepted, "query": queried})
    assert live == 0
    return {
        "attempts": attempts,
        "trace": trace,
        "files": {name: raw.hex() for name, raw in saved.items()},
    }


@pytest.mark.parametrize("case", CASES)
def test_original_windows_deletion_procedure(case, tmp_path):
    assert observe(case, tmp_path / case) == json.loads(FIXTURE.read_text())[case]
