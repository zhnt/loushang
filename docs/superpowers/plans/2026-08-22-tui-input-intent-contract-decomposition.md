# TUI Input Intent Contract Decomposition Plan

Status: approved after three independent re-reviews
Base: `3b6872d83fd123bfc70987495c58ab1cbb267dc6`
Branch: `tui/input-intent-contract-plan`
Tracking issue: none by request

## Objective

Replace the closed, cross-package `InputIntentKind` literal with an extensible
typed intent envelope while preserving the value-level `InputIntent` protocol,
every existing intent string, all routing order, and all keyboard behavior.

Land the implementation as one coherent multi-file PR. The PR must make the
generic envelope usable by TUI surfaces and presentation adapters without
introducing a plugin host or combining this contract migration with
prompt-routing deduplication.

## Current State

`loushang.tui.input.InputIntent` is used for two different purposes:

1. generic prompt-router output such as `submit`, `prompt_cancel`, and
   `invalidate_render`;
2. surface and extension actions such as `select`, `setting`,
   `approval_decision`, `surface_close`, and `consumed`.

Those purposes currently share one closed `InputIntentKind = Literal[...]`.
The literal also retains `steer` and `follow_up`, even though generic TUI is
forbidden from constructing them and HarnessTUI now represents them with
`ConversationSteerResult` and `ConversationFollowupResult`.

The closed literal creates three debts:

- an adapter-defined surface intent requires editing the generic TUI type;
- HarnessTUI converts structural surface results with
  `cast(InputIntentKind, kind)`, hiding rather than expressing extensibility;
- prompt-router and surface contracts appear more tightly coupled than their
  runtime behavior requires.

The preceding work has already completed the adjacent migrations:

- generic TUI no longer decides conversation steer/follow-up/abort semantics;
- HarnessTUI conversation results are a discriminated union;
- Harness declares steer/follow-up delivery capabilities;
- HarnessTUI owns the steer-first default interaction policy;
- keybinding defaults are composed by owner;
- HarnessTUI owns the standard conversation clipboard-image profile.

## Decision Summary

Keep one runtime `InputIntent` data class, but parameterize its `kind` type with
a covariant string-bound type variable. Treat `InputIntent[str]` as the open
surface/extension envelope and use narrower aliases at producer boundaries.

Illustrative target shape:

```python
_InputIntentKindT = TypeVar("_InputIntentKindT", bound=str, covariant=True)


@dataclass(frozen=True, slots=True)
class InputIntent(Generic[_InputIntentKindT]):
    kind: _InputIntentKindT
    text: str = ""
    note: str = ""


PromptInputIntentKind: TypeAlias = Literal[
    "submit",
    "prompt_cancel",
    "invalidate_render",
]
PromptInputIntent: TypeAlias = InputIntent[PromptInputIntentKind]

# Temporary source-compatibility alias. Internal code must stop importing it.
InputIntentKind: TypeAlias = str
```

The exact type-variable and alias syntax may be adjusted to satisfy the
repository's Python and mypy versions, but these invariants are fixed:

1. there is one runtime `InputIntent` class, not parallel prompt and surface
   classes;
2. `kind`, `text`, and `note` retain their names, defaults, value equality,
   repr, `asdict()` output, supported pickle round-trip, and existing hand-written
   payload behavior; typing introspection is explicitly allowed to change;
3. the general envelope accepts admitted adapter-defined intent strings without
   a central TUI registration edit;
4. generic prompt producers have a narrow declared vocabulary;
5. `steer` and `follow_up` are not members of a TUI-owned closed type;
6. internal production code does not use the broad compatibility alias as a
   substitute for accurate annotations.

`PromptInputIntent` is a typing-only alias. It is not a second runtime class,
must not be used with `isinstance()`, and is not exported from the top-level
`loushang.tui` package.

## Ownership Model

### Generic TUI

Generic TUI owns:

- the runtime `InputIntent` envelope;
- prompt intent vocabulary produced directly by `InputRouter`;
- reusable built-in surface mechanics and their existing action strings;
- forwarding opaque surface/extension intents without interpreting product
  semantics.

Generic TUI does not own:

- conversation steer or follow-up results;
- product/plugin intent registration;
- HarnessTUI surface workflow dispatch;
- plugin lifecycle or discovery.

### HarnessTUI

HarnessTUI owns:

- interpretation of HarnessTUI surface intent strings;
- conversion of structural surface outputs into the open `InputIntent[str]`
  envelope;
- conversation wrapping through `ConversationSurfaceResult`;
- existing workflow dispatch by surface purpose and intent kind.

HarnessTUI must not cast admitted adapter strings into a TUI-owned closed
literal.

### Product, Presentation Adapters, And Future Plugins

TUI surfaces and HarnessTUI/Product presentation adapters may emit open strings
such as `example_plugin.openArtifact` through `InputIntent[str]`. A future
Plugin declaration does not import TUI or construct `InputIntent` directly.
The declaration must first pass the Presentation/Extension owner's admission
and binding process; only the host-side adapter may translate the admitted
declaration into this TUI envelope.

This tranche only makes the adapter-side data contract extensible. It does not
decide how plugins register handlers, contribute surfaces, or participate in
lifecycle management. Existing unnamespaced intent strings remain unchanged.
New external kinds should use an owner-qualified namespace, but namespace
authority and validation remain deferred to the future presentation-owner
contract and are not enforced here.

## Compatibility Policy

This is primarily a type-contract migration, not a value-level runtime protocol
migration.

Required compatibility:

- `InputIntent(kind="select", text="x")` remains constructible;
- equality against existing `InputIntent(...)` values remains unchanged;
- tuple ordering and event routing remain unchanged;
- `InputRouter.route()` continues forwarding surface intents;
- extension hooks continue accepting and returning `InputIntent` objects;
- no action string, physical key, status copy, or playback artifact changes;
- direct imports of `InputIntentKind` continue to resolve temporarily as
  `str`, but repository production code no longer imports it.

The compatibility alias preserves only its import path. Changing it from a
closed `Literal` to `str` intentionally changes `typing.get_args()` and other
typing introspection. Making `InputIntent` generic also changes annotation
metadata and requires strict external type consumers to write
`InputIntent[str]` instead of a bare `InputIntent`. Schema generators that
derive a protocol from annotations are not guaranteed to remain unchanged.

Value-level compatibility covers constructor arguments, fields, repr,
equality, `dataclasses.asdict()`, supported pickle round-trip, and existing
hand-written playback payloads. The compatibility alias is deliberately open
and temporary. It must carry a deprecation comment and must not be re-exported
from the top-level `loushang.tui` package. Removal can occur after external
presentation APIs settle; it is not part of this PR.

## Options Considered

### Option A: Only Delete `steer` And `follow_up`

Rejected. It removes stale names but keeps the central closed literal, so every
future adapter-owned intent still requires editing generic TUI.

### Option B: Move The Whole Literal To HarnessTUI

Rejected. TUI itself produces reusable surface intents, settings intents,
loader abort, and prompt intents. Moving the type would invert the accepted
dependency direction.

### Option C: One Concrete Data Class Per Intent Kind

Rejected for this tranche. Unlike `ConversationInputResult`, most
`InputIntent` values share the same small payload and intentionally permit
adapter-defined kinds. A large closed class union would recreate the extension
problem and cause unnecessary runtime/API churn.

### Option D: Open Generic Envelope With Narrow Producer Aliases

Selected. It preserves runtime compatibility, permits extensions, and lets
prompt producers retain static precision without a global whitelist.

## Non-Goals

- Do not change `ConversationInputResult` or its variant classes.
- Do not make `ConversationInputRouter` delegate to `InputRouter`.
- Do not extract or reorder text, paste, jump, completion, history, page,
  cancel, surface, or submit routing.
- Do not change the `SurfaceHost` event ordering or consumption contract.
- Do not introduce a plugin registry, handler registry, or manifest schema.
- Do not move approval, settings, selection, dialog, or continuity workflows
  between packages.
- Do not rename existing intent strings.
- Do not remove the temporary `InputIntentKind = str` compatibility alias.
- Do not change keyboard shortcuts or keybinding catalogs.
- Do not add tests for example scripts.

## Expected File Surface

The implementation should remain cohesive but is expected to cover at least
these production and test areas:

1. `src/loushang/tui/input.py`
2. `src/loushang/tui/surfaces.py`
3. `src/loushang/tui/extensions.py`
4. `src/loushang/tui/feedback.py`
5. `src/loushang/tui/ui_parts/widgets/dialog.py`
6. `src/loushang/harnesstui/surface/view.py`
7. `src/loushang/harnesstui/selection/model.py`
8. `src/loushang/harnesstui/conversation/input.py`
9. `src/loushang/harnesstui/conversation/application_host.py`
10. `src/loushang/harnesstui/conversation/screen_runner.py`
11. `src/loushang/harnesstui/surface/controller.py`
12. `src/loushang/harnesstui/surface/workflow.py`
13. `src/loushang/harnesstui/testing/input_playback.py`
14. `tests/tui/test_input_routing.py`
15. `tests/tui/test_extension_hooks.py`
16. `tests/tui/test_widgets_command_palette.py`
17. `tests/tui/test_import_boundaries.py`
18. focused HarnessTUI surface, selection, conversation, and playback tests
19. architecture documentation and ownership gates

Mechanical annotation-only changes may extend beyond this list. Any file with
runtime branch changes requires an explicit justification in the PR.

## Implementation Plan

### Task 0: Freeze The Baseline

1. Use the long-lived TUI worktree on a clean implementation branch based on
   the latest `origin/main`.
2. Record direct `InputIntentKind` import sites and all `InputIntent` producers.
3. Freeze the complete production annotation inventory and classify every bare
   `InputIntent` occurrence as an annotation, constructor, or `isinstance`
   check.
4. Inspect the active Harness plugin-foundation lane for overlapping files,
   record the intended landing order, and require that lane to synchronize with
   the resulting `main` before integration. Do not merge or edit the other lane.
5. Run focused TUI input, extension, surface, and HarnessTUI surface tests
   outside the managed Codex sandbox on the first attempt, retaining
   `--skip-host-runtime`.
6. Run the repository's non-live/host-safe broader suite and dedicated render
   contract outside the managed sandbox on the first attempt.
7. Record current test counts and the base commit in the implementation plan or
   PR description.

### Task 1: Characterize Runtime Behavior And Add Type Contract Fixtures

First add green characterization tests for behavior that already works at
runtime despite the current closed annotation:

1. `InputIntent` accepts an owner-qualified custom kind;
2. a custom kind round-trips through the TUI extension adapter;
3. a custom surface kind forwards through `SurfaceHost` and `InputRouter`;
4. HarnessTUI structural surface normalization preserves an arbitrary string,
   including the currently accepted empty string.

Then add a dedicated mypy fixture, for example
`tests/typing/input_intent_contract.py`, and run it explicitly with
`--warn-unused-ignores`. The fixture must prove:

1. an admitted custom kind is valid through `InputIntent[str]`;
2. the compatibility alias remains importable;
3. a wrong kind passed to the narrow prompt factory is rejected;
4. covariance permits `InputIntent[Literal[...]]` to flow to
   `InputIntent[str]`, but not in the opposite direction.

Use targeted `# type: ignore[...]` assertions for expected errors so
`warn_unused_ignores` fails if the contract becomes accidentally broad. Add
red source/architecture gates proving:

1. no generic TUI producer constructs `steer` or `follow_up`;
2. production code outside the compatibility declaration no longer imports
   `InputIntentKind`;
3. production annotations do not use a bare `InputIntent` generic. Constructor
   calls and `isinstance(value, InputIntent)` remain allowed.

Do not commit a red-only step. The final implementation commit lands green.

### Task 2: Generalize The Runtime Envelope

In `src/loushang/tui/input.py`:

1. parameterize `InputIntent` by a covariant string-bound kind type;
2. add the narrow prompt vocabulary and prompt intent alias;
3. replace the closed `InputIntentKind` literal with the temporary `str`
   compatibility alias;
4. add a private `_prompt_input_intent()` factory that accepts only
   `PromptInputIntentKind`, and route every TUI-owned `submit`,
   `prompt_cancel`, and `invalidate_render` construction through it;
5. annotate prompt-only constructors and `submit()` narrowly;
6. annotate `route()` and surface forwarding with `InputIntent[str]`, because
   the public router intentionally forwards opaque surface results;
