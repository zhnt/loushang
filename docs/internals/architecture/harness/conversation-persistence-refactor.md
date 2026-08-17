# Conversation Persistence Refactor

## Status

Status: persistence phases 1–3 implemented on
`harness/conversation-persistence-refactor`; Product resume/picker work in
Phase 4 remains a follow-on.

This document is the current storage-boundary decision. It supersedes the
earlier package placement in the conversation, Agent transcript, catalog, and
file-store boundary notes. The implementation does not change the Conversation JSONL
format.

Implemented storage outcomes:

- `journal` contains only codec-driven JSONL mechanics;
- `conversation` owns branches, the in-memory repository, Store contracts,
  reference providers, provider-bound catalog, and revision-aware indexes;
- `transcript` owns `AgentTranscriptUnitOfWork`, Native file composition,
  Agent summary/query projection, and read-only legacy import;
- top-level `harness.storage`, journal repositories/branches/indexes, direct
  Native append helpers, and in-place Session v3 migration are removed;
- File Store I/O runs off the event loop, append/delete critical sections are
  shielded, and load/commit recovery diagnostics cross the Store boundary;
- existing direct resume behavior remains, while the project/worktree picker
  and fully provider-bound Product transition are explicitly Phase 4.

The refactor has four goals:

1. keep `journal` a genuinely reusable physical JSONL primitive;
2. make `conversation` the only owner of conversation structure and storage
   contracts;
3. make `transcript` an Agent-specific application/profile layer rather
   than a second persistence subsystem;
4. define catalog and resume flows that can work with file, database, and
   remote backends without making an index authoritative.

## Decision Summary

The target is a dependency graph, not three interchangeable storage layers:

```text
work.event_logs.jsonl ─────────────────────> journal
conversation.jsonl_codec / stores.file ──> journal
transcript ─────────────────────────> conversation
transcript.jsonl_file ─────────────> journal
harness.session / Product runtime ────────> transcript
CLI / TUI ────────────────────────────────> Product operations
```

`transcript` may also compose Native journal codecs and file-layout
factories, but it must not bypass `ConversationStore` for authoritative writes.

The shortest useful statement of ownership is:

```text
journal
  I safely append, load, and rewrite typed JSONL. I do not know record meaning.

conversation
  I know conversation envelopes, branches, revisions, storage ports, and
  rebuildable discovery/index mechanics. I do not know AgentMessage.

transcript
  I know Agent payload codecs, replay, commit coordination, and Agent session
  summaries. I do not define another durable-store protocol.

harness.session / Product runtime
  I choose and bind providers, project Product events, prepare resume
  candidates, and atomically replace the active session.

CLI / TUI
  I turn user input into Product operations and present their results. I do
  not load snapshots or choose storage providers directly.
```

## Package Ownership

### `loushang.harness.journal`

`journal` owns only physical, schema-parameterized JSONL mechanics:

- append, load, and rewrite;
- file locking, atomic replacement, flush, and `fsync`;
- header and record codec protocols;
- format, durability, and load policies;
- physical diagnostics such as malformed lines and truncated tails.

It must not own:

- conversation records, parent links, branches, trees, or deltas;
- conversation keys, snapshots, revisions, or compare-and-swap;
- session discovery or product search fields;
- Agent messages, replay, compaction, or resume behavior;
- a generic JSON snapshot index merely because its implementation uses a file.

`journal` remains independent because more than one domain adapter needs the
same physical primitive. For example, Work owns its own `EventLogBackend`
contract, and its JSONL adapter may use `journal` without sharing conversation
schemas or storage contracts.

### `loushang.harness.conversation`

`conversation` owns the neutral conversation domain:

- `ConversationHeader`, `ConversationRecord`, opaque payloads, tree nodes, and
  branch deltas;
- branch validation, active paths, children, trees, lowest common ancestors,
  forks, deltas, and folds;
- Native conversation-envelope codecs and payload-codec routing;
- a single in-memory `ConversationRepository`;
- `ConversationStore`, its key/snapshot/receipt types, compare-and-swap
  semantics, and storage errors;
- file and memory store adapters;
- backend-neutral enumeration and load descriptors;
- rebuildable projection-index contracts and local reference adapters;
- replay/folder and projector ports.

It must not import Agent, AI, Coding, Work, Method, Product, or TUI types.

### `loushang.harness.transcript`

`transcript` is an Agent-specific profile and application layer:

- Agent transcript payload kinds and codecs;
- mapping between conversation records and `AgentMessage`;
- Agent replay and restoration of model/thinking state;
- commit coordination over a repository plus `ConversationStore`;
- Agent-specific `AgentTranscriptSummary` projection and search semantics;
- Native file-layout and codec composition;
- transcript import/export and migration where Agent meanings are required;
- session factory, passive transcript-resource lifecycle, compaction
  integration, and interaction helpers.

