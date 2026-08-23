# HarnessTUI Discriminated Conversation Input Outcomes

Status: implementation complete; author review passed; PR review pending
Tracking: #475
Base: `f97ac58a6b5197e673ff29d70bd90eac3c9c12ca`

## Decision Summary

Replace the optional-field `ConversationInputResult` data class with a closed
union of immutable result variants. Each variant represents one primary routed
outcome and carries only the payload valid for that outcome. The screen runner
dispatches the union exhaustively. Playback continues to emit its current
default artifact fields through a compatibility serializer.

This is a HarnessTUI result-boundary refactor. It does not alter generic TUI
routing, conversation key interpretation, or product policy.

## Current Problem

`ConversationInputResult` currently exposes these independent fields:

- prompt text and attachments;
- local-command text;
- steer text and attachments;
- follow-up text and attachments;
- one surface intent;
- one clipboard outcome;
- an abort flag;
- an exit code;
- a render flag.

All fields have independent defaults. Invalid states such as a prompt and exit
in the same result, attachments without their text, or abort plus steer are
therefore constructible. The standard router does not intentionally create
those states, but neither its type nor its constructor prevents them.

The looseness propagates into consumers:

- `screen_runner.py` probes every optional field in sequence and can dispatch
  more than one action for one event;
- playback defines a structural port that repeats the optional field bag;
- the default playback serializer must know every field independently;
- test routers construct the loose data class directly.

The source baseline contains 46 direct `ConversationInputResult(...)`
constructions. Focused pre-change baselines are 30 passing HarnessTUI tests and
82 passing Coding compatibility tests.

## Goals

- One input event has exactly one result variant.
- Each result variant owns only its valid payload.
- Text and attachments cannot become detached.
- Handled-with-render and ignored-without-render are explicit outcomes.
- Runner dispatch is exhaustive and cannot silently ignore a new variant.
- Playback remains product-neutral.
- Existing default playback artifact keys and values remain stable.
- HarnessTUI and Coding keyboard behavior remains byte-for-byte compatible at
  the existing playback and loop boundaries.

## Non-Goals

- Changing `loushang.tui.InputRouter` or its `InputIntent` envelope.
- Reusing generic `InputRouter` from `ConversationInputRouter`.
- Reordering surface, completion, cancel, queue, clipboard, or submit routing.
- Changing running Enter, Alt+Enter, Escape, or Ctrl+C semantics.
- Moving keybindings between generic and conversation catalogs.
- Injecting new Coding capability or submit policy.
- Redesigning clipboard staging or attachment storage.
- Changing the default playback artifact schema.

## Result Model

Use frozen, slotted data classes with an `init=False` literal `kind` field. The
supported result type is a closed union alias:

```python
@dataclass(frozen=True, slots=True)
class ConversationInputHandled:
    kind: Literal["handled"] = field(default="handled", init=False)
    render_requested: bool = field(default=True, init=False)


@dataclass(frozen=True, slots=True)
class ConversationInputIgnored:
    kind: Literal["ignored"] = field(default="ignored", init=False)
    render_requested: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ConversationPromptResult:
    text: str
    attachments: tuple[object, ...] | None = None
    kind: Literal["prompt"] = field(default="prompt", init=False)
    render_requested: bool = field(default=True, init=False)
```

The complete union contains:

| Variant | Kind | Payload |
| --- | --- | --- |
| `ConversationInputHandled` | `handled` | none |
| `ConversationInputIgnored` | `ignored` | none |
| `ConversationPromptResult` | `prompt` | `text`, `attachments` |
| `ConversationLocalResult` | `local` | `text` |
| `ConversationSteerResult` | `steer` | `text`, `attachments` |
| `ConversationFollowupResult` | `follow_up` | `text`, `attachments` |
| `ConversationSurfaceResult` | `surface` | `intent` |
| `ConversationClipboardResult` | `clipboard` | `outcome` |
| `ConversationAbortResult` | `abort` | none |
| `ConversationExitResult` | `exit` | `exit_code` |

The attachment payload remains `tuple[object, ...] | None` at this product-neutral
runner boundary. The standard router supplies `PromptImageAttachment` values,
while custom product adapters retain the previous ability to supply another
neutral attachment representation.

