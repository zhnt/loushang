# 2026-06-15 Plain And Screen UI Boundary Audit

This report records the current `loushang.coding.ui` boundary after the screen UI
naming cleanup, the explicit plain renderer naming cleanup, and the explicit
plain event projection and app assembly naming cleanups.

> Historical note: the temporary playback, performance, shared state, status,
> settings, control, reader, and transcript-style compatibility modules listed
> below were retired by the later Harnesstui canonical-import cutover. Their
> implementations and tests now use the canonical TUI, Harnesstui, and Coding
> testing module paths directly.

## Scope

This audit covers product-side coding UI modules only:

- `src/loushang/coding/ui/*`
- direct consumers such as `src/loushang/coding/prompt_command.py`
- coding UI import-boundary tests

It does not propose changes to `loushang.tui`. The TUI package should remain a
reusable terminal component library with flexible atomic parts, render helpers,
and composition surfaces. Product-specific coding shell behavior belongs in
`loushang.coding.ui`.

## Vocabulary

Use these names consistently:

- `plain`: line-oriented, stable text/transcript output for non-full-screen
  coding runs and prompt-command output.
- `screen`: full-screen interactive terminal shell backed by the native terminal
  runtime.
- `tui`: the reusable terminal UI library and public component namespace.

Plain does not mean legacy. It is a product capability for scripts, non-TTY
execution, transcript-friendly output, and prompt-command workflows. Screen is
the richer interactive shell. Both are valid coding surfaces.

Avoid using "native UI" and "non-native UI" as product boundaries in new code.
They describe implementation detail less clearly than `screen` and `plain`.

## Current Classification

### Plain-Specific

These modules are already plain-specific or should become explicitly
plain-specific:

| Module | Current role | Recommendation |
| --- | --- | --- |
| `plain_renderer.py` | Renders stable line-oriented coding output and optional transcript records. | Keep. This is the plain surface renderer. |
| `plain_toolbar.py` | Formats compact toolbar/status text for plain output. | Keep. This is plain output presentation. |
| `plain_events.py` | Projects session events into `PlainCodingUiRenderer`. | Keep. This is the plain event projector. |
| `plain_app.py` | Builds the current plain prompt-loop app around shared handlers. | Keep. This is the plain app assembly. |

Evidence:

- `plain_events.py` imports `PlainCodingUiRenderer` and calls only plain rendering
  methods.
- `plain_app.py` requires `PlainCodingUiRenderer`, wires `PlainCodingConversationActionHost`, and is
  used by `_run_plain_tui`.
- `prompt_command.py` directly uses `PlainCodingUiRenderer` plus
  `PlainCodingEventRenderer` to render one-shot prompt output.

### Screen-Specific

These modules form the screen interactive shell and should keep the `screen_`
prefix:

- `screen_app.py`
- `screen_state.py`
- `screen_input.py`
- `screen_loop.py`
- `screen_events.py`
- `screen_surfaces.py`
- `playback.py`
- `playback_suite.py`
- `playback_runner.py`
- `playback_scenarios/*`
- `perf_probe.py`

`transcript_source.py` currently depends on `ScreenCodingTuiState` because it
merges persisted transcript records with the active screen window. Keep it
screen-adjacent unless it later gains a second non-screen consumer.

### Shared Control And Product Helpers

These modules should keep neutral names for now:

- `mode.py`
- `controller.py`
- `handlers.py`
- `prompt_dispatch.py`
- `prompt_result.py`
- `prompt_routing.py`
- `intent.py`
- `lifecycle.py`
- `abort.py`
- `steer.py`
- `follow_up_queue.py`
- `pending_queue.py`
- `status_provider.py`
- `status_line.py`
- `settings_page.py`
- `settings_page_view.py`
- `session_view.py`
- command/model/debug/hotkey helpers
- tool transcript/block projection helpers

Rationale:

- `mode.py` is the product surface selector. It decides between screen and
  plain, then delegates into the selected path.
- `handlers.py`, `prompt_dispatch.py`, and `prompt_result.py` are protocol-based
  control units for prompt, command, lifecycle, abort, follow-up, and result
  semantics. They are currently assembled by the plain app, but their concepts
  are not renderer-specific.
