# Harness Context, Compaction, And Journal Foundations

## Status

Status: implementation complete for integration into `lane/harness`.

This document defines the next capability-sized ownership transfer from
`loushang.coding` and `loushang.work` into Harness. It covers neutral context
items and packing, configurable context compaction, append-only journal
mechanics, and branch graphs. This completed foundation wave did not move a
concrete transcript profile, summarization prompts, AI calls, artifact
semantics, or product storage policy into Harness.

The follow-on
[Runtime Data Foundations](runtime-data-foundations.md) now adds a generic
transcript repository, rebuildable projection index, structural salience, and
summary-profile mechanics. The later
[Agent Transcript Profile](agent-transcript-profile-boundary.md) adds the
optional common Agent schema and codecs. The subsequent
[Agent Transcript Maintenance Runtime](agent-transcript-maintenance-boundary.md)
also moves standard summary message serialization and AI completion execution
into that optional profile. Domain-specific payloads, exact prompt text,
model/credential selection, artifact decoration, and storage policy remain
Product-owned.

The implementation should use one semantic task branch,
`harness/context-compaction-journal`, with three delivery batches for
foundation, engines, and product cutover. It should not be split into
file-sized branches, protocol-only branches, or one branch per consumer.

This wave is intentionally sized for one to two focused working days when the
context and journal tracks can proceed concurrently. If implementation runs
longer, reduce deferred or speculative scope first; do not fragment the core
ownership transfer into smaller merge units that leave duplicate production
implementations behind.

## Review Record

Two independent reviews were performed before marking this proposal ready for
implementation: one focused on ownership and compatibility, and one focused on
minimality and delivery risk. Their blocking findings are incorporated here:

- Coding keeps a compatibility planner/reducer until the standard strategy can
  prove split-turn and tool-result parity;
- the coordinator returns a Product-owned artifact and never writes a journal;
- cancellation, summary reserve, post-reduction repacking, and overflow are
  explicit contract states;
- JSONL format, durability, and load behavior are independent profiles;
- BranchGraph provides strict and compatibility corruption modes;
- Work adopts only common JSONL I/O in the first wave;
- generic indexes and projection checkpoints were deferred from this first
  wave and are governed by the follow-on Runtime Data Foundations decision;
- the delivery estimate reflects replacement scope rather than candidate
  package size.

No blocking review finding remains unresolved in this design. Implementation
may still refine symbol names without changing these ownership decisions.

## Implementation Outcome

The implementation on `harness/context-compaction-journal` now provides:

- `loushang.harness.context` records, group-aware insertion/recent/priority
  packing, RecentWindow and single-batch RollingSummary strategies, reducer
  contracts, cancellation, explicit overflow, and single-flight coordination;
- `loushang.harness.journal` functional codecs, independent format/durability/
  load profiles, shared/exclusive sidecar locking, append/atomic rewrite/load,
  typed recovery diagnostics, and strict/compatible BranchGraph behavior;
- a Coding compaction-service adapter over the Harness coordinator while the
  existing split-turn planner, reducer, prompts, and transcript projection stay
  Product-owned;
- Coding session persistence over `JsonlJournal`, locking over
  `journal_file_lock`, and tree/path/fork selection over `BranchGraph`;
- Work JSONL persistence over `JsonlJournal` while Work retains and internally
  shares its in-memory/query/subscription state semantics;
- byte-level Coding and Work format characterization plus product-neutral
  Context and Journal contract tests.

This first implementation did not add a generic index/checkpoint layer,
migrate Coding message codecs, or replace Coding's specialized compaction
planner. That historical non-goal is superseded for common messages by the
Agent Transcript Profile wave. The Runtime Data Foundations follow-on added
rebuildable JSON indexes but not journal-offset checkpoints.

The later [Conversation Runtime Core](conversation-runtime-core-boundary.md)
closes the in-memory checkpoint/replay and specialized cut-planner gaps:
opaque-record turn grouping, split-turn/non-cut planning, previous-summary
accounting, metadata cut groups, repository/catalog/query, and replay now live
in Harness. Journal-offset checkpoints remain deferred. The optional Agent
profile owns common codecs and standard summary execution; domain codecs,
prompt content, model/credential selection, and artifact semantics remain
Product-owned.

## Motivation And Existing Evidence

The repository already contains the same lower-level mechanisms behind
different product semantics:

- `coding.compaction` owns context cut-point planning, recent-token retention,
  a compaction coordinator, summary production, and Coding-specific summary
  quality rules;
- `harness.transcript` owns cross-platform file locking, atomic JSONL
  rewrite, append/load recovery, a parent-linked entry graph, branch selection,
  fork, and a session index; Coding binds it through
  `coding.session_manager`;
- `work.event_log` owns another in-memory and JSONL append/query/subscribe
  implementation;
- before this wave, `loushang.harness.context` owned only budget accounting and
  the neutral usage-estimate record;
- planned Research, PPT, Design, and Cowork products all require bounded model
  context, revision history, and branchable work without adopting
  Coding transcript semantics.

These are sufficient neutrality signals. The shared mechanisms should have one
Harness owner while Coding, Work, and future products keep their payload types,
projection rules, prompts, and defaults.

## Decision Summary

Harness will own two related but distinct foundations:

1. `loushang.harness.context` owns opaque context items, grouping, packing,
   compaction contracts, standard planners/strategies, coordination, and
   compaction diagnostics.
2. `loushang.harness.journal` owns generic append-only record storage, codec
   protocols, JSONL framing, file locking, and parent-linked branch graphs.

Context compaction and journal maintenance must remain different operations:

- context compaction changes the bounded projection sent to a model and never
  deletes source journal records;
- a successful context compaction returns an artifact to the Product, which
  decides whether and how to append a domain record such as Coding's
  `CompactionEntry`;
- rebuildable projection indexes are supplied by the follow-on Runtime Data
  Foundations wave; journal-offset checkpoints, destructive journal vacuum,
  and retention remain deferred.

Products choose the compaction trigger, strategy, reducer, persistence
policy, and domain projection. Harness provides usable default mechanisms and
strategies, not only protocols.

## Target Module Layout

The target layout is intentionally focused:

```text
loushang.harness.context
  types.py          # items, bundles, plans, results, diagnostics
  packing.py        # deterministic group-aware budget packing
  compaction.py     # protocols, coordinator, status, failure behavior
  strategies.py     # standard product-neutral strategies
  budget.py         # existing threshold accounting
  usage.py          # existing usage-estimate record

loushang.harness.journal
  types.py          # format/load options, snapshots and diagnostics
  codec.py          # header/record codec and JSON-value contracts
  jsonl.py          # lock, append, atomic rewrite, load and recovery
  branch.py         # parent graph, ancestry, leaf and fork mechanics
```

`types.py` may define small focused `ContextDiagnostic` and
`JournalDiagnostic` records when an operation cannot yet construct a complete
`DiagnosticRecord`. Products normalize those records through the existing
Harness diagnostics service. Do not use the `resource_diagnostic` factory
merely because it accepts a path; journal corruption and context overflow are
not resource-discovery failures.

Do not introduce top-level `loushang.context`, `loushang.session`,
`loushang.persistence`, or `loushang.memory`. Do not export the new symbols from
top-level `loushang.harness.__all__`; consumers should use focused modules.

## Neutral Context Model

### Context Items

Harness context items carry enough structure for deterministic packing without
understanding their domain payload:

```python
T = TypeVar("T")

@dataclass(frozen=True)
class ContextItem(Generic[T]):
    item_id: str
    kind: str
    content: T
    estimated_tokens: int
    group_id: str | None = None
    priority: int = 0
    pinned: bool = False
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextBundle(Generic[T]):
    items: tuple[ContextItem[T], ...]
    source_tokens: int
    metadata: Mapping[str, object] = field(default_factory=dict)
```

`kind`, `group_id`, and metadata values are opaque to Harness. A Coding adapter
may use a group for a user/assistant turn or a tool-call/result pair. A Research
adapter may group a claim with its evidence refs. A PPT adapter may group a
slide revision with the artifact state it references.

Harness validates only structural invariants:

- ids are non-empty and unique within a bundle;
- token estimates are normalized to non-negative integers;
- items in one group are contiguous and selected or removed atomically;
- group priority is the maximum priority of its items and any pinned item pins
  the complete group;
- priority or recency controls selection, but the final packed bundle is always
  emitted in original source order;
- pinned groups are never silently removed.

Non-contiguous repeated group ids produce a diagnostic. The first Harness
strategies do not split a group. Products that require split groups implement a
custom planner over the same compaction contracts; Harness should not introduce
a speculative generic split-policy language in this wave.

