# KD-018: Transcript Reader And Copy Semantics

Status: Accepted. Partially implemented.

Implemented:

- `/copy [N]` backend semantics and command tests.
- `TranscriptReaderSurface`.
- Native TUI transcript reader entry and modal input routing.
- Playback coverage for `transcript-reader-modal`.
- Full-session, active-window, and full-session-plus-live-window transcript
  sources.
- Detail/raw reader modes, reader mode title indicators, and reader search.

Still future/deferred:

- reader-local export convenience
- screen-buffer selection/copy
- code-block picker

## Purpose

Define the native TUI contract for reading transcript history and copying
assistant responses.

This design separates three concerns that should not share state:

- structured assistant-response copy through `/copy [N]`
- read-only transcript navigation through a transient reader surface
- editable composer selection and future screen-buffer selection

## Reference Observations

Reference CLIs use different key semantics:

- One CLI treats `/copy` and a hotkey as structured "copy last response"
  operations, and separately exposes raw/copy-friendly transcript rendering for
  terminal-native selection.
- One CLI uses `Ctrl+O` for a transcript pager. It also has a separate
  `Ctrl+E` transcript show-all/collapse action, but that key conflicts with
  common composer line-end behavior and should not be adopted directly.
- One CLI uses `Ctrl+O` for expanding and collapsing tool output across
  expandable components. That model is useful as a component pattern, but the
  global key meaning should not override Loushang's transcript-reader goal.

Loushang should combine the strongest parts:

- structured `/copy [N]` semantics
- a transcript reader entry
- reusable expandable/renderable concepts where useful
- no app-level screen-buffer selection in the first implementation

## Design Goals

- Make `/copy` deterministic and independent of current screen rendering.
- Provide a dedicated read-only transcript reader with pager navigation.
- Preserve composer editing keybindings in normal prompt mode.
- Keep transcript reader state out of composer and selected-range editing.
- Avoid claiming full-history access when only the active transcript window is
  available.
- Leave room for full session transcript loading, raw rendering, export, and
  screen-buffer selection without changing the first API shape.

## Non-Goals

- Do not implement mouse or screen-buffer text selection.
- Do not make `Ctrl+O` expand tool output globally.
- Do not bind `Ctrl+E` to transcript show-all/collapse.
- Do not make `/copy` depend on selected transcript text or terminal scrollback.
- Do not add a code-block picker in the first transcript-reader slice.
- Do not promise complete session history in the first reader if earlier records
  were trimmed or compacted out of the active window.

## User-Facing Semantics

### Structured Copy

`/copy` is equivalent to `/copy 1`.

`/copy N` copies the Nth most recent assistant response, where `1` is the latest
assistant response, `2` is the second-latest, and so on.

Rules:

- `/copy` and `/copy N` copy assistant response text, not rendered terminal
  lines.
- Tool-only turns, empty assistant messages, and unavailable responses are
  skipped.
- Invalid `N` values return a command error with usage guidance.
- If no assistant response is available, the command reports that nothing was
  copied.
- The command uses the platform clipboard backend and reports copy success,
  failure, character count, and backend message.
- The command source should eventually be the session-level assistant response
  history, not the visible transcript window.

### Transcript Reader

`Ctrl+O` or `Ctrl+T` opens a transient transcript reader from normal prompt
mode. `Ctrl+O` remains supported for compatibility; `Ctrl+T` is the discoverable
shortcut shown beside collapsed tool previews.

While the reader is open:

- `Ctrl+O` and `Ctrl+T` close the reader.
- `q`, `Esc`, and `Ctrl+C` close the reader.
- `Up` and `Down` scroll by line.
- `PageUp` and `PageDown` scroll by page.
- `Home` and `End` jump to the start and end.
- `d` toggles compact/detail rendering when the active source supports it.
- `r` toggles rich/raw rendering when the active source supports it.

`Ctrl+E` is intentionally not used by the reader. In normal prompt mode it keeps
the existing composer line-end behavior. Reader-local export shortcuts are not
reserved in this design; they should be designed with the export feature.

The open shortcuts are state-sensitive, not sequence-sensitive. Either shortcut
opens the reader when no reader is active and closes the active reader when one
is open. The
implementation must check current reader state before acting; it must not assume
that alternating presses of one shortcut are the only way the reader opens or
closes.

The reader is a strict modal in the first implementation. While it is open, all
keyboard input is captured by the reader surface. Unrecognized keys are silently
consumed and must not reach the composer, completion menu, pending queue,
command parser, or product shortcuts.

The first reader opens at the transcript tail, equivalent to a pager opened at
the latest message. The first implementation should not persist reader scroll
offset after close. Later versions may add "remember reader position" as an
explicit option.

Closing the reader restores focus to the previously focused surface, normally
the composer. It does not mutate composer text, composer selection, session
transcript records, or terminal scrollback.

## Data Model

Introduce a small source-facing snapshot model:

```python
@dataclass(frozen=True, slots=True)
class TranscriptSnapshot:
    records: tuple[DisplayRecord, ...]
    evicted_prefix_record_count: int = 0
    complete: bool = False
    source_label: str = "Transcript window"
```

`complete=False` means the snapshot is not guaranteed to contain the full
session transcript. This is expected for the first active-window source.

`evicted_prefix_record_count` is advisory UI metadata. The reader should display
a short notice when earlier records are known to be trimmed or compacted.

The source interface should stay narrow:

```python
class TranscriptSource(Protocol):
    def snapshot(self) -> TranscriptSnapshot: ...
    def recent_assistant_texts(self) -> tuple[str, ...]: ...
```

`recent_assistant_texts()` returns assistant response text newest first. It
excludes tool-only turns, empty assistant messages, and unavailable responses.
The `/copy [N]` caller should not apply a second, divergent filter.

`ActiveWindowTranscriptSource` is backed by the bounded native TUI active
window. It includes `NativeCodingTuiState.records` plus the current
`assistant_draft` when streaming is active. It sets `complete=False` because the
active window may have evicted earlier records.

`SessionTranscriptSource` is backed by persisted/session materialized history.
When used alone, it sets `complete=True` because it is presenting the full
available session projection.

`SessionTranscriptSource(..., active_window_state=...)` presents full session
history plus active UI-only suffix records. This is the normal interactive TUI
reader source. It keeps session history as the base, appends active-window
records not already covered by the session projection, and includes the current
assistant draft. When any live suffix is appended, it sets `complete=False` and
labels the snapshot `Full transcript + live window`.

Boundary matrix:

| Source shape | Includes | `complete` | Label |
| --- | --- | --- | --- |
| Active window only | bounded UI records + current assistant draft | `False` | `Transcript window` |
| Session only | full materialized session projection | `True` | `Full transcript` |
| Session + running tool | session projection + active UI-only tool record | `False` | `Full transcript + live window` |
| Session + assistant draft | session projection + current streaming draft | `False` | `Full transcript + live window` |
| Fallback active reader + draft | bounded UI records + draft, no session factory | `False` | `Transcript window` |

The reader holds a reference to `TranscriptSource`, not only a one-time
`TranscriptSnapshot`. The first implementation may freeze the first snapshot for
display, but keeping the source reference preserves a clean path for future
live-tail re-snapshotting.

State boundaries:

```text
Session records and transcript source
  - source of truth for /copy [N]
  - source for reader snapshots

TranscriptReaderSurface
  - strict modal input capture
  - header/footer chrome
  - clipped body
  - scroll offset and render/detail mode

Composer, completion, and pending queue
  - do not receive input while the reader is open
  - are restored without text, selection, or cursor mutation on close

Terminal scrollback
  - may contain previously committed transcript lines
  - is not read by /copy [N]
  - is not cleared by reader open/close
```

## Components

### TranscriptReaderSurface

`TranscriptReaderSurface` is a focused, read-only modal surface.

It owns:

- scroll offset
- render mode: rich/raw
- detail mode: compact/detail
- reader-local input handling
- header/footer chrome
- close intent

It does not own:

- assistant response copy history
- composer selection
- screen-buffer selection
- session persistence
- transcript record mutation

The reader should reuse the existing transcript rendering path wherever
possible. It should not fork markdown, tool, thinking, or assistant-message
styling.

Reuse must happen through a render-to-lines boundary. The content renderer owns
record-to-line generation; the reader owns modal layout, clipping, scrolling,
and reader chrome.

Equivalent interface:

```python
def render_transcript_records(
    records: tuple[DisplayRecord, ...],
    *,
    style: TranscriptRenderStyle,
    width: int,
) -> tuple[RenderLine, ...]: ...
```

If the current renderer is coupled to the main transcript region or terminal
scrollback assumptions, extracting this render-to-lines boundary is a
prerequisite. The reader must not create a second transcript renderer.

### Native Input Routing

Input routing should be mode-first:

1. If the transcript reader is open, route input to it before composer handling.
2. If the reader consumes a close key, close it and request render.
3. If no reader is open and `Ctrl+O` or `Ctrl+T` is pressed, open the reader.
4. Otherwise continue existing completion, selection, queue, and composer
   routing.

This keeps `PageUp` and `PageDown` from moving the composer while the reader is
active.

Because the reader is strict modal, step 1 consumes every keyboard event while
the reader is open. Recognized keys mutate reader state or close the reader.
Unrecognized keys are no-op events that still stop propagation.

### Surface Host

The reader should use the existing surface/modal infrastructure instead of
being hard-wired into the bottom frame. It should capture focus and render above
the normal TUI content.

The reader is transient UI. It must not append navigation rows to terminal
scrollback while the user scrolls.

## Rendering Contract

Default reader layout:

```text
Transcript window
Earlier transcript records were trimmed. Export may include more history.

... rendered transcript lines ...

────────────────────────────────────────────────────────────────
↑/↓ scroll   PgUp/Ctrl+B · PgDn/Ctrl+F page   Home/End jump
Ctrl+O/Ctrl+T/q/Esc close
```

