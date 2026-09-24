from __future__ import annotations

import asyncio
import stat
import sys
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import create_agent_session, create_services
from loushang.coding.package_pre_b_snapshot import (
    cutover_and_bootstrap_coding_package_product,
    prepare_and_cutover_coding_package_store_from_legacy,
    prepare_coding_package_cutover_roots,
    reopen_coding_package_cutover,
)
from loushang.coding.package_product_runtime import (
    CodingFencedProductApplicationSelection,
    bootstrap_coding_builtin_product_plugins,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.plugin_management.service import PluginManagementService


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_empty_coding_workspace_prepares_private_roots_and_cuts_over(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id="a" * 64,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    for root in (
        lifecycle.root,
        lifecycle.package_root,
        epoch.control_root,
        epoch.snapshot_root,
        epoch.epochs_root,
    ):
        assert stat.S_IMODE(root.lstat().st_mode) == 0o700
    assert cutover.attempt.result.disposition == "fenced"
    assert reopen_coding_package_cutover(lifecycle) == cutover.attempt.result


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_cutover_preparation_refuses_unsafe_existing_base_without_rewriting(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    private_base = tmp_path / "session-state"
    private_base.mkdir(mode=0o700)
    private_base.chmod(0o775)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        private_base, cwd=workspace
    )

    with pytest.raises(ValueError, match="not private"):
        prepare_coding_package_cutover_roots(lifecycle)

    assert stat.S_IMODE(private_base.lstat().st_mode) == 0o775
    assert not lifecycle.root.exists()
    assert not lifecycle.package_root.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
@pytest.mark.parametrize("legacy_kind", ("journal", "disabled_settings"))
def test_combined_cutover_refuses_implicit_legacy_plugin_adoption(
    tmp_path: Path,
    legacy_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    prepare_coding_package_cutover_roots(lifecycle)
    legacy_state = b"legacy desired state must survive\n"
    if legacy_kind == "journal":
        lifecycle.desired_state.write_bytes(legacy_state)
    settings = SettingsManager(
        ControlConfig(
            disabled_plugins=("coding.base",)
            if legacy_kind == "disabled_settings"
            else ()
        ),
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )

    with pytest.raises(RuntimeError, match="explicit (adoption|migration)"):
        cutover_and_bootstrap_coding_package_product(
            lifecycle,
            settings,
            workspace=workspace,
            namespace_id="c" * 64,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )

    if legacy_kind == "journal":
        assert lifecycle.desired_state.read_bytes() == legacy_state
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    assert not (epoch.control_root / "epoch.jsonl").exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_first_product_bootstrap_selects_base_without_reenabling_operator_disable(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings = SettingsManager(
        global_settings_path=tmp_path / "global-settings.json",
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    original_submit = PluginManagementService.submit

    def interrupt_enable(
        service: PluginManagementService, command: PluginManagementCommandV1
    ):
        if command.action == "enable":
            raise RuntimeError("injected enable interruption")
        return original_submit(service, command)

    with patch.object(PluginManagementService, "submit", interrupt_enable):
        with pytest.raises(RuntimeError, match="injected enable interruption"):
            cutover_and_bootstrap_coding_package_product(
                lifecycle,
                settings,
                workspace=workspace,
                namespace_id="b" * 64,
                runtime_version="2.0.0",
                runtime_protocol_epoch=2,
            )
    assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
    retry = cutover_and_bootstrap_coding_package_product(
        lifecycle,
        settings,
        workspace=workspace,
        namespace_id="b" * 64,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    assert retry.attempt.result.disposition == "fenced"
    assert not bootstrap_coding_builtin_product_plugins(
        lifecycle,
        settings,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )

    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    selection = CodingFencedProductApplicationSelection()
    try:
        with (
            patch(
                "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
                return_value=lifecycle,
            ),
            patch(
                "loushang.coding.package_product_runtime.version",
                return_value="2.0.0",
            ),
        ):
            factory = selection.factory_for_session(manager)
        assert factory is not None
        binding = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding",
                session_id=manager.get_header().conversation_id,
                cwd=str(workspace),
            )
        )
        try:
            runtime = binding.activate()
            for plugin_id in (
                "coding.base",
                "coding.lsp.default",
                "coding.arch.default",
            ):
                selected = runtime.capture_selected_plugin_manifest_for(
                    plugin_id, max_files=64, max_total_bytes=1024 * 1024
                )
                assert selected.verified_manifest().name == plugin_id
        finally:
            binding.dispose_runtime()
    finally:
        selection.close()

    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.version",
            return_value="2.0.0",
        ),
        patch(
            "loushang.coding.bootstrap.prepare_managed_coding_base_plugin_assembly",
            side_effect=AssertionError("legacy base assembly"),
        ),
        patch(
            "loushang.coding.bootstrap._default_package_materializer",
            side_effect=AssertionError("legacy package materializer"),
        ),
    ):
        session = create_agent_session(
            session_manager=manager,
            model=Model(
                id="plc9b-first-product",
                name="PLC9B First Product",
                provider="test",
                endpoint="anthropic-messages",
                capabilities=Capabilities(
                    reasoning=True,
                    input=("text",),
                    context_window=128000,
                    max_tokens=4096,
                ),
            ),
            services=create_services(settings_manager=settings),
            composition_set="coding-standard",
        )
    try:
        assert session._package_controller.get_package_materializer() is None
    finally:
        asyncio.run(session.dispose())

    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        product = owner.runtime_owner.product_owner
        base_operation = (
            "coding-builtin-bootstrap:"
            + sha256(
                f"{owner.epoch_runtime.registry.store_id}:coding.base".encode()
            ).hexdigest()
        )
        command_id = product.settled_install_command_id(
            operation_id=base_operation, plugin_id="coding.base"
        )
        assert command_id is not None and command_id.startswith("package:")
        assert (
            product.settled_install_command_id(
                operation_id="unknown-bootstrap", plugin_id="coding.base"
            )
            is None
        )
        with pytest.raises(ValueError, match="not settled"):
            product.settled_install_command_id(
                operation_id=base_operation, plugin_id="coding.arch.default"
            )
        state = product.desired_state.snapshot()
        installed = next(
            item
            for item in state.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        disabled = product.management.submit(
            PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:disable-base",
                    idempotency_key="operator:disable-base",
                    expected_inventory_revision=state.inventory_revision,
                    installation_key=installed.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision="operator:1",
                ),
            )
        )
        assert disabled.result is not None
        assert disabled.result.disposition == "succeeded"
    finally:
        owner.close()
    with pytest.raises(RuntimeError, match="superseded"):
        bootstrap_coding_builtin_product_plugins(
            lifecycle,
            settings,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