`ConversationInputResult` becomes the type alias over those ten classes. It is
no longer a constructible field bag. The concrete variants are the supported
construction API.

### Why Separate Handled And Ignored

The old empty result had two meanings:

- editor or surface state changed and should render;
- the event was ignored and should not render.

A free `render_requested` Boolean on every variant would preserve an invalid or
unnecessary state dimension. Two zero-payload variants retain the observable
scheduling distinction without allowing action results to opt out of their
normal render path.

### Why A Class Union Instead Of One Tagged Data Class

A single class with `kind` plus optional `text`, `attachments`, `intent`,
`outcome`, and `exit_code` would still permit invalid payload combinations and
would require runtime validation. Separate classes follow the existing
`ConversationIntent` union style and make payload validity visible to mypy.

## Router Migration

`ConversationInputRouter.handle()` and its helpers retain their current branch
order. Only result construction changes:

| Current construction | New construction |
| --- | --- |
| `ConversationInputResult()` | `ConversationInputHandled()` |
| `ConversationInputResult(render_requested=False)` | `ConversationInputIgnored()` |
| `prompt_text=..., prompt_attachments=...` | `ConversationPromptResult(text=..., attachments=...)` |
| `local_text=...` | `ConversationLocalResult(text=...)` |
| `steer_text=..., steer_attachments=...` | `ConversationSteerResult(...)` |
| `followup_text=..., followup_attachments=...` | `ConversationFollowupResult(...)` |
| `surface_intent=...` | `ConversationSurfaceResult(intent=...)` |
| `clipboard_outcome=...` | `ConversationClipboardResult(outcome=...)` |
| `abort_requested=True` | `ConversationAbortResult()` |
| `exit_code=...` | `ConversationExitResult(exit_code=...)` |

No helper is moved, shared, or reordered in this change.

## Runner Dispatch

The runner accepts the concrete closed union rather than a structural protocol
that reproduces all optional fields. Dispatch narrows by concrete variant and
ends with `assert_never(result)` so a newly added variant fails type checking
until the runner handles it.

Semantics remain:

- exit renders once and returns the requested code;
- abort performs the existing cancellation sequence and continues the loop;
- prompt starts the active prompt task;
- local, steer, follow-up, and surface call their existing handlers;
- clipboard and handled request a render but no external handler;
- ignored performs no action and does not request a render.

The runner must not dispatch more than one action from one result.

## Playback Compatibility

The testing ports use the same closed union. The generic result type parameter
is removed unless an implementation consumer is found that requires it; current
production and tests all use the standard HarnessTUI result contract.

`default_conversation_result_payload()` pattern-matches the variant and emits
the exact existing keys:

```text
prompt_text
prompt_attachment_count
local_text
steer_text
steer_attachment_count
followup_text
followup_attachment_count
surface_intent
abort_requested
exit_code
render_requested
```

No `kind` key is added in this tranche. This lets scenario snapshots remain a
behavioral oracle rather than turning the type migration into an artifact
migration. Clipboard results continue to serialize as a render-only neutral
result because that is the current artifact behavior.

## API Compatibility

`ConversationInputResult` is exported from its module `__all__`, but it is not
re-exported from the `loushang.harnesstui` or
`loushang.harnesstui.conversation` package roots and is not documented as a
public user API. Repository production has no custom result implementation.

The project is pre-1.0. Direct field-bag construction is intentionally replaced
by explicit variant construction. The PR must call out this migration and keep
the failure loud; it must not retain a permissive compatibility constructor
that recreates invalid combinations.

## Verification Strategy

### Contract tests

- each concrete result exposes the expected fixed `kind`;
- handled and ignored have fixed render behavior;
- payload variants contain only their valid dataclass fields;
- old field-bag construction fails loudly;
- the router returns the expected variant for every existing action path.

### Runner tests

- prompt attachment forwarding remains unchanged;
- exactly one handler runs for one primary result;
- ignored does not render;
- handled and clipboard render;
- abort and exit preserve their special control flow;
- a new union member produces a static exhaustiveness obligation.

### Playback tests