Rules:

- The header and footer are reader chrome, not transcript records.
- The footer separator and hint lines should use dim gray styling so they read as
  chrome rather than transcript content.
- The reader surface should fill the visible terminal height; short transcript
  bodies are padded so the footer remains anchored at the bottom.
- The body is clipped to the available reader height.
- The scroll offset is bounded after resize and source refresh.
- If `complete=False`, the reader must not label itself "Full transcript".
- Raw mode should prefer copy-friendly logical text with minimal decoration.
- Rich mode should preserve current transcript theme behavior.
- Tool outputs that are eligible for the main transcript preview (for example,
  run, test, and search tools) use their preserved expanded source in the reader
  by default. Tools whose bodies are hidden by Product policy, such as read and
  edit operations, remain hidden. Detail mode may expand additional diagnostics
  or thinking blocks later.

The footer should only advertise keys that the current reader implementation
actually handles. `d` detail and `r` raw may remain internal toggles until they
produce a visible rendering difference.

## Export Semantics

`/export` remains the stable command entry for export.

Reader-local export is a future convenience affordance, not part of the first
reader slice. When added, it should delegate to the same export backend and
should not invent a separate export format or persistence path.

If the reader source is incomplete, export should use the best available
session-level export source rather than the reader snapshot when possible. If
only the active window is available, the UI must label the output accordingly.

## Copy Semantics

The reader does not implement `/copy`.

`/copy [N]` uses `TranscriptSource.recent_assistant_texts()` or an equivalent
session-level backend. It should not read the reader's current visible lines,
scroll offset, rich/raw mode, or selected range.

Because the reader is strict modal, typed slash commands are not accepted while
the reader is open. Users close the reader before typing `/copy [N]`.

Future screen-buffer copy selection must be a separate layer. It may copy
rendered screen text, but it must not change `/copy [N]` semantics.

## Lifecycle

Opening:

- Snapshot the current transcript source.
- Initialize scroll offset at the tail.
- Capture focus.
- Request render.

Updating while open:

- The first implementation may keep a frozen snapshot while open.
- A later implementation may support live-tail updates, but it must define
  whether auto-scroll follows the tail or preserves the user's current offset.

Closing:

- Clear reader-local state.
- Restore focus to the previously focused surface, normally the composer.
- Request render.
- Do not clear session transcript records.
- Do not clear terminal scrollback.
- Do not mutate composer text, composer selection, pending queues, or command
  completion state.

## Error Handling

- If no transcript records are available, the reader opens with an empty-state
  message and the same close footer.
- If future reader-local export fails, the reader should display a status/error
  message or delegate to the existing command-result surface.
- If clipboard copy fails for `/copy [N]`, the command reports the backend
  error and leaves reader state untouched.

## Test Obligations

Unit tests:

- `/copy` equals `/copy 1`.
- `/copy 2` copies the second most recent assistant response.
- `/copy N` skips empty or tool-only assistant turns.
- invalid `/copy N` returns usage guidance.
- `TranscriptReaderSurface` clamps scroll offset on small and large heights.
- `q`, `Esc`, `Ctrl+C`, `Ctrl+O`, and `Ctrl+T` close the reader.
- `PageUp`, `PageDown`, `Home`, and `End` update reader scroll state.
- terminal resize clamps reader scroll offset and redraws header/footer.
- unrecognized keys are consumed while the reader is open.
- `Tab` while the reader is open does not open completion or mutate composer
  text.
- reader-local keys do not mutate composer content or cursor.
- `Ctrl+E` remains composer line-end in normal prompt mode.
- repeated `d` and `r` toggles are stable and bounded.

Playback tests:

- `Ctrl+O` and `Ctrl+T` each open the reader and the footer is visible.
- `PageUp` in the reader scrolls transcript content rather than composer text.
- closing the reader restores focus to the previously focused surface, normally
  the composer, without altering composer text, selection, or cursor position.
- a trimmed active window shows an incomplete-history notice.
- raw/rich toggle updates reader output without affecting main transcript
  rendering.
- `/copy 2` succeeds after opening and closing the reader, proving structured
  copy and reader state are independent.
- `Ctrl+C` closes the reader and the next input is routed normally.

Regression tests:

- completion menu selection and reader input routing do not conflict.
- composer text selection is cleared or preserved only by existing composer
  rules; opening/closing the reader does not synthesize edit operations.
- active terminal scrollback is not wiped by reader open/close.
- a reader snapshot remains valid if the active transcript window is trimmed
  after the reader opens.

## Migration Path

1. Add `/copy [N]` backend support and tests.
2. Add `TranscriptSnapshot` and active-window `TranscriptSource`.
3. Add `TranscriptReaderSurface` with frozen active-window snapshots.
4. Wire `Ctrl+O`, `Ctrl+T`, and reader-local input routing.
5. Add playback coverage.
6. Later: session-backed full transcript source.
7. Later: reader-local export shortcut and raw/detail rendering refinements.
8. Later: screen-buffer selection/copy as a separate design.
