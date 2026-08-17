# TUI Real Settings Page Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the real native TUI `/settings` path with a tabbed `Status / Config / Model / Usage / Stats` control-center page backed by `TabGroup` and `SearchableList`, while preserving legacy surfaces and `/model`.

**Architecture:** Add a focused product view in `src/loushang/coding/ui/settings_page.py` that composes existing generic widgets. `NativeSurfaceManager` remains the lifecycle owner; it opens the page, delegates new-page setting/model side effects to `SettingsPageView.apply_setting()`, and preserves legacy `SettingsSurface` close-on-submit behavior. `NativeSurfaceView` gets compatible input/cursor delegation so active bottom surfaces can host searchable page content correctly.

**Tech Stack:** Python 3.11 dataclasses, existing `loushang.tui` render/input primitives, `TabGroup`, `SearchableList`, `pytest`, native TUI playback harness.

---

## File Structure

- Create `src/loushang/coding/ui/settings_page.py`
  - Product-level settings/control-center page.
  - Owns page composition, adapters, `apply_setting()`, focus-aware input, and rendering.
  - Does not replace generic widgets or legacy `SettingsSurface`.
- Modify `src/loushang/coding/ui/native_surfaces.py`
  - Add `NativeSurfaceView.editor_input_target()`.
  - Preserve non-`InfoPanel` content cursors.
  - Let non-info hosted content consume Esc before host close fallback.
  - Open settings asynchronously and delegate new-page submit handling.
- Modify `src/loushang/coding/ui/status_provider.py`
  - Add a small read-only status snapshot method/dataclass instead of parsing rendered toolbar text.
- Add `tests/coding/test_native_settings_page.py`
  - Focused unit tests for `SettingsPageView`, page adapters, keyboard routing, and apply behavior.
- Modify `tests/coding/test_native_coding_tui_surfaces.py`
  - Manager/host integration tests and existing `/settings` expectations.
- Modify `tests/coding/test_native_coding_tui_playback.py`
  - Playback expectations for the real `/settings` path.
- Optional after implementation stabilizes: update durable internal docs under `docs/internals/architecture/tui/native-terminal-core/`.

---

### Task 1: Fix NativeSurfaceView Host Delegation

**Files:**
- Modify: `src/loushang/coding/ui/native_surfaces.py`
- Test: `tests/coding/test_native_coding_tui_surfaces.py`

- [ ] **Step 1: Add failing tests for host editor target, cursor offset, and Esc delegation**

Append focused tests near other `NativeSurfaceView` tests:

```python
class _CursorContent:
    def render(self, constraints: RenderConstraints) -> RenderResult:
        return RenderResult.from_lines(
            [RenderLine("query")],
            constraints=constraints,
            cursor=CursorDeclaration(row=0, column=3),
        )


class _EditorTargetContent(_CursorContent):
    def __init__(self) -> None:
        self.target = object()

    def editor_input_target(self) -> object:
        return self.target


class _EscContent(_CursorContent):
    def __init__(self) -> None:
        self.calls = 0

    def handle_input(self, event: InputEvent) -> InputIntent | bool | None:
        self.calls += 1
        if event.kind == "key" and event.key in {"esc", "escape"}:
            return InputIntent(kind="consumed", note="child_escape")
        return None


def test_native_surface_view_delegates_editor_input_target() -> None:
    content = _EditorTargetContent()
    view = NativeSurfaceView(title="Settings", purpose="settings", content=content)

    assert view.editor_input_target() is content.target


def test_native_surface_view_preserves_content_cursor_with_offset() -> None:
    view = NativeSurfaceView(title="Settings", purpose="settings", content=_CursorContent(), footer="")

    rendered = view.render(RenderConstraints(width=40, max_height=8))

    assert rendered.cursor == CursorDeclaration(row=2, column=3)


def test_native_surface_view_delegates_escape_to_non_info_content_first() -> None:
    content = _EscContent()
    view = NativeSurfaceView(title="Settings", purpose="settings", content=content)

    assert view.handle_input(InputEvent(kind="key", key="escape")) == InputIntent(
        kind="consumed",
        note="child_escape",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/coding/test_native_coding_tui_surfaces.py -q
```

Expected: new tests fail because `NativeSurfaceView` has no `editor_input_target()`, drops non-info cursors, and closes before content can consume Esc.

- [ ] **Step 3: Implement host delegation**

In `NativeSurfaceView`:

```python
def editor_input_target(self) -> object | None:
    target = getattr(self.content, "editor_input_target", None)
    return target() if callable(target) else None
```

