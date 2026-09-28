# Resume Request Evidence Recovery Design

## Status

Implemented on 2026-09-28 in `b57c2fe7` after three independent GPT-6 Astra
reviews: architecture, correctness and compatibility, and performance and
verification. Tracking issue: #645.

The implementation replays selected-path message anchors transactionally,
inspects only named Model Input components for legacy evidence, and fully
rebuilds only candidate snapshots whose evidence is needed. Explicit semantic
audit remains available for a selected historical snapshot.

Focused session, transcript and Coding Model Input tests: 667 passed, 374
skipped. Changed source files pass focused mypy; Ruff passes. The full Harness
typecheck currently fails on pre-existing errors in journal and sandbox files.
An offline probe of the original 77 MB session copy reached first Model Input
commit in 15.9 seconds (evidence hydration 0.36 seconds, commit 0.93 seconds),
versus 15.0 seconds with hydration disabled under the same warm conditions.
The repaired run used about 626 MB peak resident memory. Network transport was
blocked for both probes.

## Problem and measured baseline

The first model call after resuming a long Coding session can spend minutes on
local CPU before model transport starts. A 77 MB session with 762 Model Input
snapshots waited about 8 minutes 44 seconds between appending `hi` and the first
prepared Model Input. In an isolated, network-blocked control run that suppressed
historical snapshot recovery, the request reached Model Input commit in about
18 seconds; roughly 16 seconds were session load and 1.1 seconds were commit.
Three unrelated session copies entered the same recovery stack.

`SessionRequestEvidenceRuntime.project_model_input()` calls
`_recover_from_snapshots()` for each new model call. It scans backward and fully
rebuilds each historical Model Input until it finds a complete Resource evidence
context. No-evidence sessions rebuild every snapshot. Every rebuild searches
records, reconstructs ancestry, resolves growing message sequences and prepared
payloads, then hashes them. Repeating that hundreds of times causes the long
first-turn wait. Its scanned-snapshot cache is process-local.

## Authority decision

The committed user-message record is the runtime recovery authority for exact
loaded Skill facts. `AgentEventRouter` already appends
`loushang.request.resource_evidence` metadata atomically with that message.
Normal resume replays selected-path message facts; a new model request projects
those facts against its current context. Model Input snapshots remain immutable
receipts of what each request contained and an explicit audit surface. They are
not consulted merely to prepare another request.

An early format also wrote Resource evidence to Model Input without an atomic
message anchor. A private compatibility importer recovers those snapshot-only
facts. It is scoped to the selected ancestry and runs before transport only
when needed. Imported facts retain their source snapshot identity; they never
silently become authoritative on another branch.

The design needs no new persistent sidecar, migration registry, or session-file
rewrite. The compatibility query is a narrow, format-independent Model Input
component-reference lookup, not a Resource-specific normal read path.

## Contracts

1. Loaded Skill identity, generation, expected/observed digest and length, and
   model-visible text remain attached to the exact user-message record. Resume
   never reopens a mutable Skill source to recreate them.
2. Only facts on the selected ancestry may be projected. A legacy fact requires
   both its message record and its source snapshot record on that ancestry.
   Compaction can remove a message from current model context even while its
   historical record remains on the ancestry; removed messages are not
   projected into the current request.
3. Duplicate text is associated by record ID and exact occurrence, never by
   text alone. Existing schema, role, digest, message-index and context checks
   remain fail-closed for facts being recovered.
4. Hydration is transactional. Validated anchors, imported legacy facts,
   scanned markers and the completed-path key are published together. Failure
   leaves no partially hydrated state for the selected path and blocks model
   transport. State from another path must never be used as fallback.
5. Commit-time Model Input hashes and explicit full reconstruction remain
   unchanged. Routine resume no longer promises to detect unrelated corruption
   in every historical Model Input before the next model call.

## Selected-path lifecycle

Use a selected-path key containing conversation identity, current revision and
leaf identity. Initial resume and every non-append path change (branch, fork,
rollback or navigation) invalidate the current evidence overlay. Before model
transport, hydrate the newly selected ancestry into a staging projection and
atomically replace the old overlay. A normal append can reuse a verified prefix
and validate only new records. The initial implementation may replay the
selected message anchors linearly if an incremental path is more risky; it must
not perform historical Model Input reconstruction on the normal request path.

Do not key legacy evidence solely by message ID: a common ancestor message can
be present on branches A and B while the snapshot that supplied its evidence
exists only on A. Cache reuse is permitted only when the exact source snapshot
is also selected. A failed hydration never marks the path complete. Switching
away and back revalidates or reuses only a provenance-safe completed overlay.

`project_model_input()` consumes this completed selected-path projection and the
current context-message bindings. It still rejects ambiguous duplicate text,
foreign/off-context messages and mismatched durable facts before transport. A
selected snapshot that refers to a foreign message fails during legacy import;
an off-path snapshot is ignored. Already compacted-out messages are omitted.

## Compatibility importer

