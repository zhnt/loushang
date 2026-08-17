# Model Input Persistence And Capacity Recovery Tracking Draft

## Proposed Issue Title

`fix(harness): bound Model Input persistence and recover typed capacity failures`

## Status

Implementation is in progress from this local tracking artifact; no remote
issue has been created. The governing proposal is
[Model Input Persistence And Capacity Recovery](../architecture/harness/model-input-persistence-capacity-recovery.md).

The first MIR1 slice is implemented locally: model selection is serialized by
the Session host boundary, image requirements use the same AI predicate at
selection and final request preflight, incompatible selection fails before any
model-selection fact is written, and non-AI Agent exceptions no longer expose
arbitrary exception text. `AssistantMessage.errorInfo` now carries additive,
codec-backed typed failure data into retry, overflow, and allowlisted Session
diagnostics. Local prepared-request validation errors are no longer relabeled
as Provider errors, and `ModelInputRecordSizeError` is typed as request
validation. MIR2 and MIR3 have since landed locally, and the first MIR4 slice
now records terminal logical invocation outcomes without removing per-attempt
prepared snapshots. The first MIR5 slice now measures every frozen request and
supports explicit capacity limits before Model Input commit and transport.

## Summary

PR #451 completed the commit-before-transport Model Input boundary, but its
first canonical-inline representation materializes the complete logical and
prepared message sequences on every sampling attempt. Append-growing histories
therefore produce piecewise quadratic JSONL growth, repeat retained image data,
and can fail the 1 MiB record ceiling before transport. The file backend also
reloads the full journal for every single-record append.

The same investigation found three adjacent control defects:

- model selection can publish an image-incompatible model and can interleave
  with an active Model Input commit sequence;
- structured Provider failure information is reduced to public error prose
  before Harness retry/compaction policy consumes it; and
- automatic compaction has no complete Provider request budget and silently
  omits images from summary input.

This issue tracks a compatibility-safe Model Input v2, typed invocation
outcomes, capability-safe model selection, adapter-owned request metrics, and
bounded capacity recovery while preserving every pre-transport durability
invariant introduced by PR #451.

## User Impact

- A long session can grow to tens of megabytes after only hundreds of records.
- Repeated full-journal reads and repository rebuilds increasingly delay each
  append.
- One large image can prevent every later sampling attempt from committing.
- Switching to a text-only model can succeed as a selection but fail on the
  next request because historical context contains an image.
- Distinct Provider validation failures appear as `Provider request failed.`
- A long request may be unable to recover because its summary request is also
  unbounded.

## Confirmed Root Causes

1. Logical and prepared `messages` are top-level monolithic components whose
   hashes change after every append.
2. Exact component deduplication cannot reuse a changed message-array prefix.
3. Large values inside one message are not chunked below the record ceiling.
4. FileConversationStore reloads the whole journal for every append; the unit
   of work rebuilds the full repository for every record.
5. Selection persists before historical capability compatibility is known and
   is not serialized with active sampling.
6. AI's typed error information is flattened before Agent/Harness policy.
7. Compaction serializes all selected text into one unbudgeted request and
   drops image parts without a diagnostic.

## Invariants To Preserve

- Every transported attempt has an exact, durable, hash-verified prepared
  snapshot.
- AI internal retry keeps one invocation ID and increments attempt.
- Existing v1 facts, IDs, revisions, parents, branch reachability, and lineage
  remain unchanged.
- Required Model Input versions fail closed when not understood.
- Provider, prompt, path, credential, or arbitrary exception text is not copied
  into durable diagnostics.
- Model selection and Model Input commit sequences cannot interleave.
- Recovery is typed, budgeted, and bounded to one new logical invocation.

## Non-Goals

- No in-place rewrite or deletion of v1 JSONL facts.
- No cross-conversation or sibling-branch content reuse.
- No global Blob Store in the first delivery.
- No removal of per-attempt prepared snapshots.
- No terminal outcome written back into a prepared snapshot.
- No public error-message regex as the primary built-in retry policy.
- No silent image loss during compaction.

## Proposed Work

### MIR0: Regression And Performance Baseline

- Add a real FileConversationStore growth fixture covering append-growing text
  and one retained image.
- Record encoded bytes, record count, append count, bytes re-read, and wall-clock
  samples for current v1.
- Reproduce the 1 MiB single-message failure.
- Freeze typed Kimi-style 400 fixtures, selection-during-sampling behavior,
  error versus abort normalization, and unbudgeted summary behavior.

Exit gate: every confirmed defect has a failing regression or a source-backed
architecture assertion.

### MIR1: Immediate Behavior Safety

- Serialize model selection with Session idle state.
- Extract one shared normalized-context requirements analyzer.
- Validate stable requirements before selection/settings/live publication.
- Keep final AI capability preflight.
- Separate model-call failures from infrastructure/listener failures.
- Sanitize non-AI exceptions and type `ModelInputRecordSizeError`.
- Review and freeze aborted-boundary model visibility.

