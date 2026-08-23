# TUI And HarnessTUI Input Ownership Boundary Design

## Status

Approved for implementation after final independent acceptance review.

- Spec version: `2026-08-22-r7`
- Review verdict: Accept; no open findings
- Implementation prerequisite: create or identify a tracking issue under the
  high-risk change workflow before production code changes begin
- Scope: semantic ownership between `loushang.tui` and
  `loushang.harnesstui` only

This design supersedes the conversation-semantics portions of
`2026-06-09-tui-input-router-decouple-design.md`. The target protocols,
`ComposerInputTarget`, and reusable editor key helpers introduced by that work
remain valid and should be reused.

## Context

`loushang.tui` is the generic terminal UI substrate. It owns terminal input
decoding, normalized input events, surfaces and focus routing, editor
operations, completion, history, rendering, and terminal playback mechanics.

`loushang.harnesstui` is the product-neutral composition layer between Harness
conversation contracts and the generic terminal UI framework. Its documented
responsibilities include conversation input, pending queues, abort, steer,
follow-up, transcript reading, and reusable conversation-screen coordination.

The current source does not fully respect that split:

- `loushang.tui.input.InputRouter` accepts `running` and
  `steering_supported`, defines `SubmitMode = submit | follow_up | steer`, emits
  `abort`, `follow_up`, and `steer`, and interprets running Enter as follow-up.
- `loushang.harnesstui.conversation.input.ConversationInputRouter` separately
  interprets idle/running state, maps running Enter to steer, maps running
  Alt+Enter to follow-up, coordinates queued messages, and maps cancel to
  completion close, clear, pending-steer dispatch, or abort.
- Both routers therefore contain adjacent conversation state machines with
  different semantics for the same normalized key event.

This overlap is a migration remainder, not a desired two-product variation.
The production Coding screen already uses `ConversationInputRouter` through a
HarnessTUI router factory; production code under `src/` does not construct the
generic `InputRouter`. The only in-repository running-state consumer of generic
`InputRouter` is the generic composer bottom-frame example, plus focused tests.

## Problem Statement

The ownership problem is semantic rather than merely mechanical:

1. A generic editor router decides Agent/Harness conversation meaning.
2. A Harness conversation router repeats generic editor routing to preserve a
   different product-neutral conversation order.
3. A shared input-intent envelope still advertises conversation outcomes even
   though only an upper conversation layer should produce them.
4. Contributors cannot tell whether changing running submit behavior belongs in
   TUI or HarnessTUI.

Trying to remove all duplication, redesign every input intent, split every
keybinding catalog, and inject final Coding policy in one change would be too
broad. The first tranche therefore establishes semantic ownership and preserves
existing mechanical duplication where removing it would enlarge the change.

## Goals

- Make `loushang.harnesstui` the only owner of prompt/steer/follow-up/abort
  interpretation for Harness-backed conversation screens.
- Make generic `loushang.tui.InputRouter` independent of conversation run state.
- Keep TUI responsible for terminal/editor mechanics and generic prompt submit
  or cancel signals.
- Preserve all current HarnessTUI and Coding user-visible behavior.
- Keep active-surface, completion, selection, history, jump, paste, resize, and
  editor behavior unchanged.
- Keep the consumer migration and public router cut separately reviewable and
  mergeable in TUI-lane PRs, with an explicit dependent rollback order.
- Add executable ownership gates so conversation semantics cannot drift back
  into the generic router.

## Non-Goals

- Do not make `ConversationInputRouter` delegate its entire routing order to
  `InputRouter` in this tranche.
- Do not deduplicate all prompt editing orchestration in the same PR as the
  ownership cut.
- Do not redesign `ConversationInputResult` into a tagged union yet.
- Do not remove legacy `steer`/`follow_up` members from the shared
  `InputIntentKind` envelope yet; stop the generic router from producing them.
