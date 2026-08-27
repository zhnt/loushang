# Project-Declared Configuration And Pluggable Conversation Persistence

## Status

- Authority: proposed — non-normative cross-scope architecture draft
- Design status: proposed
- Implementation status: partial foundations exist; target composition and
  SQLite authority are not implemented
- Date: 2026-08-21
- Owners affected: Harness configuration, conversation, transcript, runtime,
  resources and security; Coding Product bootstrap, continuity and diagnostics
- Scope: project declarations, private user state, project identity,
  persistence-provider registration and selection, JSONL and SQLite backends,
  catalog federation, migration and recovery

This document is a review input. It does not replace accepted architecture,
current source, executable tests or an adopted architecture decision. Any
normative adoption must update the owning Harness and Coding architecture
documents and add the corresponding executable gates.

## 1. Executive Decision

Loushang should separate repository-declared configuration from private runtime
state and should make the complete conversation persistence provider
replaceable.

The target rules are:

1. A repository may contain reviewable, non-secret declarations under
   `<project>/.loushang/`.
2. Automatically generated, private or machine-specific state belongs under
   `$LOUSHANG_HOME`, which defaults to `~/.loushang`.
3. A repository declaration is data, not authority to install code, disclose
   transcripts, weaken policy or choose an arbitrary storage destination.
4. The Product admits declarations against user and OEM policy before they can
   influence an effective runtime profile.
5. A persistence plugin registers an implementation factory; it does not gain
   authority to select itself.
6. Runtime code binds a provider-neutral persistence bundle. `StorageLayout`
   remains an implementation detail of the JSONL file provider.
7. A conversation's provider selection is sealed for its lifetime and recorded
   in resumable metadata. Changing defaults affects new conversations only.
8. JSONL and SQLite providers may coexist in one continuity catalog. Migration
   is explicit, verified and never implemented as uncoordinated dual writes.

The primary target relationship is:

```text
repository declaration      private user configuration      CLI/session input
          |                            |                            |
          +----------------------------+----------------------------+
                                       |
                              configuration admission
                                       |
                           effective persistence requirements
                                       |
                  installed provider registry + Product policy
                                       |
                              provider selection (sealed)
                                       |
                          ConversationPersistenceBinding
                            |          |          |
                            |          |          +-- maintenance / health
                            |          +------------- projection index
                            +------------------------ authoritative store
```

## 2. Problem Statement

Current behavior mixes distinct classes of data in the project-local
`.loushang` namespace:

- shareable settings and resource declarations;
- conversation JSONL files;
- append coordination files and store sidecars;
- resume indexes and ModelInput-derived indexes;
- clipboard attachments;
- debug logs, traces and diagnostic archives;
- worktree and other runtime state.

Ignoring `.loushang/` in one repository reduces ordinary Git staging risk, but
it is not a product security boundary. Another repository may lack the ignore
rule, an ignored path may already be tracked, and non-Git packaging or syncing
tools need not honor `.gitignore`. Project deletion and worktree cleanup also
should not implicitly delete user conversation history.

At the same time, the current persistent transcript construction path still
assumes a directory and a concrete session file. This prevents a backend such
as SQLite from participating as a first-class authority even though the
conversation Store and Index ports are already mostly backend-neutral.

The desired result is not a universal storage abstraction that hides all
semantics. It is a typed provider boundary that preserves the exact durability,
concurrency, idempotency, query and migration contracts that every backend
must satisfy.

## 3. Goals And Non-Goals

### 3.1 Goals

- Keep project declarations easy to review, diff, merge and commit.
- Remove private and generated runtime data from the project working tree by
  default.
- Give global, project, project-local-private and session configuration
  explicit precedence and provenance.
- Enforce which configuration fields each scope may set.
- Prevent project configuration from redirecting or exfiltrating private
  transcripts without user authorization.
- Make memory, JSONL, JSONL-plus-SQLite-index and SQLite-authority providers
  selectable through one runtime contract.
- Preserve revision, operation-id, conflict, deletion, resume, branch and
  compaction correctness across providers.
- Keep continuity listing federated across legacy and current providers.
- Preserve the bounded cold-start behavior of the JSONL provider.
- Provide an incremental and reversible migration path for existing sessions.

### 3.2 Non-Goals

