from __future__ import annotations

import asyncio
import json
import shutil
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
    return build_coding_plugin_lifecycle(
        resolve_ephemeral_coding_plugin_lifecycle_state_layout(
            root / "state",
            cwd=root / "workspace",
        )
    )


def _copy_base(root: Path, name: str) -> Path:
    target = root / name
    shutil.copytree(coding_base_plugin_root(), target)
    return target


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
