# Harness Runtime Data Foundations

## Status

Status: implementation complete for integration into `lane/harness` on the
semantic branch `harness/runtime-data-foundations`.

This capability wave moves reusable runtime-data mechanics out of Coding in
three substantial batches: transcript repositories and projection indexes,
layered configuration, and context salience/summary profiles. It follows the
dependency-first migration rule and replaces duplicate Product mechanics in
the same branch as each adapter.

This foundation wave did not define an Agent transcript profile, configuration
schema, or summarization policy. Harness owns the engines; Products own domain
payloads, defaults, policy, and presentation passed into those engines. The
follow-on [Agent Transcript Profile](agent-transcript-profile-boundary.md) now
defines an optional common schema for Agent-backed Products without changing
the neutrality of these foundations.

## Ownership Decision

| Concern | Harness ownership | Product or subsystem ownership |
| --- | --- | --- |
| Transcript state | Parent-linked in-memory repository, active leaf, validation, tree, fork, and Store contracts/providers | Header and record schemas, codec, lifecycle, naming, provider binding, retention, query, and UI |
| Projection index | Revision-aware rebuildable index contract plus Memory/JSON adapters, tombstones, corrupt-file preservation, and atomic generations | Projection schema, Store provider set, query semantics, index selection, and refresh policy |
| Configuration | Ordered layers, patch merge, persistence adapter, composition codec, reload preservation, issues, snapshots, and subscriptions | Fields, validation, defaults, layer names/paths, credentials, auth/model semantics, CLI, and UI |
| Salience | Explainable signals, structural weighted scorer, stable ranking, and a custom scorer protocol | Content interpretation, weights, pinning, grouping, selection threshold, and compaction policy |
| Summary profile | Profile and section records, tagged prompt composition, mode selection, prompt override, and structural validation | System/user prompt text, serialized content, required sections, placeholder rules, model call, and artifact projection |

Harness implementations in this foundation package must not import Coding,
Work, Method, TUI, AI, Agent runtime, providers, or any Product package.
Payloads remain generic or opaque. In particular, the generic journal and
conversation foundations never serialize `AgentMessage`, resolve a model or
API key, or write a Product summary record. Only the separate optional Agent
transcript profile serializes Agent messages through its exact codec allowlist.

## Transcript Repository

The follow-on persistence consolidation replaces this historical placement
with `loushang.harness.conversation.ConversationRepository[H, R]`, a pure
in-memory repository composed with conversation-owned `BranchGraph`. A Product
supplies record-id and parent-id accessors. The repository provides:

- candidate-state validation before a Store commit;
- active-leaf selection and reset;
- record lookup, roots, children, and root-to-leaf paths;
- pure in-memory fork and fold operations;
- compatible-graph diagnostics without a physical source locator.

Durable create/load/append/delete and revisions now belong only to
`ConversationStore`; JSONL composition is isolated in its file adapter.

Coding's `SessionManager` is still the Product facade, now asynchronous for
create/load/mutation/delete. It keeps labels, summary/query relevance, recovery
wording, file naming, retention, public APIs, and backend composition. It
delegates open transcript state, graph traversal, revision-checked append,
replay, context rebuild, and fork materialization through
`AgentTranscriptUnitOfWork` over an injected `ConversationStore`; catalog and
index projection remain separate Product concerns.

The follow-on Conversation Runtime Core now wraps this lower-level repository
with `loushang.harness.conversation.ConversationRepository`, catalog/query,
checkpoint replay, LCA/branch delta, and opaque-record compaction planning. New
Product adapters should depend on the conversation owner rather than importing
the journal package for repository or branch semantics; see
[Conversation Runtime Core Boundary](conversation-runtime-core-boundary.md).

This foundation introduced no concrete message schema. Stable base AI message
codecs remain in `loushang.ai`, extension-message codec composition remains in
`loushang.agent`, and the optional Agent transcript profile composes those
stable codecs into the neutral conversation envelope. Each Product owns codecs
only for its domain-specific transcript records.

## Projection Index

`JsonConversationIndex[P, Q]` now owns the revision-aware, rebuildable
projection mechanics proven by Coding's session index:

- a caller-selected positive version and item key;
- a typed functional or object codec;
- atomic JSON replacement and deterministic ordering;
- optional per-projection freshness checks;
- stale detection for version, shape, decoding, and source-freshness failures;
- corrupt JSON preservation with a unique suffix;
- load-or-refresh using a Product-owned rebuild callback.

Coding retains `SessionSummary`, its JSON field names, session-file freshness
check, directory scan, filtering, relevance ranking, and `.session-index.json`
placement. Generic projection checkpoints at journal offsets are not part of
this wave; an index is independently rebuildable metadata, not source history.