It does not own a second persistence protocol or a second authoritative writer.
Names such as `AgentTranscriptSessionStore` and
`AgentTranscriptFileStore` currently blur that boundary and should be replaced
with application- or composition-oriented names during the migration.

An Agent-specific catalog remains valid: `conversation` can enumerate
conversation sources and host a generic projection index, but it cannot derive
Agent titles, previews, message counts, model fields, or Agent search text.
The Agent catalog therefore owns the projection and query vocabulary, not
physical discovery, Product/project identity, or durable transcript storage.

`transcript` must not import `harness.session`, CLI, TUI, or a concrete
Product. Its commit layer returns a receipt plus neutral Agent transcript data;
it does not publish Product events or replace the active Product session.

### Harness Session and Product Runtime

The session/Product layer owns:

- the selected and registered `ConversationStore` providers;
- storage roots, project identity, worktree/repository identity, retention, and
  final filename policy;
- current-directory and cross-worktree resume scopes;
- resource, policy, trust, extension, and runtime re-binding after resume;
- active-session transition locking, quiescence, pointer swap, and disposal;
- Product event projection and best-effort index-refresh scheduling;
- the decision to continue in place, re-bootstrap, or relaunch for a session
  belonging to another project context.

The Agent Native profile can provide a default filename convention and pure
layout factory. The Product chooses the root and may override that convention.

### CLI and TUI

CLI and TUI own flags, `/resume`, picker interaction, diagnostics wording, and
presentation. They construct `ResumeRequest` values and invoke Product
operations. They do not hold a Store, load a snapshot, interpret Agent records,
or perform the active-session swap.

Resume is not a storage primitive. It is Product orchestration over the
conversation and Agent transcript layers.

## Target Package Shape

The exact module split can follow file size, but ownership should converge on:

```text
loushang/harness/
├── journal/
│   ├── __init__.py
│   ├── codec.py
│   ├── jsonl.py
│   └── types.py
│
├── conversation/
│   ├── __init__.py
│   ├── types.py
│   ├── diagnostics.py
│   ├── branch.py
│   ├── repository.py
│   ├── jsonl_codec.py
│   ├── replay.py
│   ├── ports.py
│   ├── store.py
│   ├── catalog.py
│   ├── index.py
│   ├── stores/
│   │   ├── __init__.py
│   │   ├── memory.py
│   │   └── file.py
│   └── indexes/
│       ├── __init__.py
│       ├── memory.py
│       └── json_file.py
│
├── transcript/
│   ├── types.py
│   ├── kinds.py
│   ├── codecs.py
│   ├── profile.py
│   ├── unit_of_work.py
│   ├── session.py
│   ├── committer.py
│   ├── jsonl_file.py
│   ├── session_catalog.py
│   ├── session_factory.py
│   ├── lifecycle.py
│   └── ...
│
└── session/
    ├── resume.py
    ├── transition.py
    └── ...
```

This removes the top-level `harness.storage` package. A future storage provider
implements `conversation.store.ConversationStore`; it does not require a
product-neutral top-level storage namespace.

## Repository and Store Model

### One repository, in memory

The target has one canonical `ConversationRepository`. The current
`TranscriptRepository` implementation and delegating `ConversationRepository`
are merged under that name.

Its target responsibilities are:

- construct state from a `ConversationSnapshot`;
- validate and produce candidate appends;
- expose header, revision, record, active-path, branch, tree, delta, and fold
  operations;
- create a forked in-memory state;
- return a new repository state or candidate records without doing I/O.

Its target API should resemble:

```python
repository = ConversationRepository.from_snapshot(snapshot)
candidate = repository.with_appended(records)
```

The final repository must not:

- accept a `JsonlJournal`;
- expose `load(journal)`, `rewrite()`, or direct durable append methods;
- own `path`, `source_path`, file locks, or codec factories;
- expose an internal `.transcript` escape hatch;
- mutate accepted state before the durable compare-and-swap succeeds.

During the structural migration, the old persistence surface may temporarily
remain behind a private compatibility adapter. It is removed when the
authoritative write path is converged.

### One authoritative storage port

`ConversationStore` owns durable snapshot and revision semantics. The target
keeps the current single-record append model and makes load diagnostics part of
the contract:

```python
@dataclass(frozen=True)
class ConversationLoadResult:
    snapshot: ConversationSnapshot
    diagnostics: tuple[ConversationLoadDiagnostic, ...]


@dataclass(frozen=True)
class ConversationHead:
    key: ConversationKey
    revision: int
    updated_at: datetime


@dataclass(frozen=True)
class ConversationPage:
    heads: tuple[ConversationHead, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class ConversationCommitResult:
    receipt: CommitReceipt
    diagnostics: tuple[ConversationLoadDiagnostic, ...] = ()


class ConversationStore(Protocol):
    async def create(
        self,
        key: ConversationKey,
        header: ConversationHeader,
        initial_records: Sequence[ConversationRecord] = (),
        *,
        operation_id: str,
    ) -> ConversationSnapshot: ...

    async def load(
        self,
        key: ConversationKey,
        *,
        policy: ConversationLoadPolicy,
    ) -> ConversationLoadResult: ...

    async def append(
        self,
        key: ConversationKey,
        record: ConversationRecord,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> ConversationCommitResult: ...

    async def delete(
        self,
        key: ConversationKey,
        *,
        expected_revision: int,
        operation_id: str,
    ) -> DeletionReceipt: ...

    async def scan_page(
        self,
        namespace: str,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ConversationPage: ...
```

The contract owns:

- `ConversationKey`;
- `ConversationSnapshot`;
- `ConversationLoadResult` and load policies;
- `CommitReceipt`, `ConversationCommitResult`, and `DeletionReceipt`;
- not-found, already-exists, conflict, corruption, and unsupported-operation
  errors;
- compare-and-swap behavior and the meaning of revision.

Revision is the count of durable conversation records. An empty create has
revision `0`; an atomic create with initial records has revision
`len(initial_records)`; a successful single append increments it by one.
`create` makes the header and every initial record visible atomically so fork
and import cannot leave a partially created target.

`ConversationHead.updated_at` is derived from authoritative conversation
content: the last durable record's `created_at`, or the header's `created_at`
for an empty conversation. It is not filesystem `mtime`, so copying a file
does not change recent-session ordering.

`operation_id` is stable across retry and normally derives from the immutable
record id. A provider either deduplicates it or raises
`StoreCommitOutcomeUnknown` when it cannot tell whether the durable commit
occurred. The caller then reloads and reconciles by operation/record id before
retrying. It must not blindly repeat an append after a lost response. The
Native adapter uses the existing record id and adds no JSONL field.

Create and delete are idempotent operations too. Repeating the same operation
id with the same request returns the original outcome; reusing it for different
content is an identity conflict. Delete is revision-conditional so a stale
retention scan cannot delete a subsequently updated conversation. Its receipt
records the deleted revision and operation id.

`load` is always read-only. Policies distinguish inspection-compatible,
resume-safe, and writable-intent validation, but no policy silently repairs or
migrates a source. A file append may repair an explicitly recoverable partial
tail only while holding the same exclusive lock used for load, CAS, append,
and `fsync`; `ConversationCommitResult.diagnostics` reports that recovery. A
complete malformed record remains corruption.

`MemoryConversationStore` and `FileConversationStore` are reference adapters.
SQLite, PostgreSQL, object-store, or remote-service providers can be added
without changing repository or Agent transcript semantics.

The store is authoritative. An index, cache, or picker entry is never evidence
that a transcript commit succeeded.

### Maintenance and identity

- fork and import-to-a-new-key use atomic `ConversationStore.create(...,
  initial_records=...)`;
- retention uses `ConversationStore.delete`;
- semantic in-place replacement is not supported because record-count revision
  cannot distinguish equal-length snapshots;
- a `ConversationKey` is never reused, including after deletion; providers
  retain a tombstone or equivalent durable identity record;
- legacy migration means read the legacy source, validate it, atomically create
  a new Native key, then leave the source untouched;
- physical maintenance may rewrite a Native file only when the decoded header
  and record sequence are identical; it cannot change conversation meaning or
  revision;
- export writes a non-authoritative derived artifact and is outside the
  authoritative Store invariant.

Direct Native writes are statically allowlisted to the file Store and its
identity-preserving physical-maintenance helper. Agent layout, repository,
catalog, Product, and ordinary migration helpers may not call journal
append/rewrite directly. The current in-place `migrate_session_v3_file`
behavior is retired and recorded as an intentional API behavior change.

### Commit sequence

The current `AgentTranscriptSessionStore` should become
`AgentTranscriptUnitOfWork`; it owns the bound key, revision, repository, and
single commit lock. The existing `AgentTranscriptSession` remains the
Agent-semantic facade over that unit of work:

```text
AgentTranscriptUnitOfWork
  1. validates and builds candidate records in ConversationRepository
  2. calls ConversationStore.append(..., expected_revision, operation_id)
  3. accepts the candidate state only after ConversationCommitResult
  4. returns AgentTranscriptCommit(record, receipt, diagnostics)

harness.session / Product runtime
  5. projects Product events
  6. schedules rebuildable catalog-index maintenance
```