7. retain all runtime constructor arguments and values unchanged.

Do not claim that `InputRouter.route()` is prompt-only while it still accepts a
`surface_host`. The broad return annotation at that boundary is intentional.

### Task 3: Migrate Generic TUI Consumers

1. Replace `InputIntentKind` annotations on configurable `select_kind` and
   dialog helpers with `str` or a local narrow alias where the owner is closed.
2. Parameterize extension hook boundaries as `InputIntent[str]`.
3. Parameterize built-in surface and feedback results with the narrowest local
   vocabulary that remains readable.
4. Eliminate bare `InputIntent` annotations throughout the frozen production
   inventory; use `InputIntent[str]` or an owner-local narrow alias.
5. Preserve all literal values and routing branches.
6. Keep the top-level `loushang.tui.InputIntent` export unchanged, but do not
   top-level export `PromptInputIntent` or its kind alias.

Avoid creating one global `TuiSurfaceIntentKind` literal that merely recreates
the old central whitelist under another name.

### Task 4: Migrate HarnessTUI Consumers

1. Change surface view, selection, conversation, application-host, runner,
   surface controller/workflow, and playback boundaries to accept
   `InputIntent[str]`.
2. Remove `cast(InputIntentKind, kind)` from structural normalizers.
3. Preserve the current structural acceptance rule exactly: reject non-string
   kinds, but continue accepting every string including `""`. Do not add
   namespace or non-empty validation. Preserve `text` and `note` conversion
   behavior.
4. Keep `ConversationSurfaceResult` as the conversation boundary wrapper.
5. Do not change workflow dispatch branches or surface-purpose interpretation.

### Task 5: Architecture Gates And Documentation

1. Extend the TUI producer gate so `steer` and `follow_up` cannot re-enter
   generic TUI through direct construction.
2. Add a gate requiring `InputIntentKind` production imports to disappear while
   allowing its single compatibility declaration.
3. Add an annotation gate rejecting bare `InputIntent` in production type
   annotations while allowing construction and runtime `isinstance` checks.
4. Add an open TUI surface-intent contract test using an owner-qualified kind;
   state explicitly that this is not a Harness Plugin API.
5. Update the TUI editing/reference documentation with the open-envelope rule,
   strict external type-consumer migration, and typing-introspection break.
6. Update the HarnessTUI architecture document with the interpretation
   boundary.
7. Mark deferred item #3 (`ConversationInputResult` discriminated union) as
   completed by PR #476.
8. Record that router deduplication remains the next independent tranche.

### Task 6: Static And Behavioral Validation

Run every pytest command and every Make target that invokes pytest outside the
managed Codex sandbox on the first attempt, as required by the workspace guide
for the verified asyncio selector self-pipe failure. Retain
`--skip-host-runtime`, `not live`, and other safety selectors; this rule does
not authorize live or network tests. Pure Ruff, mypy, source inspection, and
documentation checks may run inside the sandbox. This type migration does not
require Host Runtime coverage; if it is run for additional confidence, use the
dedicated `make test-host-runtime` target in an appropriate environment and
report it separately.

Required focused checks:

```bash
.venv/bin/python -m pytest \
  tests/tui/test_input_routing.py \
  tests/tui/test_extension_hooks.py \
  tests/tui/test_surfaces.py \
  tests/tui/test_widgets_command_palette.py \
  tests/tui/test_import_boundaries.py \
  tests/harnesstui/conversation/test_input.py \
  tests/harnesstui/surface \
  tests/harnesstui/selection \
  tests/harnesstui/testing/test_input_playback.py \
  --skip-host-runtime \
  -q
```

Required type-contract check:

```bash
uv --cache-dir .uv-cache run --extra dev mypy \
  --warn-unused-ignores \
  tests/typing/input_intent_contract.py
```

Required static and broader checks:

```bash
uv --cache-dir .uv-cache run --extra dev ruff check \
  src/loushang/tui tests/tui tests/typing/input_intent_contract.py
make lint-harnesstui
make typecheck-tui
make typecheck-harnesstui
make check-architecture-docs
make test-sandbox
make test-tui-render-contract
git diff --check
```

