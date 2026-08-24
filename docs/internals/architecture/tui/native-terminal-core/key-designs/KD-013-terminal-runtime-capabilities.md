# KD-013: Terminal Runtime Capabilities

## Purpose

Define the runtime layer that lets `loushang.tui` adapt to different terminal
environments without leaking terminal-specific rules into product UI code.

The target environments include local terminals, tmux and screen, SSH sessions,
Windows Terminal, macOS terminal apps, Linux terminal apps, and terminals with
optional keyboard or image protocols.

This design is a refactor boundary. It does not require every advanced terminal
feature to be implemented at once, but it defines where detection, negotiation,
capability decisions, and cleanup must live.

## Design Goals

- Centralize terminal environment detection in a pure, testable layer.
- Expose one immutable capability snapshot to rendering, input, image, and
  theme code.
- Separate static environment hints from active runtime negotiation.
- Support multiple keyboard protocols without spreading raw escape handling
  across the application.
- Make startup and shutdown symmetrical so enabled terminal modes are disabled
  reliably.
- Keep coding product behavior independent from terminal protocol details.

## Non-Goals

- Do not make `loushang-coding` decide whether Kitty, iTerm2, tmux, or
  modifyOtherKeys is active.
- Do not make image rendering depend on ad hoc environment checks.
- Do not treat arbitrary sleeps as a keyboard correctness mechanism.
- Do not assume SSH, Linux, macOS, or Windows alone is enough to determine
  capabilities. Terminal app and multiplexer state matter more.
- Do not require optional tools or protocol support for basic TUI operation.

## Proposed Modules

### TerminalEnvironment

`TerminalEnvironment` is a normalized read-only view of process environment and
platform hints.

It should be constructed from:

- `os.environ`
- platform name
- `TERM`
- `TERM_PROGRAM`
- terminal-specific environment variables
- SSH-related variables
- tmux and screen variables
- Windows Terminal variables

It should not write to the terminal. It is only input to pure detection.

Suggested fields:

- `term`
- `term_program`
- `colorterm`
- `inside_tmux`
- `inside_screen`
- `inside_ssh`
- `is_windows`
- `is_macos`
- `is_linux`
- `is_wsl`
- `has_kitty_env`
- `has_iterm_env`
- `has_wezterm_env`
- `has_ghostty_env`
- `has_windows_terminal_env`
- `raw_env`

### TerminalCapabilityDetector

`TerminalCapabilityDetector` maps `TerminalEnvironment` to a conservative
`TerminalCapabilities` snapshot.

This must be a pure function. It should be easy to test with synthetic env
dicts and without a real terminal.

Suggested capability fields:

- `color_depth`: `basic`, `ansi256`, or `truecolor`
- `hyperlinks`: `bool`
- `image_protocol`: `none`, `kitty`, or `iterm2`
- `keyboard_protocol_strategy`: `kitty_then_modify_other_keys`, `modify_other_keys`,
  or `legacy`
- `query_cell_size`: `bool`
- `enable_bracketed_paste`: `bool`
- `enable_focus_events`: `bool`
- `mouse_selection_owner`: `terminal` or `application`
- `enable_mouse`: legacy compatibility input; `true` resolves ownership to
  `application`
- `alternate_screen`: `bool`
- `windows_vt_input`: `bool`
- `termux_session`: `bool`
- `apple_terminal_normalization`: `bool`
- `is_multiplexer`: `bool`
- `capability_sources`: human-readable reasons for diagnostics

### KeyboardProtocolController

`KeyboardProtocolController` owns protocol negotiation state.

Startup policy:

1. If Kitty keyboard protocol is allowed, send Kitty query `ESC[?u`.
2. If a Kitty response is observed, mark Kitty active and enable report flags
   with `ESC[>7u`.
3. If no Kitty response arrives before the fallback deadline, enable xterm
   modifyOtherKeys mode 2 with `ESC[>4;2m` when allowed.
4. If neither protocol is active, keep legacy parsing.

Shutdown policy:

1. Disable only protocols that were actually enabled.
2. Drain pending input after disabling protocol modes.
3. Do not forward protocol response fragments to application input.

The controller does not parse every key. It only coordinates protocol state and
consumes terminal control events produced by `InputReader`.

`InputReader` should remain the only escape sequence assembler. The controller
must not implement a second parser for CSI, OSC, DCS, APC, SS3, paste, mouse, or
Kitty key sequences.

### TerminalSession

`TerminalSession` owns terminal lifecycle. It is the successor boundary around
the current `TerminalInputMode` behavior, not a parallel lifecycle that should
coexist indefinitely.