- Do not split `DEFAULT_KEYBINDINGS` into Core, HarnessTUI, and Product catalogs
  in this tranche; follow-up #479 later introduced duplicate-safe catalog
  composition.
- Do not move approval, continuity, settings, dialog, question, or selection
  intent kinds between packages.
- Do not change Coding slash-command classification, attachment conversion,
  clipboard directory policy, or product copy in this tranche; follow-up #479
  later moved the standard clipboard profile and generic copy to HarnessTUI.
- Do not change Harness Session, Agent loop, queue authority, or action host
  behavior.
- Do not change any effective keyboard shortcut in the Coding conversation
  screen.
- Do not add tests for the example script itself.

## Current Ownership Evidence

The accepted package direction is:

```text
loushang.coding.ui -> loushang.harnesstui -> loushang.tui
```

The package descriptions assign:

- terminal rendering, input, layout, surfaces, widgets, and playback substrate
  to `loushang.tui`;
- product-neutral Harness conversation interaction and TUI composition to
  `loushang.harnesstui`;
- final Product policy and composition to `loushang.coding`.

Current source-use inventory:

| Consumer | Generic `InputRouter` | HarnessTUI `ConversationInputRouter` |
| --- | --- | --- |
| Coding production screen | no | yes |
| HarnessTUI screen runner | no | yes |
| generic TUI examples | yes | no |
| `tests/tui` | yes | no |
| `tests/harnesstui` | no | yes |
| Coding TUI regression/playback | no | yes |

This inventory makes a semantic cut in generic `InputRouter` low blast radius,
provided the stateful generic example migrates first and public contracts move
with the later router cut.

## Target Ownership

### `loushang.tui`

Owns:

- terminal byte stream to normalized `InputEvent` conversion;
- key identifier normalization and generic keybinding mechanics;
- active surface/focus routing;
- prompt target protocols and `ComposerInputTarget`;
- text and paste insertion;
- selection, cursor, word, line, page, kill/yank, undo/redo, and jump editing;
- completion navigation and application;
- history traversal;
- explicit newline insertion;
- generic prompt `submit`, `prompt_cancel`, and render invalidation intents.

Does not own:

- whether a run is idle, running, or aborting;
- whether submitted text is a new prompt, steer, or follow-up;
- steering capability detection or downgrade policy;
- pending steer/follow-up queue restoration;
- transcript-reader commands or clipboard attachment coordination;
- Product command/exit classification.

### `loushang.harnesstui`

Owns:

- idle/running conversation input interpretation;
- completion-submit behavior used by conversation commands;
- running primary submit and alternate follow-up ordering;
- prompt, steer, follow-up, and abort results;
- pending queue restore and UI projection;
- transcript-reader command routing;
- product-neutral prompt attachment coordination;
- conversation-screen surface priority and result projection.

It continues to reuse generic TUI target adapters and editor helpers. Reusing
mechanics does not transfer conversation policy into TUI.

### `loushang.coding`

No production change is required in this tranche. Coding continues to supply:

- slash-command and exit predicates;
- the Coding clipboard-image profile;
- final action handlers and Product copy;
- configured keybindings.

Capability and downgrade decisions must remain above generic TUI. At the time
of this semantic cut, Coding used HarnessTUI's implicit
`running_submit_mode="steer"`. Follow-up #477 replaced that deferred seam:
Harness now declares steer/follow-up delivery capability, HarnessTUI owns a
steer-first policy with capability-aware fallback, and Coding may override the
policy without owning the capability fact.

## Decision Index

| ID | Decision | Status |
| --- | --- | --- |
| TIO-DEC-001 | TUI prompt routing is conversation-state neutral. | Approved |
| TIO-DEC-002 | HarnessTUI remains the sole conversation semantic router. | Approved |
| TIO-DEC-003 | Generic cancel is `prompt_cancel`, not run `abort`. | Approved |
| TIO-DEC-004 | First tranche accepts temporary orchestration duplication. | Approved |
| TIO-DEC-005 | Remove undocumented router knobs without a compatibility facade; retain the shared intent envelope. | Approved |
| TIO-DEC-006 | Keybinding catalog and broad intent cleanup are deferred. | Deferred |
| TIO-DEC-007 | Behavior is protected by focused, playback, and ownership gates. | Approved |