- Automatically installing executable plugins named by a repository.
- Storing project declarations in SQLite or another opaque binary format.
- Making all persistence technologies expose identical optional features.
- Switching a live conversation between providers.
- Silently copying or deleting legacy session data.
- Defining a general remote transcript service protocol in the first delivery.
- Treating a rebuildable projection index as transcript authority.
- Combining credentials, configuration, conversation data, cache and logs into
  one unrestricted "storage plugin."

## 4. Current Facts And Reusable Foundations

The following are Current implementation facts, not claims that the proposed
target is complete.

### 4.1 Configuration

- Coding resolves a global settings path and a project settings path.
- `SettingsManager` composes persistent `global` and `project` layers followed
  by a non-persistent `session` layer.
- `LayeredConfig` delegates physical reads and writes to the `ConfigStore`
  protocol; the default implementation is JSON-file based.
- `ConfigLayer` is still path-shaped and does not encode trust, sensitivity,
  allowed fields or separate source/sink behavior.
- The standard settings codec currently accepts `session_dir` without a
  general per-scope admission declaration.

Relevant Current source:

- `src/loushang/coding/control/settings_store.py`
- `src/loushang/harness/config/types.py`
- `src/loushang/harness/config/engine.py`
- `src/loushang/harness/config/agent/manager.py`
- `src/loushang/harness/config/agent/_settings_codec.py`

### 4.2 Conversation persistence

- `ConversationKey` is a backend-neutral namespace plus conversation ID.
- `ConversationLocator` adds a provider ID to the provider-local key.
- `ConversationStore` defines asynchronous create, load, append, delete, scan
  and paginated-scan operations with optimistic revision and operation-id
  semantics.
- `ConversationBatchStore` is an optional contiguous batch-append extension.
- `ConversationIndex` owns rebuildable, source-revision-bearing projections.
- `ConversationCatalog` can federate multiple provider bindings.
- `AgentTranscriptSessionCatalog.from_provider()` already accepts a non-file
  Store and an external Index.
- Memory and file Stores share a conformance suite.

Relevant Current source and tests:

- `src/loushang/harness/conversation/store.py`
- `src/loushang/harness/conversation/index.py`
- `src/loushang/harness/conversation/catalog.py`
- `src/loushang/harness/transcript/session_catalog.py`
- `tests/harness/conversation/test_store_conformance.py`

### 4.3 Remaining file coupling

- `AgentTranscriptLifecycleContext` requires `session_dir` and optionally
  `session_file`.
- the persistent runtime factory creates only an
  `AgentTranscriptFileLayout`-backed Store;
- the conversation namespace is currently derived from the selected session
  directory;
- the transcript runtime registry is constructed from hard-coded memory and
  file implementations;
- continue, open, fork, export and some diagnostics paths still use a file path
  as the primary identity;
- file-specific indexes and sidecars are constructed beside transcript files.

These are adapter and composition gaps. They do not require weakening the
existing Store correctness contract.

## 5. Ownership And Authority

| Concern | Authority | Notes |
| --- | --- | --- |
| Project declaration bytes | repository file | Reviewable input, not effective runtime authority |
| User configuration bytes | user configuration source | May contain private provider bindings, but credentials remain separately owned |
| Effective settings | scoped configuration runtime after admission | Records provenance and rejected fields |
| Installed provider factories | persistence provider registry | Registration does not imply selection |
| Provider selection | Product runtime plan after policy admission | One exclusive, sealed selection per conversation |
| Conversation header and records | selected `ConversationStore` | Sole content authority for that locator |
| Resume/search projection | selected or shared `ConversationIndex` | Rebuildable; never silently overrides Store authority |
| Attachments | selected `BlobStore` when present | Referenced by stable blob identity, not an assumed workspace path |
| Filesystem paths | JSONL provider adapter | Not part of the provider-neutral Product contract |
| Migration publication | migration coordinator | Source and target Stores do not independently claim completion |

No plugin manager, Index, `StorageLayout`, TUI picker or project file becomes a
peer conversation authority.

## 6. Target Data Placement

### 6.1 Private platform home

`LOUSHANG_HOME` remains the logical platform root and defaults to
`~/.loushang`. The proposed initial layout is:

```text
$LOUSHANG_HOME/
  config/
    settings.json
    models/
    projects/
      <project-id>/
        settings.local.json
  auth/
  data/
    coding/
      projects/
        <project-id>/
          project.json
          sessions/
          attachments/
  state/
    project-registry.sqlite
    coding/
      projects/
        <project-id>/
          migrations/
          store-heads/
  cache/
    coding/
      projects/
        <project-id>/
          session-index/
          model-input-v2/
  runtime/
    coding/
      projects/
        <project-id>/
          locks/
          leases/
  logs/
    debug/
    traces/
    diagnostics/
```

