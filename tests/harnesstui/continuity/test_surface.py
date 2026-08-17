from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from types import SimpleNamespace

from loushang.harness.continuity import (
    ContinuityDiagnostic,
    ContinuityPage,
    ContinuityPreview,
    ContinuityPreviewSection,
    ContinuityProviderDescriptor,
    ContinuityQuery,
    ContinuitySummary,
    ContinuityTarget,
    ProviderPageState,
)
from loushang.harnesstui.continuity import (
    ContinuitySurface,
    build_continuity_surface_view,
    run_continuity_picker,
)
from loushang.harnesstui.surface.controller import normalize_surface_intent
from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    TuiInputResult,
    strip_control_sequences,
    visible_width,
)


@dataclass
class _Provider:
    descriptor: ContinuityProviderDescriptor


class _Hub:
    def __init__(self) -> None:
        descriptor = ContinuityProviderDescriptor(
            provider_id="coding.sessions",
            experience_id="studio",
            domain_ids=("coding",),
            label="Coding",
            supported_sorts=("updated", "created"),
        )
        self.composition = SimpleNamespace(
            experience=SimpleNamespace(domain_ids=("coding", "design")),
            continuity_providers=(SimpleNamespace(provider=_Provider(descriptor)),),
        )
        self.queries: list[ContinuityQuery] = []
        self.previewed: list[ContinuityTarget] = []
        self.summary = ContinuitySummary(
            target=ContinuityTarget(
                provider_id="coding.sessions",
                opaque_id="session-1",
                revision="1",
            ),
            domain_ids=("coding",),
            primary_domain_id="coding",
            title="Review the parser",
            updated_at="2026-07-24T00:00:00Z",
            created_at="2026-07-23T00:00:00Z",
            excerpt="Parser discussion",
        )

    async def query(self, request: ContinuityQuery) -> ContinuityPage:
        self.queries.append(request)
        items = (
            (self.summary,)
            if not request.text or request.text.lower() in self.summary.title.lower()
            else ()
        )
        return ContinuityPage(
            items=items,
            next_cursor=None,
            provider_diagnostics=(),
            partial=False,
            ordering_complete=True,
            provider_states={
                "coding.sessions": ProviderPageState(
                    index_state="fresh",
                    index_generation="generation-1",
                    query_snapshot="snapshot-1",
                )
            },
            aggregate_index_state="fresh",
        )

    async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
        self.previewed.append(target)
        return ContinuityPreview(
            target=target,
            revision=target.revision,
            heading="Review the parser",
            sections=(
                ContinuityPreviewSection(
                    kind="key_value",
                    rows=(("Messages", "4"),),
                ),
            ),
        )


def test_common_resume_view_is_a_real_page_and_renders_loading_first() -> None:
    hub = _Hub()
    renders: list[str] = []
    view = build_continuity_surface_view(
        hub=hub,  # type: ignore[arg-type]
        request_render=renders.append,
    )

    before = view.render(RenderConstraints(width=80, max_height=12))
    assert view.presentation == "page"
    assert any("Loading" in line.text for line in before.lines)
    assert hub.queries == []

    asyncio.run(view.content.start())
    after = view.render(RenderConstraints(width=80, max_height=12))

    assert any("Review the parser" in line.text for line in after.lines)
    assert hub.queries == [ContinuityQuery()]
    assert renders


def test_continuity_surface_can_exclude_non_selectable_summaries() -> None:
    hub = _Hub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
        include_summary=lambda _summary: False,
        selection_action="delete",
    )

    async def scenario() -> None:
        await surface.start()
        assert surface.selected_target is None
        assert "delete" in surface.footer_help
        surface.close()

    asyncio.run(scenario())


def test_delete_continuity_view_uses_the_delete_surface_purpose() -> None:
    view = build_continuity_surface_view(
        hub=_Hub(),  # type: ignore[arg-type]
        request_render=lambda _kind: None,
        title="Delete a previous session",
        selection_action="delete",
        purpose="delete",
    )

    assert view.purpose == "delete"


