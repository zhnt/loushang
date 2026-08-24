# Testing Strategy

## Purpose

The native terminal core must be tested at the render-operation level. Manual
testing remains useful, but flicker, duplicated transcript, resize instability,
and cursor mapping need deterministic tests.

## Test Layers

### 1. Pure Renderable Tests

Render UI parts with fixed constraints and assert logical lines, cursor markers,
and overflow behavior.

Examples:

- composer soft wrap and explicit newline
- multi-line paste insertion and paste-marker editing
- status truncation
- select list navigation
- markdown wrapping
- tool execution record rendering

### 2. Render Loop Tests

Drive RenderLoop with previous rendered lines, current logical lines, terminal
size, and viewport tracking. Assert terminal operations, changed line ranges, and
recovery repaint reasons.

Examples:

- append update
- changed bottom-frame line update
- first changed line above viewport triggers recovery repaint
- width resize triggers full recompose plus resize repaint
- height resize triggers full recompose plus resize repaint by default
- resize repaint emits clear scrollback by default
- disabled clear-scrollback policy is observable on resize
- explicit clear-scrollback policy is observable for recovery repaint when enabled
- user scrollback movement invalidates stale row mapping
- external stdout forces repaint recovery instead of stale diff
- render tick coalescing preserves responsive input
- failed flush does not update previous rendered lines

### 3. Terminal Playback Tests

Use the playback harness to script input, product events, streaming chunks,
surface events, and resize events. Assert both logical transcript and terminal
operations.

Playback frames are also reusable terminal-operation traces: a successful trace
can be replayed against a fresh FakeTerminal without invoking the renderer.
When native scrollback is preserved, the trace contract rejects erase-display
operations (`clear_screen` and `clear_from_cursor`), because emulator history
behavior for those operations is not portable. JSONL artifacts include the
scrollback-size delta and safety result; `--include-frames` also includes the
concrete operation payloads and serialized output. FakeTerminal keeps scrollback in immutable
shared chunks so long-session replay remains append-linear while old frame
snapshots stay stable.

Examples:

- submit prompt, stream assistant, commit worked divider
- resize during streaming
- resize with clear scrollback disabled
- user scrolls up while streaming continues
- paste multi-line content without submitting
- paste content with terminal control sequences without executing it
- queue follow-up while running
- steer while running
- Esc with active approval surface
- stacked surfaces restore focus in order
- constrained-height bottom frame follows priority rules
- concise error without traceback
- composer selection stress with wide text, paste markers, kill/yank, undo,
  completion refresh, and selection key priority
- product-composed interaction with long transcript, running queue state,
  settings search, completion, and composer selection in one playback

Composer selection playback should be run directly when changing composer input,
selection, paste marker, completion, keybinding, or render-highlight behavior:

```bash
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py composer-selection-stress --artifacts /tmp/loushang-selection-playback --include-frames
```

The trace should include `composer-selection-stress` as a passing scenario. Use
the generated JSONL artifact when diagnosing selection regressions because the
final screen cannot show transient selected ranges after replacement or undo.

Product-composed playback should be run when changing bottom-frame composition,
pending queue state, transcript viewport behavior, settings search, completion,
or cross-feature input routing:

```bash
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py product-composed-interaction --artifacts /tmp/loushang-product-playback --include-frames
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py product-streaming-control-flow --artifacts /tmp/loushang-product-streaming-playback --include-frames
```

The trace should include `product-composed-interaction` and
`product-streaming-control-flow` as passing scenarios. These scenarios protect
cross-feature regressions that are easy to miss when composer, surface,
lifecycle, resize, streaming transcript, and pending queue tests are run only in
isolation. When a scenario fails, inspect the JSONL trace and screen artifact;
review-oriented failures should preserve enough last frames to explain the
visible state at the failure point.

### 4. Boundary Tests

Import and integration tests enforce module boundaries.

Examples:

- importing `loushang.tui` does not import coding modules
- raw runtime imports do not require prompt_toolkit, Rich, or Pygments
- extensions cannot receive TerminalPort
- extensions receive normalized input events rather than raw terminal bytes
- v1 prompt_toolkit modules are not on the new public API path

### 5. Native Terminal Transport Tests

Keep terminal evidence in four separate layers. A test may depend inward on a
more deterministic layer, but must not use a host transport as the oracle for
portable rendering or input semantics.

| Layer | Owner and evidence | Local entrypoint |
| --- | --- | --- |
| FakeTerminal/playback | portable input, rendering, control-sequence lifecycle, and screen state | `make test-tui-input-playback` |
| simulated platform backend | pure Python Windows, POSIX, and Darwin adapter behavior with injected OS modules | `uv run python scripts/run_tui_platform_tests.py current -q` |
| native PTY/ConPTY transport | real process, pipe, resize, Unicode, platform query boundary, and teardown behavior | `make test-tui-native` |
| live terminal smoke | emulator selection, IME, clipboard, and user-visible restoration | manual checklist below |

`--skip-host-runtime` skips the native PTY/ConPTY layer but not simulated
platform units or FakeTerminal/playback. Live POSIX `termios`/PTY tests are
explicitly skipped on Windows; injected POSIX backend units remain portable and
continue to run there. Conversely, Windows backend units use fake console and
kernel APIs and do not require a real Windows console.

Run the same test-only terminal driver contract over a POSIX PTY on Linux and
ConPTY on Windows. These tests prove structured argv, cwd/environment handling,
Unicode and VT transport, resize, exit status, large output drain, terminal
query boundaries, bounded timeout, process-tree termination, and idempotent
cleanup. They do not claim exact final screen state or exact ConPTY byte counts;
FakeTerminal/playback owns screen evidence and ConPTY exposes a reconstructed
renderer stream rather than transparent application stdout.

