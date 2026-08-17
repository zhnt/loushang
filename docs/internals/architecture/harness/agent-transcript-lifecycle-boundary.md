# Harness Agent Transcript Lifecycle Boundary

## Status

Status: implementation complete for integration into `lane/harness` on
`harness/agent-transcript-lifecycle`.

## Purpose

`loushang.harness.transcript.lifecycle` owns the reusable lifecycle
assembly for one optional Agent transcript. `AgentTranscriptLifecycle` creates,
restores, detaches, forks, and disposes an `AgentTranscriptSessionStore` without
knowing a Product's profile-selection, root-selection, or resume policy.

The neutral `harness.conversation` and `harness.storage` cores remain
independent of Agent and AI. This optional Agent/AI profile may use current
Conversation JSONL transcript helpers, but does not import Coding or another Product.

## Binding Contract

A Product first decides its header metadata, `cwd`, persistence mode, selected
`ConversationStore`, and `AgentTranscriptProfile`. It supplies those choices
through three small values:

- `AgentTranscriptLifecycleContext` carries the selected location, header,
  persistence mode, and optional Native file path. Persistent non-file stores
  do not provide a file path.
- `AgentTranscriptRuntimeBinding` supplies one sealed
  `ConversationStore[ConversationHeader, AgentTranscriptRecord]`, its key,
  transcript profile, opaque Product binding, and async disposer.
- `AgentTranscriptLifecycleSession` returns the bound transcript, standard
  label indexes, and the Product binding for the duration of that session.

The runtime binder is the only Product callback. It may bind the standard
Native file provider, Memory, SQL, Redis, or another conforming provider. The
lifecycle neither selects nor implements those providers, and it never changes
the selected binding after construction.

`default_jsonl_session_file()` is only the Conversation JSONL filename helper.
Coding calls it after selecting its Native file policy; a database or Redis
Product does not call it and may use a persistent context with no file path.

## Lifecycle Semantics

`create()` with retained initial records persists them through the bound store.
A persistent empty create is provisional: it binds the runtime and builds the
in-memory repository without calling `ConversationStore.create()`.
Administrative records may be staged in that repository. The first user Agent
message or application message atomically calls Store create with the header,
all staged records, and the materializing message. Disposing a still
provisional transcript only releases its binding, so no empty authority or
index row exists to delete.

`restore()` loads an already materialized persistent store, while a
non-persistent restore snapshots a current Conversation JSONL source into the
selected detached store before any new record can be written. Detached restore
therefore never mutates its source file.

`fork()` copies only the selected ancestor path to a newly bound transcript.
The new transcript has Product-selected header metadata and storage identity;
the copied records retain their record identities. `delete_agent_transcript_jsonl()`
owns only Conversation JSONL file deletion and rejects a path that is the active
transcript.

If create or restore fails after a runtime binding has been acquired, Harness
releases that binding before propagating the error. A returned lifecycle session
releases its binding exactly once. Commit, queue, retry, compaction, and Product
event presentation remain outside this lifecycle boundary.

## Product Boundary

Coding retains runtime and capability profile resolution, header snapshot
validation, session-root and cwd policy, persist/default decisions,
Product-specific metadata and index fields, CLI/TUI behavior, diagnostics, and
the compatibility `SessionManager` facade. It supplies the binding through its
`ProductRuntimePlan`; it does not recreate lifecycle algorithms, Native
detached-copy behavior, branch-path fork mechanics, or active-file deletion
protection.

Other Products may supply different headers, filename policy, stores, and
transcript profiles. A Product-specific semantic record remains in that
Product's profile or projection rather than expanding this common lifecycle.

## Verification

- Harness tests cover persistent create/restore, detached restore without
  source mutation, selected-path fork, failure cleanup, exact-once disposal,
  and active-file deletion protection.
- Coding session-manager tests exercise the same lifecycle through the Coding
  runtime binding and compatibility facade.
- Import-boundary tests require `SessionManager` to use
  `AgentTranscriptLifecycle` and prohibit lifecycle imports from Coding.