It coordinates:

- environment snapshot
- capability detection
- raw or cbreak mode
- bracketed paste enable and disable
- focus event enable and disable
- keyboard protocol negotiation
- cell size query
- terminal write cleanup
- input drain on exit

P0 should keep the existing native loop integration shape by making
`TerminalSession` usable as an `AbstractContextManager`. The default
`mode_factory(stdin, stdout)` can then return a `TerminalSession`, while tests
that inject a custom context manager remain compatible.

It should expose:

- `environment`
- `capabilities`
- `keyboard_protocol_state`
- `cell_size`

`native_loop` should own the `TerminalSession` because the session spans input
mode, output capability, and protocol negotiation. `TuiRuntime` should stay
focused on rendering and terminal writes. Renderers, theme, Markdown, and image
adapters consume the session capability snapshot through explicit parameters or
application state, not by probing environment variables themselves.

Internally, `TerminalSession` consumes a `NativeTerminalPlatform` composed from
the small `NativeConsoleMode` and `NativeModifierKeys` ports. The default path
selects those ports lazily from the host platform. `platform_adapter=` remains a
compatibility input only: it is converted once at the session boundary and its
platform-named methods are not called from the session lifecycle itself. An
explicit `native_platform=` takes precedence for deterministic tests and custom
composition.

### InputReader

`InputReader` remains the single owner of input sequence assembly.

It must understand the sequence families listed below and should be parameterized
by the active keyboard protocol state when protocol-specific decoding differs.

`InputReader.feed(data)` should evolve from returning a flat tuple of events to
returning an `InputBatch`:

```python
@dataclass(frozen=True, slots=True)
class InputBatch:
    app_events: tuple[InputEvent, ...]
    control_events: tuple[InputEvent, ...]
    has_pending: bool = False
```

`app_events` are safe to route to product input handlers:

- text
- key press, repeat, and release
- paste
- mouse
- focus
- resize

`control_events` are internal terminal/runtime responses:

- Kitty keyboard protocol responses
- cell size responses
- OSC responses or payloads that are not product text
- DCS responses or payloads that are not product text
- APC responses or payloads that are not product text

The native loop should route batches in this order:

```text
raw chunk
  -> InputReader.feed(raw chunk)
  -> KeyboardProtocolController.consume(batch.control_events)
  -> TerminalSession.consume(batch.control_events)
  -> NativeInputRouter.handle(batch.app_events)
```

This keeps terminal control responses consumed before product routing while user
input remains normalized and application-facing.

It must not be duplicated by a second parser in the native app loop.

### Input Idle Flush

Standalone Escape disambiguation belongs with the input assembly boundary.

`InputReader` should expose whether it has a pending incomplete sequence and
should expose a targeted pending flush operation. The async native loop or a
small input scheduler owns the idle deadline because it already waits for input,
render wakeups, and active task completion.

The raw read layer must not use an escape-specific timeout to join sequence
tails. It should only preserve byte and UTF-8 character boundaries. This removes
the current overlap between transport reads and `InputReader` sequence
assembly.

The idle deadline is used only when `InputReader.has_pending` is true. It should
not delay ordinary keys, text, paste, mouse, or complete escape sequences.

### TerminalImageAdapter

Image support should consume `TerminalCapabilities.image_protocol`.

The adapter should:

- emit Kitty image sequences only when the capability snapshot says `kitty`
- emit iTerm2 image sequences only when the snapshot says `iterm2`
- return text fallback when image support is `none`
- treat tmux and screen as `none` unless explicit passthrough support is added
  later

Existing `detect_image_protocol(env)` can remain as a compatibility API during
P0, but its implementation should delegate to `TerminalCapabilityDetector`.

### Theme And Markdown

Theme and Markdown rendering should consume the same capability snapshot for:

- truecolor decisions
- hyperlink decisions
- terminal cell size when known

They should not run separate environment probes.

## Detection Policy

The detector must be conservative. A capability is enabled only when the
environment strongly indicates support or when runtime negotiation confirms it.

Initial static policy:

| Environment Hint | Policy |
| --- | --- |
| `TMUX` or `STY` | disable images and hyperlinks; truecolor only from explicit color hints |
| `KITTY_WINDOW_ID` or `TERM_PROGRAM=kitty` | Kitty images, truecolor, hyperlinks |
| `GHOSTTY_RESOURCES_DIR` or Ghostty program hint | Kitty images, truecolor, hyperlinks |
| `WEZTERM_PANE` or WezTerm program hint | Kitty images, truecolor, hyperlinks |
| `ITERM_SESSION_ID` or `TERM_PROGRAM=iTerm.app` | iTerm2 images, truecolor, hyperlinks |
| `TERM_PROGRAM=vscode` | truecolor and hyperlinks; no images |
| `COLORTERM=truecolor` | truecolor |
| `WT_SESSION` | truecolor; no images by default |
| Termux session hints | no special resize assumptions until tested |
| unknown terminal | no images, no hyperlinks, color from `TERM` and `COLORTERM` |

