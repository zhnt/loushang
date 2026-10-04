# TUI Mouse, Detail Disclosure, and Transcript Shortcuts

Status: reviewed from interaction, architecture, and portability perspectives
on 2026-09-27; findings incorporated below.

## Outcome

An interactive conversation screen can expand one tool activity in place with
mouse or keyboard, select and copy visible transcript text while it owns mouse
input, and use Ctrl+T for the full transcript and Ctrl+O for the latest completed
assistant answer. The keyboard path works when no mouse event reaches the app.
The generic `loushang.tui` runner keeps its existing terminal-owned selection
default; the conversation profile opts into the new policy only after its copy
path is ready.

## Existing boundaries

- `TerminalSession` owns 1000/1002/1006 setup and cleanup, with
  `mouse_selection_owner=terminal|application` and terminal ownership as its
  default. `InputReader` parses SGR and X10 mouse sequences but leaves the SGR
  button bit field uninterpreted. `SurfaceHost` translates coordinates for the
  focused surface, not arbitrary hit targets.
- `TranscriptRegion` has retained segmented rendering, a presentation hook,
  and a bounded viewport, but its `RenderResult` has only lines and cursor.
  Product state keeps tool call IDs while `ToolExecutionRecord` does not.
- `TranscriptReaderSurface` supports whole-view detail/raw modes. Both Ctrl+O
  and Ctrl+T currently open or close it. `copy_to_clipboard` tries host commands
  synchronously and does not report remote clipboard delivery.

## User contract

| Context | Input | Action |
| --- | --- | --- |
| Main conversation | Ctrl+T | Open full transcript reader. |
| Reader | Ctrl+T, q, Esc | Close reader; Esc first clears search or selection. |
| Conversation or reader | Ctrl+O | Copy latest completed nonempty assistant answer. Never copy a streaming draft or tool output as the answer. |
| Conversation or reader | Ctrl+C with transcript selection | Copy selected transcript text. Without selection, retain current interrupt/cancel behavior. |
| Main conversation | F4, then Up/Down and Enter/Space | Focus the first visible detail control, cycle visible controls, and toggle one activity. Focus is visibly marked. Escape returns focus to composer. No visible controls leaves F4 inert. |
| Visible detail control | Stationary left click released on the same control | Toggle that activity. A drag that begins there becomes selection; no toggle on press. |
| Application-owned transcript | Left drag and Ctrl+C | Highlight displayed text and copy it. Synthetic control labels do not enter copied text. Copy success and failure are explicit. |
| Terminal-owned transcript | Mouse drag | Host terminal or tmux owns text selection. Detail shortcuts remain available. |

When no answer exists, Ctrl+O reports that fact without changing the draft or
selection. Copy work must not block the input/render loop. The old Ctrl+O
transcript binding is a deliberate default-key migration: user-configured
`tui.transcript.open` bindings still work, and the default moves to Ctrl+T.
Add configurable `tui.transcript.copyLastAnswer` (Ctrl+O) and
`tui.transcript.focusDetail` (F4). An explicit user binding takes precedence
over another action's default; two explicit claims remain a reported conflict.
The reader resolves the same keymap instead of hardcoding Ctrl+O/Ctrl+T, and
its close hint reflects the resolved binding. Hints, guide text, and playback
expectations change with the defaults.

In the main screen, input ownership order is modal surface, transcript
selection, detail focus, composer selection/completion, global shortcuts, then
editor input. Escape first clears transcript selection or detail focus without
interrupting work or clearing the composer. Ctrl+C copies a nonempty transcript
selection first, then resumes its existing cancellation path when selection is
cleared. A failed copy retains selection and Escape releases it. Opening a
modal, typing into the composer, a new selection, terminal focus loss, and
terminal handoff cancel a pending pointer gesture. The reader keeps its
existing `d` whole-view detail and `r` raw modes; per-tool disclosure controls
belong to the main conversation only. Reader Escape returns to reader
navigation before closing the modal. General keyboard text selection is not
part of this delivery; Ctrl+O and terminal-owned selection remain available.

## Mouse policy and adapters

