from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.extensions.declarations import (
    ExtensionCapabilityDeclarationSnapshot,
    ExtensionGraphProviderRestartRequiredError,
    ExtensionRuntimeCapabilityDeclaration,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)
from loushang.harness.session.resource_refresh import (
    CatalogRefreshRequiresAsyncError,
    SessionResourceRefreshRuntime,
)


class _Loader:
    def __init__(self, bundle: ResourceBundle | Exception) -> None:
        self.bundle = bundle
        self.calls: list[str] = []

    def reload_resources(self, cwd: str) -> ResourceBundle:
        self.calls.append(cwd)
        if isinstance(self.bundle, Exception):
            raise self.bundle
        return self.bundle


class _ExtensionRuntime:
    def __init__(self) -> None:
        self.calls: list[ResourceBundle] = []

    def discover_resources(self, bundle: ResourceBundle) -> ResourceBundle:
        self.calls.append(bundle)
        return bundle.merge(
            prompts=[
                PromptFragmentDescriptor(
                    name="extension-refresh",
                    source_path=Path("/tmp/extension/prompts/refresh.md"),
                    text="extension refresh prompt",
                )
            ]
        )


class _AsyncExtensionRuntime:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    async def discover_resources_async(
        self, bundle: ResourceBundle, *, reason: str = "refresh"
    ) -> ResourceBundle:
        self.reasons.append(reason)
        await asyncio.sleep(0)
        return bundle.merge(
            prompts=[
                PromptFragmentDescriptor(
                    name="extension-refresh",
                    source_path=Path("/tmp/extension/prompts/async.md"),
                    text="async extension refresh prompt",
                )
            ]
        )


class _StagedRetirement:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def retire(self) -> None:
        self.events.append("retire")


class _StagedCandidate:
    def __init__(
        self,
        events: list[str],
        *,
        activation_error: BaseException | None = None,
        activation_started: asyncio.Event | None = None,
        rollback_started: asyncio.Event | None = None,
        release_rollback: asyncio.Event | None = None,
        publication_error: BaseException | None = None,
        capability_declarations: ExtensionCapabilityDeclarationSnapshot | None = None,
    ) -> None:
        self.events = events
        self.activation_error = activation_error
        self.activation_started = activation_started
        self.rollback_started = rollback_started
        self.release_rollback = release_rollback
        self.publication_error = publication_error
        self.capability_declarations = (
            capability_declarations
            if capability_declarations is not None
            else ExtensionCapabilityDeclarationSnapshot(declarations=())
        )

    async def discover_resources_async(
        self,
        bundle: ResourceBundle,
        *,
        reason: str,
    ) -> ResourceBundle:
        self.events.append(f"discover:{reason}")
        return bundle.merge(
            prompts=[
                PromptFragmentDescriptor(
                    name="candidate",
                    source_path=Path("/tmp/extension/prompts/candidate.md"),
                    text="candidate prompt",
                )
            ]
        )

    async def activate(self, bindings: object) -> None:
        del bindings
        self.events.append("activate")
        if self.activation_started is not None:
            self.activation_started.set()
            await asyncio.Event().wait()
        if self.activation_error is not None:
            raise self.activation_error

    def publish(self, commit_resource) -> _StagedRetirement:
        self.events.append("publish")
        commit_resource()
        self.events.append("committed")
        if self.publication_error is not None:
            raise self.publication_error
        return _StagedRetirement(self.events)

    async def rollback(self) -> None:
        self.events.append("rollback")
        if self.rollback_started is not None:
            self.rollback_started.set()
        if self.release_rollback is not None:
            await self.release_rollback.wait()


class _StagedExtensionRuntime:
    def __init__(self, candidate: _StagedCandidate) -> None:
        self.candidate = candidate
        self.extension_sets: list[list[object]] = []

    def prepare_generation(self, extensions) -> _StagedCandidate:
        self.extension_sets.append(list(extensions))
        return self.candidate


class _Settings:
    def get_disabled_skills(self) -> list[str]:
        return ["disabled-skill"]


class _PromptLoader:
    def __init__(self, prompts: object) -> None:
        self.prompts = prompts

    def get_prompts(self) -> dict[str, object]:
        return {"prompts": self.prompts}

    def reload_resources(self, cwd: str) -> ResourceBundle:
        raise AssertionError(f"unexpected reload for {cwd}")


