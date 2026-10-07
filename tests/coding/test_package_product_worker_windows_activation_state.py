"""Native Windows C5 state bytes stay bound to one Product root."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_activation_state import (
    open_coding_windows_product_worker_activation_state_store,
)
from loushang.coding.package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from loushang.coding.package_product_worker_windows_gc_history import (
    CodingWindowsWorkerGcHistoryAuthority,
)
from loushang.coding.package_product_worker_windows_pending_host import (
    CodingWindowsWorkerPendingHostError,
    _require_uncoupled_windows_host_c5_absent,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    inspect_coding_windows_product_worker_offline_recovery,
)
from loushang.coding.session_manager import SessionManager
from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_gc_executor import (
    PackageProductGcExecutionError,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_windows_local_wheel_product_root_gc,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
    windows_flush_directory,
    windows_flush_file,
)
from loushang.harness.worker.activation_state_journal import (
    WorkerActivationStateJournalError,
)
from loushang.harness.worker.product_activation import _initial_state


@pytest.mark.requires_host_runtime
def test_windows_product_c5_state_reopens_and_refuses_complete_record_loss(
    tmp_path: Path,
) -> None:
    if os.name != "nt" or os.environ.get("LOUSHANG_WINDOWS_BACKEND_REVIEW") != "1":
        pytest.skip("native Windows backend review is required")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch("loushang.coding.package_product_runtime.version", return_value="2.0.0"),
    ):
        selection = CodingFencedProductApplicationSelection(
            windows_candidate=True, worker_candidates=True
        )
        factory = None
        try:
            factory = selection.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            product = selection.product_owner_for_factory(factory)
            with pytest.raises(ValueError, match="candidate owner is required"):
                open_coding_windows_product_worker_activation_state_store(product)
            journal = CodingWindowsWorkerActivationStateJournal(product)
            assert journal.load() is None
            assert journal.load_with_presence_read_only() == (False, None)
            _require_uncoupled_windows_host_c5_absent(product)
            assert journal.retained_attempts_read_only() == ()
            assert not any(
                name.startswith("worker-activation-state")
                for name in os.listdir(product.state_root)
            )
            initial = _initial_state(restart_budget=3)
            second = {**initial, "stateRevision": 2}
            assert not journal.compare_and_swap(expected_revision=1, document=second)
            assert not any(
                name.startswith("worker-activation-state")
                for name in os.listdir(product.state_root)
            )
            with product.gc_gate.guard(require_write=True):
                with (
                    WindowsPrivateDirectoryAcl() as acl,
                    product.epoch_runtime.borrow_product_state_root_descriptor() as root,
                ):
                    journal._prepare_lock(root, acl)
            assert journal.load_with_presence_read_only() == (True, None)
            with pytest.raises(CodingWindowsWorkerPendingHostError) as existing_c5:
                _require_uncoupled_windows_host_c5_absent(product)
            assert existing_c5.value.code == (
                "coding_worker_pending_c5_owner_requires_recovery"
            )
            assert journal.compare_and_swap(expected_revision=0, document=initial)
            assert journal.compare_and_swap(expected_revision=1, document=second)
            assert journal.load() == second
            assert journal.load_with_presence_read_only() == (True, second)
            assert journal.retained_attempts_read_only() == ()
            assert not journal.compare_and_swap(expected_revision=0, document=initial)
        finally:
            try:
                if factory is not None:
                    factory.dispose_unbound_runtime()
            finally:
                selection.close()

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        windows_candidate=True,
    )
    try:
        product = owner.runtime_owner.product_owner
        journal = CodingWindowsWorkerActivationStateJournal(product)
        assert journal.load() == second
        assert journal.load_with_presence_read_only() == (True, second)
        assert journal.retained_attempts_read_only() == ()
        recovery = inspect_coding_windows_product_worker_offline_recovery(product)
        assert recovery.activation_state_owner_present
        assert recovery.activation_state_revision == 2
        assert recovery.retained_activation_attempts == ()
        assert recovery.native_job_absence == ()
        gc = open_windows_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingWindowsWorkerGcHistoryAuthority(product),
        )
        gc.prepare()
        history = product.state_root / "worker-activation-state.jsonl"
        original = history.read_bytes()
        history.write_bytes(original.splitlines(keepends=True)[0])
        with pytest.raises(WorkerActivationStateJournalError) as lost_revision:
            journal.load()
        assert lost_revision.value.code == "worker_activation_state_corrupt"
        with pytest.raises(PackageProductGcExecutionError) as lost_gc:
            gc.prepare()
        assert lost_gc.value.code == "plugin_package_gc_worker_history_unsettled"
        with pytest.raises(WorkerActivationStateJournalError) as lost_recovery:
            inspect_coding_windows_product_worker_offline_recovery(product)
        assert lost_recovery.value.code == "worker_activation_state_corrupt"
        history.write_bytes(original)
        head = product.state_root / "worker-activation-state.h00000002.json"
        original_head = head.read_bytes()
        head.write_bytes(b"{}")
        with pytest.raises(WorkerActivationStateJournalError) as changed_head:
            journal.load()
        assert changed_head.value.code == "worker_activation_state_corrupt"
        head.write_bytes(original_head)
        assert journal.load() == second
        history.unlink()
        with pytest.raises(WorkerActivationStateJournalError) as orphan_lock:
            journal.load()
        assert orphan_lock.value.code == "worker_activation_state_corrupt"
        with product.gc_gate.guard(require_write=True):
            with (
                WindowsPrivateDirectoryAcl() as acl,
                product.epoch_runtime.borrow_product_state_root_descriptor() as root,
            ):
                descriptor = open_windows_regular_file_at(
                    root,
                    "worker-activation-state.jsonl",
                    create_new=True,
                    write=True,
                    security_descriptor=acl.security_descriptor,
                    read_control=True,
                )
                with os.fdopen(descriptor, "wb") as restored:
                    acl.validate(restored.fileno())
                    assert restored.write(original) == len(original)
                    restored.flush()
                    windows_flush_file(restored.fileno())
                windows_flush_directory(root)
        assert journal.load() == second
    finally:
        owner.close()
