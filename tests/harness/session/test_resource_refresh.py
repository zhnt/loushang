from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)
from loushang.harness.session.resource_refresh import SessionResourceRefreshRuntime


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
    ) -> None:
        self.events = events
        self.activation_error = activation_error
        self.activation_started = activation_started
        self.rollback_started = rollback_started
        self.release_rollback = release_rollback

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
    )


def test_session_resource_refresh_runtime_gets_prompt_templates_from_loader_then_bundle() -> (
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

    assert runtime.get_prompt_templates() == [loader_prompt]
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
        get_resource_loader=lambda: _Loader(
            ResourceBundle(cwd=Path("/tmp/project"))
        ),
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
    assert events == [
        "discover:reload",
        "activate",
        "publish",
        "restored",
        "rollback",
    ]


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