## Decision Records

### TIO-DEC-001: TUI Prompt Routing Is Conversation-State Neutral

`InputRouter` will no longer accept or store `running` or
`steering_supported`. Its `submit()` operation will have no mode parameter and
will emit only a generic `submit` intent containing the current prompt text.

Rationale:

- run state is not an editor or terminal property;
- the production conversation screen already uses HarnessTUI;
- removing the branch eliminates the conflicting generic running-Enter rule;
- the target adapters already isolate prompt editing operations.

Rejected alternative: retain `running` but rename follow-up to a neutral
alternate submit. This keeps run state in the generic layer and does not solve
the ownership problem.

### TIO-DEC-002: HarnessTUI Remains The Sole Conversation Semantic Router

`ConversationInputRouter` keeps the current observable state machine:

| Event | Condition | Result |
| --- | --- | --- |
| Enter | idle, non-empty | prompt or injected local/exit result |
| Enter | running, non-empty | steer by current HarnessTUI policy |
| Alt+Enter | running, non-empty | follow-up |
| explicit newline key | any applicable state | insert newline |
| Escape/Ctrl+C | completion visible | close completion |
| Escape/Ctrl+C | running | request abort |
| Escape/Ctrl+C | idle with pending steer | dispatch pending steer |
| Escape/Ctrl+C | idle with draft | clear draft and staged attachments |
| Alt+Up | pending queue present | restore queued text to composer |

No production HarnessTUI behavior changes are allowed in the ownership-cut PR.

Rejected alternative: migrate HarnessTUI onto a new shared whole-event router
while removing generic conversation semantics. That combines ownership change,
routing-order change, and deduplication in one high-risk patch.

### TIO-DEC-003: Generic Cancel Is `prompt_cancel`

After active surfaces and completion cancellation have had priority, generic
`InputRouter` returns `InputIntent(kind="prompt_cancel")` for the configured
cancel binding.

A cancel key that also terminates a pending character-jump mode is already
consumed by editor state and must not emit `prompt_cancel`. The router records
that the jump was cancelled, still gives an active surface, focused editor, and
completion their existing priority, and then swallows the cancel if none of
those layers handled it. This preserves existing jump-mode Escape/Ctrl+C
behavior without moving surface or completion policy into the application.

`is_cancel` must be computed before the pending-jump toggle branch. If a custom
keybinding assigns the same key to cancel and jump, the cancel priority path
wins; repeated-jump early return is allowed only when `is_cancel` is false.
This prevents a custom overlap from bypassing an active surface, focused
editor, or completion. With no pending jump and no higher-priority consumer,
the overlapped key emits `prompt_cancel` and must not enter jump mode.

It does not decide whether cancel means clear, close, abort, or no-op. A generic
application adapter owns that decision.

The existing generic `abort` intent remains available to generic cancellable
widgets that already use it; `InputRouter` simply stops producing it from
conversation run state.

Rejected alternatives:

- continue emitting `abort`: misleading because generic `InputRouter` no
  longer knows whether work is active;
- silently ignore cancel: prevents generic applications from implementing a
  policy outside TUI;
- clear the composer inside `InputRouter`: makes cancel policy an editor side
  effect and diverges from surface-first application control.

### TIO-DEC-004: Accept Temporary Orchestration Duplication

The first tranche does not make `ConversationInputRouter` call generic
`InputRouter`. It continues to reuse:

- `ComposerInputTarget`;
- `route_editor_selection_key()`;
- `route_prompt_completion_key()`;
- `route_editor_editing_key()`.

The duplicated handling around text/paste, jump mode, history, page movement,
tab forcing, and routing order remains until a later behavior-preserving
deduplication design.

