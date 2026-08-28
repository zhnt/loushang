# Session Discovery and Continuity

Phase 5A turns the machine-local storage substrate into a visible Product
experience without creating a second Session store. Transcript JSONL and
Session Blob authorities remain the source of truth. Discovery is a bounded,
read-only projection; Continuity is the existing Product/OEM provider seam;
and the transcript lifecycle remains the only restore/import transaction
owner.

## Authority and origins

The default Coding Product declares one canonical source and two compatibility
sources:

| source | origin | mode | meaning |
| --- | --- | --- | --- |
| `sessions.global` | `global` | canonical | `$LOUSHANG_HOME/data/sessions` writable authority |
| `sessions.cwd_compatibility` | `cwd` | compatibility | `<cwd>/.loushang/sessions` read-only discovery |
| `sessions.home_compatibility` | `home` | compatibility | `$LOUSHANG_HOME/sessions` read-only discovery |

Additional admitted sources use the same `SessionDiscoverySource` contract and
receive a stable `source_id`, origin, mode, and priority. Visibility never
grants write authority. Resuming a compatibility transcript uses the existing
copy-first import operation: Blob objects are published first, the canonical
transcript commits second, the source remains unchanged, and no destination is
overwritten.

## Read model

Each selected summary carries `SessionDiscoveryMetadata`:

- `SessionLocator` identifies the exact source, Conversation ID, transcript
  path, and observed revision;
- `origin` and `mode` explain why the Session is visible;
- `health` is one of `available`, `legacy`, `needs_attention`, or `conflict`;
- `aliases` are byte-identical copies of the selected authority;
- `conflicts` are same-ID candidates whose exact equality cannot be proven.

The CLI JSON projection preserves this structure. TSV remains the stable
five-column compatibility projection; provenance is available only in JSON so
its column count never changes according to the selected row.

## Merge and selection rules

Candidates are grouped by Conversation ID. Canonical mode wins selection;
within one mode the declared source priority and stable source identity decide
order. Duplicate files are compared through no-follow descriptors with a
strict aggregate comparison bound. Exact copies become aliases. A changed,
unsafe, oversized, unreadable, or racing candidate is not guessed equal and
therefore becomes a conflict.

When only compatibility sources disagree and no canonical Session exists, the
conflict remains visible for diagnosis but is not resumable or deletable by
opaque ID. CLI resolution and the Continuity Provider both reject it. Once a
canonical Session exists, it remains authoritative: a changed retained
compatibility copy is reported as `needs_attention` with conflict provenance,
but cannot veto canonical resume. An explicit existing path remains an
intentional exact-source import request and does not rely on ambiguous
discovery lookup.

Compatibility roots and transcript candidates are not followed through
symbolic links or Windows reparse points. Index mutation remains restricted to
the canonical authority; compatibility indexes are read only.

## Product projection

The existing Coding Continuity Provider maps discovery health into the common
TUI picker:

- canonical healthy Sessions retain the compact existing presentation;
- compatibility Sessions show their origin and `Legacy` state;
- unresolved compatibility conflicts remain visible with a `Conflict` status;
- canonical Sessions with drifting compatibility copies show `Needs attention`;
- selected previews report storage origin, compatible/conflicting copies, and
  durable asset health.

Asset inspection is intentionally selection-scoped and strictly bounded. The
list path never loads image bytes. Preview accepts only a bounded transcript,
caps reference count, and validates Session Blob ownership and object metadata
without hashing image contents. It reports `partial` when objects are present,
because full content integrity remains part of the separately bounded model-call
hydration path. Oversized or racing previews report `unavailable` instead of
blocking the picker.

Continuity summaries advertise per-target actions. Compatibility targets expose
activation only; canonical targets may also expose deletion. Canonical deletion
publishes the existing Conversation identity tombstone before unlinking the
transcript. Discovery consults that tombstone so retained compatibility copies
cannot silently resurrect an explicitly deleted Session.

## Plugin boundary

`SessionDiscoverySource` is deliberately a machine-local filesystem value, not
a provider-neutral plugin identity or an ambient filesystem capability. The 5A
runtime admits its roots explicitly and applies the same bounded, no-follow
read policy to each one. Remote, database-backed, or plugin-owned Sessions must
enter through `ConversationProviderBinding` and a Continuity Provider, returning
portable summaries and opaque targets instead of fabricating local paths.
Plugins may later contribute provider bindings, metadata, health checks, and
presentation. Harness continues to own:

- canonical authority selection;
- identity and revision validation;
- admission budgets and no-follow policy;
- copy-first commit, cancellation, and recovery;
- deletion tombstones and positive reclamation evidence.

Mutation plugins may propose a typed plan in a later phase. They must not
receive an unrestricted path deletion or transcript-write side door.

Phase 5B implements the portable, read-only owner foundation: bounded
query/preview records, exact activation bytes, the Product bridge into the
canonical transcript lifecycle, Provider-aware filtering, and stale-result
invalidation. It deliberately does not construct or register installed Plugin
Providers. That later path must consume finalized Plugin selection, owner
admission, durable activation approval, verified Component Host construction,
and a revocation-safe authority lease rather than accepting raw callables or
self-minted trust facts. The normative boundary is
[Portable Continuity Provider Foundation](plugin/continuity-provider-phase5b-contract.md).
Plugin execution and all mutation contributions remain outside this phase.
