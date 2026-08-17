# Store And Runtime Event Protocol Migration

## Status

Implemented on the semantic branch `harness/store-event-protocol-runtime`.

This wave depends on the Conversation JSONL and Agent Transcript profile from
`harness/agent-transcript-profile`. It refines the earlier inventory decision
that left concrete Product stores and all session events in Coding. The refined
boundary is:

```text
Harness owns reusable persistence protocols, reference Memory/File adapters,
Agent transcript store mechanics, and common in-process runtime events.

Product owns backend selection, storage roots, retention and recovery policy,
domain projections, transport/display schemas, and activation/trust decisions.
```

The plan deliberately does not implement SQL, Redis, a durable outbox, a new
extension surface, or distributed delivery. Those systems must be able to
implement the protocols, but their features do not belong in this migration.

## Problem

`coding.session_manager.SessionManager` remains a high-fan-in Product facade over several
mechanisms that are already neutral:

- Conversation JSONL load and append;
- Agent transcript record writing and replay;
- active branch, tree, fork, and context construction;
- file persistence and locking;
- rebuildable catalog and index mechanics.

The facade also owns Product decisions that should not move:

- Coding session roots and current-working-directory layout;
- session naming, retention, recovery acceptance, and import policy;
- Coding summary fields and search defaults;
- CLI/RPC/TUI projections.

The current concrete facade makes a file path part of the effective storage
contract. A Product that wants a database must reproduce much of the session
runtime or make the rest of Coding understand database details.

`coding.event.AgentSessionEvent` has a related ownership problem. It combines
raw Agent loop events with queue, compaction, retry, branch, resource, and
session metadata events. Most of those runtime facts are cross-product, while
their JSON, Work, extension, print, RPC, and TUI projections are not.

The two migrations are sequenced together because a completed transcript
record is a durable fact and its runtime notification must only be published
after the Store commit succeeds.

## Migration Goals

1. Make File an injected Store implementation rather than a session contract.
2. Let an OEM or trusted Product bootstrap provide another implementation
   without importing or modifying Coding.
3. Move reusable Agent transcript persistence mechanics out of Coding.
4. Establish one common runtime-event envelope and ordered in-process bus.
5. Publish transcript-commit events only after durable append succeeds.
6. Preserve current Coding behavior and Conversation JSONL format.
7. Leave Product storage policy and Product event projections in Product code.

## Ownership Boundary

### Harness Storage Ownership

Add `loushang.harness.storage` for persistence ports and reference adapters:

```text
loushang.harness.storage
  types.py          neutral keys, snapshots, revisions, and receipts
  protocols.py      ConversationStore protocol
  memory.py         deterministic in-memory reference implementation
  file.py           Conversation JSONL File implementation
```

The reusable provider contract probes live in the Harness storage test suite;
they are test contracts, not a production registration or discovery API.

Add a focused application service to the existing optional Agent profile:

```text
loushang.harness.transcript.store
  AgentTranscriptSessionStore
```

This service composes the existing `ConversationRepository`,
`AgentTranscriptProfile`, pure `AgentTranscriptRecordFactory`, and
`TranscriptCommitter`.
It owns one open conversation and must not create a second repository, branch
graph, replay folder, codec registry, writer, or cross-conversation catalog.

There is exactly one writable-state path per open conversation:

```text
AgentTranscriptSessionStore
  -> one journal-free ConversationRepository for graph/leaf/state projection
  -> one injected ConversationStore for authoritative persistence
```

The File adapter wraps the existing `JsonlJournal` directly; it does not create
another `ConversationRepository` or import the Agent Transcript profile. Its
constructor receives Product-supplied `create_path`, `resolve_path`,
`scan_paths`, `key_for_path`, and journal-factory callables. Coding therefore
retains its current root, timestamped filename, discovery, and Native codec
composition without those decisions leaking into neutral storage code.

Before a commit, the in-memory repository validates the candidate graph
mutation without applying it. The session store then appends through the
backend and applies the already validated record to the in-memory repository
only after backend success.

`AgentTranscriptRecordFactory` only constructs records;
`AgentTranscriptSessionStore` is the asynchronous commit owner and
`TranscriptCommitter` uses that same port. Product controllers must await
transcript mutations. This prevents a record factory, backend, and loaded
repository from becoming competing commit owners.

Harness owns:

- create, load, append, delete, and scan protocols;
- monotonically increasing Store revision and optimistic append checks;
- the minimal `StoreAlreadyExistsError`, `StoreNotFoundError`,
  `StoreConflictError`, and `StoreDataError` error contract;
