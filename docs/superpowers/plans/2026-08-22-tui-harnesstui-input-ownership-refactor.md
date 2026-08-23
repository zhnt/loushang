# TUI And HarnessTUI Input Ownership Refactor Plan

> Implementation plan for the reviewed design in
> `docs/superpowers/specs/2026-08-22-tui-harnesstui-input-ownership-boundary-design.md`.
> Execute tasks in order and stop after the semantic ownership cut. Do not add
> route deduplication or keybinding-catalog migration to this plan.

**Goal:** Remove Harness conversation semantics from generic
`loushang.tui.InputRouter` while preserving all HarnessTUI and Coding
conversation behavior.

**Architecture:** `loushang.tui` owns terminal and prompt-editor mechanics plus
generic submit/cancel signals. `loushang.harnesstui` remains the sole owner of
idle/running prompt, steer, follow-up, queue, and abort interpretation. This
plan deliberately keeps the current HarnessTUI routing order and its partial
mechanical duplication.

**Tech stack:** Python 3.11+, dataclasses, typing `Literal`/`Protocol`, pytest,
Ruff, existing TUI input playback and screen-loop playback.

---

## Scope Guard

Allowed production edits:

- `src/loushang/tui/input.py`
- the generic stateful demo adapter in
  `examples/tui/29_composer_bottom_frame.py`

Allowed contract/documentation edits:

- focused tests under `tests/tui/`
- focused HarnessTUI/Coding characterization tests only when a missing invariant
  is demonstrated
- TUI and HarnessTUI architecture/input documentation
- English and Chinese TUI editing/user guides

Not allowed under this plan:

- behavior changes in `src/loushang/harnesstui/conversation/input.py`
- production changes under `src/loushang/coding/` or `src/loushang/harness/`
- `ConversationInputResult` redesign
- global keybinding catalog movement
- broad `InputIntentKind` cleanup, including removal of existing
  `steer`/`follow_up` envelope members; this tranche only adds the new generic
  prompt cancel result
- shared whole-router extraction or route-order deduplication

If implementation requires a file outside this guard to make production
behavior work, stop and return to design review.

## Target Contract

After this plan:

```text
loushang.tui.InputRouter
  input: InputEvent + PromptInputTarget
  state: editor/surface/jump/viewport only
  output: submit | prompt_cancel | invalidate_render | generic surface intents

loushang.harnesstui.ConversationInputRouter
  input: InputEvent + conversation UI state
  output: prompt | local | steer | follow-up | abort | surface result | exit
```

Generic `InputRouter` must not:

- read `running`;
- inspect steering support;
- produce steer/follow-up;
- downgrade steer to follow-up;
- restore or request queued conversation messages;
- map cancel to active-run abort.

## PR Sequence

### PR 1: Freeze The Boundary

Reviewed design/plan/review artifacts and passing current-behavior
characterization tests only. No production behavior change, current
architecture-doc rewrite, target-contract red test, or future-state source
gate.

### PR 2: Migrate The Stateful Example

Change only the application adapter in
`examples/tui/29_composer_bottom_frame.py`. Stop passing conversation state to
generic `InputRouter` and stop consuming its conversation-specific outputs,
while the old router contract still exists. Verify the interactive event loop,
not only snapshot rendering.

### PR 3: Cut Generic Conversation Semantics

Target-contract red tests, package-level source ownership gates, generic TUI
implementation, durable/public documentation, and final verification. Red
tests are not committed separately; they land green with the implementation.

Do not combine any PR with later route deduplication.

Rollback is dependency-ordered: revert PR 3 before PR 2, then PR 1 if desired.
PR 2 is independently mergeable against the old Router, but it is not safe to
revert PR 2 while PR 3 remains because that would restore a `running=` caller
against the narrowed constructor. Record the PR 2 head/base SHA in PR 3 so the
zero-example-diff and rollback order are mechanically reviewable.

---

## Task 0: Establish The High-Risk Work Lane

**Files:** none

- [ ] Create or identify a GitHub tracking issue for the TUI/HarnessTUI input
  ownership cut.
- [ ] Use the long-lived TUI worktree without deleting or repurposing it.
- [ ] Confirm the worktree is clean before switching branches.
- [ ] Create a task branch from the latest local `main`, for example:

```bash
git switch -c tui/input-ownership-boundary main
```

- [ ] Record the baseline commit in the tracking issue or PR notes.
- [ ] Run the focused baseline:

```bash
.venv/bin/python -m pytest \
  tests/tui/test_input_routing.py \
  tests/harnesstui/conversation/test_input.py \
  tests/harnesstui/conversation/test_clipboard_input.py \
  tests/coding/test_screen_coding_tui_input.py \
  --skip-host-runtime \
  -q
```

Expected current baseline: 110 tests pass. If the count changes on the eventual
base commit, record the new passing count rather than forcing 110.

- [ ] Run the playback baseline:

```bash
.venv/bin/python -m pytest \
  tests/tui/test_import_boundaries.py \
  tests/harnesstui/testing/test_import_boundaries.py \
  tests/harnesstui/testing/test_input_playback.py \
  tests/harnesstui/testing/test_screen_loop_playback.py \
  --skip-host-runtime \
  -q
```

Expected current boundary/playback baseline: 21 tests pass. Record the actual
count on the eventual base commit if it changes.

- [ ] Run the Coding conversation playback/loop baseline:

```bash
.venv/bin/python -m pytest \
  tests/coding/test_screen_tui_playback_harness.py \
  tests/coding/test_screen_coding_tui_loop.py \
  --skip-host-runtime \
  -q
```

Expected current Coding playback/loop baseline: 46 tests pass. Record the
actual count on the eventual base commit if it changes.

- [ ] Stop if either baseline is red for reasons unrelated to this plan.

## Task 1: Freeze Current Conversation Behavior

**Files:**

- Modify only if a listed invariant is missing:
  `tests/harnesstui/conversation/test_input.py`
- Modify only if a listed invariant is missing:
  `tests/coding/test_screen_coding_tui_input.py`
- Verify: `tests/tui/test_input_routing.py`

### Step 1: Inventory Existing Conversation Regressions

- [ ] Confirm existing HarnessTUI/Coding tests cover:
  - idle Enter starts a prompt;
  - running Enter produces steer;
  - running Alt+Enter produces follow-up;
  - completion cancel wins before abort;
  - idle cancel handles pending steer before draft clear;
  - Alt+Up restores pending steer/follow-up text;
  - Ctrl+O and clipboard-image routing remain HarnessTUI/Coding behavior.
- [ ] Add only missing characterization. Do not rewrite already adequate tests.

### Step 2: Run Passing Characterization

Run the focused baseline from Task 0. PR 1 is mergeable only when every added
test passes against unchanged production code.

Do not add the future-state generic boundary tests or source ownership gate in
PR 1. They belong to Task 3 because they are expected to fail before the
implementation changes.

## Task 2: Migrate The Generic Stateful Example First

**Files:**

- Modify: `examples/tui/29_composer_bottom_frame.py`

This task is PR 2. It must remain independently mergeable while the current
conversation-aware `InputRouter` implementation still exists.

### Step 1: Record The Current Interactive Behavior

Before editing, run the example with a deterministic fake duration:

```bash
.venv/bin/python examples/tui/29_composer_bottom_frame.py \
  --min-run-seconds 20 \
  --max-run-seconds 20
```

Record the observed state after idle Enter, running Enter, `/steer ...` Enter,
Alt+Up, idle Ctrl+C, and running Escape/Ctrl+C. The example has no completion
provider/items, so completion cancel is not a reachable example gate. This is a
manual/PTY acceptance record, not a new example unit test. Also record idle
`/quit` and running `/quit`; the latter must cancel the active fake task before
exit.

### Step 2: Remove Conversation Arguments And Outputs

Construct generic `InputRouter` without `running=`:

```python
router = InputRouter(
    composer=app.composer,
    width=runtime.terminal.size().columns,
)
```

The demo/application adapter must own these rules:

- compute configured `is_cancel` with `KeybindingManager.matches()` and compute
  normalized Ctrl+C identity without comparing the raw `"ctrl_c"` alias;
