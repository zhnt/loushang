"""Freeze the original confirmation procedure over inert authority/storage ports.

No Product binding or persistent authorization is created by these probes.
Native receipt prefix/ACL behavior remains covered by its own existing tests.
"""

from __future__ import annotations

import inspect
import json
import os
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from loushang.coding import package_private_data_windows_confirmation as module
from loushang.coding.package_legacy_windows_receipt import write_windows_private_receipt
from loushang.coding.package_private_data_deletion_preview import (
    CodingArchPrivateDataTargetSnapshotV1,
)
from loushang.harness.plugin_management.private_data_confirmation import (
    PluginPrivateDataConfirmationRecordV1,
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
    "new",
    "existing",
    "collision",
    "invalid_existing",
    "staged_retry",
    "read_failure",
    "write_failure",
    "write_after",
    "no_publication",
    "corrupt_publication",
    "oversized",
    "no_history",
    "stale_plan",
    "stale_generation",
    "invalid_confirmation",
)
FIXTURE = Path(__file__).with_name("fixtures") / "windows_confirmation_storage_v2.json"


def observe(case):
    trace, saved, attempts = [], {}, []
    root = Path("/unused-confirmation-root")
    state_root = Path("/unused-confirmation-state")
    key = PluginInstallationKeyV1(
        "coding", "workspace", "workspace:" + "a" * 64, "coding.arch.default"
    )
    target = CodingArchPrivateDataTargetSnapshotV1(
        sha256(os.fsencode(str(root))).hexdigest(), None, ()
    )
    plan = PluginPrivateDataDeletionPlanV1(
        key,
        "coding.arch.private-data:windows-v1",
        "absent:" + "c" * 64 if case == "stale_plan" else target.target_id,
    )
    confirmation = PluginPrivateDataDeletionConfirmationV1(
        "d" * 64 if case == "invalid_confirmation" else plan.fingerprint,
        "arch-delete:storage",
    )
    record = (
        None
        if case == "invalid_confirmation"
        else PluginPrivateDataConfirmationRecordV1(
            1, plan, confirmation, "operator", "policy:1"
        )
    )
    read_count = 0
    fired = False

    @contextmanager
    def borrowed():
        trace.append("borrow_enter")
        try:
            yield 7
        finally:
            trace.append("borrow_exit")

    class State:
        def snapshot(self):
            trace.append("desired_snapshot")
            return self

        def installation(self, selected_key):
            assert selected_key == key
            trace.append("installation")
            return SimpleNamespace(
                latest_instance_revision_ref=None if case == "no_history" else object()
            )

    @contextmanager
    def offline():
        trace.append("offline_enter")
        try:
            yield
        finally:
            trace.append("offline_exit")

    product = SimpleNamespace(
        state_root=state_root,
        desired_state=State(),
        epoch_runtime=SimpleNamespace(borrow_product_state_root_descriptor=borrowed),
        assert_private_data_read_authority_current=lambda: trace.append(
            "read_authority"
        ),
    )
    owner = object.__new__(module.CodingWindowsArchPrivateDataConfirmationOwner)
    object.__setattr__(owner, "layout", SimpleNamespace(scope_id=key.scope_id))
    object.__setattr__(owner, "product", product)
    path = owner._record_path(confirmation)
    if case in {"existing", "collision"}:
        value = PluginPrivateDataConfirmationRecordV1(
            1,
            plan,
            confirmation,
            "other" if case == "collision" else "operator",
            "policy:1",
        )
        saved[path.name] = canonical_json_bytes(value.to_dict()) + b"\n"
    if case == "invalid_existing":
        saved[path.name] = b"{invalid}\n"
    if case == "staged_retry":
        saved[path.name + ".stage"] = (canonical_json_bytes(record.to_dict()) + b"\n")[
            :20
        ]

    def preview(layout, selected_product):
        assert layout is owner.layout and selected_product is product
        trace.append("preview")
        return SimpleNamespace(_offline=offline)

    def selected_root(layout, selected_key):
        assert layout is owner.layout and selected_key == key
        trace.append("root")
        return root

    def generation(layout, selected_key, *, state_root):
        nonlocal read_count
        assert (
            layout is owner.layout
            and selected_key == key
            and state_root == product.state_root
        )
        read_count += 1
        trace.append("generation")
        return (1, 2) if case == "stale_generation" and read_count == 2 else None

    def read(path, *, maximum_bytes, allow_unpublished_stage=False):
        assert path.parent == state_root
        trace.append(["read", maximum_bytes, allow_unpublished_stage])
        if case == "read_failure":
            raise OSError("injected:read")
        return saved.get(path.name)

    def write(
        path,
        payload,
        *,
        maximum_bytes=inspect.signature(write_windows_private_receipt)
        .parameters["maximum_bytes"]
        .default,
    ):
        nonlocal fired
        assert path.parent == state_root
        trace.append(
            ["write", maximum_bytes, len(payload), sha256(payload).hexdigest()]
        )
        if case == "write_failure":
            raise OSError("injected:write")
        if case == "no_publication":
            return
        saved.pop(path.name + ".stage", None)
        saved[path.name] = b"corrupt" if case == "corrupt_publication" else payload
        if case == "write_after" and not fired:
            fired = True
            raise OSError("injected:written_then_failed")

    def read_native(_io, *args, **kwargs):
        return read(*args, **kwargs)

    def write_native(_io, *args, **kwargs):
        return write(*args, **kwargs)

    def result(operation):
        try:
            value = operation()
            return (
                {"record": value.to_dict()}
                if hasattr(value, "to_dict")
                else {"confirmed": value}
            )
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
        for name, value in {
            "CodingWindowsArchPrivateDataReadPreview": preview,
            "coding_arch_installation_private_data_root": selected_root,
            "inspect_coding_windows_arch_installation_root": generation,
            "read_windows_private_receipt": read,
        }.items():
            stack.enter_context(patch.object(module, name, value))
        if hasattr(module, "write_windows_private_receipt"):
            stack.enter_context(
                patch.object(module, "write_windows_private_receipt", write)
            )
        profile = getattr(module, "_receipt_io", None)
        if profile is not None:
            stack.enter_context(
                patch.object(type(profile), "read_private_receipt", read_native)
            )
            stack.enter_context(
                patch.object(type(profile), "write_private_receipt", write_native)
            )
        for _attempt in range(2 if case == "write_after" else 1):
            accepted = result(
                lambda: owner.record_confirmation(
                    plan,
                    confirmation,
                    actor_id="x" * 17000 if case == "oversized" else "operator",
                    policy_revision="policy:1",
                )
            )
            confirmed = result(lambda: owner.is_confirmed(plan, confirmation))
            attempts.append({"accept": accepted, "query": confirmed})
    return {
        "attempts": attempts,
        "trace": trace,
        "files": {name: raw.hex() for name, raw in saved.items()},
    }


@pytest.mark.parametrize("case", CASES)
def test_original_windows_confirmation_storage(case):
    assert observe(case) == json.loads(FIXTURE.read_text())[case]