def _runtime(
    *,
    loader: _Loader | _PromptLoader | None,
    bundle: ResourceBundle | None = None,
    extension_runtime: object | None = None,
    settings: _Settings | None = None,
    refreshed: list[ResourceBundle] | None = None,
    rebuilds: list[str] | None = None,
    failures: list[Exception] | None = None,
    syncs: list[str] | None = None,
    extension_declaration_preflight=None,
    catalog_refresh=None,
    prepare_refresh=None,
) -> SessionResourceRefreshRuntime:
    return SessionResourceRefreshRuntime(
        get_resource_loader=lambda: loader,
        get_resource_bundle=lambda: bundle,
        get_cwd=lambda: "/tmp/project",
        get_extension_runtime=lambda: extension_runtime,
        get_settings=lambda: settings,
        set_resource_bundle=(refreshed if refreshed is not None else []).append,
        rebuild_prompt_and_tools_view=lambda: (
            rebuilds if rebuilds is not None else []
        ).append("rebuild"),
        record_refresh_failure=(failures if failures is not None else []).append,
        sync_extension_diagnostics=lambda: (syncs if syncs is not None else []).append(
            "resource_loading"
        ),
        extension_declaration_preflight=extension_declaration_preflight,
        refresh_catalog=catalog_refresh,
        prepare_resource_refresh=prepare_refresh,
    )


def test_session_resource_refresh_runtime_gets_only_committed_prompt_templates() -> (
    None
):
    loader_prompt = PromptFragmentDescriptor(
        name="loader-prompt",
        source_path=Path("/tmp/project/prompts/loader.md"),
        text="loader prompt",
    )
    bundle_prompt = PromptFragmentDescriptor(
        name="bundle-prompt",
        source_path=Path("/tmp/project/prompts/bundle.md"),
        text="bundle prompt",
    )
    bundle = ResourceBundle(cwd=Path("/tmp/project"), prompts=[bundle_prompt])

    runtime = _runtime(loader=_PromptLoader([loader_prompt]), bundle=bundle)
    fallback_runtime = _runtime(loader=None, bundle=bundle)

    assert runtime.get_prompt_templates() == [bundle_prompt]
    assert fallback_runtime.get_prompt_templates() == [bundle_prompt]


def test_session_resource_refresh_runtime_reloads_discovers_disables_and_rebuilds() -> (
    None
):
    refreshed: list[ResourceBundle] = []
    rebuilds: list[str] = []
    extension_runtime = _ExtensionRuntime()
    loader = _Loader(
        ResourceBundle(
            cwd=Path("/tmp/project"),
            prompt_fragments=["runtime prompt"],
            skills=[
                SkillDescriptor(
                    name="enabled-skill",
                    source_path=Path("/tmp/project/skills/enabled/SKILL.md"),
                ),
                SkillDescriptor(
                    name="disabled-skill",
                    source_path=Path("/tmp/project/skills/disabled/SKILL.md"),
                ),
            ],
        )
    )
    runtime = _runtime(
        loader=loader,
        extension_runtime=extension_runtime,
        settings=_Settings(),
        refreshed=refreshed,
        rebuilds=rebuilds,
    )

    runtime.refresh()

    assert loader.calls == ["/tmp/project"]
    assert len(extension_runtime.calls) == 1
    assert len(refreshed) == 1
    bundle = refreshed[0]
    assert bundle.prompt_fragments == ["runtime prompt", "extension refresh prompt"]
    assert [descriptor.name for descriptor in bundle.prompt_descriptors] == [
        "runtime-reload-0",
        "extension-refresh",
    ]
    assert [skill.enabled for skill in bundle.skills] == [True, False]
    assert rebuilds == ["rebuild"]


def test_session_resource_refresh_runtime_awaits_async_extension_discovery() -> None:
    refreshed: list[ResourceBundle] = []
    rebuilds: list[str] = []
    extension_runtime = _AsyncExtensionRuntime()
    loader = _Loader(
        ResourceBundle(cwd=Path("/tmp/project"), prompt_fragments=["runtime prompt"])
    )
    runtime = _runtime(
        loader=loader,
        extension_runtime=extension_runtime,
        refreshed=refreshed,
        rebuilds=rebuilds,
    )

    asyncio.run(runtime.refresh_async(reason="reload"))

    assert extension_runtime.reasons == ["reload"]
    assert len(refreshed) == 1
    assert refreshed[0].prompt_fragments == [
        "runtime prompt",
        "async extension refresh prompt",
    ]
    assert rebuilds == ["rebuild"]