- record `had_completions`, then call the generic router exactly once;
- if cancel started with completions, treat it as editor-consumed;
- otherwise map both the old Router's empty cancel result and the future
  Router's `prompt_cancel` result into one application cancel decision;
- idle Ctrl+C intentionally fixes the existing alias bug and exits the demo;
- running Escape/Ctrl+C aborts the demo task exactly once;
- idle Escape remains a no-op;
- Alt+Up restores only the last pending follow-up before generic routing; it
  does not restore or reorder pending steer;
- `/q`, `/quit`, and `/exit` are classified before idle/running submit policy;
  running exit cancels `active_task` before exiting;
- generic `submit` starts work while idle;
- generic `submit` queues a follow-up while running, except the existing
  `/steer ` convention queues steer text.

Remove demo dependence on these generic output forms:

- `intent.kind == "follow_up"`;
- `intent.kind == "abort"` from `InputRouter`;
- `intent.note == "edit_last_queued_prompt"`.

Do not add HarnessTUI imports to a generic TUI example. The application policy
may use local helpers, app state, normalized key ids, and configured input
actions. PR 3 must consume future `prompt_cancel` without changing this PR 2
example code or executing cancel policy twice.

### Step 3: Prove The Example Is Decoupled

The following source inventory must return no conversation dependency in the
interactive adapter:

```bash
rg -n \
  'running=|intent\.kind == "follow_up"|intent\.kind == "abort"|edit_last_queued_prompt' \
  examples/tui/29_composer_bottom_frame.py
```

Review any match before proceeding; unrelated display copy is not sufficient
reason to weaken the check.

### Step 4: Run Static And Non-Interactive Smoke

```bash
.venv/bin/python -m ruff check examples/tui/29_composer_bottom_frame.py
.venv/bin/python examples/tui/29_composer_bottom_frame.py --snapshot --width 100 --height 28
.venv/bin/python examples/tui/29_composer_bottom_frame.py --scripted --width 100 --height 28
```

Snapshot and scripted modes prove import/render health only; they do not close
the interactive gate.

### Step 5: Repeat The Interactive Acceptance Sequence

Repeat Step 1 after the change and record:

| Input | Required observation |
| --- | --- |
| text + Enter while idle | fake run starts and composer clears |
| text + Enter while running | follow-up appears in the pending area |
| `/steer focus logs` + Enter while running | steer item appears distinctly |
| Alt+Up with steer and follow-up pending | last follow-up returns; steer remains pending |
| Ctrl+C while idle | demo exits through the intentional alias bug fix |
| Escape/Ctrl+C while running without completion | fake run aborts |
| `/quit` + Enter while idle | demo exits without starting a fake run |
| `/quit` + Enter while running | active fake task is cancelled, then demo exits |

Do not merge PR 2 if only snapshot/scripted output was checked.

## Task 3: Make Generic `InputRouter` Conversation-Neutral

**Files:**

- Modify: `src/loushang/tui/input.py`
- Modify: `tests/tui/test_input_routing.py`
- Modify or create package ownership coverage under `tests/tui/`

This task begins PR 3. PR 2 must already be green so the generic router no
longer has a stateful in-repository example consumer.

### Step 1: Add Desired Generic Boundary Tests

Add focused tests that express the target generic contract. These are expected
to be red before the implementation in this task:

```python
def test_input_router_submit_is_conversation_neutral() -> None:
    composer = Composer(prompt="> ")
    composer.insert_text("later")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="enter")) == (
        InputIntent(kind="submit", text="later"),
    )


def test_input_router_unconsumed_cancel_emits_prompt_cancel() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="escape")) == (
        InputIntent(kind="prompt_cancel"),
    )


def test_input_router_does_not_own_conversation_queue_editing() -> None:
    composer = Composer(prompt="> ")
    router = InputRouter(composer=composer)

    assert router.route(InputEvent(kind="key", key="alt+up")) == ()
```

Also add regressions for the cancel priority matrix:

- Escape and Ctrl+C each terminate a pending jump without producing
  `prompt_cancel`;
- an active surface still receives cancel when a jump is pending;
- a focused editor still blocks prompt cancel when a jump is pending;
- active completion still consumes cancel when a jump is pending;
- Escape and Ctrl+C produce `prompt_cancel` only when truly unconsumed.
- with a custom `jumpForward=escape` overlap, surface, focused editor, and
  completion still win before jump cancel is swallowed.