Harness does not inspect content or decide which product facts deserve
pinning. The follow-on structural salience scorer applies only
Product-supplied weights to neutral item fields and metadata; Products still
own content signals and selection policy.

### Packing

`ContextPacker` owns deterministic selection under a target token budget. Its
input is a `PackingRequest`; its output records selected and omitted ids,
accounted tokens, overflow, and diagnostics.

The first implementation provides:

- stable insertion-order packing;
- priority-first packing with stable ties;
- atomic-group packing;
- mandatory pinned-item handling;
- explicit overflow when pinned content alone exceeds the budget;
- no implicit truncation of an opaque payload.

Payload truncation is performed only by an injected reducer or by a product
adapter that knows the payload type.

## Compaction Model

### Contracts

Compaction is separated into planning, reduction, and packing. Trigger policy
remains a Product decision in the first wave; the existing Harness budget and
usage records provide neutral inputs:

```python
class CompactionStrategy(Protocol, Generic[T]):
    def plan(self, request: CompactionRequest[T]) -> CompactionPlan: ...


class ContextReducer(Protocol, Generic[T]):
    async def reduce(
        self,
        request: ReductionRequest[T],
    ) -> ContextItem[T]: ...
```

The exact public names may be adjusted during implementation, but the
separation of concerns is required. Harness must not call an AI model itself.
The product supplies `ContextReducer`, which may use an AI model, a
deterministic reducer, or a remote service.

`CompactionRequest` carries the target budget, a required
`summary_reserve_tokens` for summary-producing strategies, a previous summary
as an opaque context item, product instructions, overflow behavior, and a
neutral cancellation signal passed unchanged to the reducer.
`ReductionRequest` includes the selected item batch and `max_output_tokens`.
The returned summary item reports its actual estimated tokens.

After reduction the coordinator repacks the summary and retained groups. If the
result still exceeds the target, the configured behavior is explicit:
`report_overflow` or `raise`. The coordinator never silently drops pinned or
newly summarized content to make the assertion pass.

### Standard Strategies

The first wave provides two usable standard strategies plus the packer's
priority selection mode:

1. `RecentWindowStrategy` retains the newest complete groups that fit after
   pinned content. It performs no summarization.
2. `RollingSummaryStrategy` marks one batch of older complete groups for an
   injected reducer, reserves the configured summary budget, and retains the
   returned summary plus recent groups. It may incorporate one previous summary
   item.

Products opt out by not invoking compaction. Priority packing is an ordering
mode of `ContextPacker`, not a second strategy class.

Coding's existing planner is not equivalent to standard RollingSummary. It can
split an oversized turn, separately summarize history and a turn prefix, avoid
tool-result cut points, and rebuild from `first_kept_entry_id`. Coding therefore
keeps a `CodingCompactionStrategy` and reducer adapter in the first wave while
delegating coordinator state and neutral packing contracts to Harness. Standard
RollingSummary is validated by product-neutral fixtures; Coding must not adopt
it until parity is demonstrated.

`HierarchicalSummaryStrategy` is explicitly deferred. It should be added only
after single-batch rolling summaries have production evidence. The first wave
must not build a speculative multi-level memory system.

### Coordinator

The Harness coordinator owns:

- one-active-compaction enforcement;
- caller-supplied reason strings;
- cancellation and status snapshots;
- planner and reducer invocation order;
- diagnostic capture;
- configurable failure behavior: `keep_original` or `raise`;
- verification that the result satisfies the target budget or reports
  explicit overflow.

Cancellation must be observable by both the coordinator and reducer. Before
reduction it returns an aborted result with the original bundle. During reducer
IO, the neutral signal is forwarded and task cancellation is propagated. An
aborted or failed result is never persisted by Harness. Because persistence is
Product-owned, there is no ambiguous "compaction succeeded but checkpoint
failed" transaction inside the coordinator.

It does not own model selection, retry classification, prompts, cost policy,
or product UI status text.

### Compaction Records

Harness-owned records should generalize the reusable part of current Coding
records:

- `CompactionRequest`, including summary reserve, overflow behavior, and a
  cancellation signal;
- `CompactionPlan` with kept, summarized, and omitted item/group ids;
- `CompactionResult` containing the output bundle, token accounting,
  diagnostics, overflow, and abort/error state;
