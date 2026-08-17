# Screen TUI Playback Regression Tests

Use the `tests/coding/test_screen_tui_playback_*` tests when a screen TUI
change can affect terminal behavior, not just pure component rendering.

Reusable conversation drivers and product-neutral scenario recipes live under
`loushang.harnesstui.testing`. The bound Coding suite, product fakes, frozen
frame budgets, and product profiles are repository-local support under
`tests/coding/tui_support`. They are not installed as a Coding compatibility
package. The former `loushang.coding.ui.playback*` compatibility imports are
retired; tests use the shared drivers and local support directly.

Good candidates include:

- composer input echo
- Working timer frames
- streaming updates
- completion open and close
- overlay and surface interactions
- viewport or cursor positioning
- long transcript resume behavior
- product-composed interactions that combine transcript, running state,
  pending queues, surfaces, completion, and composer selection
- streaming product control flows that combine long transcripts, live assistant
  draft, follow-up queueing, steering, resize, surfaces, and abort

Prefer focused component tests for pure rendering functions. Use the playback
harness when the test needs a `ScreenCodingTuiApp`, `TuiRuntime`, and
`FakeTerminalPort` together.

Useful assertions:

- `assert_no_clear(step)` for no `clear_screen` and no `clear_scrollback`
- `assert_operation_class(step, "...")` for differential update expectations
- `assert_visible_contains(text)` and `assert_visible_not_contains(text)` for visible terminal output
- `assert_cursor_matches_diagnostics(step)` when cursor anchoring is part of the behavior
- `assert_last_cursor_on_visible_line(text, column=n)` when a long transcript
  makes logical cursor rows differ from visible screen rows

Avoid broad snapshot-only tests. Prefer targeted assertions on terminal operations, diagnostics, visible text, and cursor/viewport invariants.

JSONL traces include `logical_cursor`, `viewport`, `hardware_cursor`, and
`screen_cursor`. Use `screen_cursor` for the fake terminal's final physical
cursor position, and keep `logical_cursor`/`viewport` for diagnosing render-loop
line mapping.

If a playback scenario fails after producing a `PlaybackResult`, attach that
result to the `AssertionError` as `playback_result`. The scenario runner will
write the normal error file plus the JSONL trace and final screen artifact, so
reviewers can inspect the last frames without rerunning the scenario locally.

## Manual entrypoint smoke

Use these commands to separate product entrypoint problems from playback harness
regressions:

```bash
loushang --tui
loushang-tui
printf "hi\n/quit\n" | loushang --tui
```

The first two commands should open the screen surface in an interactive terminal.
The piped command runs through the same TUI mode but falls back to the plain prompt loop
because stdin is not interactive. Do not use a separate UI selector flag for this
smoke path.

Useful direct smoke commands:

```bash
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py composer-selection-stress --artifacts /tmp/loushang-selection-playback --include-frames
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py product-composed-interaction --artifacts /tmp/loushang-product-playback --include-frames
uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py product-streaming-control-flow --artifacts /tmp/loushang-product-streaming-playback --include-frames
```

For a public, product-neutral playback example, see
`examples/tui/42_playback_smoke.py`.
