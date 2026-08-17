"""Product-neutral `/agents` projection of a live technical agent tree."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from loushang.harness.multiagent import (
    AgentFact,
    AgentRecord,
)
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
)
from loushang.tui.cell_width import wrap_cells
from loushang.tui.theme import ThemeResolver, apply_theme_style

from .projection import AgentTreeProjection, AgentTreeRow

AgentFactSubscriber = Callable[
    [Callable[[AgentFact], None]],
    Callable[[], None],
]

AGENT_TREE_PAGE_THEME = ThemeResolver(
    defaults={
        "surface.title": {"bold": True, "color": "yellow"},
        "surface.subtitle": {"color": "bright_black"},
        "surface.footer": {"color": "bright_black", "dim": True},
        "agent_tree.running": {"color": "yellow"},
        "agent_tree.idle": {"color": "cyan"},
        "agent_tree.completed": {"color": "green"},
        "agent_tree.failed": {"color": "red"},
        "agent_tree.interrupted": {"color": "magenta"},
        "agent_tree.closed": {"color": "bright_black", "dim": True},
        "agent_tree.detail": {"color": "bright_black"},
        "agent_tree.reference": {"color": "cyan"},
    }
)


@dataclass(slots=True)
class AgentTreeSurface:
    """Project ordered facts without owning agent control or execution."""

    records: Iterable[AgentRecord]
    subscribe_facts: AgentFactSubscriber
    request_render: Callable[[], object]
    theme: ThemeResolver = field(default_factory=lambda: AGENT_TREE_PAGE_THEME)
    _projection: AgentTreeProjection = field(
        init=False,
        repr=False,
    )
    _unsubscribe: Callable[[], None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _scroll_offset: int = field(default=0, init=False, repr=False)
    _last_body_height: int = field(default=1, init=False, repr=False)
    _last_line_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self._projection = AgentTreeProjection(tuple(self.records))

    def start(self) -> None:
        if self._unsubscribe is None:
            self._unsubscribe = self.subscribe_facts(self._accept_fact)

    def close(self) -> None:
        unsubscribe = self._unsubscribe
        self._unsubscribe = None
        if unsubscribe is not None:
            unsubscribe()

    @property
    def footer_help(self) -> str:
        if self._max_scroll_offset() > 0:
            return "Up/Down/Page scroll · Esc close"
        return "Esc close"

    def handle_input(self, event: InputEvent) -> InputIntent | None:
        if event.kind != "key":
            return None
        if event.key in {"escape", "esc", "enter"}:
            return InputIntent(kind="surface_close")
        page = max(1, self._last_body_height)
        deltas = {
            "down": 1,
            "up": -1,
            "pageDown": page,
            "pageUp": -page,
        }
        if event.key in deltas:
            return self._scroll(deltas[event.key])
        if event.key == "home":
            return self._set_scroll(0)
        if event.key == "end":
            return self._set_scroll(self._max_scroll_offset())
        return None

    def render(self, constraints: RenderConstraints) -> RenderResult:
        lines = self._render_lines(constraints.width)
        self._last_body_height = constraints.max_height
        self._last_line_count = len(lines)
        self._scroll_offset = min(self._scroll_offset, self._max_scroll_offset())
        visible = lines[
            self._scroll_offset : self._scroll_offset + constraints.max_height
        ]
        return RenderResult.from_lines(
            [RenderLine(line) for line in visible],
            constraints=constraints,
        )

    def _accept_fact(self, fact: AgentFact) -> None:
        self._projection.apply(fact)
        self.request_render()

    def _render_lines(self, width: int) -> list[str]:
        rows = self._projection.rows()
        if not rows:
            return ["No agents have been started in this session."]
        open_count = sum(row.status != "closed" for row in rows)
        running_count = sum(row.status == "running" for row in rows)
        lines = [
            apply_theme_style(
                f"{open_count} open · {running_count} running · {len(rows)} shown",
                self.theme.resolve("agent_tree.detail"),
            ),
            "",
        ]
        for row in rows:
            lines.extend(self._render_row(row, width))
        return lines

    def _render_row(self, row: AgentTreeRow, width: int) -> list[str]:
        depth = row.ref.path.depth
        prefix = "  " * depth + ("└─ " if depth else "")
        marker = _status_marker(row.status)
        heading = (
            f"{prefix}{marker} {row.ref.path.name}  "
            f"{row.status} · {row.agent_type} · round {row.round_id}"
        )
        lines = [
            apply_theme_style(
                heading,
                self.theme.resolve(f"agent_tree.{row.status}"),
            )
        ]
        detail_prefix = "  " * depth + "   "
        details = _row_details(row)
        for detail, token in details:
            wrapped = wrap_cells(
                f"{detail_prefix}{detail}",
                width=max(1, width),
            ) or [""]
            lines.extend(
                apply_theme_style(line, self.theme.resolve(token)) for line in wrapped
            )
        return lines

    def _scroll(self, delta: int) -> InputIntent | None:
        return self._set_scroll(self._scroll_offset + delta)

    def _set_scroll(self, offset: int) -> InputIntent | None:
        next_offset = max(0, min(offset, self._max_scroll_offset()))
        if next_offset == self._scroll_offset:
            return None
        self._scroll_offset = next_offset
        return InputIntent(kind="consumed", note="agent_tree_scroll")

    def _max_scroll_offset(self) -> int:
        return max(0, self._last_line_count - self._last_body_height)


def _status_marker(status: str) -> str:
    return {
        "running": "●",
        "idle": "○",
        "completed": "✓",
        "failed": "×",
        "interrupted": "!",
        "closed": "·",
    }.get(status, "•")


def _row_details(row: AgentTreeRow) -> list[tuple[str, str]]:
    details: list[tuple[str, str]] = []
    progress = row.progress
    if progress.recent_activity:
        details.append((progress.recent_activity, "agent_tree.detail"))
    if progress.summary:
        details.append((progress.summary, "agent_tree.detail"))
    usage = progress.usage
    if usage.latest_input_tokens or usage.cumulative_output_tokens:
        details.append(
            (
                f"tokens {usage.latest_input_tokens} in · "
                f"{usage.cumulative_output_tokens} out"
                f" · {progress.tool_uses} tools",
                "agent_tree.detail",
            )
        )
    if row.workspace_ref:
        details.append((f"workspace {row.workspace_ref}", "agent_tree.reference"))
    if row.change_set_ref:
        details.append((f"changes {row.change_set_ref}", "agent_tree.reference"))
    if row.artifact_refs:
        details.append(
            (f"artifacts {', '.join(row.artifact_refs)}", "agent_tree.reference")
        )
    return details


def build_agent_tree_surface_view(
    *,
    records: Iterable[AgentRecord],
    subscribe_facts: AgentFactSubscriber,
    request_render: Callable[[], object],
) -> ScreenSurfaceView:
    """Build the shared cross-Product live full-screen Agent Tree page."""

    return ScreenSurfaceView(
        title="Agents",
        subtitle="Live session collaboration",
        purpose="agent_tree",
        content=AgentTreeSurface(
            records=records,
            subscribe_facts=subscribe_facts,
            request_render=request_render,
        ),
        footer="",
        presentation="page",
        theme=AGENT_TREE_PAGE_THEME,
    )


__all__ = [
    "AGENT_TREE_PAGE_THEME",
    "AgentFactSubscriber",
    "AgentTreeSurface",
    "build_agent_tree_surface_view",
]
