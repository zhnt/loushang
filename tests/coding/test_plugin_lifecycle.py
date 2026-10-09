from __future__ import annotations

import asyncio
import gc
import json
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

import loushang.coding._base_plugin as base_plugin_module
import loushang.coding._plugin_lifecycle as plugin_lifecycle_module
from loushang.ai.model import Capabilities, Model
from loushang.coding._base_plugin import (
    CodingBasePluginAssemblyError,
    coding_base_plugin_root,
    prepare_managed_coding_base_plugin_assembly,
)
from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleError,
    build_coding_plugin_lifecycle,
    build_coding_plugin_management_application,
    package_revision_ref,
    project_coding_plugin_enablement_compatibility,
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.package_epoch_layout import (
    resolve_coding_lifecycle_pre_b_members,
    resolve_coding_package_epoch_layout,
    resolve_coding_package_pre_b_store_members,
)
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginLifecycleError,
    PluginManagementApplicationCommandV1,
    PluginManagementCommandV1,
    PluginManagementUpdateCommandV2,
    PluginPackageLifecycleError,
)
from loushang.harness.resources.packages.plugin_lifecycle.epoch_fence import (
    PackageEpochFenceJournal,
    PackageEpochFenceRequestV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_pre_fence_registration import (
    PackagePosixPreFenceRegistrationOwner,
)
from loushang.harness.resources.plugins import (
    PluginResolutionAuthority,
    PluginSource,
)
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
)


def _materializer(root: Path) -> CodingPackageMaterializer:
    return CodingPackageMaterializer(
        install_root=root / "packages",
        plugin_revision_root=root / "revisions",
    )


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _lifecycle(root: Path):
    lifecycle = build_coding_plugin_lifecycle(
        resolve_ephemeral_coding_plugin_lifecycle_state_layout(
            root / "state",
            cwd=root / "workspace",
        )
    )
    lifecycle.reconcile_retirements()
    lifecycle.complete_startup_recovery()
    return lifecycle


def test_coding_pre_b_package_mapping_rejects_unmapped_member(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    layout.package_root.mkdir(parents=True, mode=0o700)
    (layout.package_root / "installed").mkdir(mode=0o700)
    (layout.package_root / "plugin-revisions").mkdir(mode=0o700)
    (layout.package_root / "package-lock.json").write_bytes(b"{}\n")
    (layout.package_root / "package-lock.json.lock").write_bytes(b"")
    mapping = resolve_coding_package_pre_b_store_members(layout)
    assert mapping.domain_members() == {
        "store_bytes": ("installed", "plugin-revisions"),
        "binding_history": ("package-lock.json",),
        "lock_history": ("package-lock.json", "package-lock.json.lock"),
    }
    (layout.package_root / "unknown-state").write_bytes(b"unaccounted")
    with pytest.raises(ValueError, match="unmapped members"):
        resolve_coding_package_pre_b_store_members(layout)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pre-fence lifecycle"
)
def test_coding_pre_b_lifecycle_mapping_covers_real_owner_state(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    lifecycle = build_coding_plugin_lifecycle(layout, startup_id="pre-b-inventory")
    try:
        lifecycle.reconcile_retirements()
        lifecycle.complete_startup_recovery()
    finally:
        lifecycle.release_owned_process_startup_lease()
    mapping = resolve_coding_lifecycle_pre_b_members(layout)
    domains = mapping.domain_members()
    assert set(domains) == {"desired_state", "enablement_state", "instance_state"}
    assert {name for members in domains.values() for name in members} == {
        path.name for path in layout.root.iterdir()
    }
    assert "desired-state.jsonl.lock" in domains["desired_state"]
    assert "process-startups" in domains["instance_state"]
    (layout.root / "unmapped-state.jsonl").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="unmapped members"):
        resolve_coding_lifecycle_pre_b_members(layout)


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pre-fence owner"
)
def test_coding_legacy_lifecycle_registers_before_state_and_rejects_fence(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    lifecycle = build_coding_plugin_lifecycle(
        layout, startup_id="legacy-coding-runtime"
    )
    fences = PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl")
    owner = PackagePosixPreFenceRegistrationOwner(
        epoch.authority_root, store_id=epoch.store_id, fences=fences
    )
    try:
        with owner.exclusive_quiescence(store_id=epoch.store_id) as live:
            assert len(live.active_registration_ids) == 1
    finally:
        lifecycle.release_owned_process_startup_lease()
    with owner.exclusive_quiescence(store_id=epoch.store_id) as released:
        assert released.active_registration_ids == ()

    fences.publish(
        PackageEpochFenceRequestV1.create(
            store_id=epoch.store_id,
            prior_fence=None,
            legacy_root_identity="a" * 64,
            fenced_root_identity="b" * 64,
            namespace_id="c" * 64,
            minimum_runtime_version="2.0.0",
            minimum_runtime_protocol_epoch=2,
            quiescence_receipt_id="d" * 64,
            snapshot_receipt_id="e" * 64,
            root_switch_receipt_id="f" * 64,
        )
    )
    with pytest.raises(CodingPluginLifecycleError) as refused:
        build_coding_plugin_lifecycle(layout, startup_id="legacy-coding-runtime")
    assert refused.value.code == "package_runtime_epoch_unsupported"
    with pytest.raises(CodingPluginLifecycleError) as management_refused:
        build_coding_plugin_management_application(layout)
    assert management_refused.value.code == "package_runtime_epoch_unsupported"


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux pre-fence owner"
)
def test_coding_management_application_holds_pre_fence_registration(
    tmp_path: Path,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "session", cwd=tmp_path / "workspace"
    )
    epoch = resolve_coding_package_epoch_layout(layout)
    build_coding_plugin_management_application(layout)
    owner = PackagePosixPreFenceRegistrationOwner(
        epoch.authority_root,
        store_id=epoch.store_id,
        fences=PackageEpochFenceJournal(epoch.control_root / "epoch.jsonl"),
    )
    try:
        with owner.exclusive_quiescence(store_id=epoch.store_id) as live:
            assert len(live.active_registration_ids) == 1
    finally:
        plugin_lifecycle_module._release_process_startup_lease(
            layout, startup_id=plugin_lifecycle_module._CODING_PLUGIN_RUNTIME_BOOT_ID
        )


def _copy_base(root: Path, name: str) -> Path:
    target = root / name
    shutil.copytree(coding_base_plugin_root(), target)
    return target


def _platform_paths(root: Path) -> PlatformPaths:
    return PlatformPaths(
        home=root,
        data=root / "data",
        state=root / "state",
        cache=root / "cache",
        runtime=root / "runtime",
        temporary=root / "tmp",
    )


def _package_ref(plugin_id: str = "coding.base"):
    return package_revision_ref(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity=f"embedded:{plugin_id}",
    )


def test_product_management_writer_observes_reserved_package_revision(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    assert not lifecycle.gc_writer_epoch_ready()
    lifecycle.prepare_gc_writer_epoch()
    lifecycle.prepare_gc_writer_epoch()
    assert lifecycle.gc_writer_epoch_ready()
    project_coding_plugin_enablement_compatibility(lifecycle.layout)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    for action, revision, desired_state, selected in (
        ("install", 0, "installed_disabled", package),
        ("remove", 1, "absent", None),
    ):
        lifecycle.management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=f"product-gc-{action}",
                    idempotency_key=f"product-gc-{action}",
                    expected_inventory_revision=revision,
                    installation_key=key,
                    desired_state=desired_state,
                    package_revision=selected,
                    actor_id="test:operator",
                    policy_revision="test-policy-v1",
                    approval_reference="test",
                ),
            )
        )
    candidate = lifecycle.packages.gc_candidates()[0]
    lifecycle._gc_reservations.reserve(
        candidate,
        lifecycle=lifecycle.packages,
        operation_id="product-gc-reserve",
        idempotency_key="product-gc-reserve",
    )
    application = build_coding_plugin_management_application(lifecycle.layout)
    with pytest.raises(PluginLifecycleError) as caught:
        application.commands.submit(
            PluginManagementApplicationCommandV1(
                correlation_id="product-gc-selection",
                command=PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="product-gc-reinstall",
                        idempotency_key="product-gc-reinstall",
                        expected_inventory_revision=2,
                        installation_key=key,
                        desired_state="installed_disabled",
                        package_revision=package,
                        actor_id="test:operator",
                        policy_revision="test-policy-v1",
                        approval_reference="test",
                    ),
                ),
            )
        )
    assert caught.value.code == "plugin_package_gc_reserved"


def test_product_gc_writer_epoch_requires_completed_startup_recovery(
    tmp_path: Path,
) -> None:
    lifecycle = build_coding_plugin_lifecycle(
        resolve_ephemeral_coding_plugin_lifecycle_state_layout(
            tmp_path / "state", cwd=tmp_path / "workspace"
        ),
        startup_id="gc-epoch-unrecovered",
    )
    with pytest.raises(PluginPackageLifecycleError) as caught:
        lifecycle.prepare_gc_writer_epoch()
    assert caught.value.code == "plugin_package_recovery_incomplete"
    assert not lifecycle.gc_writer_epoch_ready()


