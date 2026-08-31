from __future__ import annotations

import asyncio
import json
import os
import shutil
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding._plugin_lifecycle as plugin_lifecycle_module
from loushang.coding._plugin_lifecycle import (
    build_coding_plugin_lifecycle,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.continuity import (
    bind_coding_continuity,
    shutdown_coding_continuity,
)
from loushang.coding.continuity_bootstrap import (
    CodingContinuityBootstrapError,
    CodingContinuityStateLayout,
    bind_coding_configured_continuity,
    get_coding_configured_continuity_composition,
    get_coding_continuity_bootstrap_status,
    resolve_coding_continuity_state_layout,
    retry_coding_continuity_bootstrap,
)
from loushang.coding.control import SettingsManager
from loushang.foundation.platform_paths import PlatformPaths
from loushang.harness.config.agent.types import ControlConfig
from loushang.harness.continuity import (
    ContinuityDeletionPlanV1,
    ContinuityQuery,
    consume_prepared_activation,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PluginSymbolReference,
)
from loushang.harness.plugin_management import (
    PluginContinuityDeletionJournal,
    PluginDesiredStateLedger,
    PluginDesiredStateMutationV1,
    PluginEnablementMigrationError,
    PluginEnablementMigrationJournal,
    PluginInstanceRuntimeLedger,
    PluginManagementCommandV1,
    PluginPackageRevisionRefV1,
    plugin_enablement_legacy_input_fingerprint,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.continuity_provider import (
    ContinuityProviderDeclarationWirePayloadV2,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.transcript import SessionIndexPage


@dataclass
class _Runtime:
    session_dir: Path
    prepared_payloads: list[bytes] = field(default_factory=list)

    def try_query_session_index_page(self, *_args, **_kwargs) -> SessionIndexPage:
        return SessionIndexPage(
            items=(),
            has_more=False,
            index_state="fresh",
            index_generation="coding-g1",
            query_snapshot="coding-q1",
        )

    def request_session_index_refresh(self, *, all_sessions: bool = False) -> None:
        del all_sessions

    def request_session_index_repair(self) -> None:
        return None

    def request_bounded_session_index_refresh(self) -> None:
        return None

    def get_current_session(self) -> None:
        return None

    def get_current_session_ref(self) -> None:
        return None

    async def delete_session(self, _session_id: str | Path) -> bool:
        return False

    async def prepare_restore_session_operation(
        self,
        session_id: str | Path,
        **_kwargs: object,
    ) -> object:
        self.prepared_payloads.append(Path(session_id).read_bytes())

        class _Prepared:
            async def consume(self) -> object:
                return {"restored": True}

            async def abort(self) -> None:
                return None

            async def close(self) -> None:
                return None

        return _Prepared()


def test_continuity_state_layout_is_canonical_and_redacts_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "private" / "customer-secret"
    paths = PlatformPaths(
        home=tmp_path / "home",
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "tmp",
    )

    first = resolve_coding_continuity_state_layout(workspace, platform_paths=paths)
    second = resolve_coding_continuity_state_layout(workspace, platform_paths=paths)

    assert first == second
    assert first.root.parent == paths.state / "plugins/coding/continuity/workspaces"
    assert workspace.name not in str(first.root)
    assert first.scope_id == f"workspace:{first.root.name}"
    assert first.instance_runtime.parent == first.root
    lifecycle = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=paths,
    )
    assert first.package_root == lifecycle.package_root
    assert first.private_data_base == lifecycle.private_data_base
    assert first.package_root.is_relative_to(paths.data)
    assert not first.package_root.is_relative_to(first.root)


def test_private_state_root_rejects_symlink_without_chmodding_target(
    tmp_path: Path,
) -> None:
    from loushang.coding.continuity_bootstrap import _prepare_private_state_root

    target = tmp_path / "shared-target"
    target.mkdir(mode=0o755)
    link = tmp_path / "state-link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        _prepare_private_state_root(link)

    assert caught.value.code == "coding_continuity_state_permissions_failed"
    assert target.stat().st_mode & 0o777 == 0o755


def test_private_state_layout_tightens_every_application_owned_ancestor(
    tmp_path: Path,
) -> None:
    from loushang.coding.continuity_bootstrap import _prepare_private_state_layout

    layout = _test_layout(tmp_path / "state", tmp_path / "workspace")
    previous_umask = os.umask(0o002)
    try:
        _prepare_private_state_layout(layout)
    finally:
        os.umask(previous_umask)

    current = layout.private_state_base
    assert current.stat().st_mode & 0o777 == 0o700
    for part in layout.root.relative_to(current).parts:
        current /= part
        assert current.stat().st_mode & 0o777 == 0o700


def test_private_state_layout_rejects_an_intermediate_symlink(
    tmp_path: Path,
) -> None:
    from loushang.coding.continuity_bootstrap import _prepare_private_state_layout

    layout = _test_layout(tmp_path / "state", tmp_path / "workspace")
    target = tmp_path / "shared-target"
    target.mkdir(mode=0o755)
    layout.private_state_base.mkdir(mode=0o700)
    (layout.private_state_base / "plugins").symlink_to(
        target,
        target_is_directory=True,
    )

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        _prepare_private_state_layout(layout)

    assert caught.value.code == "coding_continuity_state_permissions_failed"
    assert target.stat().st_mode & 0o777 == 0o755


def test_configured_sources_resolve_relative_to_their_settings_scope(
    tmp_path: Path,
) -> None:
    from loushang.coding.continuity_bootstrap import _configured_sources

    project_base = tmp_path / "project-config"
    global_base = tmp_path / "global-config"
    cwd = tmp_path / "workspace"
    manager = SimpleNamespace(
        project_base_dir=project_base,
        global_base_dir=global_base,
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(
                "plugins/project",
                "plugins/global",
                "plugins/session",
            ),
            disabled_plugins=("disabled.example",),
        ),
        get_project_settings=lambda: {
            "plugin_sources": ["plugins/project"],
        },
        get_global_settings=lambda: {
            "plugin_sources": ["plugins/global"],
        },
        get_session_settings=lambda: {
            "plugin_sources": ["plugins/session"],
        },
    )

    sources, disabled = _configured_sources(manager, cwd=cwd)

    assert sources == (
        str((project_base / "plugins/project").resolve()),
        str((global_base / "plugins/global").resolve()),
        str((cwd / "plugins/session").resolve()),
    )
    assert disabled == frozenset({"disabled.example"})


def test_bootstrap_request_fingerprint_separates_source_and_disabled_boundaries(
    tmp_path: Path,
) -> None:
    from loushang.coding.continuity_bootstrap import _bootstrap_request_fingerprint

    first = _bootstrap_request_fingerprint(
        ("/workspace/a", "/workspace/b"),
        disabled_plugins=frozenset(),
        cwd=tmp_path,
        all_sessions=False,
    )
    second = _bootstrap_request_fingerprint(
        ("/workspace/a",),
        disabled_plugins=frozenset({"/workspace/b"}),
        cwd=tmp_path,
        all_sessions=False,
    )

    assert first != second


def test_invalid_config_is_redacted_and_recorded_before_composition(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path / "sessions")
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources="not-a-source-list",
            disabled_plugins=(),
        )
    )

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=settings,
                session_dir=runtime.session_dir,
                cwd=tmp_path,
            )
        )

    assert caught.value.code == "coding_continuity_plugin_sources_invalid"
    assert caught.value.__cause__ is None
    assert "not-a-source-list" not in str(caught.value)
    status = get_coding_continuity_bootstrap_status(runtime)
    assert status.state == "failed"
    assert status.retryable is False


