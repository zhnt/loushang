from __future__ import annotations

import asyncio

from loushang.harness.extensions.context import SessionStartEvent
from loushang.harness.extensions.session_runtime import ExtensionSessionRuntime


class Runner:
    def __init__(self) -> None:
        self.bindings: list[object] = []
        self.refresh_bindings: list[object] = []
        self.start_reasons: list[str] = []
        self.refresh_reasons: list[str] = []
        self.invalidations: list[str] = []
        self.refreshing_during_emit: list[bool] = []
        self.controller: ExtensionSessionRuntime | None = None

    def bind_runtime(self, bindings: object) -> None:
        self.bindings.append(bindings)

    def refresh_runtime(self, bindings: object) -> None:
        self.refresh_bindings.append(bindings)

    async def emit_session_start(self, event: SessionStartEvent) -> None:
        self.start_reasons.append(event.reason)

    async def emit_session_refresh(self, event) -> None:
        self.refresh_reasons.append(event.reason)
        assert self.controller is not None
        self.refreshing_during_emit.append(self.controller.is_refreshing)

    def invalidate_contexts(self, message: str) -> None:
        self.invalidations.append(message)


def test_extension_runtime_controller_binds_reloads_and_refreshes_with_guard() -> None:
    runner = Runner()
    diagnostics_syncs: list[str] = []
    resource_refreshes: list[str] = []
    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {
            "binding": len(runner.bindings) + len(runner.refresh_bindings)
        },
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: resource_refreshes.append("refresh"),
        record_runtime_diagnostic=lambda diagnostic: None,
        sync_extension_diagnostics=lambda *, phase: diagnostics_syncs.append(phase),
    )
    runner.controller = controller

    async def scenario() -> None:
        await controller.bind(reason="startup")
        await controller.bind(reason="reload")
        await controller.refresh(reason="model_selection_changed")

    asyncio.run(scenario())

    assert runner.bindings == [{"binding": 0}, {"binding": 1}]
    assert runner.refresh_bindings == [{"binding": 2}]
    assert runner.start_reasons == ["startup", "reload"]
    assert runner.refresh_reasons == ["model_selection_changed"]
    assert runner.invalidations == [
        "Extension context is stale after extension reload."
    ]
    assert resource_refreshes == ["refresh"]
    assert runner.refreshing_during_emit == [True]
    assert controller.is_refreshing is False
    assert diagnostics_syncs == ["runtime", "runtime", "runtime"]


def test_extension_runtime_controller_awaits_async_resource_refresh_on_reload() -> None:
    runner = Runner()
    resource_refreshes: list[str] = []

    async def refresh_resources() -> None:
        await asyncio.sleep(0)
        resource_refreshes.append("refresh")

    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {"binding": len(runner.bindings)},
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=refresh_resources,
        record_runtime_diagnostic=lambda diagnostic: None,
        sync_extension_diagnostics=lambda *, phase: None,
    )

    asyncio.run(controller.bind(reason="reload"))

    assert resource_refreshes == ["refresh"]
    assert runner.bindings == [{"binding": 0}]
    assert runner.start_reasons == ["reload"]


def test_extension_runtime_controller_uses_staged_reload_without_preinvalidating() -> (
    None
):
    runner = Runner()
    staged_bindings: list[object] = []
    legacy_refreshes: list[str] = []

    async def reload_generation(bindings: object) -> None:
        await asyncio.sleep(0)
        staged_bindings.append(bindings)

    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {"binding": "candidate"},
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: legacy_refreshes.append("legacy"),
        reload_generation=reload_generation,
        record_runtime_diagnostic=lambda diagnostic: None,
        sync_extension_diagnostics=lambda *, phase: None,
    )

    asyncio.run(controller.bind(reason="reload"))

    assert staged_bindings == [{"binding": "candidate"}]
    assert runner.bindings == []
    assert runner.invalidations == []
    assert legacy_refreshes == []
    assert runner.start_reasons == ["reload"]


def test_extension_runtime_controller_keeps_old_generation_on_staged_failure() -> (
    None
):
    runner = Runner()
    diagnostics: list[str] = []

    async def reload_generation(bindings: object) -> None:
        del bindings
        raise RuntimeError("candidate failed")

    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: object(),
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: None,
        reload_generation=reload_generation,
        record_runtime_diagnostic=lambda diagnostic: diagnostics.append(
            diagnostic.code
        ),
        sync_extension_diagnostics=lambda *, phase: None,
    )

    asyncio.run(controller.bind(reason="reload"))

    assert runner.bindings == []
    assert runner.invalidations == []
    assert runner.start_reasons == []
    assert diagnostics == ["extension_resource_refresh_failed"]


