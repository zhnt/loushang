# Model Input Persistence And Capacity Recovery

## Status

Accepted corrective boundary following the capability-runtime convergence merged
in PR #451. Three internal reviews and one independent external review have been
incorporated. MIR1 through MIR4 and the standard MIR5 capacity path are
implemented locally. Dynamic account/endpoint limit discovery remains future
work; sections describing that discovery are normative targets rather than
claims about current behavior.

Current source and the following implemented documents remain authoritative:

- [Capability Runtime Convergence Plan](capability-runtime-convergence-plan.md);
- [Session And Model-Call Closure Boundary](session-model-call-closure-boundary.md);
- [Agent Transcript Profile Boundary](agent-transcript-profile-boundary.md); and
- [Agent Transcript File Store Boundary](agent-transcript-file-store-boundary.md).

The associated implementation and issue breakdown is recorded in
[Model Input Persistence And Capacity Recovery Tracking Draft](../../plans/2026-08-15-model-input-persistence-capacity-recovery.md).

## Decision Summary

The corrective work preserves PR #451's central guarantee:

```text
freeze the exact logical and Provider-visible request
  -> durably commit reconstructable Model Input facts
  -> recheck cancellation
  -> permit Provider transport
```

It changes the physical representation and failure/control boundaries:

1. append-growing Model Input values use an incremental, content-addressed v2
   representation instead of repeating one monolithic `messages` component;
2. existing v1 facts remain readable and are never rewritten implicitly;
3. every Provider attempt retains its pre-transport prepared snapshot, while
   one separate terminal outcome describes the logical invocation after all
   internal transport retries;
4. model selection is serialized with Session activity and validates stable
   context requirements before publishing a selection fact;
5. Provider failures remain typed across AI, Agent, and Harness boundaries;
6. exact or conservative request-capacity metrics are evaluated before durable
   Model Input commit and transport; and
7. overflow recovery uses bounded hierarchical compaction and at most one new
   logical recovery invocation.

This boundary does not introduce a second transcript authority, silently drop
model-visible content, rewrite historical record identities, or make UI text an
input to retry policy.

## Confirmed Defects

### Append-Growing Model Input Is Repeated

`SessionModelCallPreparer` projects the complete logical `messages` sequence on
every sampling boundary. `ModelInputTranscriptCommitter` materializes each
top-level logical and prepared mapping value as one component. Exact content
hashing deduplicates stable `system_prompt`, Tool, option, and header values, but
one appended message changes the hash of the entire message sequence.

For an un-compacted append-only run, the persisted message bytes therefore grow
piecewise as:

```text
|M1| + |M1,M2| + ... + |M1,...,Mn| = Theta(n^2)
```

Logical and prepared projections add separate copies. A base64 image retained
inside either sequence is repeated with every later changed component.

The file backend compounds the problem: each single-record append locks and
reloads the complete JSONL journal, while the transcript unit of work rebuilds
the repository from all records. When the file itself grows as `Theta(n^2)` and
each turn performs a bounded non-zero number of appends, the cumulative
read/rebuild path approaches `Theta(n^3)`. This is a source-level complexity
bound, not a wall-clock claim; an implementation benchmark is required.

### One Large Message Can Fail Before Transport

Every encoded Model Input record is limited to 1 MiB. Message-level splitting
alone is insufficient: one image or other large string can exceed the ceiling
inside one message. A compliant v2 representation must split large leaves and
must not increase the ceiling as a substitute for bounded records.

### Model Selection Is Published Before Compatibility Is Known

The current selection path commits `agent.model_selection` and then updates the
live Agent. Historical image compatibility is checked only in AI's final
preflight. Local model commands may also run while a sampling operation owns a
fresh Model Input committer. An intervening selection append correctly fails
the committer closed on revision mismatch and performs zero transport, but the
entire user turn fails.

### Structured Provider Failure Is Lost At The Agent Boundary