def test_foreign_bootstrap_failure_suppresses_sensitive_exception_context(
    tmp_path: Path,
) -> None:
    secret_source = tmp_path / "customer-secret-plugin"
    runtime = _Runtime(tmp_path / "sessions")

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=_settings(secret_source),
                session_dir=runtime.session_dir,
                cwd=tmp_path / "workspace",
                materializer=_materializer_for_layout(
                    _test_layout(tmp_path / "state", tmp_path / "workspace")
                ),
                state_layout=_test_layout(
                    tmp_path / "state",
                    tmp_path / "workspace",
                ),
            )
        )

    rendered = "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert str(secret_source) not in rendered


def test_configured_continuity_base_only_preserves_legacy_binding(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path / "sessions")
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(),
            disabled_plugins=(),
        )
    )

    composition = bind_coding_continuity(runtime, cwd=tmp_path)
    adopted = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=tmp_path,
        )
    )

    assert adopted is composition
    assert composition.plugin_publication is None
    assert get_coding_configured_continuity_composition(runtime) is composition
    assert get_coding_continuity_bootstrap_status(runtime).to_dict() == {
        "state": "ready",
        "code": "coding_continuity_ready",
        "configuredSourceCount": 0,
        "pluginCount": 0,
        "providerCount": 0,
        "recoveredDeletionCount": 0,
        "retryable": False,
    }
    asyncio.run(shutdown_coding_continuity(runtime))


