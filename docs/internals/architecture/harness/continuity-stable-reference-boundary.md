# Continuity Stable Reference Boundary

## Status

Implemented CLA7d boundary. The stable reference, shutdown order, consumer
migration, acceptance gates, and evidence defined here are landed on the
harness lane. This document defines
the process-owned typed stable reference and the shutdown order required by
the [Capability Composition Lifecycle Authority
Plan](composition-lifecycle-authority-plan.md) slice CLA7d before any
Session-scoped Consumer may observe continuity facts. Acceptance of this
document authorizes one bounded implementation PR; it does not change current
source behavior and does not unlock the graph `stable_reference` requirement
binding, which remains fail-closed.

Revision 2 incorporates three-reviewer findings: the observation descriptor
channel, the CLI migration entry, the close-then-record shutdown
restructuring, and the outstanding-activation-lease close interaction.

## Problem

`continuity.provider_packs` is a Process-scoped, sealed Runtime Profile slot.
The composed `ContinuityHub` is constructed once per Product runtime by
`coding/continuity.py::bind_coding_continuity` and disposed by
`shutdown_coding_continuity`. Today the concrete hub is threaded directly
into process-composed TUI surfaces and the CLI resume flow
(`coding/cli/__main__.py`, `coding/ui/screen_surfaces.py`,
`harnesstui/conversation/agent_surfaces.py`,
`harnesstui/continuity/runner.py`, `harnesstui/continuity/surface.py`).

Two facts make raw hub threading unacceptable as the long-term contract:

1. a Session-scoped observer would hold a reference to an object it neither
   owns nor can invalidate, while the process authority can dispose the
   underlying binding underneath it; and
2. the shutdown order between Session Graph retirement and process continuity
   disposal is currently implicit (a `try/finally` accident of two call
   sites), not a contract.

CLA7d requires a process-owned typed stable lease/reference and an explicit
shutdown order before a Session Consumer can observe continuity. The Session
Graph never owns the concrete `ContinuityHub`.

## Historical Source-Backed Baseline Before CLA7d

This table records the original problem state. The close-then-record contract
below superseded its mark-before-close behavior; A174 current implementation
ownership is recorded after the table.

| Fact | Site | Evidence |
| --- | --- | --- |
| Slot declaration | `src/loushang/harness/runtime/_profile_standard.py::CONTINUITY_PROVIDER_PACKS_SLOT` | scope `process`, refresh boundary `sealed`, ordered `aggregate_contribution` |
| Process binding and hub construction | `src/loushang/coding/continuity.py::bind_coding_continuity` | one `RuntimeProfileBinder`, one `ContinuityHub`, attached to the Product runtime via `_RUNTIME_BINDING_ATTRIBUTE`; rebinding with new layers/grants/implementations fails sealed |
| Mark-then-execute shutdown (requires restructuring) | `src/loushang/coding/continuity.py::CodingContinuityComposition.shutdown` | sets `_shutdown = True` before awaiting `binder.dispose`; a failed or cancelled close would make retry unreachable, so this slice restructures it to close-then-record (see Shutdown Order Contract) |
| Process shutdown entrypoint | `src/loushang/coding/continuity.py::shutdown_coding_continuity` | removes the runtime attribute, then awaits composition shutdown; safe to call repeatedly |
| Session-before-continuity ordering | `src/loushang/coding/runtime/agent_session_runtime.py::dispose_session_runtime` | `try` disposes the Session runtime, `finally` shuts down continuity; ordering exists by construction, not by contract |
| CLI continuation flow | `src/loushang/coding/cli/__main__.py` | binds continuity for the resume picker, calls `composition.hub.prepare` directly, passes the concrete hub to `continuity_runner`, disposes the caller view, and shuts continuity down only when no activation occurred |
| Hub composition metadata consumers | `src/loushang/harnesstui/continuity/surface.py` | reads `hub.composition.experience.domain_ids` and `hub.composition.continuity_providers` to build domain filter and sort options; any observation port must carry this metadata |
| Existing lease-like concept | `src/loushang/harness/continuity/provider.py::PreparedActivationLease` | an activation handle returned by `ContinuityHub.prepare`; consumption (`activation.py::consume_prepared_activation`) invokes the provider callback directly without re-entering the hub, so an issued-but-unconsumed lease currently outlives hub-level guards |
| Existing activation abort semantics | `src/loushang/harness/continuity/activation.py::CallbackPreparedActivationLease` | idempotent close/abort and `ActivationLeaseStateError` already exist and are reused by the close contract below |
| Graph contract reservation | `src/loushang/harness/capabilities/contracts.py::CapabilityRequirementBinding` | `stable_reference` is reserved; planning skips the scope-inversion check for it, and binding fails closed with `stable_reference_binding_not_implemented` (`graph_binding.py`) |