Everything after the receipt is a post-commit projection. An event or index
failure is reported and scheduled for repair; it must not roll back, obscure,
or turn an already successful transcript append into a failed append result.
Products requiring reliable event publication use an outbox rather than a
fallible synchronous callback.

`FileConversationStore` is the only authoritative Native file writer:

```text
ConversationStore.append
  -> FileConversationStore
  -> JsonlJournal
  -> lock / CAS / append / fsync
```

No migration helper, Agent file-layout helper, repository, catalog, or Product
session may append the same Conversation JSONL transcript through a parallel path.

## Diagnostics

Diagnostics follow the layer that can interpret them:

- `JournalDiagnostic` describes physical JSONL load/recovery facts;
- `ConversationDiagnostic` describes invalid parents, duplicate record ids,
  cycles, missing branch leaves, and other conversation invariants;
- Agent and Product diagnostics add decoding, replay, binding, and UX context.

`BranchGraph` must not return a `JournalDiagnostic` after it moves into
`conversation`.

A Store load always returns the `ConversationLoadResult` defined by the Store
contract, never a bare snapshot. Physical diagnostics are translated into
stable `ConversationLoadDiagnostic` variants at that boundary.
`ConversationRepository.open(load_result)` then returns a
`ConversationOpenResult` containing the repository plus any semantic
diagnostics added by branch validation. Agent and Product layers may decorate
that result, but they do not have to reopen the source to recover diagnostics.

```python
@dataclass(frozen=True)
class ConversationOpenResult:
    repository: ConversationRepository
    diagnostics: tuple[
        ConversationLoadDiagnostic | ConversationDiagnostic,
        ...,
    ]
```

Strict corruption is an exception. Compatible recovery is a successful result
with diagnostics. Phase 0 freezes each existing diagnostic's code, severity,
path, line, details, and strict/compatible behavior before types move.

## Discovery, Catalog, and Index

These are three different concepts:

| Concept | Authority | Responsibility |
| --- | --- | --- |
| Store provider | authoritative | Enumerate, create, load, append, delete, and compare revisions |
| Federated catalog | authority-preserving read model | Project entries from one or more bound providers |
| Projection index | rebuildable | Accelerate summary, filtering, ordering, and search |

### Provider-bound discovery

A catalog must not discover future database-backed sessions by recursively
scanning `.jsonl` files. It consumes the `scan` and `load` capabilities of the
same bound Store provider that will receive a later append. There is no second
catalog `load` path.

```python
@dataclass(frozen=True)
class ConversationLocator:
    provider_id: str
    key: ConversationKey


@dataclass(frozen=True)
class ConversationDescriptor:
    locator: ConversationLocator
    source_revision: int
    updated_at: datetime


@dataclass(frozen=True)
class ConversationProviderBinding:
    provider_id: str
    store: ConversationStore


@dataclass(frozen=True)
class ProductConversationProviderRegistration:
    provider: ConversationProviderBinding
    project: ProjectIdentity
    repository: RepositoryIdentity | None
    worktree: WorktreeIdentity | None
    trust_domain: str
    lifecycle: Literal["persistent", "process", "request"]
```

`ConversationProviderBinding` is neutral and can be consumed by the Agent
catalog without importing Product types.
`ProductConversationProviderRegistration` is Product-owned and adds scope,
trust, and provider-lifetime policy. The Product registry uses a provider id
stable across processes; renames retain an alias until locators/index rows are
migrated. A federated catalog wraps each Store result with that id; resume
resolves the locator back to the exact Store and validates the Product
registration. Two providers may contain the same `ConversationKey` without
colliding because the locator includes provider identity.

Provider-internal paths, database row ids, and service tokens stay inside the
provider. An explicit external path is resolved by Product policy into a
temporary/read-only file provider binding or an import operation before it
becomes a locator. No physical locator lives on
`ConversationRepository`.

`scan_page` is asynchronous and paginated at the provider boundary.
Cancellation and partial-page failure must be observable. This deliberately
avoids the ambiguous Protocol spelling `async def scan() -> AsyncIterator`;
an implementation that later chooses streaming would instead declare
`def scan(...) -> AsyncIterator[...]`.

File-provider locking, directory scans, whole-file reads, repair, append, and
`fsync` are blocking work and must run in a dedicated worker/executor. Once a
durable commit enters its non-cancellable critical section it is shielded and
returns a receipt or `StoreCommitOutcomeUnknown`.

### Rebuildable projection index

Conversation owns neutral envelopes and projection CRUD; query syntax is
generic so Agent search fields do not leak down:

```python
@dataclass(frozen=True)
class IndexedProjection(Generic[ProjectionT]):
    locator: ConversationLocator
    source_revision: int
    projection: ProjectionT


class ConversationIndex(Protocol[ProjectionT, QueryT]):
    async def upsert(self, item: IndexedProjection[ProjectionT]) -> bool: ...
    async def delete(
        self,
        locator: ConversationLocator,
        *,
        through_revision: int,
    ) -> bool: ...
    async def get(
        self,
        locator: ConversationLocator,
    ) -> IndexedProjection[ProjectionT] | None: ...
    async def query(
        self,
        query: QueryT,
    ) -> Sequence[IndexedProjection[ProjectionT]]: ...
```

`upsert` rejects an older revision overwriting a newer one. Index deletion
retains a tombstone through the deleted revision and rejects a late upsert at
or below it; Store keys are not reused. A complete rebuild publishes a new
generation atomically only after every required provider scan finishes; a
partial scan preserves the previous good generation and reports
per-descriptor diagnostics. Delete/reconcile removes ghost rows.

The Agent catalog supplies a serializable `AgentTranscriptQuery` and projector.
The existing callable-based `ProjectionQuery` remains an in-process collection
utility; it is not the Redis/SQL protocol. A picker selection always reloads
through the authoritative Store and validates the returned revision.

The current JSON projection index moves out of `journal`: it writes an ordinary
JSON snapshot and implements discovery acceleration, not append-only journal
semantics.

### Redis policy

Redis is suitable by default for a rebuildable session index or bounded cache,
not for the only complete transcript.

Reasonable Redis projection fields include:

- provider id, conversation key, and source revision;
- Agent transcript title, preview, timestamps, message count, and model name;
- labels, Agent status, durable head, and bounded search text;
- TTL-based picker or search caches.

The Product may decorate an `AgentTranscriptSummary` into a separate
`ProductSessionSummary` with project, repository, worktree, trust, and resume
scope. Those Product fields do not become Agent transcript semantics.

Full records, tool outputs, artifacts, large checkpoints, and the only copy of
a transcript remain in an authoritative Store unless a separately designed
Redis Store explicitly defines durability, capacity, persistence, backup,
large-value, atomic-CAS, and recovery guarantees.

Redis upserts use a transaction or Lua check so an old revision cannot replace
a new one. Keys are tenant/Product/provider namespaced. ACL, transport
encryption, retention, and deletion propagation are mandatory deployment
concerns. Even bounded search text may contain sensitive prompts or code, so a
shared Redis index is opt-in. TTL expiry means cache miss, never transcript
deletion or authoritative non-existence.

## Agent Transcript File Composition

The current Agent transcript file module has valid Agent-specific work, but its
name should describe composition rather than a second Store.

The target `transcript.jsonl_file` may own:

- Native header/record codec assembly;
- payload codec registration;
- a default filename convention and pure layout helpers shared by Agent
  products;
- creation of a configured `FileConversationStore`;
- read-only import/export and format-recognition helpers;
- Native migration decoding that requires Agent payload meaning and submits
  the result through atomic Store create under a new key.

It must not own a direct durable append path beside
`FileConversationStore.append`.

Likewise, `transcript.session_catalog` may own:

- projection from a loaded Agent transcript to `AgentTranscriptSummary`;
- title, preview, message-count, model, status, and search-field derivation;
- Agent-specific filters, ranking, and tolerant projection policy.

It must consume bound Store providers and `ConversationIndex`, not scan the
filesystem directly in the final architecture. Tolerant listing records
per-descriptor failures; it must not silently replace a good index generation
with a partial result.

## Resume Flow

### Current baseline

Resume is not starting from zero. The current Harness/Coding stack already
provides:

- CLI parsing for `--continue`, `--resume`, and `--resume <reference>`;
- direct restore through the shared session-resolution and lifecycle ports;
- `/resume <session-id-or-path>` in the standard session command pack;
- recent-session selection and Native restore in
  `AgentTranscriptSessionFactory`;
- a file-backed Agent session catalog and current-root/all-root queries.

The missing target capability is principally interactive selection,
project/worktree-aware grouping, and discovery that is not coupled to Native
files. The migration must preserve direct restore while replacing its
file-specific lookup inputs.

### Boundary objects

Binding cannot be resolved safely before the authoritative header is loaded.
Resume therefore uses two Product-owned stages:

```python
@dataclass(frozen=True)
class ResolvedResumeLocator:
    locator: ConversationLocator
    project_hint: ProjectIdentity | None = None


@dataclass(frozen=True)
class PreparedResumeCandidate:
    locator: ConversationLocator
    load_result: ConversationLoadResult
    repository: ConversationRepository
    agent_state: AgentTranscriptContext
    binding_input: ProductBindingInput
    product_session: ProductTranscriptSession
```

CLI text, a picker row, or an explicit path first resolves to
`ResolvedResumeLocator`. A strict read-only load validates the header; only
then may Product policy construct trusted `binding_input`, resolve resources,
and prepare the candidate. Neither type is neutral persistence state.