def test_empty_and_reentrant_continuity_bootstrap_reconcile_compatibility(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    paths = PlatformPaths(
        home=tmp_path / "home",
        data=tmp_path / "data",
        state=tmp_path / "state",
        cache=tmp_path / "cache",
        runtime=tmp_path / "runtime",
        temporary=tmp_path / "tmp",
    )
    common_layout = resolve_coding_plugin_lifecycle_state_layout(
        workspace,
        platform_paths=paths,
    )
    continuity_layout = resolve_coding_continuity_state_layout(
        workspace,
        platform_paths=paths,
    )
    lifecycle = build_coding_plugin_lifecycle(
        common_layout,
        startup_id="continuity-early-reconcile",
    )
    key = lifecycle.installation_key("continuity-example")
    package = PluginPackageRevisionRefV1(
        plugin_id="continuity-example",
        plugin_version="1.0.0",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity="local:continuity-example",
    )
    try:
        lifecycle.migrate_legacy_enablement(
            key,
            package,
            legacy_disabled=False,
            manifest_enabled_default=True,
            legacy_input_fingerprint=plugin_enablement_legacy_input_fingerprint(
                key,
                legacy_disabled=False,
                manifest_enabled_default=True,
            ),
        )
    finally:
        lifecycle.release_owned_process_startup_lease()

    settings_path = tmp_path / "settings.json"
    settings = SettingsManager(
        initial=ControlConfig(disabled_plugins=("continuity-example",)),
        project_settings_path=settings_path,
    )
    runtime = _Runtime(tmp_path / "sessions")
    first = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=workspace,
            state_layout=continuity_layout,
        )
    )

    assert settings.get_settings().disabled_plugins == ()
    settings_path.write_text(
        json.dumps({"disabled_plugins": ["continuity-example"]}),
        encoding="utf-8",
    )
    repeated = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=workspace,
            state_layout=continuity_layout,
        )
    )

    assert repeated is first
    assert settings.get_settings().disabled_plugins == ()
    with pytest.raises(PluginEnablementMigrationError):
        settings.disable_plugin("continuity-example")
    asyncio.run(shutdown_coding_continuity(runtime))


@pytest.mark.parametrize(
    ("configured_cwd", "configured_all_sessions"),
    (("other", False), ("original", True)),
)
def test_configured_continuity_rejects_unverifiable_legacy_scope_changes(
    tmp_path: Path,
    configured_cwd: str,
    configured_all_sessions: bool,
) -> None:
    runtime = _Runtime(tmp_path / "sessions")
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(),
            disabled_plugins=(),
        )
    )
    bind_coding_continuity(
        runtime,
        cwd=tmp_path / "original",
        all_sessions=False,
    )

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=settings,
                session_dir=runtime.session_dir,
                cwd=tmp_path / configured_cwd,
                all_sessions=configured_all_sessions,
            )
        )

    assert caught.value.code == "coding_continuity_composition_already_bound"
    assert caught.value.retryable is False
    assert get_coding_configured_continuity_composition(runtime) is None
    asyncio.run(shutdown_coding_continuity(runtime))


def test_configured_continuity_reentry_survives_slot_runtime_status_fallback(
    tmp_path: Path,
) -> None:
    class SlotRuntime:
        __slots__ = ("_loushang_coding_continuity",)

    runtime = SlotRuntime()
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(),
            disabled_plugins=(),
        )
    )
    first = asyncio.run(
        bind_coding_configured_continuity(
            runtime,  # type: ignore[arg-type]
            settings_manager=settings,
            session_dir=tmp_path / "sessions",
            cwd=tmp_path / "workspace",
        )
    )
    repeated = asyncio.run(
        bind_coding_configured_continuity(
            runtime,  # type: ignore[arg-type]
            settings_manager=settings,
            session_dir=tmp_path / "sessions",
            cwd=tmp_path / "workspace",
        )
    )

    assert repeated is first
    assert get_coding_continuity_bootstrap_status(runtime).state == "idle"
    assert get_coding_configured_continuity_composition(runtime) is first
    asyncio.run(shutdown_coding_continuity(runtime))


def test_configured_continuity_reentry_requires_the_exact_bootstrap_scope(
    tmp_path: Path,
) -> None:
    runtime = _Runtime(tmp_path / "sessions")
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(),
            disabled_plugins=(),
        )
    )
    first = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=tmp_path / "first",
            all_sessions=True,
        )
    )
    repeated = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=tmp_path / "first",
            all_sessions=True,
        )
    )
    assert repeated is first

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=settings,
                session_dir=runtime.session_dir,
                cwd=tmp_path / "second",
                all_sessions=True,
            )
        )
    assert caught.value.code == "coding_continuity_composition_already_bound"
    assert get_coding_continuity_bootstrap_status(runtime).state == "ready"
    asyncio.run(shutdown_coding_continuity(runtime))


def test_ready_and_failed_diagnostics_are_best_effort(
    tmp_path: Path,
) -> None:
    class BrokenDiagnostics:
        def capture_failure(self, **_kwargs: object) -> None:
            raise RuntimeError("diagnostic sink unavailable")

    runtime = _Runtime(tmp_path / "sessions")
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(),
            disabled_plugins=(),
        )
    )
    asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=tmp_path,
            diagnostics_service=BrokenDiagnostics(),  # type: ignore[arg-type]
        )
    )
    assert get_coding_continuity_bootstrap_status(runtime).state == "ready"
    asyncio.run(shutdown_coding_continuity(runtime))

    failed = _Runtime(tmp_path / "failed-sessions")
    invalid = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources="invalid",
            disabled_plugins=(),
        )
    )
    with pytest.raises(CodingContinuityBootstrapError):
        asyncio.run(
            bind_coding_configured_continuity(
                failed,
                settings_manager=invalid,
                session_dir=failed.session_dir,
                cwd=tmp_path,
                diagnostics_service=BrokenDiagnostics(),  # type: ignore[arg-type]
            )
        )
    assert get_coding_continuity_bootstrap_status(failed).state == "failed"