- deterministic in-memory and Native File adapters;
- open Agent transcript state, record construction, replay, branch, fork, and context
  mechanics;
- conformance probes reusable by an OEM Store implementation.

### Product Storage Ownership

Coding and every future Product retain:

- Store provider selection and construction;
- storage namespace, roots, paths, and default backend;
- retention, deletion confirmation, and recovery acceptance policy;
- Product summary projection and query fields;
- session naming and display behavior;
- external import acceptance and source-format diagnostics;
- configuration schema, credentials, trust, and activation policy;
- CLI, RPC, TUI, and HTML representation of Store results.

Product code may use a `Path` when constructing the File adapter. No Harness
consumer may assume that a conversation has a filesystem path.

### Harness Event Ownership

Add `loushang.harness.events`:

```text
loushang.harness.events
  types.py          RuntimeEvent and missing event-specific payload records
  bus.py            ordered in-process publication
  protocols.py      publisher and listener ports
```

Harness owns:

- a minimal runtime-event envelope;
- per-stream monotonic sequencing;
- one session/host-scoped publisher that allocates event id, sequence, and
  timestamp for its stream;
- ordered synchronous/asynchronous in-process delivery;
- the transcript-record-committed payload;
- wrapping of an owner-supplied runtime payload without redefining it.

`OrderedEventBus` moves from `harness.host.events` to the new common owner.
`harness.host.events` remains an explicitly documented compatibility re-export
for the already accepted Host import path.

### Product Event Ownership

Coding retains:

- JSON event field names and view filtering;
- RPC, print, TUI, and extension delivery projections;
- Coding-only event kinds;
- tool render enrichment and protocol shaping;
- retry classification, compaction triggering, and other control decisions.

`loushang.agent.AgentEvent` stays owned by Agent. The optional Agent Transcript
adapter may consume Agent events without making the neutral event package
depend on Agent. `loushang.work.WorkEvent` and its event log stay owned by Work;
the Coding/Work adapter consumes Runtime events and performs that projection.
Harness neither imports nor wraps `loushang.work` or `loushang.channel` types.

## Store Protocol

The protocol uses `typing.Protocol`; it is an interface declaration, not part
of the retired broad `loushang.protocol` namespace.

The persistence boundary is asynchronous because a conforming backend may use
database or network I/O. Loaded snapshots and in-memory projections remain
synchronous values.

The initial contract is intentionally small:

```python
class ConversationStore(Protocol[HeaderT, RecordT]):
    async def create(
        self,
        key: ConversationKey,
        header: HeaderT,
        records: Sequence[RecordT] = (),
    ) -> ConversationSnapshot[HeaderT, RecordT]: ...

    async def load(
        self,
        key: ConversationKey,
    ) -> ConversationSnapshot[HeaderT, RecordT]: ...

    async def append(
        self,
        key: ConversationKey,
        record: RecordT,
        *,
        expected_revision: int,
    ) -> CommitReceipt: ...

    async def delete(self, key: ConversationKey) -> None: ...

    async def scan(self, namespace: str) -> tuple[ConversationKey, ...]: ...
```

Required value semantics:

- `ConversationKey` contains an opaque namespace and conversation id; it does
  not expose a path, SQL table, Redis key, or Product type.
- `ConversationSnapshot` contains header, records, and Store revision.
- Store revision is a monotonically increasing concurrency token for one
  conversation, not a transcript record id or global event sequence.
- Conversation header is immutable after create; mutable name and session
  information continue to use append-only metadata records.
- revision equals the number of durable records: create with N initial fork
  records returns revision N and each successful append increases it by one.
- `CommitReceipt` contains the committed revision, record id when applicable,
  and commit timestamp.
- `create(..., records=...)` supports an atomic initial fork snapshot without
  adding a backend-specific batch or copy API.
- an `expected_revision` mismatch raises `StoreConflictError` before mutation;
- the File adapter checks record count and appends under one exclusive lock;
- the File adapter keeps the sidecar lock inode after data deletion so a
  concurrent delete/recreate cannot split mutual exclusion across two lock
  files;
- record graph validity is checked before calling the backend;
- append failure does not advance the Store snapshot, transcript leaf, or
  runtime state;
- `scan(namespace)` enumerates keys for catalog rebuild without defining a
  universal Product query language.
- Coding path identity resolution strictly reads the Conversation JSONL header. It
  never invokes an importer, migrates a file, or rewrites data during scan,
  resolve, or delete.

