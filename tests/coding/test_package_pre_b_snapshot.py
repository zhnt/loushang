from __future__ import annotations

import asyncio
import json
import shutil
import stat
import subprocess
import sys
from hashlib import sha256
from io import StringIO
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding._plugin_lifecycle import (
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.bootstrap import (
    create_agent_session,
    create_agent_session_runtime,
    create_services,
)
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
from loushang.harness.cli.package_lifecycle import (
    PackageLifecycleError,
    PackageLifecycleRequest,
    run_package_lifecycle,
)
from loushang.harness.config.agent import ControlConfig, SettingsManager
from loushang.harness.host.rpc.commands.packages import RpcPackageCommands
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.plugin_management.service import PluginManagementService
from loushang.harness.resources.packages.operations import PackageOperationsRuntime
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleAction,
)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX platform selection")
def test_unadmitted_posix_platform_keeps_existing_session_route(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    lifecycle.package_root.mkdir(parents=True)
    (lifecycle.package_root / "package-lock.json").write_text("{}")
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    selection = CodingFencedProductApplicationSelection()
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch("loushang.coding.package_product_runtime.sys.platform", "darwin"),
    ):
        assert selection.factory_for_session(manager) is None
    assert (lifecycle.package_root / "package-lock.json").read_text() == "{}"
    selection.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX platform selection")
def test_unadmitted_posix_platform_rejects_old_settings(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    settings_path = tmp_path / "settings.json"
    settings_path.write_text('{"disabled_plugins":["coding.base"]}')
    settings = SettingsManager(global_settings_path=settings_path)
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    selection = CodingFencedProductApplicationSelection()
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch("loushang.coding.package_product_runtime.sys.platform", "darwin"),
        pytest.raises(RuntimeError, match="pre-B workspace is unsupported"),
    ):
        selection.factory_for_session(manager, settings_manager=settings)
    assert not lifecycle.package_root.exists()
    selection.close()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX platform selection")