def test_real_configured_continuity_plugin_lifecycle_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_real_configured_lifecycle(tmp_path, monkeypatch))


def test_removed_continuity_tombstone_never_reinspects_configured_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding import continuity_bootstrap

    async def scenario() -> None:
        marker = tmp_path / "removed-plugin.log"
        monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
        plugin_root = _write_continuity_plugin(tmp_path / "removed-plugin")
        workspace = tmp_path / "workspace"
        layout = _test_layout(tmp_path / "state", workspace)
        settings = _settings(plugin_root)
        first_runtime = _Runtime(tmp_path / "sessions")
        first = await bind_coding_configured_continuity(
            first_runtime,
            settings_manager=settings,
            session_dir=first_runtime.session_dir,
            cwd=workspace,
            state_layout=layout,
            runtime_id="coding-process:tombstone-first",
        )
        assert first.plugin_publication is not None
        await shutdown_coding_continuity(first_runtime)

        lifecycle = continuity_bootstrap._build_lifecycle(layout)
        snapshot = lifecycle.desired.snapshot()
        [installed] = snapshot.installations
        removed = lifecycle.management.submit(
            PluginManagementCommandV1(
                action="remove",
                mutation=PluginDesiredStateMutationV1(
                    operation_id="remove-continuity-plugin",
                    idempotency_key="remove-continuity-plugin",
                    expected_inventory_revision=snapshot.inventory_revision,
                    installation_key=installed.installation_key,
                    desired_state="absent",
                    package_revision=None,
                    actor_id="test",
                    policy_revision="test",
                ),
            )
        )
        lifecycle.common.release_owned_process_startup_lease()
        assert removed.result is not None
        assert removed.result.disposition == "succeeded"
        forgotten = _materializer_for_layout(layout)
        forgotten.forget_plugin_binding(plugin_root)
        assert forgotten.get_plugin_binding(plugin_root) is None

        def reject_inspection(*_args, **_kwargs):
            raise AssertionError("removed source was reinspected")

        monkeypatch.setattr(
            continuity_bootstrap,
            "_inspect_continuity_source",
            reject_inspection,
        )
        restarted_runtime = _Runtime(tmp_path / "sessions")
        restarted = await bind_coding_configured_continuity(
            restarted_runtime,
            settings_manager=settings,
            session_dir=restarted_runtime.session_dir,
            cwd=workspace,
            state_layout=layout,
            runtime_id="coding-process:tombstone-restart",
        )

        assert restarted.plugin_publication is None
        assert (
            get_coding_continuity_bootstrap_status(restarted_runtime).plugin_count == 0
        )
        await shutdown_coding_continuity(restarted_runtime)

    asyncio.run(scenario())


def test_continuity_bootstrap_rejects_unsupported_secure_staging_before_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding import continuity_bootstrap

    marker = tmp_path / "unsupported.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    plugin_root = _write_continuity_plugin(tmp_path / "plugin")
    monkeypatch.setattr(
        continuity_bootstrap,
        "supports_coding_continuity_secure_staging",
        lambda: False,
    )
    runtime = _Runtime(tmp_path / "sessions")

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=_settings(plugin_root),
                session_dir=runtime.session_dir,
                cwd=tmp_path / "workspace",
                materializer=_materializer_for_layout(
                    _test_layout(tmp_path / "state", tmp_path / "workspace")
                ),
                state_layout=_test_layout(tmp_path / "state", tmp_path / "workspace"),
            )
        )

    assert caught.value.code == "coding_continuity_secure_staging_unsupported"
    assert caught.value.retryable is False
    assert not marker.exists()