Error behavior is fixed across providers:

- create of an existing key raises `StoreAlreadyExistsError`;
- load or delete of a missing key raises `StoreNotFoundError`;
- stale revision raises `StoreConflictError`;
- malformed or undecodable persisted data raises `StoreDataError`;
- the Product adapter maps those errors to current bool, diagnostic, or UI
  behavior and the Store does not invent Product wording.

The first contract does not include header mutation, transactions, leases,
caches, persistent idempotency, full-text search, blobs, credentials, or an
event outbox.
Capabilities may be added later as separate protocols rather than optional
methods on `ConversationStore`.

## Store Composition

The Product composition root injects exactly one authoritative
`ConversationStore`. The existing `ConversationCatalog` and
`JsonProjectionIndex` remain Product-composed, rebuildable projections; this
wave does not add a second catalog protocol or make the open-session Store
service own cross-session queries.

The initial wave supplies these compositions only:

| Composition | Primary | Purpose |
| --- | --- | --- |
| Test | Memory | contract and runtime tests |
| Coding default | Native File | current local behavior |
| OEM probe | injected fake provider | prove protocol injection |

Deferred adapters may implement the same Protocol for a database or use Redis
for auxiliary cache, lease, or transport. They must still designate one
authoritative primary. Their transactions, outbox, Redis integration, and
capability discovery are outside this wave.

## Provider And Extension Boundary

This wave supports direct `ConversationStore` injection at Product/OEM
bootstrap, verified by the conformance suite. It adds no extension manifest
field, contribution surface, provider registry, marketplace contract, dynamic
discovery, or runtime Store replacement. A future trusted bootstrap plugin can
construct the same Protocol implementation before session startup; its
discovery, trust, configuration, secrets, and migration concerns are separate.

## Runtime Event Contract

The event envelope is an in-process runtime fact, not a durable transcript
record, Work event, Channel envelope, hook decision, or UI model:

```python
@dataclass(frozen=True)
class RuntimeEvent(Generic[PayloadT]):
    event_id: str
    kind: str
    stream_id: str
    sequence: int
    occurred_at: datetime
    session_id: str | None
    run_id: str | None
    source_event_ref: str | None
    source_record_id: str | None
    payload: PayloadT
```

Contract rules:

- sequence is monotonic within `stream_id`; no global order is promised;
- controllers submit kind, payload, and source references to the scoped
  publisher rather than constructing envelope sequence values themselves;
- completed-record events carry `source_record_id`, record id, Store revision,
  and commit time copied from the successful `CommitReceipt`;
- runtime payloads are typed Python values and are not automatically wire
  compatible;
- Product serializers own JSON and Channel projection;
- listener failure follows the existing `OrderedEventBus` ordering and task
  semantics; it never rolls back an already committed Store mutation and gains
  no durable retry or listener isolation;
- retrying event projection must not append the transcript record again;
- events observe completed facts and are not before-hooks, commands, approval
  requests, or policy decisions.

This wave adds only `TranscriptRecordCommitted`. Existing Agent, Host,
queue, retry, compaction, branch, package, and Product payloads keep their
current owners and can be carried as opaque typed payload values. Promoting
more payload records requires a separate ownership review; the common event
envelope is not a reason to duplicate their type hierarchies.

The neutral `harness.events` package imports no Agent, Work, Product, or
Channel types. Raw `AgentEvent` remains unchanged; the Coding Host adapter
wraps it in `RuntimeEvent` for common runtime observers, while the existing
Extension Agent-event mirror keeps its schema and timing. Product-only event
kinds use a Product namespace and remain Product payloads.

## Commit And Publication Order

The runtime path becomes:

```text
Agent message_end
  -> transcript commit owner
  -> ConversationStore.append(expected_revision)
  -> CommitReceipt
  -> update loaded repository/leaf
  -> RuntimeEvent(transcript.record_committed)
  -> ordered in-process publication
  -> Work/Product/RPC/TUI projections
```

The Store commit is the boundary between durable fact and transient
observation. `AgentTranscriptSessionStore` returns the committed record paired
with the exact backend receipt. `SessionManager` schedules the commit
observation from that result only for a new commit; it never derives revision
from a later record count and an idempotent application-message hit does not
publish a second commit fact. If append fails, no committed event is published.
If event publication fails, the record stays committed and a retry may only
repeat publication or rebuild a projection. The Agent event router remembers a
completed message append for its process lifetime so retrying a failed
projection cannot append that same message object again.