def test_extension_runtime_controller_records_bind_failures() -> None:
    class BrokenRunner(Runner):
        def bind_runtime(self, bindings: object) -> None:
            del bindings
            raise RuntimeError("bind failed")

    diagnostics: list[str] = []
    controller = ExtensionSessionRuntime(
        extension_runtime=BrokenRunner(),
        build_bindings=lambda: object(),
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: None,
        record_runtime_diagnostic=lambda diagnostic: diagnostics.append(
            diagnostic.code
        ),
        sync_extension_diagnostics=lambda *, phase: None,
    )

    asyncio.run(controller.bind(reason="startup"))

    assert diagnostics == ["extension_runtime_bind_failed"]


def test_extension_runtime_controller_records_session_start_emit_failures() -> None:
    class BrokenStartRunner(Runner):
        async def emit_session_start(self, event: SessionStartEvent) -> None:
            del event
            raise RuntimeError("start transport boom")

    diagnostics: list[tuple[str, str]] = []
    diagnostics_syncs: list[str] = []
    runner = BrokenStartRunner()
    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {"binding": len(runner.bindings)},
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: None,
        record_runtime_diagnostic=lambda diagnostic: diagnostics.append(
            (diagnostic.code, diagnostic.message)
        ),
        sync_extension_diagnostics=lambda *, phase: diagnostics_syncs.append(phase),
    )

    asyncio.run(controller.bind(reason="startup"))

    assert runner.bindings == [{"binding": 0}]
    assert diagnostics == [
        (
            "extension_session_start_failed",
            "Extension hook 'session_start' failed: start transport boom",
        )
    ]
    assert diagnostics_syncs == ["runtime"]


def test_extension_runtime_controller_records_session_refresh_emit_failures() -> None:
    class BrokenRefreshRunner(Runner):
        async def emit_session_refresh(self, event) -> None:
            self.refresh_reasons.append(event.reason)
            assert self.controller is not None
            self.refreshing_during_emit.append(self.controller.is_refreshing)
            raise RuntimeError("refresh transport boom")

    diagnostics: list[tuple[str, str]] = []
    diagnostics_syncs: list[str] = []
    runner = BrokenRefreshRunner()
    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {"binding": len(runner.refresh_bindings)},
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: None,
        record_runtime_diagnostic=lambda diagnostic: diagnostics.append(
            (diagnostic.code, diagnostic.message)
        ),
        sync_extension_diagnostics=lambda *, phase: diagnostics_syncs.append(phase),
    )
    runner.controller = controller

    asyncio.run(controller.refresh(reason="model_selection_changed"))

    assert runner.refresh_bindings == [{"binding": 0}]
    assert runner.refresh_reasons == ["model_selection_changed"]
    assert runner.refreshing_during_emit == [True]
    assert controller.is_refreshing is False
    assert diagnostics == [
        (
            "extension_session_refresh_failed",
            "Extension hook 'session_refresh' failed: refresh transport boom",
        )
    ]
    assert diagnostics_syncs == ["runtime"]


def test_extension_runtime_controller_records_refresh_runtime_failures() -> None:
    class BrokenRefreshRuntimeRunner(Runner):
        def refresh_runtime(self, bindings: object) -> None:
            del bindings
            raise RuntimeError("refresh runtime boom")

    diagnostics: list[tuple[str, str]] = []
    diagnostics_syncs: list[str] = []
    runner = BrokenRefreshRuntimeRunner()
    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {"binding": len(runner.refresh_bindings)},
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: None,
        record_runtime_diagnostic=lambda diagnostic: diagnostics.append(
            (diagnostic.code, diagnostic.message)
        ),
        sync_extension_diagnostics=lambda *, phase: diagnostics_syncs.append(phase),
    )
    runner.controller = controller

    asyncio.run(controller.refresh(reason="resource_watch"))

    assert runner.refresh_bindings == []
    assert runner.refresh_reasons == []
    assert controller.is_refreshing is False
    assert diagnostics == [
        (
            "extension_runtime_refresh_failed",
            "Extension runtime refresh failed: refresh runtime boom",
        )
    ]
    assert diagnostics_syncs == []


def test_extension_runtime_controller_refresh_bindings_records_failures() -> None:
    class BrokenRefreshRuntimeRunner(Runner):
        def refresh_runtime(self, bindings: object) -> None:
            del bindings
            raise RuntimeError("refresh bindings boom")

    diagnostics: list[tuple[str, str]] = []
    runner = BrokenRefreshRuntimeRunner()
    controller = ExtensionSessionRuntime(
        extension_runtime=runner,
        build_bindings=lambda: {"binding": len(runner.refresh_bindings)},
        session_start_event=SessionStartEvent(reason="startup"),
        refresh_resources=lambda: None,
        record_runtime_diagnostic=lambda diagnostic: diagnostics.append(
            (diagnostic.code, diagnostic.message)
        ),
        sync_extension_diagnostics=lambda *, phase: None,
    )

    controller.refresh_bindings()

    assert runner.refresh_bindings == []
    assert diagnostics == [
        (
            "extension_runtime_refresh_failed",
            "Extension runtime refresh failed: refresh bindings boom",
        )
    ]