## Current Binding Lifetime Ownership (A174)

The public `CodingContinuityComposition` and private failed-construction data
record retain their Coding data fields, constructors and nominal identities.
Their complete methods now inherit the existing Continuity scope's private
`_ContinuityCompositionLifetime` and `_ContinuityBindingReservationLifetime`.
The ordinary bases add no second state or instance dictionary to the original
non-slotted data records. The concrete Hub, Publication, Profile binder/binding,
generation and pending-cleanup objects are the existing Core owners.

`harness.continuity._binding_lifetime.shutdown_bound_continuity` owns the full
bound-slot shutdown, retained reservation retry, original owned Task join and
identity-checked deletion. Coding's entrypoint binds its original slot name,
actual Coding composition/reservation classes and error policy. Unknown or
foreign bindings stay outside that nominal admission. An existing optional
owned-cleanup callback remains at its original final point; it is not claimed
to be pure or newly migrated IO.

The three flag and failure contracts remain separate: Hub/Publication and
binder success precede `_core_shutdown`; owned cleanup success precedes its
completion flag and final shutdown. Reservation cleanup catches each
`BaseException`, records its original code, continues later owners, and clears
only successful references. Caller cancellation removes a binding only if the
owned operation actually succeeded (and reservation codes are empty) and the
slot still holds that exact object. Task-creation rejection behavior is not
changed in this migration. These implementation placements preserve CLA7d's
reference authority and shutdown order; no graph binding, payload format or
storage capability is added.

## Decision Summary

1. **One typed observation reference.** `StableContinuityReference` is the
   only supported way for anything outside the process authority to observe
   continuity. It is a narrow, typed, async port over the hub's existing
   verbs (`query`, `preview`, `prepare`, `delete`) plus one frozen
   issuance-time metadata snapshot, and it revalidates authority liveness on
   every verb call. It owns nothing and cannot dispose anything.
2. **The process authority keeps exclusive ownership.** The concrete
   `ContinuityHub`, the Profile binding, and the binder remain owned by the
   Product runtime composition (`CodingContinuityComposition` today). No
   Session, graph node, CLI flow, or surface stores a `ContinuityHub`.
3. **Explicit shutdown order.** Reference invalidation, outstanding
   activation-lease abort, and in-flight join happen inside the process
   authority before the Profile binding is disposed. Session disposal
   completes before continuity shutdown begins; continuity shutdown must
   still succeed when a Session died without releasing its reference.
4. **Graph `stable_reference` stays fail-closed.** No graph node references
   continuity in this slice. Promoting continuity to a Session-graph
   dependency requires a concrete accepted Session Consumer and a separate
   decision; that Provider would receive a process-issued reference as an
   identity-only binding input and would never construct or own a hub.

## The Stable Continuity Reference

`StableContinuityReference` is harness-owned
(`src/loushang/harness/continuity/`, alongside the hub) and Product-neutral.
It is distinct from `PreparedActivationLease`, which remains an activation
handle with its own existing consumption semantics while the authority is
live.