Remote SSH should not automatically disable capabilities. SSH often forwards the
client terminal environment. It should only make diagnostics more explicit.

tmux and screen should remain conservative until explicit passthrough handling is
implemented and tested.

## Sequence Ownership

Terminal sequence vocabulary belongs in the glossary. Runtime ownership is:

- CSI: parsed by `InputReader`; emitted by `TerminalSession` for known mode
  setup and teardown.
- OSC: parsed by `InputReader` for completeness; emitted only by approved
  rendering features such as hyperlinks.
- DCS: parsed by `InputReader` for completeness; emitted only by explicit
  protocol adapters.
- APC: parsed by `InputReader` for completeness; not interpreted by product UI.
- SS3: parsed by `InputReader` for legacy function and arrow keys.

Product code must receive normalized events and capability booleans, not raw
terminal control sequences.

Mouse handling has three separate owners:

- `TerminalRuntimeCapabilities.mouse_selection_owner` expresses product-neutral
  session policy. The default is `terminal`, so ordinary host text selection is
  preserved.
- `TerminalSession` maps `application` ownership to DECSET setup and teardown:
  button-event tracking (`1002`) plus SGR coordinates (`1006`). It never enables
  all-motion tracking (`1003`) by default.
- `NativeConsoleMode` maps the neutral `preserve_native_selection` intent onto
  host APIs. On Win32 this means preserving the original Quick Edit flag for
  terminal ownership and clearing it only for application ownership.

`InputReader` continues to parse mouse sequences independently of this policy.
Product surfaces receive normalized mouse events and do not emit or interpret
DECSET sequences themselves. The old `enable_mouse=True` flag remains a
compatibility input and resolves to application ownership.

Synchronized update mode is owned by the terminal writer/render loop. KD-013 does
not move that responsibility into input session code.

## Runtime Data Flow

```text
process env + platform
        |
        v
TerminalEnvironment
        |
        v
TerminalCapabilityDetector
        |
        v
TerminalCapabilities --------------+
        |                           |
        v                           v
TerminalSession              renderer / theme / image
        |
        v
KeyboardProtocolController
        |
        v
InputReader -> InputBatch
        |          |
        |          +-> control_events -> TerminalSession / KeyboardProtocolController
        |
        +-> app_events -> router -> product UI
```

## Startup Contract

1. Build `TerminalEnvironment`.
2. Detect static `TerminalCapabilities`.
3. Enter terminal input mode.
4. Enable bracketed paste and focus events when allowed.
5. Enable platform runtime hooks that must happen after raw mode, such as
   Windows VT input.
6. Start keyboard protocol negotiation.
7. Query cell size only when useful and safe.
8. Preserve host text selection by default. Enable application mouse tracking
   only when `mouse_selection_owner=application` (or the legacy compatibility
   flag requests it).
9. Start the render loop after the terminal session is ready.

Startup must not block basic UI rendering indefinitely. Runtime negotiation
deadlines should be short and bounded.

## Shutdown Contract

1. Stop routing application input.
2. Disable active keyboard protocol modes.
3. Disable focus events and bracketed paste.
4. Drain pending protocol tail input.
5. Disable active platform runtime hooks such as Windows VT input.
6. Restore terminal input mode.
7. Clear managed viewport state as needed.
8. Return shell cursor to a clean line.

Shutdown must be idempotent. Calling cleanup twice should not emit conflicting
terminal state.

## Diagnostics

The runtime should make capabilities inspectable for debugging and examples.

Useful diagnostics:

- detected terminal program
- multiplexer status
- color depth
- hyperlink support
- image protocol
- keyboard protocol state
- cell size status
- mouse mode status
- effective mouse selection owner
- Windows VT input status
- Termux or Apple Terminal special handling status
- reasons that enabled or disabled a capability

Diagnostics should be printable without requiring a live TUI session.

## Migration Slices

### P0: Pure Capability Detection

- Add `TerminalEnvironment`.
- Add pure capability detection tests.
- Route image protocol detection through the new capability snapshot.
- Keep `detect_image_protocol(env)` as a compatibility wrapper.
- Preserve existing public behavior.

