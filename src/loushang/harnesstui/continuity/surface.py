"""Product-neutral full-screen continuity discovery surface."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

from loushang.harness.continuity import (
    ContinuityPage,
    ContinuityPreview,
    ContinuityQuery,
    ContinuitySummary,
    ContinuityTarget,
    StableContinuityReference,
)
from loushang.harnesstui.continuity.keybindings import (
    CONTINUITY_DOMAIN_ACTION,
    CONTINUITY_PREVIEW_ACTION,
    CONTINUITY_SORT_ACTION,
    continuity_keybinding_manager,
)
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    CursorDeclaration,
    InputEvent,
    InputIntent,
    KeybindingConfig,
    KeybindingManager,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SelectionSurface,
    SelectItem,
)
from loushang.tui.cell_width import (
    autowrap_safe_width,
    truncate_to_width,
    visible_width,
    wrap_cells,
)
from loushang.tui.theme import ThemeResolver, apply_theme_style

_SEARCH_DEBOUNCE_SECONDS = 0.15
_ACTIVATION_TICK_SECONDS = 0.5
_INDEX_REQUERY_SECONDS = 0.5
_TARGET_SEPARATOR = "\x1f"
_MIN_TIME_COLUMN_WIDTH = 8
_MAX_TIME_COLUMN_WIDTH = 12
_MAX_CONTEXT_COLUMN_WIDTH = 24
_MIN_PRIMARY_COLUMN_WIDTH = 32
_MAX_PRIMARY_COLUMN_WIDTH = 72
_PRIMARY_COLUMN_RATIO = 0.55
ContinuitySort = Literal["updated", "created"]
_PageSelectionTarget = int | Literal["last"]
_PendingPageSelection = tuple[ContinuityTarget, _PageSelectionTarget]

CONTINUITY_PAGE_THEME = ThemeResolver(
    defaults={
        "surface.title": {"bold": True, "color": "cyan"},
        "surface.footer": {"color": "bright_black", "dim": True},
        "selection.selected": {"bold": True, "color": "cyan"},
        "continuity.toolbar.label": {"color": "bright_black", "dim": True},
        "continuity.toolbar.active": {"bold": True, "color": "cyan"},
        "continuity.toolbar.inactive": {"color": "bright_black", "dim": True},
        "continuity.state": {
            "color": "bright_black",
            "dim": True,
            "italic": True,
        },
        "continuity.error": {"color": "red"},
        "continuity.warning": {"color": "yellow"},
        "continuity.activating": {"color": "yellow", "bold": True},
    }
)


class ContinuitySurface:
    """Own common search, paging, preview, and responsive list state."""

    def __init__(
        self,
        *,
        reference: StableContinuityReference,
        request_render: Callable[[str], None],
        page_size: int = 25,
        keybindings: KeybindingManager | KeybindingConfig | None = None,
        theme: ThemeResolver | None = None,
        include_summary: Callable[[ContinuitySummary], bool] | None = None,
        selection_action: str = "resume",
    ) -> None:
        self._reference = reference
        self._request_render = request_render
        self._theme = theme if theme is not None else CONTINUITY_PAGE_THEME
        self._include_summary = include_summary or (lambda _summary: True)
        self._selection_action = selection_action
        self._keybindings = continuity_keybinding_manager(keybindings)
        self._query = ContinuityQuery(page_size=page_size)
        self._summaries: list[ContinuitySummary] = []
        self._targets: dict[str, ContinuityTarget] = {}
        self._loading = True
        self._page: ContinuityPage | None = None
        self._preview: ContinuityPreview | None = None
        self._preview_target: ContinuityTarget | None = None
        self._preview_visible = False
        self._error: str | None = None
        self._notice: str | None = None
        self._activating = False
        self._activating_title: str | None = None
        self._activation_started: float | None = None
        self._activation_tick_task: asyncio.Task[None] | None = None
        self._generation = 0
        self._query_task: asyncio.Task[None] | None = None
        self._preview_task: asyncio.Task[None] | None = None
        self._index_requery_task: asyncio.Task[None] | None = None
        observation = reference.observation
        self._domain_options = (
            (None, *observation.experience.domain_ids)
            if len(observation.providers) > 1
            else (None,)
        )
        self._domain_index = 0
        self._selection = self._build_selection()

    @property
    def selected_target(self) -> ContinuityTarget | None:
        selected = self._selection.selected_item()
        if selected is None:
            return None
        return self._targets.get(selected.selected_value)

    @property
    def selected_summary(self) -> ContinuitySummary | None:
        target = self.selected_target
        if target is None:
            return None
        return next(
            (summary for summary in self._summaries if summary.target == target),
            None,
        )

    @property
    def query(self) -> ContinuityQuery:
        return self._query

    @property
    def loading(self) -> bool:
        return self._loading

    async def start(self) -> None:
        await self._load(reset=True)

    def begin_activation(self) -> bool:
        """Mark the selected target as activating and reject duplicate submits."""

        if self._activating or self.selected_target is None:
            return False
        self._activating = True
        self._error = None
        self._notice = None
        summary = self.selected_summary
        self._activating_title = summary.title if summary is not None else None
        self._activation_started = time.monotonic()
        self._cancel_activation_tick()
        self._activation_tick_task = asyncio.create_task(self._activation_ticker())
        self._request_render("product")
        return True

    async def _activation_ticker(self) -> None:
        while self._activating:
            await asyncio.sleep(_ACTIVATION_TICK_SECONDS)
            if self._activating:
                self._request_render("product")

    def _cancel_activation_tick(self) -> None:
        task = self._activation_tick_task
        self._activation_tick_task = None
        if task is not None and not task.done():
            task.cancel()

    def cancel_activation(self) -> bool:
        """Reset an in-flight activation after the host cancelled it."""

        if not self._activating:
            return False
        self._activating = False
        self._activating_title = None
        self._activation_started = None
        self._cancel_activation_tick()
        self._error = None
        action = (
            "Resume"
            if self._selection_action == "resume"
            else self._selection_action.capitalize()
        )
        self._notice = f"{action} cancelled."
        self._request_render("product")
        return True

    def fail_activation(self, error: BaseException) -> None:
        self._activating = False
        self._activating_title = None
        self._activation_started = None
        self._cancel_activation_tick()
        self._notice = None
        self.report_error(error)

    def report_error(self, error: BaseException) -> None:
        self._error = str(error).strip() or error.__class__.__name__
        self._loading = False
        self._request_render("product")

    def close(self) -> None:
        self._cancel_activation_tick()
        for task in (
            self._query_task,
            self._preview_task,
            self._index_requery_task,
        ):
            if task is not None and not task.done():
                task.cancel()

    def handle_input(self, event: InputEvent) -> InputIntent[str] | bool | None:
        if self._activating:
            event = self._resolve_keybinding(event)
            if event.kind == "key" and event.key == "escape":
                # "consumed" (not "dialog_cancel"): hosts must cancel the
                # in-flight activation WITHOUT closing this surface.
                return InputIntent(
                    kind="consumed",
                    note="continuity_cancel_activation",
                )
            return InputIntent(kind="consumed", note="continuity_activating")
        event = self._resolve_keybinding(event)
        if event.kind == "key" and event.key == "space":
            self._preview_visible = not self._preview_visible
            if self._preview_visible:
                self._schedule_preview()
            self._request_render("product")
            return InputIntent(kind="consumed", note="continuity_preview")
        if event.kind == "key" and event.key == "tab":
            self._cycle_domain()
            return InputIntent(kind="consumed", note="continuity_domain")
        if event.kind == "key" and event.key in {"ctrl+s", "ctrl_s"}:
            self._toggle_sort()
            return InputIntent(kind="consumed", note="continuity_sort")

        before_filter = self._selection.filter_text
        before_target = self.selected_target
        page_selection = self._page_selection_for(event)
        if page_selection is not None:
            if not self._loading:
                self._schedule_query(
                    reset=False,
                    page_selection=page_selection,
                )
            return InputIntent(kind="consumed", note="continuity_load_page")
        result = self._selection.handle_input(event)
        if self._selection.filter_text != before_filter:
            self._query = replace(
                self._query,
                text=self._selection.filter_text,
                cursor=None,
            )
            self._schedule_query(reset=True)
        if self.selected_target != before_target and self._preview_visible:
            self._schedule_preview()
        return result

    @property
    def footer_help(self) -> str:
        if self._activating:
            return f"{self._key_label('tui.select.cancel')} cancel"
        hints = [
            f"{self._key_label('tui.select.confirm')} {self._selection_action}",
            f"{self._key_label('tui.select.cancel')} exit",
        ]
        if len(self._domain_options) > 1:
            hints.append(f"{self._key_label(CONTINUITY_DOMAIN_ACTION)} domain")
        if len(self._sort_options()) > 1:
            hints.append(f"{self._key_label(CONTINUITY_SORT_ACTION)} sort")
        hints.extend(
            (
                f"{self._key_label(CONTINUITY_PREVIEW_ACTION)} preview",
                f"{self._key_label('tui.select.up')}/"
                f"{self._key_label('tui.select.down')} browse",
            )
        )
        status = self._footer_status()
        return " · ".join((*((status,) if status else ()), *hints))

    def render(self, constraints: RenderConstraints) -> RenderResult:
        width = constraints.width
        lines: list[RenderLine] = []
        preview_lines = self._preview_lines(
            width=width,
            max_height=max(0, constraints.max_height // 3),
        )
        state_lines = self._state_lines(width=width)
        selection_height = max(
            1,
            constraints.max_height - len(lines) - len(state_lines) - len(preview_lines),
        )
        self._selection.max_visible = min(20, max(1, selection_height))
        self._selection.primary_column_width = _responsive_primary_column_width(width)
        selection = self._selection.render(
            RenderConstraints(
                width=width,
                max_height=selection_height,
                visible_height=constraints.visible_height,
            )
        )
        cursor = (
            CursorDeclaration(
                row=len(lines) + selection.cursor.row,
                column=selection.cursor.column,
            )
            if selection.cursor is not None
            else None
        )
        lines.extend(selection.lines)
        lines.extend(state_lines)
        lines.extend(preview_lines)
        return RenderResult.from_lines(
            lines[: constraints.max_height],
            constraints=constraints,
            cursor=cursor,
        )

    async def _load(
        self,
        *,
        reset: bool,
        background: bool = False,
        page_selection: _PendingPageSelection | None = None,
    ) -> None:
        self._generation += 1
        generation = self._generation
        if not background:
            self._loading = True
            self._error = None
        if reset:
            request = replace(self._query, cursor=None)
        else:
            next_cursor = self._page.next_cursor if self._page is not None else None
            if next_cursor is None:
                if not background:
                    self._loading = False
                return
            request = replace(self._query, cursor=next_cursor)
        if not background:
            self._request_render("product")
        try:
            page = await self._reference.query(request)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if generation == self._generation:
                self._error = str(exc) or type(exc).__name__
                if not background:
                    self._loading = False
                self._request_render("product")
            return
        if generation != self._generation:
            return
        if page.restart_required and not reset:
            self._query = replace(self._query, cursor=None)
            await self._load(reset=True)
            return
        selected = self.selected_target
        previous_page = self._page
        previous_summaries = tuple(self._summaries)
        if reset:
            self._summaries = [
                item for item in page.items if self._include_summary(item)
            ]
        else:
            existing = {
                (item.target.provider_id, item.target.opaque_id)
                for item in self._summaries
            }
            self._summaries.extend(
                item
                for item in page.items
                if self._include_summary(item)
                if (item.target.provider_id, item.target.opaque_id) not in existing
            )
        self._page = page
        if not background:
            self._loading = False
        self._rebuild_selection(selected=selected)
        if (
            not reset
            and page_selection is not None
            and selected == page_selection[0]
            and self._summaries
        ):
            target_index = page_selection[1]
            self._selection.selected_index = (
                len(self._summaries) - 1
                if target_index == "last"
                else min(target_index, len(self._summaries) - 1)
            )
        if self._preview_visible and self.selected_target != selected:
            self._schedule_preview()
        if (
            not background
            or page != previous_page
            or tuple(self._summaries) != previous_summaries
        ):
            self._request_render("product")
        self._ensure_index_requery()

    def _schedule_query(
        self,
        *,
        reset: bool,
        page_selection: _PendingPageSelection | None = None,
    ) -> None:
        if self._query_task is not None and not self._query_task.done():
            self._query_task.cancel()
        self._loading = True
        self._request_render("product")

        async def run() -> None:
            if reset:
                await asyncio.sleep(_SEARCH_DEBOUNCE_SECONDS)
            await self._load(
                reset=reset,
                page_selection=page_selection,
            )

        self._query_task = asyncio.create_task(run())

    def _page_selection_for(
        self,
        event: InputEvent,
    ) -> _PendingPageSelection | None:
        if (
            event.kind != "key"
            or event.key not in {"down", "pageDown", "end"}
            or not self._summaries
            or self._page is None
            or self._page.next_cursor is None
        ):
            return None
        selected = self.selected_target
        if selected is None:
            return None
        current_index = self._selection.selected_index
        last_index = len(self._summaries) - 1
        if event.key == "down" and current_index >= last_index:
            return selected, current_index + 1
        if event.key == "pageDown":
            target_index = current_index + max(1, self._selection.max_visible)
            if target_index > last_index:
                return selected, target_index
        if event.key == "end" and current_index >= last_index:
            return selected, "last"
        return None

    def _schedule_preview(self) -> None:
        target = self.selected_target
        self._preview_target = target
        self._preview = None
        if self._preview_task is not None and not self._preview_task.done():
            self._preview_task.cancel()
        if target is None:
            return

        async def load() -> None:
            try:
                preview = await self._reference.preview(target)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._preview_target == target:
                    self._error = str(exc) or type(exc).__name__
                    self._request_render("product")
                return
            if self._preview_target == target:
                self._preview = preview
                self._request_render("product")

        self._preview_task = asyncio.create_task(load())

    def _ensure_index_requery(self) -> None:
        page = self._page
        if page is None or page.aggregate_index_state not in {"rebuilding", "stale"}:
            return
        task = self._index_requery_task
        if task is not None and not task.done():
            return

        async def requery() -> None:
            while True:
                await asyncio.sleep(_INDEX_REQUERY_SECONDS)
                if self._loading:
                    continue
                await self._load(reset=True, background=True)
                current = self._page
                if current is None or current.aggregate_index_state not in {
                    "rebuilding",
                    "stale",
                }:
                    return

        self._index_requery_task = asyncio.create_task(requery())

    def _cycle_domain(self) -> None:
        if len(self._domain_options) == 1:
            return
        self._domain_index = (self._domain_index + 1) % len(self._domain_options)
        domain = self._domain_options[self._domain_index]
        self._query = replace(
            self._query,
            domain_ids=() if domain is None else (domain,),
            cursor=None,
        )
        self._rebuild_selection(selected=self.selected_target)
        self._schedule_query(reset=True)

    def _toggle_sort(self) -> None:
        sort_options = self._sort_options()
        if len(sort_options) < 2:
            return
        current_index = sort_options.index(self._query.sort_id)
        self._query = replace(
            self._query,
            sort_id=sort_options[(current_index + 1) % len(sort_options)],
            cursor=None,
        )
        self._rebuild_selection(selected=self.selected_target)
        self._schedule_query(reset=True)

    def _rebuild_selection(
        self,
        *,
        selected: ContinuityTarget | None,
    ) -> None:
        self._selection = self._build_selection()
        if self._query.text:
            self._selection.set_filter(self._query.text)
        if selected is None:
            return
        selected_key = _target_key(selected)
        for index, item in enumerate(self._selection._filtered_items):
            if item.selected_value == selected_key:
                self._selection.selected_index = index
                break

    def _build_selection(self) -> SelectionSurface:
        self._targets = {
            _target_key(summary.target): summary.target for summary in self._summaries
        }
        multiple_providers = (
            len({summary.target.provider_id for summary in self._summaries}) > 1
        )
        descriptions = _summary_descriptions(
            self._summaries,
            show_provider=multiple_providers,
        )
        index_pending = self._page is not None and self._page.aggregate_index_state in {
            "rebuilding",
            "stale",
        }
        empty_text = (
            "Searching…"
            if self._loading and self._query.text
            else (
                "Loading sessions…"
                if self._loading or index_pending
                else (
                    "No results for your search"
                    if self._query.text
                    else "No sessions yet"
                )
            )
        )
        return SelectionSurface(
            items=[
                SelectItem(
                    label=summary.title,
                    value=_target_key(summary.target),
                    description=description,
                )
                for summary, description in zip(
                    self._summaries,
                    descriptions,
                    strict=True,
                )
            ],
            max_visible=20,
            empty_text=self._styled(empty_text, "continuity.state"),
            wrap_navigation=False,
            enable_search=True,
            search_prompt="Search: ",
            search_placeholder=self._styled(
                "Type to search",
                "continuity.state",
            ),
            search_toolbar=self._toolbar_copy(compact=False),
            search_toolbar_compact=self._toolbar_copy(compact=True),
            search_min_input_width=20,
            search_gap_lines=1,
            filter_mode="remote",
            preserve_description_spacing=True,
            theme=self._theme,
        )

    def _toolbar_copy(self, *, compact: bool) -> str:
        controls: list[str] = []
        if len(self._domain_options) > 1:
            controls.append(
                self._toolbar_control(
                    "Domain",
                    tuple(
                        ("All" if domain is None else _display_option_label(domain))
                        for domain in self._domain_options
                    ),
                    active_index=self._domain_index,
                    compact=compact,
                )
            )
        sort_options = self._sort_options()
        if len(sort_options) > 1:
            controls.append(
                self._toolbar_control(
                    "Sort",
                    tuple(_display_option_label(option) for option in sort_options),
                    active_index=sort_options.index(self._query.sort_id),
                    compact=compact,
                )
            )
        return self._styled("   ", "continuity.toolbar.label").join(controls)

    def _toolbar_control(
        self,
        label: str,
        options: tuple[str, ...],
        *,
        active_index: int,
        compact: bool,
    ) -> str:
        label_copy = self._styled(
            f"{label}:{'' if compact else ' '}",
            "continuity.toolbar.label",
        )
        active = self._styled(
            f"[{options[active_index]}]",
            "continuity.toolbar.active",
        )
        if compact:
            return f"{label_copy}{active}"
        values = [
            (
                active
                if index == active_index
                else self._styled(
                    option,
                    "continuity.toolbar.inactive",
                )
            )
            for index, option in enumerate(options)
        ]
        return f"{label_copy}{' '.join(values)}"

    def _sort_options(self) -> tuple[ContinuitySort, ...]:
        providers = self._reference.observation.providers
        if not providers:
            return ("updated",)
        return (
            ("updated", "created")
            if all(
                "created" in descriptor.supported_sorts
                for descriptor in providers
            )
            else ("updated",)
        )

    def _resolve_keybinding(self, event: InputEvent) -> InputEvent:
        if event.kind != "key":
            return event
        actions = (
            (CONTINUITY_PREVIEW_ACTION, "space"),
            (CONTINUITY_DOMAIN_ACTION, "tab"),
            (CONTINUITY_SORT_ACTION, "ctrl+s"),
            ("tui.select.confirm", "enter"),
            ("tui.select.cancel", "escape"),
            ("tui.select.up", "up"),
            ("tui.select.down", "down"),
            ("tui.select.pageUp", "pageUp"),
            ("tui.select.pageDown", "pageDown"),
        )
        for action, canonical in actions:
            if self._keybindings.matches(event.key, action):
                return replace(event, key=canonical)
        return event

    def _key_label(self, action: str) -> str:
        keys = self._keybindings.keys_for(action)
        return _display_key(keys[0]) if keys else "Unbound"

    def _state_lines(self, *, width: int) -> list[RenderLine]:
        if self._activating:
            action = (
                "Resuming"
                if self._selection_action == "resume"
                else (
                    f"{self._selection_action[:-1].capitalize()}ing"
                    if self._selection_action.endswith("e")
                    else f"{self._selection_action.capitalize()}ing"
                )
            )
            label = (
                f'"{self._activating_title}"'
                if self._activating_title
                else "selected item"
            )
            elapsed = ""
            if self._activation_started is not None:
                seconds = max(
                    0, int(time.monotonic() - self._activation_started)
                )
                elapsed = f" ({seconds}s)"
            return [
                RenderLine(""),
                RenderLine(
                    self._styled(
                        truncate_to_width(
                            f"{action} {label}…{elapsed}",
                            max_width=width,
                        ),
                        "continuity.activating",
                    )
                ),
            ]
        if self._error:
            return [
                RenderLine(""),
                RenderLine(
                    self._styled(
                        truncate_to_width(
                            f"Error: {self._error}",
                            max_width=width,
                        ),
                        "continuity.error",
                    )
                ),
            ]
        if self._notice:
            return [
                RenderLine(""),
                RenderLine(
                    self._styled(
                        truncate_to_width(self._notice, max_width=width),
                        "continuity.warning",
                    )
                ),
            ]
        lines: list[RenderLine] = []
        if self._page is not None and self._page.partial:
            detail = (
                self._page.provider_diagnostics[0].message
                if self._page.provider_diagnostics
                else "one or more providers are unavailable"
            )
            lines.extend(
                (
                    RenderLine(""),
                    RenderLine(
                        self._styled(
                            truncate_to_width(
                                f"Partial results: {detail}",
                                max_width=width,
                            ),
                            "continuity.warning",
                        )
                    ),
                )
            )
        return lines

    def _footer_status(self) -> str:
        if self._loading and self._summaries:
            return "Searching…" if self._query.text else "Loading older sessions…"
        if (
            self._summaries
            and self._page is not None
            and self._page.aggregate_index_state != "fresh"
        ):
            return "Refreshing session index…"
        return ""

    def _styled(self, text: str, token: str) -> str:
        return apply_theme_style(text, self._theme.resolve(token))

    def _preview_lines(self, *, width: int, max_height: int) -> list[RenderLine]:
        if not self._preview_visible or max_height < 3:
            return []
        lines = [RenderLine(""), RenderLine("Preview")]
        if self._preview is None:
            lines.append(RenderLine("Loading preview…"))
            return lines[:max_height]
        for section in self._preview.sections:
            if section.title:
                lines.append(
                    RenderLine(truncate_to_width(section.title, max_width=width))
                )
            if section.text:
                for line in wrap_cells(section.text, width=width):
                    lines.append(RenderLine(line))
            for key, value in section.rows:
                lines.append(
                    RenderLine(truncate_to_width(f"{key}: {value}", max_width=width))
                )
            for artifact in section.artifacts:
                lines.append(
                    RenderLine(
                        truncate_to_width(
                            f"{artifact.label}: {artifact.reference}",
                            max_width=width,
                        )
                    )
                )
            if len(lines) >= max_height:
                break
        return lines[:max_height]


def build_continuity_surface_view(
    *,
    reference: StableContinuityReference,
    request_render: Callable[[str], None],
    keybindings: KeybindingManager | KeybindingConfig | None = None,
    theme: ThemeResolver | None = None,
    include_summary: Callable[[ContinuitySummary], bool] | None = None,
    title: str = "Resume a previous session",
    selection_action: str = "resume",
    purpose: Literal["session", "delete"] = "session",
) -> ScreenSurfaceView:
    resolved_theme = theme if theme is not None else CONTINUITY_PAGE_THEME
    content = ContinuitySurface(
        reference=reference,
        request_render=request_render,
        keybindings=keybindings,
        theme=resolved_theme,
        include_summary=include_summary,
        selection_action=selection_action,
    )
    return ScreenSurfaceView(
        title=title,
        purpose=purpose,
        content=content,
        footer=content.footer_help,
        presentation="page",
        theme=resolved_theme,
    )


def _target_key(target: ContinuityTarget) -> str:
    return (
        f"{target.provider_id}{_TARGET_SEPARATOR}"
        f"{target.opaque_id}{_TARGET_SEPARATOR}{target.revision or ''}"
    )


def _display_option_label(value: str) -> str:
    return " ".join(
        part.capitalize() for part in value.replace("_", "-").split("-") if part
    )


def _summary_descriptions(
    summaries: list[ContinuitySummary],
    *,
    show_provider: bool,
) -> list[str]:
    rows = [
        (
            _normalize_column_value(_relative_time(summary.updated_at)),
            _normalize_column_value(
                (
                    summary.target.provider_id
                    if show_provider
                    else summary.primary_domain_id or ""
                )
            ),
            _normalize_column_value(summary.status or ""),
        )
        for summary in summaries
    ]
    if not rows:
        return []
    time_width = min(
        _MAX_TIME_COLUMN_WIDTH,
        max(
            _MIN_TIME_COLUMN_WIDTH,
            *(visible_width(time) for time, _context, _status in rows),
        ),
    )
    context_width = min(
        _MAX_CONTEXT_COLUMN_WIDTH,
        max((visible_width(context) for _time, context, _status in rows), default=0),
    )
    show_status = any(status for _time, _context, status in rows)
    descriptions: list[str] = []
    for time_text, context, status in rows:
        facts = [_right_align(time_text, time_width)]
        if context_width:
            facts.append(
                truncate_to_width(
                    context,
                    max_width=context_width,
                    pad=show_status,
                )
            )
        if status:
            facts.append(status)
        descriptions.append(" · ".join(facts))
    return descriptions


def _right_align(value: str, width: int) -> str:
    clipped = truncate_to_width(value, max_width=width)
    return (" " * max(0, width - visible_width(clipped))) + clipped


def _normalize_column_value(value: str) -> str:
    return " ".join(value.split())


def _responsive_primary_column_width(width: int) -> int:
    target_width = autowrap_safe_width(width)
    preferred = max(
        _MIN_PRIMARY_COLUMN_WIDTH,
        int(target_width * _PRIMARY_COLUMN_RATIO),
    )
    return max(1, min(_MAX_PRIMARY_COLUMN_WIDTH, preferred))


def _relative_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
    except ValueError:
        return value
    seconds = max(
        0,
        int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()),
    )
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


def _display_key(key: str) -> str:
    aliases = {
        "enter": "Enter",
        "escape": "Esc",
        "space": "Space",
        "tab": "Tab",
        "up": "↑",
        "down": "↓",
        "pageUp": "PgUp",
        "pageDown": "PgDn",
    }
    if key in aliases:
        return aliases[key]
    return "+".join(part.title() for part in key.split("+"))


__all__ = [
    "CONTINUITY_PAGE_THEME",
    "ContinuitySurface",
    "build_continuity_surface_view",
]