def test_empty_selected_continuity_still_completes_common_startup_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding._plugin_lifecycle import CodingPluginLifecycle

    workspace = tmp_path / "workspace"
    layout = _test_layout(tmp_path / "state", workspace)
    plugin_root = _write_continuity_plugin(tmp_path / "plugin")
    settings = SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(str(plugin_root),),
            disabled_plugins=("continuity-example",),
        )
    )
    calls: list[Path] = []
    complete = CodingPluginLifecycle.complete_startup_recovery

    def track_complete(self: CodingPluginLifecycle) -> None:
        calls.append(self.layout.root)
        complete(self)

    monkeypatch.setattr(
        CodingPluginLifecycle,
        "complete_startup_recovery",
        track_complete,
    )
    runtime = _Runtime(tmp_path / "sessions")

    result = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=workspace,
            materializer=_materializer_for_layout(layout),
            state_layout=layout,
            runtime_id="coding-process:empty-selection",
        )
    )

    assert result.plugin_publication is None
    assert calls == [layout.root]
    key = next(
        item.installation_key
        for item in PluginDesiredStateLedger(layout.desired_state)
        .snapshot()
        .installations
        if item.installation_key.plugin_id == "continuity-example"
    )
    migration = PluginEnablementMigrationJournal(
        layout.root / "enablement-migration.jsonl"
    ).snapshot(key)
    assert migration is not None
    assert migration.phase == "compatibility_window"
    assert migration.disposition == "seeded"
    assert (
        PluginDesiredStateLedger(layout.desired_state)
        .snapshot()
        .installation(key)
        .selection.desired_state
        == "installed_disabled"
    )
    asyncio.run(shutdown_coding_continuity(runtime))


def test_continuity_bootstrap_rejects_noncanonical_package_authority(
    tmp_path: Path,
) -> None:
    plugin_root = _write_continuity_plugin(tmp_path / "plugin")
    runtime = _Runtime(tmp_path / "sessions")
    layout = _test_layout(tmp_path / "state", tmp_path / "workspace")

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=_settings(plugin_root),
                session_dir=runtime.session_dir,
                cwd=tmp_path / "workspace",
                materializer=PackageMaterializer(
                    install_root=runtime.session_dir / "packages"
                ),
                state_layout=layout,
            )
        )

    assert caught.value.code == "coding_continuity_package_authority_mismatch"
    assert caught.value.retryable is False
    assert not (runtime.session_dir / "package-lock.json").exists()


def test_continuity_bootstrap_selects_only_continuity_contributions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "mixed.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    plugin_root = _write_continuity_plugin(
        tmp_path / "mixed-plugin",
        include_unselected_tool_pack=True,
    )
    runtime = _Runtime(tmp_path / "sessions")
    composition = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=_settings(plugin_root),
            session_dir=runtime.session_dir,
            cwd=tmp_path / "workspace",
            materializer=_materializer_for_layout(
                _test_layout(tmp_path / "state", tmp_path / "workspace")
            ),
            state_layout=_test_layout(tmp_path / "state", tmp_path / "workspace"),
            runtime_id="coding-process:test-mixed",
            clock=lambda: 125,
        )
    )

    assert composition.plugin_publication is not None
    assert marker.read_text(encoding="utf-8").splitlines() == [
        "import",
        "create:https://sessions.invalid",
    ]
    asyncio.run(shutdown_coding_continuity(runtime))


def test_continuity_bootstrap_rejects_required_cross_owner_contribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "required-mixed.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    plugin_root = _write_continuity_plugin(
        tmp_path / "required-mixed-plugin",
        include_unselected_tool_pack=True,
        unselected_tool_pack_required=True,
    )
    runtime = _Runtime(tmp_path / "sessions")

    with pytest.raises(CodingContinuityBootstrapError) as caught:
        asyncio.run(
            bind_coding_configured_continuity(
                runtime,
                settings_manager=_settings(plugin_root),
                session_dir=runtime.session_dir,
                cwd=tmp_path / "workspace",
                materializer=_materializer_for_layout(
                    _test_layout(tmp_path / "state", tmp_path / "workspace")
                ),
                state_layout=_test_layout(
                    tmp_path / "state",
                    tmp_path / "workspace",
                ),
                runtime_id="coding-process:test-required-mixed",
                clock=lambda: 126,
            )
        )

    assert caught.value.code == "coding_continuity_definition_rejected"
    assert caught.value.retryable is False
    assert caught.value.__cause__ is None
    assert str(plugin_root) not in "".join(traceback.format_exception(caught.value))
    assert not marker.exists()
    status = get_coding_continuity_bootstrap_status(runtime)
    assert status.state == "failed"
    assert status.retryable is False