AI creates structured `AIErrorInfo`, but outer Agent failure handling reduces
arbitrary exceptions to `str(error)` and emits only a synthetic terminal
message. Retry and overflow policy subsequently infer semantics from public
error text. This makes distinct Provider HTTP 400 responses indistinguishable
and risks persisting sensitive data from non-AI exceptions.

Error assistants are removed during AI normalization and are not model-visible.
Aborted assistants are currently repaired into ordinary text turns and can be
model-visible. The corrective work must preserve that distinction rather than
treating every unsuccessful run as a Provider error.

### Compaction Is Unbounded And Omits Images

Current compaction serializes the selected textual conversation into one user
prompt without applying the target Provider's complete input budget. Images are
omitted without a placeholder or degradation diagnostic. A request can
therefore fail again during summarization, or can succeed while silently losing
image semantics.

## Scope

This boundary covers:

- the physical representation and reconstruction of Model Input components;
- Conversation JSONL append cost required by that representation;
- Model Input payload version and downlevel-reader policy;
- Session selection serialization and stable context requirements;
- AI-to-Agent structured model-call failures;
- logical invocation outcome facts;
- adapter-owned request-capacity metrics;
- bounded compaction and one-shot overflow recovery; and
- restart, cancellation, retry, branch, fork, and orphan semantics.

## Non-Goals

The first delivery does not:

- rewrite or delete v1 Model Input facts;
- replace ConversationStore with a global Blob Store;
- deduplicate immutable content across conversations or sibling branches;
- claim that Provider request construction or hashing becomes sublinear;
- persist arbitrary Provider response bodies;
- infer account entitlements from an optimistic model-catalog context window;
- make every Provider transport phase durable in the first outcome slice; or
- silently summarize an image with a text-only model.

## Required Invariants

The following invariants are non-negotiable:

1. **Commit before transport.** No Provider transport begins unless the exact
   prepared attempt is durably reconstructable and hash-verifiable.
2. **Same frozen payload.** Transport receives the payload whose hash was
   committed; no model-visible mutation occurs after the barrier.
3. **Append-only history.** Existing facts, record IDs, parents, revisions, and
   snapshot IDs are not rewritten by ordinary load, resume, or migration.
4. **Active-path reachability.** A snapshot references only facts reachable
   through its ancestor path. A branch never references a sibling-only node.
5. **Bounded records.** Every encoded Model Input record remains within the
   Store ceiling; large leaves are split rather than truncated.
6. **Fail closed.** Missing, wrong-kind, tampered, cyclic, too-deep, or
   cross-sibling references prevent reconstruction and transport.
7. **Typed policy.** Built-in retry and compaction policy consumes structured
   categories, never public UI prose.
8. **No diagnostic leakage.** Durable failures contain only allowlisted fields.
9. **Serialized selection.** Model publication cannot interleave with a current
   sampling commit sequence.
10. **Bounded recovery.** Compaction batches, merge depth, and logical recovery
    attempts all have explicit limits.

## Model Input Payload Version 2

### Record Versioning

The existing record kinds remain stable:

- `model.input.component`; and
- `model.input.prepared`.

Their v1 codecs and value types remain registered. V2 is represented by
`ConversationRecord.payload_version == 2` with separate codecs and value types;
the internal Model Input schema and projection versions are also explicit.

Mixed v1/v2 records are valid for a v2-aware reader. New writes use v2 only
after the downlevel-reader rollout gate is satisfied.

### Downlevel Reader Policy

The current generic decoder preserves an unknown kind or payload version as an
opaque value. That behavior is appropriate for optional extension facts but is
unsafe for required Model Input facts because an old reader could silently omit
the durable sampling boundary.

Before v2 writes are enabled:

1. a bridge release must fail closed when a required core Model Input kind uses
   an unknown payload version;
2. downgrade to binaries older than that bridge is declared unsupported for a
   session containing v2 facts; and
3. the rollout must choose either a minimum-reader feature in the Conversation
   compatibility contract or an explicit fork into a newer Conversation format
   when strict downlevel refusal is required.

Changing only the record kind is insufficient because unknown kinds are also
opaque to the current generic decoder.