def test_session_resource_refresh_runtime_request_records_failures_once() -> None:
    failures: list[Exception] = []
    syncs: list[str] = []
    runtime = _runtime(
        loader=_Loader(RuntimeError("reload boom")),
        failures=failures,
        syncs=syncs,
    )

    runtime.request_refresh()

    assert [str(error) for error in failures] == ["reload boom"]
    assert syncs == []


def test_session_resource_refresh_runtime_request_without_loader_is_a_no_op() -> None:
    syncs: list[str] = []
    runtime = _runtime(loader=None, syncs=syncs)

    runtime.request_refresh()

    assert syncs == []


def test_catalog_refresh_is_async_only_and_never_enters_legacy_bundle_pipeline() -> (
    None
):
    events: list[str] = []
    loader = _Loader(AssertionError("legacy loader must not run"))

    async def refresh_catalog(reason: str) -> ResourceBundle:
        events.append(f"catalog:{reason}")
        return ResourceBundle(cwd=Path("/tmp/project"))

    runtime = _runtime(
        loader=loader,
        bundle=ResourceBundle(cwd=Path("/tmp/project")),
        catalog_refresh=refresh_catalog,
        prepare_refresh=lambda: events.append("prepare"),
    )

    with pytest.raises(CatalogRefreshRequiresAsyncError):
        runtime.refresh()
    asyncio.run(runtime.refresh_async(reason="watch"))

    assert events == ["prepare", "catalog:watch"]
    assert loader.calls == []
    assert runtime.resource_revision == 2


def test_catalog_refresh_request_coalesces_and_reports_one_success() -> None:
    events: list[str] = []

    async def scenario() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def refresh_catalog(reason: str) -> ResourceBundle:
            events.append(f"catalog:{reason}")
            started.set()
            await release.wait()
            return ResourceBundle(cwd=Path("/tmp/project"))

        runtime = _runtime(
            loader=None,
            catalog_refresh=refresh_catalog,
            syncs=events,
        )
        runtime.request_refresh()
        runtime.request_refresh()
        await started.wait()
        release.set()
        await runtime.close()

        assert runtime.resource_revision == 1

    asyncio.run(scenario())
    assert events == ["catalog:refresh", "resource_loading"]


def test_catalog_extension_reload_delegates_to_the_same_refresh_authority() -> None:
    events: list[str] = []

    async def refresh_catalog(reason: str) -> ResourceBundle:
        events.append(reason)
        return ResourceBundle(cwd=Path("/tmp/project"))

    current = ResourceBundle(cwd=Path("/tmp/current"))
    runtime = _runtime(
        loader=None,
        bundle=current,
        catalog_refresh=refresh_catalog,
    )

    result = asyncio.run(
        runtime.reload_extension_generation(object(), reason="extension-reload")
    )

    assert result is current
    assert events == ["extension-reload"]
    assert runtime.resource_revision == 2


def test_staged_extension_reload_publishes_resource_before_retiring_old_generation() -> (
    None
):
    events: list[str] = []
    refreshed: list[ResourceBundle] = []
    candidate = _StagedCandidate(events)
    extension_runtime = _StagedExtensionRuntime(candidate)
    runtime = _runtime(
        loader=_Loader(ResourceBundle(cwd=Path("/tmp/project"))),
        extension_runtime=extension_runtime,
        refreshed=refreshed,
        rebuilds=events,
    )

    result = asyncio.run(runtime.reload_extension_generation(object()))

    assert result is not None
    assert runtime.resource_revision == 1
    assert result.prompt_fragments == ["candidate prompt"]
    assert extension_runtime.extension_sets == [[]]
    assert refreshed == [result]
    assert events == [
        "discover:reload",
        "activate",
        "publish",
        "rebuild",
        "committed",
        "retire",
    ]