def test_common_resume_requeries_after_background_index_rebuild() -> None:
    class _RebuildingHub(_Hub):
        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            ready = len(self.queries) > 1
            return ContinuityPage(
                items=(self.summary,) if ready else (),
                next_cursor=None,
                provider_diagnostics=(),
                partial=False,
                ordering_complete=True,
                provider_states={
                    "coding.sessions": ProviderPageState(
                        index_state="fresh" if ready else "rebuilding",
                        index_generation="generation-1" if ready else "unavailable",
                        query_snapshot="snapshot-1" if ready else "unavailable",
                    )
                },
                aggregate_index_state="fresh" if ready else "rebuilding",
            )

    hub = _RebuildingHub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    async def scenario() -> None:
        await surface.start()
        assert surface.selected_target is None
        await asyncio.sleep(0.6)
        assert surface.selected_target == hub.summary.target
        assert len(hub.queries) == 2
        surface.close()

    asyncio.run(scenario())


def test_common_resume_keeps_background_index_refresh_visually_stable() -> None:
    class _SlowRebuildingHub(_Hub):
        def __init__(self) -> None:
            super().__init__()
            self.release = asyncio.Event()

        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            if len(self.queries) > 1:
                await self.release.wait()
            ready = len(self.queries) > 1
            return ContinuityPage(
                items=(self.summary,) if ready else (),
                next_cursor=None,
                provider_diagnostics=(),
                partial=False,
                ordering_complete=True,
                provider_states={
                    "coding.sessions": ProviderPageState(
                        index_state="fresh" if ready else "stale",
                        index_generation="generation-1" if ready else "stale",
                        query_snapshot="snapshot-1" if ready else "stale",
                    )
                },
                aggregate_index_state="fresh" if ready else "stale",
            )

    hub = _SlowRebuildingHub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    async def scenario() -> None:
        await surface.start()
        initial = surface.render(RenderConstraints(width=80, max_height=12))
        assert surface.loading is False
        assert sum("Loading sessions" in line.text for line in initial.lines) == 1

        await asyncio.sleep(0.55)
        refreshing = surface.render(RenderConstraints(width=80, max_height=12))
        assert len(hub.queries) == 2
        assert surface.loading is False
        assert [line.text for line in refreshing.lines] == [
            line.text for line in initial.lines
        ]

        hub.release.set()
        await asyncio.sleep(0)
        assert surface.selected_target == hub.summary.target
        surface.close()

    asyncio.run(scenario())


def test_common_resume_distinguishes_empty_and_partial_responsive_views() -> None:
    class _PageHub(_Hub):
        def __init__(self, page: ContinuityPage) -> None:
            super().__init__()
            self.page = page

        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            return self.page

    empty_hub = _PageHub(
        ContinuityPage(
            items=(),
            next_cursor=None,
            provider_diagnostics=(),
            partial=False,
            ordering_complete=True,
            provider_states={},
            aggregate_index_state="fresh",
        )
    )
    empty_view = build_continuity_surface_view(
        hub=empty_hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )
    asyncio.run(empty_view.content.start())
    narrow = empty_view.render(RenderConstraints(width=28, max_height=14))
    assert any("No sessions yet" in line.text for line in narrow.lines)
    assert all(visible_width(line.text) <= 28 for line in narrow.lines)

    diagnostic = ContinuityDiagnostic(
        code="provider_unavailable",
        message="Design history is temporarily unavailable",
        provider_id="design.canvases",
    )
    partial_hub = _PageHub(
        ContinuityPage(
            items=(empty_hub.summary,),
            next_cursor=None,
            provider_diagnostics=(diagnostic,),
            partial=True,
            ordering_complete=False,
            provider_states={
                "coding.sessions": ProviderPageState(
                    index_state="fresh",
                    index_generation="generation-1",
                    query_snapshot="snapshot-1",
                )
            },
            aggregate_index_state="fresh",
        )
    )
    partial_view = build_continuity_surface_view(
        hub=partial_hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )
    asyncio.run(partial_view.content.start())
    wide = partial_view.render(RenderConstraints(width=120, max_height=24))
    assert any("Partial results:" in line.text for line in wide.lines)
    assert all(visible_width(line.text) <= 120 for line in wide.lines)


