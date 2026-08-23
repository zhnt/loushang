# HarnessTUI Conversation Input Outcome Refactor Plan

> Tracking issue: #475
> Design: `docs/superpowers/specs/2026-08-22-harnesstui-conversation-input-outcome-design.md`

## Objective

Replace the optional-field HarnessTUI conversation input result with a closed,
discriminated union while preserving router order, runner behavior, playback
artifacts, and Coding keyboard semantics.

Land the implementation as one coherent multi-file PR. Do not split individual
variant, runner, or playback changes into separate PRs.

## Baseline

- base commit: `f97ac58a6b5197e673ff29d70bd90eac3c9c12ca`
- branch: `harnesstui/discriminated-input-outcomes`
- focused HarnessTUI baseline: 30 passed
- Coding input/playback baseline: 82 passed
- direct old result constructions: 46

## Scope

Expected production and test files:

1. `src/loushang/harnesstui/conversation/input.py`
2. `src/loushang/harnesstui/conversation/screen_runner.py`
3. `src/loushang/harnesstui/testing/input_playback.py`
4. `src/loushang/harnesstui/testing/ports.py`
5. `tests/harnesstui/conversation/test_input.py`
6. `tests/harnesstui/conversation/test_clipboard_input.py`
7. `tests/harnesstui/conversation/test_screen_runner.py`
8. `tests/harnesstui/testing/test_input_playback.py`
9. Coding playback/scenario compatibility files only where type migration
   requires them.

The two design/plan documents travel with the implementation so the PR remains
self-contained and reviewable.

## Task 0: Freeze And Record The Baseline

- [x] Create issue #475.
- [x] Use the clean long-lived TUI worktree.
- [x] Create `harnesstui/discriminated-input-outcomes` from `f97ac58a`.
- [x] Run and record the 30-test HarnessTUI focused baseline.
- [x] Run and record the 82-test Coding compatibility baseline.
- [x] Record the sandbox-first pytest exception in the issue.

## Task 1: Add Result Contract Tests

Files:

- modify `tests/harnesstui/conversation/test_input.py`
- optionally add a focused result-contract test module only if the existing
  input test file becomes unclear

Steps:

1. [x] Add tests for the ten concrete variants and fixed `kind` values.
2. [x] Assert handled renders and ignored does not render.
3. [x] Assert text/attachment variants expose coupled payloads.
4. [x] Assert the old optional-field construction API is unavailable.
5. [x] Add representative router assertions for prompt, local, steer, follow-up,
   surface, clipboard, abort, handled, ignored, and exit.
6. [x] Run the focused test slice and record the expected red failures before
   implementing the variants.

Do not commit red tests separately. They land green with the implementation.

## Task 2: Define The Closed Result Union

File:

- modify `src/loushang/harnesstui/conversation/input.py`

Steps:

1. [x] Add frozen, slotted result variants with `init=False` literal `kind` and
   fixed `render_requested` fields.
2. [x] Define `ConversationInputResult` as their `TypeAlias` union.
3. [x] Replace every old constructor in the router mechanically.
4. [x] Keep control-flow branches and helper ordering unchanged.
5. [x] Export the alias and concrete variants from the module `__all__`.
6. [x] Run focused router and clipboard tests.
7. [x] Inspect the diff specifically for accidental route-order changes.

## Task 3: Make Runner Dispatch Exhaustive

Files:

- modify `src/loushang/harnesstui/conversation/screen_runner.py`
- modify `tests/harnesstui/conversation/test_screen_runner.py`

Steps:

1. [x] Replace the optional-field `ConversationInputResultPort` with the closed
   result union at the router factory boundary.
2. [x] Dispatch by concrete variant.
3. [x] End the dispatch with `assert_never` so new variants require an explicit
   runner branch.
4. [x] Preserve exit and abort early-control-flow behavior.
5. [x] Preserve prompt attachment forwarding and all handler return handling.
6. [x] Add a test proving one variant invokes only one handler.
7. [x] Run focused runner tests.

Do not refactor terminal polling, task lifecycle, or handler abstractions in
this task.

## Task 4: Preserve Playback Artifacts

Files:

- modify `src/loushang/harnesstui/testing/input_playback.py`
- modify `src/loushang/harnesstui/testing/ports.py`
- modify `tests/harnesstui/testing/test_input_playback.py`
- modify Coding scenario binding only if the now-closed result type eliminates
  an obsolete generic cast

Steps:

1. [x] Replace the structural optional-field port with the closed result union.
2. [x] Simplify playback router generics only as required by that union.
3. [x] Pattern-match every variant in the default serializer.
4. [x] Emit exactly the existing artifact keys and values; do not add `kind`.
5. [x] Add a table-driven serializer test covering every variant.
6. [x] Run HarnessTUI playback and Coding scenario baselines.

Stop if existing scenario snapshots require updates for value changes.

## Task 5: Static And Architecture Review

1. Run Ruff on all changed Python files.
2. Run focused mypy on the changed modules.
3. Run `make typecheck-tui`.
4. Run `make typecheck-harnesstui`.
5. Run `git diff --check`.
6. Search for legacy field-bag names and classify every remaining match:

```bash
rg -n \
  'prompt_text|prompt_attachments|local_text|steer_text|steer_attachments|followup_text|followup_attachments|surface_intent|abort_requested' \
  src/loushang/harnesstui/conversation \
  src/loushang/harnesstui/testing
```

Serializer compatibility keys may remain. Result objects and runner dispatch
must not retain the optional-field protocol.

## Task 6: Regression Gates

Run all pytest commands outside the filesystem sandbox on the first attempt.

Focused HarnessTUI:

```bash
.venv/bin/python -m pytest \
  tests/harnesstui/conversation/test_input.py \
  tests/harnesstui/conversation/test_clipboard_input.py \
  tests/harnesstui/conversation/test_screen_runner.py \
  tests/harnesstui/testing/test_input_playback.py \
  tests/harnesstui/testing/test_screen_loop_playback.py \
  --skip-host-runtime -q
```

Coding compatibility:

```bash
.venv/bin/python -m pytest \
  tests/coding/test_screen_coding_tui_input.py \
  tests/coding/test_screen_tui_playback_harness.py \
  tests/coding/test_screen_coding_tui_playback.py \
  --skip-host-runtime -q
```

Broader gates:

```bash
make check-harnesstui
.venv/bin/python -m pytest tests/tui tests/harnesstui --skip-host-runtime -q
```

Run the repository's dedicated cross-platform/render CI after the PR is
published. Do not treat marker deselection as failure when the Make target
intentionally selects a complementary suite; record the selected test count.

## Task 7: Commit, PR, And Merge

1. Confirm at least the coherent production/test surface above is included;
   do not publish single-file migration PRs.
2. Commit with `Refs #475` while review remains open.
3. Push and create one implementation PR against `main`.
4. PR description must include:
   - old field-bag to variant migration;
   - public/pre-1.0 compatibility note;
   - proof of artifact schema stability;
   - baseline and post-change test counts;
   - explicit exclusions: no route dedup, keybinding move, or policy change.
5. Wait for all CI checks.
6. Use `Fixes #475` only when the closed union, runner, playback, tests, and
   docs all land together and no required work remains.

## Review Checklist

- [x] Every current router branch maps to one variant.
- [x] No variant permits a payload belonging to another kind.
- [x] `kind` and `render_requested` cannot be overridden by callers.
- [x] Runner dispatch is exhaustive.
- [x] Abort and exit retain their current early control flow.
- [x] Playback artifacts have no key or value churn.
- [x] Coding behavior is unchanged.
- [x] No generic TUI production file changes.
- [x] No route deduplication or keybinding movement appears in the diff.
- [x] Typecheck baselines remain zero.
- [x] Pytest ran outside the sandbox first.

## Rollback

The result declarations, router construction migration, runner dispatch, and
playback adapter are one atomic compatibility unit and must be reverted
together. No later route-deduplication work may depend on this branch until this
PR is merged and green.

## Completion Criteria

- the reviewed result union is implemented across router, runner, and playback;
- at least the expected multi-file production/test surface is migrated in one
  PR;
- focused and broad regression gates pass;
- both TUI typecheck targets remain clean;
- default playback artifacts remain compatible;
- issue #475 contains the baseline and final verification record;
- deferred routing and policy work remains deferred.