- with `jumpForward=escape` and no pending jump or higher-priority consumer,
  Escape emits `prompt_cancel`; later text inserts normally instead of being
  consumed as a jump target.

Add public contract tests using dataclass/runtime/signature inspection:

- constructor fields exclude `running` and `steering_supported`;
- `inspect.signature(InputRouter)` is exactly `composer`, `surface_host`, then
  keyword-only `width`, `height`, `keybindings`, and `target`;
- `_jump_mode` is `init=False` and absent from the public constructor;
- `InputRouter(composer, None, True)` raises `TypeError` rather than silently
  rebinding `True` to `width`;
- `submit()` accepts no `mode` argument;
- a non-empty zero-argument `submit()` produces only generic `submit`.

### Step 2: Add Package-Level Source Ownership Gates

Add architecture tests that use runtime/dataclass inspection to verify:

- `running` is absent;
- `steering_supported` is absent;
- generic `input.py` has no `SubmitMode` definition.

Add an AST producer gate over every Python file under
`src/loushang/tui/**/*.py`. Reject direct constant construction in both
positional and keyword forms:

- `InputIntent("steer", ...)`;
- `InputIntent(kind="steer", ...)`;
- `InputIntent("follow_up", ...)`;
- `InputIntent(kind="follow_up", ...)`;
- `InputIntent("command", ..., "edit_last_queued_prompt")`;
- `InputIntent(kind="command", note="edit_last_queued_prompt")`.

The AST gate must not reject retained `InputIntentKind` literal declarations,
string values in migration documentation, or unrelated generic
`InputIntent(kind="abort")` producers used by cancellable widgets. Existing
structural dynamic-envelope forwarders such as configurable selection/dialog
result kinds are explicitly outside this direct-constant guarantee. Add checker
self-tests with small parsed snippets for every rejected positional/keyword
form and for the allowed dynamic/abort forms. Recognize both
`ast.Name(id="InputIntent")` and `ast.Attribute(attr="InputIntent")` call
targets so module-qualified construction cannot bypass the gate. Do not use a
brittle whole-tree substring assertion.

### Step 3: Run The New Tests And Confirm RED

Run only the new generic boundary tests.

Expected failures:

- `prompt_cancel` is not yet an accepted intent kind/route;
- Alt+Up still emits the queued-edit command;
- the current class still exposes conversation-state fields and branches.

Do not commit red tests alone. Continue within this task and commit the tests
with the green implementation.

### Step 4: Narrow Generic Intent Vocabulary

In `InputIntentKind`:

- [ ] Add `prompt_cancel`.
- [ ] Retain `follow_up` and `steer` as legacy members of the shared surface
  intent envelope; generic `InputRouter` must stop constructing them.
- [ ] Keep `abort`; other generic components already use it and broad intent
  cleanup is outside scope.

Remove:

```python
SubmitMode = Literal["submit", "follow_up", "steer"]
```

Do not touch unrelated approval, dialog, selection, settings, or command intent
kinds.

### Step 5: Remove Conversation State From The Router

Remove these dataclass fields:

```python
running: bool = False
steering_supported: bool = False
```

Add a keyword-only boundary and hide internal jump state from construction:

```python
_: KW_ONLY
width: int = 80
height: int = 24
keybindings: KeybindingManager | None = None
target: InitVar[PromptInputTarget | None] = None
_jump_mode: Literal["forward", "backward"] | None = field(
    default=None,
    init=False,
)
```

Keep `composer` and `surface_host` as the only positional parameters. This is a
loud-failure boundary for old third/fourth positional calls, not a compatibility
shim.

### Step 6: Replace Cancel Routing Without Leaking Jump Cancel

Compute `is_cancel` before evaluating pending jump state. Preserve these
priorities:

1. a pending jump is cleared, while recording whether this key is cancel; a
   repeated jump binding returns early only when `not is_cancel`;
2. active surface receives the key first;
3. focused editor target still blocks prompt-only actions;
4. active completion closes before generic cancel;
5. cancel that already terminated pending jump returns no intent;
6. only a truly unconsumed cancel emits `prompt_cancel`.