The semantic categories are:

- `data`: user data that must survive cache deletion;
- `state`: persistent coordination or migration state;
- `cache`: completely rebuildable projections and accelerators;
- `runtime`: process-scoped locks and leases;
- `logs`: bounded diagnostic output;
- `auth`: credentials or references to a platform credential owner;
- `config`: user-authored private configuration.

Platform-specific directory standards may later map these categories to
different operating-system roots. The logical categories and
`LOUSHANG_HOME` override remain stable.

### 6.2 Repository declaration root

The repository root contains only declarative, intentionally shareable data:

```text
<project>/.loushang/
  settings.json
  lsp.json
  prompts/
  skills/
  packages/
```

The following names are prohibited for newly generated project-local runtime
data:

```text
sessions/
clipboard/
debug/
traces/
diagnostics/
cache/
locks/
worktrees/
*.store.json
```

Legacy readers may continue to discover these names during migration. New
writes must not recreate them unless the user explicitly selected a custom
file destination.

### 6.3 Permissions

Private roots and files must not inherit permissive process defaults:

- private directories: `0700` on POSIX;
- transcripts, SQLite files, WAL/SHM files, indexes and sensitive logs: `0600`;
- temporary files: created exclusively in the destination directory and
  published atomically;
- credentials: system credential storage where available, with `auth/` only as
  an explicitly controlled fallback.

Permission repair is part of migration and `doctor`, not only new-file
creation.

## 7. Project Identity

Private data directories use an opaque `project-id`, not a sanitized absolute
workspace path.

The Project Identity Resolver maintains aliases in a private registry:

```text
canonical workspace root  -> project-id
canonical Git common dir  -> project-id
historical local alias    -> project-id
```

Rules:

1. A Git common directory is the preferred local identity input so worktrees
   of one local repository share one project bucket.
2. Each conversation still records its actual `cwd`, workspace root and
   relevant worktree facts.
3. Distinct clones remain distinct local projects by default, even when their
   normalized remote identities match.
4. A non-Git workspace uses its canonical project root.
5. Symlink and platform case normalization occur before registry lookup.
6. Raw credential-bearing remote URLs must never be used as project IDs or
   written to a manifest.
7. Moving a project adds or repairs an alias; it does not rename every stored
   conversation.

The concrete project-id allocation algorithm remains an open decision. An
opaque UUID plus a registry is preferred over a path-derived directory name
because it avoids path disclosure and makes alias repair possible.

## 8. Project-Declared Configuration

### 8.1 Layer order

The target precedence is:

```text
built-in defaults
  < global user configuration
  < repository project declaration
  < private per-project user override
  < session and CLI overrides
```

Precedence does not bypass admission. A higher layer may be rejected or
clamped when it is not authorized to set a field.

### 8.2 Layer metadata

`ConfigLayer` should evolve from only a name/path pair to an admitted source
description. The exact API may be split into `ConfigSource` and `ConfigSink`,
but must represent at least:

```text
layer id
scope
provenance
trust state
read capability
write capability
private/shareable classification
```

A file-backed project source remains appropriate. A SQLite-backed private
configuration source may be added later, but repository declarations must stay
textual and version-control friendly.

### 8.3 Field admission

Each configuration field declares its allowed scopes and security behavior.

| Field class | Project declaration | Admission behavior |
| --- | --- | --- |
| Presentation and model preference | allowed | Strict schema and compatibility validation |
| LSP and resource declarations | allowed | Paths confined to permitted project/resource roots |
| Sandbox, tool and network policy | allowed only monotonically | May tighten user/OEM ceilings, never loosen them |
| Persistence capabilities and preference | allowed as constrained input | Product chooses among installed and user-authorized providers |
| Provider connection/path/profile | private only | Rejected from repository declaration |
| Authentication and secrets | forbidden | Never decoded into normal project settings |
| Plugin/package dependency | declaration only | Does not install or activate executable code automatically |
| `session_dir` and output paths | private or CLI only | Rejected from repository declaration |

Rejected fields produce structured diagnostics with source, key and reason.
They do not make the whole valid portion of a project declaration disappear
unless the schema or policy class requires fail-closed behavior.