### P0: InputBatch Boundary

- Add `InputBatch` to separate app events from control events.
- Keep `InputReader` as the only sequence assembler.
- Route Kitty protocol, cell size, OSC, DCS, and APC responses through
  `control_events`.
- Ensure control events are consumed before `NativeInputRouter`.

### P0: Input Idle Flush Boundary

- Remove escape-tail joining from raw read helpers.
- Expose pending state and pending flush from `InputReader`.
- Let the native loop or input scheduler own the idle deadline.
- Keep the idle deadline scoped to pending incomplete escape sequences only.

### P0: Terminal Session Lifecycle

- Introduce `TerminalSession` around existing `TerminalInputMode` behavior.
- Preserve the `mode_factory(stdin, stdout) -> context manager` integration
  point in the first implementation slice.
- Make cleanup order explicit and idempotent.

### P0: Keyboard Negotiation Boundary

- Move Kitty query and modifyOtherKeys fallback into
  `KeyboardProtocolController`.
- Consume `InputBatch.control_events` before product routing.
- Ensure protocol responses are consumed before product routing.

### P1: Cell Size And Rendering Capabilities

- Add a single cell size query path.
- Feed cell size and capability snapshot to Markdown, theme, and image paths.
- Avoid separate environment checks in renderers.

### P1: Multiplexer And Remote Policy

- Add explicit tmux and screen policy tests.
- Add SSH diagnostic visibility.
- Keep image passthrough out of default behavior until separately designed.
- Add Windows VT input detection hooks without requiring Windows-only code paths
  to run on non-Windows tests.

### P1: Platform Boundaries

- Put Windows VT input enable/restore behind `NativeConsoleMode`; retain
  `TerminalPlatformAdapter` only as a compatibility facade and injection bridge.
- Normalize Apple Terminal Shift+Enter before `InputReader` parsing, using an
  ApplicationServices/Quartz Shift probe when available.
- Treat Termux height-only resize as keyboard chrome churn, not a mandatory
  full terminal repaint; width changes still repaint.

### P2: Advanced Protocol Expansion

- Add optional support for richer Kitty keyboard flags.
- Add optional tmux passthrough for images or hyperlinks if there is a tested
  user setting.
- Add optional cursor style and alternate screen policies.
- Add optional Apple Terminal input normalization if a tested implementation is
  available.
- Add optional Termux resize policy if terminal behavior requires it.
- Add terminal playback fixtures for negotiation sequences.

## Test Obligations

- static env detection for Kitty, Ghostty, WezTerm, iTerm2, VSCode, Windows
  Terminal, tmux, screen, SSH, and unknown terminals
- tmux and screen disable images by default
- truecolor follows `COLORTERM=truecolor` and `WT_SESSION`
- Kitty response switches protocol state to active Kitty and enables flags
- absent Kitty response falls back to modifyOtherKeys when allowed
- shutdown disables only modes that were enabled
- `InputReader.feed()` separates app events from control events
- protocol responses never appear in composer text or product router input
- split Kitty response chunks become one control event
- split `ESC` then `[A` becomes one `up` app event
- standalone `ESC` becomes an app event only after the idle deadline
- bracketed paste remains an atomic app event even when split across chunks
- fake-clock tests cover pending idle flush and Kitty fallback deadlines
- cleanup can be called twice without duplicated or conflicting terminal writes
- image adapter falls back to text when `image_protocol=none`
- Markdown and theme receive the same capability snapshot as the runtime
- cell size responses update runtime state without entering scrollback
- terminal-native text selection is the default mouse owner
- application ownership enables `1002` and `1006` and restores both on exit
- legacy `enable_mouse=True` resolves to application ownership
- Win32 preserves Quick Edit for terminal ownership and restores the original
  console mode on exit
- Windows Terminal, Termux, and Apple Terminal hints are visible in diagnostics
- Windows VT input enable/restore is idempotent and diagnostic-visible
- Apple Terminal Return becomes `shift+enter` only when the Shift probe is true
- Termux height-only resize does not clear scrollback; Termux width resize still
  performs resize repaint

## Open Questions

- Should users be able to override image and hyperlink support from config?
- Should tmux passthrough be opt-in per session or global config?
- Should SSH diagnostics warn only when terminal hints are unknown?
- Should keyboard protocol state be exposed in the status/debug surface?
- Should `InputReader.feed()` switch directly to `InputBatch`, or should P0 add
  a temporary compatibility method while callers migrate?
- Should a future dynamic per-surface ownership switch be added, and if so what
  focus transition owns its balanced setup and teardown?