The real CLI contract follows the same split. Shared assertions cover launch,
`/quit`, exit status, bracketed-paste/focus mode pairing, and reader cleanup.
The POSIX-only contract observes raw cursor-hide and synchronized-output
lifecycle sequences. The Windows-only contract checks ConPTY's renderer-visible
final cursor restoration; it does not require ConHost to replay every
application control sequence byte-for-byte.

Terminal query evidence is deliberately split. The portable responder unit
contract proves incremental cross-chunk recognition, configured replies, and
fail-closed unknown blocking queries. POSIX PTY additionally proves the full
application DSR -> responder -> input loop because the master observes raw
application output. ConPTY mediates application output through ConHost before
the client pipe, so its Windows-only native contract proves that boundary and
does not pretend an application DSR was observable. Product probes on Windows
must retain bounded fallback behavior.

The Windows backend calls the system ConPTY API through a test-only `ctypes`
wrapper, explicitly selects ConPTY, and owns its pipes, HPCON, process handle,
and lifecycle threads. It has no WinPTY fallback or Windows package dependency.
Pywinpty versions 3.0.5 and
2.0.15 were both rejected by the Windows lifecycle spike for pending writes,
lost or corrupted output, and incomplete teardown. Both backends execute the
shared real CLI `/quit` contract in
`tests/coding/test_cli_terminal_contract.py`.

tmux is a separate terminal-implementation integration. Its marker only proves
pane history and scrollback behavior and must not be used as the Windows
equivalent of ConPTY. Marker assertions require every settled history line to
appear exactly once and in order. The tmux suite includes live transcript
replacement, line-budget trimming, and post-resume streaming so FakeTerminal's
portable screen model is not the sole oracle for emulator-specific history.

Run the local collections with:

```bash
make test-tui-render-contract
make test-tui-terminal-platform
make test-tui-input-playback
make test-tui-native
```

GNU Make is only a convenience wrapper. Windows PowerShell should use the
cross-platform Python entrypoints directly:

```powershell
uv run python scripts/run_tui_platform_tests.py current -q
uv run python scripts/run_tui_native_tests.py current -q
uv run python scripts/run_tui_playback.py composer-selection-stress bracketed-paste-large-marker mouse-select-active-surface screen-loop-terminal-session-cleanup screen-loop-ctrl-c-abort-running
```

The platform runner owns four non-overlapping profiles: `shared`, `windows`,
`posix`, and `current`. CI invokes `shared` plus exactly one host profile;
developers normally invoke `current`. The native runner separately composes a
shared process contract with exactly one host-specific file and rejects a
Windows profile on POSIX or a POSIX profile on Windows before pytest starts.

CI runs deterministic and platform jobs on fixed Ubuntu 24.04 and Windows
Server 2022 runners, runs the shared native contract with
`LOUSHANG_REQUIRED_TERMINAL_BACKEND=posix-pty|conpty`, and runs tmux in a
separate fixed-Ubuntu required job. Each required job emits pytest XML and
fails closed when the report is empty, skipped, failing, or records the wrong
native backend.

Both TUI workflows cancel superseded runs for the same ref. Every pytest job
uses a bounded GitHub job timeout and `faulthandler_timeout=60`, so a stalled
async lifecycle emits a Python stack before the runner deadline. The
Harnesstui quality job also persists JUnit XML and passes it through the same
fail-closed verifier. `tui-cross-platform-contracts` is the stable aggregate
required-check context: it succeeds only after every Linux, Windows, native
terminal, and tmux dependency succeeds.

Deterministic screen-loop lifecycle recipes use `BlockingPromptController`
for prompts that settle during abort. Its one-shot context requires the prompt
to start, receive settlement from the abort callback, finish within a bounded
deadline, and leave no active asyncio task when the recipe returns.

## Live Terminal Smoke Checklist

Manual testing should focus on terminal behavior that is hard to assert
visually:

- startup below existing shell output
- resizing during long streaming output
- scrolling up while output continues
- IME candidate window placement
- terminal restoration after Ctrl-C, Esc abort, exception, and normal exit
- default mouse drag selects terminal text without inserting SGR fragments
- application-owned selection surfaces receive clicks without disabling normal
  terminal selection in sessions that did not opt in
- paste text containing emoji, press Ctrl-C and then Enter, and verify no UTF-8
  surrogate encoding error reaches the shell
- on Windows, switch focus away from and back to the terminal while the
  composer is active; verify the focus report does not insert `[I`
- on Windows, copy `hello`, right-click paste into the composer, and verify the
  draft is exactly `hello` with no `[200~` or `[201~` marker fragments
- narrow terminal status truncation
- modifier-key variants for Shift+Enter, Alt+Enter, Ctrl+Shift+Left/Right, and
  terminal-specific option/meta behavior
- keyboard-protocol negotiation in terminals that support enhanced key reporting
- image fallback and image protocol behavior when Kitty, iTerm2, WezTerm,
  Ghostty, VS Code terminal, tmux, or SSH changes runtime capabilities. The
  baseline manual matrix should include Kitty, iTerm2, WezTerm, Ghostty, VS Code terminal.
- composer selection in a real terminal:
  - type `abc`, press `Shift+Left`, verify the final `c` is visibly selected,
    then type `x` and verify the draft becomes `abx`
  - type `你🙂a`, press `Shift+Left` twice, type `x`, and verify the draft
    becomes `你x` without splitting the emoji grapheme
  - type a short draft, use `Shift+Home` and `Shift+End` from opposite line
    ends, and verify typing replaces exactly the selected text
  - press `Ctrl+-` after a selection replacement and verify undo restores the
    previous content and clears the visible selection

Manual smoke tests should be run after the playback harness and unit tests pass.