### 8.4 Example repository declaration

```json
{
  "schemaVersion": 1,
  "conversation": {
    "persistence": {
      "requiredCapabilities": [
        "durable",
        "transactional",
        "project-query"
      ],
      "preferredProvider": "builtin.sqlite"
    }
  },
  "permissions": {
    "network": "prompt"
  }
}
```

`preferredProvider` is not a database locator. It can only refer to an
installed, admitted provider ID. A Product or OEM may ignore the preference
when policy or compatibility requires another provider.

### 8.5 Example private user binding

```json
{
  "conversationPersistence": {
    "defaultProvider": "builtin.sqlite",
    "providers": {
      "builtin.sqlite": {
        "scope": "per-project",
        "journalMode": "WAL",
        "synchronous": "FULL"
      }
    }
  }
}
```

Paths derived from the platform home and project ID should normally be omitted
from user configuration. Explicit custom destinations remain a private or CLI
escape hatch.

### 8.6 Trust and explanation

Project configuration is treated as untrusted until admitted by the existing
or future project-trust owner. Trust does not permit secrets in the repository
and does not make arbitrary plugin installation safe.

The Product should expose an explanation command showing:

```text
effective value
winning layer
all contributing layers
rejected/clamped values
policy owner
restart or new-session requirement
```

`loushang config explain conversation.persistence` is the target user-facing
shape; exact command naming is not decided here.

## 9. Persistence Provider Architecture

### 9.1 Provider descriptor

A provider registers static metadata independently of any live session:

```python
@dataclass(frozen=True)
class PersistenceProviderDescriptor:
    provider_id: str
    implementation_version: int
    capabilities: frozenset[str]
    configuration_schema: Mapping[str, JSONValue]
    readable_formats: frozenset[str]
    writable_formats: frozenset[str]
```

Representative capability IDs include:

```text
durable
transactional
batch-append
project-query
full-text-query
attachments
portable-export
multi-process
```

Capabilities are admission facts, not an excuse for application code to branch
on implementation names.

### 9.2 Provider factory and binding

The provider factory binds one Product-approved target:

```python
class ConversationPersistenceProvider(Protocol):
    descriptor: PersistenceProviderDescriptor

    async def bind(
        self,
        context: PersistenceContext,
        configuration: Mapping[str, JSONValue],
    ) -> ConversationPersistenceBinding: ...


@dataclass
class ConversationPersistenceBinding:
    provider_id: str
    namespace: str
    store: ConversationStore[ConversationHeader, AgentTranscriptRecord]
    index: ConversationIndex[SessionSummary, SessionQuery] | None
    blobs: BlobStore | None
    maintenance: PersistenceMaintenance | None
    dispose: AsyncDisposer
```

The names are illustrative. The important boundary is that the Product binds
one coherent provider bundle instead of separately guessing compatible Store,
Index, layout and lock implementations.

### 9.3 Built-in providers

The initial provider catalog should distinguish these coherent variants:

| Provider | Authority | Projection | Intended role |
| --- | --- | --- | --- |
| `builtin.memory` | memory | memory | ephemeral sessions and tests |
| `builtin.jsonl` | JSONL | JSON index | portable default and legacy compatibility |
| `builtin.jsonl-sqlite-index` | JSONL | SQLite | lower-risk fast catalog option |
| `builtin.sqlite` | SQLite | same-database SQL projection | transactional authority option |

The hybrid provider is not a permanent requirement, but it allows index
performance to be evaluated without changing transcript authority.

### 9.4 Registration versus selection

Provider registration and provider selection are different authorities:

- a built-in or admitted plugin registers a factory;
- user/OEM policy decides which provider implementations are eligible;
- the project may declare requirements and a preference;
- the Product resolves those inputs into one selection;
- the existing runtime capability binder creates and owns the live binding.

A plugin cannot select itself merely because its code was discovered. A
project cannot name a source path and cause that code to be installed. A
provider factory is never invoked before registration, policy admission and
selection all succeed.

The `conversation.store` runtime slot should remain exclusive, session-scoped
and sealed. External provider factories may be added to its registry without
granting Extensions peer selection authority over the slot.

### 9.5 Provider-neutral lifecycle context

Replace mandatory file fields in the generic lifecycle boundary with logical
identity and optional provider hints:

```python
@dataclass(frozen=True)
class PersistenceContext:
    product_id: str
    project_id: str
    namespace: str
    conversation_id: str
    cwd: str
    persist: bool
    header: ConversationHeader
    resume_locator: ConversationLocator | None = None
```

The JSONL adapter resolves this context through its private `StorageLayout`.
The SQLite adapter resolves it to a database and logical primary key. A file
path may remain optional presentation or export metadata; it cannot remain the
canonical conversation identity.

### 9.6 Locator-first consumers

Continuity, resume, fork, export, diagnostics and deletion operate on
`ConversationLocator`.

- a file provider may project a local path for display;
- a SQLite provider may project a logical URI or no physical path;
- export requests the authoritative Store snapshot and chooses a destination;
- fork loads a source locator and creates a target locator;
- diagnostics report provider ID, namespace and redacted physical details;
- a bare session ID lookup must detect ambiguity across providers.

## 10. SQLite Authority Design

### 10.1 Default database scope

The proposed default is one authority database per project ID:

```text
$LOUSHANG_HOME/data/coding/projects/<project-id>/conversations.sqlite
```

Reasons:

- one project cannot corrupt or lock every other project's transcript
  authority;
- backup, export and deletion boundaries remain understandable;
- worktrees share a database through the common project ID;
- JSONL cold fallback and per-project continuity remain bounded;
- a small global registry/index can still implement all-project discovery.

A single global authority database may remain a provider configuration option,
but it is not the proposed default.

### 10.2 Illustrative schema

The schema below records semantics, not final column naming:

```sql
CREATE TABLE conversations (
    namespace        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    header_json      TEXT NOT NULL,
    revision         INTEGER NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    deleted_at       TEXT,
    codec_token      TEXT NOT NULL,
    PRIMARY KEY (namespace, conversation_id)
);

CREATE TABLE records (
    namespace        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    revision         INTEGER NOT NULL,
    record_id        TEXT NOT NULL,
    parent_id        TEXT,
    kind             TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    metadata_json    TEXT NOT NULL,
    PRIMARY KEY (namespace, conversation_id, revision),
    UNIQUE (namespace, conversation_id, record_id)
);

CREATE TABLE operations (
    namespace        TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    operation_id     TEXT NOT NULL,
    request_hash     TEXT NOT NULL,
    result_revision  INTEGER NOT NULL,
    committed_at     TEXT NOT NULL,
    PRIMARY KEY (namespace, conversation_id, operation_id)
);

CREATE TABLE session_projections (
    namespace          TEXT NOT NULL,
    conversation_id    TEXT NOT NULL,
    source_revision    INTEGER NOT NULL,
    cwd                TEXT NOT NULL,
    name               TEXT,
    first_prompt       TEXT,
    last_preview       TEXT,
    message_count      INTEGER NOT NULL,
    entry_count        INTEGER NOT NULL,
    updated_at         TEXT NOT NULL,
    PRIMARY KEY (namespace, conversation_id)
);
```

Payloads remain encoded through the accepted transcript codecs. SQLite is a
storage engine, not a second interpretation of Agent message semantics.

### 10.3 Append transaction

One append transaction performs:

```text
BEGIN IMMEDIATE
  -> load conversation revision and codec token
  -> compare expected revision
  -> look up operation ID
       same request hash      -> return prior receipt
       different request hash -> operation conflict
  -> validate record ID uniqueness and record codec
  -> insert record at revision + 1
  -> update authoritative conversation revision and updated time
  -> upsert source-revision-bearing session projection
  -> record operation request hash and receipt
COMMIT
```

Batch append applies the same rules to one contiguous revision range inside
one transaction.

The operation table is required even with SQLite transactions. It is how a
caller safely reconciles a commit whose success response was lost after the
database may already have committed.

### 10.4 Durability and concurrency

The initial authority profile should use:

- WAL mode where platform support is verified;
- foreign keys enabled;
- a bounded busy timeout;
- `synchronous=FULL` for the default transcript-authority profile;
- short transactions with no model, network or filesystem attachment work
  while the write lock is held;
- the SQLite backup API for live backups rather than raw copying of an open
  database;
- transactional, versioned schema migrations.

Any weaker durability profile must be explicit and visible in explanation and
diagnostics.

### 10.5 Compatibility token

Every conversation records a compatibility token covering at least:

```text
header codec identity and version
record codec identity and version
record-id semantics
projection schema version
provider schema version
```