This is deliberate. Semantic ownership must be stable before deciding whether
the shared unit should be a whole router, staged route engine, or smaller prompt
editing controller.

### TIO-DEC-005: Remove Undocumented Conversation Knobs Directly

The package version is `0.1.0`. Repository production code does not construct
generic `InputRouter`; the conversation-specific constructor fields and
`submit(mode=...)` behavior are absent from the public TUI user guides.

Therefore this tranche removes:

- `InputRouter.running`;
- `InputRouter.steering_supported`;
- `SubmitMode`;
- `submit(mode=...)`;
- generic `follow_up` and `steer` output construction;
- generic `edit_last_queued_prompt` command construction.

It does not remove the `follow_up` and `steer` literal members from
`InputIntentKind`. That type is a cross-package surface-intent envelope today,
and removing members is unnecessary to establish producer ownership. The
source ownership gate constrains what generic `InputRouter` constructs. Literal
cleanup belongs with the deferred result-envelope redesign.

No compatibility facade is introduced. A compatibility facade inside
`loushang.tui` would keep the forbidden semantics in the package and create a
second cleanup project. The stateful example migrates first in an independently
mergeable PR. The public editing docs must carry a persistent pre-1.0 breaking
change migration note, and the semantic-cut PR description must repeat it.

Contract tests must verify the new constructor fields and zero-argument
`submit()` signature, in addition to behavior tests. The migration note maps
old `running=`, `steering_supported=`, and `submit(mode=...)` usage to either a
HarnessTUI conversation router or an application-owned adapter.

Because `InputRouter` is a public dataclass, deleting the third and fourth
fields must not silently rebind old positional calls to `width` and `height`.
The new constructor keeps only `composer` and `surface_host` positional, adds a
`dataclasses.KW_ONLY` boundary before public configuration fields, and declares
`_jump_mode` with `init=False`. Old third-position calls must fail loudly with
`TypeError`; no compatibility facade is required.

If evidence of an external supported consumer appears before implementation,
this decision must be reopened rather than silently adding a permanent shim.

### TIO-DEC-006: Defer Catalog And Broad Intent Cleanup

The current default keybinding definitions include HarnessTUI- and
Product-oriented action ids such as transcript open, queue edit, continuity,
and clipboard-image paste. `InputIntentKind` also includes several surface and
workflow actions beyond generic prompt routing.

Those are real layering debts, but moving them requires a composable definition
catalog and coordinated updates across settings, surfaces, HarnessTUI, and
Coding. They are not required to stop generic `InputRouter` from deciding
conversation state.

Deferred follow-ups:

1. split Core, HarnessTUI, and Product keybinding definitions — completed by
   follow-up #479 for Core, conversation, and continuity catalogs;
2. decide whether `InputIntentKind` should remain a shared structural envelope
   or split into narrower typed results;
3. replace `ConversationInputResult`'s optional-field result bag only in a
   dedicated contract migration;
4. reduce prompt-routing duplication after semantic ownership is green.

### TIO-DEC-007: Executable Ownership And Behavior Gates

The ownership cut must be proven at three levels:

1. generic TUI input unit tests;
2. HarnessTUI/Coding conversation regression tests;
3. input and screen-loop playback with intermediate state assertions.

A source-level architecture gate should prevent `InputRouter` from regaining
conversation state fields. A package-wide AST producer gate over
`src/loushang/tui/**/*.py` should prevent direct constant construction of
`steer`, `follow_up`, or queued-edit intents. It checks both positional and
keyword `InputIntent` arguments and has checker self-tests. It explicitly
allows retained legacy literal declarations, unrelated generic `abort`
producers, and existing structural dynamic-envelope forwarders such as
configurable selection/dialog result kinds. Proving dynamic result values
belongs to the deferred typed-envelope redesign. Constructor matching covers
both bare `InputIntent(...)` names and attribute forms such as
`input_module.InputIntent(...)`.