_TEST_OWNER_CONTRIBUTIONS = (
    ("commands.session", ("coding.standard",)),
    ("resources.prompt", ("prompt-standard",)),
    ("resources.skill", ("skill-standard",)),
    ("tools.workspace", ("coding.builtin",)),
)


def _disable_or_remove(
    lifecycle,
    *,
    action: str,
    plugin_id: str = "coding.base",
) -> object:
    key = lifecycle.installation_key(plugin_id)
    snapshot = lifecycle.desired.snapshot()
    desired_state = "installed_disabled" if action == "disable" else "absent"
    event = lifecycle.management.submit(
        PluginManagementCommandV1(
            action=action,
            mutation=PluginDesiredStateMutationV1(
                operation_id=f"test-{action}:{snapshot.inventory_revision}",
                idempotency_key=f"test-{action}:{snapshot.inventory_revision}",
                expected_inventory_revision=snapshot.inventory_revision,
                installation_key=key,
                desired_state=desired_state,
                package_revision=None,
                actor_id="test:operator",
                policy_revision="test-policy-v1",
                approval_reference="test",
            ),
        )
    )
    assert event.result is not None
    assert event.result.disposition == "succeeded"
    return event


def test_capability_plugin_refuses_legacy_disable_before_product_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        with pytest.raises(RuntimeError, match="pre-B workspace is unsupported"):
            create_agent_session(
                session_manager=manager,
                model=_model(),
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(
                            capabilities={
                                "coding.arch": "always",
                                "coding.lsp": "disabled",
                            },
                            disabled_plugins=("coding.arch.default",),
                        )
                    )
                ),
                composition_set="coding-architecture",
            )

    asyncio.run(scenario())
    assert not layout.root.exists()
    assert not layout.package_root.exists()


@pytest.mark.parametrize("action", ("disable", "remove"))
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_arch_management_change_pins_active_session_and_blocks_new_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from importlib.metadata import version

    from loushang.coding._capability_plugin_composition import (
        CodingCapabilityPluginCompositionError,
    )
    from loushang.coding.arch import INSPECT_IMPORT_GRAPH_TOOL_NAME
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("import os\n", encoding="utf-8")

    async def scenario() -> None:
        settings = SettingsManager(
            ControlConfig(
                capabilities={"coding.arch": "always", "coding.lsp": "always"}
            )
        )
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-a",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(settings_manager=settings),
            composition_set="coding-architecture",
        )
        await active.prepare_model_call_runtime()
        assembly = active._coding_capability_plugin_assembly
        assert assembly is not None
        assert assembly.tool_owner_for("coding.arch.default") is not None
        before_tools = tuple(active.get_active_tool_names())
        assert INSPECT_IMPORT_GRAPH_TOOL_NAME in before_tools

        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            inventory = product.desired_state.snapshot()
            arch = next(
                item
                for item in inventory.installations
                if item.installation_key.plugin_id == "coding.arch.default"
            )
            changed = product.management.submit(
                PluginManagementCommandV1(
                    action=action,
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=f"operator:{action}-arch",
                        idempotency_key=f"operator:{action}-arch",
                        expected_inventory_revision=inventory.inventory_revision,
                        installation_key=arch.installation_key,
                        desired_state=(
                            "installed_disabled" if action == "disable" else "absent"
                        ),
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert changed.result is not None
            assert changed.result.disposition == "succeeded"
            with pytest.raises(
                CodingCapabilityPluginCompositionError,
                match="requires restart",
            ):
                await active.prepare_model_call_runtime()
            diagnostics = [
                item
                for item in active.get_session_diagnostics()
                if item.code == "coding_capability_product_restart_required"
            ]
            assert len(diagnostics) == 1
            assert diagnostics[0].details["pluginId"] == "coding.arch.default"
            assert tuple(active.get_active_tool_names()) == before_tools

            second_manager = await SessionManager.new(
                session_dir=tmp_path / "sessions-b",
                cwd=str(workspace),
                persist=True,
            )
            replacement = create_agent_session(
                session_manager=second_manager,
                model=_model(),
                services=create_services(settings_manager=settings),
                composition_set="coding-architecture",
            )
            try:
                replacement_assembly = replacement._coding_capability_plugin_assembly
                assert replacement_assembly is not None
                assert (
                    replacement_assembly.tool_owner_for("coding.lsp.default")
                    is not None
                )
                assert (
                    replacement_assembly.tool_owner_for("coding.arch.default") is None
                )
                assert INSPECT_IMPORT_GRAPH_TOOL_NAME not in {
                    tool.name for tool in replacement.get_all_tools()
                }
            finally:
                await replacement.dispose()
        finally:
            await active.dispose()
            owner.close()

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_base_lsp_and_arch_share_one_session_runtime_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        session = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={
                            "coding.arch": "always",
                            "coding.lsp": "always",
                        }
                    )
                )
            ),
            composition_set="coding-architecture",
        )
        await session.prepare_model_call_runtime()
        base = session._coding_base_product_compilation
        capability = session._coding_capability_plugin_assembly
        assert base is not None
        assert capability is not None
        assert capability.tool_owner_for("coding.lsp.default") is not None
        assert capability.tool_owner_for("coding.arch.default") is not None
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            snapshot = registry.snapshot(store_id=registry.store_id)
            assert len(snapshot.active_leases) == 1
            assert snapshot.active_leases[0].runtime_id.startswith("coding-session:")
            await session.dispose()
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
                registry.snapshot(store_id=registry.store_id)
            assert caught.value.code == "package_epoch_lease_absent"
        finally:
            await session.dispose()
            owner.close()

    asyncio.run(scenario())


def _managed_base(
    root: Path,
    *,
    session_id: str,
    materializer: CodingPackageMaterializer,
    lifecycle,
):
    return prepare_managed_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id=session_id,
        package_materializer=materializer,
        lifecycle=lifecycle,
    )


def test_managed_base_migrates_legacy_disable_without_mounting(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")

    assembly = prepare_managed_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="legacy-disabled-base",
        package_materializer=_materializer(tmp_path),
        lifecycle=lifecycle,
        legacy_disabled=True,
    )

    assert assembly is None
    migration = lifecycle.enablement_migrations.journal.snapshot(key)
    assert migration is not None
    assert migration.phase == "compatibility_window"
    assert migration.disposition == "seeded"
    assert (
        lifecycle.desired.snapshot().installation(key).selection.desired_state
        == "installed_disabled"
    )


def test_managed_base_receipts_existing_disabled_history_without_resurrection(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    _disable_or_remove(lifecycle, action="disable")

    assembly = prepare_managed_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="authoritative-disabled-base",
        package_materializer=_materializer(tmp_path),
        lifecycle=lifecycle,
    )

    assert assembly is None
    migration = lifecycle.enablement_migrations.journal.snapshot(key)
    assert migration is not None
    assert migration.disposition == "already_authoritative"
    assert (
        lifecycle.desired.snapshot().installation(key).selection.desired_state
        == "installed_disabled"
    )


def test_first_party_default_uses_management_once_and_replays_without_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _copy_base(tmp_path, "mutable-base")
    monkeypatch.setattr(base_plugin_module, "coding_base_plugin_root", lambda: source)
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)

    first = _managed_base(
        tmp_path,
        session_id="managed-1",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    assert first is not None
    key = lifecycle.installation_key("coding.base")
    state = lifecycle.desired.snapshot().installation(key)
    assert state.selection.desired_state == "installed_enabled"
    assert len(lifecycle.desired.transitions()) == 2
    assert first.plan_seed.plan.context.instance_revision_refs == (
        state.selection.instance_revision_ref,
    )
    pinned_root = first.package.root
    shutil.rmtree(source)

    second = _managed_base(
        tmp_path,
        session_id="managed-2",
        materializer=_materializer(tmp_path),
        lifecycle=_lifecycle(tmp_path),
    )
    assert second is not None
    try:
        assert len(lifecycle.desired.transitions()) == 2
        assert second.package.root == pinned_root
        assert second.binding.source == str(source.resolve())
        assert second.package.revision_handle.closed is False
        assert second.evaluate_management_change().disposition == "no_change"
    finally:
        second.close()
        first.close()


def test_first_party_default_resumes_its_own_crash_interrupted_install(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    event = lifecycle.management.submit(
        PluginManagementCommandV1(
            action="install",
            mutation=PluginDesiredStateMutationV1(
                operation_id="coding-default-crash-install",
                idempotency_key="coding-default-crash-install",
                expected_inventory_revision=0,
                installation_key=key,
                desired_state="installed_disabled",
                package_revision=package,
                actor_id="product:coding",
                policy_revision="coding-plugin-lifecycle-v1",
                approval_reference="coding-first-party-default",
            ),
        )
    )
    assert event.result is not None
    assert event.result.disposition == "succeeded"

    _lifecycle(tmp_path).bootstrap_first_party_default(key, package)

    state = lifecycle.desired.snapshot().installation(key)
    assert state.selection.desired_state == "installed_enabled"
    assert state.selection.package_revision == package
    assert len(lifecycle.desired.transitions()) == 2


def test_first_party_default_never_overrides_operator_remove_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    original = type(lifecycle)._submit_default
    raced = False

    def race(self, submitted_key, **kwargs):
        nonlocal raced
        if self is lifecycle and kwargs["action"] == "install" and not raced:
            raced = True
            install = self.management.submit(
                PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator-install",
                        idempotency_key="operator-install",
                        expected_inventory_revision=0,
                        installation_key=key,
                        desired_state="installed_disabled",
                        package_revision=package,
                        actor_id="test:operator",
                        policy_revision="test-policy-v1",
                        approval_reference="test",
                    ),
                )
            )
            assert install.result is not None
            assert install.result.disposition == "succeeded"
            _disable_or_remove(self, action="remove")
        return original(self, submitted_key, **kwargs)

    monkeypatch.setattr(type(lifecycle), "_submit_default", race)
    lifecycle.bootstrap_first_party_default(key, package)

    state = lifecycle.desired.snapshot().installation(key)
    assert state.selection.desired_state == "absent"
    assert len(lifecycle.desired.transitions()) == 2