async def _real_configured_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "plugin.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    plugin_root = _write_continuity_plugin(tmp_path / "continuity-plugin")
    layout = _test_layout(tmp_path / "state", tmp_path / "workspace")
    settings = _settings(plugin_root)
    runtime = _Runtime(tmp_path / "sessions")

    composition = await bind_coding_configured_continuity(
        runtime,
        settings_manager=settings,
        session_dir=runtime.session_dir,
        cwd=tmp_path / "workspace",
        state_layout=layout,
        runtime_id="coding-process:test-first",
        clock=lambda: 150,
    )
    assert composition.plugin_publication is not None
    assert (layout.package_root / "package-lock.json").is_file()
    assert (layout.package_root / "plugin-revisions").is_dir()
    assert not (runtime.session_dir / "package-lock.json").exists()
    assert get_coding_continuity_bootstrap_status(runtime).provider_count == 1

    page = await composition.hub.query(
        ContinuityQuery(provider_ids=("continuity.example",))
    )
    [summary] = page.items
    assert summary.title == "Remote session"
    assert summary.actions == ("activate", "delete")
    preview = await composition.hub.preview(summary.target)
    assert preview.heading == "Remote session"
    lease = await composition.hub.prepare(summary.target)
    assert await consume_prepared_activation(lease) == {"restored": True}
    assert runtime.prepared_payloads == [b'{"session":"remote-1"}\n']
    [plugin_bound] = [
        item
        for item in composition.hub.composition.continuity_providers
        if item.source.source == "plugin"
    ]
    deletion_journal = PluginContinuityDeletionJournal.for_instance_runtime(
        layout.instance_runtime
    )
    deletion_journal.accept(
        ContinuityDeletionPlanV1(summary.target),
        plugin_bound.source,
    )

    await shutdown_coding_continuity(runtime)
    first_lines = marker.read_text(encoding="utf-8").splitlines()
    assert first_lines.count("delete-commit") == 0
    assert first_lines[-1] == "dispose"
    desired, intents, retirement_sets, security = _lifecycle_sources(layout)
    open_families = (
        PluginInstanceRuntimeLedger(
            layout.instance_runtime,
            management_operation_journal_path=layout.management_operations,
            desired_state=desired,
            retirement_intents=intents,
            retirement_sets=retirement_sets,
            security_acceptances=security,
        )
        .snapshot()
        .open_families
    )
    assert len(open_families) == 1
    assert open_families[0].lease_kind == "direct_host"
    assert open_families[0].holder_reference == (
        f"coding-continuity-host:{layout.scope_id}"
    )

    # Simulate a process exit after deletion acceptance but before Domain commit.
    # A new process must settle that exact operation before publishing its Hub.
    restarted = _Runtime(tmp_path / "sessions")
    second = await bind_coding_configured_continuity(
        restarted,
        settings_manager=settings,
        session_dir=restarted.session_dir,
        cwd=tmp_path / "workspace",
        state_layout=layout,
        runtime_id="coding-process:test-second",
        clock=lambda: 151,
    )
    assert (
        get_coding_continuity_bootstrap_status(restarted).recovered_deletion_count == 1
    )
    assert marker.read_text(encoding="utf-8").splitlines().count("delete-commit") == 1
    assert deletion_journal.pending() == ()
    second_page = await second.hub.query(
        ContinuityQuery(provider_ids=("continuity.example",))
    )
    assert second_page.items[0].target == summary.target
    assert await second.hub.delete(second_page.items[0].target) is True
    assert marker.read_text(encoding="utf-8").splitlines().count("delete-commit") == 2
    await shutdown_coding_continuity(restarted)


def test_bootstrap_failure_is_redacted_and_explicit_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        marker = tmp_path / "retry.log"
        monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
        first = _write_continuity_plugin(tmp_path / "first")
        second = _write_continuity_plugin(tmp_path / "second")
        sources = [str(first), str(second)]
        settings = SimpleNamespace(
            get_settings=lambda: SimpleNamespace(
                plugin_sources=tuple(sources),
                disabled_plugins=(),
            )
        )
        runtime = _Runtime(tmp_path / "sessions")
        retry_layout = _test_layout(
            tmp_path / "retry-state",
            tmp_path / "workspace",
        )

        def held_retry_startup_leases() -> tuple[Path, ...]:
            with plugin_lifecycle_module._PROCESS_STARTUP_LEASES_LOCK:
                return tuple(
                    lease_path
                    for lease_path in plugin_lifecycle_module._PROCESS_STARTUP_LEASES
                    if lease_path.is_relative_to(retry_layout.root)
                )

        kwargs = {
            "settings_manager": settings,
            "session_dir": runtime.session_dir,
            "cwd": tmp_path / "workspace",
            "materializer": _materializer_for_layout(retry_layout),
            "state_layout": retry_layout,
            "clock": lambda: 200,
        }

        with pytest.raises(CodingContinuityBootstrapError) as caught:
            await bind_coding_configured_continuity(runtime, **kwargs)
        assert caught.value.code == "coding_continuity_plugin_identity_ambiguous"
        assert str(first) not in str(caught.value)
        assert str(second) not in str(caught.value)
        status = get_coding_continuity_bootstrap_status(runtime)
        assert status.state == "failed"
        assert status.retryable is False
        [first_startup_lease] = held_retry_startup_leases()

        sources.pop()
        composition = await retry_coding_continuity_bootstrap(runtime, **kwargs)
        assert composition.plugin_publication is not None
        assert get_coding_continuity_bootstrap_status(runtime).state == "ready"
        assert held_retry_startup_leases() == (first_startup_lease,)
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def test_changed_source_replays_selected_revision_until_management_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        marker = tmp_path / "rollback.log"
        monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
        plugin_root = _write_continuity_plugin(tmp_path / "plugin")
        manifest_path = plugin_root / "plugin.json"
        original_manifest = manifest_path.read_bytes()
        layout = _test_layout(tmp_path / "state", tmp_path / "workspace")
        materializer = _materializer_for_layout(layout)
        kwargs = {
            "settings_manager": _settings(plugin_root),
            "session_dir": tmp_path / "sessions",
            "cwd": tmp_path / "workspace",
            "materializer": materializer,
            "state_layout": layout,
            "clock": lambda: 225,
        }

        first_runtime = _Runtime(tmp_path / "sessions")
        first = await bind_coding_configured_continuity(
            first_runtime,
            runtime_id="coding-process:revision-first",
            **kwargs,
        )
        assert first.plugin_publication is not None
        await shutdown_coding_continuity(first_runtime)

        changed = json.loads(original_manifest)
        changed["version"] = "2"
        manifest_path.write_text(json.dumps(changed), encoding="utf-8")
        changed_runtime = _Runtime(tmp_path / "sessions")
        replayed = await bind_coding_configured_continuity(
            changed_runtime,
            runtime_id="coding-process:revision-changed",
            **kwargs,
        )
        assert replayed.plugin_publication is not None
        await shutdown_coding_continuity(changed_runtime)

        shutil.rmtree(plugin_root)
        deleted_source_runtime = _Runtime(tmp_path / "sessions")
        restored = await bind_coding_configured_continuity(
            deleted_source_runtime,
            runtime_id="coding-process:revision-source-deleted",
            **kwargs,
        )
        assert restored.plugin_publication is not None
        await shutdown_coding_continuity(deleted_source_runtime)

    asyncio.run(scenario())


