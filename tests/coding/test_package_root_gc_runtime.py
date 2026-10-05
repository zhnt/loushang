from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from importlib.metadata import version
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.cli.application import run_cli
from loushang.coding.cli.package_gc import main as package_gc_main
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
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_gc_target import (
    resolve_plugin_package_gc_root_target,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.plugin import build_coding_data_skill_wheel


def test_package_gc_cli_refuses_unsupported_platform_before_product_open(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(sys, "platform", "win32"),
        patch(
            "loushang.coding.cli.package_gc.open_coding_fenced_product_application_owner"
        ) as opened,
    ):
        assert package_gc_main(["prepare"]) == 1
    opened.assert_not_called()
    assert capsys.readouterr().err == (
        "Coding Package GC refused: package_gc_platform_unsupported\n"
    )


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted GC")
def test_product_gc_reclaims_old_revision_after_update_without_touching_selected_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "private-home"))
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="d" * 64,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )

    def package_command(action: str, wheel: Path) -> None:
        stderr = StringIO()
        assert (
            asyncio.run(
                run_cli(
                    [action, str(wheel), "--package-scope", "project"],
                    cwd=workspace,
                    stdin=StringIO(),
                    stdout=StringIO(),
                    stderr=stderr,
                )
            )
            == 0
        ), stderr.getvalue()

    for wheel_version, action in (
        ("1", "--install-package"),
        ("2", "--update-package"),
    ):
        wheel = tmp_path / f"reviewpack-{wheel_version}-py3-none-any.whl"
        wheel.write_bytes(
            build_coding_data_skill_wheel(
                plugin_id="reviewpack",
                version=wheel_version,
                contribution_id="review-skill",
                skill_name="review",
                skill_document=b"---\nname: review\ndescription: Review files\n---\n# Review\n",
            )
        )
        package_command(action, wheel)
        if action == "--install-package":
            stderr = StringIO()
            assert (
                asyncio.run(
                    run_cli(
                        ["--enable-plugin", "reviewpack"],
                        cwd=workspace,
                        stdin=StringIO(),
                        stdout=StringIO(),
                        stderr=stderr,
                    )
                )
                == 0
            ), stderr.getvalue()

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        installation = next(
            item
            for item in product.desired_state.snapshot().installations
            if item.installation_key.plugin_id == "reviewpack"
        )
        current_revision = installation.selection.package_revision
        assert current_revision is not None
        assert current_revision.plugin_version == "2"
        gc = open_posix_local_wheel_product_root_gc(product)
        gc.prepare()
        assert gc.dependency_retention() == ()
        assert gc.dependency_inspections() == ()
        operator_view = gc.operator_snapshot()
        assert operator_view.dependency_inspections == ()
        assert any(
            item.package_revision.plugin_id == "reviewpack"
            for item in operator_view.candidates
        )
        with pytest.raises(PackageProductGcExecutionError) as missing_dependency:
            gc.delete_dependency(
                "0" * 64,
                expected_settlement_id="0" * 64,
                operation_id="operator:missing-dependency",
                idempotency_key="operator:missing-dependency",
            )
        assert (
            missing_dependency.value.code
            == "plugin_package_gc_dependency_target_unavailable"
        )
        assert not (product.state_root / "dependency-gc.jsonl").exists()
        old_candidate = next(
            item
            for item in gc.candidates()
            if item.package_revision.plugin_id == "reviewpack"
            and item.package_revision.plugin_version == "1"
        )
        executor = gc.application.executor
        old_target = resolve_plugin_package_gc_root_target(
            old_candidate.package_revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=executor.committed_sets.records(),
            settlements=executor.root_settlements.records(),
        )
        current_target = resolve_plugin_package_gc_root_target(
            current_revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=executor.committed_sets.records(),
            settlements=executor.root_settlements.records(),
        )
        old_root = product.plugin_store_root / old_target.settlement.final_name
        current_root = product.plugin_store_root / current_target.settlement.final_name
        assert old_root.is_dir() and current_root.is_dir() and old_root != current_root
        result = gc.execute(
            PackageProductRootGcCommandV1(
                candidate=old_candidate,
                reservation_operation_id="operator:reserve-old-review",
                reservation_idempotency_key="operator:reserve-old-review",
                attempt_operation_id="operator:delete-old-review",
                attempt_idempotency_key="operator:delete-old-review",
            )
        )
        assert result.disposition == "succeeded"
        assert not old_root.exists()
        assert current_root.is_dir()
        assert (
            product.desired_state.snapshot()
            .installation(installation.installation_key)
            .selection.package_revision
            == current_revision
        )
        runtime = product.factory_for_session(
            session_id="gc-selected-review",
            cwd=workspace,
            runtime_id="gc-selected-review",
        ).create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id="gc-selected-review",
                cwd=str(workspace),
            )
        )
        try:
            runtime.activate()
            selected = runtime.capture_selected_plugin_manifest_for(
                "reviewpack", max_files=16, max_total_bytes=2 * 1024 * 1024
            )
            assert selected.manifest.version == "2"
        finally:
            runtime.dispose_runtime()
    finally:
        owner.close()


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
        runtime_version=version("loushang"),
        runtime_protocol_epoch=2,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version=version("loushang"),
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
        second_live = product.factory_for_session(
            session_id="second-live-session",
            cwd=workspace,
            runtime_id="second-live-session",
        )
        try:
            with pytest.raises(PackageProductGcExecutionError) as refused:
                gc.execute(command)
            assert refused.value.code == "plugin_package_gc_runtime_active"
            assert deleted_root.is_dir()
            assert gc.application.gate.snapshot().active == ()
            live.dispose_unbound_runtime()
            with pytest.raises(PackageProductGcExecutionError) as still_live:
                gc.execute(command)
            assert still_live.value.code == "plugin_package_gc_runtime_active"
            assert deleted_root.is_dir()
        finally:
            live.dispose_unbound_runtime()
            second_live.dispose_unbound_runtime()

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
        runtime_version=version("loushang"),
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

        product = reopened_owner.runtime_owner.product_owner
        state = product.desired_state.snapshot()
        lsp = next(
            item
            for item in state.installations
            if item.installation_key.plugin_id == "coding.lsp.default"
        )
        lsp_revision = lsp.selection.package_revision
        assert lsp_revision is not None
        removal = product.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:remove-lsp-after-gc",
                    idempotency_key="operator:remove-lsp-after-gc",
                    expected_inventory_revision=state.inventory_revision,
                    installation_key=lsp.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert removal.result is not None
        assert removal.result.disposition == "succeeded"
        lsp_candidate = next(
            item
            for item in reopened_gc.candidates()
            if item.package_revision == lsp_revision
        )
        lsp_target = resolve_plugin_package_gc_root_target(
            lsp_revision,
            bindings=product.gc_bindings.records(),
            claims=product.gc_bindings.claims(),
            committed_sets=reopened_gc.application.executor.committed_sets.records(),
            settlements=reopened_gc.application.executor.root_settlements.records(),
        )
        lsp_root = product.plugin_store_root / lsp_target.settlement.final_name
        assert lsp_root.is_dir()
        lsp_command = PackageProductRootGcCommandV1(
            candidate=lsp_candidate,
            reservation_operation_id="operator:gc-reserve-lsp",
            reservation_idempotency_key="operator:gc-reserve-lsp",
            attempt_operation_id="operator:gc-delete-lsp",
            attempt_idempotency_key="operator:gc-delete-lsp",
        )
        with patch.object(
            reopened_gc.application.executor.results,
            "record",
            side_effect=RuntimeError("injected crash after physical deletion"),
        ):
            with pytest.raises(RuntimeError, match="injected crash"):
                reopened_gc.execute(lsp_command)
        assert not lsp_root.exists()
        started = next(
            item
            for item in reopened_gc.statuses()
            if item.reservation.candidate == lsp_candidate
        )
        assert started.state == "deletion_started"
        assert started.latest_attempt is None

        recovery = subprocess.run(
            (
                sys.executable,
                "-m",
                "loushang.coding.cli.package_gc",
                "--workspace",
                str(workspace),
                "retry",
                "--reservation-id",
                started.reservation.reservation_id,
                "--attempt-key",
                "crash-recovery",
            ),
            env={**os.environ, "LOUSHANG_HOME": str(tmp_path / "private-home")},
            capture_output=True,
            text=True,
            check=False,
            timeout=90,
        )
        assert recovery.returncode == 0, recovery.stderr
        assert json.loads(recovery.stdout)["disposition"] == "succeeded"
        recovered_lsp = next(
            item
            for item in reopened_gc.statuses()
            if item.reservation.candidate == lsp_candidate
        )
        assert recovered_lsp.state == "succeeded"
        assert recovered_lsp.latest_attempt is not None
        assert recovered_lsp.latest_attempt.store_result is not None
        assert recovered_lsp.latest_attempt.store_result.disposition == "already_absent"
    finally:
        reopened_owner.close()
