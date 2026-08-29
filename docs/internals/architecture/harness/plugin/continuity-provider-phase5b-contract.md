# Portable Continuity Provider Foundation (Phase 5B)

## Status and authority

- Contract: Phase 5B implemented owner-side foundation for portable,
  read-only Continuity Providers.
- Owner: `loushang.harness.continuity` owns portable query/preview records,
  federation budgets, activation payloads, and Provider lifecycle composition.
- Product owner: the Product supplies the bridge into its canonical Session
  lifecycle and remains the sole authority for Runtime Profile assembly.
- Plugin lifecycle: not implemented by this phase. Installed Plugin
  declaration, selection, approval, verified symbol loading, Component Host
  construction, and exact authority leases belong to Phase 5C and the existing
  Plugin architecture.

This contract refines
[Session Discovery and Continuity](../session-discovery-continuity.md) and the
[Plugin Architecture](architecture.md). It does not replace either authority.

## First-principles split

Discovery, activation, Plugin execution, and mutation are different
authorities:

```text
portable Provider records and prepared bytes
                    |
                    v
Harness Continuity validation and federation
                    |
                    v
Product activation bridge
    canonical copy-first Session lifecycle

future Plugin declaration / approval / execution
                    |
                    v
existing Plugin selection and Component Host path (Phase 5C)
```

An external target is opaque and Provider-qualified. Visibility grants no
local path authority. Phase 5B adds no Plugin grant minting, factory loading,
instance reader, trust reader, package discovery, or Runtime Profile Extension
layer. `continuity.provider_packs` therefore remains Product/OEM-only.

## Portable owner contracts

`ContinuityImportProvider` is a read-only shape containing query, preview, and
portable import preparation. `ContinuityImportProviderPack` bounds the number
of already constructed Provider values. These are owner-side payload
contracts, not a public Plugin authoring or registration SDK.

`ContinuityActivationPayload` supports the existing portable transcript media
types:

- Conversation JSONL; and
- `.loushang.zip` transcript-and-Blob bundles.

The payload requires exact built-in bytes, an exact SHA-256 digest, an optional
bounded source cwd suggestion, and a hard aggregate size ceiling. Accepting
bytes subclasses would make the size check overrideable and is prohibited. A
Product bridge never trusts the source cwd directly; Coding uses only its own
explicitly configured fallback.

The Coding Product bridge writes the payload to a private temporary file, asks
the existing transcript lifecycle to prepare a copy-first import, and removes
the temporary source before returning the activation lease. Cancellation joins
an in-flight owned write before identity-checked cleanup, so the worker cannot
leave an unreachable transcript behind. On POSIX, creation and removal stay
anchored to a no-follow directory descriptor; path ancestors must not be
non-sticky shared-writable. The bridge wraps the Product candidate in the full
`PreparedActivationLease` contract, preserving the external target and
declaring Coding's in-place disposition. Consume remains the existing canonical
Session transition; a failed or cancelled consume cancellation-atomically
aborts the underlying Product candidate exactly once. Abort remains the
existing unpublished-candidate rollback. Platforms without secure
directory-relative no-follow creation fail closed in Phase 5B; a Windows
reparse-safe handle bridge is a separate implementation requirement, not a
path-based fallback.

## Composition and presentation

Product/OEM Runtime Profile provenance remains the identity used by signed Hub
cursors and stable observations. The standard slot is Process-scoped and
sealed. Arbitrary Extension input is rejected at the slot and Coding Product
boundaries.

Continuity descriptors advertise supported actions. The Hub filters Providers
by required action, rejects pages larger than the requested limit, and rejects
summary actions outside the Provider declaration.

The common Resume surface can filter by Provider and Domain. Filter changes
reserve and invalidate the prior result generation synchronously, so an old
Provider that suppresses task cancellation still cannot republish its target
while the next query is pending. Provider and Domain options are restricted to
the current action and selected Provider, and a retained Domain is reindexed
when the Provider narrows its option set.

## Phase 5C handoff

Phase 5C must start from finalized `PluginSelection` and
`PluginContributionCandidate` evidence, pass exact owner admission, consume a
durable activation approval, load verified package symbols through the existing
Plugin import realm and Component Host, and hand Continuity an owner-validated
Provider value plus a revocation-safe authority lease.

The concrete lifecycle, sole-writer split, sealed-process behavior, and
consume-versus-revoke ordering are frozen by the
[Phase 5C contract baseline](continuity-provider-phase5c-contract.md).

It must not reintroduce any of the rejected Phase 5B review shapes:

- a public contribution that accepts raw factory/disposer callables;
- caller-constructed trusted snapshots or independent instance/trust readers;
- a contribution that mints its own Runtime Profile grant;
- Plugin identity inferred from self-reported Runtime Profile JSON config; or
- an issued activation lease that can publish after Plugin authority revocation.

## Explicit non-goals

Phase 5B does not add:

- installed Plugin discovery, declaration codecs, selection, or execution;
- Plugin deletion, rename, archive, sync, or arbitrary mutation callbacks;
- ambient filesystem discovery or `SessionDiscoverySource` construction;
- direct access to the Product runtime or canonical Conversation store;
- unbounded streams, binary data in cursors, or durable external staging paths;
- automatic two-way synchronization or global Blob deduplication.

Mutation, if added later, enters as a typed, previewable, revalidated plan
rather than another Provider method.