Exit gate: incompatible or concurrent selection changes no durable/live state;
error handling leaks no arbitrary exception text.

### MIR2: Store Append And Bundling Gate

- Prototype bounded Model Input node bundles and a ConversationStore batch
  append.
- Benchmark both against v1 and projected v2 workloads.
- Select the smaller authority/API change that meets record-count and latency
  budgets.
- Exercise operation-ID reconciliation, cancellation, partial failure, fsync,
  and repository revision continuity.

Exit gate: the selected primitive does not amplify per-attempt append latency as
v2 splits large values.

Implementation result (2026-08-15): select both bounded v2 bundles and the
optional Store batch extension. `FileConversationStore` now appends one ordered
batch with one exclusive lock, one journal load, one payload write, and one
sync; the transcript Unit of Work validates and rebuilds the repository once.
Current v1 Model Input commits batch all missing components, then commit the
per-attempt prepared snapshot separately. Tests cover stable operation IDs,
duplicate rejection, lost responses, a durable-prefix retry, cancellation,
revision continuity, and the one-load/one-write/one-sync boundary. This gate
does not claim to fix v1 byte growth; tail/root bundles and large-leaf chunks
remain MIR3 work.

### MIR3: Model Input Payload Version 2

- Register v1 and v2 codecs/types for the existing Model Input record kinds.
- Add domain-separated node references, incremental sequence tails, bounded
  bundles, and large-value/blob chunks.
- Store only logical/prepared roots in v2 prepared snapshots.
- Reuse only verified active-path ancestors.
- Add bounded reconstruction and verified in-session caching.
- Land the required-reader bridge/downlevel policy before enabling writes.
- Preserve one prepared snapshot per Provider attempt.

Exit gate: physical growth follows unique materialized content, v1/v2 mixed
sessions reconstruct exactly, and every fork/branch/lineage invariant passes.

Implementation result (2026-08-16): payload version 2 is implemented for the
existing required Model Input kinds and is now the only version written by the
prepared-request committer. Typed value nodes, append-only sequence tails,
mapping roots, and bounded bundles preserve active-path reachability. Values
larger than one record are split into deterministic canonical-JSON chunks;
long string tokens receive independent boundaries so identical base64 leaves
can be shared across logical and Provider-shaped payloads. Reconstruction
enforces typed record/ordinal/hash ancestry plus node, depth, sequence, and
decoded-byte budgets, then compares the committed canonical prepared envelope
before transport. Tests cover real JSONL growth, a retained image present in
both surfaces, a message over 1 MiB, mixed v1/v2 reconstruction and fork,
branch-back isolation, invalid ancestry/kind/ordinal, retry reuse, and
cancellation-orphan recovery. No v1 fact is migrated or rewritten.

### MIR4: Typed Failure And Logical Outcome

- Preserve Provider-specific typed categories across AI and Agent.
- Emit a stable model-call failure identity.
- Migrate built-in retry/overflow decisions to typed-code-first behavior.
- Add one hidden terminal `model.call.outcome` per logical invocation, linking
  every prepared attempt snapshot.
- Treat prepared snapshots without a terminal outcome as interrupted/unknown.
- Restrict durable diagnostic fields to an explicit allowlist.

Exit gate: internal Provider retry creates multiple prepared snapshots and one
terminal outcome without revision conflicts or diagnostic leakage.

Implementation result (2026-08-16): the standard AI prepared-request port now
has an optional terminal outcome observer. Provider runtime calls it once after
all internal retries, using the same invocation identity. Harness appends one
hidden `model.call.outcome` through the Model Input committer and verifies that
its snapshot IDs exactly equal the complete ordered attempt sequence on the
active path. Completed, failed, and cancelled outcomes preserve final usage;
failed outcomes retain only allowlisted typed identity, HTTP status, request ID,
and bounded scalar details. Provider output and response bodies are excluded.
The existing prepared snapshots remain one-per-attempt and immutable. Projection
of a missing outcome now returns `unknown` without inventing a terminal fact;
off-path summary forks retain a unique associated outcome. Recovery-parent
links remain for the subsequent recovery work.

### MIR5: Capacity Metrics And Bounded Compaction

- Add adapter-owned canonical, estimated-wire, message, image, Tool-schema, and
  token metrics.
- Resolve account/endpoint overrides before curated defaults; keep unknown
  limits explicit.
- Preflight capacity after payload preparation and before durable snapshot
  commit/transport.
- Plan turn-safe summary batches with output reserve.
- Add bounded partial-summary merge and complete snapshot lineage.
- Require an explicit visual, placeholder/degraded, or refusal image policy.
- Start at most one new logical recovery invocation.