This wave preserves the Agent Transcript contract of in-process application
message idempotency. It does not claim crash-safe exactly-once behavior and
does not add a persistent deduplication table or event outbox.

## Agent Event Router Split

`coding.session.AgentEventRouter` currently persists messages, mirrors events,
records diagnostics, and invokes retry/compaction control. Replace it with
focused collaborators without changing control policy:

```text
AgentTranscriptSessionStore
  commit completed transcript records and return record + CommitReceipt

AgentRuntimeEventAdapter
  wrap raw Agent events and committed-record references

CodingEventProjection
  preserve current JSON/RPC/print/TUI event shapes

CodingAgentControlObserver
  preserve retry, diagnostics, and auto-compaction decisions

ExtensionAgentEventMirror
  preserve existing Extension event schema and timing
```

The event bus is not used as a command dispatcher. Retry and compaction remain
direct control calls so observer ordering cannot change execution policy.

## Implemented Cutover

The branch should remain green through these capability-sized commits:

### Commit 1: Storage Contracts And File Conformance

- add storage values, protocols, errors, and conformance probes;
- implement Memory and Native File stores using existing journal/conversation
  mechanics;
- inject File path creation/resolution/discovery and the journal factory from
  Coding rather than teaching Harness the Coding directory layout or codec;
- add one focused journal compare-and-append primitive that counts records,
  verifies `expected_revision`, and appends under the same exclusive lock;
- keep headers immutable after create and derive revision from record count;
- keep the Conversation JSONL schema and load policy unchanged;
- prove File and Memory behavior through the same contract tests;
- add import gates preventing storage protocols from importing Products,
  Work, Method, Channel, TUI, or AI.

No Coding runtime behavior changes in this commit.

### Commit 2: Agent Transcript Store Cutover

- add `AgentTranscriptSessionStore` over the existing profile, repository,
  pure record factory, and committer;
- make the Committer use the session store's single asynchronous commit port
  instead of appending directly to a journal-backed repository;
- retain one journal-free in-memory repository and prevalidate each graph
  mutation before backend commit;
- move common create/load/append/header/branch/tree/fork/context mechanics from
  `coding.session_manager.SessionManager`;
- inject the File Store from Coding bootstrap while the existing Product
  catalog/index remains a separate Coding projection;
- keep Coding storage roots, summaries, queries, recovery choice, naming, and
  CLI projection in a small Coding adapter;
- make current Product load/scan/delete paths strict and read-only with respect
  to unsupported formats; explicit external importers remain separate;
- switch production consumers from `SessionManager` to the focused Harness
  service or Coding projection adapter and await every transcript mutation;
- change `AgentEventRouter`'s message commit port to `Awaitable` and await the
  commit before preserving its existing event mirror and control flow;
- convert append entry/message/selection/compaction/branch summary/annotation/
  metadata and rename/delete call sites in the same commit; loaded tree and
  context reads plus Product projection computation remain synchronous after
  their asynchronous Store load completes;
- treat a Coding cwd override as runtime Product state rather than mutating the
  immutable persisted conversation header;
- retain Coding's Native codec and journal factory as Product composition;
  persistence locking and compare-and-append live in the File Store.

### Commit 3: Runtime Event Core

- add the event envelope, committed-record payload, publisher/listener
  protocols, and ordered bus;
- add one scoped publisher per session/host stream as the only event id,
  sequence, and timestamp allocator;
- move the generic ordered bus implementation from `harness.host`;
- adapt Host and Coding session streams, then move common Session payload types
  in the follow-up Session Runtime Events migration;
- preserve raw Agent, Extension, Work, and Product event contracts;
- add per-stream order and listener-failure tests.

### Commit 4: Commit/Event Router Cutover

- split `AgentEventRouter` by commit, observation, control, and projection;
- enforce Store-commit-before-event ordering;
- project Runtime events back to the existing Coding JSON/RPC/TUI shapes;
- change the Coding Work adapter upstream from the Coding event union to the
  common runtime event where semantics match;
- retain Product-only projection code under `coding.event`;
- retain `AgentSessionEvent` only as the Coding UI/RPC/extension projection
  input; common runtime and Work observers subscribe to `RuntimeEvent`.
- remove the second Coding event bus; the accepted Product subscription installs
  a projection listener on the same ordered Runtime stream.

Store async correctness is already complete in Commit 2; this commit does not
defer or repeat that mutation cutover.

### Commit 5: Closure

- document the accepted `harness.host.events` compatibility re-export and
  delete other unused Store/Event compatibility code;
