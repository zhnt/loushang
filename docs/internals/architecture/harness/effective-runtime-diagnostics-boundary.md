# Effective Runtime Diagnostics Boundary

Status: implemented PR9 boundary. The effective-runtime projection, explain,
JSON, diff, and clock-skew contracts are enforced by source and tests.

## Purpose

PR9 makes an assembled Harness runtime explainable without creating another
selection authority or graph projector. `RuntimeCapabilityGraphProjector`
remains the only graph projector and composes references to four independently
committed clocks:

1. the current Runtime Profile fingerprint;
2. the committed Mount Graph id, generation, and assembly fingerprint;
3. the registration inventory revision and referenced Mount generation; and
4. an optional Model Input snapshot and the three runtime clocks it observed.

`EffectiveRuntimeView` is an immutable JSON-only read model. It is not an
atomic snapshot and is not persisted as a fifth authority.

## Value Contract

The view contains:

- explicit Profile, Mount, registration, and optional Model Input clock values;
- redacted Profile slot/selection references that exclude selection config;
- committed Mount nodes and registration inventory entries, which already
  exclude live Provider values and callbacks;
- deterministic clock-skew labels; and
- a canonical composition fingerprint over those references.

The optional Model Input reference carries only its snapshot id, schema
version, Product/runtime identity, Profile fingerprint, Mount generation, and
registration revision. Provider payloads and transcript components remain in
the transcript authority.

The registration read model reuses the graph inventory plus current
owner-scoped Tool and Extension-generation inventories. Extension registrations
retained after retryable retirement failure remain visible as
`pending_retirement` until exact cleanup succeeds. The read model deduplicates
exact registration ids and computes one revision without changing any
registration lifecycle owner. A private-facet refresh may therefore advance
only the registration clock while the Mount generation remains unchanged.

## Skew Semantics

Differences between authority clocks are facts, not automatically failures.
The Projector labels these comparisons independently:

- current Profile versus the Profile used by the Mount Graph;
- registration inventory versus the Mount Graph;
- Model Input versus the current Profile;
- Model Input runtime provenance versus the current Mount runtime;
- Model Input versus the current Mount generation; and
- Model Input versus the current registration revision.

A turn-level Profile refresh beside an unchanged Mount generation, or a
historical Model Input beside a newer runtime, is legitimate clock skew. The
view never synthesizes a replacement selection to make references agree.

## Explain And Diff

The existing capability explanation remains compatible. Additive explanation
operations cover Runtime Profile slots and exact registration ids. Every
explanation includes the clock references under which it was produced.

`diff()` compares two effective views from the same Product/runtime and reports
Profile-slot, Capability, registration, generation, revision, and Model Input
changes separately. It includes both clock sets and both skew sets. A change in
one clock must not be represented as a change in another clock.

JSON is the canonical machine-readable representation. Product adapters own
CLI, RPC, TUI, and Web presentation. DOT output and multi-Product aggregation
remain deferred until operational evidence justifies them.

## Safety And Ownership

- no view or explanation contains credentials, raw environment values,
  selection config, callbacks, live Provider objects, or arbitrary object
  representations;
- projection is read-only and does not bind, refresh, dispose, or select
  capabilities;
- missing Profile or Model Input facts fail closed rather than being guessed;
- Model Input reconstruction stays owned by the transcript boundary; and
- Product adapters may expose the neutral values but must not fork their
  semantics.

## Acceptance

PR9 is accepted when:

- repeated projection of the same committed inputs produces identical JSON and
  composition fingerprints;
- capability, Profile-slot, and registration explanations identify their
  selected Provider/implementation or exact owner;
- diffs distinguish additions, removals, replacements, Mount generation,
  registration revision, and Model Input reference changes;
- skew output names every compared clock and preserves unchanged clocks;
- historical Model Input references remain explainable after later Profile or
  runtime changes;
- projection contains no opaque or sensitive values; and
- architecture gates still prove there is only one graph projector and no
  Product presentation dependency in Harness capabilities.