Bridge result (2026-08-15): `ConversationPayloadCodecRegistry` now allows a
profile to mark core payload kinds as requiring a known version. The standard
Agent transcript profile marks both Model Input kinds required, so an unknown
Model Input payload version fails with
`unsupported_required_payload_version`; unknown extension kinds remain opaque.
Sessions containing v2 facts must not be opened with binaries older than this
bridge. Strict enforcement by an older binary would still require a future
Conversation format/minimum-reader boundary or an explicit fork.

### Content-Addressed Value Shape

V2 uses coarse, typed, domain-separated nodes. It does not create one record per
JSON scalar. The illustrative values are:

```text
ModelInputNodeRef
  record_id
  ordinal                 # node position inside a bounded bundle
  node_kind
  content_hash

ModelInputSequenceTail
  algorithm_version
  previous_tail_ref | null
  appended_item_refs[]
  total_item_count
  sequence_hash

ModelInputLargeValue
  encoding
  chunk_refs[]
  decoded_bytes
  value_hash

ModelInputNodeBundle
  schema_version
  nodes[]                 # encoded bundle remains below the record ceiling

ModelInputSnapshotV2
  existing invocation/runtime/source fields
  logical_root_ref
  prepared_root_ref
  model_visible_headers_root_ref
  logical_input_hash
  prepared_payload_hash
  outcome = "prepared"
```

Small mappings and scalar values remain inline inside a typed node. Append-
growing sequences, Tool arrays that benefit from stable reuse, and large
strings use references. A large leaf is divided by a deterministic,
schema-versioned algorithm and reconstructed exactly before JSON decoding or
transport verification.

Logical and prepared roots are independent because Provider adapters reshape
messages. Identical typed large leaves may be shared when their canonical
content and encoding match. Per-request fields remain outside reusable message
tails so they do not invalidate stable sequence prefixes.

### Incremental Sequence Rule

A sequence is incremental only when a previous active-path sequence is a
verified prefix under the same algorithm and value schema. The new tail stores
only appended or changed suffix references. A snapshot stores only the final
root/tail, never the accumulated item or chunk-reference array.

If an adapter rewrites an earlier item, the longest verified prefix may be
reused and the changed suffix is materialized again. The expected physical
growth is therefore:

```text
O(unique materialized content + prepared attempts)
```

It is not an unconditional `O(turns)` claim.

### Bundling And Store Append Cost

V2 must not multiply single-record appends without a measured bound. Before its
production gate, implementation must choose and benchmark at least one of:

- bounded node bundles, so a normal attempt adds a constant small number of
  records; or
- a ConversationStore batch append that performs one lock/load/fsync and one
  repository rebuild for an ordered record batch.

A generic batch API is not a correctness prerequisite if bounded bundles meet
the latency gate. Large inputs may require multiple bundles, so batch append
remains a candidate optimization. No implementation may use node-per-scalar
materialization.

### Reconstruction And Resource Bounds

V2 reconstruction:

- resolves only snapshot ancestors;
- validates record kind, ordinal, domain-separated hash, sequence count, root
  hash, and final logical/prepared hash;
- rejects cycles and duplicate/conflicting identities;
- caps node count, reference depth, and decoded bytes;
- may cache verified nodes by typed hash within one loaded Session; and
- treats component bundles without a referencing prepared snapshot as orphan
  facts, never as a model-visible invocation.

Implementation result (2026-08-16): Model Input payload version 2 now uses
typed value, sequence-tail, mapping-root, and canonical-JSON chunk nodes in
bounded bundles. Normal writes use v2 while v1 remains readable. Large JSON
string tokens are aligned independently before deterministic 48 KiB
character chunking, allowing the same retained base64 image to be shared
between differently shaped logical and prepared messages. Bundles target
700 KiB and use the Store batch extension added by the preceding slice.
Snapshots retain only three roots and are rebuilt and hash-verified before
transport. Indexing and reuse are restricted to verified active-path
ancestors, with node, depth, item-count, and decoded-byte limits. Cancellation
may leave orphan bundles; a later attempt can reuse them only from its active
path after validation.