### Runtime sequence

```text
/resume argument or picker selection
  -> CLI/TUI emits ResumeRequest
  -> Product resolves provider-bound locator
  -> exact provider performs strict read-only load
  -> ConversationRepository opens the load result
  -> Agent profile decodes/replays the durable head
  -> Product resolves resources and prepares candidate binding/session
  -> session lifecycle commits one active-pointer/UI-model swap
  -> old session disposal, events, and index refresh run post-commit
```

The active-session transition is explicitly two-phase:

1. prepare the locator, snapshot, repository, Agent replay, resources, binding,
   and candidate session in isolation;
2. acquire the transition lock, quiesce the old session, perform all remaining
   fallible binding work, then execute one non-throwing active-pointer/UI-model
   swap as the commit point.

The first implementation rejects `/resume` while a turn, approval, transcript
commit, or queued mutation is active. A later implementation may offer
wait/cancel, but it must drain commits before the swap. Prepare failure releases
the candidate and leaves the current session active. Any failure after
quiescence but before the swap must dispose the candidate, unquiesce the old
session, and restore input/queue acceptance. The active pointer and UI model are
one indivisible aggregate-state assignment, not two fallible writes. After the
swap, old-session dispose, Product event, or index failure becomes a
diagnostic; it does not make the caller believe resume failed.

Any binding that mutates non-rollbackable process-global state is not eligible
for in-process switching. Cross-project resume uses a relaunch/copyable command
until the Product can prove transactional preparation.

Resume should never be implemented as “read arbitrary JSONL and replace the
message list.” It restores revision, the complete branch tree, the path to the
durable head, profile/version, model and thinking state, Product state, and
runtime bindings together.

For this no-format-change migration, the durable head is the last successfully
appended conversation record. Selecting an older branch without appending is
ephemeral UI state and is not restored after process restart. Persisting that
selection later requires a separate append-only selection record or
revision-CAS metadata proposal; a rebuildable index is never authoritative for
it.

### CLI and command behavior

Recommended semantics:

- `--continue`: resume the newest compatible session in the default scope;
- `--resume`: open the interactive picker when a TTY is available and fail
  with guidance in non-interactive mode;
- `--resume <id|name|path>`: resolve and resume directly;
- `/resume`: open the picker inside an active interactive session;
- `/resume <id|name|path>`: resolve and replace directly.

Changing non-interactive, argument-free `--resume` from its current
latest-session alias is an intentional CLI compatibility change:
`--continue` remains the unambiguous latest-session command.

Reference resolution is deterministic: an explicit path is recognized first;
otherwise exact id, unique id prefix, and unique name are tried in that order.
Ambiguous matches are errors. An already active locator is a no-op. An external
or legacy-format path is offered as import and is never repaired, migrated, or
rewritten by resume preparation.

Unqualified id/prefix/name lookup is limited to the current project/worktree
provider set. Cross-worktree/project selection uses the picker or an explicit
stable `provider_id:reference` qualifier. Provider aliases make registry
renames resolvable during a controlled migration; implicit global search is
never used.

Recommended picker scopes:

1. current project/worktree, selected by default;
2. other worktrees of the same repository;
3. all explicitly registered projects.

`ProjectIdentity` is a registered Product project id, falling back to a
canonical project root for an unregistered project. `RepositoryIdentity` is
derived from the Git common directory, not a worktree root.
`WorktreeIdentity` combines repository identity with the worktree Git
directory/root. Non-Git projects have no repository aggregation. Moved or
deleted worktrees remain unavailable until their explicit registry entry is
updated; duplicate registrations are rejected by canonical identity.

`--continue` never crosses the current project/worktree scope. “Newest” is
ordered by authoritative update time, then locator for a stable tie-break.
Candidates are validated read-only; corrupt or incompatible entries are
reported, not automatically repaired. A load race is reported instead of
silently switching to a different session.

Do not model “upper directory history” as an unbounded recursive parent scan.
Repository/worktree identity is more stable and avoids surfacing unrelated or
untrusted sessions. A path remains an explicit escape hatch.

Resuming a session from another project cannot silently keep the current
project's runtime binding. The Product must either:

- fully re-bootstrap the runtime in the target context; or
- offer a relaunch/copyable command in the target directory.

The latter is an acceptable first implementation if in-process re-binding is
not yet transactional.

## Concrete Moves and Renames

