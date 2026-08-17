# TUI Render Performance Contract

## Status

Frozen on 2026-07-16 against `main` commit
`5fbf2674a82b1585bae729e93e7c63fb6ae45a5f`.
The initial isolated contract run contains 151 passing cases.

The screen-presentation extraction extends the isolated contract to 161 passing
cases on 2026-07-19: the existing 154 cases plus direct ownership, identity,
streaming-presentation parity, cache-promotion parity, and segment-invalidation
checks, including the flat streaming fallback. Moving ownership into TUI and
Harnesstui may not change the existing thresholds, exceptional repaint reasons,
or structural work bounds in the same change.

This contract is the guardrail for later TUI extraction and refactoring. The
freeze itself changes tests, test entry points, and documentation only. It does
not change the renderer, markdown renderer, transcript projection, or coding UI
implementation.

## Boundary

The contract has two layers:

- `loushang.tui` owns generic render segments, render planning, terminal
  operations, streaming markdown rendering, transcript rendering, and cache
  bounds.
- Marked `loushang.coding.ui` tests are integration probes. They prove that a
  product adapter can project a long or streaming conversation without
  defeating the generic TUI fast paths.

The integration probes do not make session lifecycle, tools, approval policy,
or coding command semantics responsibilities of `loushang.tui`. If generic
conversation interaction later moves to `harnesstui`, the marked probes may
move with it, but their observable contract must not be weakened during the
move.

## Hard Frame Budgets

All budgets below apply after the initial frame. Synchronized output is
required in every case.

| Scenario | Disallowed operation classes | Max operations | Max serialized bytes | Max changed visible lines |
| --- | --- | ---: | ---: | ---: |
| Ordinary interaction | `baseline_repaint`, `recovery_repaint` | 32 | 768 | 8 |
| Long-transcript interaction | `baseline_repaint`, `recovery_repaint` | 12 | 2,000 | 3 |
| Product composed interaction | `baseline_repaint`, `recovery_repaint` | 64 | 3,000 | 20 |
| Product streaming control flow | `baseline_repaint`, `recovery_repaint` | 1,500 | 90,000 | 18 |

The exact values are asserted in
`tests/coding/test_tui_render_performance_contract.py`. Playback scenarios also
exercise the budgets against real fake-terminal frames; the constants alone
are not treated as sufficient evidence.

## Structural Work Bounds

The marked tests freeze these machine-independent properties:

- Updating one bottom-frame row below 11,748 unchanged committed rows compares
  only the one-row tails, reuses the committed segment, materializes one line,
  and performs no full logical-line flattening. A subsequent no-op materializes
  and flattens zero lines.
- With at least 1,000 committed transcript lines, timer and composer updates
  materialize at most 20 lines; a new streaming chunk materializes at most 30;
  all three reuse committed segments and flatten zero logical lines.
- With more than 512 stable streaming markdown segments, no-op, timer, and
  composer updates reuse more than 512 segments, materialize at most 16 lines,
  flatten zero lines, and do not rescan unchanged draft source. Appending one
  block materializes fewer than 64 lines.
- Render-segment finalization caches retain only the current committed frame.
  Streaming markdown and themed renderer caches remain bounded by their active
  render keys.
- Streaming buffers do not join all chunks merely to render, and the
  performance example summary retains only its last step instead of the full
  run history.

These are structural budgets, not implementation prescriptions. An
implementation may change data structures or algorithms if it preserves the
observable bounds and rendered result.

## Correctness And Terminal Invariants

Performance changes must also preserve the marked correctness baseline:

- segmented output is identical to the fresh flat-render oracle at every
  streaming chunk boundary, including lists, growing tables, closing fences,
  late references, height clipping, and record boundaries;
- stable markdown blocks are reused while the mutable block is rerendered;
- terminal playback does not clear screen or scrollback during steady-state
  streaming and does not introduce recovery repaints;
- cursor anchors, protected bottom-frame append, resize repaint, active-window
  replacement, image cleanup, and failed-flush retry semantics remain stable;
- cache promotion or eviction never changes visible transcript content.

## Explicit Exceptions

The steady-state budgets intentionally skip the first frame. Dedicated tests
continue to allow and verify these exceptional paths:

- first render;
- an explicit resize repaint under the configured scrollback policy;
- an explicit baseline reset, such as replacing the active transcript window;
- recovery repaint after the runtime proves that its viewport is unsafe.

An exception must carry its expected operation class and reason. It must not be
used to relax an ordinary interaction or long-transcript budget.

## Timing Policy

Wall-clock thresholds are not part of this hard contract. They vary with the
host, Python build, instrumentation, and CI load. Existing millisecond probes
remain useful smoke tests, but the merge gate is based on deterministic work
counts, cache bounds, terminal operations, serialized bytes, changed rows, and
rendered-output equivalence.

## Running The Contract

Run the isolated contract before and after every render-path refactor:

```bash
make test-tui-render-contract
```

The command selects tests marked `tui_render_contract`. Run the broader TUI and
coding UI regression suites after the isolated contract passes. The same
command is a required pull-request and `main` push check in
`.github/workflows/tui-render-contract.yml`.

## Change Protocol

A refactor may not update contract thresholds in the same change merely to make
the suite pass. A threshold or exception change requires a separate review
that records:

1. the scenario and before/after frame diagnostics;
2. why the previous bound is no longer valid;
3. why the new bound is not masking a regression;
4. the replacement deterministic assertion, when an old assertion is removed.

Moving a marked test between `loushang.tui`, `harnesstui`, and a product adapter
is allowed only when the marker, behavior, and threshold remain intact.

## Related Designs

- [KD-001: Render Loop And Terminal Writer](./key-designs/KD-001-render-loop-and-terminal-writer.md)
- [KD-010: Terminal Playback Harness](./key-designs/KD-010-terminal-playback-harness.md)
- [KD-015: Versioned Rendered Segments](./key-designs/KD-015-stable-tail-window-and-transcript-block-cache.md)
- [KD-019: Streaming Markdown Stable Prefix Cache](./key-designs/KD-019-streaming-markdown-stable-prefix-cache.md)
