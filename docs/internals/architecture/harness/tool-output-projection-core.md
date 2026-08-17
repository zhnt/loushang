# Tool Output Projection Core Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

This work is developed in the Harness lane because it changes the shared
cross-product execution path. Package ownership still follows dependency
direction: the core contract belongs below Harness rather than being placed in
`loushang.harness` merely because the migration uses that lane.

## Ownership Stack

```text
loushang.foundation.json       # canonical strict JSON value algebra
  -> loushang.ai               # durable AI message schema and codec
  -> loushang.agent            # raw tool result plus boundary projectors
  -> loushang.harness          # strict journals and shared presentation runtime
  -> Product adapter           # event/RPC schemas, artifacts, UI, domain details
```

`loushang.foundation.json` owns `JSONValue` for the strict wire algebra used by
this core, plus `JsonValueError`, validation, copying, and JSON dumping with
`allow_nan=False`. It accepts only null, exact built-in booleans, valid UTF-8
strings, encoder-supported integers, finite floats, exact lists, and exact
string-keyed dictionaries. It rejects scalar and container subclasses,
unpaired Unicode surrogates, and values that validate but cannot be encoded by
the runtime. It never implicitly converts `Path`, tuple, set, dataclass, enum,
bytes, arbitrary `__dict__`, or an unknown object through `repr()`. Diagnostic
error paths escape control characters and bound attacker-controlled key text.

Today, all production consumers use canonical `loushang.foundation.json`; the
retired `loushang.protocol` package no longer provides a second entry point.

The contract lives below AI because AI, Agent, Harness, Work, Channel, and
future products all need the same wire-value invariant. AI must not import
Agent or Harness, and Agent must not import Harness.

`loushang.foundation.observability` owns the canonical diagnostics runtime and
uses `loushang.foundation.json.JSONValue`. Diagnostic projection remains an
explicit canonical policy for log and Problem details; it is not a second JSON
algebra. `ai.structured` validates schemas through strict `foundation.json`,
and transcript, event, journal, Channel, and product wire schemas must do the
same.

Foundation -> AI -> Agent -> Harness -> Product dependency direction is read
from lower owner to higher consumer.

## Agent Ownership

`loushang.agent.tool_output` owns:

- `ToolOutputProjector[TDetails]`;
- `StrictJsonToolOutputProjector`, the default for already-JSON details;
- `FunctionalToolOutputProjector`, the explicit adapter for domain records;
- `ToolOutputProjectionError`, including target, path, and source value type;
- `ToolOutputPreviewPolicy`, for bounded diagnostic previews.

`AgentToolResult[TDetails]` keeps raw domain details for in-process tool and
product logic while exposing four explicit views:

| View | Purpose |
| --- | --- |
| transcript | durable `ToolResultMessage.details` and replay |
| event | product-neutral Agent event serialization |
| hook | extension/observer-safe metadata |
| diagnostic preview | deterministic bounded logs, never durable state |

Transcript, event, and hook projections are snapshotted independently on first
access. Repeated serialization returns a fresh strict-JSON copy of that
snapshot, so later mutation of raw details and stateful projector callbacks
cannot change an already-observed wire payload. The result wrapper performs
the snapshot copy even for independently implemented projector protocols, not
only for the built-in projectors.

Tools returning JSON-native details need no adapter. A tool returning a domain
dataclass or another rich object must provide a projector at construction. A
hook that replaces details must also provide the matching projector; otherwise
the replacement uses the strict JSON default. Content-only hook changes retain
the existing projector. Omitted hook details remain distinguishable from an
explicit JSON null without exposing a sentinel through the public `details`
field; copying and pickling preserve that distinction. Hook `is_error` and
`terminate` overrides accept only exact built-in booleans or null. A composed
hook pipeline recomputes `hook_details` whenever details or the projector
changes, so later observers never receive a new raw result paired with a stale
safe view.

## Projection Timing And Failure

Partial tool updates snapshot and validate the event projection synchronously
inside the update callback, before control returns to the tool. An invalid
update is dropped and records
`tool_output_update_projection_failed`; raw details are not emitted.

Content snapshots validate both the strict JSON representation and the known
`TextPart` / `ImagePart` field schema. A dataclass instance with an invalid
runtime field type is a projection failure even when its encoded value belongs
to the JSON algebra. Terminal `is_error` and `terminate` values also require
exact built-in booleans before an event or message is emitted; no arbitrary
truthiness is evaluated. A structured fallback forces an invalid `terminate`
value to false and `is_error` to true, so the fallback itself remains encodable.

Final results validate any required hook view before the hook runs, then
validate transcript and event views before the terminal event or transcript
message is published. The terminal emit boundary enforces this invariant for
executed tools and immediate preparation/validation failures alike. A failure
becomes an error tool result with the stable code
`tool_output_projection_failed` and JSON details containing `target`, `path`,
and `valueType`. The raw unprojectable value is not copied into a journal,
event payload, hook payload, or diagnostic record.