- `CompactionStatus`;
- `ReductionRequest` and an optional `CompactionArtifact` returned to the
  Product for domain projection;
- compaction reasons as open strings or metadata rather than Coding-specific
  enums.

Coding compatibility aliases may preserve existing `CompactionStatus` and
parts of `CompactionPlan` only when constructor fields and behavior can remain
identical. Do not force a false identity alias when Coding's record embeds
`AgentMessage` or transcript-specific fields; use a thin projection adapter.

## Journal Model

### Generic Snapshot

The JSONL engine is generic over product header and record types. It does not
wrap every `SessionEntry` or `EventLogEntry` in a second durable envelope:

```python
H = TypeVar("H")
R = TypeVar("R")

@dataclass(frozen=True)
class JsonlSnapshot(Generic[H, R]):
    header: H | None
    records: tuple[R, ...]
    diagnostics: tuple[JournalDiagnostic, ...] = ()
```

The JSONL engine must support both header-first journals and headerless record
logs. Coding session files keep their first-line session header. Existing Work
event log files remain headerless. Initial adoption must not rewrite existing
files merely to match a new Harness envelope.

### Codec Boundary

This generic journal package owns JSON framing and focused codec protocols, not
concrete payload schemas. Headerless logs must not implement fake header
methods, so header and record codecs remain separate:

```python
class JournalRecordCodec(Protocol, Generic[R]):
    def encode_record(self, record: R) -> Mapping[str, object]: ...
    def decode_record(self, value: Mapping[str, object]) -> R: ...


class JournalHeaderCodec(Protocol, Generic[H]):
    def encode_header(self, header: H) -> Mapping[str, object]: ...
    def decode_header(self, value: Mapping[str, object]) -> H: ...
```

The JSONL engine receives an optional `JournalHeaderCodec`; `None` means the log
is headerless. The Harness JSON-value normalizer supports JSON scalars,
mappings, and sequences. It must not silently serialize arbitrary objects with
`repr()` in durable formats. Unsupported values produce a typed error or
diagnostic chosen by the caller.

At completion of this foundation wave, concrete codec ownership was:

- Coding owns Coding transcript entries, custom messages, model/thinking
  changes, compaction-entry projection, and their compatibility codec;
- `loushang.work` owns `WorkOperation`, `WorkEvent`, and `EventLogEntry`
  encoding;
- future Research/PPT/Design/Cowork packages own their domain record codecs;
- AI owns the stable base-message and message-part codec for AI-owned value
  types;
- Agent owns the extension-message codec protocol and registry that composes
  those base codecs;
- each Product owns codecs for its custom transcript entries and message
  extensions.

The follow-on Agent Transcript Profile supersedes the first item for common
Agent transcript records: it composes stable AI/Agent codecs into a standard
optional profile and migrates Coding to it. Products continue to own only their
domain-specific payload codecs and projections. The generic journal itself
remains unaware of both Agent messages and Product payloads.

Harness may import stable `loushang.agent` value primitives elsewhere, but this
journal design remains opaque and does not import `loushang.ai`.

### JSONL Engine

The shared JSONL engine owns:

- cross-platform shared/exclusive lock mechanics;
- parent-directory creation;
- configurable flush/fsync append;
- atomic rewrite through a same-directory temporary file and replace;
- optional header encode/decode;
- record encode/decode;
- line number and source-path diagnostics;
- configurable invalid-record behavior;
- optional tolerance for a partial trailing line after interruption;
- preservation of original file format and field spelling through the codec.

Encoding, loading, and durability are configuration because the current
consumers do not have identical behavior. A focused `JournalFormatProfile`
controls UTF-8 encoding, newline, `ensure_ascii`, `sort_keys`, and separators.
A `JournalDurabilityProfile` controls sidecar locking, lock modes, flush, and
fsync. A `JournalLoadPolicy` controls header presence, invalid header, invalid
middle records, and a partial trailing line. Coding selects its current required
header + lock + fsync + default `json.dumps` profile. Work selects its current
headerless + no-lock + no-fsync + `ensure_ascii=False, sort_keys=True` profile.
Harness may offer named presets, but the product adapter makes the choice.

Standard load policies are `strict` and `skip_invalid_records`. Coding adopts
the policy that preserves its current behavior: an invalid or missing header is
fatal/recoverable by the Coding facade, while invalid entry lines are skipped.
Work preserves its accepted strict behavior. Work's compatibility codec may
normalize unsupported payload objects with its current `repr()` fallback before
calling the strict Harness JSON writer; Harness itself does not add that
fallback.