Resume and append validate the token before trusting cached or indexed state.
An incompatible token invokes an explicit migrator or fails closed; it must not
silently reinterpret existing records.

### 10.6 Projection behavior

When the SQLite provider owns both authority and projection, the projection is
updated in the same transaction as the authoritative append. It remains
logically rebuildable and carries `source_revision`.

Resume queries use bounded, cursor-based SQL over metadata fields such as
project, name, first prompt, last preview and update time. Full transcript
parsing remains a selected-conversation operation, not a list operation.

Optional full-text indexing is a separate provider capability with explicit
retention and privacy semantics. It is not required by the base Store contract.

## 11. Catalog Federation And Resume

During migration, the continuity catalog can bind multiple providers:

```text
legacy project JSONL provider
global JSONL provider
SQLite provider
```

Catalog rules:

1. Locators, not file paths, identify items.
2. Provider IDs are stable and namespaced.
3. Duplicate conversation IDs across providers are not silently merged.
4. A migration alias is honored only after a verified migration receipt is
   published.
5. An unavailable provider produces a diagnostic placeholder; another backend
   does not guess how to open its data.
6. The current active conversation is excluded or handled through its provider
   live projection without forcing an authority rebuild.
7. JSONL cold-start discovery remains bounded; SQLite catalog queries remain
   paginated.

The provider selected for a new conversation comes from current effective
configuration. The provider used to resume an existing conversation comes from
that conversation's stored locator/runtime profile, not the new default.

## 12. Migration And Compatibility

### 12.1 Dual read, single write

The transition uses dual discovery but one authority per conversation:

- new sessions write only to the selected provider;
- legacy JSONL sessions remain readable in place;
- catalogs show both;
- no normal turn is synchronously dual-written to JSONL and SQLite.

Dual writing creates two possible authorities after partial failure and is not
an acceptable migration mechanism.

### 12.2 Explicit migration transaction

A JSONL-to-SQLite migration performs:

```text
discover source locator
  -> acquire source migration lease
  -> load and fully validate the source snapshot
  -> create target in an unpublished migration namespace
  -> append/import all records with stable identities
  -> reload target and compare header, records, revision and compatibility
  -> publish migration receipt and locator alias atomically
  -> leave source retained and marked migrated
```

Deletion of retained sources is a separate user-approved cleanup operation.
Retrying a partially completed migration is idempotent through a migration ID
and source fingerprint.

### 12.3 Legacy path behavior

For a compatibility window:

- continuity discovers `<project>/.loushang/sessions` read-only;
- explicit legacy `--session-dir` remains supported;
- new default writes use `$LOUSHANG_HOME`;
- `doctor` reports legacy paths, permissions, duplicates and migration state;
- no startup path automatically moves or deletes user data.

### 12.4 Export and portability

All authority providers must support a canonical conversation export through
the transcript codecs. A SQLite user can export JSONL without exposing the
database implementation, and a JSONL user can import into SQLite through the
same validated representation.

Provider-specific backups may exist in addition to, not instead of, canonical
export.

## 13. Failure And Recovery Semantics

Every persistent provider must define and test:

- create idempotency and existing-key behavior;
- optimistic revision conflicts;
- record-ID uniqueness;
- operation-ID same-request replay and different-request rejection;
- unknown commit outcome reconciliation;
- ordered contiguous batch append;
- deletion and tombstone ordering;
- provider and codec compatibility checks;
- paginated scan stability;
- process crash before, during and after commit;
- concurrent writers in one process and across processes;
- corrupted authority versus corrupted rebuildable projection;
- cancellation-safe bind and dispose;
- schema migration interruption and retry;
- unavailable or removed provider behavior.

The existing neutral Store conformance suite is the minimum gate. SQLite
requires additional transaction, WAL, process-crash and migration tests; it
does not receive a reduced contract because its implementation is different.

## 14. Security Model

### 14.1 Repository declarations

- parsed as untrusted data;
- strict schema and bounded size;
- no credentials or secret interpolation;
- no arbitrary provider path, DSN or plugin source;
- paths normalized and confined to declared resource roots where applicable;
- executable dependencies require separate installation and trust decisions;
- policy settings can only tighten higher-authority ceilings.

### 14.2 Provider plugins