The host-safe suite excludes only demonstrated Host Runtime cases. The
dedicated render-contract target is complementary and must also pass. Record
both selected and deselected counts rather than treating an intentional marker
split as missing coverage. Cross-platform deterministic render, terminal
platform, Windows shell, Harnesstui quality, and Harness quality remain required
CI gates after publication.

### Task 7: Review, Commit, And PR

1. Perform a source scan for every remaining `InputIntentKind` import and every
   `steer`/`follow_up` occurrence under generic TUI.
2. Confirm the diff contains no route-order or shortcut changes.
3. Commit the production, tests, gates, and documentation as one coherent
   change; do not split per file or per alias.
4. Create one PR against `main` without a tracking issue.
5. PR description must state:
   - value-level `InputIntent` compatibility and typing-introspection break;
   - open presentation-adapter kind behavior;
   - narrow prompt producer typing;
   - temporary compatibility alias;
   - strict external type migration from `InputIntent` to `InputIntent[str]`;
   - Plugin declarations require Presentation owner admission and do not import
     TUI;
   - explicit exclusion of router deduplication and plugin lifecycle;
   - local test counts and CI status.
6. Wait for all cross-platform CI before merging.

## Acceptance Matrix

| Scenario | Required result |
| --- | --- |
| Idle Enter with text | Existing `submit` intent, same text/history behavior |
| Escape with unconsumed prompt | Existing `prompt_cancel` intent |
| Resize/SIGWINCH | Existing `invalidate_render` intent |
| Built-in selection surface | Existing `select`/`surface_close` values |
| Loader cancel | Existing `abort` value |
| TUI/presentation adapter emits `example_plugin.openArtifact` | Value reaches consumer unchanged |
| Structural HarnessTUI surface emits custom string | Wrapped without closed-literal cast |
| Structural HarnessTUI surface emits empty string | Existing acceptance remains unchanged |
| Conversation running Enter | Existing `ConversationSteerResult` behavior |
| Conversation running Alt+Enter | Existing `ConversationFollowupResult` behavior |
| Generic TUI source scan | No steer/follow-up producer |
| Runtime value compatibility | Constructor, repr, equality, asdict, supported pickle and payloads remain stable |
| Playback/render contracts | No artifact or frame change |

## Review Checklist

- [ ] One runtime `InputIntent` class remains.
- [ ] `kind`, `text`, and `note` runtime behavior is unchanged.
- [ ] The open envelope does not require central TUI registration for admitted
      adapter kinds.
- [ ] Prompt producers retain narrow type declarations.
- [ ] Prompt producers use the narrow private factory rather than relying on
      contextual generic inference.
- [ ] `InputIntentKind` is only a temporary `str` compatibility alias.
- [ ] Repository production code no longer imports the compatibility alias.
- [ ] Production annotations contain no bare `InputIntent` generic.
- [ ] No new global closed surface-kind whitelist is introduced.
- [ ] HarnessTUI no longer casts custom strings into a TUI-owned literal.
- [ ] Structural normalizers still accept every string, including empty.
- [ ] `steer` and `follow_up` remain HarnessTUI conversation result kinds only.
- [ ] `abort` remains available to generic cancellable UI feedback.
- [ ] Future Plugin declarations remain TUI-independent and require owner
      admission before adapter conversion.
- [ ] No event-routing branch or shortcut changes.
- [ ] No plugin lifecycle or handler registry is introduced.
- [ ] No prompt-routing deduplication is included.
- [ ] Focused and full pytest run outside the managed sandbox on the first
      attempt while retaining all non-live and host-safety selectors.

## Rollback

The generic type declaration, TUI annotations, HarnessTUI annotations,
architecture gates, and tests form one atomic compatibility unit. Revert the
single implementation commit if external type consumers or cross-platform CI
expose an incompatibility. Because runtime values and routing are unchanged,
rollback requires no persisted-data or settings migration.

## Deferred Next Tranche

After this contract is green, plan prompt-routing deduplication separately.
That work may extract neutral stages for text/paste, jump, completion, history,
and page navigation, but must preserve the explicit HarnessTUI ordering around
queue edit, transcript, cancel/abort, clipboard paste, running submit policy,
and local commands. It must not be folded into this PR.