Change `handle_input()` so info surfaces keep current behavior, but non-info surfaces delegate first:

```python
def handle_input(self, event: InputEvent) -> InputIntent | None:
    if self.purpose == "info":
        if event.kind == "key" and event.key in {"enter", "space", "escape", "esc"}:
            return InputIntent(kind="surface_close")
        if event.kind == "key":
            return self._handle_info_scroll_input(event.key)
        return None

    handler = getattr(self.content, "handle_input", None)
    if callable(handler):
        intent = _native_input_intent_or_none(handler(self._translate_content_input_event(event)))
        if intent is not None:
            return intent
    if event.kind == "key" and event.key in {"escape", "esc"}:
        return InputIntent(kind="surface_close")
    return None
```

When rendering non-info content, offset its cursor:

```python
else:
    self._last_content_start_row = len(lines)
    result = self.content.render(body_constraints)
    lines.extend(line.text for line in result.lines)
    if result.cursor is not None:
        cursor_row = self._last_content_start_row + result.cursor.row
        if cursor_row < constraints.max_height:
            cursor = CursorDeclaration(row=cursor_row, column=result.cursor.column)
```

- [ ] **Step 4: Run host tests**

Run:

```bash
uv run pytest tests/coding/test_native_coding_tui_surfaces.py -q
```

Expected: tests pass or unrelated existing tests reveal assumptions that need local updates.

- [ ] **Step 5: Commit**

```bash
git add src/loushang/coding/ui/native_surfaces.py tests/coding/test_native_coding_tui_surfaces.py
git commit -m "fix(tui): delegate native surface content input hooks"
```

---

### Task 2: Add Status Snapshot API

**Files:**
- Modify: `src/loushang/coding/ui/status_provider.py`
- Test: `tests/coding/test_native_settings_page.py`

- [ ] **Step 1: Write failing status snapshot test**

Create `tests/coding/test_native_settings_page.py` with:

```python
from loushang.coding.ui.status_provider import CodingTuiStatusProvider


def test_status_provider_exposes_read_only_snapshot() -> None:
    provider = CodingTuiStatusProvider(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label=lambda: "abcd",
        thinking_level=lambda: "medium",
        running=lambda: False,
    )

    snapshot = provider.snapshot()

    assert snapshot.model_label == "moonshot/kimi-for-coding"
    assert snapshot.cwd == "/repo"
    assert snapshot.branch == "main"
    assert snapshot.session_label == "abcd"
    assert snapshot.thinking_level == "medium"
    assert snapshot.running is False
    assert snapshot.statusline_visible is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py::test_status_provider_exposes_read_only_snapshot -q
```

Expected: fail because `snapshot()` does not exist.

- [ ] **Step 3: Implement `StatusSnapshot`**

In `src/loushang/coding/ui/status_provider.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    model_label: str | None
    cwd: str
    branch: str | None
    session_label: str | None
    thinking_level: str | None
    running: bool
    statusline_visible: bool
```

Add:

```python
def snapshot(self) -> StatusSnapshot:
    return StatusSnapshot(
        model_label=self._model_label,
        cwd=self._cwd,
        branch=self._branch,
        session_label=self._session_label(),
        thinking_level=self._thinking_level(),
        running=self._running(),
        statusline_visible=self._visible,
    )
```

Export `StatusSnapshot` in `__all__`.

- [ ] **Step 4: Run test**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py::test_status_provider_exposes_read_only_snapshot -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/loushang/coding/ui/status_provider.py tests/coding/test_native_settings_page.py
git commit -m "feat(tui): expose coding status snapshot"
```

---

### Task 3: Implement SettingsPageView Core

**Files:**
- Create: `src/loushang/coding/ui/settings_page.py`
- Test: `tests/coding/test_native_settings_page.py`

- [ ] **Step 1: Add failing page render and focus tests**

Add tests:

```python
import asyncio

from loushang.ai.model import ModelSelection
from loushang.coding.ui.settings_page import SettingsPageView
from loushang.coding.ui.status_provider import CodingTuiStatusProvider
from loushang.tui import InputEvent, InputIntent, RenderConstraints, strip_control_sequences


class _Session:
    def __init__(self) -> None:
        self.current_model = ModelSelection(provider="moonshot", model_id="kimi-for-coding")
        self.models = (
            ModelSelection(provider="moonshot", model_id="kimi-for-coding"),
            ModelSelection(provider="openai", model_id="gpt-5.4"),
        )
        self.set_model_calls = []

    def get_model_selection(self) -> object:
        return self.current_model

    def get_available_models(self) -> list[object]:
        return list(self.models)

    async def set_model(self, selection: object) -> None:
        self.set_model_calls.append(selection)
        self.current_model = selection