- installed and admitted through an explicit user/OEM-controlled lifecycle;
- registered under stable owner-qualified provider IDs;
- configuration validated before factory invocation;
- connection secrets resolved from private configuration or credential owners;
- physical details redacted from ordinary diagnostics;
- remote/networked providers require a separate capability and explicit policy;
- unloading a provider cannot discard or reinterpret its sessions.

### 14.3 Private state

- private filesystem permissions are enforced explicitly;
- logs and traces have retention and size bounds;
- diagnostic export is explicit and redacted;
- project manifests may store local paths but never raw credential-bearing
  remote URLs;
- cache deletion cannot delete authoritative transcripts or attachments.

## 15. Performance Model

### 15.1 JSONL provider

- steady resume listing uses its rebuildable projection index;
- missing/stale indexes use stat plus bounded head/tail reads;
- only a selected conversation receives a complete authoritative parse;
- current-session writes update summaries without invalidating every catalog
  entry;
- ModelInput indexes remain provider-owned accelerators.

### 15.2 SQLite provider

- append cost is one short transaction and does not scale with prior record
  count;
- list/search cost is driven by indexes, cursor and page size;
- projections update in the authority transaction;
- selected resume still loads the records required to reconstruct the active
  branch and verify codec semantics;
- large payload retrieval can later become paginated or checkpoint-aware
  without changing Store identity.

### 15.3 Cross-provider constraints

- all-project listing must not open every project authority database eagerly;
- a small private project registry or rebuildable global summary catalog routes
  the initial query;
- provider discovery and health checks are bounded;
- unavailable providers do not block healthy providers from listing;
- background index repair is cancellable and has an I/O budget.

## 16. Proposed Delivery Sequence

### Phase A — configuration safety

1. Introduce field-level scope and sensitivity metadata.
2. Reject project-level `session_dir`, credentials and provider connection
   details.
3. Add the private per-project user override layer.
4. Add configuration provenance and explanation tests.
5. Define a project trust/admission input without auto-installing code.

Exit gate: opening an untrusted repository cannot redirect transcript output,
weaken policy or execute a newly declared plugin.

### Phase B — private default layout

1. Add the project identity resolver and private registry.
2. Resolve new default session targets below `$LOUSHANG_HOME`.
3. enforce `0700`/`0600` permissions;
4. retain explicit session-directory overrides;
5. add legacy dual discovery and `doctor` reporting.

Exit gate: a normal new conversation, attachment, lock, index and diagnostic
flow creates no generated file in the repository working tree.

### Phase C — provider-neutral lifecycle

1. Introduce `PersistenceContext` and `ConversationPersistenceBinding`.
2. Make transcript lifecycle locator-first.
3. Move `StorageLayout` construction fully inside the JSONL provider.
4. Inject external provider implementations into the runtime registry.
5. Convert continue, resume, fork, export and delete to locator-first APIs.

Exit gate: an in-memory non-file provider completes the full Product lifecycle
without manufacturing fake paths.

### Phase D — SQLite projection option

1. Implement a SQLite `ConversationIndex`.
2. Compose it with JSONL authority as
   `builtin.jsonl-sqlite-index`.
3. Validate cold rebuild, write-through, pagination and crash recovery.

Exit gate: index deletion or corruption never damages JSONL authority and the
bounded fallback remains available.

### Phase E — SQLite authority provider

1. Implement `SqliteConversationStore` and optional batch append.
2. Add it to the full neutral Store conformance matrix.
3. Add same-transaction session projection writes.
4. Add WAL/process-crash/schema-migration tests.
5. Bind it as `builtin.sqlite` through the provider registry.

Exit gate: create, continuous append, exit, restart, resume, branch, conflict,
unknown outcome and delete semantics match the neutral contract.

### Phase F — migration and plugin publication

1. Implement verified JSONL-to-SQLite migration receipts.
2. Federate legacy, JSONL-home and SQLite catalogs.
3. Add canonical import/export.
4. Expose provider descriptors and factories through the admitted plugin
   lifecycle.
5. Add user-facing provider/config/storage explanation and health commands.

Exit gate: disabling a provider is diagnosable and recoverable, and migration
never leaves two silently writable authorities.

## 17. Verification Matrix