Conceptually, the final decision is:

```python
if keybindings.matches(event.key, "tui.select.cancel"):
    if cancelled_pending_jump:
        return ()
    return (InputIntent(kind="prompt_cancel"),)
```

Do not return immediately when the jump is first cleared: that would skip the
existing surface/focused-editor/completion priority. Do not clear the prompt and
do not emit `abort` here. Add the custom `jumpForward=escape` overlap
regressions rather than broadening keybinding conflict validation in this PR.

### Step 7: Remove Conversation Queue Routing

Delete the `tui.queue.editLast` branch from generic `InputRouter`:

```python
if keybindings.matches(event.key, "tui.queue.editLast"):
    return (InputIntent(kind="command", note="edit_last_queued_prompt"),)
```

Do not remove the keybinding definition in this plan; HarnessTUI still consumes
the action id. The generic router simply stops assigning it conversation
meaning.

### Step 8: Simplify Submit

Change:

```python
def submit(self, *, mode: SubmitMode = "submit") -> tuple[InputIntent, ...]:
```

to:

```python
def submit(self) -> tuple[InputIntent, ...]:
```

Keep the existing generic sequence:

1. read target text;
2. ignore empty text;
3. add to target history;
4. clear the target;
5. return one generic submit intent.

Delete all running, steer-support, downgrade, follow-up, and note branches.

### Step 9: Update Existing Generic Tests

- [ ] Remove construction with `running=` or `steering_supported=`.
- [ ] Delete/replace tests whose only contract is generic running steer or
  follow-up behavior.
- [ ] Preserve surface-before-cancel and completion-before-cancel tests, changing
  only the final generic result where necessary.
- [ ] Expand jump cancellation coverage to Escape and Ctrl+C plus active
  surface, focused editor, and completion combinations.
- [ ] Preserve all editor, target, selection, completion, history, paste, jump,
  page, resize, and keybinding override tests.
- [ ] Verify that tests do not recreate conversation interpretation inside
  `tests/tui`.

### Step 10: Run Focused TUI Tests

```bash
.venv/bin/python -m pytest \
  tests/tui/test_input_routing.py \
  --skip-host-runtime \
  -q
```

Expected: PASS.

### Step 11: Run HarnessTUI And Coding Behavior Tests

```bash
.venv/bin/python -m pytest \
  tests/harnesstui/conversation/test_input.py \
  tests/harnesstui/conversation/test_clipboard_input.py \
  tests/coding/test_screen_coding_tui_input.py \
  --skip-host-runtime \
  -q
```

Expected: all existing behavior remains green without production edits under
`src/loushang/harnesstui` or `src/loushang/coding`.

## Task 4: Update Durable And Public Documentation

**Files:**

- Modify:
  `docs/internals/architecture/tui/native-terminal-core/key-designs/KD-002-input-event-routing.md`
- Modify:
  `docs/internals/architecture/tui/native-terminal-core/key-designs/KD-003-abort-steer-follow-up-sequence.md`
- Modify: `docs/internals/architecture/harnesstui/README.md`
- Modify: `docs/en/reference/tui-editing.md`
- Modify: `docs/zh-CN/reference/tui-editing.md`
- Modify if necessary: `docs/en/user-guide/tui.md`
- Modify if necessary: `docs/zh-CN/user-guide/tui.md`
- Modify status note:
  `docs/superpowers/specs/2026-06-09-tui-input-router-decouple-design.md`

### Step 1: Correct KD-002 Ownership

Replace claims that generic `InputRouter` owns running abort or
steer/follow-up semantics with:

- generic TUI owns editor and prompt intent mechanics;
- HarnessTUI owns conversation run-state interpretation;
- Product adapters may define final command and action policy.

Keep surface-first, focused-editor, completion, paste, and editor-state
requirements unchanged.

### Step 2: Correct KD-003 And Clarify HarnessTUI Ownership

Correct KD-003 before updating the HarnessTUI README:

- HarnessTUI conversation adapters interpret idle/running Enter,
  follow-up/steer alternatives, queue restore, and conversation abort;