## Target Generic `InputRouter` Contract

Conceptual constructor after the cut:

```python
@dataclass(slots=True)
class InputRouter:
    composer: Composer | None = None
    surface_host: SurfaceHost | None = None
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

Conceptual submit contract:

```python
def submit(self) -> tuple[InputIntent, ...]:
    text = self._target.value
    if not text:
        return ()
    self._target.add_history(text)
    self._target.clear()
    return (InputIntent(kind="submit", text=text),)
```

The generic router continues to clear and add history on accepted non-empty
submit. That is existing generic prompt behavior and not conversation policy.
HarnessTUI retains its own attachment-aware submission path.

## Target Generic Routing Order

The generic order remains unchanged except for the removed conversation steps
and the explicit distinction between jump cancellation and prompt cancellation:

1. ignore key release events;
2. compute `is_cancel`, then cancel or complete a pending character-jump mode,
   recording when a cancel key terminated it; a repeated jump key may return
   early only when it is not also cancel;
3. route active surfaces first;
4. route focused surface editor selection/editing and stop prompt fallback;
5. route prompt selection before completion navigation;
6. route active completion navigation/application/cancel;
7. swallow cancel when it already terminated a pending jump;
8. emit generic `prompt_cancel` only for a truly unconsumed cancel;
9. enter character-jump mode;
10. force/apply completion on Tab;
11. emit generic submit on configured submit;
12. insert explicit newline;
13. perform visual movement or history traversal;
14. perform page movement;
15. route ordinary editing keys;
16. route paste and text insertion;
17. emit render invalidation for resize and SIGWINCH.

Removed steps:

- running cancel to abort;
- queue edit command emission;
- running submit mode interpretation;
- steering capability downgrade.

## Compatibility And Migration

### In-repository consumers

`examples/tui/29_composer_bottom_frame.py` migrates before the generic router
cut and becomes an example of the correct application-adapter boundary:

- generic `submit` is interpreted by the demo application according to its own
  `app.running` state;
- cancel is normalized through configured keybindings, routed once through the
  old/new-compatible application adapter, and aborts only when demo work is
  running;
- the adapter treats old Router empty cancel and future `prompt_cancel` as the
  same single application decision without double execution;
- `/q`, `/quit`, and `/exit` are classified before idle/running submit policy;
  a running exit cancels the active fake task before exiting;
- idle Ctrl+C is intentionally fixed to exit by configured action matching;
- Alt+Up restores only the last pending follow-up before generic prompt routing;
- generic `InputRouter` is not reconstructed with `running=`;
- the demo no longer depends on generic `follow_up`, `abort`, or
  `edit_last_queued_prompt` outputs, so the example PR works both before and
  after the router cut.

No unit test is added specifically for this example, consistent with repository
guidance. The example PR instead requires Ruff/import smoke plus a recorded
interactive PTY or terminal acceptance sequence for idle submit, running
follow-up, `/steer`, follow-up-only Alt+Up restore, idle Ctrl+C, and running
cancel. The example has no completion provider, so completion cancel remains an
automated generic/HarnessTUI/Coding gate rather than a fake manual example gate.

### Public documentation

The English and Chinese TUI editing guides must say explicitly:

- `InputRouter` emits generic prompt intents;
- application or HarnessTUI adapters interpret run-state behavior;
- Harness-backed conversation applications should use HarnessTUI rather than
  generic `InputRouter` for steer/follow-up/abort semantics.
- removal of `running=`, `steering_supported=`, and `submit(mode=...)` is a
  pre-1.0 breaking API change, with old-to-new migration examples.

KD-002 and KD-003 must agree with the same owner split: HarnessTUI interprets
idle/running conversation keys; capability/downgrade policy remains above TUI;
Coding used the HarnessTUI steer default in this tranche; capability projection
and optional Product policy injection were completed by follow-up #477.

### Historical design

The older target-decoupling spec remains useful history for the target adapter
boundary, but its statement that generic `InputRouter` owns running abort and
steer/follow-up submission is superseded by this design.

## Rollout Plan

### PR 1: Contract And Characterization

- Link a tracking issue.
- Land the reviewed design, implementation plan, and review record.
- Add/strengthen passing tests that characterize current HarnessTUI/Coding
  behavior.
- Make no production behavior changes.
- Do not add target-contract tests that are expected to fail against the
  current generic router.

### PR 2: Migrate The Stateful Example

- Change only `examples/tui/29_composer_bottom_frame.py`.
- Stop passing `running=` and stop consuming generic conversation outputs.
- Move running submit, cancel, and Alt+Up queue policy into the demo adapter.
- Preserve idle/running `/q`, `/quit`, and `/exit` behavior before submit
  classification.
- Treat idle Ctrl+C normalization as an explicit example-only bug fix and keep
  Alt+Up scoped to pending follow-up.
- Run static/import smoke and record the explicit interactive acceptance
  sequence.
- Keep current generic `InputRouter` production behavior unchanged.

### PR 3: Generic Semantic Cut

- Add the target generic boundary tests and source ownership gate, confirm the
  intended failures, and land them with the green implementation.
- Remove conversation state and output branches from generic `InputRouter`.
- Add generic `prompt_cancel`.
- Add `KW_ONLY`, hide `_jump_mode` from the constructor, and prove old third
  positional calls fail rather than rebind.
- Preserve jump-mode cancel consumption and surface/focused-editor/completion
  priority, including custom jump/cancel key overlap.
- Remove generic queue-edit routing.
- Migrate generic tests, KD-002, KD-003, HarnessTUI ownership docs, public
  guides, and the persistent API migration note.
- Keep HarnessTUI and Coding production behavior unchanged.
- Run the focused and playback gates below.
- Re-run the PR 2 example interaction matrix without modifying the example.

Stop after PR 3. Do not begin route deduplication, keybinding-catalog movement,
or result-type redesign under the same tracking objective unless they receive a
separate reviewed plan.

Rollback is dependency-ordered, not arbitrary: revert PR 3 before PR 2, then
PR 1 if desired. Reverting PR 2 while PR 3 remains would restore a `running=`
caller against a constructor that no longer accepts it.

## Verification Gates

Focused baseline and regression:

```bash
.venv/bin/python -m pytest \
  tests/tui/test_input_routing.py \
  tests/harnesstui/conversation/test_input.py \
  tests/harnesstui/conversation/test_clipboard_input.py \
  tests/coding/test_screen_coding_tui_input.py \
  --skip-host-runtime \
  -q
