# TUI InputRouter Target Decoupling Design

## Status

Partially superseded by
[TUI/HarnessTUI Input Ownership Boundary](2026-08-22-tui-harnesstui-input-ownership-boundary-design.md).
The target-adapter and focused-editor design remains valid. Statements that
generic `InputRouter` owns running abort, steer, follow-up, or queued-message
semantics are historical and no longer describe the current contract.

## Context

`loushang.tui` has a mature terminal input stack: `InputReader` normalizes
terminal byte streams into `InputEvent`, `InputRouter` turns those events into
editor mutations or `InputIntent`, and `SurfaceHost` can route events to focused
surfaces. The rendering layer now has an explicit strategy pipeline, so the next
maintainability issue is input routing.

The current `InputRouter` is coupled directly to `Composer`. It stores
`composer: Composer`, calls many concrete `composer.*` methods, and exposes
helper functions named `route_composer_editing_key()` and
`route_composer_selection_key()`. This works for the prompt composer, but it
makes multiple editor instances awkward. Any future search field, dialog input,
tree filter, or inline editor either needs to bypass `InputRouter` or grow more
Composer-specific conditionals.

The codebase already has the pieces for a cleaner model. `SurfaceHost` tracks a
focused `Focusable`, translates mouse coordinates for surface entries, and routes
surface events before the composer. `TextInput` already implements its own
`handle_input()` and has focused rendering. The gap is a narrow target boundary
between generic router decisions and prompt-specific Composer behavior.

## Goals

- Remove `InputRouter`'s hard dependency on the concrete `Composer` type.
- Preserve all existing key behavior, `InputIntent` values, and routing priority.
- Keep `composer=` construction working for existing callers and tests.
- Make prompt-specific behavior explicit instead of pretending every editor has
  history, completions, steering, and queued follow-up semantics.
- Create a path for multiple editable widgets without introducing a full focus
  manager in this slice.
- Reduce duplicated Composer key routing between `InputRouter` and
  `NativeInputRouter` in a later implementation phase.

## Non-Goals

- Do not change `InputReader` parsing, key names, paste sanitization, or Kitty
  input protocol handling.
- Do not change submit, follow-up, steer, completion, history, or abort
  semantics.
- Do not introduce a widget ecosystem, dialog framework, or global focus manager.
- Do not make `TextInput` the prompt composer.
- Do not require existing callers to replace `InputRouter(composer=...)` in the
  first implementation.
- Do not move product-specific native coding behavior into `loushang.tui`.

## Design Summary

Introduce a target adapter layer between `InputRouter` and editable state.
`InputRouter` continues to own global routing order, running-state abort rules,
surface-first dispatch, resize invalidation, and prompt submission decisions.
Editor operations are delegated to a target interface.

The first implementation keeps behavior unchanged:

1. Add a generic editor target protocol for text insertion, paste, cursor
   movement, selection, kill-ring operations, undo/redo, and visual navigation.
2. Add a prompt target protocol for Composer-only features: value submission,
   history browsing, completions, explicit newlines, and jump-to-character mode.
3. Add `ComposerInputTarget`, a stateless adapter over a `Composer` instance.
4. Update `InputRouter` to use a target internally while preserving the public
   `composer` field or property for compatibility.
5. Generalize composer key helpers to target key helpers, leaving the old helper
   names as compatibility wrappers.

This is adapter-first, not focus-manager-first. Surfaces still receive events
before the prompt target. A later slice can let `SurfaceHost` expose an active
editor target when a focused surface wants shared router behavior.

## Target Types

The target API should be small enough to describe input behavior, not the entire
Composer object.

```python
class EditorInputTarget(Protocol):
    def insert_text(self, text: str) -> None: ...
    def paste(self, text: str) -> None: ...
    def move_left(self) -> None: ...
    def move_right(self) -> None: ...
    def move_word_left(self) -> None: ...
    def move_word_right(self) -> None: ...
    def move_to_line_start(self) -> None: ...
    def move_to_line_end(self) -> None: ...
    def select_char_left(self) -> None: ...
    def select_char_right(self) -> None: ...
    def select_word_left(self) -> None: ...
    def select_word_right(self) -> None: ...
    def select_line_start(self) -> None: ...
    def select_line_end(self) -> None: ...
    def delete_backward(self) -> None: ...
    def delete_forward(self) -> None: ...
    def delete_word_backward(self) -> None: ...
    def delete_word_forward(self) -> None: ...
    def kill_to_line_start(self) -> None: ...
    def kill_to_line_end(self) -> None: ...
    def yank(self) -> None: ...
    def yank_pop(self) -> None: ...
    def undo(self) -> None: ...
    def redo(self) -> None: ...
```

The prompt target extends this with behavior that should not be assumed for
ordinary fields:

```python
class PromptInputTarget(EditorInputTarget, Protocol):
    @property
    def value(self) -> str: ...

    @property
    def browsing_history(self) -> bool: ...

    @property
    def has_completions(self) -> bool: ...

    def clear(self) -> None: ...
    def add_history(self, text: str) -> None: ...
    def insert_newline(self) -> None: ...
    def history_previous(self) -> None: ...
    def history_next(self) -> None: ...
    def move_visual_up(self, *, width: int) -> bool: ...
    def move_visual_down(self, *, width: int) -> bool: ...
    def move_visual_page_up(self, *, width: int, visible_lines: int) -> None: ...
    def move_visual_page_down(self, *, width: int, visible_lines: int) -> None: ...
    def jump_to_char(self, text: str, *, direction: Literal["forward", "backward"]) -> None: ...
    def refresh_completions(self, *, force: bool = False, explicit: bool = False) -> None: ...
    def apply_selected_completion(self) -> None: ...
    def select_previous_completion(self) -> None: ...
    def select_next_completion(self) -> None: ...
    def clear_completion_items(self) -> None: ...
```

The interface intentionally remains method-oriented. A single
`handle_input(event)` callback would align with `TextInput`, but it would move
too much routing policy into every target and make global priority rules harder
to audit. Read-only state is kept on `PromptInputTarget` unless generic key
helpers need it. Fake-target tests may expose their own inspection fields without
widening the production protocol.

## InputRouter Construction

The first implementation should preserve the existing constructor shape:

```python
@dataclass(slots=True)
class InputRouter:
    composer: Composer | None = None
    target: InitVar[PromptInputTarget | None] = None
    _target: PromptInputTarget = field(init=False, repr=False)
    ...

    def __post_init__(self, target: PromptInputTarget | None) -> None:
        if self.composer is not None and target is not None:
            raise TypeError("InputRouter accepts composer or target, not both")
        if target is not None:
            self._target = target
        elif self.composer is not None:
            self._target = ComposerInputTarget(self.composer)
        else:
            raise TypeError("InputRouter requires composer or target")
```

`composer` and `target` are intentionally mutually exclusive. This avoids two
sources of editable state drifting apart. Existing `InputRouter(composer=...)`
callers continue to work; new callers use `InputRouter(target=...)`. The router
uses `_target` internally and may expose a read-only `target` property for tests
and diagnostics.

The public `composer` attribute may remain during the transition. It should be
documented as a compatibility attribute for prompt routers, not as the router's
long-term extension point.

## Routing Order

This order describes the generic `InputRouter` only. Routing priority must not
change:

1. Ignore key release events.
2. For key events, clear jump-to-character mode before continuing. If the key is
   another jump-mode key, clear the mode and consume the event.
3. For key events, route active runtime surfaces and return if they emit
   `InputIntent` values.
4. Route selection keys before completion handling.
5. Route completion navigation and cancellation.
6. Convert cancel to abort only when the app is running and completion did not
   consume it.
7. Enter jump-to-character mode.
8. Emit queue-edit command intents.
9. Force and apply completion on tab.
10. Submit prompt text exactly as typed. Do not apply an active completion on
    generic submit.
11. Insert explicit newline.
12. Move visual cursor or browse history.
13. Route page movement.
14. Route ordinary editing keys.
15. Route paste and text insertion.
16. Emit render invalidation for resize and SIGWINCH.

The adapter should not reorder these checks. Tests should assert the most fragile
crossovers: completion cancel before running abort, selection before completion,
surface escape before running abort, and submit without applying an active
completion.

## Key Helper Extraction

Rename helper internals around editor targets:

- `route_editor_editing_key(target, key, *, keybindings=None) -> bool`
- `route_editor_selection_key(target, key, *, keybindings=None) -> bool`
- `route_prompt_completion_key(target, key, *, keybindings=None) -> bool`

Keep compatibility wrappers:

```python
def route_composer_editing_key(composer: Composer, key: str, *, keybindings=None) -> bool:
    return route_editor_editing_key(ComposerInputTarget(composer), key, keybindings=keybindings)
```

The wrapper creation cost is negligible for compatibility callers. If this
becomes a hot path in `NativeInputRouter`, it should store and reuse a target
adapter instead of calling the wrapper repeatedly.

## NativeInputRouter Reuse

`NativeInputRouter` is product-specific and should remain in
`loushang.coding.ui.native_input`, but it currently duplicates much of the
Composer routing chain. After `InputRouter` has target helpers, native input can
incrementally reuse:

- `ComposerInputTarget` for prompt editing.
- `route_editor_selection_key()` and `route_editor_editing_key()` for ordinary
  editing behavior.
- `route_prompt_completion_key()` for completion navigation if the native
  submit-after-slash-command rule stays local.

Native-only behavior remains local:

- clipboard image attachment
- local command detection
- queued steer/follow-up integration
- transcript reader command
- restoring queued messages
- exit command mapping

This keeps `loushang.tui` general while reducing duplicated editor semantics.