class _ContinuitySettings:
    def __init__(self, plugin_root: Path) -> None:
        self.value = SimpleNamespace(
            plugin_sources=(str(plugin_root),),
            disabled_plugins=(),
        )

    def get_settings(self):
        return self.value

    def bind_plugin_enablement_legacy_mutation_guard(self, authority, guard):
        assert authority is not None
        self.guard = guard

        def publish(projection):
            migrated = set(projection.migrated_plugin_ids)
            retained = {
                item for item in self.value.disabled_plugins if item not in migrated
            }
            self.value = SimpleNamespace(
                plugin_sources=self.value.plugin_sources,
                disabled_plugins=tuple(
                    sorted(retained | set(projection.disabled_plugin_ids))
                ),
            )

        return publish


def _settings(plugin_root: Path) -> object:
    return _ContinuitySettings(plugin_root)


def _test_layout(state_root: Path, workspace: Path):
    paths = PlatformPaths(
        home=state_root.parent / "home",
        data=state_root.parent / "data",
        state=state_root,
        cache=state_root.parent / "cache",
        runtime=state_root.parent / "runtime",
        temporary=state_root.parent / "tmp",
    )
    return resolve_coding_continuity_state_layout(workspace, platform_paths=paths)


def _materializer_for_layout(
    layout: CodingContinuityStateLayout,
) -> PackageMaterializer:
    return PackageMaterializer(
        install_root=layout.package_root / "installed",
        lockfile_path=layout.package_root / "package-lock.json",
        plugin_revision_root=layout.package_root / "plugin-revisions",
    )


def _lifecycle_sources(layout):
    from loushang.harness.plugin_management import (
        PluginDesiredStateLedger,
        PluginRetirementIntentLedger,
        PluginRetirementSetLedger,
    )
    from loushang.harness.plugin_management.continuity_adapter import (
        PluginContinuitySecurityRetirementJournal,
    )

    desired = PluginDesiredStateLedger(layout.desired_state)
    intents = PluginRetirementIntentLedger(layout.retirement_intents)
    sets = PluginRetirementSetLedger(
        layout.retirement_sets,
        retirement_intents=intents,
    )
    security = PluginContinuitySecurityRetirementJournal.for_instance_runtime(
        layout.instance_runtime
    )
    return desired, intents, sets, security