def _status_provider() -> CodingTuiStatusProvider:
    return CodingTuiStatusProvider(
        model_label="moonshot/kimi-for-coding",
        cwd="/repo",
        branch="main",
        session_label=lambda: "abcd",
        thinking_level=lambda: None,
        running=lambda: False,
    )


def _page() -> SettingsPageView:
    return asyncio.run(SettingsPageView.create(session=_Session(), status_provider=_status_provider()))


def _plain(page: SettingsPageView, *, width: int = 100, height: int = 18) -> tuple[str, ...]:
    rendered = page.render(RenderConstraints(width=width, max_height=height))
    return tuple(strip_control_sequences(line.text) for line in rendered.lines)


def test_settings_page_opens_config_tab_with_search_focus() -> None:
    page = _page()
    lines = _plain(page)

    assert any("Status" in line and "Config" in line and "Model" in line for line in lines)
    assert any("Search settings" in line for line in lines)
    assert any("Status line" in line for line in lines)
    assert page.editor_input_target() is not None


def test_settings_page_search_filters_config_rows() -> None:
    page = _page()

    assert page.handle_input(InputEvent(kind="text", text="status")) is True
    lines = _plain(page)

    assert any("Status line" in line for line in lines)
    assert not any("Terminal progress" in line for line in lines)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py -q
```

Expected: fail because `settings_page.py` does not exist.

- [ ] **Step 3: Add data objects and simple render pages**

Create `src/loushang/coding/ui/settings_page.py` with:

```python
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from loushang.coding.ui.model_list import ModelChoice, available_model_choices, current_model_choice_value, select_available_model
from loushang.coding.ui.status_provider import CodingTuiStatusProvider, StatusSnapshot
from loushang.tui import (
    CursorDeclaration,
    FocusableMixin,
    InputEvent,
    InputIntent,
    RenderConstraints,
    RenderLine,
    RenderResult,
    SearchableList,
    SearchableListItem,
    SearchableListSelect,
    TabGroup,
    TabPage,
    truncate_to_width,
)


@dataclass(frozen=True, slots=True)
class SettingsApplyResult:
    message: str
    statusline_visible: bool | None = None
    refresh_model_label: bool = False


@dataclass(frozen=True, slots=True)
class ConfigRow:
    id: str
    label: str
    value: str
    description: str = ""
    disabled: bool = False
```

Implement small helpers:

```python
def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _as_bool(value: str) -> bool | None:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None
```

Implement `StaticLinesPage(FocusableMixin)`:

- stores tuple lines;
- `focus()`/`blur()` update focus;
- `handle_input()` consumes left/right/home/end while focused;
- `render()` truncates lines.

Implement `SettingsPageView` with:

- `create(session, status_provider, usage_provider=None, settings_manager=None, session_settings=None)`;
- top-level tabs with selected value `"config"`;
- `focus()` calls `tabs.focus_content()`;
- `editor_input_target()` delegates to tabs;
- `render()` uses `tabs.render()`, adds a separator and focus-aware footer;
- `handle_input()` delegates to tabs first, then close fallback;
- `apply_setting()` initially supports `"statusline"` and `"model.current"`.

Keep initial implementation minimal: Status/Usage/Stats can render static lines from available snapshots or unavailable text.

- [ ] **Step 4: Add ConfigSettingsPage**

Implement `ConfigSettingsPage(FocusableMixin)`:

- takes `rows: tuple[ConfigRow, ...]`;
- owns `SearchableList`;
- `focus()` focuses list search;
- `handle_input()`:
  - delegates to `SearchableList`;
  - returns `InputIntent(kind="setting", text=row.id, note=next_value)` for enter/space activation;
  - consumes unhandled left/right/home/end while focused;
- `set_rows(rows, preserve_active_key="")` refreshes list items.

Initial row builder should include:

```python
def _config_rows(status_provider: CodingTuiStatusProvider, settings_manager: object | None) -> tuple[ConfigRow, ...]:
    rows = [
        ConfigRow("statusline", "Status line", _bool_text(status_provider.is_visible())),
    ]
    if settings_manager is not None:
        getter = getattr(settings_manager, "get_show_terminal_progress", None)
        if callable(getter):
            rows.append(ConfigRow("terminal.progress", "Terminal progress", _bool_text(bool(getter()))))
    rows.append(ConfigRow("model.current", "Current model", "Use Model tab", disabled=True))
    return tuple(rows)