Resolve four facts independently: desired pointer policy (`auto`, `terminal`,
`application`), containing tmux pane's mouse option (`on`, `off`, `unknown`, or
`absent`), availability of a copy route to the terminal user's clipboard, and
whether the terminal actually sends events (`observed` only after receipt).
Silence is not proof that a terminal refused mouse reporting.

| Policy and environment | Effective owner | Behavior |
| --- | --- | --- |
| `terminal` | terminal | No mouse report request; keyboard details and transcript remain. |
| `auto` + tmux explicitly off | terminal | Preserve terminal/tmux copy path; never request app capture. |
| `auto` + tmux on, or direct terminal, with a usable user-clipboard route | application | Request 1000/1002/1006; use app click and app transcript selection. |
| `auto` + tmux on, or direct terminal, without a user-clipboard route, including direct SSH and headless Linux | application | Request 1000/1002/1006 so Show Detail can be clicked. Copy reports that the clipboard is unavailable; the explicit `terminal` policy restores native selection. |
| `auto` + inconclusive tmux probe | terminal | Preserve copy and expose an explicit application override. |
| `application` | application | Request capture even when probe is inconclusive; diagnostics explain an explicit tmux-off conflict. |

`TerminalMouseEnvironment` is a small immutable result supplied to a pure
resolver. A `MouseEnvironmentProbe` protocol has a neutral implementation and
an optional tmux implementation. The containing pane is queried with argv
(`tmux display-message -p -t <TMUX_PANE> '#{mouse}'`), not a shell command.
Selection of the tmux adapter is lazy and based on the environment; no tmux
subprocess or import occurs outside tmux. The probe has a bounded wait and
does not change tmux options. The native Windows terminal backend remains the
sole owner of console mode / Quick Edit handling. POSIX and Windows transports
share the neutral SGR event and policy model rather than product `if/else`
branches. Re-entry after a terminal handoff refreshes the policy. If Win32 VT
input cannot be activated, `auto` falls back to terminal ownership even when
a clipboard route exists. An explicit `application` request with tmux off or
without a clipboard route remains possible, but diagnostics state that copy
or click may fail; `auto` never takes that risk silently.

The protocol requests button reporting (1000), button and drag reporting
(1002), and SGR coordinates (1006). It does not request all-motion hover
(1003). Input normalization
decodes the SGR button field into button, press/release/drag/wheel, and
Ctrl/Alt/Shift flags, with zero-based columns and rows. Preserve the existing
`InputEvent` fields for compatibility while adding a typed mouse view; consumers
stop interpreting raw button codes. Unknown terminal sequences remain inert.
`TerminalSession` always restores active modes on exit or failed entry. Mouse
diagnostics expose desired mode, resolved owner, tmux observation, capture
request, and whether any event was observed. It never claims to detect a
terminal permission prompt or infer its answer from silence.

## Hit testing, ownership, and performance

Rendering stores control row positions in the committed transcript segment
and clips that map to the visible viewport. The runner translates physical
terminal rows through the committed render loop's viewport top before main
transcript hit testing or text selection. Modal input
goes through `SurfaceHost`; the reader receives translated mouse coordinates.
On release, the main screen checks the current record identity and revision.
The tool identity map rebuilds only after a transcript revision; pointer
movement uses visible rows. Resize, modal entry, focus loss, and a new press
cancel pending gestures.

Tool disclosure is keyed by the existing tool call ID. Rendering stays
product-neutral: the product attaches an optional presentation identity to a
tool record and owns the expanded-ID set; the generic renderer emits either
compact or expanded lines and a synthetic `Show Detail` / `Show Less` control
where full command/output exists. The synthetic label is outside searchable
and copied source text. Expansion does not mutate persisted transcript facts.
Reflow, trimming, compaction, and resume remove invisible/stale focus targets
without transferring expansion to another tool. Mouse and keyboard dispatch
produce the same toggle intent. One tool's toggle invalidates the composed
segment and that record's render cache entry, not the global style token or
unrelated record/streaming caches. The main transcript pins the activated
control row in a bounded viewing window while detail focus and record revision
remain unchanged. The reader remains the route to the complete content of a
detail larger than one viewport.