## Attempt And Outcome Semantics

### Prepared Attempt Facts

Existing per-attempt semantics remain. An AI internal transport retry keeps one
`invocation_id`, increments `attempt`, prepares its exact payload, and commits a
new `model.input.prepared` snapshot before transport. Identical values reuse
v2 nodes; the prepared snapshot itself remains distinct.

`ModelInputSnapshotV2.outcome` remains `"prepared"`. A pre-transport fact cannot
claim completion, failure, or Provider acceptance.

### Logical Invocation Outcome

The first outcome slice appends exactly one hidden `model.call.outcome` after
all AI-internal retries for the logical invocation finish. It references:

- the logical `invocation_id`;
- every prepared snapshot ID created for its attempts;
- `completed`, `failed`, or `cancelled` disposition;
- safe typed error fields when failed;
- final usage when available.

A crash may leave prepared snapshots without a terminal outcome. Replay
classifies those invocations as `unknown`; it does not invent a terminal fact.

Implementation result (2026-08-16): AI exposes a Harness-neutral terminal
outcome recorder on the existing prepared-request committer. The Provider
runtime invokes it once, after its internal retry loop reaches a terminal raw
part. The Harness committer serializes the outcome through the same revision
authority as its prepared snapshots and requires the outcome to reference the
complete ordered attempt sequence on the active path. The hidden outcome fact
contains no generated content or Provider response body. Failed outcomes retain
only code, source, retryability, HTTP status, request ID, usage, and explicitly
allowlisted scalar details. A structured Provider body may contribute bounded
identifier-shaped `type` and `code` fields, but never its message or arbitrary
response summary. Existing snapshots remain immutable. Retry and
recovery parent links remain part of the later recovery slice. The selected-
path projection groups all prepared attempts by invocation and reports a
missing terminal fact as `unknown`; it never fabricates a failed or completed
outcome. Forking an off-path summary lineage retains the unique associated
terminal outcome when one exists.

If later requirements demand a durable record for every transport phase, AI
must expose a Harness-neutral lifecycle observer owned by the same per-sampling
commit sequence. Session code must not append an attempt outcome between
retries through a separate revision authority.

### Provider Retry Versus Recovery

```text
AI transport retry:
  same invocation_id, attempt += 1

Harness retry without changed logical context:
  new logical invocation, retry_of_invocation_id

Compaction recovery:
  new logical invocation, recovery_of_invocation_id
```

Recovery and retry do not masquerade as another AI transport attempt.

## Structured Failure Boundary

### AI

AI owns Provider-specific parsing and stable failure categories:

- `context_overflow`;
- `request_too_large`;
- `unsupported_input`;
- `invalid_tool_history`;
- `request_validation`;
- `safety_rejection`;
- `authentication`;
- `rate_limit`;
- `timeout`;
- `service_unavailable`; and
- `unknown_provider_error`.

HTTP status constrains the error family but does not erase a more specific
validated Provider classification. Public error text is presentation, not
policy input.

### Agent

Agent preserves a typed model-call failure and emits a stable failure identity.
An optional, additive, allowlisted `error_info` value may accompany an
Assistant error for UI/replay compatibility, but infrastructure, transcript,
listener, and extension failures are not synthesized as Provider messages.

`error` and `aborted` remain distinct. Error assistants are not model-visible.
The current aborted-boundary repair is explicitly reviewed because it turns an
unsuccessful call into a later model-visible text turn.

### Harness

Harness persists the terminal logical outcome and uses typed categories for
retry and compaction. Regex classification remains only as a compatibility
fallback for custom adapters that cannot supply structured errors.

Durable error details use an allowlist:

- status code;
- request ID;
- Provider error type and code;
- local stable category;
- numeric capacity fields; and
- exception class.

Arbitrary Provider `message`, `detail`, response body, prompt echo, filesystem
path, or model-visible content is not durable by default. Model-visible headers
and prepared-payload projections continue to exclude credentials and receive a
separate security review as exact request facts.