Exit gate: every summary request fits its selected budget, image semantics are
never silently lost, and recovery cannot loop.

Implementation result, first slice (2026-08-16): every prepared request now
records canonical bytes, message bytes/count, decoded inline-image bytes, and
Tool-schema bytes; adapters may additionally supply conservative wire-byte and
input-token estimates. Explicit `CallOptions` limits are checked after payload
freezing and before Model Input commit. A rejected request sends no transport
and writes no prepared snapshot, but records one typed terminal failure with
safe metrics. Requests with unknown limits remain observable and are not
rejected. Provider HTTP 413 and safe structured `request_too_large` identities
now retain that stable category instead of collapsing to generic Provider
failure. Bounded summary planning, endpoint/account limit resolution, and
one-shot recovery remain pending.

Implementation result, safety floor (2026-08-16): compaction and branch-summary
calls now apply a 512 KiB internal canonical-request ceiling while preserving
any stricter caller limit. The active Agent's explicit request limits flow into
Product compaction without breaking older callback signatures. Summary input
no longer drops images silently: the default policy replaces each image with a
deterministic MIME/base64-length placeholder and persists an `image_omitted`
degradation count; an explicit `refuse` policy stops before a model call.

Implementation result, bounded execution (2026-08-16): the standard compactor
packs whole conversation turns into at most 16 history batches under canonical
byte and estimated input-token budgets. One turn is never split implicitly; a
turn with no legal cut fails before a model call. Partial summaries merge under
the same request budget through at most four levels, with at most 32 total model
calls and 8 MiB total source. Summary output is reserved explicitly and capped
at 8,192 tokens or the lower model maximum/context fraction. History, merge,
and split-prefix snapshots remain ordered in final checkpoint lineage. Typed
`request_too_large` now enters the existing one-shot compact-and-continue path,
including when context-window metadata is unknown. Dynamic account/endpoint
limit discovery remains pending.

### MIR6: Optional Physical Reclamation

Deferred to a separate accepted Store boundary. Evaluate only:

- fork/new conversation with explicit lineage; or
- sealed/compressed segments preserving all logical record identities and
  revisions.

In-place semantic rewriting of the authoritative JSONL is excluded.

## Dependency Order

```text
MIR0
  |-> MIR1 model-selection and failure safety
  |-> MIR2 Store append/bundle gate -> MIR3 Model Input v2
  |-> MIR4 typed failure and terminal outcome

MIR1 + MIR3 + MIR4
  -> MIR5 bounded compaction and one-shot recovery

MIR6 remains separately gated
```

MIR3 precedes MIR5 so hierarchical summary calls do not multiply monolithic v1
snapshots. MIR1 precedes MIR3 so local selection cannot interrupt a longer v2
commit sequence. MIR4 precedes recovery so policy never depends on public error
text.

## Acceptance Checklist

- [x] Real JSONL growth is near-linear in unique v2 content.
- [x] Large image/text leaves remain below every encoded-record ceiling.
- [ ] V1 load/rebuild/resume/fork/checkpoint behavior remains unchanged.
- [x] Mixed v1/v2 sessions and branch-back/fork scenarios verify all hashes.
- [x] Unknown required Model Input versions fail loudly under the supported
      reader matrix.
- [ ] V2 appends meet the selected record-count and latency budgets.
- [x] Selection during sampling waits or fails without changing state.
- [x] Image-incompatible selection writes no transcript/settings facts.
- [x] Error and abort model visibility is explicit and tested.
- [x] Non-AI and Provider diagnostics persist only allowlisted data.
- [x] Every Provider attempt retains a prepared snapshot.
- [x] Every terminal Provider-runtime invocation with the durable Harness port
      appends exactly one terminal outcome.
- [x] Crash without terminal outcome projects unknown without inventing a fact.
- [x] Every compaction batch and merge passes Provider capacity preflight.
- [x] Image omission is explicit and degraded or refused.
- [x] Capacity recovery creates at most one new logical invocation.
- [x] Any failed prepared commit results in zero Provider transport calls.

## Review Questions

1. Should v2 use bounded node bundles, Store batch append, or both?
2. What compatibility mechanism prevents pre-bridge readers from silently
   treating required v2 Model Input facts as opaque?
3. Does the Product retain aborted-boundary text as model-visible context?
4. Which image-compaction policy is the default when no visual model is
   configured?
5. Are durable intermediate summary results required, or is deterministic
   restart from the last committed checkpoint sufficient?
6. Which endpoint/account capacity facts may be discovered dynamically, and
   which require explicit user configuration?

## Validation Commands By Slice

Each slice runs focused tests first. Source-changing AI slices additionally run
`make check-ai`; integrated Harness slices run `make check-harness`; all slices
run `git diff --check`. The final recovery slice also runs the supported Coding
smoke entrypoint and the sandbox-safe suite required by the Harness lane.
