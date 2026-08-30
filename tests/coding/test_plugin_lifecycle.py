from __future__ import annotations

import asyncio
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import loushang.coding._base_plugin as base_plugin_module
from loushang.ai.model import Capabilities, Model
from loushang.coding._base_plugin import (
    CodingBasePluginAssemblyError,
    coding_base_plugin_root,
    prepare_managed_coding_base_plugin_assembly,
)
from loushang.coding._plugin_lifecycle import (
    build_coding_plugin_lifecycle,
    package_revision_ref,
    resolve_coding_plugin_lifecycle_state_layout,
    resolve_ephemeral_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.plugin_management import (
    PluginDesiredStateMutationV1,
    PluginManagementCommandV1,
    PluginManagementUpdateCommandV2,
)
from loushang.harness.resources.plugins import (
    PluginResolutionAuthority,
    PluginSource,
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


_TEST_OWNER_CONTRIBUTIONS = (
    ("commands.session", ("coding.standard",)),
    ("resources.prompt", ("prompt-standard",)),
    ("resources.skill", ("skill-standard",)),
    ("tools.workspace", ("coding.builtin",)),
)


def _disable_or_remove(lifecycle, *, action: str) -> object:
    key = lifecycle.installation_key("coding.base")
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

    assert lifecycle.desired.snapshot().installation(
        key
    ).selection.desired_state == "installed_enabled"
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


def test_production_package_replay_crosses_session_save_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    source = _copy_base(tmp_path, "mutable-production-base")
    monkeypatch.setattr(base_plugin_module, "coding_base_plugin_root", lambda: source)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=tmp_path / "cwd-sessions",
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
        first_base = first._coding_base_plugin_assembly
        assert first_base is not None
        first_lease = first_base.management_lease
        assert first_lease is not None
        pinned_root = first_base.package.root
        pinned_ref = first_lease.instance_revision_ref
        shutil.rmtree(source)

        second_manager = await SessionManager.new(
            session_dir=tmp_path / "user-global-sessions",
            cwd=str(workspace),
            persist=True,
        )
        second = create_agent_session(
            session_manager=second_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        second_base = second._coding_base_plugin_assembly
        assert second_base is not None
        second_lease = second_base.management_lease
        assert second_lease is not None
        assert second_base.package.root == pinned_root
        assert second_lease.instance_revision_ref == pinned_ref
        await second.dispose()
        await first.dispose()

    asyncio.run(scenario())


def test_nonpersistent_transcript_honors_configured_durable_product_disable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
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
        assert first._coding_base_plugin_assembly is not None
        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")

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
        assert second._coding_base_plugin_assembly is None
        await second.dispose()
        await first.dispose()

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
    assert len(retirement_set.plan.targets) == 4
    assert len(retirement_set.latest_outcomes) == 4


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


def test_public_update_replays_deleted_source_into_model_input_and_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"
    original_source = _copy_base(tmp_path, "public-base-v1")
    monkeypatch.setattr(
        base_plugin_module,
        "coding_base_plugin_root",
        lambda: original_source,
    )

    async def scenario() -> None:
        services = create_services(
            settings_manager=SettingsManager(
                ControlConfig(capabilities={"coding.lsp": "disabled"})
            )
        )
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=services,
        )
        await active.prepare_model_call_runtime()
        active_base = active._coding_base_plugin_assembly
        assert active_base is not None
        old_ref = active_base.management_lease.instance_revision_ref
        layout = resolve_coding_plugin_lifecycle_state_layout(workspace)
        lifecycle = build_coding_plugin_lifecycle(layout)
        key = lifecycle.installation_key("coding.base")
        expected = lifecycle.desired.snapshot().installation(
            key
        ).selection.package_revision
        assert expected is not None

        updated_source = _copy_base(tmp_path, "public-base-v2")
        manifest_path = updated_source / "plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "2.0.0"
        manifest_path.write_text(
            json.dumps(
                manifest,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        marker = "PLC6 public immutable replay marker"
        (updated_source / "prompts" / "standard.md").write_text(
            marker,
            encoding="utf-8",
        )
        materializer = CodingPackageMaterializer(
            install_root=layout.package_install_root,
            lockfile_path=layout.package_lockfile,
            plugin_revision_root=layout.plugin_revision_root,
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
        update = lifecycle.management.submit(
            PluginManagementUpdateCommandV2(
                operation_id="public-test-update",
                idempotency_key="public-test-update",
                expected_inventory_revision=snapshot.inventory_revision,
                installation_key=key,
                expected_package_revision=expected,
                staged_package_revision=staged,
                actor_id="test:operator",
                policy_revision="test-policy-v1",
                approval_reference="test",
            )
        )
        assert update.result is not None
        assert update.result.disposition == "restart_required"
        shutil.rmtree(updated_source)
        monkeypatch.setattr(
            base_plugin_module,
            "coding_base_plugin_root",
            lambda: (_ for _ in ()).throw(
                AssertionError("updated source must not be rescanned")
            ),
        )
        await active.dispose()

        replacement_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        replacement = create_agent_session(
            session_manager=replacement_manager,
            model=_model(),
            services=services,
        )
        replacement_base = replacement._coding_base_plugin_assembly
        assert replacement_base is not None
        assert replacement_base.package.content_digest == staged.package_content_digest
        assert replacement_base.binding.source == str(updated_source.resolve())

        await replacement.prepare_model_call_runtime()

        assert marker in replacement.agent.system_prompt
        assert len(replacement._capability_owner_generations) == 2
        owner_registrations = {
            (item.surface, item.public_key, item.owner_id)
            for item in replacement.get_effective_runtime_view().registrations
            if item.surface in {"tool", "session_command_pack"}
        }
        assert (
            "session_command_pack",
            "harness.session.standard",
            "commands.session",
        ) in owner_registrations
        assert (
            "tool",
            "bash",
            "tools.workspace",
        ) in owner_registrations
        await replacement.dispose()
        retired = lifecycle.instances.snapshot().instance(old_ref)
        assert retired is not None
        assert retired.state == "RETIRED"

    asyncio.run(scenario())


def test_public_session_dispose_then_resume_reacquires_a_fresh_live_lease(
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
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        await first_manager.append_message(
            UserMessage(
                role="user",
                content=[TextPart(type="text", text="resume lifecycle")],
                timestamp=0.0,
            )
        )
        session_file = first_manager.get_session_file()
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
        first_base = first._coding_base_plugin_assembly
        assert first_base is not None
        first_lease = first_base.management_lease
        assert first_lease is not None
        first_family_id = first_lease.family.family_id
        selected_ref = first_lease.instance_revision_ref
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
        resumed_base = resumed._coding_base_plugin_assembly
        assert resumed_base is not None
        resumed_lease = resumed_base.management_lease
        assert resumed_lease is not None
        assert resumed_lease.instance_revision_ref == selected_ref
        assert resumed_lease.family.family_id != first_family_id
        await resumed.prepare_model_call_runtime()
        assert resumed.get_tool_definition("bash") is not None
        assert len(resumed._capability_owner_generations) >= 2
        assert resumed._capability_composition_inputs is not None
        await resumed.dispose()

    asyncio.run(scenario())


def test_production_bootstrap_disable_keeps_active_generation_and_omits_new_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    session_dir = tmp_path / "sessions"

    async def scenario() -> None:
        first_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        active = create_agent_session(
            session_manager=first_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        await active.prepare_model_call_runtime()
        assert active._coding_base_plugin_assembly is not None
        before_tools = tuple(active.get_active_tool_names())

        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action="disable")
        with pytest.raises(
            CodingBasePluginAssemblyError,
            match="requires restart",
        ):
            await active.refresh_resources()
        records = [
            item
            for item in active.get_session_diagnostics()
            if item.code == "coding_base_management_restart_required"
        ]
        assert len(records) == 1
        assert records[0].details["restartRequired"] is True
        assert records[0].details["reason"] == "plugin_disabled"
        assert tuple(active.get_active_tool_names()) == before_tools
        assert active._coding_base_plugin_assembly.package.revision_handle.closed is False

        second_manager = await SessionManager.new(
            session_dir=session_dir,
            cwd=str(workspace),
            persist=True,
        )
        replacement = create_agent_session(
            session_manager=second_manager,
            model=_model(),
            services=create_services(
                settings_manager=SettingsManager(
                    ControlConfig(capabilities={"coding.lsp": "disabled"})
                )
            ),
        )
        assert replacement._coding_base_plugin_assembly is None
        assert replacement._capability_composition_inputs is None
        assert "Use tools as needed" not in replacement.agent.system_prompt
        await replacement.prepare_model_call_runtime()
        assert {"bash", "read", "write"}.isdisjoint(
            replacement.get_active_tool_names()
        )
        await replacement.dispose()
        await active.dispose()

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ("disable", "remove"))
def test_production_bootstrap_preserves_lsp_only_when_base_is_unselected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    from loushang.coding.bootstrap import create_agent_session, create_services
    from loushang.coding.control import ControlConfig, SettingsManager
    from loushang.coding.lsp import (
        DOCUMENT_OUTLINE_TOOL_NAME,
        INSPECT_SYMBOL_TOOL_NAME,
        LspServerDefinition,
    )
    from loushang.coding.session_manager import SessionManager

    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "loushang-home"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
        assert first._coding_base_plugin_assembly is not None
        lifecycle = build_coding_plugin_lifecycle(
            resolve_coding_plugin_lifecycle_state_layout(workspace)
        )
        _disable_or_remove(lifecycle, action=action)
        await first.dispose()

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
                    ControlConfig(capabilities={"coding.lsp": "always"})
                )
            ),
            lsp_definitions=(
                LspServerDefinition(
                    id="python-test",
                    command=("python-language-server", "--stdio"),
                    language_extensions={"python": (".py",)},
                ),
            ),
        )
        assert replacement._coding_base_plugin_assembly is None
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
        await replacement.dispose()
        assert replacement._capability_owner_generations == ()

    asyncio.run(scenario())