## Layered Configuration

`loushang.harness.config.LayeredConfig[T]` composes a Product `ConfigCodec[T]`,
ordered `ConfigLayer` values, and a `ConfigStore`. It owns:

- deterministic low-to-high layer precedence;
- recursive mapping patch merge with defensive copies;
- update and replace operations;
- optional per-layer persistence;
- reload that preserves the last valid layer when storage fails;
- codec and storage issues with layer provenance;
- immutable-value snapshots, patch snapshots, and subscriptions.

`JsonConfigStore` provides object-only JSON loading and atomic replacement.
It does not know standard Product paths.

Coding keeps `ControlConfig`, all nested setting records, field normalization,
removed-setting compatibility, defaults, global/project/session path choices,
provider/model/auth interpretation, and command/UI projection. Its
`SettingsManager` now adapts those rules through a Coding-owned codec over the
Harness engine.

Harness configuration must not become a credential store or a service locator.
Harness never stores credentials.
Model registry and auth resolution remain outside this wave and should move
only to their correct AI owner or remain Product composition policy.

## Context Salience And Summary Profiles

`ContextSalienceRanker` evaluates Product-supplied `SalienceSignal` values and
returns a stable ranked view. `WeightedSalienceScorer` is a usable structural
default over item recency, priority, kind, and numeric metadata, but all weights
are supplied by the Product. Pinned items sort first. Ranking does not mutate,
drop, pack, or persist context and therefore cannot violate group atomicity by
itself.

Products may supply a scorer that reads domain content. For example, Research
may score verified citations, PPT may score slide dependencies, and Cowork may
score unresolved decisions. Those meanings do not enter Harness.

`SummaryProfile` and `build_summary_prompt` provide reusable summary mechanics:

- Product-defined modes and exact prompt text;
- tagged serialized-content and previous-summary blocks;
- append or replace custom instructions;
- Product-defined required sections and placeholder markers;
- optional Product block tags ignored during structural validation;
- profile-declared `SummaryResourceOperationTag` mappings, including the standard
  `read-files` / `modified-files` tags where appropriate.

Harness also owns profile-driven summary fixture evaluation and the neutral
`SummaryResourceOperations` evidence model. Each fixture case resolves a
Product-supplied profile independently; the evaluator parses only tags declared
by that profile and never imports a Product package. Coding keeps its
compaction, update, turn-prefix, and branch prompt text in
`coding.compaction.profiles`, its message-to-text serialization, production
summary decoration, model completion, retry, Product role mappings,
tool-result interpretation, and summary artifact semantics. Harness owns the
generic split-turn/non-cut-role planning and summary evaluation mechanisms.

## Compatibility And Failure Semantics

- A transcript append validates the candidate graph and writes the journal
  before publishing new in-memory state.
- A detached transcript load never appends to its source journal.
- Invalid configuration reloads preserve the previous layer and report an
  issue rather than silently resetting Product state.
- Persistence failure leaves the in-memory configuration patch unchanged.
- Invalid or stale indexes rebuild from Product source data; malformed JSON is
  preserved for diagnosis.
- Summary prompt composition preserves Coding's existing tag and whitespace
  layout.
- Summary validation preserves Coding's missing, empty, and placeholder section
  results and ignores Product-declared metadata blocks.

## Validation

The wave is complete only when all of the following pass:

- product-neutral Harness transcript, index, config, salience, and summary
  tests, including non-Coding Research-shaped fixtures;
- Coding session-file, session-manager, settings, compaction, and summary
  compatibility tests;
- architecture import and ownership assertions;
- Ruff and Harness-package mypy checks;
- the repository's full non-live test suite.

No type-only, protocol-only, or duplicate parallel implementation counts as a
completed batch. Lack of a second production consumer is not a blocking gate:
clear product neutrality, a usable engine, an independent fixture, a real
Coding cutover, and duplicate removal are sufficient evidence.

## Explicit Non-Goals

This wave does not:

- move Coding transcript records or custom message codecs into Harness in this
  completed foundation wave; that historical non-goal is superseded by the
  separate Agent Transcript Profile wave;
- move AI base-message codecs, model registry, or auth resolution into Harness;
- move Product setting fields, defaults, credential policy, or presentation;
- move Product system prompts, compaction prompt text, model calls, or content
  salience weights into Harness;
- define artifact lifecycle or Product artifact meaning;
- add journal vacuum, retention, encryption, replication, remote storage,
  vector memory, or database behavior;
- move Product query, export, naming, command, controller, or UI behavior.