```

- [ ] **Step 5: Add ModelPage**

Implement `ModelPage(FocusableMixin)`:

- takes model choices and current value;
- owns `SearchableList`;
- renders `Search models...`;
- activation returns `InputIntent(kind="setting", text="model.current", note=item.key)`;
- unavailable state uses `StaticLinesPage` behavior.

Use `SearchableListItem(choice.value, choice.label, status, choice.description)`.

- [ ] **Step 6: Add apply behavior**

In `SettingsPageView.apply_setting()`:

```python
if item_id == "statusline":
    enabled = _as_bool(value)
    if enabled is None:
        return SettingsApplyResult("Invalid status line value.")
    settings = self.status_provider.settings_list().set_enabled("statusline", enabled)
    message = self.status_provider.apply_settings(settings)
    self._refresh_config_rows(preserve_active_key="statusline")
    return SettingsApplyResult(message, statusline_visible=self.status_provider.is_visible())

if item_id == "model.current":
    message = await select_available_model(self.session, query=value)
    await self._refresh_model_page()
    return SettingsApplyResult(message, refresh_model_label=True)
```

Unknown ids return `SettingsApplyResult(f"Unknown setting: {item_id}")`.

- [ ] **Step 7: Run page tests**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py -q
```

Expected: tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/loushang/coding/ui/settings_page.py tests/coding/test_native_settings_page.py
git commit -m "feat(tui): add tabbed settings page view"
```

---

### Task 4: Add SettingsPageView Interaction Tests

**Files:**
- Modify: `tests/coding/test_native_settings_page.py`
- Modify: `src/loushang/coding/ui/settings_page.py`

- [ ] **Step 1: Add failing interaction tests**

Add tests:

```python
def test_settings_page_statusline_toggle_returns_setting_intent_and_apply_updates_rows() -> None:
    page = _page()
    page.handle_input(InputEvent(kind="key", key="down"))
    intent = page.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="setting", text="statusline", note="false")

    result = asyncio.run(page.apply_setting("statusline", "false"))

    assert result.statusline_visible is False
    assert result.message == "Status line: off"
    assert any("Status line" in line and "false" in line for line in _plain(page))


def test_settings_page_q_is_search_text_but_closes_from_list_focus() -> None:
    page = _page()

    assert page.handle_input(InputEvent(kind="text", text="q")) is True
    assert any("q" in line for line in _plain(page))

    page.handle_input(InputEvent(kind="key", key="down"))
    assert page.handle_input(InputEvent(kind="text", text="q")) == InputIntent(kind="surface_close")


def test_settings_page_search_editing_keys_do_not_switch_tabs() -> None:
    page = _page()

    before = page.tabs.value
    assert page.handle_input(InputEvent(kind="key", key="right")) is True

    assert page.tabs.value == before


def test_settings_page_model_tab_filters_and_selects_model() -> None:
    page = _page()
    page.tabs.focus_header()
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="right"))
    page.handle_input(InputEvent(kind="key", key="down"))

    assert page.tabs.value == "model"
    assert page.handle_input(InputEvent(kind="text", text="gpt")) is True
    intent = page.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="setting", text="model.current", note="openai/gpt-5.4")
```

- [ ] **Step 2: Run tests to verify failures**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py -q
```

Expected: interaction gaps fail if routing/apply is incomplete.

- [ ] **Step 3: Fix interaction routing**

In `SettingsPageView.handle_input()`:

- delegate to `self.tabs.handle_input(event)` first;
- if result is `SearchableListSelect`, convert by selected page type;
- if result is not `None`, return result;
- close on Esc/Escape;
- close on text/key `q` only if `_focus_context()` is `"tabs"`, `"page"`, or `"settings-list"`, not `"search"`.