```

Boundary and playback:

```bash
.venv/bin/python -m pytest \
  tests/tui/test_import_boundaries.py \
  tests/harnesstui/testing/test_import_boundaries.py \
  tests/harnesstui/testing/test_input_playback.py \
  tests/harnesstui/testing/test_screen_loop_playback.py \
  --skip-host-runtime \
  -q
```

Coding conversation playback and loop:

```bash
.venv/bin/python -m pytest \
  tests/coding/test_screen_tui_playback_harness.py \
  tests/coding/test_screen_coding_tui_loop.py \
  --skip-host-runtime \
  -q
```

Broader subsystem regression:

```bash
.venv/bin/python -m pytest tests/tui tests/harnesstui --skip-host-runtime -q
.venv/bin/python -m pytest \
  tests/coding \
  --skip-host-runtime \
  -m "not live and not tui_render_contract" \
  -q
```

Static checks:

```bash
.venv/bin/python -m ruff check \
  src/loushang/tui/input.py \
  src/loushang/harnesstui/conversation/input.py \
  tests/tui/test_input_routing.py \
  tests/harnesstui/conversation/test_input.py
git diff --check
```

## Risks And Mitigations

### Risk: public advanced callers rely on `running=`

Mitigation: repository and public-doc inventory is recorded; project version is
pre-1.0; PR description calls out the change; reopen TIO-DEC-005 if supported
external consumers are identified before implementation.

### Risk: Ctrl+C/Escape behavior changes in generic examples

Mitigation: migrate the stateful demo adapter first; distinguish jump cancel
from unconsumed prompt cancel; and keep surface, focused-editor, completion, and
jump-mode priority regressions for both Escape and Ctrl+C.

### Risk: generic change accidentally alters Coding conversation behavior

Mitigation: Coding does not use generic `InputRouter`; run the full focused
Coding screen input suite and HarnessTUI playback anyway.

### Risk: contributors interpret retained keybinding entries as retained
ownership

Mitigation: document TIO-DEC-006 and add a package-wide AST producer gate.
Catalog placement and retained literal declarations are not permission for any
generic TUI module to produce conversation actions.

### Risk: temporary route duplication persists indefinitely

Mitigation: record deduplication as a named deferred follow-up, but do not make
it a hidden completion requirement for this high-risk semantic cut.

## Success Criteria

- Generic `InputRouter` has no `running` or `steering_supported` state.
- Generic input code defines no `SubmitMode` and constructs no `steer` or
  `follow_up` intent.
- Generic `InputRouter` does not emit a queued-message edit command.
- Generic unconsumed cancel produces `prompt_cancel`, not run abort.
- Escape/Ctrl+C that terminates a pending jump produces no `prompt_cancel`,
  while active surface, focused editor, and completion priorities remain intact.
- A package-wide producer gate rejects steer, follow-up, or queued-edit intent
  direct constant construction anywhere under `src/loushang/tui/` and tests
  both positional and keyword call forms.
- Public constructor configuration after `surface_host` is keyword-only,
  `_jump_mode` is not constructor state, and old third positional calls fail.
- HarnessTUI remains the only owner of running Enter, running Alt+Enter,
  pending-steer cancel, queue restore, and conversation abort behavior.
- Coding conversation keyboard behavior is unchanged.
- Active surface, completion, selection, history, paste, jump, resize, and
  editing regressions pass.
- Public TUI documentation describes the neutral boundary.
- The production patch contains no route deduplication, keybinding catalog
  migration, or Product-policy redesign.

## Review Ledger

| Finding | Priority | Disposition | Resolution in `r7` |
| --- | --- | --- | --- |
| Initial proposal combined semantic cut and whole-router deduplication. | P1 | Changes requested | Deduplication is explicitly deferred; first tranche changes ownership only. |
| Removing public constructor knobs could create an unbounded compatibility project. | P1 | Accepted with constraint | Direct removal is allowed only because version is 0.1.0, production has no caller, and public guides do not document the knobs; reopen if contrary evidence appears. |
| Reusing `abort` for generic cancel would retain conversation meaning. | P1 | Changes requested | Added distinct `prompt_cancel`; generic router no longer decides active-work abort. |
| Moving keybinding catalogs now would expand the patch across settings and Products. | P2 | Deferred | Catalog composition is a separately reviewed follow-up. |
| Optional-field `ConversationInputResult` invites invalid combinations. | P2 | Deferred | Tagged-result migration is separate from ownership cut. |
| Old target-decoupling design still assigns running semantics to generic TUI. | P2 | Changes requested | This spec explicitly supersedes only that portion and retains the target adapter work. |
| Full Coding policy injection is not necessary to cut TUI ownership. | P3 | Retained as follow-up | HarnessTUI current default remains behavior-compatible for this tranche. |
| The initial task ordering mixed passing characterization with target red tests, making the PR 1 gate ambiguous. | P1 | Changes requested | PR 1 now contains current-behavior characterization only; target red tests and ownership gates begin and land in PR 3. |
| Removing `steer`/`follow_up` from the shared `InputIntentKind` envelope adds API churn without changing router ownership. | P1 | Changes requested | Retain the literal members for now; forbid generic `InputRouter` from constructing them and defer envelope cleanup. |
| Durable ownership docs were assigned to different PRs in the design and implementation plan. | P2 | Changes requested | PR 1 now contains reviewed decision artifacts and current characterization only; current architecture and public contract docs migrate with PR 3. |
| Unconditional `prompt_cancel` would leak Escape/Ctrl+C after cancelling pending jump mode. | P1 | Changes requested | Added an explicit consumed-jump rule after surface/focused-editor/completion priority plus combination regressions. |
| The semantic-cut PR also contained a stateful example event-loop rewrite. | P2 | Changes requested | Added a separately mergeable example-adapter PR before the public router cut. |
| Example snapshot/scripted smoke does not execute the interactive event loop. | P2 | Changes requested | Added static/import checks and an explicit recorded PTY/terminal acceptance sequence. |
| Class-scoped ownership gates do not protect the declared TUI package boundary. | P2 | Changes requested | Producer gate now scans all `src/loushang/tui/**/*.py`, with narrow legacy-literal and generic-abort exceptions. |
| KD-003 would retain ambiguous Product-vs-HarnessTUI classification language. | P2 | Changes requested | KD-003 is now a required PR 3 migration document. |
| Direct public API removal needs a durable migration contract. | P3 | Changes requested | Added signature tests and a persistent pre-1.0 migration note with replacement examples. |
| Removing dataclass fields would silently rebind old third/fourth positional arguments. | P1 | Changes requested | Added a `KW_ONLY` constructor boundary, `init=False` internal jump state, exact signature tests, and a loud-failure migration contract. |
| The example completion-cancel manual gate is unreachable and old/new cancel adaptation was underspecified. | P1 | Changes requested | Removed the unreachable manual step, specified a single-execution dual-version adapter, and require a zero-diff example re-run after PR 3. |
| A custom jump binding can overlap cancel and trigger the current repeated-jump early return. | P2 | Changes requested | Compute cancel first, forbid early return on overlap, and add surface/focused-editor/completion overlap regressions. |
| AST wording claimed more than direct constant analysis can prove. | P2 | Changes requested | Gate positional/keyword constant producers with checker self-tests; explicitly defer structural dynamic-envelope proof. |
| Required HarnessTUI playback does not directly cover Coding steer/follow-up/abort paths. | P2 | Changes requested | Added the Coding playback and loop files as explicit mandatory gates. |
| Example baseline text misstates idle Ctrl+C and Alt+Up behavior. | P2 | Changes requested | Record Ctrl+C normalization as an intentional example fix and constrain Alt+Up to last pending follow-up. |
| Sandbox-safe pytest examples omitted `--skip-host-runtime`. | P3 | Changes requested | All required pytest commands now use the repository sandbox flag. |
| PR 2 and PR 3 were described as independently reversible despite a constructor dependency. | P2 | Changes requested | Changed the claim to separately mergeable and documented rollback order PR 3, then PR 2, then PR 1. |
| PR 2 did not freeze idle/running exit-command behavior. | P2 | Changes requested | Exit classification now precedes submit policy and is part of the before/after interaction matrix. |
| Durable docs overstated current Coding capability injection. | P2 | Changes requested | State the invariant that policy stays above TUI, the current HarnessTUI steer default, and deferred Coding injection. |
| Custom overlap lacked a no-pending-jump direct cancel test. | P3 | Changes requested | Added a no-pending overlap case requiring `prompt_cancel` rather than entering jump mode. |
| AST gate did not explicitly cover attribute-form `InputIntent` constructors. | P3 | Changes requested | Checker and self-tests now cover both `ast.Name` and `ast.Attribute` constructors. |

## Review Verdict

**Final independent acceptance: Accept.**

Revision `r7` has no open P0, P1, P2, or P3 findings. The five Round 3
resolutions and retained `r6` safeguards were independently verified. The
tracking issue and high-risk workflow remain prerequisites for production
implementation.