def test_first_party_default_retries_unrelated_inventory_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    package = _package_ref()
    original = type(lifecycle)._submit_default
    raced = False

    def race(self, submitted_key, **kwargs):
        nonlocal raced
        if self is lifecycle and kwargs["action"] == "install" and not raced:
            raced = True
            snapshot = self.desired.snapshot()
            other_key = self.installation_key("coding.other")
            event = self.management.submit(
                PluginManagementCommandV1(
                    action="install",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="other-install",
                        idempotency_key="other-install",
                        expected_inventory_revision=snapshot.inventory_revision,
                        installation_key=other_key,
                        desired_state="installed_disabled",
                        package_revision=_package_ref("coding.other"),
                        actor_id="test:operator",
                        policy_revision="test-policy-v1",
                        approval_reference="test",
                    ),
                )
            )
            assert event.result is not None
            assert event.result.disposition == "succeeded"
        return original(self, submitted_key, **kwargs)

    monkeypatch.setattr(type(lifecycle), "_submit_default", race)
    lifecycle.bootstrap_first_party_default(key, package)

    assert (
        lifecycle.desired.snapshot().installation(key).selection.desired_state
        == "installed_enabled"
    )
    assert len(lifecycle.desired.transitions()) == 3


def test_concurrent_sessions_share_exact_activation_but_not_live_lease(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    barrier = threading.Barrier(2)

    def acquire(sequence: int):
        current = _lifecycle(tmp_path)
        barrier.wait()
        return current.acquire_session(
            key,
            session_id=f"session-{sequence}",
            lease_attempt_id=f"attempt-{sequence}",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = tuple(executor.map(acquire, (1, 2)))
    try:
        assert leases[0].instance_revision_ref == leases[1].instance_revision_ref
        assert leases[0].family.family_id != leases[1].family.family_id
        assert len(lifecycle.instances.snapshot().open_families) == 3
    finally:
        leases[0].close()
        leases[1].close()


def test_same_session_resume_is_process_exclusive_and_retryable(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    first = lifecycle.acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-first",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    contender = _lifecycle(tmp_path)

    with pytest.raises(CodingPluginLifecycleError) as caught:
        contender.acquire_session(
            key,
            session_id="shared-conversation",
            lease_attempt_id="attempt-concurrent",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        )

    assert caught.value.code == "coding_plugin_session_already_active"
    assert len(lifecycle.instances.snapshot().open_families) == 2
    first.close()

    resumed = contender.acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-after-close",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    resumed.close()


def test_same_session_owner_reenters_until_its_last_process_lease_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    owner_id = "session-manager:shared"
    first = lifecycle.acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-first",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id=owner_id,
    )
    second = _lifecycle(tmp_path).acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-second",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id=owner_id,
    )
    lease_path = plugin_lifecycle_module._session_owner_lease_path(
        lifecycle.layout,
        session_id="shared-conversation",
    )
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        state = plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[lease_path]
        assert state.owner_id == owner_id
        assert state.references == 2

    first.close()
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        assert (
            plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[lease_path].references
            == 1
        )
    with pytest.raises(CodingPluginLifecycleError) as caught:
        _lifecycle(tmp_path).acquire_session(
            key,
            session_id="shared-conversation",
            lease_attempt_id="attempt-contender",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
            session_owner_id="session-manager:other",
        )
    assert caught.value.code == "coding_plugin_session_already_active"

    release_started = threading.Event()
    allow_release = threading.Event()
    replacement_started = threading.Event()
    replacement_lock_attempted = threading.Event()

    class BlockingLease:
        def __init__(self, underlying) -> None:
            self.underlying = underlying

        def __exit__(self, *args) -> None:
            release_started.set()
            assert allow_release.wait(timeout=20)
            self.underlying.__exit__(*args)

    class ObservableLock:
        def __init__(self, underlying) -> None:
            self.underlying = underlying

        def __enter__(self):
            if replacement_started.is_set():
                replacement_lock_attempted.set()
            self.underlying.acquire()
            return self

        def __exit__(self, *_args) -> None:
            self.underlying.release()

    monkeypatch.setattr(
        plugin_lifecycle_module,
        "_PROCESS_SESSION_OWNER_LEASES_LOCK",
        ObservableLock(plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK),
    )

    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        state = plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[lease_path]
        state.lease = BlockingLease(state.lease)
    replacement_lifecycle = _lifecycle(tmp_path)

    def acquire_replacement():
        replacement_started.set()
        return replacement_lifecycle.acquire_session(
            key,
            session_id="shared-conversation",
            lease_attempt_id="attempt-replacement",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
            session_owner_id=owner_id,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        close_future = executor.submit(second.close)
        assert release_started.wait(timeout=20)
        replacement_future = executor.submit(acquire_replacement)
        assert replacement_lock_attempted.wait(timeout=20)
        assert replacement_future.done() is False
        allow_release.set()
        close_future.result(timeout=20)
        replacement = replacement_future.result(timeout=20)

    replacement.close()
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        assert lease_path not in plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES
    resumed = _lifecycle(tmp_path).acquire_session(
        key,
        session_id="shared-conversation",
        lease_attempt_id="attempt-after-close",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id="session-manager:other",
    )
    resumed.close()


def test_same_session_manager_rejects_concurrent_product_runtime_until_dispose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new_with_composition(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )
        first = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=services,
        )
        try:
            with pytest.raises(
                RuntimeError, match="Package runtime identity is already registered"
            ):
                create_agent_session(
                    session_manager=manager,
                    model=_model(),
                    services=services,
                )
            await first.prepare_model_call_runtime()
            await manager.append_message(
                UserMessage(
                    role="user",
                    content=[TextPart(type="text", text="product runtime lease")],
                    timestamp=0.0,
                )
            )
        finally:
            await first.dispose()
        resumed_manager = await SessionManager.load(manager.get_session_file())
        resumed = create_agent_session(
            session_manager=resumed_manager,
            model=_model(),
            services=services,
        )
        try:
            await resumed.prepare_model_call_runtime()
        finally:
            await resumed.dispose()

    asyncio.run(scenario())


def test_session_owner_unlock_failure_drops_invalid_process_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    lease = lifecycle.acquire_session(
        key,
        session_id="unlock-failure",
        lease_attempt_id="attempt-failing-close",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        session_owner_id="session-manager:first",
    )
    lease_path = plugin_lifecycle_module._session_owner_lease_path(
        lifecycle.layout,
        session_id="unlock-failure",
    )

    class UnlockThenFailLease:
        def __init__(self, underlying) -> None:
            self.underlying = underlying

        def __exit__(self, *args) -> None:
            self.underlying.__exit__(*args)
            raise OSError("injected unlock report failure")

    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        state = plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[lease_path]
        state.lease = UnlockThenFailLease(state.lease)

    failed_release_completed = threading.Event()
    allow_old_wrapper_check = threading.Event()
    release_owner_lease = plugin_lifecycle_module._release_session_owner_lease

    def release_then_pause(*args, **kwargs) -> None:
        try:
            release_owner_lease(*args, **kwargs)
        except OSError:
            failed_release_completed.set()
            assert allow_old_wrapper_check.wait(timeout=20)
            raise

    monkeypatch.setattr(
        plugin_lifecycle_module,
        "_release_session_owner_lease",
        release_then_pause,
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        failed_close = executor.submit(lease.close)
        assert failed_release_completed.wait(timeout=20)
        with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
            assert (
                lease_path not in plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES
            )

        replacement = _lifecycle(tmp_path).acquire_session(
            key,
            session_id="unlock-failure",
            lease_attempt_id="attempt-after-failed-unlock",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
            session_owner_id="session-manager:first",
        )
        replacement_authority_id = replacement._session_owner_lease.authority_id
        allow_old_wrapper_check.set()
        with pytest.raises(OSError, match="injected unlock report failure"):
            failed_close.result(timeout=20)

    # The first Session family release succeeded before platform unlock
    # reported its error; retrying its close must not touch the new owner.
    lease.close()
    with plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES_LOCK:
        state = plugin_lifecycle_module._PROCESS_SESSION_OWNER_LEASES[lease_path]
        assert state.owner_id == "session-manager:first"
        assert state.authority_id == replacement_authority_id
        assert state.references == 1
    replacement.close()


def test_concurrent_last_session_close_linearizes_exact_retirement(
    tmp_path: Path,
) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    leases = tuple(
        lifecycle.acquire_session(
            key,
            session_id=f"session-{sequence}",
            lease_attempt_id=f"attempt-{sequence}",
            owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
        )
        for sequence in (1, 2)
    )
    for sequence, lease in enumerate(leases, start=1):
        receipt = OwnerGenerationRetirementReceipt(
            owner_reference=f"owner:session-{sequence}",
            owner_generation_reference=f"generation:session-{sequence}",
            retirement_handle=f"retirement:session-{sequence}",
            contribution_ids=("coding.standard",),
        )
        lease.publish_owner_generations((receipt,))
        lease.retire_owner_generations((receipt,))

    _disable_or_remove(lifecycle, action="disable")
    lifecycle.reconcile_retirements()
    barrier = threading.Barrier(2)

    def close(lease) -> None:
        barrier.wait()
        lease.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        tuple(executor.map(close, leases))

    selected_ref = leases[0].instance_revision_ref
    retired = lifecycle.instances.snapshot().instance(selected_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    [intent] = lifecycle.management_retirement_intents()
    completed = lifecycle.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert completed is not None
    assert completed.state == "succeeded"
    assert completed.plan is not None
    assert len(completed.plan.targets) == 2
    assert len(completed.latest_outcomes) == 2


def test_public_lease_publish_writes_prepared_evidence_first(tmp_path: Path) -> None:
    lifecycle = _lifecycle(tmp_path)
    key = lifecycle.installation_key("coding.base")
    lifecycle.bootstrap_first_party_default(key, _package_ref())
    lease = lifecycle.acquire_session(
        key,
        session_id="write-ahead-session",
        lease_attempt_id="write-ahead-attempt",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    receipt = OwnerGenerationRetirementReceipt(
        owner_reference="owner:write-ahead",
        owner_generation_reference="generation:write-ahead",
        retirement_handle="retirement:write-ahead",
        contribution_ids=("coding.standard",),
    )

    lease.publish_owner_generations((receipt,))

    evidence = lifecycle.owner_evidence.family(lease.family.family_id)
    assert evidence is not None
    assert evidence.publication_state == "published"
    assert (
        len(
            lifecycle.layout.owner_generation_evidence.read_text(
                encoding="utf-8"
            ).splitlines()
        )
        == 2
    )
    lease.retire_owner_generations((receipt,))
    lease.close()


@pytest.mark.parametrize("publish_owner_evidence", [False, True])
def test_startup_lock_fault_injection_requires_positive_orphan_evidence(
    tmp_path: Path,
    publish_owner_evidence: bool,
) -> None:
    layout = resolve_ephemeral_coding_plugin_lifecycle_state_layout(
        tmp_path / "state",
        cwd=tmp_path / "workspace",
    )
    old_startup = f"old-startup-{publish_owner_evidence}"
    old = build_coding_plugin_lifecycle(layout, startup_id=old_startup)
    old.reconcile_retirements()
    old.complete_startup_recovery()
    key = old.installation_key("coding.base")
    old.bootstrap_first_party_default(key, _package_ref())
    lease = old.acquire_session(
        key,
        session_id="crashed-session",
        lease_attempt_id="crashed-attempt",
        owner_contributions=_TEST_OWNER_CONTRIBUTIONS,
    )
    receipt = OwnerGenerationRetirementReceipt(
        owner_reference="owner:crashed-session",
        owner_generation_reference="generation:crashed-session",
        retirement_handle="retirement:crashed-session",
        contribution_ids=("coding.standard",),
    )
    if publish_owner_evidence:
        lease.publish_owner_generations((receipt,))

    recovered = build_coding_plugin_lifecycle(
        layout,
        startup_id=f"new-startup-{publish_owner_evidence}",
    )
    recovered.reconcile_retirements()
    assert recovered.instances.snapshot().family(lease.family.family_id) is not None

    # Narrow unit-level fault injection for both owner-evidence branches.  The
    # product-level tests below kill a real child process and prove the OS lock
    # transition without reaching into this process-local registry.
    old_lease_path = plugin_lifecycle_module._startup_lease_path(
        layout,
        startup_id=old_startup,
    )
    with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
        old_process_lease = plugin_lifecycle_module._PROCESS_STARTUP_LEASES.pop(
            old_lease_path
        )
    old_process_lease.__exit__(None, None, None)

    recovered.reconcile_retirements()

    assert recovered.instances.snapshot().family(lease.family.family_id) is None
    family_evidence = recovered.owner_evidence.family(lease.family.family_id)
    if publish_owner_evidence:
        assert family_evidence is not None
        assert family_evidence.retired is True
        assert family_evidence.retirement_outcome_reference == (
            "coding-session-process-exit-confirmed:"
            f"{old_startup}:{lease.family.family_id}"
        )
    else:
        assert family_evidence is None

    _disable_or_remove(recovered, action="disable")
    recovered.reconcile_retirements()
    retired = recovered.instances.snapshot().instance(lease.instance_revision_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    [intent] = recovered.management_retirement_intents()
    retirement_set = recovered.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert retirement_set is not None
    assert retirement_set.state == "succeeded"
    assert retirement_set.plan is not None
    assert len(retirement_set.plan.targets) == int(publish_owner_evidence)


def _start_plugin_lifecycle_child(
    tmp_path: Path,
    *,
    mode: str,
) -> tuple[subprocess.Popen[str], dict[str, object], Path]:
    helper = Path(__file__).parent / "fixtures" / "plugin_lifecycle_child.py"
    marker = tmp_path / "owner-publication-crash.json"
    process = subprocess.Popen(
        (
            sys.executable,
            str(helper),
            mode,
            str(tmp_path / "loushang-home"),
            str(tmp_path / "workspace"),
            str(tmp_path / "sessions"),
            str(marker),
        ),
        cwd=Path(__file__).parents[2],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    with ThreadPoolExecutor(max_workers=1) as executor:
        handshake = executor.submit(process.stdout.readline)
        try:
            line = handshake.result(timeout=20)
        except FutureTimeoutError:
            _stop_plugin_lifecycle_child(process)
            pytest.fail("Plugin lifecycle child handshake timed out")
    if not line:
        assert process.stderr is not None
        stderr = process.stderr.read()
        process.wait(timeout=20)
        pytest.fail(f"Plugin lifecycle child exited before publishing state: {stderr}")
    return process, json.loads(line), marker


def _stop_plugin_lifecycle_child(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.kill()
    process.communicate(timeout=20)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_runtime_identity_rejects_another_process_until_orphan_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    process, child_state, _marker = _start_plugin_lifecycle_child(
        tmp_path,
        mode="product_hold",
    )
    owner = open_coding_fenced_product_application_owner(
        resolve_coding_plugin_lifecycle_state_layout(workspace),
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        registry = owner.epoch_runtime.registry
        [live] = registry.snapshot(store_id=registry.store_id).active_leases
        assert live.lease_id == child_state["leaseId"]
        assert live.runtime_id == child_state["runtimeId"]
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
            registry.register(
                runtime_id=str(child_state["runtimeId"]),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
        assert caught.value.code == "package_epoch_lease_identity_conflict"

        process.kill()
        assert process.wait(timeout=20) != 0
        assert registry.review_orphans(store_id=registry.store_id) == (live,)
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
            registry.snapshot(store_id=registry.store_id)
        assert caught.value.code == "package_epoch_lease_orphaned"
        registry.repair_orphan(live.lease_id)
        replacement = registry.register(
            runtime_id=live.runtime_id,
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        assert replacement.lease.lease_id != live.lease_id
        replacement.release()
    finally:
        owner.close()
        _stop_plugin_lifecycle_child(process)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_process_death_requires_exact_orphan_repair_before_new_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    process, child_state, _marker = _start_plugin_lifecycle_child(
        tmp_path,
        mode="product_hold",
    )
    owner = open_coding_fenced_product_application_owner(
        layout,
        workspace=workspace,
        runtime_version=version("loushang"),
        runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    )
    try:
        registry = owner.epoch_runtime.registry
        [live] = registry.snapshot(store_id=registry.store_id).active_leases
        assert live.lease_id == child_state["leaseId"]

        process.kill()
        assert process.wait(timeout=20) != 0
        assert registry.review_orphans(store_id=registry.store_id) == (live,)
        with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
            registry.snapshot(store_id=registry.store_id)
        assert caught.value.code == "package_epoch_lease_orphaned"

        async def resume() -> None:
            manager = await SessionManager.new(
                session_dir=tmp_path / "sessions-after-crash",
                cwd=str(workspace),
                persist=True,
            )
            settings = SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
            resumed = create_agent_session(
                session_manager=manager,
                model=_model(),
                services=create_services(settings_manager=settings),
            )
            try:
                [replacement] = registry.snapshot(
                    store_id=registry.store_id
                ).active_leases
                assert replacement.lease_id != live.lease_id
                assert registry.review_orphans(store_id=registry.store_id) == ()
                selected = resumed._coding_base_product_compilation
                assert selected is not None
                assert (
                    repr(selected.selected_manifest.snapshot.package_revision)
                    == child_state["selectedRevision"]
                )
                await resumed.prepare_model_call_runtime()
            finally:
                await resumed.dispose()

        asyncio.run(resume())
    finally:
        owner.close()
        _stop_plugin_lifecycle_child(process)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_hard_crash_after_lease_registration_repairs_exact_orphan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
    process, child_state, marker = _start_plugin_lifecycle_child(
        tmp_path,
        mode="product_crash_after_lease",
    )
    try:
        exit_code = process.wait(timeout=20)
        assert process.stderr is not None
        stderr = process.stderr.read()
        assert exit_code == 83, stderr
        assert json.loads(marker.read_text(encoding="utf-8")) == child_state
        owner = open_coding_fenced_product_application_owner(
            layout,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            [orphan] = registry.review_orphans(store_id=registry.store_id)
            assert orphan.lease_id == child_state["leaseId"]
            assert orphan.runtime_id == child_state["runtimeId"]

            async def recover() -> None:
                manager = await SessionManager.new(
                    session_dir=tmp_path / "sessions-recovered",
                    cwd=str(workspace),
                    persist=True,
                )
                settings = SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
                with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
                    create_agent_session(
                        session_manager=manager,
                        model=_model(),
                        services=create_services(settings_manager=settings),
                    )
                assert caught.value.code == "package_epoch_lease_orphaned"
                assert registry.review_orphans(store_id=registry.store_id) == (orphan,)
                registry.repair_orphan(orphan.lease_id)
                session = create_agent_session(
                    session_manager=manager,
                    model=_model(),
                    services=create_services(settings_manager=settings),
                )
                try:
                    [replacement] = registry.snapshot(
                        store_id=registry.store_id
                    ).active_leases
                    assert replacement.lease_id != orphan.lease_id
                    assert registry.review_orphans(store_id=registry.store_id) == ()
                    await session.prepare_model_call_runtime()
                    assert session._coding_base_product_compilation is not None
                finally:
                    await session.dispose()

            asyncio.run(recover())
            kinds = tuple(
                json.loads(line)["kind"]
                for line in registry.path.read_text(encoding="utf-8").splitlines()
            )
            assert kinds[0:2] == ("registered", "orphan_repaired")
            assert kinds.count("registered") == kinds.count("released") + 1
            assert kinds[-1] == "released"
        finally:
            owner.close()
    finally:
        _stop_plugin_lifecycle_child(process)


def test_workspace_lifecycle_uses_state_and_data_authorities_independent_of_session_scope(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias = tmp_path / "workspace-alias"
    alias.symlink_to(workspace, target_is_directory=True)
    first_paths = _platform_paths(tmp_path / "user-a")
    second_paths = _platform_paths(tmp_path / "user-b")

    first = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=first_paths,
    )
    canonical_alias = resolve_coding_plugin_lifecycle_state_layout(
        alias,
        platform_paths=first_paths,
    )
    other_user = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=second_paths,
    )
    other_workspace = resolve_coding_plugin_lifecycle_state_layout(
        tmp_path / "other-workspace",
        platform_paths=first_paths,
    )

    assert canonical_alias.scope_id == first.scope_id
    assert canonical_alias.root == first.root
    assert canonical_alias.package_root == first.package_root
    assert first.root.is_relative_to(first_paths.state)
    assert first.package_root.is_relative_to(first_paths.data)
    assert other_user.scope_id == first.scope_id
    assert other_user.root != first.root
    assert other_user.package_root != first.package_root
    assert other_workspace.scope_id != first.scope_id


def test_product_session_rejects_caller_supplied_legacy_package_materializer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import (
        CodingPackageProductLegacyPathError,
        create_agent_session,
        create_services,
    )
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )
        with pytest.raises(CodingPackageProductLegacyPathError):
            create_agent_session(
                session_manager=manager,
                model=_model(),
                services=services,
                package_materializer=_materializer(tmp_path / "session-authority"),
            )
        recovered = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=services,
        )
        await recovered.dispose()

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_package_selection_crosses_session_save_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = SettingsManager(ControlConfig(capabilities={"coding.lsp": "disabled"}))

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "cwd-sessions",
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(settings_manager=settings),
        )
        first_base = first._coding_base_product_compilation
        assert first_base is not None
        pinned = first_base.selected_manifest.snapshot

        second_manager = await SessionManager.new(
            session_dir=tmp_path / "user-global-sessions",
            cwd=str(workspace),
            persist=True,
        )
        second = create_agent_session(
            session_manager=second_manager,
            model=_model(),
            services=create_services(settings_manager=settings),
        )
        try:
            second_base = second._coding_base_product_compilation
            assert second_base is not None
            selected = second_base.selected_manifest.snapshot
            assert selected.root_ref == pinned.root_ref
            assert selected.package_revision == pinned.package_revision
            await second.prepare_model_call_runtime()
        finally:
            await second.dispose()
            await first.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("corruption", ("missing_root", "changed_file"))
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_base_replay_refuses_changed_committed_root_without_live_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.package_product.product_root_gc_runtime import (
        open_posix_local_wheel_product_root_gc,
    )
    from loushang.harness.plugin_management.package_gc_target import (
        resolve_plugin_package_gc_root_target,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    settings = SettingsManager(ControlConfig(capabilities={"coding.lsp": "disabled"}))

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-first",
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(settings_manager=settings),
        )
        selected = first._coding_base_product_compilation
        assert selected is not None
        snapshot = selected.selected_manifest.snapshot
        await first.dispose()

        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            gc = open_posix_local_wheel_product_root_gc(product)
            executor = gc.application.executor
            target = resolve_plugin_package_gc_root_target(
                snapshot.package_revision,
                bindings=product.gc_bindings.records(),
                claims=product.gc_bindings.claims(),
                committed_sets=executor.committed_sets.records(),
                settlements=executor.root_settlements.records(),
            )
            root = product.plugin_store_root / target.settlement.final_name
            assert root.is_dir()
            if corruption == "missing_root":
                root.rename(root.with_name(root.name + ".missing"))
            else:
                manifest_name = next(
                    name for name, _ in snapshot.files if name.endswith("plugin.json")
                )
                (root / manifest_name).write_bytes(b"tampered Product root")

            failed_manager = await SessionManager.new(
                session_dir=tmp_path / "sessions-failed",
                cwd=str(workspace),
                persist=True,
            )
            with pytest.raises(RuntimeError):
                create_agent_session(
                    session_manager=failed_manager,
                    model=_model(),
                    services=create_services(settings_manager=settings),
                )
            registry = owner.epoch_runtime.registry
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
                registry.snapshot(store_id=registry.store_id)
            assert caught.value.code == "package_epoch_lease_absent"
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("journal", "expected_code"),
    (
        ("desired", "plugin_lifecycle_journal_corrupt"),
        ("gc_binding", "plugin_package_gc_binding_corrupt"),
        ("committed_set", "package_committed_set_journal_corrupt"),
    ),
)
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_base_replay_refuses_corrupt_authority_journal_without_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    journal: str,
    expected_code: str,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.package_product.product_root_gc_runtime import (
        open_posix_local_wheel_product_root_gc,
    )
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    settings = SettingsManager(ControlConfig(capabilities={"coding.lsp": "disabled"}))

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-first",
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(settings_manager=settings),
        )
        assert first._coding_base_product_compilation is not None
        await first.dispose()

        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            paths = {
                "desired": product.desired_state.path,
                "gc_binding": product.gc_bindings.path,
                "committed_set": open_posix_local_wheel_product_root_gc(
                    product
                ).application.executor.committed_sets.path,
            }
            path = paths[journal]
            before = path.read_bytes()
            assert before.endswith(b"\n")
            with path.open("ab") as stream:
                stream.write(b"{invalid authority record}\n")

            failed_manager = await SessionManager.new(
                session_dir=tmp_path / "sessions-failed",
                cwd=str(workspace),
                persist=True,
            )
            with pytest.raises(RuntimeError) as caught:
                create_agent_session(
                    session_manager=failed_manager,
                    model=_model(),
                    services=create_services(settings_manager=settings),
                )
            assert getattr(caught.value, "code", None) == expected_code
            registry = owner.epoch_runtime.registry
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as absent:
                registry.snapshot(store_id=registry.store_id)
            assert absent.value.code == "package_epoch_lease_absent"
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_nonpersistent_transcript_honors_durable_product_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    global_settings = tmp_path / "settings" / "settings.json"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-a",
            cwd=str(workspace),
            persist=False,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"}),
                    global_settings_path=global_settings,
                )
            ),
        )
        assert first._coding_base_product_compilation is not None
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            inventory = product.desired_state.snapshot()
            base = next(
                item
                for item in inventory.installations
                if item.installation_key.plugin_id == "coding.base"
            )
            disabled = product.management.submit(
                PluginManagementCommandV1(
                    action="disable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id="operator:disable-base",
                        idempotency_key="operator:disable-base",
                        expected_inventory_revision=inventory.inventory_revision,
                        installation_key=base.installation_key,
                        desired_state="installed_disabled",
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert disabled.result is not None
            assert disabled.result.disposition == "succeeded"

            second_manager = await SessionManager.new(
                session_dir=tmp_path / "sessions-b",
                cwd=str(workspace),
                persist=False,
            )
            second = create_agent_session(
                session_manager=second_manager,
                model=_model(),
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(capabilities={"coding.lsp": "disabled"}),
                        global_settings_path=global_settings,
                    )
                ),
            )
            try:
                assert second._coding_base_product_compilation is None
                selected = product.desired_state.snapshot().installation(
                    base.installation_key
                )
                assert selected.selection.desired_state == "installed_disabled"
            finally:
                await second.dispose()
        finally:
            await first.dispose()
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("action", "reason"),
    (("disable", "plugin_disabled"), ("remove", "plugin_removed")),
)
def test_explicit_disable_or_remove_never_self_heals_and_pins_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    reason: str,
) -> None:
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    active = _managed_base(
        tmp_path,
        session_id=f"active-{action}",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    assert active is not None
    active_ref = active.management_lease.instance_revision_ref
    active_handle = active.package.revision_handle
    _disable_or_remove(lifecycle, action=action)

    change = active.evaluate_management_change()
    assert change is not None
    assert change.disposition == "restart_required"
    assert change.reason == reason
    assert change.diagnostic_details()["restartRequired"] is True
    monkeypatch.setattr(
        base_plugin_module,
        "coding_base_plugin_root",
        lambda: (_ for _ in ()).throw(AssertionError("source must not be scanned")),
    )
    replacement = _managed_base(
        tmp_path,
        session_id=f"new-{action}",
        materializer=materializer,
        lifecycle=_lifecycle(tmp_path),
    )
    assert replacement is None
    assert active_handle.closed is False
    assert len(lifecycle.desired.transitions()) == 3
    active.close()
    assert active_handle.closed is True
    retired = lifecycle.instances.snapshot().instance(active_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    intent = next(
        item
        for item in lifecycle.management_retirement_intents()
        if item.instance_revision_ref == active_ref
    )
    retirement_set = lifecycle.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert retirement_set is not None
    assert retirement_set.state == "succeeded"
    assert retirement_set.plan is not None
    assert len(retirement_set.latest_outcomes) == len(retirement_set.plan.targets)
    retention = lifecycle.packages.snapshot().package(retired.package_revision)
    assert retention is not None
    assert retention.nonretired_instances == ()
    assert retention.open_cleanup_ids == ()


def test_retirement_waits_for_every_session_owner_generation(
    tmp_path: Path,
) -> None:
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    first = _managed_base(
        tmp_path,
        session_id="retirement-first",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    second = _managed_base(
        tmp_path,
        session_id="retirement-second",
        materializer=materializer,
        lifecycle=_lifecycle(tmp_path),
    )
    assert first is not None
    assert second is not None
    old_ref = first.management_lease.instance_revision_ref
    assert second.management_lease.instance_revision_ref == old_ref
    _disable_or_remove(lifecycle, action="disable")

    first.close()

    draining = lifecycle.instances.snapshot().instance(old_ref)
    assert draining is not None
    assert draining.state == "DRAINING"
    assert len(draining.open_family_ids) == 2

    second.close()

    retired = lifecycle.instances.snapshot().instance(old_ref)
    assert retired is not None
    assert retired.state == "RETIRED"
    [intent] = lifecycle.management_retirement_intents()
    retirement_set = lifecycle.retirement_sets.snapshot().retirement_set(
        intent.retirement_id
    )
    assert retirement_set is not None
    assert retirement_set.state == "succeeded"
    assert retirement_set.plan is not None
    # These low-level assemblies never publish a Session runtime, so there are
    # no real owner generations to retire.  Lifecycle must not manufacture the
    # historical four static owner targets.
    assert retirement_set.plan.targets == ()
    assert retirement_set.latest_outcomes == ()


def test_update_selects_new_revision_while_old_session_remains_pinned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_source = _copy_base(tmp_path, "base-v1")
    monkeypatch.setattr(
        base_plugin_module,
        "coding_base_plugin_root",
        lambda: original_source,
    )
    materializer = _materializer(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    active = _managed_base(
        tmp_path,
        session_id="update-old",
        materializer=materializer,
        lifecycle=lifecycle,
    )
    assert active is not None
    old_root = active.package.root
    old_ref = active.management_lease.instance_revision_ref
    key = lifecycle.installation_key("coding.base")
    expected = lifecycle.desired.snapshot().installation(key).selection.package_revision
    assert expected is not None

    updated_source = _copy_base(tmp_path, "base-v2")
    manifest_path = updated_source / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "2.0.0"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    updated_runtime = authority.publish_runtime(
        (authority.inspect(PluginSource(path=updated_source)),),
        binding_store=materializer,
    )
    [updated_package] = updated_runtime.packages
    [updated_binding] = updated_runtime.bindings
    staged = package_revision_ref(
        plugin_id=updated_package.manifest.name,
        plugin_version=updated_package.manifest.version,
        package_content_digest=updated_package.content_digest,
        dependency_lock_digest=updated_package.dependency_lock.digest,
        package_source_identity=updated_binding.source_identity,
    )
    updated_runtime.close()
    snapshot = lifecycle.desired.snapshot()
    update_event = lifecycle.management.submit(
        PluginManagementUpdateCommandV2(
            operation_id="test-update",
            idempotency_key="test-update",
            expected_inventory_revision=snapshot.inventory_revision,
            installation_key=key,
            expected_package_revision=expected,
            staged_package_revision=staged,
            actor_id="test:operator",
            policy_revision="test-policy-v1",
            approval_reference="test",
        )
    )
    assert update_event.result is not None
    assert update_event.result.disposition == "restart_required"
    shutil.rmtree(updated_source)

    replacement = _managed_base(
        tmp_path,
        session_id="update-new",
        materializer=_materializer(tmp_path),
        lifecycle=_lifecycle(tmp_path),
    )
    assert replacement is not None
    try:
        assert replacement.package.content_digest == staged.package_content_digest
        assert replacement.package.root != old_root
        assert replacement.management_lease.instance_revision_ref.revision == (
            old_ref.revision + 1
        )
        assert active.package.root == old_root
        assert active.package.revision_handle.closed is False
        change = active.evaluate_management_change()
        assert change is not None
        assert change.disposition == "restart_required"
        assert change.reason == "plugin_updated"
    finally:
        replacement.close()
        active.close()
    retired = lifecycle.instances.snapshot().instance(old_ref)
    assert retired is not None
    assert retired.state == "RETIRED"


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_session_resume_reacquires_lease_for_same_selected_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new_with_composition(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await first.prepare_model_call_runtime()
        await first_manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="resume lifecycle")],
                timestamp=0.0,
            )
        )
        session_file = first_manager.get_session_file()
        first_base = first._coding_base_product_compilation
        assert first_base is not None
        selected_revision = first_base.selected_manifest.snapshot.package_revision
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            first_snapshot = registry.snapshot(store_id=registry.store_id)
            assert len(first_snapshot.active_leases) == 1
            first_lease_id = first_snapshot.active_leases[0].lease_id
            await first.dispose()

            resumed_manager = await SessionManager.load(session_file)
            assert (
                resumed_manager.get_header().conversation_id
                == first_manager.get_header().conversation_id
            )
            resumed = create_agent_session(
                session_manager=resumed_manager,
                model=_model(),
                services=create_services(
                    settings_manager=SettingsManager(
                        ControlConfig(capabilities={"coding.lsp": "disabled"})
                    )
                ),
            )
            try:
                resumed_base = resumed._coding_base_product_compilation
                assert resumed_base is not None
                assert (
                    resumed_base.selected_manifest.snapshot.package_revision
                    == selected_revision
                )
                resumed_snapshot = registry.snapshot(store_id=registry.store_id)
                assert len(resumed_snapshot.active_leases) == 1
                assert resumed_snapshot.active_leases[0].lease_id != first_lease_id
                await resumed.prepare_model_call_runtime()
                assert resumed.get_tool_definition("bash") is not None
            finally:
                await resumed.dispose()
        finally:
            await first.dispose()
            owner.close()

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_arch_resume_reuses_selected_revision_and_private_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.ai.types import TextPart, UserMessage
    from loushang.coding.arch import INSPECT_IMPORT_GRAPH_TOOL_NAME
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("import os\n", encoding="utf-8")
    session_dir = tmp_path / "sessions"
    services = create_services(
        settings_manager=SettingsManager(
            ControlConfig(
                capabilities={"coding.arch": "always", "coding.lsp": "disabled"}
            )
        )
    )

    async def scenario() -> None:
        first_manager = await SessionManager.new_with_composition(
            session_dir=session_dir,
            cwd=str(workspace),
            composition_set="coding-architecture",
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=services,
            composition_set="coding-architecture",
        )
        await first.prepare_model_call_runtime()
        await first_manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="resume Arch cache")],
                timestamp=0.0,
            )
        )
        first_assembly = first._coding_capability_plugin_assembly
        assert first_assembly is not None
        assert first_assembly.tool_owner_for("coding.arch.default") is not None
        first_base = first._coding_base_product_compilation
        assert first_base is not None
        first_selected = next(
            item.snapshot.package_revision
            for item in first_base.selected_capability_manifests
            if item.manifest.name == "coding.arch.default"
        )
        first_tool = next(
            tool
            for tool in first.agent.tools
            if tool.name == INSPECT_IMPORT_GRAPH_TOOL_NAME
        )
        cold = await first_tool.execute(
            "arch-resume-cold",
            {"root": ".", "query": "summary"},
        )
        first_config = next(
            item.configuration
            for item in first_assembly.selection.plan.effective_configuration_set.entries
            if item.plugin_id == "coding.arch.default"
            and item.contribution_id == "coding-arch-default"
        )
        private_root = Path(str(first_config["privateDataRoot"]))
        assert cold.details["cache"]["misses"] == 1
        assert (private_root / "import-facts-v1.json").is_file()
        session_file = first_manager.get_session_file()
        await first.dispose()
        assert private_root.is_dir()

        resumed_manager = await SessionManager.load(session_file)
        resumed = create_agent_session(
            session_manager=resumed_manager,
            model=_model(),
            services=services,
            composition_set="coding-architecture",
        )
        await resumed.prepare_model_call_runtime()
        resumed_assembly = resumed._coding_capability_plugin_assembly
        assert resumed_assembly is not None
        assert resumed_assembly.tool_owner_for("coding.arch.default") is not None
        resumed_base = resumed._coding_base_product_compilation
        assert resumed_base is not None
        resumed_selected = next(
            item.snapshot.package_revision
            for item in resumed_base.selected_capability_manifests
            if item.manifest.name == "coding.arch.default"
        )
        resumed_config = next(
            item.configuration
            for item in resumed_assembly.selection.plan.effective_configuration_set.entries
            if item.plugin_id == "coding.arch.default"
            and item.contribution_id == "coding-arch-default"
        )
        assert Path(str(resumed_config["privateDataRoot"])) == private_root
        assert resumed_selected == first_selected
        resumed_tool = next(
            tool
            for tool in resumed.agent.tools
            if tool.name == INSPECT_IMPORT_GRAPH_TOOL_NAME
        )
        warm = await resumed_tool.execute(
            "arch-resume-warm",
            {"root": ".", "query": "summary"},
        )
        assert warm.details["cache"]["hits"] == 1
        await resumed.dispose()
        assert private_root.is_dir()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ("disable", "remove"))
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_base_change_keeps_active_selection_and_omits_new_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"
    settings = SettingsManager(ControlConfig(capabilities={"coding.lsp": "disabled"}))

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(settings_manager=settings),
        )
        await active.prepare_model_call_runtime()
        assert active._coding_base_product_compilation is not None
        before_tools = tuple(active.get_active_tool_names())
        assert {"bash", "read", "write"}.issubset(before_tools)

        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            product = owner.runtime_owner.product_owner
            inventory = product.desired_state.snapshot()
            base = next(
                item
                for item in inventory.installations
                if item.installation_key.plugin_id == "coding.base"
            )
            changed = product.management.submit(
                PluginManagementCommandV1(
                    action=action,
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=f"operator:{action}-base",
                        idempotency_key=f"operator:{action}-base",
                        expected_inventory_revision=inventory.inventory_revision,
                        installation_key=base.installation_key,
                        desired_state=(
                            "installed_disabled" if action == "disable" else "absent"
                        ),
                        package_revision=None,
                        actor_id="operator",
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            assert changed.result is not None
            assert changed.result.disposition == "succeeded"
            with pytest.raises(CodingBasePluginAssemblyError, match="requires restart"):
                await active.prepare_model_call_runtime()
            records = [
                item
                for item in active.get_session_diagnostics()
                if item.code == "coding_base_product_restart_required"
            ]
            assert len(records) == 1
            assert records[0].type == "error"
            assert records[0].source == "session"
            assert tuple(active.get_active_tool_names()) == before_tools

            second_manager = await SessionManager.new(
                session_dir=session_dir,
                cwd=str(workspace),
                persist=True,
            )
            replacement = create_agent_session(
                session_manager=second_manager,
                model=_model(),
                services=create_services(settings_manager=settings),
            )
            try:
                assert replacement._coding_base_product_compilation is None
                await replacement.prepare_model_call_runtime()
                assert {"bash", "read", "write"}.isdisjoint(
                    replacement.get_active_tool_names()
                )
                selected = product.desired_state.snapshot().installation(
                    base.installation_key
                )
                assert selected.selection.desired_state == (
                    "installed_disabled" if action == "disable" else "absent"
                )
            finally:
                await replacement.dispose()
        finally:
            await active.dispose()
            owner.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("owner_id", ["commands.session", "tools.workspace"])
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_owner_cleanup_failure_keeps_runtime_lease_until_exact_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    owner_id: str,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assert active._coding_base_product_compilation is not None
        generation = next(
            item
            for item in active._capability_owner_generations
            if item.binding.plugin_id == "coding.base"
            and item.binding.owner_id == owner_id
        )
        failing_lease = generation.value.scope._leases[0]
        release = failing_lease._dispose
        assert release is not None
        attempts = 0

        def fail_once():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient Product owner cleanup failure")
            return release()

        failing_lease._dispose = fail_once
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            [live] = registry.snapshot(store_id=registry.store_id).active_leases
            with pytest.raises(
                RuntimeError, match="generation disposal remains incomplete"
            ):
                await active.dispose()
            [retained] = registry.snapshot(store_id=registry.store_id).active_leases
            assert retained == live
            assert attempts == 1
            await active.dispose()
            assert attempts == 2
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as absent:
                registry.snapshot(store_id=registry.store_id)
            assert absent.value.code == "package_epoch_lease_absent"
        finally:
            owner.close()

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_nonpersistent_product_sessions_release_runtime_without_erasing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
    settings = SettingsManager(ControlConfig(capabilities={"coding.lsp": "disabled"}))

    async def scenario() -> None:
        first_inventory_revision: int | None = None
        for sequence in range(3):
            manager = await SessionManager.new(
                session_dir=tmp_path / f"sessions-{sequence}",
                cwd=str(workspace),
                persist=False,
            )
            session = create_agent_session(
                session_manager=manager,
                model=_model(),
                services=create_services(settings_manager=settings),
            )
            await session.prepare_model_call_runtime()
            assert session._coding_base_product_compilation is not None
            owner = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            )
            try:
                product = owner.runtime_owner.product_owner
                revision = product.desired_state.snapshot().inventory_revision
                if first_inventory_revision is None:
                    first_inventory_revision = revision
                else:
                    assert revision == first_inventory_revision
                registry = owner.epoch_runtime.registry
                assert (
                    len(registry.snapshot(store_id=registry.store_id).active_leases)
                    == 1
                )
                await session.dispose()
                with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as caught:
                    registry.snapshot(store_id=registry.store_id)
                assert caught.value.code == "package_epoch_lease_absent"
                assert product.state_root.is_dir()
            finally:
                await session.dispose()
                owner.close()

    asyncio.run(scenario())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_session_runtime_release_failure_retains_lease_until_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(workspace),
            persist=False,
        )
        session = create_agent_session(
            session_manager=manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await session.prepare_model_call_runtime()
        binding = session._package_product_runtime_binding
        assert binding is not None and binding.on_dispose is not None
        release = binding.on_dispose
        attempts = 0

        def fail_once() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient Product runtime release failure")
            release()

        object.__setattr__(binding, "on_dispose", fail_once)
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            [live] = registry.snapshot(store_id=registry.store_id).active_leases
            with pytest.raises(
                RuntimeError,
                match="transient Product runtime release failure",
            ):
                await session.dispose()
            [retained] = registry.snapshot(store_id=registry.store_id).active_leases
            assert retained == live
            assert attempts == 1
            await session.dispose()
            assert attempts == 2
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as absent:
                registry.snapshot(store_id=registry.store_id)
            assert absent.value.code == "package_epoch_lease_absent"
        finally:
            owner.close()

    asyncio.run(scenario())


def test_explicit_ephemeral_root_is_not_deleted_by_gc() -> None:
    import loushang.coding.bootstrap as bootstrap_module

    owner = bootstrap_module._ExplicitTemporaryDirectory(
        prefix="loushang-coding-no-finalizer-test-"
    )
    root = Path(owner.name)
    assert root.is_dir()

    del owner
    gc.collect()

    assert root.is_dir()
    shutil.rmtree(root)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_dual_capability_construction_failure_releases_unbound_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
        PackageEpochRuntimeLeaseRegistryError,
    )

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    settings = SettingsManager(
        ControlConfig(capabilities={"coding.lsp": "always", "coding.arch": "always"})
    )

    def fail_agent(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("injected Product Session construction failure")

    async def scenario() -> None:
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-failed",
            cwd=str(workspace),
            persist=True,
        )
        with pytest.raises(
            RuntimeError, match="injected Product Session construction failure"
        ):
            create_agent_session(
                session_manager=manager,
                model=_model(),
                services=create_services(settings_manager=settings),
                composition_set="coding-architecture",
                agent_factory=fail_agent,  # type: ignore[arg-type]
            )
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        try:
            registry = owner.epoch_runtime.registry
            with pytest.raises(PackageEpochRuntimeLeaseRegistryError) as absent:
                registry.snapshot(store_id=registry.store_id)
            assert absent.value.code == "package_epoch_lease_absent"
            recovered_manager = await SessionManager.new(
                session_dir=tmp_path / "sessions-recovered",
                cwd=str(workspace),
                persist=True,
            )
            recovered = create_agent_session(
                session_manager=recovered_manager,
                model=_model(),
                services=create_services(settings_manager=settings),
                composition_set="coding-architecture",
            )
            try:
                await recovered.prepare_model_call_runtime()
                assembly = recovered._coding_capability_plugin_assembly
                assert assembly is not None
                assert assembly.tool_owner_for("coding.lsp.default") is not None
                assert assembly.tool_owner_for("coding.arch.default") is not None
            finally:
                await recovered.dispose()
        finally:
            owner.close()

    asyncio.run(scenario())