def test_common_resume_uses_compact_colored_picker_chrome() -> None:
    hub = _Hub()
    view = build_continuity_surface_view(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    wide = view.render(RenderConstraints(width=80, max_height=14))
    wide_lines = [strip_control_sequences(line.text) for line in wide.lines]

    assert wide_lines[0] == "Resume a previous session"
    assert "continuity item" not in "\n".join(wide_lines)
    assert wide_lines[2].startswith("Type to search")
    assert wide_lines[2].rstrip().endswith("Sort: [Updated] Created")
    assert "Loading sessions…" in wide_lines
    assert "\x1b[" in wide.lines[0].text
    assert "\x1b[" in wide.lines[2].text

    compact = view.render(RenderConstraints(width=40, max_height=14))
    compact_lines = [strip_control_sequences(line.text) for line in compact.lines]
    assert compact_lines[2].startswith("Type to search")
    assert compact_lines[2].endswith("Sort:[Updated]")

    narrow = view.render(RenderConstraints(width=28, max_height=14))
    narrow_lines = [strip_control_sequences(line.text) for line in narrow.lines]
    assert narrow_lines[2] == "Type to search"
    assert narrow_lines[3] == "Sort:[Updated]"
    assert all(visible_width(line.text) <= 28 for line in narrow.lines)


def test_common_resume_adds_neutral_domain_filter_for_multi_provider_experience() -> (
    None
):
    hub = _Hub()
    design = ContinuityProviderDescriptor(
        provider_id="design.canvases",
        experience_id="studio",
        domain_ids=("design",),
        label="Design",
        supported_sorts=("updated", "created"),
    )
    hub.composition = SimpleNamespace(
        experience=hub.composition.experience,
        continuity_providers=(
            *hub.composition.continuity_providers,
            SimpleNamespace(provider=_Provider(design)),
        ),
    )
    view = build_continuity_surface_view(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    rendered = view.render(RenderConstraints(width=120, max_height=14))
    toolbar = strip_control_sequences(rendered.lines[2].text)

    assert toolbar.startswith("Type to search")
    assert "Domain: [All] Coding Design" in toolbar
    assert toolbar.rstrip().endswith("Sort: [Updated] Created")
    assert "Cwd" not in toolbar


def test_common_resume_loads_next_page_without_wrapping_to_first_item() -> None:
    class _PagedHub(_Hub):
        def __init__(self) -> None:
            super().__init__()
            self.release_second_page = asyncio.Event()
            self.summaries = tuple(
                replace(
                    self.summary,
                    target=ContinuityTarget(
                        provider_id="coding.sessions",
                        opaque_id=f"session-{index + 1}",
                        revision="1",
                    ),
                    title=f"Session {index + 1}",
                )
                for index in range(100)
            )

        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            if request.cursor is None:
                items = self.summaries[:50]
                next_cursor = "cursor-50"
            elif request.cursor == "cursor-50":
                await self.release_second_page.wait()
                items = self.summaries[50:75]
                next_cursor = "cursor-75"
            else:
                items = self.summaries[75:100]
                next_cursor = None
            return ContinuityPage(
                items=items,
                next_cursor=next_cursor,
                provider_diagnostics=(),
                partial=False,
                ordering_complete=True,
                provider_states={
                    "coding.sessions": ProviderPageState(
                        index_state="fresh",
                        index_generation="generation-1",
                        query_snapshot="snapshot-1",
                    )
                },
                aggregate_index_state="fresh",
            )

    async def scenario() -> None:
        hub = _PagedHub()
        surface = ContinuitySurface(
            hub=hub,  # type: ignore[arg-type]
            request_render=lambda _kind: None,
        )
        await surface.start()
        surface.render(RenderConstraints(width=80, max_height=24))

        surface._selection.selected_index = 49
        assert surface.selected_target == hub.summaries[49].target

        result = surface.handle_input(InputEvent(kind="key", key="down"))
        assert result == InputIntent(
            kind="consumed",
            note="continuity_load_page",
        )
        assert surface.selected_target == hub.summaries[49].target
        loading = surface.render(RenderConstraints(width=80, max_height=24))
        loading_lines = [strip_control_sequences(line.text) for line in loading.lines]
        assert "  (50/50)" in loading_lines
        assert "  (1/50)" not in loading_lines

        hub.release_second_page.set()
        assert surface._query_task is not None
        await surface._query_task

        assert surface.selected_target == hub.summaries[50].target
        second_page = surface.render(RenderConstraints(width=80, max_height=24))
        assert "  (51/75)" in [
            strip_control_sequences(line.text) for line in second_page.lines
        ]

        surface._selection.selected_index = 74
        assert surface.selected_target == hub.summaries[74].target
        surface.handle_input(InputEvent(kind="key", key="down"))
        assert surface._query_task is not None
        await surface._query_task

        assert surface.selected_target == hub.summaries[75].target
        final_page = surface.render(RenderConstraints(width=80, max_height=24))
        assert "  (76/100)" in [
            strip_control_sequences(line.text) for line in final_page.lines
        ]

        surface._selection.selected_index = 99
        surface.handle_input(InputEvent(kind="key", key="down"))
        assert surface.selected_target == hub.summaries[99].target
        assert len(hub.queries) == 3
        surface.close()

    asyncio.run(scenario())


def test_common_resume_page_down_crosses_page_boundary_without_wrapping() -> None:
    class _PagedHub(_Hub):
        def __init__(self) -> None:
            super().__init__()
            self.summaries = tuple(
                replace(
                    self.summary,
                    target=ContinuityTarget(
                        provider_id="coding.sessions",
                        opaque_id=f"session-{index + 1}",
                        revision="1",
                    ),
                    title=f"Session {index + 1}",
                )
                for index in range(75)
            )

        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            items = (
                self.summaries[:50] if request.cursor is None else self.summaries[50:]
            )
            return ContinuityPage(
                items=items,
                next_cursor="cursor-50" if request.cursor is None else None,
                provider_diagnostics=(),
                partial=False,
                ordering_complete=True,
                provider_states={},
                aggregate_index_state="fresh",
            )

    async def scenario() -> None:
        hub = _PagedHub()
        surface = ContinuitySurface(
            hub=hub,  # type: ignore[arg-type]
            request_render=lambda _kind: None,
        )
        await surface.start()
        surface.render(RenderConstraints(width=80, max_height=24))
        surface._selection.selected_index = 40

        surface.handle_input(InputEvent(kind="key", key="pageDown"))
        assert surface.selected_target == hub.summaries[40].target
        assert surface._query_task is not None
        await surface._query_task

        assert surface.selected_target == hub.summaries[60].target
        assert len(hub.queries) == 2
        surface.close()

    asyncio.run(scenario())


def test_common_resume_aligns_metadata_and_expands_titles_on_wide_screens(
    monkeypatch,
) -> None:
    from loushang.harnesstui.continuity import surface as surface_module

    class _ColumnHub(_Hub):
        def __init__(self) -> None:
            super().__init__()
            self.summary = replace(
                self.summary,
                title="A" * 60,
                updated_at="53m ago",
                status="ready",
            )
            self.second = replace(
                self.summary,
                target=ContinuityTarget(
                    provider_id="coding.sessions",
                    opaque_id="session-2",
                    revision="1",
                ),
                domain_ids=("presentation-design",),
                primary_domain_id="presentation-design",
                title="分析一下如何实现自演化",
                updated_at="1h ago",
            )

        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            return ContinuityPage(
                items=(self.summary, self.second),
                next_cursor=None,
                provider_diagnostics=(),
                partial=False,
                ordering_complete=True,
                provider_states={
                    "coding.sessions": ProviderPageState(
                        index_state="fresh",
                        index_generation="generation-1",
                        query_snapshot="snapshot-1",
                    )
                },
                aggregate_index_state="fresh",
            )

    monkeypatch.setattr(surface_module, "_relative_time", lambda value: value)
    hub = _ColumnHub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )
    asyncio.run(surface.start())

    narrow = surface.render(RenderConstraints(width=80, max_height=12))
    wide = surface.render(RenderConstraints(width=120, max_height=12))
    narrow_rows = [
        strip_control_sequences(line.text)
        for line in narrow.lines
        if " · " in strip_control_sequences(line.text)
    ]
    wide_rows = [
        strip_control_sequences(line.text)
        for line in wide.lines
        if " · " in strip_control_sequences(line.text)
    ]

    assert len(wide_rows) == 2
    assert [visible_width(row.split("·", 1)[0]) for row in wide_rows] == [76, 76]
    assert [visible_width(row.rsplit("·", 1)[0]) for row in wide_rows] == [98, 98]
    assert "A" * 60 not in narrow_rows[0]
    assert "A" * 60 in wide_rows[0]
    assert all(visible_width(line.text) <= 80 for line in narrow.lines)
    assert all(visible_width(line.text) <= 120 for line in wide.lines)
    surface.close()


def test_common_resume_surface_searches_provider_and_routes_typed_target() -> None:
    hub = _Hub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    async def scenario() -> None:
        await surface.start()
        surface.handle_input(InputEvent(kind="text", text="parser"))
        assert surface.selected_target == hub.summary.target
        await asyncio.sleep(0.2)

        assert hub.queries[-1].text == "parser"
        assert surface.selected_target == hub.summary.target
        view = build_continuity_surface_view(
            hub=hub,  # type: ignore[arg-type]
            request_render=lambda _kind: None,
        )
        view.content = surface
        event = normalize_surface_intent(
            InputIntent(kind="select", text="opaque-render-value"),
            view,
        )
        assert event is not None
        assert event.payload == hub.summary.target
        surface.close()

    asyncio.run(scenario())


def test_common_resume_surface_shows_activation_progress_and_inline_failure() -> None:
    hub = _Hub()
    renders: list[str] = []
    view = build_continuity_surface_view(
        hub=hub,  # type: ignore[arg-type]
        request_render=renders.append,
    )
    surface = view.content

    async def scenario() -> None:
        await surface.start()

        assert surface.begin_activation() is True
        assert surface.begin_activation() is False
        assert surface.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
            kind="consumed",
            note="continuity_activating",
        )
        activating = view.render(RenderConstraints(width=80, max_height=12))
        assert (
            sum("Resuming selected item" in line.text for line in activating.lines) == 1
        )
        assert surface.footer_help == ""

        surface.fail_activation(RuntimeError("restore failed"))
        failed = view.render(RenderConstraints(width=80, max_height=12))
        assert any("Error: restore failed" in line.text for line in failed.lines)
        assert surface.begin_activation() is True
        surface.close()

    asyncio.run(scenario())
    assert renders