In `ConfigSettingsPage` and `ModelPage`, make activation explicit for list/search enter and list-space. Do not intercept text `" "` while search is focused.

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/loushang/coding/ui/settings_page.py tests/coding/test_native_settings_page.py
git commit -m "test(tui): cover settings page keyboard behavior"
```

---

### Task 5: Integrate SettingsPageView Into NativeSurfaceManager

**Files:**
- Modify: `src/loushang/coding/ui/native_surfaces.py`
- Modify: `tests/coding/test_native_coding_tui_surfaces.py`

- [ ] **Step 1: Add failing manager tests**

Update `test_native_surface_manager_opens_settings_in_bottom_frame_with_runtime_overlay_host()` to expect the new tabbed page:

```python
rendered = app.active_surface.render(RenderConstraints(width=100, max_height=12))
plain = tuple(strip_control_sequences(line.text) for line in rendered.lines)
assert any("Status" in line and "Config" in line and "Model" in line for line in plain)
assert any("Search settings" in line for line in plain)
assert any("Status line" in line for line in plain)
```

Add tests:

```python
def test_native_surface_manager_settings_page_submit_keeps_surface_open() -> None:
    app = _app()
    manager = _manager(app, _Session())

    asyncio.run(manager.handle_text("/settings"))
    assert isinstance(app.active_surface, NativeSurfaceView)
    intent = app.active_surface.handle_input(InputEvent(kind="key", key="enter"))

    assert intent == InputIntent(kind="setting", text="statusline", note="false")
    asyncio.run(manager.handle_surface_intent(intent))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert app.state.statusline_visible is False
    assert app.state.status_message == "Status line: off"


def test_native_surface_manager_legacy_settings_surface_still_closes_on_submit() -> None:
    app = _app()
    manager = _manager(app, _Session())
    app.active_surface = NativeSurfaceView(
        title="Settings",
        purpose="settings",
        content=SettingsSurface(list(manager.status_provider.settings_list().items), enable_search=True),
        presentation="bottom-exclusive",
    )

    asyncio.run(manager.handle_surface_intent(InputIntent(kind="setting", text="statusline", note="false")))

    assert app.active_surface is None
    assert app.state.statusline_visible is False
```

Add model submit test:

```python
def test_native_surface_manager_settings_page_model_submit_uses_model_selection() -> None:
    session = _Session()
    app = _app()
    manager = _manager(app, session)

    asyncio.run(manager.handle_text("/settings"))
    asyncio.run(manager.handle_surface_intent(InputIntent(kind="setting", text="model.current", note="openai/gpt-5.4")))

    assert isinstance(app.active_surface, NativeSurfaceView)
    assert session.set_model_calls
    assert app.state.model_label == "openai/gpt-5.4"
```

- [ ] **Step 2: Run targeted tests to verify failures**

Run:

```bash
uv run pytest tests/coding/test_native_coding_tui_surfaces.py -q
```

Expected: settings opener and submit routing tests fail.

- [ ] **Step 3: Make `_open_settings()` async and await it**

In imports:

```python
from loushang.coding.ui.settings_page import SettingsPageView
```

Change:

```python
elif command.name == "settings" and isinstance(intent, SettingsIntent):
    await self._open_settings()
```

Change `_open_settings`:

```python
async def _open_settings(self) -> None:
    surface = await SettingsPageView.create(
        session=self.session,
        status_provider=self.status_provider,
        settings_manager=getattr(self.session, "settings_manager", None),
        session_settings=getattr(self.session, "settings_controller", None),
    )
    self._open_surface(
        NativeSurfaceView(
            title="Settings",
            purpose="settings",
            content=surface,
            footer="",
            presentation="bottom-exclusive",
        )
    )
```

- [ ] **Step 4: Delegate new-page submit handling**

Update `_handle_settings_submit()`:

```python
async def _handle_settings_submit(self, payload: dict[str, str]) -> None:
    surface = self._current_surface()
    page = surface.content if isinstance(surface, NativeSurfaceView) else None
    apply_setting = getattr(page, "apply_setting", None)
    if callable(apply_setting):
        result = await apply_setting(payload["id"], payload.get("value", ""))
        if getattr(result, "statusline_visible", None) is not None:
            self.app.set_statusline_visible(result.statusline_visible)
        if getattr(result, "refresh_model_label", False):
            await self._refresh_model_label()
        self.app.set_status(result.message)
        return

    updated = self.status_provider.settings_list().toggle(payload["id"])
    self.close_surface()
    message = self.status_provider.apply_settings(updated)
    self.app.set_statusline_visible(self.status_provider.is_visible())
    self.app.set_status(message)
```

- [ ] **Step 5: Run manager tests**

Run:

```bash
uv run pytest tests/coding/test_native_coding_tui_surfaces.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/loushang/coding/ui/native_surfaces.py tests/coding/test_native_coding_tui_surfaces.py
git commit -m "feat(tui): open real tabbed settings page"
```

---

### Task 6: Update Native Playback Coverage

**Files:**
- Modify: `tests/coding/test_native_coding_tui_playback.py`

- [ ] **Step 1: Update existing `/settings` playback tests**

Change `test_native_tui_playback_settings_surface_toggles_statusline()` expectations:

```python
steps = playback.play(
    [
        PlaybackEvent.input("/settings\r"),
        PlaybackEvent.input("\r"),
        PlaybackEvent.input("\x1b"),
    ]
)