- capability and downgrade policy stays above generic TUI;
- at implementation time Coding used HarnessTUI's default
  `running_submit_mode="steer"`; follow-up #477 later replaced that implicit
  seam with Harness-declared capabilities, HarnessTUI steer-first fallback,
  and optional Product policy injection;
- Coding continues to supply slash-command classification, final actions, and
  copy;
- generic TUI emits neutral prompt/editor signals only.

Then document `ConversationInputRouter` as the sole Harness conversation input
semantic owner. State that it reuses TUI editing targets/helpers without using
generic `InputRouter` as a second conversation state machine.

### Step 3: Update Public TUI Guidance

Explain that generic `InputRouter` emits `submit` and `prompt_cancel`; an
application adapter decides run-state meaning. Point Harness-backed conversation
applications to HarnessTUI.

Add a durable, searchable **Pre-1.0 InputRouter migration** section to the
English and Chinese reference guides. It must identify the breaking removals
and show both replacement paths:

| Old API | Harness-backed replacement | Generic application replacement |
| --- | --- | --- |
| `InputRouter(running=...)` | `ConversationInputRouter` state projection | interpret generic `submit` from app state |
| `steering_supported=...` | choose `running_submit_mode="steer"` when supported, otherwise `"follow_up"` | app-owned capability decision |
| `submit(mode=...)` | HarnessTUI running-submit route | zero-argument `submit()` plus app policy |
| third/fourth positional state arguments | use explicit HarnessTUI configuration | replace with keyword-only generic configuration and app state |

State explicitly that only `composer` and `surface_host` remain positional.
All later constructor configuration is keyword-only, and legacy calls such as
`InputRouter(composer, None, True)` now raise `TypeError` instead of silently
binding `True` to `width`.

Do not rely on the PR description as the only migration record.

### Step 4: Mark The Older Design Partially Superseded

Add a short status note to the 2026-06-09 design:

- target adapter and focused-editor work remains valid;
- generic ownership of running abort/steer/follow-up is superseded by the
  2026-08-22 ownership design.

Do not rewrite historical implementation steps.

## Task 5: Final Verification And Review Gate

**Files:** verify all files changed by Tasks 1-4

### Step 1: Focused Regression

```bash
.venv/bin/python -m pytest \
  tests/tui/test_input_routing.py \
  tests/harnesstui/conversation/test_input.py \
  tests/harnesstui/conversation/test_clipboard_input.py \
  tests/coding/test_screen_coding_tui_input.py \
  --skip-host-runtime \
  -q
```

### Step 2: Boundary And Playback Regression

```bash
.venv/bin/python -m pytest \
  tests/tui/test_import_boundaries.py \
  tests/harnesstui/testing/test_import_boundaries.py \
  tests/harnesstui/testing/test_input_playback.py \
  tests/harnesstui/testing/test_screen_loop_playback.py \
  --skip-host-runtime \
  -q
```

### Step 3: Coding Conversation Playback And Loop Regression

```bash
.venv/bin/python -m pytest \
  tests/coding/test_screen_tui_playback_harness.py \
  tests/coding/test_screen_coding_tui_loop.py \
  --skip-host-runtime \
  -q
```

### Step 4: Broader Subsystem Regression

```bash
.venv/bin/python -m pytest tests/tui tests/harnesstui --skip-host-runtime -q
.venv/bin/python -m pytest \
  tests/coding \
  --skip-host-runtime \
  -m "not live and not tui_render_contract" \
  -q
```

If a broader suite has a known unrelated failure, record the exact failing test
and prove the focused baseline remains unchanged. Do not weaken or skip a new
input failure.

### Step 5: Re-run The PR 2 Example Without Editing It

- [ ] Verify PR 3 has no diff for
  `examples/tui/29_composer_bottom_frame.py` relative to the recorded PR 3 base.
- [ ] Repeat the PR 2 interactive matrix unchanged against the new Router.
- [ ] Confirm cancel policy executes once for both Escape and Ctrl+C, Alt+Up
  restores only follow-up, idle Ctrl+C exits, and idle/running `/quit` retain
  the PR 2 behavior.

Do not patch the example inside PR 3 to make this gate pass. If the PR 2 adapter
is not dual-version compatible, stop and repair/re-review the PR split.