| Current location or name | Target | Reason |
| --- | --- | --- |
| `journal/branch.py` | `conversation/branch.py` | Branches are conversation semantics |
| `journal` `TranscriptRepository` implementation | merge into `conversation/repository.py` | One canonical repository |
| delegating `ConversationRepository` | replace with merged implementation | Remove forwarding and `.transcript` escape hatch |
| `storage/protocols.py`, types, errors | `conversation/store.py` | The port speaks conversation schema and revision semantics |
| `storage/file.py` | `conversation/stores/file.py` | Native file provider for the conversation port |
| `storage/memory.py` | `conversation/stores/memory.py` | Reference provider for the conversation port |
| `journal/index.py` | `conversation/indexes/json_file.py` | It is a rebuildable JSON projection, not a journal |
| `transcript/store.py` | `transcript/unit_of_work.py` and `AgentTranscriptUnitOfWork` | It owns the bound repository/revision/CAS transaction; it is not the backend |
| `transcript/file_store.py` | `transcript/jsonl_file.py` | It composes Agent codecs/layout with the file provider |
| `transcript/catalog.py` | `transcript/session_catalog.py` | It owns Agent summary/search meaning, not physical storage |

Avoid a large `conversation/store.py` only for aesthetic consolidation. Keep
the public contract, value types, and errors together while implementation
providers remain separate; split internal modules later if the contract itself
becomes difficult to navigate.

## Migration Plan

### Phase 0: characterization

Before moves:

- freeze Conversation JSONL byte fixtures covering every Agent payload kind,
  non-ASCII text, opaque/future payloads, future headers, invalid complete
  lines, and partial tails;
- characterize strict and compatible load behavior, including diagnostic code,
  severity, path, line, details, and whether the source changes;
- characterize branch selection, fork, tree, delta, replay, and compaction;
- characterize atomic create-with-records, revision/CAS, lock, receipt,
  deletion, and partial-tail append behavior;
- record catalog ordering, tolerant projection, and resume behavior;
- inventory every production caller allowed to append/rewrite Conversation JSONL;
- build a symbol ledger for every exported
  `harness.storage.*`, `journal.BranchGraph`,
  `journal.TranscriptRepository`, `journal.JsonProjectionIndex`,
  `AgentTranscriptSessionStore`, and direct Agent file helper, including old
  path/name, target, signature/exception change, and removal test;
- add import-boundary tests for the target dependency directions.

### Phase 1: serialized behavior unchanged; intentional Python API cutover

1. **1a — diagnostics and graph:** define the load/open result contracts, move
   `BranchGraph`, and preserve diagnostic parity.
2. **1b — repository:** merge implementations under
   `ConversationRepository` while preserving the current Agent candidate-state
   commit behavior.
3. **1c — Store:** move the contract/reference adapters, retain atomic
   create/delete/scan, and add load-result conformance.
4. **1d — index:** move the JSON projection index out of `journal` without yet
   changing catalog behavior.
5. **1e — Agent names:** rename the unit-of-work and Native composition
   modules, then update all imports and exports.

Each subphase must pass targeted behavior tests, import-boundary tests, and a
static check that it introduced no new Native writer. No serialized JSONL bytes
change.

### Phase 2: converge authoritative writes

1. Remove the repository's remaining journal parameter and direct persistence
   surface.
2. Route create, append, fork/import, and revision-conditional delete through
   Store capabilities; limit physical rewrites to identity-preserving
   maintenance.
3. Preserve the existing rule that candidate repository state is accepted only
   after a successful receipt.
4. Add operation-id reconciliation and outcome-unknown tests.
5. Remove Agent-layout and ordinary migration direct writes.
6. Enforce the Native-writer allowlist with an architecture/static test.

This phase is deliberately separate because it changes transaction ownership,
not merely file placement.

### Phase 3: backend-neutral catalog and index

1. Introduce provider ids, locators, Store heads, and a Product provider
   registry.
2. Make the Agent session catalog enumerate and load through the same bound
   Store.
3. Make Agent catalog project `AgentTranscriptSummary` and Product decorate
   `ProductSessionSummary`.
4. Define revision-conditional upsert, deletion reconciliation, atomic
   generation rebuild, and partial-scan diagnostics.
5. Retain memory/JSON index adapters and add Redis only as an optional
   rebuildable adapter.

### Phase 4: resume

1. Preserve the existing direct `/resume <ref>`, `--resume <ref>`,
   `--continue`, and recent-session behavior with characterization tests.
2. Add project/worktree-aware enumeration and provider-bound locators.
3. Add no-argument `/resume` and its TUI picker.
4. Evolve interactive `--resume` from “latest” to the same picker while keeping
   `--continue` as the unambiguous latest-session command.
5. Add isolated candidate preparation, busy-session rejection, and the
   two-phase active-session transition.
6. Use an explicit cross-project relaunch until Product re-binding is proven
   transactional.

### Phase 5: optional Work cleanup

If `work.event_log` is too broad, split its domain contract from providers:

```text
work/event_log.py
work/event_logs/memory.py
work/event_logs/jsonl.py
```

This is independent of the conversation migration. Work continues to depend on
its own `EventLogBackend`; only its JSONL adapter depends on `journal`.

## Compatibility Strategy

Decision for this Harness migration lane: perform one repository-wide atomic
Python import cutover and do not add deprecated re-export shims. Although the
current symbols appear in `__all__`, they have not been accepted as a stable
external contract for this lane. The Phase 0 symbol ledger drives removal and
tombstone tests.

In particular, do not re-export conversation classes from `journal`; that
would recreate the old ownership and risks dependency cycles. If release
management declares any old path externally supported before implementation,
pause and record a separate compatibility ADR with warning and removal
versions rather than making this plan conditional.

Conversation JSONL uses one compatibility-oriented decoder:

- new sessions write `CURRENT_CONVERSATION_FORMAT_VERSION`;
- the decoder accepts every released version from the minimum supported version
  through the current version;
- schema evolution is additive: new fields are optional, missing fields receive
  defaults, and unknown optional fields are ignored;
- existing field names, types, and meanings are not changed after 1.0;
- breaking payload changes use `payloadVersion` or a new record `kind`;
- external JSONL families are skipped during discovery and are never rewritten.

Session v3 is a separate pre-1.0 format family. It is not part of Resume
discovery or the Conversation JSONL compatibility promise.

## Verification Gates

The refactor is complete only when these gates pass:

- Conversation JSONL golden fixtures and append bytes for the Phase 0 fixture matrix
  are unchanged;
- branch, fork, tree, delta, replay, and compaction characterization tests pass;
- memory and file adapters pass the same Store conformance suite;
- create-with-initial-records is atomic and revision remains record count;
- create/append/delete operation ids are idempotent, payload mismatches are
  rejected, and lost responses have a deterministic reconciliation path;
- stale revision delete conflicts, deleted keys cannot be reused, and durable
  tombstones reject late index upserts;
- two independent Store instances produce the same CAS conflict behavior;
- partial-tail load is read-only and append repairs only under the commit lock;
- lost-response/outcome-unknown reconciliation cannot duplicate a record;
- any explicit legacy import leaves its source unchanged;
- a failed commit does not mutate accepted in-memory repository state;
- observer and index failures cannot mask a successful receipt or cause a
  duplicate retry;
- diagnostic exception/result parity is preserved across journal,
  conversation, Agent, and Product layers;
- stale/missing indexes rebuild from authoritative sources, lower revisions
  cannot overwrite higher revisions, deletion removes ghosts, and malformed or
  unrelated source files do not prevent valid summaries from being published;
- catalog tests run against a non-filesystem fake Store provider and disambiguate
  the same key in two providers;
- a projection-only fake index proves listing/search do not require complete
  transcripts; Redis conformance is required only when a Redis adapter ships;
- detached and persisted resume restore equivalent Agent/Product state;
- strict resume preparation never repairs, migrates, or rewrites its source;
- failed prepare/bind leaves the current session active, while post-swap
  dispose/event/index failures do not reverse the reported outcome;
- a failure after quiescence but before swap restores old-session input and
  queue acceptance;
- busy turn/approval/commit/queue, same-session no-op, TTY/non-TTY, ambiguous
  id/name/path, moved worktree, and cross-provider resume cases are covered;
- selecting an old branch without appending resumes the last durable record,
  documenting the intentionally ephemeral selection;
- Work's memory and JSONL event-log adapters remain behavior-compatible;
- architecture tests enforce imports, old-symbol tombstones, and the Native
  writer allowlist;
- Ruff, mypy, targeted suites, the full non-live Harness/Coding/TUI suites, and
  `git diff --check` pass.

## Architecture Invariants

After migration:

```text
journal             must not import conversation, transcript, or Product
conversation        must not import Agent, AI, Coding, Work, Method, Product, TUI
transcript    may import conversation and compose journal codecs
harness.session /
Product runtime     may import transcript and owns active transitions
CLI / TUI           invokes Product operations and owns presentation only
```

And:

1. every authoritative conversation write crosses `ConversationStore`; only
   identity-preserving physical maintenance may rewrite the same logical
   snapshot outside its mutation surface;
2. every projection index is disposable and rebuildable;
3. a repository contains conversation state, not a physical source locator;
4. Agent catalog semantics do not leak into neutral conversation;
5. Redis is not assumed to be the durable transcript source;
6. resume restores a prepared, provider-bound Product session, not only decoded
   messages;
7. pure branch selection remains ephemeral until a separate persistence
   proposal changes the Native format or Store metadata.

These invariants are more important than reducing the raw package or file
count. The refactor is successful when each name denotes one role and each
durable transition has one owner.