def _write_continuity_plugin(
    root: Path,
    *,
    include_unselected_tool_pack: bool = False,
    unselected_tool_pack_required: bool = False,
) -> Path:
    declarations = root / "declarations"
    declarations.mkdir(parents=True)
    item = {
        "configuration": {"endpoint": "https://sessions.invalid"},
        "contributionExecutionModel": "in_process",
        "declarationSource": {
            "kind": "document",
            "locator": "declarations/continuity.json",
            "mediaType": "application/vnd.loushang.plugin-declarations+json",
            "schemaId": "loushang.plugin-declaration-document",
            "schemaVersion": 1,
            "sourceVersion": 1,
        },
        "id": "remote-sessions",
        "kind": "continuity_provider",
        "owner": "harness.continuity",
        "requestedAuthorities": ["continuity.delete", "network.read"],
        "required": True,
    }
    items = [item]
    if include_unselected_tool_pack:
        (declarations / "unselected-invalid.json").write_text(
            "not a declaration document",
            encoding="utf-8",
        )
        items.append(
            {
                "configuration": {},
                "contributionExecutionModel": "data_only",
                "declarationSource": {
                    "kind": "document",
                    "locator": "declarations/unselected-invalid.json",
                    "mediaType": ("application/vnd.loushang.plugin-declarations+json"),
                    "schemaId": "loushang.plugin-declaration-document",
                    "schemaVersion": 1,
                    "sourceVersion": 1,
                },
                "id": "unselected-tools",
                "kind": "tool_pack",
                "owner": "tools.workspace",
                "requestedAuthorities": [],
                "required": unselected_tool_pack_required,
            }
        )
    contribution = PluginContributionReservation.from_dict(item)
    payload = ContinuityProviderDeclarationWirePayloadV2(
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=PluginSymbolReference(
            path="provider.py",
            symbol="dispose_provider",
            execution_model="in_process",
        ),
        supported_actions=("activate", "delete"),
        binding_inputs={"endpoint": "https://sessions.invalid"},
    )
    declaration = PluginDeclaration(
        plugin_id="continuity-example",
        contribution_id=contribution.contribution_id,
        kind=contribution.kind,
        owner=contribution.owner,
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        source_kind=contribution.declaration_source.kind,
        payload=payload.to_dict(),
    )
    (declarations / "continuity.json").write_bytes(
        PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(declarations=(declaration,))
        )
    )
    (root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "continuity-example",
                "version": "1",
                "contributionIndex": {"items": items, "version": 2},
            }
        ),
        encoding="utf-8",
    )
    (root / "provider.py").write_text(_PROVIDER_SOURCE, encoding="utf-8")
    return root


_PROVIDER_SOURCE = """\
import os
from pathlib import Path

from loushang.harness.continuity.import_provider import (
    CONTINUITY_JSONL_MEDIA_TYPE,
    ContinuityActivationPayload,
    ContinuityDeletionPlanV1,
    ContinuityDeletionReceiptV1,
    ContinuityImportProviderPack,
)
from loushang.harness.continuity.types import (
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuitySummary,
    ContinuityTarget,
    ProviderPage,
    ProviderPageItem,
)

MARKER = Path(os.environ["LOUSHANG_CONTINUITY_PLUGIN_MARKER"])
with MARKER.open("a", encoding="utf-8") as stream:
    stream.write("import\\n")

TARGET = ContinuityTarget("continuity.example", "remote-1", "r1")

class Prepared:
    @property
    def target(self):
        return TARGET

    @property
    def payload(self):
        return ContinuityActivationPayload.from_bytes(
            b'{"session":"remote-1"}\\n',
            media_type=CONTINUITY_JSONL_MEDIA_TYPE,
        )

    async def abort(self):
        return None

    async def close(self):
        return None

class PreparedDelete:
    def __init__(self):
        self._plan = ContinuityDeletionPlanV1(TARGET)

    @property
    def target(self):
        return TARGET

    @property
    def plan(self):
        return self._plan

    async def commit(self, plan):
        with MARKER.open("a", encoding="utf-8") as stream:
            stream.write("delete-commit\\n")
        return ContinuityDeletionReceiptV1(
            target=TARGET,
            plan_fingerprint=plan.fingerprint,
            disposition="applied",
        )

    async def abort(self):
        return None

    async def close(self):
        return None

class Provider:
    @property
    def descriptor(self):
        return ContinuityProviderDescriptor(
            provider_id="continuity.example",
            experience_id="coding",
            domain_ids=("coding",),
            primary_domain_id="coding",
            label="Remote sessions",
            supported_actions=("activate", "delete"),
        )

    async def query(self, request):
        return ProviderPage(
            items=(ProviderPageItem(
                summary=ContinuitySummary(
                    target=TARGET,
                    domain_ids=("coding",),
                    primary_domain_id="coding",
                    title="Remote session",
                    updated_at="2026-08-28T10:00:00Z",
                    actions=("activate", "delete"),
                ),
                after_cursor="remote-1",
            ),),
            has_more=False,
            index_state="fresh",
            index_generation="g1",
            query_snapshot="q1",
        )

    async def preview(self, target):
        return ContinuityPreview(
            target=target,
            revision=target.revision,
            heading="Remote session",
            sections=(ContinuityPreviewSection(kind="text", text="ready"),),
        )

    async def prepare_import(self, target):
        return Prepared()

    async def prepare_delete(self, target):
        return PreparedDelete()

def create_provider(context):
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write(f"create:{context.binding_inputs['endpoint']}\\n")
    return ContinuityImportProviderPack((Provider(),))

def dispose_provider(value):
    with MARKER.open("a", encoding="utf-8") as stream:
        stream.write("dispose\\n")
"""