def test_unadmitted_posix_platform_validates_existing_fence(tmp_path: Path) -> None:
    from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout
    from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
        PackageEpochFenceError,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    epoch = resolve_coding_package_epoch_layout(lifecycle)
    epoch.control_root.mkdir(parents=True, mode=0o700)
    (epoch.control_root / "epoch.jsonl").write_text("invalid B fence\n")
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    selection = CodingFencedProductApplicationSelection()
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch("loushang.coding.package_product_runtime.sys.platform", "darwin"),
        pytest.raises(PackageEpochFenceError),
    ):
        selection.factory_for_session(manager)
    selection.close()


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

    with pytest.raises(RuntimeError, match="pre-B workspace is unsupported"):
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
@pytest.mark.parametrize(
    "legacy_kind",
    (
        "global_settings",
        "project_settings",
        "custom_global_settings",
        "custom_project_settings",
        "desired_state",
        "package_lock",
    ),
)
def test_ordinary_session_refuses_pre_b_workspace_without_writing(
    tmp_path: Path, legacy_kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    global_settings = tmp_path / "global-settings.json"
    if legacy_kind == "global_settings":
        global_settings.write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    elif legacy_kind == "project_settings":
        project_settings = workspace / ".loushang" / "settings.json"
        project_settings.parent.mkdir(mode=0o700)
        project_settings.write_text(
            json.dumps({"plugin_sources": ["old-source"]}), encoding="utf-8"
        )
    elif legacy_kind == "custom_global_settings":
        custom_global_settings = tmp_path / "custom-global" / "settings.json"
        custom_global_settings.parent.mkdir(mode=0o700)
        custom_global_settings.write_text(
            json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
        )
    elif legacy_kind == "custom_project_settings":
        custom_project_settings = workspace / "custom-project" / "settings.json"
        custom_project_settings.parent.mkdir(mode=0o700)
        custom_project_settings.write_text(
            json.dumps({"plugin_sources": ["old-source"]}), encoding="utf-8"
        )
    elif legacy_kind == "desired_state":
        lifecycle.root.mkdir(parents=True, mode=0o700)
        lifecycle.desired_state.write_bytes(b"old Desired State must survive\n")
    else:
        lifecycle.package_root.mkdir(parents=True, mode=0o700)
        (lifecycle.package_root / "package-lock.json").write_bytes(
            b"old Package lock must survive\n"
        )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    services = None
    if legacy_kind in {"custom_global_settings", "custom_project_settings"}:
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=(
                    custom_global_settings
                    if legacy_kind == "custom_global_settings"
                    else tmp_path / "custom-global" / "settings.json"
                ),
                project_settings_path=(
                    custom_project_settings
                    if legacy_kind == "custom_project_settings"
                    else workspace / "custom-project" / "settings.json"
                ),
            )
        )

    def snapshot() -> tuple[tuple[str, bytes | None], ...]:
        return tuple(
            sorted(
                (
                    path.relative_to(tmp_path).as_posix(),
                    path.read_bytes() if path.is_file() else None,
                )
                for path in tmp_path.rglob("*")
            )
        )

    before = snapshot()
    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=global_settings,
        ),
        pytest.raises(RuntimeError, match="pre-B workspace is unsupported"),
    ):
        create_agent_session(session_manager=manager, services=services)
    assert snapshot() == before


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_ordinary_session_initializes_fresh_workspace_in_b_product(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
    selection = CodingFencedProductApplicationSelection()
    try:
        with (
            patch(
                "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
                return_value=lifecycle,
            ),
            patch(
                "loushang.coding.package_product_runtime.default_global_settings_path",
                return_value=tmp_path / "global-settings.json",
            ),
            patch(
                "loushang.coding.package_product_runtime.version",
                return_value="2.0.0",
            ),
        ):
            factory = selection.factory_for_session(manager, settings_manager=settings)
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
            second = selection.factory_for_session(manager, settings_manager=settings)
            assert second is not None
            second.dispose_unbound_runtime()
        assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
        assert not lifecycle.desired_state.exists()
        assert not (lifecycle.package_root / "package-lock.json").exists()
    finally:
        selection.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_live_product_owner_refuses_replaced_state_root_with_identical_journals(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
    selection = CodingFencedProductApplicationSelection()
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
        try:
            factory = selection.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            factory.dispose_unbound_runtime()
            owner = selection._owners[workspace]
            product = owner.runtime_owner.product_owner
            inventory = product.desired_state.snapshot()
            arch = next(
                item
                for item in inventory.installations
                if item.installation_key.plugin_id == "coding.arch.default"
            )
            disable = PluginManagementCommandV1(
                action="disable",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="operator:state-root-substitution",
                    idempotency_key="operator:state-root-substitution",
                    expected_inventory_revision=inventory.inventory_revision,
                    installation_key=arch.installation_key,
                    desired_state="installed_disabled",
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
            state_root = product.state_root
            replacement = state_root.with_name("product-state-copy")
            original = state_root.with_name("product-state-original")
            shutil.copytree(state_root, replacement)
            state_root.rename(original)
            replacement.rename(state_root)
            try:
                before = {
                    path.relative_to(state_root): path.read_bytes()
                    for path in state_root.rglob("*")
                    if path.is_file()
                }
                with pytest.raises(ValueError, match="state root changed"):
                    owner.epoch_runtime.assert_current()
                with pytest.raises(ValueError, match="state root changed"):
                    product.assert_root_gc_authority_current()
                with pytest.raises(ValueError, match="GC parent directory changed"):
                    product.management.submit(disable)
                assert {
                    path.relative_to(state_root): path.read_bytes()
                    for path in state_root.rglob("*")
                    if path.is_file()
                } == before
            finally:
                state_root.rename(replacement)
                original.rename(state_root)
        finally:
            selection.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_ordinary_product_repairs_only_builtin_session_orphan(
    tmp_path: Path,
) -> None:
    from loushang.coding.package_epoch_layout import resolve_coding_package_epoch_layout

    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
    selection = CodingFencedProductApplicationSelection()
    try:
        with (
            patch(
                "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
                return_value=lifecycle,
            ),
            patch(
                "loushang.coding.package_product_runtime.default_global_settings_path",
                return_value=tmp_path / "global-settings.json",
            ),
            patch(
                "loushang.coding.package_product_runtime.version",
                return_value="2.0.0",
            ),
        ):
            factory = selection.factory_for_session(manager, settings_manager=settings)
            factory.dispose_unbound_runtime()
    finally:
        selection.close()

    epoch = resolve_coding_package_epoch_layout(lifecycle)
    runtime_id = (
        "coding-session:"
        + sha256(manager.get_header().conversation_id.encode()).hexdigest()
    )
    child = """
import os
import sys
from pathlib import Path
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
owner = PackageProductPosixFencedRuntimeOwner.open(
    authority_root=Path(sys.argv[1]),
    control_root=Path(sys.argv[2]),
    store_id=sys.argv[3],
    epochs_root_name=sys.argv[4],
)
owner.issue_runtime_lease(
    runtime_id=sys.argv[5], runtime_version="2.0.0", runtime_protocol_epoch=2
)
os._exit(0)
"""
    subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(epoch.authority_root),
            str(epoch.control_root),
            epoch.store_id,
            epoch.epochs_root_name,
            runtime_id,
        ],
        check=True,
        timeout=20,
    )
    owner = open_coding_fenced_product_application_owner(
        lifecycle,
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
    )
    try:
        registry = owner.epoch_runtime.registry
        (orphan,) = registry.review_orphans(store_id=registry.store_id)
        assert orphan.runtime_id == runtime_id
        worker_evidence = (
            owner.runtime_owner.product_owner.state_root / "worker-start-gates.jsonl"
        )
        worker_evidence.write_bytes(b"")
        try:
            with pytest.raises(
                RuntimeError, match="Worker recovery requires explicit review"
            ):
                owner.factory_for_session(manager)
            assert registry.review_orphans(store_id=registry.store_id) == (orphan,)
        finally:
            worker_evidence.unlink()
        factory = owner.factory_for_session(manager)
        factory.dispose_unbound_runtime()
        assert registry.review_orphans(store_id=registry.store_id) == ()
    finally:
        owner.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_ordinary_session_retries_interrupted_fresh_product_bootstrap(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
    original_submit = PluginManagementService.submit
    interrupted = False

    def interrupt_once(
        service: PluginManagementService, command: PluginManagementCommandV1
    ):
        nonlocal interrupted
        if command.action == "enable" and not interrupted:
            interrupted = True
            raise RuntimeError("injected first enable interruption")
        return original_submit(service, command)

    with (
        patch(
            "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
            return_value=lifecycle,
        ),
        patch(
            "loushang.coding.package_product_runtime.default_global_settings_path",
            return_value=tmp_path / "global-settings.json",
        ),
        patch(
            "loushang.coding.package_product_runtime.version",
            return_value="2.0.0",
        ),
    ):
        first = CodingFencedProductApplicationSelection()
        try:
            with patch.object(PluginManagementService, "submit", interrupt_once):
                with pytest.raises(
                    RuntimeError, match="injected first enable interruption"
                ):
                    first.factory_for_session(manager, settings_manager=settings)
        finally:
            first.close()
        assert interrupted
        assert reopen_coding_package_cutover(lifecycle).disposition == "fenced"
        retry = CodingFencedProductApplicationSelection()
        try:
            factory = retry.factory_for_session(manager, settings_manager=settings)
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
            retry.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_ordinary_session_preserves_operator_disable_after_fresh_b_bootstrap(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
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
        patch(
            "loushang.coding.package_product_runtime.version",
            return_value="2.0.0",
        ),
    ):
        first = CodingFencedProductApplicationSelection()
        try:
            factory = first.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            factory.dispose_unbound_runtime()
        finally:
            first.close()
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version="2.0.0",
            runtime_protocol_epoch=2,
        )
        try:
            product = owner.runtime_owner.product_owner
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
                        operation_id="operator:disable-auto-base",
                        idempotency_key="operator:disable-auto-base",
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
        reopened = CodingFencedProductApplicationSelection()
        try:
            factory = reopened.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            factory.dispose_unbound_runtime()
            product = reopened._owners[workspace].runtime_owner.product_owner
            state = product.desired_state.snapshot()
            base = next(
                item
                for item in state.installations
                if item.installation_key.plugin_id == "coding.base"
            )
            assert base.selection.desired_state == "installed_disabled"
        finally:
            reopened.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_ordinary_session_does_not_bootstrap_old_snapshot_with_fresh_namespace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions", cwd=str(workspace), persist=False
        )
    )
    global_settings = tmp_path / "global-settings.json"
    global_settings.write_text(
        json.dumps({"disabled_plugins": ["coding.base"]}), encoding="utf-8"
    )
    settings = SettingsManager(
        global_settings_path=global_settings,
        project_settings_path=workspace / ".loushang" / "settings.json",
    )
    epoch = prepare_coding_package_cutover_roots(lifecycle)
    namespace_id = sha256(
        b"loushang.coding-fresh-product-epoch/v1\0" + epoch.store_id.encode()
    ).hexdigest()
    cutover = prepare_and_cutover_coding_package_store_from_legacy(
        lifecycle,
        settings,
        namespace_id=namespace_id,
        minimum_runtime_version="2.0.0",
        minimum_runtime_protocol_epoch=2,
    )
    assert cutover.attempt.result.disposition == "fenced"
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
            factory = selection.factory_for_session(manager, settings_manager=settings)
            assert factory is not None
            factory.dispose_unbound_runtime()
        assert not selection._owners[
            workspace
        ].runtime_owner.product_owner.desired_state.transitions()
    finally:
        selection.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_ordinary_session_requires_existing_workspace_before_first_b_writes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "missing-workspace"
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
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
                "loushang.coding.package_product_runtime.default_global_settings_path",
                return_value=tmp_path / "global-settings.json",
            ),
            pytest.raises(ValueError, match="existing directory"),
        ):
            selection.factory_for_session(manager)
        assert not workspace.exists()
        assert not lifecycle.root.exists()
        assert not lifecycle.package_root.exists()
    finally:
        selection.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_runtime_session_refuses_effective_old_settings_without_product_writes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    lifecycle = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session-state", cwd=workspace
    )
    custom_settings = tmp_path / "custom-global" / "settings.json"
    custom_settings.parent.mkdir(mode=0o700)
    old_bytes = b'{"disabled_plugins":["coding.base"]}'
    custom_settings.write_bytes(old_bytes)
    services = create_services(
        settings_manager=SettingsManager(global_settings_path=custom_settings)
    )

    async def scenario() -> None:
        runtime = create_agent_session_runtime(
            session_dir=tmp_path / "sessions", services=services, persist=False
        )
        try:
            with pytest.raises(RuntimeError, match="pre-B workspace is unsupported"):
                await runtime.create_session(cwd=str(workspace))
        finally:
            await runtime.dispose()

    with patch(
        "loushang.coding.package_product_runtime.resolve_coding_plugin_lifecycle_state_layout",
        return_value=lifecycle,
    ):
        asyncio.run(scenario())
    assert custom_settings.read_bytes() == old_bytes
    assert not lifecycle.root.exists()
    assert not lifecycle.package_root.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux rooted cutover")
