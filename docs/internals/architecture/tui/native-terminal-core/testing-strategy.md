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

Run the same test-only terminal driver contract over a POSIX PTY on Linux and
ConPTY on Windows. These tests prove structured argv, cwd/environment handling,
Unicode and VT transport, resize, exit status, large output drain, terminal
query response, bounded timeout, process-tree termination, and idempotent
cleanup. They do not claim exact final screen state; FakeTerminal/playback owns
that evidence.

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
equivalent of ConPTY.

Run the local collections with:

```bash
make test-tui-render-contract
make test-tui-terminal-platform
make test-tui-native
```

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