def test_staged_extension_reload_rejects_graph_provider_change_before_discovery() -> (
    None
):
    events: list[str] = []
    candidate_snapshot = ExtensionCapabilityDeclarationSnapshot(
        declarations=(
            ExtensionRuntimeCapabilityDeclaration(
                extension_id="example",
                slot="prompt.sections",
                name="replacement",
                implementation_version=2,
                priority=10,
                granted_permissions=("prompt.sections",),
            ),
        )
    )
    candidate = _StagedCandidate(
        events,
        capability_declarations=candidate_snapshot,
    )
    seen: list[ExtensionCapabilityDeclarationSnapshot] = []

    def preflight(snapshot: ExtensionCapabilityDeclarationSnapshot) -> None:
        seen.append(snapshot)
        raise ExtensionGraphProviderRestartRequiredError(
            capability_ids=("harness.resources",),
            changed_slots=("prompt.sections",),
            baseline_fingerprint="a" * 64,
            candidate_fingerprint="b" * 64,
        )

    runtime = _runtime(
        loader=_Loader(ResourceBundle(cwd=Path("/tmp/project"))),
        extension_runtime=_StagedExtensionRuntime(candidate),
        extension_declaration_preflight=preflight,
    )

    with pytest.raises(ExtensionGraphProviderRestartRequiredError):
        asyncio.run(runtime.reload_extension_generation(object()))

    assert seen == [candidate_snapshot]
    assert events == ["rollback"]
    assert runtime.resource_revision == 0


def test_staged_extension_reload_rejects_async_preflight_before_effects() -> None:
    events: list[str] = []
    candidate = _StagedCandidate(events)

    async def invalid_preflight(
        _snapshot: ExtensionCapabilityDeclarationSnapshot,
    ) -> None:
        events.append("preflight")

    runtime = _runtime(
        loader=_Loader(ResourceBundle(cwd=Path("/tmp/project"))),
        extension_runtime=_StagedExtensionRuntime(candidate),
        extension_declaration_preflight=invalid_preflight,
    )

    with pytest.raises(TypeError, match="must be synchronous"):
        asyncio.run(runtime.reload_extension_generation(object()))

    assert events == ["rollback"]
    assert runtime.resource_revision == 0


def test_staged_extension_reload_rolls_back_failed_candidate_without_commit() -> None:
    events: list[str] = []
    refreshed: list[ResourceBundle] = []
    candidate = _StagedCandidate(
        events,
        activation_error=RuntimeError("candidate failed"),
    )
    runtime = _runtime(
        loader=_Loader(ResourceBundle(cwd=Path("/tmp/project"))),
        extension_runtime=_StagedExtensionRuntime(candidate),
        refreshed=refreshed,
    )

    with pytest.raises(RuntimeError, match="candidate failed"):
        asyncio.run(runtime.reload_extension_generation(object()))

    assert events == ["discover:reload", "activate", "rollback"]
    assert refreshed == []


def test_staged_extension_reload_joins_candidate_rollback_when_cancelled() -> None:
    events: list[str] = []
    activation_started = asyncio.Event()
    candidate = _StagedCandidate(
        events,
        activation_started=activation_started,
    )
    runtime = _runtime(
        loader=_Loader(ResourceBundle(cwd=Path("/tmp/project"))),
        extension_runtime=_StagedExtensionRuntime(candidate),
    )

    async def scenario() -> None:
        task = asyncio.create_task(runtime.reload_extension_generation(object()))
        await activation_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert events == ["discover:reload", "activate", "rollback"]


def test_staged_extension_reload_restores_resource_when_publication_fails() -> None:
    events: list[str] = []
    previous = ResourceBundle(cwd=Path("/tmp/project"), prompt_fragments=["old"])
    current: list[ResourceBundle | None] = [previous]
    candidate = _StagedCandidate(events)

    def set_bundle(bundle: ResourceBundle | None) -> None:
        current[0] = bundle

    def rebuild() -> None:
        if current[0] is not previous:
            raise RuntimeError("view rebuild failed")
        events.append("restored")

    runtime = SessionResourceRefreshRuntime(
        get_resource_loader=lambda: _Loader(ResourceBundle(cwd=Path("/tmp/project"))),
        get_resource_bundle=lambda: current[0],
        get_cwd=lambda: "/tmp/project",
        get_extension_runtime=lambda: _StagedExtensionRuntime(candidate),
        get_settings=lambda: None,
        set_resource_bundle=set_bundle,
        rebuild_prompt_and_tools_view=rebuild,
        record_refresh_failure=lambda error: None,
        sync_extension_diagnostics=lambda: None,
    )

    with pytest.raises(RuntimeError, match="view rebuild failed"):
        asyncio.run(runtime.reload_extension_generation(object()))

    assert current == [previous]
    assert runtime.resource_revision == 1
    assert events == [
        "discover:reload",
        "activate",
        "publish",
        "restored",
        "rollback",
    ]