def test_common_resume_surface_uses_resolved_keybinding_actions() -> None:
    hub = _Hub()
    view = build_continuity_surface_view(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
        keybindings={"tui.continuity.preview": "ctrl+p"},
    )
    surface = view.content

    async def scenario() -> None:
        await surface.start()
        intent = surface.handle_input(InputEvent(kind="key", key="ctrl+p"))
        assert intent == InputIntent(kind="consumed", note="continuity_preview")
        assert "Ctrl+P preview" in view.footer
        surface.close()

    asyncio.run(scenario())


def test_common_resume_preview_uses_only_structured_portable_sections() -> None:
    hub = _Hub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    async def scenario() -> None:
        await surface.start()
        intent = surface.handle_input(InputEvent(kind="key", key="space"))
        assert intent == InputIntent(kind="consumed", note="continuity_preview")
        await asyncio.sleep(0)
        rendered = surface.render(RenderConstraints(width=80, max_height=15))

        assert hub.previewed == [hub.summary.target]
        assert any("Messages: 4" in line.text for line in rendered.lines)
        surface.close()

    asyncio.run(scenario())


def test_common_resume_cancels_preview_when_selection_moves_quickly() -> None:
    class _PreviewHub(_Hub):
        def __init__(self) -> None:
            super().__init__()
            self.second = replace(
                self.summary,
                target=ContinuityTarget(
                    provider_id="coding.sessions",
                    opaque_id="session-2",
                    revision="1",
                ),
                title="Review the renderer",
            )
            self.cancelled: list[str] = []
            self.completed: list[str] = []

        async def query(self, request: ContinuityQuery) -> ContinuityPage:
            self.queries.append(request)
            return ContinuityPage(
                items=(self.summary, self.second),
                next_cursor=None,
                provider_diagnostics=(),
                partial=False,
                ordering_complete=True,
                provider_states={
                    "coding.sessions": ProviderPageState(
                        index_state="fresh",
                        index_generation="generation-1",
                        query_snapshot="snapshot-1",
                    )
                },
                aggregate_index_state="fresh",
            )

        async def preview(self, target: ContinuityTarget) -> ContinuityPreview:
            try:
                if target == self.summary.target:
                    await asyncio.sleep(1)
                self.completed.append(target.opaque_id)
            except asyncio.CancelledError:
                self.cancelled.append(target.opaque_id)
                raise
            return await super().preview(target)

    hub = _PreviewHub()
    surface = ContinuitySurface(
        hub=hub,  # type: ignore[arg-type]
        request_render=lambda _kind: None,
    )

    async def scenario() -> None:
        await surface.start()
        surface.handle_input(InputEvent(kind="key", key="space"))
        await asyncio.sleep(0)
        surface.handle_input(InputEvent(kind="key", key="down"))
        await asyncio.sleep(0)

        assert hub.cancelled == ["session-1"]
        assert hub.completed == ["session-2"]
        surface.close()

    asyncio.run(scenario())


