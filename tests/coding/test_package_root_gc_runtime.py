from __future__ import annotations

import sys
from pathlib import Path

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.harness.config.agent import SettingsManager
from loushang.harness.package_product.product_gc_executor import (
    PackageProductGcExecutionError,
    PackageProductRootGcCommandV1,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    open_posix_local_wheel_product_root_gc,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted GC")
def test_fenced_coding_product_gc_excludes_live_session_and_deletes_exact_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=resolve_platform_paths(
            environ={"LOUSHANG_HOME": str(tmp_path / "private-home")}
        ),
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="c" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        selected = product.desired_state.snapshot()
        installation = next(
            item
            for item in selected.installations
            if item.installation_key.plugin_id == "coding.arch.default"
        )
        revision = installation.selection.package_revision
        assert revision is not None
        removed = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-arch",
                    idempotency_key="operator:remove-arch",
                    expected_inventory_revision=selected.inventory_revision,
                    installation_key=installation.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        gc = open_posix_local_wheel_product_root_gc(product)
        gc.prepare()
        pin_path = gc.transaction_pins.path
        settled_pin_history = pin_path.read_bytes()
        first_pin = settled_pin_history.splitlines(keepends=True)[0]
        pin_path.write_bytes(first_pin)
        try:
            with pytest.raises(PackageProductGcExecutionError) as open_pin:
                gc.candidates()
            assert open_pin.value.code == "plugin_package_gc_transaction_pin_active"
        finally:
            pin_path.write_bytes(settled_pin_history)
        (candidate,) = gc.candidates()
        assert candidate.package_revision == revision
        executor = gc.application.executor
        target = resolve_plugin_package_gc_root_target(
            revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=executor.committed_sets.records(),
            settlements=executor.root_settlements.records(),
        )
        deleted_root = product.plugin_store_root / target.settlement.final_name
        assert deleted_root.is_dir()
        private_data = tmp_path / "private-data"
        private_data.mkdir(mode=0o700)
        private_marker = private_data / "user-state.txt"
        private_marker.write_text("keep", encoding="utf-8")
        command = PackageProductRootGcCommandV1(
            candidate=candidate,
            reservation_operation_id="operator:gc-reserve-arch",
            reservation_idempotency_key="operator:gc-reserve-arch",
            attempt_operation_id="operator:gc-delete-arch",
            attempt_idempotency_key="operator:gc-delete-arch",
        )
        live = product.factory_for_session(
            session_id="live-session", cwd=workspace, runtime_id="live-session"
        )
        try:
            with pytest.raises(PackageProductGcExecutionError) as refused:
                gc.execute(command)
            assert refused.value.code == "plugin_package_gc_runtime_active"
            assert deleted_root.is_dir()
            assert gc.application.gate.snapshot().active == ()
        finally:
            live.dispose_unbound_runtime()

        result = gc.execute(command)
        assert result.disposition == "succeeded"
        assert not deleted_root.exists()
        assert private_marker.read_text(encoding="utf-8") == "keep"
        assert gc.execute(command) == result
        (status,) = gc.statuses()
        assert status.state == "succeeded"
        assert status.deletion_start is not None
        assert status.latest_attempt == result
        assert status.settlement_id == target.settlement_id
        assert executor.committed_sets.is_tombstoned(
            target.settlement.receipt.stable_ref.ref_id
        )
        assert executor.root_settlements.is_tombstoned(
            target.settlement.receipt.stable_ref.ref_id
        )
    finally:
        owner.close()

    reopened_owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        reopened_gc = open_posix_local_wheel_product_root_gc(
            reopened_owner.runtime_owner.product_owner
        )
        assert reopened_gc.execute(command) == result
        (recovered,) = reopened_gc.statuses()
        assert recovered.state == "succeeded"
        assert recovered.latest_attempt == result
        assert private_marker.read_text(encoding="utf-8") == "keep"
    finally:
        reopened_owner.close()
