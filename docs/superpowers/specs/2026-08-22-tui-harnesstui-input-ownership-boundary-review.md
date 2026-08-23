# TUI And HarnessTUI Input Ownership Boundary Review

## Review Target

- Design:
  `2026-08-22-tui-harnesstui-input-ownership-boundary-design.md`
- Implementation plan:
  `../plans/2026-08-22-tui-harnesstui-input-ownership-refactor.md`
- Independent review Round 1 target: `2026-08-22-r4`
- Independent review Round 2 target: `2026-08-22-r5`
- Independent review Round 3 target: `2026-08-22-r6`
- Current revised target: `2026-08-22-r7`
- Review scope: architecture, API compatibility, regression strategy, rollout,
  and rollback boundaries

## Current Status

**Final acceptance verdict: Accept.**

Round 3 found three P2 and two P3 findings. Revision `r7` incorporated every
requested change. A fresh independent acceptance reviewer found no open
findings and approved the plan for implementation.
Approval does not extend to route deduplication, keybinding catalog movement,
result-type redesign, or Coding policy injection.

## Evidence Reviewed

- Generic `InputRouter` currently stores `running` and
  `steering_supported`, defines `SubmitMode`, constructs steer/follow-up
  intents, maps running cancel to abort, and emits a queued-edit command.
- `ConversationInputRouter` independently owns the production conversation
  state machine, including running Enter, running Alt+Enter, abort, pending
  steer, queue restore, transcript, and attachment paths.
- Production Coding uses the HarnessTUI router factory; no production module
  under `src/` constructs generic `InputRouter`.
- The stateful in-repository generic consumer is
  `examples/tui/29_composer_bottom_frame.py`, plus generic TUI tests.
- `InputRouter` is a top-level public export, while `SubmitMode` is not.
- The public package version is `0.1.0`.
- Focused input plus import-boundary/playback baselines passed: 131 tests.
- Coding conversation playback/loop passed: 46 tests.
- Broader `tests/tui tests/harnesstui` passed: 1,752 tests.
- Focused Ruff and example snapshot/scripted smoke passed.

## Round 1 Independent Findings And `r5` Resolutions

| ID | Priority | Independent finding | Resolution in `r5` |
| --- | --- | --- | --- |
| TIO-IREV-001 | P1 | Unconditional `prompt_cancel` leaks after Escape/Ctrl+C cancels pending jump mode. | Record jump cancellation, preserve surface/focused-editor/completion priority, then swallow that cancel; add the full priority matrix. |
| TIO-IREV-002 | P2 | The semantic-cut PR also rewrites the stateful example event loop. | Split a separately mergeable example-adapter PR before the public router cut. |
| TIO-IREV-003 | P2 | Snapshot/scripted smoke bypasses the modified interactive example loop. | Require Ruff/import smoke plus a recorded interactive PTY/terminal acceptance matrix. |
| TIO-IREV-004 | P2 | A class-scoped producer gate is weaker than the declared TUI package boundary. | Scan all `src/loushang/tui/**/*.py` with AST, while allowing legacy literal declarations and unrelated generic abort producers. |
| TIO-IREV-005 | P2 | KD-003 retains ambiguous Product-vs-HarnessTUI classification language. | Add KD-003 to PR 3 and explicitly assign conversation key interpretation to HarnessTUI. |
| TIO-IREV-006 | P3 | Direct removal of a public pre-1.0 API lacks a durable migration contract. | Add constructor/submit signature tests and persistent English/Chinese migration guidance with replacement mappings. |

## Round 2 Independent Findings And `r6` Resolutions

| ID | Priority | Independent finding | Resolution in `r6` |
| --- | --- | --- | --- |
| TIO-IREV2-001 | P1 | Removing dataclass state fields can silently rebind legacy third/fourth positional arguments to `width`/`height`. | Add `KW_ONLY`, make `_jump_mode` `init=False`, assert the exact signature, and require legacy third-position calls to raise `TypeError`. |
| TIO-IREV2-002 | P1 | The example has no completion provider, so its manual completion gate is unreachable; old/new cancel adaptation was not single-execution. | Remove that manual gate, specify normalized old/new-compatible cancel adaptation, and re-run the PR 2 matrix after PR 3 with zero example diff. |
| TIO-IREV2-003 | P2 | A custom jump binding can overlap cancel and hit the repeated-jump early return. | Compute cancel first, disallow early return on overlap, and add surface/focused-editor/completion overlap regressions. |
| TIO-IREV2-004 | P2 | The package AST gate claimed more than direct constant analysis could prove. | Check positional/keyword constants with checker self-tests and explicitly defer structural dynamic-envelope proof. |
| TIO-IREV2-005 | P2 | Required HarnessTUI playback does not directly cover Coding steer/follow-up/abort paths. | Add Coding playback and loop files as mandatory baseline and PR 3 gates. |
| TIO-IREV2-006 | P2 | Example baseline text misstated idle Ctrl+C normalization and Alt+Up scope. | Make Ctrl+C an explicit example-only alias fix and keep Alt+Up follow-up-only. |
| TIO-IREV2-007 | P3 | Sandbox-safe pytest commands omitted `--skip-host-runtime`. | Add the repository sandbox flag to every required pytest command. |

## Round 3 Independent Findings And `r7` Resolutions