def test_failure_custodian_gates_every_cleanup_stage_on_runtime_close() -> None:
    from loushang.coding._capability_plugin_composition import (
        CodingCapabilityPluginCleanupCustodian,
    )

    events: list[str] = []

    class Runtime:
        attempts = 0

        def close(self) -> None:
            events.append("runtime")
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("transient runtime close failure")

    class Lease:
        def close(self) -> None:
            events.append("lease")

    custodian = CodingCapabilityPluginCleanupCustodian(
        runtime=Runtime(),  # type: ignore[arg-type]
        management_leases={"coding.lsp.default": Lease()},  # type: ignore[dict-item]
        management_state_cleanup=lambda: events.append("management"),
        state_cleanup=lambda: events.append("state"),
        private_state_cleanup=lambda: events.append("private"),
    )

    with pytest.raises(RuntimeError, match="transient runtime close failure"):
        custodian.close()

    assert events == ["runtime"]
    assert custodian._runtime_closed is False
    assert custodian._management_released is False
    assert custodian._state_cleaned is False
    assert custodian._private_state_cleaned is False

    custodian.close()

    assert events == [
        "runtime",
        "runtime",
        "lease",
        "management",
        "state",
        "private",
    ]
    assert custodian._runtime_closed is True
    assert custodian._management_released is True
    assert custodian._state_cleaned is True
    assert custodian._private_state_cleaned is True


