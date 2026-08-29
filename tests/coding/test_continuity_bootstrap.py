from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.continuity import shutdown_coding_continuity
from loushang.coding.continuity_bootstrap import (
    CodingContinuityBootstrapError,
    bind_coding_configured_continuity,
    get_coding_continuity_bootstrap_status,
    resolve_coding_continuity_state_layout,
    retry_coding_continuity_bootstrap,
)
from loushang.foundation.platform_paths import PlatformPaths
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
    PluginInstanceRuntimeLedger,
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
    assert "not-a-source-list" not in str(caught.value)
    status = get_coding_continuity_bootstrap_status(runtime)
    assert status.state == "failed"
    assert status.retryable is False


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

    composition = asyncio.run(
        bind_coding_configured_continuity(
            runtime,
            settings_manager=settings,
            session_dir=runtime.session_dir,
            cwd=tmp_path,
        )
    )

    assert composition.plugin_publication is None
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


def test_real_configured_continuity_plugin_lifecycle_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_real_configured_lifecycle(tmp_path, monkeypatch))


async def _real_configured_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "plugin.log"
    monkeypatch.setenv("LOUSHANG_CONTINUITY_PLUGIN_MARKER", str(marker))
    plugin_root = _write_continuity_plugin(tmp_path / "continuity-plugin")
    layout = _test_layout(tmp_path / "state", tmp_path / "workspace")
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    settings = _settings(plugin_root)
    runtime = _Runtime(tmp_path / "sessions")

    composition = await bind_coding_configured_continuity(
        runtime,
        settings_manager=settings,
        session_dir=runtime.session_dir,
        cwd=tmp_path / "workspace",
        materializer=materializer,
        state_layout=layout,
        runtime_id="coding-process:test-first",
        clock=lambda: 150,
    )
    assert composition.plugin_publication is not None
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
        materializer=materializer,
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
        kwargs = {
            "settings_manager": settings,
            "session_dir": runtime.session_dir,
            "cwd": tmp_path / "workspace",
            "materializer": PackageMaterializer(
                install_root=tmp_path / "retry-packages"
            ),
            "state_layout": _test_layout(
                tmp_path / "retry-state", tmp_path / "workspace"
            ),
            "runtime_id": "coding-process:test-retry",
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

        sources.pop()
        composition = await retry_coding_continuity_bootstrap(runtime, **kwargs)
        assert composition.plugin_publication is not None
        assert get_coding_continuity_bootstrap_status(runtime).state == "ready"
        await shutdown_coding_continuity(runtime)

    asyncio.run(scenario())


def _settings(plugin_root: Path) -> object:
    return SimpleNamespace(
        get_settings=lambda: SimpleNamespace(
            plugin_sources=(str(plugin_root),),
            disabled_plugins=(),
        )
    )


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


def _write_continuity_plugin(root: Path) -> Path:
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
                "contributionIndex": {"items": [item], "version": 2},
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