Projector exceptions are an untrusted boundary too. Their target, path, and
value-type metadata is validated and bounded before it can enter an error tool
result or diagnostic record. An after-tool hook failure preserves the tool's
existing `terminate` decision, so observability or extension failure cannot
silently resume a run that the tool ended.

Projection callbacks are expected to be deterministic and side-effect free.
The first-access snapshot prevents repeated downstream encoders from invoking
them again for the same view.

## AI, Harness, And Product Adoption

`ToolResultMessage.details` is a `JSONValue`, and the AI message codec validates
it without compatibility coercion. Existing JSON transcripts remain readable;
only attempts to write new non-JSON details now fail. The message also persists
the opt-in `terminate` bit so live and replay presentation retain the same
terminal status.

Coding's transcript reader provides the narrow legacy exception for session
files produced by the former writer: non-finite number tokens are preserved as
their string spelling, unpaired surrogate code units are preserved as escaped
text, and each affected line emits a `legacy_session_json_migrated` journal
diagnostic. The source file is not rewritten implicitly. Harness journal parsing
and every new append remain strict JSON. The syntax-only
`parse_legacy_jsonl_line()` helper is explicit and opt-in; it returns legacy
constants without assigning migration semantics, while Coding owns the value
conversion and writes the migrated temporary line with the strict Foundation
JSON dumper through the canonical Foundation contract.

Harness journal codecs validate every encoded mapping before opening a durable
write, reject non-standard constants and invalid strict values while reading,
and always dump with `allow_nan=False`. Harness presentation projects a live
result through its transcript view before calling a renderer and isolates the
renderer from the result's content list. This makes live rendering and replay
rendering consume the same result semantics.

The explicit `loushang.harnesswork.integrations.agent_session` bridge serializes Agent messages
with the AI codec, accepts an injected product message serializer for custom
Agent messages, and serializes tool update/end results with the Agent event view. It
strictly snapshots every payload before constructing a `WorkEvent`. In-memory
and JSONL event logs enforce the same strict snapshot contract. Channel
envelope encoding validates the complete wire object, while decoding uses
exact schema types rather than `str()` or `int()` coercion. None of these
boundaries retain `asdict()`, tuple, datetime, `__dict__`, or `repr()`
fallbacks. The bridge is the documented dependency exception and is exposed
lazily from the Work package root; importing Work or Channel protocol types
does not load Agent or AI. Unrelated Work runtime modules remain independent of
Agent.

Coding remains responsible for its session and transport schemas:

- session entry codecs accept only strict JSON metadata;
- `BranchSummaryDetails` has an explicit `readFiles` / `modifiedFiles`
  projection before entering the session store;
- context usage and HTML session stats explicitly project known dataclasses;
- Coding event serialization consumes the Agent event view;
- Coding error diagnostics consume projected event details rather than raw
  tool details;
- Coding RPC has a documented transport adapter for dataclasses, `Path`,
  mappings, lists, and tuples, but rejects cycles, sets, arbitrary objects,
  non-string keys, non-finite floats, `__dict__` discovery, and `repr()`
  fallback. RPC input parsing rejects non-standard JSON constants before
  command dispatch, and the Print JSON event sink enforces the same strict
  output algebra.

Product adapters still own tool-specific detail vocabulary, artifact meaning,
event field names, RPC compatibility, terminal/web rendering, and decisions
about which projection is appropriate for a product hook.

## Non-Goals

This core does not:

- move product event or transcript schemas into Harness;
- make Harness depend directly on AI;
- serialize credentials or auth state;
- infer domain semantics from arbitrary Python objects;
- treat a log preview as a recoverable durable representation;
- require every projection target to expose identical metadata.

## Validation

The boundary is complete while all of these remain true:

- strict JSON tests cover nested paths, cycles, enum/scalar subclasses,
  non-finite floats, Unicode surrogates, encoder limits, copying, and small
  preview limits;
- Agent tests cover distinct target views, first-access snapshots, explicit
  projectors, update/final failure behavior, and structured diagnostics;
- journal tests prove a `Path` cannot reach JSONL and non-standard JSON cannot
  enter from an existing file;
- Work and Channel tests prove Agent event projection reaches durable payloads
  without raw result or `repr()` fallback, malformed Work record fields are
  rejected without coercion, and importing Channel does not load Agent or AI;
- Coding tests cover event, RPC, branch-summary, print, export, and transcript
  compatibility;
- architecture tests preserve the Foundation -> Protocol compatibility -> AI
  -> Agent -> Harness -> Product dependency direction;
- the full non-live repository test suite passes.