The normal format obtains evidence from message metadata. For older mixed or
snapshot-only paths, a private importer inspects selected Model Input snapshots
for possible unanchored message facts. Component presence alone is not a reason
to fully rebuild a request: modern anchored snapshots also contain the
component. A shallow lookup obtains and verifies the relevant component
reference and value sufficiently to identify its message record IDs. If all
referenced messages already have equivalent anchors, the snapshot needs no
legacy import or full request rebuild. If a selected, currently relevant
message lacks an anchor, the importer uses the existing full reconstruction and
Resource evidence semantic checks for the necessary candidate snapshots, back
to the existing `contextComplete` boundary. Anchored and imported facts must
agree where they overlap.

The lookup is implemented inside the Model Input layer for both formats: V1
component-reference names and V2 logical-root entries. Build one position map
for the selected ancestry and reuse it for all inspected snapshots. Never call
`records_to()`, build a full resolver, or recursively resolve `messages` or the
prepared payload for every snapshot. V2 deferred bundles currently decode the
whole bundle even through `node_at()`; cache each distinct root/component bundle
decode and measure its actual bytes. Validate selected ancestry, record kind
and version, ordinal, node kind, reference/node hash and unique entry names.
This shallow check is not full logical/prepared-payload verification.

The importer stages anchors and legacy facts together, validates conflicts and
semantic associations, then publishes the complete overlay. With K genuinely
required legacy snapshots, K full rebuilds may still be costly, especially if
all have `contextComplete=false`; report K and total time. No promise that all
legacy sessions match the no-recovery control is made without measurement. A
durable checkpoint is a separate follow-up only if legacy measurements warrant
its complexity.

## Audit boundary

`verify_model_input()` checks reconstructed hashes, but a hash-valid snapshot
can still contain semantically invalid Resource evidence, such as duplicate
message indices or a false `contextComplete` claim. Keep these as separate
claims. Expose an explicit Resource evidence audit over a selected snapshot
that invokes the existing pure semantic validator with its logical messages and
selected ancestry. The compatibility importer invokes the same validator for
facts it imports. Modern anchored recovery need not fully rebuild unrelated
historical requests; a historical snapshot-only semantic error still fails when
that snapshot is required for recovery. Tests must demonstrate that Model Input
hash verification can succeed while Resource evidence audit fails.

## Delivery sequence

1. Add regressions for no-evidence first resume, anchored-only, snapshot-only,
   mixed, malformed and conflicting evidence; include long real V2 deferred
   bundles and `A -> common ancestor -> B -> A` navigation. Establish focused
   baseline measurements before runtime edits.
2. Refactor anchor replay into a staged selected-path projection. Preserve live
   atomic message append and current request projection output. Make path-key
   validation a pre-transport gate, then remove `_recover_from_snapshots()` from
   ordinary `project_model_input()`.
3. Add the narrow V1/V2 component lookup and private legacy importer. Stage
   anchors, imported facts, caches and completion marker in one transaction.
   Keep exact legacy full verification for facts actually imported.
4. Add explicit semantic audit and phase measurements. Run isolated offline
   resume probes with the installed CLI and the same copied histories.

Runtime implementation follows the workspace high-risk workflow: tracking
issue, isolated harness lane, focused baseline, regression first, then source
change. The existing working tree's unrelated files must be preserved.

## Acceptance

- A selected path with 700+ evidence-free V1/V2 snapshots performs zero
  historical full rebuilds from process start through first Model Input commit,
  and zero recursive sequence/value reconstruction in evidence hydration.
- An anchored-only long session also performs zero historical full rebuilds.
  Normal and resumed, immediate and queued, tool-loop and retry requests
  project the same evidence without reopening the Skill source.
- Legacy-complete and legacy-all-incomplete fixtures report how many candidate
  snapshots were fully rebuilt. Invalid or conflicting selected facts fail
  before transport; a failed attempt does not contaminate a later retry or
  different branch.
- Branch tests cover `A -> common ancestor -> B -> A`, including an unanchored
  ancestor message whose only evidence source is an A-only snapshot. Compaction
  tests require evidence only for messages retained in current context.
- Model Input hash verification and Resource evidence semantic audit are tested
  independently, including a hash-valid but semantically invalid snapshot.
- CI uses deterministic work-count assertions: one selected-path position index
  per hydration, no per-snapshot ancestry/resolver builds, no absent-component
  recursive decode, and at most one decode of each distinct deferred bundle
  needed by the shallow lookup. Corrupt root references fail; unrelated deep
  corruption remains discoverable through explicit verification.
- Offline wall time starts when the process opens the session and ends at first
  Model Input commit; also report time from `hi` append. On the same machine,
  alternate baseline and repaired runs with matched cold/warm index states.
  For the 77 MB evidence-free fixture, target a repaired median no more than
  1.5 times the no-recovery control median, and report session load, hydration,
  preparation, commit, root-bundle decode bytes and peak memory separately.
  Shared CI does not use a fixed wall-clock threshold.

## Remaining risk

Legacy paths with many incomplete candidate snapshots can still require many
full rebuilds on each cold resume. The measured 8-minute case has no Resource
evidence and does not take this path after the fix. If legacy benchmarks show
unacceptable cost, a separately reviewed durable migration checkpoint may be
necessary. Its validity must be tied to selected ancestry and source snapshot
hashes; a process-local completed flag is insufficient.