| ID | Priority | Independent finding | Resolution in `r7` |
| --- | --- | --- | --- |
| TIO-IREV3-001 | P2 | PR 2/PR 3 were called independently reversible despite a constructor dependency. | Describe them as separately mergeable and require rollback order PR 3, PR 2, PR 1 with a recorded PR 2 SHA. |
| TIO-IREV3-002 | P2 | PR 2 omitted idle/running exit-command behavior. | Classify `/q`, `/quit`, `/exit` before submit policy and add idle/running PTY rows plus the zero-diff PR 3 re-run. |
| TIO-IREV3-003 | P2 | Durable docs overstated current Coding capability injection. | State the above-TUI invariant, current HarnessTUI steer default, static steer/follow-up mapping, and deferred Coding injection. |
| TIO-IREV3-004 | P3 | Custom jump/cancel overlap lacked a no-pending-jump direct cancel gate. | Require `prompt_cancel` with no pending jump and prove later text is not consumed as a jump target. |
| TIO-IREV3-005 | P3 | AST gate did not explicitly cover attribute-form `InputIntent` construction. | Recognize and self-test both `ast.Name` and `ast.Attribute` constructor targets. |

## Retain, Rewrite, Defer

Retain now:

- `coding -> harnesstui -> tui` dependency direction;
- HarnessTUI as the sole conversation input semantic owner;
- `prompt_cancel` as a neutral generic signal;
- `ComposerInputTarget`, focused-editor separation, and reusable editor helpers;
- HarnessTUI's current routing order and observable shortcut behavior;
- existing generic `abort` intent for unrelated cancellable widgets;
- legacy `steer`/`follow_up` members in the shared `InputIntentKind` envelope,
  without generic TUI production.

Rewrite in this change:

- stateful example adapter ownership before the router cut;
- generic `InputRouter` constructor and submit contract;
- jump-aware generic cancel routing;
- package-wide producer gates;
- KD-002, KD-003, HarnessTUI ownership docs, and public API migration guidance.

Defer:

- Core/HarnessTUI/Product keybinding catalog composition;
- whole-event route reuse or staged editing-controller extraction;
- typed redesign of `ConversationInputResult`;
- cleanup or splitting of the shared `InputIntentKind` envelope;
- explicit Coding injection of running-submit policy.

## Revised Approval Constraints

PR 1 must:

- contain no production behavior change;
- add only tests that pass against current production behavior;
- record the package boundary and link the tracking issue.

PR 2 must:

- change only `examples/tui/29_composer_bottom_frame.py`;
- remain compatible with the current generic Router;
- stop passing `running=` and stop consuming generic conversation outputs;
- use one normalized cancel path that works against both old empty cancel and
  future `prompt_cancel` without double execution;
- explicitly fix idle Ctrl+C alias handling and preserve follow-up-only Alt+Up;
- preserve idle/running `/q`, `/quit`, and `/exit` before submit classification;
- preserve observable demo behavior with a reachable interactive acceptance
  matrix, not snapshot-only evidence.

PR 3 must:

- change no production file under `loushang.harnesstui`, `loushang.coding`, or
  `loushang.harness`;
- preserve HarnessTUI/Coding keyboard behavior and routing priorities;
- preserve jump-mode cancel consumption after surface/focused-editor/completion
  priority, including a custom jump/cancel binding overlap;
- make configuration after `surface_host` keyword-only and keep `_jump_mode`
  out of the public constructor;
- land target red tests with their green implementation;
- reject direct constant conversation producers across the complete
  `loushang.tui` package, with positional/keyword and bare/attribute-form
  checker self-tests;
- update KD-002, KD-003, public docs, and durable API migration guidance;
- pass focused, boundary, playback, and broader subsystem gates;
- re-run PR 2's matrix without modifying its example file;
- stop after semantic ownership is cut.

## Required Stop Conditions

Return to design review instead of expanding the patch if:

- a supported consumer of `InputRouter(running=...)`,
  `steering_supported=...`, or `submit(mode=...)` is identified;
- preservation requires a HarnessTUI or Coding production change;
- the example cannot migrate independently against the old Router;
- keyword-only migration cannot prevent positional calls from silently
  rebinding;
- a new shared whole-event route engine becomes necessary;
- adding `prompt_cancel` triggers a broad intent migration;
- playback exposes an unresolved ordering difference.

Rollback must follow PR 3, then PR 2, then PR 1. PR 2 must not be reverted while
the narrowed PR 3 constructor remains.

## Final Acceptance Review

**Verdict: Accept. No P0, P1, or lower-priority open findings.**

The independent reviewer verified:

- dependency-ordered rollback PR 3, then PR 2, then PR 1;
- idle/running exit classification and the before/after/zero-diff PTY gates;
- current HarnessTUI steer default versus deferred explicit Coding policy;
- no-pending and pending jump/cancel overlap behavior;
- bare/attribute and positional/keyword direct-constant AST coverage;
- retained `KW_ONLY`, `_jump_mode init=False`, dual-version single cancel,
  sandbox-safe pytest commands, and Coding playback gates.

The reviewer accepted the existing independent baseline evidence: 110 focused,
21 boundary/playback, 46 Coding playback/loop, and 1,752 broader TUI/HarnessTUI
tests passed.