def test_fenced_product_routes_package_entrances_and_preserves_operator_disable(
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
        assert session.package_product_lifecycle_mode == "enforced"
        assert session.package_product_binding_id is not None
        lifecycle_owner = session._package_controller.product_lifecycle
        assert lifecycle_owner is not None
        missing_source = str(workspace / "missing-plugin.whl")
        with (
            patch.object(
                lifecycle_owner, "route", wraps=lifecycle_owner.route
            ) as routed,
            patch.object(
                PackageOperationsRuntime,
                "_materialize_legacy",
                side_effect=AssertionError("legacy materialization fallback"),
            ),
            patch.object(
                PackageOperationsRuntime,
                "_remove_legacy",
                side_effect=AssertionError("legacy deletion fallback"),
            ),
        ):
            requests: dict[PackageProductLifecycleAction, PackageLifecycleRequest] = {
                "install": PackageLifecycleRequest(
                    install=(missing_source,), scope="project"
                ),
                "materialize": PackageLifecycleRequest(
                    materialize=(missing_source,), scope="project"
                ),
                "update": PackageLifecycleRequest(
                    update=(missing_source,), scope="project"
                ),
                "remove": PackageLifecycleRequest(
                    remove=(missing_source,), scope="project"
                ),
                "uninstall": PackageLifecycleRequest(
                    uninstall=(missing_source,), scope="project"
                ),
            }
            for action, request in requests.items():
                try:
                    direct = asyncio.run(
                        session.execute_package_lifecycle(
                            action,
                            missing_source,
                            entrypoint="session",
                            operation_id=f"product-default-session-{action}",
                            scope="project",
                        )
                    )
                except RuntimeError:
                    pass
                else:
                    assert direct["lifecycle"] == "failed"
                with pytest.raises(PackageLifecycleError):
                    asyncio.run(
                        run_package_lifecycle(
                            session,
                            request,
                        )
                    )
                rpc_output = StringIO()
                rpc = RpcPackageCommands(
                    runtime=session,
                    get_session=lambda: session,
                    output=RpcOutput(rpc_output),
                )
                asyncio.run(
                    cast(
                        Any,
                        dict(rpc.bindings())[f"{action}_package"](
                            f"product-default-rpc-{action}",
                            {"source": missing_source, "scope": "project"},
                        ),
                    )
                )
                assert json.loads(rpc_output.getvalue())["success"] is False
            sync_uninstall = session.uninstall_package(missing_source, scope="project")
            assert sync_uninstall["lifecycle"] == "failed"
            assert routed.call_count == 16
        with patch.object(type(session), "execute_package_lifecycle", None):
            with pytest.raises(
                PackageLifecycleError,
                match="Package Product lifecycle executor is unavailable",
            ):
                asyncio.run(
                    run_package_lifecycle(
                        session,
                        PackageLifecycleRequest(
                            install=(missing_source,), scope="project"
                        ),
                    )
                )
            missing_rpc_output = StringIO()
            missing_rpc = RpcPackageCommands(
                runtime=session,
                get_session=lambda: session,
                output=RpcOutput(missing_rpc_output),
            )
            asyncio.run(
                cast(
                    Any,
                    dict(missing_rpc.bindings())["install_package"](
                        "product-default-rpc-missing-executor",
                        {"source": missing_source, "scope": "project"},
                    ),
                )
            )
            assert json.loads(missing_rpc_output.getvalue())["success"] is False
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