The engine must not implement product retention, file naming, session
directories, user-visible recovery messages, or encryption policy.

### Follow-On Index And Deferred Projection Checkpoints

Coding's session index remains a Coding summary/query projection, but the
follow-on Runtime Data Foundations wave moves its versioned JSON persistence,
stale detection, corrupt preservation, and rebuild callback into
`JsonProjectionIndex`. Coding still owns the projection schema, directory
scan, freshness predicate, query, ranking, and index location. Incremental
journal-offset checkpoints and a `CheckpointStore` remain deferred.

A Product may append a domain compaction artifact to its source journal, as
Coding does with `CompactionEntry`. That record remains source history, not a
Harness recovery cache. A future `ProjectionCheckpoint` may cache an opaque
projection at a covered record position, but it must be independently
rebuildable and must not be coupled to the Context coordinator.

## Branch And Fork Mechanics

`BranchGraph` operates on record ids and parent ids. It owns:

- unique-id validation;
- deterministic child indexes;
- root and leaf enumeration;
- path-to-root and ancestor queries;
- lowest common ancestor;
- path selection by any existing node;
- dangling-parent, self-parent, duplicate-id, and cycle diagnostics;
- a fork plan that copies the ancestry path visible from a selected node.

Graph corruption handling is explicit. A strict construction mode rejects
duplicate ids, dangling/self parents, and cycles. A compatible mode emits
diagnostics, uses last-record-wins lookup for duplicate ids, treats dangling or
self parents as roots for tree projection, and cuts a cycle at the first
revisited id during a parent walk. Root and child output preserve source
insertion order. Coding selects compatible mode to preserve accepted behavior
while gaining cycle termination. Harness must never enter an unbounded parent
walk on malformed input.

The graph does not understand messages, claims, slides, artifacts, models, or
work steps. Products decide:

- which record kinds are visible in a product context;
- whether a fork copies records or references an immutable source journal;
- the target journal header and metadata;
- which product state is reconstructed after selecting a branch;
- branch naming, retention, approval, and UI.

Coding's `SessionManager` remains the public product facade. It delegates graph
construction, branch paths, tree topology, and fork record selection to
Harness, while retaining SessionHeader, SessionEntry, label events, context
rebuild, cwd, model/thinking state, file naming, and session summaries.

## Work Adoption

`loushang.work` remains the owner of operations, events, run/plan/step
projections, artifact refs, delivery hints, and Work event schemas. It may
depend on the lower Harness journal engine; Harness must not import Work.

Work adoption should:

- preserve `EventLogBackend`, `InMemoryEventLogBackend`, and
  `JsonlEventLogBackend` public imports;
- route only matching JSONL encode/load/append mechanics through Harness;
- preserve existing field names, ordering, query filters, positions, and file
  format;
- leave Work normalization, in-memory backend, positions, filtering, query,
  replay, subscription, and projection semantics in Work.

The first wave intentionally does not add generic query or subscription APIs to
Harness. Moving only JSONL mechanics is the supported scope, and no Work class
is expected to become a Harness identity alias.

## Product Ownership Matrix

| Concern | Harness | Product / subsystem |
| --- | --- | --- |
| Context item identity and grouping | records and invariants | mapping domain facts/messages to items |
| Token budget | normalization and accounting | model capability lookup and defaults |
| Packing | group-aware deterministic engines and explainable structural salience | content weights, selection, priority, and pinned decisions |
| Compaction trigger | existing budget/usage input records | enablement, trigger and retry policy |
| Compaction planning | standard recent/single-batch rolling strategies | strategy selection and compatibility/custom planner |
| Summary reduction | async reducer protocol, coordination, profile composition, and structural validation | exact prompt text, model, temperature, content rules |
| Compaction persistence | no implicit write | domain artifact projection and journal append |
| JSONL | locking, framing, append/load/recovery | schema, naming, location, retention |
| Branch graph | topology, ancestry, fork selection | state rebuild and product-visible semantics |
| Index/checkpoint | rebuildable JSON projection-index mechanics | projection schema/query/cache policy; journal-offset checkpoints deferred |
| Diagnostics | structural codes and provenance | remediation and user-facing grouping |

Examples of product-specific policy that remains outside Harness:

- Coding preserves tool-call/result pairs, file changes, current model,
  thinking level, and its exact summary prompts;
- Research preserves claims, citations, evidence, source reliability, and
  report revision state;
- PPT preserves the current deck/artifact projection and slide dependencies;
- Cowork preserves unresolved decisions, assigned tasks, and collaboration
  state;
- Work preserves audit events even when a bounded model context uses a compact
  projection.

## OEM And Extension Integration

Compaction is a replacement-style capability at product assembly time. Harness
accepts an injected strategy and reducer. A product or OEM may choose a
standard Harness strategy or supply a custom implementation.

Do not add a `compaction` extension surface in this wave unless the Extension
Runtime has a concrete replacement-slot processing path and policy gate. Direct
protocol injection is sufficient for the initial migration. Extension
packaging can be added later without changing the compaction contracts.

Journal codecs and storage locations are also product-assembly dependencies,
not dynamically replaceable extension hooks by default. A storage replacement
must be selected before a journal is opened.

## Compatibility Requirements

### Coding File Compatibility

The initial migration must preserve:

- Coding session JSONL first-line header;
- all existing camelCase field names and optional-field omission behavior;
- invalid header errors and recovery codes;
- invalid entry-line skip behavior;
- append fsync and atomic rewrite behavior;
- session id, cwd, parent session, leaf selection, labels, and fork outputs;
- the public `loushang.coding.SessionManager` import; the retired
  `coding.store` package is not preserved;
- current compaction triggers, cut points, retained messages, summary payloads,
  and public result behavior when Coding selects its compatibility strategy.

Existing files must open without migration. New files produced through the
adapter must remain readable by the pre-migration Coding codec for the current
format version.

### Work File Compatibility

The initial migration must preserve:

- Work EventLog JSON field names and ISO timestamps;
- append/query/subscribe ordering and position behavior;
- run/session filters and limits;
- existing in-memory and JSONL public constructors;
- additive unknown payload fields.

### API Compatibility

Accepted Coding and Work public paths remain available through thin adapters or
aliases. Internal consumers should import Harness owners directly only for
genuinely Harness-owned records and mechanisms. Compatibility must not preserve
a second implementation.

## Dependency Direction

The target direction is:

```text
Coding compaction/session/store adapters -----> loushang.harness.context
                                         \----> loushang.harness.journal

loushang.work event-log adapter --------------> loushang.harness.journal

future product adapters ----------------------> both Harness packages
```

Forbidden directions:

```text
loushang.harness.context -> coding / work / method / TUI / AI / products
loushang.harness.journal -> coding / work / method / TUI / AI / products
loushang.harness         -> product codecs or product storage policy
```

Harness context and journal packages may depend on Python standard-library
types and existing Harness diagnostics. Context may use existing Harness budget
records. The journal package must not depend on context; compaction artifacts
are Product-owned values so the two mechanisms remain independently reusable.

## Migration Execution Plan

Implement the wave on one semantic branch in three delivery batches. The
batches are integration checkpoints, not hard serialization barriers: context
and journal work may proceed concurrently inside a batch. Internal commits may
remain reviewable, but the branch is merged only after the complete wave passes
its exit criteria.

No type-only, protocol-only, codec-only, or single-adapter change counts as a
finished delivery batch. Each batch must leave a usable vertical capability
with focused tests. Compatibility characterization is written just before the
corresponding contract or adapter and lands in the same batch, avoiding a
separate waiting phase.

### Batch 1: Compatibility Baseline And Complete Contracts

- capture byte-level Coding JSONL fixtures for headers, field order, Unicode,
  invalid records, invalid headers, and partial trailing lines;
- capture Work JSONL fixtures for Unicode, stable key order, strict loading,
  and its product-owned unsupported-value normalization;
- capture Coding compaction fixtures for split turns, tool-result boundaries,
  previous summaries, cancellation, and retained-entry selection;
- capture branch fixtures for duplicates, dangling/self parents, cycles,
  insertion order, path selection, and fork ancestry.
- add context item/bundle/packing/compaction records;
- add journal format/load/durability profiles and codec/branch records;
- establish no-product import guards and top-level export discipline;
- add construction, invariant, and compatibility-baseline tests in the same
  change set.

Batch 1 is complete only when both context and journal contracts are usable by
a fixture adapter. Do not merge a records-only shell.

### Batch 2: Complete Harness Engines