## Model Selection Boundary

Model selection follows this order:

```text
serialize with Session activity / wait for idle
  -> capture one transcript revision and effective context
  -> resolve the candidate Model
  -> derive ContextRequirements through the shared normalized-context analyzer
  -> validate stable requirements
  -> append agent.model_selection
  -> publish the live Model
  -> refresh settings/extensions and emit post-commit notifications
```

The first slice covers stable requirements such as image, audio, document, and
required Tool input. Per-call reasoning, structured output, temperature, Tool
choice, and streaming remain final AI preflight concerns.

Validation failure changes no transcript fact, setting, live Model, extension
state, or event. Post-commit refresh and observer failures report degraded
diagnostics and cannot claim that the append-only selection was rolled back.

AI preflight remains mandatory because context may change after selection and
before the next sampling boundary. Queued model-selection and prompt ordering
must be specified and tested rather than delegated to UI timing.

## Request Capacity Boundary

The Provider adapter owns metrics derived from its frozen request:

```text
PreparedRequestMetrics
  canonical_bytes
  estimated_wire_bytes | null
  message_bytes | null
  message_count
  image_bytes
  tool_schema_bytes
  estimated_input_tokens | null
```

`canonical_bytes` describes the frozen audit representation. It is not named
`wire_bytes` unless transport sends the exact same byte buffer. SDK adapters
provide conservative wire estimates and safety margins where exact
serialization is unavailable.

Budget facts resolve in this priority:

```text
account/endpoint runtime fact
  > explicit user endpoint override
  > curated Provider/model limit
  > unknown
```

Unknown limits are observable but do not justify an invented hard rejection.
After a typed Provider capacity failure, recovery may derive a smaller bounded
target from known limits or from a conservative reduction of the failed
request; it must never enter an unbounded retry loop.

Capacity preflight occurs after Provider payload preparation and before Model
Input commit. A rejected, unsent candidate records safe preflight diagnostics
but is not a prepared transport snapshot. A committed prepared snapshot still
exists for any request that reaches transport and is later rejected.

## Bounded Compaction

Overflow recovery is not enabled until compaction itself obeys the selected
Provider budget.

The compactor:

1. plans turn-safe batches under input and output-reserve budgets;
2. prepares and preflights every summary batch;
3. produces bounded partial summaries;
4. merges partial summaries through a bounded fan-in and depth;
5. commits one final checkpoint with lineage covering all summary Model Input
   snapshots; and
6. starts at most one new logical recovery invocation.

Limits include maximum batches, merge depth, total summary calls, total source
bytes, and recovery attempts. A batch with no legal cut fails explicitly.

Image-bearing source context chooses one explicit policy:

- summarize through an image-capable model;
- replace the image with a deterministic metadata placeholder and persist an
  `image_omitted` degradation diagnostic; or
- refuse automatic compaction.

No mode silently discards image semantics. A final checkpoint may continue to
store one merged summary and the complete ordered snapshot lineage; durable
partial plans/results are required only if mid-compaction crash-resume becomes
an accepted requirement.

The implemented standard path uses the placeholder mode by default, records an
`image_omitted` degradation count, and caps each summary request's canonical
prepared envelope at 512 KiB (or a stricter caller limit). Conversation turns
are packed without splitting into at most 16 history batches; partial summaries
merge through at most four levels. Total source is capped at 8 MiB, total model
calls at 32, and every call carries a bounded output-token reserve. A single
turn with no legal cut fails before any model call. All successful history,
merge, and split-prefix Model Input snapshots remain ordered in the final
checkpoint lineage.

## Cancellation, Crash, And Orphan Semantics

| Last durable fact | Transport possible | Replay interpretation |
| --- | --- | --- |
| v2 component/bundle only | no | orphan content; not an invocation |
| prepared snapshot, cancelled before transport | no | prepared but not sent; terminal cancellation if recorded, otherwise unknown |
| prepared snapshot, transport started, process crashed | yes/unknown | interrupted/unknown; never completed by inference |
| prepared snapshot plus failed outcome | yes | terminal typed failure |
| prepared snapshot plus completed outcome | yes | terminal completion |