Issuance and semantics:

- issued only by the process authority through one entrypoint
  (`ContinuityHub.reference()`); construction anywhere else is an
  architecture-gate violation;
- every verb revalidates liveness before delegating; after the authority
  begins closing, calls fail with the typed `StaleContinuityReferenceError`
  and never reach a provider;
- **admit protocol:** each verb performs its liveness check and in-flight
  registration synchronously, with no `await` between check and
  registration, so a verb admitted before close starts is always joined by
  close and a verb arriving after close starts never reaches a provider;
- `release()` is synchronous, idempotent bookkeeping so a Session or surface
  can declare it is done early; a released reference fails subsequent calls
  with the same typed error;
- the reference holds no disposal power over hub, binding, binder, or
  providers; releasing is never a precondition for authority shutdown;
- the reference carries no credentials, callbacks, or Product content; it is
  an identity-bearing observation port only.

### Observation Descriptor

Migrating the existing surfaces requires the hub's composition metadata
(domain filter options and sort options). The reference exposes one
synchronous property, `observation`, returning a frozen issuance-time
snapshot:

```text
ContinuityObservationDescriptor (frozen dataclass)
  experience: ExperienceDescriptor        # identity of the composed experience
  providers: tuple[ContinuityProviderDescriptor, ...]  # identity and admission metadata, no instances
```

The descriptor is identity-only metadata captured at issuance; it has no
liveness semantics, holds no provider object, and remains readable after
close so surfaces can render a stable final frame. It never exposes
credentials, callbacks, or provider instances.

## Shutdown Order Contract

The contract has three ordered steps and one failure rule:

1. **Session scope retires first.** When a Session-scoped holder exists, it
   releases its `StableContinuityReference` during Session shutdown, before
   Session Graph disposal completes. Release is cooperative bookkeeping; the
   authority must not depend on it for correctness.
2. **Authority close.** `CodingContinuityComposition.shutdown()` first awaits
   `ContinuityHub.close()`. Close, in one cancellation-atomic and idempotent
   operation:
   - marks the authority closing, staling every outstanding reference
     immediately (new verbs fail with `StaleContinuityReferenceError`);
   - aborts every issued-but-unconsumed `PreparedActivationLease` using the
     existing idempotent abort semantics, so no activation consumption runs
     after the binding is disposed; and
   - joins in-flight reference-guarded operations exactly once.
3. **Binding disposal.** Only after close completes does shutdown dispose
   the Profile binding via the binder. The binding is never disposed while
   a reference-guarded operation is in flight or an activation lease remains
   consumable.

**Close-then-record restructuring.** The current
`CodingContinuityComposition.shutdown()` sets `_shutdown = True` before
awaiting disposal (mark-then-execute). This slice restructures it: the
composition records shutdown completion only after `ContinuityHub.close()`
and binding disposal both succeed. A failed or cancelled close leaves the
composition unrecorded, so the retry called out below is actually reachable.

Failure rule: continuity shutdown runs even when Session disposal failed
(the existing `try/finally` ordering is part of this contract). Close
therefore force-stales references and aborts activation leases whose holders
died without releasing; unreleased references are stale, not leaks. A failed
close retains the un-disposed binding and surfaces a retryable diagnostic
rather than disposing underneath live operations.

## Migration Path For Current Consumers

Five current consumers thread the raw hub; all five migrate to
`StableContinuityReference`, issued once by the process authority and
threaded exactly where the hub is threaded today:

| Consumer | Current raw-hub use | Migrated shape |
| --- | --- | --- |
| `coding/cli/__main__.py` resume flow | `composition.hub.prepare(target)`; passes `hub=composition.hub` to `continuity_runner` | issues one reference; `reference.prepare(target)`; passes the reference to `continuity_runner` |
| `coding/ui/screen_surfaces.py` | passes `continuity.hub` into surfaces | passes the issued reference |
| `harnesstui/conversation/agent_surfaces.py` | stores `continuity_hub: ContinuityHub \| None`; `require_continuity()` | stores the reference; same `None` contract |
| `harnesstui/continuity/runner.py` | `hub: ContinuityHub` parameter | parameter becomes `StableContinuityReference` |
| `harnesstui/continuity/surface.py` | hub verbs plus `hub.composition` metadata reads | reference verbs plus the frozen `observation` descriptor |

After migration, only the process authority names `ContinuityHub` in a
stored field or parameter annotation. The migration is behavior-preserving
while the authority is live: same verbs, same timeouts, same domain/sort
options (via the descriptor), same `PreparedActivationLease` consumption
flow. It changes ownership visibility only.

## Acceptance Criteria

- a reference cannot outlive its authority: post-close and post-release
  calls fail with `StaleContinuityReferenceError` and reach no provider;
- the admit protocol holds: a verb admitted before close starts is joined by
  close, and a verb arriving after close starts never reaches a provider;
- `ContinuityHub.close()` aborts outstanding activation leases, joins
  in-flight reference operations exactly once, is idempotent, and converges
  under cancellation;
- no activation consumption starts once close begins: an issued-but-unconsumed
  `PreparedActivationLease` fails with the existing typed lease-state error; a
  consumption already in flight when close begins runs to completion unguarded
  and must not touch binding-owned state;
- the Profile binding is never disposed while a reference operation is in
  flight or an activation lease remains consumable; a failed close leaves
  the composition unrecorded and retryable;
- the `observation` descriptor carries the same domain and provider identity
  the surfaces use today (domain filter options and sort options regression
  tests stay green without `hub.composition`);
- a synthetic Session-scoped holder exercises both the cooperative
  `release()` path and the force-stale path (Session dies without release),
  proving shutdown-order step 1 and the failure rule;
- sealed rebinding, query cursor integrity, provider timeout behavior, and
  activation semantics while the authority is live are unchanged;
- no `harness/session/`, `harnesstui/`, CLI, or graph file stores or
  parameter-annotates `ContinuityHub`; construction of `ContinuityHub`
  remains frozen to `coding/continuity.py::bind_coding_continuity`;
- `stable_reference_binding_not_implemented` remains the binding diagnostic
  for graph `stable_reference` requirements; and
- the generated catalog and current owner map record continuity as
  Process-owned with the typed reference as the only observation port.

## Architecture Gates

The implementation PR adds or extends AST gates to freeze:

- `ContinuityHub` construction sites: `coding/continuity.py` only;
- `StableContinuityReference` issuance: `ContinuityHub.reference()` only;
- no `ContinuityHub` name in stored-field or parameter annotations outside
  `coding/continuity.py` (extending the existing construction-site AST
  visitor to annotation positions), backed by a text-prohibition assertion
  over `harness/session/`, `harnesstui/`, and CLI sources so unannotated
  assignments cannot bypass the gate; and
- the existing fail-closed `stable_reference` binding test remains green.

## Explicit Non-Goals

- no graph node, Provider, or Consumer for continuity in this slice;
- no unlock of the graph `stable_reference` requirement binding;
- no hot replacement, refresh, or rebind of continuity packs (the slot
  remains sealed);
- no redesign of `PreparedActivationLease`: while the authority is live,
  activation semantics are unchanged; close only applies the existing
  idempotent abort semantics to outstanding leases;
- no second ContinuityHub, hub registry, or service-locator access; and
- no new Product policy about which continuity providers exist.

## Relationship To The CLA Plan

This document is the explicit scope, refresh-boundary, restart-behavior, and
stable-reference definition required before the CLA7d slice moves. When the
implementation PR lands, the CLA plan's CLA7d entry gains its implemented
evidence pointing at this boundary, the migrated consumers, and the gates
above. CLA8 later removes or freezes any remaining raw-hub compatibility
surface.