- implement group-aware packing;
- implement RecentWindow, single-batch RollingSummary, and recent/priority
  packer modes;
- implement coordinator, cancellation, failure behavior, and diagnostics;
- implement profiled JSONL lock/append/rewrite/load mechanics;
- implement BranchGraph and fork-plan mechanics;
- add independent Research/PPT-shaped contract fixtures without product
  imports.

The context engine and journal/branch engine are parallel work tracks. They
share diagnostics and architecture checks but do not wait on each other's
internal implementation. Batch 2 lands only when all advertised Harness APIs
have production implementations and focused tests.

### Batch 3: Product Cutover, Duplicate Removal, And Closure

- map SessionEntry/AgentMessage values to opaque context items;
- retain a Coding compatibility planner/reducer for token estimation, split
  turns, summary prompts, model calls, and detail projection;
- preserve Coding cut points, previous-summary behavior, retries, and status;
- reduce `coding.compaction` to product policy and compatibility adapters where
  possible.
- route Coding file locks, JSONL, graph, branch, and fork mechanics through
  Harness; the follow-on Runtime Data Foundations wave also routes the generic
  session-index mechanics through Harness while leaving its projection in
  Coding;
- retain the Coding session codec and SessionManager product facade;
- route only matching Work JSONL I/O through Harness while preserving Work
  types, in-memory/query/subscription behavior, and public behavior;
- remove the replaced Coding and Work implementations in the same batch as
  their adapters; do not retain a second implementation for a later cleanup;
- run focused Harness, Coding compaction/store/session, Work event-log, startup,
  and full non-live tests;
- add architecture tests and identity tests only for true aliases;
- update migration inventory and ownership documents;
- record measured source-line ownership changes.

Coding compaction adoption, Coding store adoption, and Work JSONL adoption may
proceed concurrently after Batch 2 APIs stabilize. A failing adapter blocks the
final wave merge, but it does not block progress on the other adapters.

### Delivery Guardrails

- prefer three substantial, durable commits matching the batches; use extra
  commits only when they isolate an independently reviewable risk, not a file;
- run focused tests continuously within each track and avoid repeatedly running
  the entire suite after every small edit;
- run the full non-live suite once after all product cutovers and duplicate
  removals are assembled, then rerun only affected failures;
- do not add deferred checkpoint, hierarchical-memory, or generic query work
  merely to make a batch appear larger;
- if a compatibility mismatch appears, keep the Product adapter specialized
  and continue the rest of the wave instead of redesigning Harness around one
  product exception;
- report progress by capability closed and duplicate implementation removed,
  not by files moved or protocol count.

## Source Migration Map

| Current source | Target ownership | Product remainder |
| --- | --- | --- |
| `coding.compaction.types` | neutral request/status/result shapes where behavior matches | transcript-specific plans, results, and branch-summary projections use adapters rather than false aliases |
| `coding.compaction.compaction` | common packing/reducer boundary plus opaque-record turn/cut planning | Coding compatibility records, message/token adapters, prompts, AI completion, transcript mapping, and file details |
| `coding.compaction.service` | single-flight coordinator state, cancellation, and failure lifecycle | Coding invocation and artifact projection adapter |
| `coding.session.context_usage` | existing Harness budget and usage inputs only | trigger policy, model lookup, and Coding stale-entry interpretation |
| removed `coding.store.file_lock` | Harness journal locking | no Coding alias remains |
| removed `coding.store.file_codec` | JSONL framing and atomic IO | SessionHeader/SessionEntry codec remains in Harness |
| `coding.session_manager.SessionManager` | Coding Product runtime binding | projection schema/fields, lifecycle, cwd, labels, naming, recovery, and retention |
| `work.event_log` | matching JSONL I/O only | Work normalization, in-memory backend, positions, filters, query, replay, subscriptions, records, and public adapters |
| `coding.message.json_codec` | superseded by `loushang.harness.transcript` for common transcript records | AI owns base codecs, Agent owns extension codec composition, and Products own only domain payload codecs |

## Planned Size And Measured Outcome

Expected production-code ownership change:

- 350 to 650 lines removed from or replaced inside Coding;
- 30 to 80 lines of duplicate Work JSONL mechanics replaced;
- 900 to 1,400 lines of focused Harness production code in the first wave;
- 150 to 300 lines of Coding/Work adapters and compatibility exports remain;
- 600 to 1,000 lines of focused Harness and compatibility tests are expected.