Orphans are safe in an append-only Store and may be reused only when they are
reachable through the current active path and verify exactly. Cancellation
never rolls back an already durable record.

## Existing Session And Migration Policy

An upgraded reader loads and reconstructs v1 snapshots and writes new attempts
as v2 after the rollout gate. It does not convert prior facts during resume.
The first v2 attempt may materialize the complete current effective input once;
later attempts reuse v2 tails.

Physical reclamation of old v1 duplication is deferred. An accepted future
design may:

- fork into a new conversation with explicit lineage; or
- introduce sealed/compressed Store segments that preserve every record ID,
  order, revision, and decoded fact.

An in-place semantic rewrite of the authoritative JSONL is prohibited.

## Delivery Dependencies

```text
selection idle gate --------------------+
                                         +--> Model Input v2
Store append/bundle performance gate ----+         |
                                                   v
typed Provider failure --> terminal outcome --> bounded compaction
                                                   |
                                                   v
                                      one-shot capacity recovery
```

Model Input v2 lands before hierarchical compaction so summary calls do not
multiply v1 monolithic snapshots. Typed error propagation lands before retry
policy uses capacity categories. The idle gate lands before v2 lengthens the
Model Input commit sequence.

## Acceptance Gates

### Persistence And Store

- A real FileConversationStore workload with growing history demonstrates
  near-linear physical growth relative to unique materialized content.
- A repeated large image is stored in a bounded number of large-value chunks,
  not once per later turn or separately per surface when canonical leaves
  match.
- A value larger than 1 MiB commits as bounded records and rebuilds exactly.
- The selected bundle/batch design meets an explicit append-latency and record-
  count budget.
- V1 snapshots rebuild after reload, resume, fork, and checkpoint lineage use.
- A mixed v1/v2 session rebuilds every snapshot and writes only v2 thereafter.
- Cross-sibling, wrong-kind, tampered, cyclic, over-depth, and over-byte
  references fail closed.
- Orphan bundles never project as prepared requests and cannot cause transport.

### Compatibility

- The bridge reader fails loudly on unknown required Model Input payload
  versions.
- The supported downlevel/downgrade matrix is explicit and exercised.
- Ordinary load never changes a pre-existing session byte-for-byte; only a new
  append changes the authoritative file.

### Selection And Failure

- Image-bearing effective context rejects a text-only model before selection,
  settings, live Model, or extension state changes.
- A model command during sampling waits or fails explicitly without changing
  the Model Input revision sequence.
- A later image insertion is still rejected by final AI preflight.
- Non-AI infrastructure failures persist no raw `str(error)` content and do not
  become Provider assistant messages.
- Error and abort follow distinct, documented model-visibility rules.

### Attempts And Recovery

- Three internal Provider attempts produce three prepared snapshots sharing v2
  content and exactly one terminal logical outcome.
- A crash after a prepared snapshot but before a terminal outcome is reported
  as interrupted/unknown.
- Typed built-in Provider errors, not public prose, drive retry and compaction.
- Durable diagnostics contain no arbitrary Provider or prompt text.
- Every summary batch and merge is within the selected budget.
- Image omission is explicit and diagnosed.
- Capacity recovery creates at most one new logical invocation and cannot loop.
- Any failed Model Input commit results in zero Provider transport calls.

## Open Decisions Before Acceptance

The following choices still require prototype evidence or explicit acceptance:

1. minimum-reader feature versus new Conversation format/fork for strict
   downlevel refusal;
2. whether partial summary results need durable mid-compaction resume; and
3. default image policy when no image-capable summary model is available.

Automatic capacity recovery remains gated on the unresolved compaction and
image-policy decisions. Strict downgrade refusal beyond the bridge reader also
remains a compatibility follow-up; it does not permit rewriting old facts.