| Area | Required evidence |
| --- | --- |
| Configuration precedence | deterministic layer composition and provenance tests |
| Field admission | project forbidden-field, monotonic-policy and trust tests |
| Repository cleanliness | end-to-end assertion that normal runtime creates no project state |
| Project identity | Git worktree grouping, clone separation, symlink/case and non-Git tests |
| Permissions | POSIX directory/file/WAL/SHM permission tests where supported |
| Store semantics | shared memory/file/SQLite conformance suite |
| SQLite durability | multi-process conflict, kill/restart, unknown commit and migration tests |
| Catalog | provider federation, ambiguity, pagination and unavailable-provider tests |
| Resume | large continuous conversation, exit, restart and provider-stable resume |
| Migration | interrupt at every publication boundary, retry and source-retention tests |
| Security | untrusted repository cannot install code, redirect output or disclose secrets |
| Performance | 1,000 logical large sessions plus one valid large selected transcript |
| Architecture | import and ownership gates preventing Product/TUI dependency on file adapters |

## 18. Acceptance Criteria

The proposal is ready for normative adoption only when reviewers agree that:

1. repository declarations and private user state have distinct owners and
   directories;
2. every sensitive setting has an explicit allowed-scope rule;
3. project declarations cannot self-authorize plugin code or storage egress;
4. `ConversationLocator` is the primary identity outside provider adapters;
5. `StorageLayout` is private to file-backed implementations;
6. provider registration and provider selection remain separate;
7. provider selection is sealed and resumable;
8. SQLite passes the same Store correctness contract as JSONL and memory;
9. projection authority and transcript authority remain distinct even when
   stored in one SQLite transaction;
10. migration has one publication authority, idempotent retry and retained
    source data;
11. legacy sessions stay discoverable throughout the compatibility window;
12. performance gates cover both cold listing and selected full resume.

## 19. Rejected Alternatives

### 19.1 Keep all state in the project and rely on `.gitignore`

Rejected because ignore rules are repository-specific and do not protect
non-Git packaging, already tracked files, project deletion or permissive file
permissions.

### 19.2 Move every `.loushang` file into the user home

Rejected because shareable project declarations, prompts, skills and package
references should remain reviewable repository artifacts.

### 19.3 Make `StorageLayout` the universal backend API

Rejected because database and remote providers do not have meaningful file
layout semantics. It would leak one provider's physical model into all
consumers.

### 19.4 Let a plugin register and select itself

Rejected because implementation availability is not selection authority. It
would let discovered code capture private transcript writes.

### 19.5 Let project configuration contain the SQLite path or remote DSN

Rejected because a repository must not choose a private data destination or
network egress endpoint. Such bindings are user/OEM-private configuration.

### 19.6 Switch existing conversations when the default changes

Rejected because a provider is part of a conversation's durable identity and
compatibility contract. Existing data requires explicit migration.

### 19.7 Dual-write every turn during migration

Rejected because partial failure creates two competing authorities and makes
unknown commit outcomes substantially harder to reconcile.

### 19.8 Put repository declarations in SQLite

Rejected because it removes useful Git diff, merge, review, blame and manual
editing properties without providing a meaningful security benefit.

## 20. Open Decisions

1. Should project IDs be random UUIDs in a private registry or derived from a
   stable local identity with an alias table?
2. Is one SQLite authority database per project the accepted default, or should
   a global database be the first implementation?
3. Does the first project declaration format remain JSON, or is a versioned
   TOML manifest introduced separately from current settings?
4. Which existing settings are project-allowed, private-only or monotonic?
5. Which owner admits project trust, and how is that decision explained?
6. Should the hybrid JSONL-plus-SQLite-index provider ship before SQLite
   authority?
7. What is the minimum public plugin registration surface for persistence
   providers?
8. Are remote providers in scope for the initial provider contract or
   explicitly deferred behind a later network/storage capability?
9. Which attachment operations belong in the first `BlobStore` port?
10. What retention policy applies to legacy sources after verified migration?
11. Is at-rest encryption delegated to platform/filesystem facilities, or does
    a future encrypted provider capability need a standard contract?

## 21. Expected Architecture Follow-Up

If accepted, this cross-scope proposal should be decomposed into owner-specific
normative changes rather than implemented directly from this draft:

- a cross-scope decision for repository declarations versus private state;
- a Harness conversation decision for persistence-provider authority;
- Harness configuration requirements for scope admission and provenance;
- Harness transcript specification changes for locator-first lifecycle;
- Coding Product changes for project identity, default provider selection,
  continuity and diagnostics;
- resource/plugin security changes for provider factory admission;
- executable architecture gates and traceability updates in every affected
  owner.

Until those decisions are adopted, Current source and tests remain the
authority.