- `abort.py`, `steer.py`, and `follow_up_queue.py` depend on renderer protocols,
  not concrete plain classes. They should not be renamed to `plain_*` unless a
  future screen path stops sharing the semantics and they become truly
  plain-only.
- Settings, status line, command catalog, prompt intent, and session view are
  product-level coding concerns, not plain or screen presentation details.

## TUI Library Boundary

The clean dependency direction is:

```text
loushang.coding.ui -> loushang.tui
loushang.tui       -> no loushang.coding dependency
```

Current import-boundary tests already protect the most important edges:

- importing screen state does not load `mode` or `plain_renderer`
- the old `loushang.coding.ui.renderer` module is gone
- `loushang.tui` import checks should not be affected by coding-side renderer
  imports

Future changes should preserve this direction. Product-specific settings rows,
status text, coding session labels, queue state, prompt intents, and playback
scenarios should stay out of `loushang.tui`.

## Cleanup Sequence

### Completed: Rename Plain Event Projection

The event projection boundary is explicit:

- `src/loushang/coding/ui/plain_events.py`
- `PlainCodingEventRenderer`
- imports updated in:
  - `mode.py`
  - `prompt_command.py`
  - `tests/coding/test_ui_plain_renderer.py`
- import-boundary assertion added for removed `loushang.coding.ui.events`

This was low risk because the class already required `PlainCodingUiRenderer`.

### Completed: Rename Plain App Assembly

The plain prompt-loop app assembly boundary is explicit:

- `src/loushang/coding/ui/plain_app.py`
- `PlainCodingTuiApp`
- `build_plain_coding_tui_app`
- imports updated in:
  - `mode.py`
  `tests/coding/test_ui_plain_app.py`
- import-boundary assertion added for removed `loushang.coding.ui.app`

This makes `screen_app.py` and `plain_app.py` symmetrical without changing
runtime behavior.

### 1. Hold Shared Handlers Stable

Do not rename these in the same pass:

- `handlers.py`
- `prompt_dispatch.py`
- `prompt_result.py`
- `abort.py`
- `steer.py`
- `follow_up_queue.py`

They should remain neutral until a later audit proves they are plain-only. A
premature rename would make the architecture look cleaner than the actual
ownership model and could cause screen semantics to fork unnecessarily.

### 2. Avoid New Subpackages For Now

Do not introduce `ui/plain/` and `ui/screen/` subpackages yet. The flat module
layout with explicit `plain_*` and `screen_*` names is currently simpler:

- it keeps imports short,
- it matches the recent naming direction,
- it avoids large mechanical moves,
- it still gives enough visual separation in file listings and tests.

Revisit subpackages only if both surfaces continue to grow after the plain app
and plain event rename cleanups.

## Non-Goals

This audit does not recommend:

- deleting plain output capability,
- moving product settings or session semantics into `loushang.tui`,
- adding compatibility shims for old module names,
- changing command behavior,
- changing terminal rendering,
- renaming shared control modules without stronger ownership evidence.

## Validation For Follow-Up PRs

For future rename PRs, use targeted red/green validation:

- import-boundary test for the removed old module name
- focused plain renderer/app tests
- mode tests that cover both screen and plain dispatch
- CLI prompt-command tests if imports move through `prompt_command.py`

Suggested commands:

```bash
uv --cache-dir /tmp/uv-cache run --extra dev pytest tests/coding/test_ui_plain_renderer.py tests/coding/test_ui_mode.py tests/coding/test_ui_import_boundaries.py -q
uv --cache-dir /tmp/uv-cache run --extra dev pytest tests/coding/test_ui_plain_app.py tests/coding/test_cli.py -k tui -q
uv --cache-dir /tmp/uv-cache run --extra dev ruff check src/loushang/coding tests/coding
git diff --check
```

## Recommendation

Treat the plain/screen naming cleanup as complete for the current flat module
layout. Keep plain as a first-class capability, keep screen as the interactive
shell, and keep `loushang.tui` clean by letting it provide reusable terminal
components rather than product-specific coding UI surfaces.