- update the migration inventory and accepted boundary documentation;
- add OEM fake-Store injection coverage;
- run focused and full non-live tests, Ruff check, format check, and import
  architecture checks.

## Expected Coding End State

The `coding.store` package is removed. The remaining Product adapter lives in
`coding.session_manager` and contains no persistence engine or session
repository facade:

```text
coding.session_manager.py
  SessionManager   Coding roots, runtime-profile binding, and restored-header validation
```

`coding.event` should contain only Product projections:

```text
coding.event
  projection.py    view selection and tool render enrichment
  serialization.py current Coding wire schema
  product_types.py genuinely Coding-only payloads, if any
```

`coding.session_manager.SessionManager` remains a Coding Product adapter over
`AgentTranscriptSessionStore`; `AgentSessionEvent` remains a Product
projection contract rather than the common runtime event model.

## Validation

### Storage Contract Tests

- Memory and File pass the same create/load/append/delete/scan suite.
- create with N records returns revision N; successful append increases it by
  one and header mutation is unavailable.
- stale expected revision fails without modifying backend or loaded state.
- File compare-and-append performs count, revision check, and append under one
  exclusive lock.
- failed append does not advance transcript leaf or runtime state.
- create with initial records preserves active-path fork semantics.
- unknown Native payloads remain JSON-semantically equivalent after File
  load/rewrite/fork.
- corrupted known payload and malformed envelope retain current strict errors.
- stale/corrupt Product index rebuilds from primary storage.
- namespace scans do not expose another Product namespace.
- delete preserves the stable sidecar lock inode, and scan/path resolution does
  not migrate or rewrite an unsupported format.
- existing, missing, stale, and corrupt cases map to the four frozen Store
  errors consistently.
- injected File path/journal factories preserve Coding filenames and Native
  codecs without a Harness-to-Coding or neutral-Storage-to-Agent import.
- a fake OEM implementation can be injected without importing Coding.

### Event Contract Tests

- listener delivery is ordered within one stream.
- one scoped publisher allocates every event id, sequence, and timestamp for a
  stream.
- independent streams do not claim a global ordering guarantee.
- Store append completes before the committed-record event is observed.
- committed-record revision, record id, and timestamp come from the exact
  `CommitReceipt`, including under concurrent append attempts.
- Store append failure publishes no committed-record event.
- an idempotent application-message hit does not publish a duplicate commit
  fact.
- listener failure preserves current ordering and exception propagation while
  not rolling back or duplicating Store append.
- Agent event, Extension mirror, Work projection, and current Coding JSON shapes
  remain behaviorally equivalent.
- retry, compaction, diagnostics, and resource progress control behavior is
  unchanged.

### Integration Tests

- new, restore, resume, fork, clone, import, branch navigation, rename, list,
  find, delete, export, compaction, and extension messages remain functional;
- RPC, print, TUI, HTML, and Work projections remain stable;
- full non-live suite passes;
- neutral Harness storage/events import no Agent, Product, Work, Method,
  Channel, TUI, provider, auth, registry, or model-call modules; only the
  optional Agent Transcript adapter imports Agent event data.

## Explicit Non-Goals

This migration does not:

- implement SQLite, PostgreSQL, SQLAlchemy, Redis, or another external driver;
- define a generic database query language or ORM;
- implement cache, distributed lease, persistent idempotency, event transport,
  event log, outbox, CDC, replication, or cross-process subscription;
- promise exactly-once delivery;
- add an Extension manifest storage surface or runtime Store replacement;
- define plugin discovery, signing, trust, secrets, or marketplace behavior;
- support Store hot swapping or backend-to-backend migration;
- redesign Conversation JSONL schema or support older Loushang formats;
- redesign AgentEvent, WorkEvent, ChannelEnvelope, extension hooks, approval,
  policy, workflow, artifacts, or UI;
- move Product paths, summaries, retention, recovery decisions, wire formats, or
  presentation into Harness;
- turn Harness into a service locator or dependency-injection framework.

## Completion Criteria

The wave is complete only when:

- Coding uses an injected Store protocol and no session runtime assumes File;
- the default Coding composition still uses the Conversation JSONL File format;
- common transcript/session persistence mechanics no longer live in Coding;
- common runtime and Work observers no longer require the Coding event union;
- Product event and storage policies remain visibly outside Harness;
- Memory, File, and fake OEM provider contract tests pass;
- Store commit and runtime event ordering is covered at failure boundaries;
- the one retained Host event-bus compatibility path is documented;
- architecture docs and import gates match the implemented ownership.
