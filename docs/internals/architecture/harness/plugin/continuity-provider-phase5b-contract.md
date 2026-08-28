# Continuity Provider Plugin Contract (Phase 5B)

## Status and authority

- Contract: Phase 5B implemented boundary for Plugin-contributed Continuity
  Providers.
- Owner: `loushang.harness.continuity` owns admission, federation budgets,
  portable activation payloads, and Provider lifecycle composition.
- Product owner: the Product supplies the activation bridge into its canonical
  Session lifecycle and the current Plugin instance/trust readers.
- Plugin: contributes bounded query, preview, and portable import preparation.
  It never receives a Session store, Product runtime, filesystem root, deletion
  capability, or canonical transcript writer.

This contract refines
[Session Discovery and Continuity](../session-discovery-continuity.md) and the
[Plugin Architecture](architecture.md). It does not replace either authority.

## First-principles split

Discovery, activation, and mutation are different authorities:

```text
Plugin Continuity Provider
    query / preview / prepare portable bytes
                    |
                    v
Harness admission + budgets + read-only adapter
                    |
                    v
Product activation bridge
    canonical copy-first Session lifecycle
```

A Plugin target is opaque and Provider-qualified. Visibility grants no local
path authority. The adapter strips `delete` from Plugin summaries and does not
implement the deletion protocol, even when the underlying Python object has a
method with that name. Mutation contribution remains a later typed-plan phase.

## Admission identity

One `ContinuityPluginProviderContribution` is pinned to all of:

- Product and Experience identity;
- Plugin ID plus contribution ID;
- exact `PluginInstanceRevisionRef`;
- exact trusted `PluginSourceTrustSnapshotV1`;
- implementation version, priority, and strict-JSON binding inputs; and
- current instance and trust readers supplied by the Product owner.

The adapter revalidates instance and trust identity before factory execution
and before every Provider operation. Update, disable, uninstall, trust-policy
change, or Instance revision change therefore fails closed without reaching
the Plugin.

Admission projects one process-scoped, sealed `extension` Runtime Profile
layer. The existing `continuity.provider` permission remains mandatory. The
factory receives `ContinuityPluginProviderContext`, not the Product runtime.
That context contains only redacted identity and frozen binding inputs.

## Portable activation

Plugins prepare `ContinuityActivationPayload` values. Phase 5B supports the
existing portable transcript media types:

- Conversation JSONL; and
- `.loushang.zip` transcript-and-Blob bundles.

The payload is immutable bytes with an exact SHA-256 digest, optional cwd
fallback, and a hard aggregate size ceiling. Harness validates it before the
Product bridge is called. The Coding bridge publishes a private temporary file,
asks the existing transcript lifecycle to prepare a copy-first import, and
removes the temporary source before returning the activation lease. Consume is
therefore the existing canonical Session transition; abort rolls back the
unpublished lifecycle candidate.

Plugin preparation and Product preparation are one combined lease. Abort,
failure, cancellation, Hub shutdown, or successful consumption settles both
sides exactly once.

## Composition and diagnostics

Runtime Profile provenance remains the composition identity used by signed
Hub cursors. Plugin layers additionally carry finite JSON identity fields so a
stable observation can report Product, OEM, or Plugin origin without exposing
paths or credentials. Duplicate Provider IDs remain rejected across every
pack.

The common Resume surface may filter by Provider as well as Domain. Provider
failure remains partial-result diagnostics; it does not replace successful
results from other admitted Providers.

## Explicit non-goals

Phase 5B does not add:

- Plugin deletion, rename, archive, sync, or arbitrary mutation callbacks;
- ambient filesystem discovery or `SessionDiscoverySource` construction;
- direct access to the Product runtime or canonical Conversation store;
- unbounded streams, binary data in cursors, or durable Plugin staging paths;
- automatic two-way synchronization or global Blob deduplication.

Those require separate owner contracts. Mutation, if added, enters as a typed,
previewable, revalidated plan rather than another Provider method.