Native routing order is not the generic `InputRouter` order. It must keep its
existing product-specific priority: runtime surfaces and active surfaces route
before text/paste/resize/key-release handling, transcript and queued-message
commands stay native, `follow_up_keys` keep their current position, and
slash-command selected-completion submit remains native-only. If helper reuse
would reorder any of those checks, stop at generic router decoupling and leave
native routing unchanged.

## Surface and TextInput Path

The first slice should not make surfaces use `InputRouter`. `SurfaceHost` already
routes focused surface input before the prompt, and `TextInput.handle_input()`
already works for standalone overlays.

The target layer prepares the next slice:

- A focused surface may optionally expose an `EditorInputTarget`.
- `SurfaceHost` may later expose `current_editor_target()`.
- `InputRouter` may later route shared editor keys to that focused editor before
  falling back to the prompt target.

That later focus integration needs its own spec because it will define how
surface-local submit, escape, and consumed intents interact with global prompt
submission.

## Error Handling

- Constructing `InputRouter` without either `composer` or `target` should fail
  early with a clear `TypeError`.
- Constructing `InputRouter` with both `composer` and `target` should fail early
  with a clear `TypeError`.
- A target missing required prompt behavior should fail at construction or first
  use, not silently fall back to Composer.
- Existing surface input normalization should remain defensive: non-`InputIntent`
  surface results are ignored unless already supported.
- The compatibility wrappers should remain thin. They should not catch errors
  from target methods because those errors indicate broken editor state or an
  incomplete adapter.

## Testing

Focused tests should come before implementation.

Add target-level tests:

- `InputRouter(composer=composer)` creates a Composer-backed target and preserves
  existing text, paste, submit, and clear behavior.
- `InputRouter(target=fake_prompt_target)` routes ordinary editing keys without
  importing or constructing `Composer`.
- Passing both `composer` and `target` raises `TypeError`.
- Selection keys call target selection methods before completion routing.
- Completion cancel still closes completion before running abort.
- Tab still forces completions and applies the selected completion.
- Enter with active completion in generic `InputRouter` still submits raw text
  without applying completion.
- Native slash-command completion submit stays covered by native input tests.
- Resize and SIGWINCH still emit `invalidate_render` without touching the target.

Keep existing behavior tests:

- `tests/tui/test_input_routing.py` should remain green.
- Text input overlay tests should remain green, proving surface-first routing is
  unchanged.
- Native input focused tests should remain green after helper reuse.

The implementation should run:

```sh
uv --cache-dir .uv-cache run --extra dev pytest tests/tui/test_input_routing.py tests/tui/test_text_input.py -q
uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_native_coding_tui_input.py -q
uv --cache-dir .uv-cache run --extra dev pytest tests/tui -q
uv --cache-dir .uv-cache run --extra dev ruff check src/loushang/tui/input.py src/loushang/coding/ui/native_input.py tests/tui/test_input_routing.py
```

Adjust the native input test path if the current repository names it
differently.

## Rollout Plan

Use small behavior-preserving commits:

1. Add target protocols, `ComposerInputTarget`, and target key helper tests.
2. Route `InputRouter` through the target adapter while keeping `composer=`
   compatibility.
3. Keep old composer helper names as wrappers and update tests to cover both
   compatibility and target paths.
4. Reuse target helpers inside `NativeInputRouter` where this does not change
   native coding behavior.
5. Document the input routing order and target boundary in the TUI internals
   docs.

Stop after step 3 if native reuse begins to require product behavior changes.
The main value is decoupling the generic router; native deduplication is useful
but secondary.

## Rejected Approaches

### Make Composer Implement a Large Protocol Directly

This is the smallest edit, but it leaves `InputRouter` conceptually coupled to
Composer. The protocol would become a renamed copy of Composer's public surface,
and future editors would need to grow prompt-only methods they do not support.

### Give Every Editor `handle_input(event)`

This matches `TextInput`, but it pushes routing policy into each editable widget.
Global rules such as surface-first dispatch, completion-before-abort, and
running submit modes would become harder to verify. `InputRouter` should keep
the policy; targets should provide operations.

### Build a Full Focus Manager Now

A focus manager is likely needed eventually, but it is larger than the immediate
problem. The current `SurfaceHost` already handles focused surfaces. The first
slice should make prompt routing replaceable, then the next slice can decide how
focused editor targets interact with prompt submission and surface intents.

## Success Criteria

- Existing `InputRouter(composer=...)` callers keep working.
- `InputRouter` can be tested with a fake prompt target and no `Composer`
  instance.
- Composer-specific methods are isolated in `ComposerInputTarget`.
- Existing input routing behavior and priority tests pass unchanged.
- Future editor widgets can reuse router key policy without pretending to be a
  Composer.
- A contributor can understand where generic input policy ends and prompt
  behavior begins without reading all of `input.py`.