def test_staged_extension_reload_restores_revision_when_publish_fails_after_commit() -> (
    None
):
    events: list[str] = []
    previous = ResourceBundle(cwd=Path("/tmp/old"), prompt_fragments=["old"])
    current: list[ResourceBundle | None] = [previous]
    candidate = _StagedCandidate(
        events,
        publication_error=RuntimeError("publication failed after commit"),
    )
    runtime = SessionResourceRefreshRuntime(
        get_resource_loader=lambda: _Loader(ResourceBundle(cwd=Path("/tmp/new"))),
        get_resource_bundle=lambda: current[0],
        get_cwd=lambda: "/tmp/project",
        get_extension_runtime=lambda: _StagedExtensionRuntime(candidate),
        get_settings=lambda: None,
        set_resource_bundle=lambda bundle: current.__setitem__(0, bundle),
        rebuild_prompt_and_tools_view=lambda: events.append("rebuild"),
        record_refresh_failure=lambda error: None,
        sync_extension_diagnostics=lambda: None,
    )

    with pytest.raises(RuntimeError, match="publication failed after commit"):
        asyncio.run(runtime.reload_extension_generation(object()))

    assert current == [previous]
    assert runtime.resource_revision == 1
    assert events[-1] == "rollback"


def test_failed_view_restoration_still_restores_publication_revision() -> None:
    previous = ResourceBundle(cwd=Path("/tmp/old"), prompt_fragments=["old"])
    current: list[ResourceBundle | None] = [previous]
    candidate = _StagedCandidate(
        [],
        publication_error=RuntimeError("publication failed after commit"),
    )

    def rebuild() -> None:
        if current[0] is previous:
            raise RuntimeError("restoration rebuild failed")

    runtime = SessionResourceRefreshRuntime(
        get_resource_loader=lambda: _Loader(ResourceBundle(cwd=Path("/tmp/new"))),
        get_resource_bundle=lambda: current[0],
        get_cwd=lambda: "/tmp/project",
        get_extension_runtime=lambda: _StagedExtensionRuntime(candidate),
        get_settings=lambda: None,
        set_resource_bundle=lambda bundle: current.__setitem__(0, bundle),
        rebuild_prompt_and_tools_view=rebuild,
        record_refresh_failure=lambda error: None,
        sync_extension_diagnostics=lambda: None,
    )

    with pytest.raises(
        RuntimeError,
        match="publication failed after commit",
    ) as caught:
        asyncio.run(runtime.reload_extension_generation(object()))

    assert current == [previous]
    assert runtime.resource_revision == 1
    assert "previous resource bundle view restoration failed" in caught.value.__notes__


def test_failed_publication_restores_old_resource_before_async_candidate_cleanup() -> (
    None
):
    previous = ResourceBundle(cwd=Path("/tmp/old"))
    current: list[ResourceBundle | None] = [previous]
    rollback_started = asyncio.Event()
    release_rollback = asyncio.Event()
    candidate = _StagedCandidate(
        [],
        rollback_started=rollback_started,
        release_rollback=release_rollback,
    )

    def rebuild() -> None:
        if current[0] is not previous:
            raise RuntimeError("view rebuild failed")

    runtime = SessionResourceRefreshRuntime(
        get_resource_loader=lambda: _Loader(ResourceBundle(cwd=Path("/tmp/new"))),
        get_resource_bundle=lambda: current[0],
        get_cwd=lambda: "/tmp/project",
        get_extension_runtime=lambda: _StagedExtensionRuntime(candidate),
        get_settings=lambda: None,
        set_resource_bundle=lambda bundle: current.__setitem__(0, bundle),
        rebuild_prompt_and_tools_view=rebuild,
        record_refresh_failure=lambda error: None,
        sync_extension_diagnostics=lambda: None,
    )

    async def scenario() -> None:
        task = asyncio.create_task(runtime.reload_extension_generation(object()))
        await rollback_started.wait()
        assert current == [previous]
        release_rollback.set()
        with pytest.raises(RuntimeError, match="view rebuild failed"):
            await task

    asyncio.run(scenario())