assert app.active_surface is None
assert app.state.statusline_visible is False
assert app.state.status_message == "Status line: off"
```

Update visible text assertions to expect the tabbed page during intermediate frames and absence after Esc.

Change search test expectations from legacy `Search: zz` to the new query row. Assert:

```python
assert any("Search settings" in line and "zz" in line for line in lines)
assert any("No matching settings" in line for line in lines)
```

- [ ] **Step 2: Add playback tests for q and Model tab**

Add:

```python
def test_native_tui_playback_settings_q_is_search_text_then_list_close_key() -> None:
    session = _Session()
    app = _app()
    playback = _NativeInteractivePlayback(app, _manager(app, session), columns=100, rows=18)

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("q"),
        ]
    )

    assert app.active_surface is not None
    assert any("q" in line for line in _plain_lines(steps[-1].diagnostics))


def test_native_tui_playback_settings_model_tab_is_available() -> None:
    session = _Session()
    app = _app()
    playback = _NativeInteractivePlayback(app, _manager(app, session), columns=100, rows=18)

    steps = playback.play(
        [
            PlaybackEvent.input("/settings\r"),
            PlaybackEvent.input("\x1b[A"),  # search -> top tabs
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[C"),
            PlaybackEvent.input("\x1b[B"),  # content
        ]
    )

    lines = _plain_lines(steps[-1].diagnostics)
    assert any("Search models" in line for line in lines)
    assert any("moonshot/kimi-for-coding" in line for line in lines)
```

Adjust exact key sequences if playback translation differs; keep intent assertions stable.

- [ ] **Step 3: Run playback tests**

Run:

```bash
uv run pytest tests/coding/test_native_coding_tui_playback.py -k settings -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/coding/test_native_coding_tui_playback.py
git commit -m "test(tui): update settings page playback"
```

---

### Task 7: Final Focused Verification And Cleanup

**Files:**
- Modify only if tests reveal small issues:
  - `src/loushang/coding/ui/settings_page.py`
  - `src/loushang/coding/ui/native_surfaces.py`
  - `tests/coding/test_native_settings_page.py`
  - `tests/coding/test_native_coding_tui_surfaces.py`
  - `tests/coding/test_native_coding_tui_playback.py`

- [ ] **Step 1: Run focused test suite**

Run:

```bash
uv run pytest tests/coding/test_native_settings_page.py tests/coding/test_native_coding_tui_surfaces.py tests/coding/test_native_coding_tui_playback.py -k "settings or model_selector or native_surface_view" -q
```

Expected: pass.

- [ ] **Step 2: Run widget regressions**

Run:

```bash
uv run pytest tests/tui/test_widgets_tab_group.py tests/tui/test_widgets_searchable_list.py -q
```

Expected: pass.

- [ ] **Step 3: Run lint on touched files**

Run:

```bash
uv run ruff check src/loushang/coding/ui/settings_page.py src/loushang/coding/ui/native_surfaces.py src/loushang/coding/ui/status_provider.py tests/coding/test_native_settings_page.py tests/coding/test_native_coding_tui_surfaces.py tests/coding/test_native_coding_tui_playback.py
```

Expected: pass.

- [ ] **Step 4: Manual smoke**

Run:

```bash
uv run pytest tests/coding/test_native_coding_tui_playback.py -k settings -q
```

Expected: pass. This is the automated playback equivalent of manual `/settings` smoke for this slice.

- [ ] **Step 5: Commit any final cleanup**

If Step 1-4 required fixes:

```bash
git add <changed-files>
git commit -m "fix(tui): polish settings page integration"
```

If no fixes were needed, skip this commit.

---

## Implementation Notes

- Do not add a new `InputIntentKind` for model selection.
- Do not delete `SettingsSurface`; legacy tests must still pass.
- Do not close the new `SettingsPageView` after Config or Model selection.
- Do not parse toolbar render text for Status page data.
- Do not compute Usage by broad session introspection. Use an explicit provider or render unavailable.
- Keep `/model` behavior intact. Existing model selector tests should continue to pass.
- Keep changes local to the coding product surface and host compatibility hooks; do not refactor generic widgets unless a test proves a widget bug.
