# TUI Editing

English | [中文](../../zh-CN/reference/tui-editing.md)

`loushang.tui` provides reusable editing primitives for terminal inputs. Use
them when a surface needs cursor movement, selection, undo, kill/yank, paste,
or completion behavior without carrying bespoke edit state.

For lifecycle wiring, see [TUI Runner](tui-runner.md).

## Components

| Component | Use it for | Index unit |
| --- | --- | --- |
| `TextInput` | Single-line fields such as search, filters, and small prompts. | Grapheme cluster |
| `Composer` | Multi-line prompt editors, bottom-frame composers, paste markers, history, and completions. | Composer atom |
| `InputRouter` | User-like routing for Composer key, text, paste, completion, history, submit, and surface events. | Composer atom |
| `SelectionRange` / `SelectionController` | Reusable anchor/focus selection state. | Supplied by the owning buffer |

Editing indexes are not terminal cell columns. Wide CJK, emoji, combining
marks, and paste markers keep stable logical indexes; display width remains a
rendering and hit-test concern.

## TextInput

`TextInput` is a focusable single-line editor. It owns an `EditorBuffer`,
selection state, undo/redo stacks, and a kill ring.

```python
from loushang.tui import InputEvent, RenderConstraints, TextInput


field = TextInput(prompt="Search: ", placeholder="type to filter")
field.focus()

field.handle_input(InputEvent(kind="text", text="hello world"))
field.handle_input(InputEvent(kind="key", key="ctrl+shift+left"))
assert field.selected_range == (6, 11)

field.handle_input(InputEvent(kind="text", text="loushang"))
assert field.value == "hello loushang"

field.handle_input(InputEvent(kind="key", key="ctrl+-"))
assert field.value == "hello world"

field.handle_input(InputEvent(kind="key", key="alt+r"))
assert field.value == "hello loushang"

result = field.render(RenderConstraints(width=40, max_height=1))
```

Prefer `handle_input()` for user keystrokes because it records undo boundaries
and invokes callbacks. `set_text()` and `clear()` are programmatic resets and
clear undo/redo history. `selected_range` is `None` when there is no active
non-empty selection.

## Composer

`Composer` is the multi-line editor used by prompt and bottom-frame UIs. It
adds atom-aware editing, paste-marker safety, history, completion refresh, and
rendered selection highlighting.

Use `InputRouter` when you want behavior equivalent to normal terminal input:

```python
from loushang.tui import Composer, InputEvent, InputRouter, RenderConstraints


composer = Composer(prompt="> ")
router = InputRouter(composer, width=72, height=12)

router.route(InputEvent(kind="text", text="alpha beta"))
router.route(InputEvent(kind="key", key="shift+left"))
assert composer.selected_range == (9, 10)

router.route(InputEvent(kind="key", key="ctrl+k"))
assert composer.value == "alpha bet"
assert composer.kill_ring[0] == "a"

router.route(InputEvent(kind="key", key="ctrl+y"))
assert composer.value == "alpha beta"

result = composer.render(RenderConstraints(width=72, max_height=6))
```

Composer selections use atom indexes. Normal text is split into grapheme-like
text atoms; large paste markers are single atoms and are never split by range
editing.

## Default Editing Keys

| Action | Default keys |
| --- | --- |
| Move left / right | `left`, `right`, `ctrl+b`, `ctrl+f` |
| Move by word | `alt+left`, `ctrl+left`, `alt+b`, `alt+right`, `ctrl+right`, `alt+f` |
| Move to line start / end | `home`, `ctrl+a`, `alt+<`, `end`, `ctrl+e`, `alt+>` |
| Select char | `shift+left`, `shift+right` |
| Select word | `ctrl+shift+left`, `alt+shift+b`, `ctrl+shift+right`, `alt+shift+f` |
| Select line range | `shift+home`, `shift+end` |
| Delete char | `backspace`, `delete`, `ctrl+d` |
| Delete word | `ctrl+w`, `alt+backspace`, `alt+d`, `alt+delete` |
| Kill to line start / end | `ctrl+u`, `ctrl+k` |
| Yank / yank-pop | `ctrl+y`, `alt+y` |
| Undo | `ctrl+-`, `ctrl+_`, `alt+u` |
| Redo | `alt+r` |
| New line / submit | `shift+enter`, `alt+enter`, `ctrl+j`, `enter` |

Some terminals report `ctrl+-` as `ctrl+_`; both are treated as undo. `alt+u`
and `alt+r` provide mnemonic terminal-stable undo/redo alternatives without
claiming `ctrl+u` or `ctrl+r`.

## Selection-Aware Edits

When a selection exists:

- typing and paste replace the selected range in one undoable edit
- Backspace and Delete remove the selected range without deleting adjacent text
- kill commands kill the selected range instead of also applying line or word
  boundaries
- yank replaces the selected range
- completion application clears text selection
- undo and redo restore content and cursor, then clear selection

Completion-list selection and composer text selection are independent. Selection
keybindings route before completion-list navigation, while unmodified
completion keys such as `up`, `down`, `tab`, and `enter` keep their completion
behavior.

## Playback Smoke Cookbook

Run playback before changing composer input, selection, paste marker,
completion, keybinding, or render-highlight behavior:

```bash
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py --list
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py composer-selection-stress --artifacts /tmp/loushang-selection-playback --include-frames
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py --tag composer --json
```

Use `--include-frames` when diagnosing transient selection rendering. The final
screen often cannot show a selection after replacement, kill, yank, or undo
because those operations intentionally clear selection.

## Examples

- [examples/tui/41_editing_foundation.py](../../../examples/tui/41_editing_foundation.py):
  deterministic TextInput and Composer editing walkthrough.
- [examples/tui/35_completion_providers.py](../../../examples/tui/35_completion_providers.py):
  completion provider behavior in Composer.
- [examples/tui/40_runner_basic.py](../../../examples/tui/40_runner_basic.py):
  `TuiRunner` lifecycle and top-level input handling.