### Step 6: Static Validation

```bash
.venv/bin/python -m ruff check \
  src/loushang/tui/input.py \
  src/loushang/harnesstui/conversation/input.py \
  examples/tui/29_composer_bottom_frame.py \
  tests/tui/test_input_routing.py \
  tests/harnesstui/conversation/test_input.py
git diff --check
```

### Step 7: Manual Diff Review

Verify:

- [ ] no production file under `src/loushang/harnesstui` changed behavior;
- [ ] no production file under `src/loushang/coding` changed;
- [ ] generic InputRouter has no conversation state or result construction;
- [ ] package-wide AST gate prevents direct constant conversation intent
  producers elsewhere under `src/loushang/tui/`, including positional and
  keyword call forms;
- [ ] public constructor makes all configuration after `surface_host`
  keyword-only and excludes `_jump_mode`;
- [ ] existing routing priorities were not reordered beyond deleted
  conversation branches;
- [ ] jump-mode Escape/Ctrl+C remains consumed after surface, focused-editor,
  and completion priority;
- [ ] custom `jumpForward=escape` cannot bypass those priorities;
- [ ] with no pending jump, the same overlap emits `prompt_cancel` rather than
  entering jump mode;
- [ ] AST checker covers bare and attribute-form `InputIntent` constructors;
- [ ] example-owned policy did not leak back into TUI;
- [ ] docs distinguish current generic and conversation contracts;
- [ ] no keybinding catalog, tagged-result, or route-deduplication work slipped
  into the patch.

## Commit And PR Guidance

Recommended commits:

1. `docs(tui): define input ownership boundary` — reviewed design, plan,
   review record, and passing characterization where appropriate.
2. `refactor(tui-example): own conversation demo input policy` — stateful
   example adapter migration and its recorded interactive acceptance evidence.
3. `refactor(tui): remove conversation semantics from input router` — red/green
   boundary tests, implementation, package-level ownership gate, durable
   architecture updates, and public migration guidance.

Use `Refs #N` while the tracking issue remains open. Do not use `Fixes #N` if
the issue also tracks deferred route deduplication or keybinding cleanup.

PR 2 description must include the static/import commands and the complete
interactive acceptance record, call out the intentional idle Ctrl+C alias fix,
state that Alt+Up remains follow-up-only, and record idle/running exit-command
behavior. PR 3 description must include:

- the removed advanced constructor/method behavior;
- proof that production Coding uses HarnessTUI rather than generic
  `InputRouter`;
- focused and playback commands with results;
- explicit statement that effective Coding shortcuts did not change;
- the pre-1.0 breaking API migration mapping;
- proof that old positional state arguments fail loudly and `_jump_mode` is not
  a public constructor parameter;
- proof that PR 2's example file did not change and its matrix still passes;
- rollback order PR 3, then PR 2, then PR 1;
- deferred follow-ups that were intentionally excluded.

## Stop Conditions

Stop and return to design review if any of the following occurs:

- a supported production or external consumer of `InputRouter(running=...)` is
  identified;
- keyword-only migration cannot prevent legacy positional calls from silently
  rebinding;
- preserving Coding behavior requires modifying Coding production code;
- HarnessTUI must change routing order to accommodate the generic cut;
- `prompt_cancel` cannot be introduced without broad widget intent migration;
- the implementation begins to require a new whole-event route engine;
- focused input or playback tests reveal an existing ambiguity not resolved by
  the reviewed decision records.

## Completion Criteria

- The reviewed spec decisions TIO-DEC-001 through TIO-DEC-005 and TIO-DEC-007
  are implemented.
- All focused, boundary, and playback gates pass.
- Constructor signature and legacy positional loud-failure tests pass.
- The example adapter PR passed static/import smoke and the recorded
  interactive acceptance matrix before and after the router cut without a PR 3
  example diff.
- Idle/running exit commands remain classified before submit/follow-up policy.
- Generic `InputRouter` is conversation-state neutral.
- HarnessTUI/Coding conversation behavior is unchanged.
- Public docs and the stateful generic example use the new boundary.
- Deferred work remains deferred and is not hidden in the implementation PR.