@pytest.mark.parametrize("action", ("disable", "remove"))
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux Product route")
def test_product_bootstrap_preserves_lsp_only_when_base_is_unselected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from importlib.metadata import version

    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.lsp import (
        DOCUMENT_OUTLINE_TOOL_NAME,
        INSPECT_SYMBOL_TOOL_NAME,
        LspServerDefinition,
    )
    from loushang.coding.package_product_runtime import (
        CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        open_coding_fenced_product_application_owner,
    )
    from loushang.coding.session_manager import SessionManager
    from loushang.harness.sandbox import SandboxSettings

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").touch()
    (workspace / "main.py").write_text(
        "target = 1\nprint(target)\n",
        encoding="utf-8",
    )
    method_log = workspace / "lsp-methods.log"
    fake_lsp_server = Path(__file__).parent / "lsp" / "fixtures" / "fake_lsp_server.py"
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        first = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        assert first._coding_base_product_compilation is not None
        owner = open_coding_fenced_product_application_owner(
            resolve_coding_plugin_lifecycle_state_layout(workspace),
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
        )
        product = owner.runtime_owner.product_owner
        inventory = product.desired_state.snapshot()
        base = next(
            item
            for item in inventory.installations
            if item.installation_key.plugin_id == "coding.base"
        )
        changed = product.management.submit(
            PluginManagementCommandV1(
                action=action,
                mutation=PluginDesiredStateMutationV1(
                    operation_id=f"operator:lsp-only-{action}-base",
                    idempotency_key=f"operator:lsp-only-{action}-base",
                    expected_inventory_revision=inventory.inventory_revision,
                    installation_key=base.installation_key,
                    desired_state=(
                        "installed_disabled" if action == "disable" else "absent"
                    ),
                    package_revision=None,
                    actor_id="operator",
                    policy_revision=product.desired_policy_revision,
                ),
            )
        )
        assert changed.result is not None
        assert changed.result.disposition == "succeeded"
        await first.dispose()
        owner.close()

        replacement_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        replacement = create_agent_session(
            session_manager=replacement_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(
                        capabilities={"coding.lsp": "always"},
                        sandbox=SandboxSettings(enabled=False),
                    )
                )
            ),
            lsp_definitions=(
                LspServerDefinition(
                    id="python-test",
                    command=(sys.executable, str(fake_lsp_server)),
                    language_extensions={"python": (".py",)},
                    root_markers=("pyproject.toml",),
                    environment={"LOUSHANG_FAKE_LSP_LOG": str(method_log)},
                    startup_timeout_seconds=3,
                    request_timeout_seconds=3,
                    shutdown_timeout_seconds=3,
                ),
            ),
        )
        assert replacement._coding_base_product_compilation is None
        lsp_assembly = replacement._coding_lsp_plugin_assembly
        assert lsp_assembly is not None
        assert lsp_assembly.selection.plan.selected_plugin_ids == (
            "coding.lsp.default",
        )
        inputs = replacement._capability_composition_inputs
        assert inputs is not None
        assert {
            (item.plugin_id, item.contribution_id)
            for item in inputs.product_composition.catalog_admissions
        } == {("coding.lsp.default", "coding-lsp-tools")}
        assert "Use tools as needed" not in replacement.agent.system_prompt

        await replacement.prepare_model_call_runtime()

        active_tools = set(replacement.get_active_tool_names())
        assert {DOCUMENT_OUTLINE_TOOL_NAME, INSPECT_SYMBOL_TOOL_NAME}.issubset(
            active_tools
        )
        assert {"bash", "edit", "find", "grep", "ls", "read", "write"}.isdisjoint(
            active_tools
        )
        assert "session" not in {item.name for item in replacement.list_commands()}
        assert len(replacement._capability_owner_generations) == 1
        registrations = replacement.get_effective_runtime_view().registrations
        assert {
            (item.surface, item.public_key)
            for item in registrations
            if item.surface in {"tool", "session_command_pack"}
        } == {
            ("tool", DOCUMENT_OUTLINE_TOOL_NAME),
            ("tool", INSPECT_SYMBOL_TOOL_NAME),
        }
        materialized = {tool.name: tool for tool in replacement.agent.tools}
        result = await materialized[INSPECT_SYMBOL_TOOL_NAME].execute(
            f"lsp-only-{action}",
            {"path": "main.py", "line": 2, "character": 7},
        )
        assert result.details["server_id"] == "python-test"
        assert result.details["count"] == 1
        assert result.details["items"][0]["path"] == "main.py"
        await replacement.dispose()
        assert replacement._capability_owner_generations == ()
        assert method_log.read_text(encoding="utf-8").splitlines() == [
            "initialize",
            "initialized",
            "textDocument/didOpen",
            "textDocument/definition",
            "shutdown",
            "exit",
        ]

    asyncio.run(scenario())