def test_standalone_picker_keeps_page_open_after_activation_failure(
    monkeypatch,
) -> None:
    from loushang.harnesstui.continuity import runner as runner_module

    hub = _Hub()
    rendered_after_failure: list[str] = []

    class _Runner:
        def __init__(self, tui, **_kwargs) -> None:
            self.tui = tui

        async def run(self, on_input, *, on_start) -> int:
            context = SimpleNamespace(
                tui=self.tui,
                request_render=lambda _kind: None,
                stop=lambda exit_code=0: TuiInputResult(exit_code=exit_code),
            )
            on_start(context)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

            failed = await on_input(InputEvent(kind="key", key="enter"), context)
            assert failed.exit_code is None
            view = self.tui.surface_host.entries[0].surface.renderable
            rendered_after_failure.extend(
                line.text
                for line in view.render(
                    RenderConstraints(width=80, max_height=14)
                ).lines
            )

            closed = await on_input(InputEvent(kind="key", key="escape"), context)
            assert closed.exit_code == 0
            return 0

    async def fail_activation(_target: ContinuityTarget) -> object:
        raise RuntimeError("candidate validation failed")

    monkeypatch.setattr(runner_module, "TuiRunner", _Runner)
    selection = asyncio.run(
        run_continuity_picker(
            hub=hub,  # type: ignore[arg-type]
            activate=fail_activation,
            stdin=SimpleNamespace(),  # type: ignore[arg-type]
            stdout=SimpleNamespace(),  # type: ignore[arg-type]
        )
    )

    assert selection is None
    assert any("candidate validation failed" in line for line in rendered_after_failure)