Repository line count may increase because the wave adds reusable strategies,
structural diagnostics, and independent product-neutral tests. Success is
measured by one owned implementation and smaller product adapters, not by a
mechanical net deletion target.

Measured Python source lines on this branch, using the same raw `*.py` line
count as the migration inventory:

- Harness: 18,503 to 20,065, an increase of 1,562 lines;
- Coding: 49,537 to 49,514, a reduction of 23 lines;
- Work: 903 to 874, a reduction of 29 lines;
- focused new Harness and compatibility tests: 658 lines.

The Product reduction is below the initial estimate because review deliberately
kept Coding's split-turn planner and session index, plus Work query/subscription
semantics, outside Harness. The ownership result is still substantive: the
cross-platform lock algorithm, JSONL framing/durability/recovery, compaction
lifecycle, packing/standard strategies, and parent graph algorithms now each
have one Harness implementation. Product adapters retain schema and policy,
not duplicate substrate algorithms.

Final validation completed with 4,425 non-live tests passing and 9 live tests
deselected. The focused cross-subsystem run passed 279 tests; Ruff passed for
all changed Python files, Harness Context/Journal passed mypy, and
`git diff --check` reported no whitespace errors.

## Validation Matrix

### Harness Context

- item id and token normalization;
- stable order and priority ties;
- atomic groups and pinned overflow;
- exact-budget and zero-budget packing;
- RecentWindow and RollingSummary with and without a previous summary;
- summary-reserve enforcement, post-reduction repacking, and explicit overflow;
- reducer success, exception, cancellation, and invalid result;
- coordinator concurrent-call rejection and status reset;
- context compaction leaves source journal records untouched.

### Harness Journal

- shared/exclusive locking on supported platforms;
- fsync append and atomic rewrite;
- header-first and headerless files;
- strict and skip-invalid load policies;
- invalid header, middle-line corruption, and partial-tail recovery;
- codec error provenance with path and line number;
- duplicate ids, dangling parents, self-parent, cycles, roots, leaves,
  ancestors, LCA, branch paths, and fork plans;
- strict and compatible graph construction modes.

### Product-Neutral Contract Probes

- a Research-shaped fixture packs claims and evidence as atomic groups and uses
  the priority packer mode without importing Research;
- a PPT-shaped fixture retains a pinned deck-state artifact while compacting
  discussion through RollingSummary;
- a headerless generic event fixture round-trips through the journal engine;
- none of these fixtures imports Coding, Work, AI, Method, or TUI.

### Compatibility

- Coding compaction plan/result parity for accepted fixtures;
- Coding session JSONL golden files read and write identically;
- Coding branch/tree/fork behavior and session-index bytes/query behavior
  remain unchanged while their generic mechanics use Harness owners;
- Work EventLog round-trip, query, positions, and subscription behavior remains
  unchanged;
- startup and session replacement smoke tests pass;
- architecture boundaries pass;
- full non-live suite passes.

## Non-Goals

This wave does not:

- move product summarization prompts or model calls into Harness;
- define one universal transcript payload schema;
- move WorkEvent, MethodPlan, ArtifactRef, or product domain records;
- persist or delete model context implicitly;
- introduce a journal-offset projection checkpoint store;
- define a generic compaction-trigger protocol before another trigger shape is
  understood;
- implement destructive journal vacuum, retention, encryption, remote storage,
  replication, or a database;
- implement hierarchical memory, vector search, long-term user profiles, or a
  memory product;
- move Coding UI, commands, export formats, session naming, or query relevance;
- move Agent/AI message serialization without an accepted AI-layer owner;
- add extension surface types without a working injection path.

## Exit Criteria

The design is implemented only when:

- Harness contains concrete, product-neutral packing, compaction, journal, and
  branch engines rather than contract-only shells;
- Coding and Work no longer contain second implementations of migrated JSONL,
  locking, packing, coordinator, or branch mechanics;
- Coding uses Harness coordinator/contracts through its compatibility planner
  and reducer while retaining prompts and transcript semantics;
- at least two non-Coding-shaped fixtures exercise different standard
  compaction strategies;
- existing Coding and Work files require no migration and preserve accepted
  behavior;
- context compaction cannot destroy journal history;
- dependency and top-level export boundaries are enforced by tests;
- the complete non-live suite is green.