- existing scenario payloads remain identical;
- every variant maps to the old default payload schema;
- attachment counts and surface intent encoding remain unchanged.

### Regression gates

- the 30-test HarnessTUI focused baseline;
- the 82-test Coding input/playback baseline;
- full relevant HarnessTUI and Coding playback/loop suites;
- `make typecheck-tui` and `make typecheck-harnesstui`;
- Ruff and `git diff --check`;
- final repository CI, including cross-platform TUI gates.

All pytest commands run outside the filesystem sandbox on the first attempt due
to the workspace's verified selector/self-pipe `EPERM` failure inside it.

## Risks And Mitigations

### Risk: hidden custom router depends on structural result fields

Mitigation: repository and documentation inventory is clean; the change is
pre-1.0 and called out explicitly. Stop if a supported custom result producer is
identified during review.

### Risk: route order changes during mechanical constructor migration

Mitigation: do not move branches or helpers; compare the router's control-flow
diff independently from result declarations; run focused input playback before
and after.

### Risk: playback snapshots churn

Mitigation: serialize variants back to the current field schema and add direct
schema compatibility tests before updating any snapshot.

### Risk: runner accidentally changes multi-handler behavior

The current standard router creates one primary field at a time, so exhaustive
single-result dispatch preserves supported behavior. Add a regression proving
one variant calls only its matching handler.

### Risk: result union and intent union become confused

`InputIntent` and `ConversationIntent` describe inputs to other layers. The new
union describes the outcome of terminal event routing. Names retain the
`Result` suffix and no intent types move in this tranche.

## Stop Conditions

Return to design review if:

- a supported product needs to produce multiple primary actions for one event;
- a supported custom result type cannot migrate to the closed union;
- artifact compatibility requires changing existing playback snapshots;
- preserving behavior requires route-order or keybinding changes;
- the refactor begins to require generic/conversation route deduplication;
- focused input or runner baselines regress before implementation changes.

## Acceptance Criteria

- `ConversationInputResult` is a closed union of payload-valid variants.
- No optional-field result bag remains.
- Router result construction is variant-based with unchanged branch order.
- Runner dispatch is exhaustive and single-action.
- Playback default artifacts retain their current schema and values.
- HarnessTUI and Coding interaction regressions remain green.
- Both TUI typecheck targets remain at zero errors.
- No blanket ignore, route deduplication, keybinding move, or product-policy
  change enters the patch.

## Author Review Record

The implementation was reviewed against the baseline control flow before the
broader regression run. This is an author review, not an independent review.

| Finding | Priority | Resolution |
| --- | --- | --- |
| Text-action attachment payloads were initially narrowed to `PromptImageAttachment`, while the existing runner port deliberately accepts neutral `object` attachments. | P1 | Restored `tuple[object, ...] | None` on prompt, steer, and follow-up variants; the standard router still supplies concrete prompt-image attachments. |
| Transcript-open returns a dynamic render decision rather than a fixed action result. | P2 | Map success to `ConversationInputHandled` and failure to `ConversationInputIgnored`; do not restore a caller-controlled render Boolean. |
| The old structural result port appeared extensible, but the runner could only interpret its fixed optional fields. | P2 | Replace it with an alias to the closed union; keep the legacy port name as a type alias for annotation migration without admitting unknown runtime actions. |
| Playback compatibility could be claimed without covering every new variant. | P1 | Added a table-driven test over all ten variants and the exact legacy field schema; no `kind` artifact key was added. |
| Mechanical result replacement could accidentally reorder routing branches. | P1 | Reviewed the router diff separately; condition and helper order is unchanged. Focused and broad playback gates pass. |

Verification at author-review completion:

- HarnessTUI focused baseline: 30 passed before, 33 passed after three new
  result-contract tests;
- Coding input/playback compatibility: 82 passed before and after;
- complete TUI/HarnessTUI suite: 1765 passed;
- `make check-harnesstui`: 1270 passed, 65 marker-deselected;
- TUI mypy: 90 source files clean;
- HarnessTUI mypy: 139 source files clean;
- architecture documentation: 5 passed;
- focused Ruff and diff checks: clean.