Application-owned selection uses final displayed plain-text rows pinned at
gesture start; it clears when the displayed transcript changes. Cell slicing
uses grapheme widths;
presentation prefixes are copied if visibly selected, while synthetic controls
are omitted. Dragging across wrapped lines and tool records retains displayed
order. A selection copies on release or Ctrl+C. Clipboard writes use an
injected asynchronous `TextClipboardWriter` port with a declared destination:
terminal user's machine or remote host. SSH `auto` enables pointer input
independently of copying and accepts only a copy route to the terminal user's
machine; remote host command success does not satisfy it.
Host-specific writers (Linux Wayland/X11, macOS, Windows) are selected lazily
from a registry; a terminal OSC 52 writer is an optional bounded route for
SSH/tmux. A write result distinguishes confirmed, sent-without-ack, and
failed; only confirmed delivery says "Copied". OSC 52 without acknowledgment
is an explicit opt-in route and reports "Sent to terminal". Failure preserves
selection. No platform module is imported on an unrelated host.

One session-owned copy coordinator serializes requests in submission order,
snapshots answer or selection text at dispatch, and suppresses stale feedback
after a newer request. Terminal OSC 52 writes pass through the terminal owner
and are cancelled on handoff/exit; a late worker cannot write to an unowned
terminal. Copy processing never blocks keyboard echo or streaming frames.

## Delivery slices

1. Add normalized pointer events, policy resolver/probe, diagnostics, and
   rollback tests; keep conversation pointer capture opt-in while selection is
   incomplete.
2. Add visible hit regions, per-tool detail state, keyboard focus/toggle and
   mouse click/toggle. Migrate Ctrl+T and Ctrl+O with nonblocking copy and
   context precedence.
3. Add application transcript selection and clipboard adapters; then make
   conversation `auto` the default where app capture is usable. Keep generic
   `TuiRunner` terminal-owned by default.
4. Add one runnable example under `examples/` with compact and expanded tools,
   keyboard and mouse instructions, a status area, and a fake answer. No unit
   tests are added for the example script itself.

## Acceptance

- Focused interaction tests verify press/drag/release, focus and Enter/Space,
  Ctrl+T open/close, Ctrl+O answer copy, selected-text precedence, and copy
  failure without interrupt or draft loss.
- Reflow tests cover bounded anchor height, reader selection invalidation
  after scrolling, and stale control press suppression.
- Adapter tests inject tmux on/off/unknown and Linux/macOS/Windows/WSL/Termux/
  SSH clipboard routes, headless/no-writer, Unicode encoding and Win32
  VT-input-failure cases without importing unrelated backends. Terminal
  lifecycle tests verify capture cleanup on normal, exception, and handoff
  paths, including Win32 Quick Edit restoration.
- Slow first copy followed by a second preserves request order and suppresses
  stale feedback. Terminal ownership rejects a late OSC 52 write.
- A long expanded tool with following messages remains within the viewport
  budget. Expanding one tool reuses unrelated cached record and draft
  segments. Focus loss and a missing mouse release cannot trigger a stale click.
- Configured Ctrl+O transcript override wins over the default copy binding;
  failed copy, Escape, then Ctrl+C cancels an active turn without draft loss.
- The manual example supports direct Linux and macOS terminals, SSH,
  tmux mouse on/off, Windows Terminal/ConPTY, and forced terminal/application
  policies. Linux pseudo-terminal startup, reader navigation, and exit were
  exercised; host-dependent scenarios still need runs on those hosts.

## Review disposition

The three reviewers found no P0 issue. Interaction review required explicit
binding precedence, selection Escape behavior, F4 navigation, and reader mode
ownership. Architecture review required displayed-text offset mapping, local
cache invalidation, and a viewport anchor. Portability review required a
clipboard-route gate, SSH destination semantics, copy ordering and terminal
lifetime, focus-loss cancellation, and Win32 VT failure fallback. Each is
specified above and must be verified in the matching acceptance cases.

Post-implementation reviews found viewport overrun, stale selection mappings,
control-origin drag behavior, invisible reader copy feedback, and Windows/WSL
clipboard encoding. These were fixed with focused regression tests.
