# Continuity Provider Plugin Lifecycle (Phase 5C Contract Baseline)

## Status and authority

- Document kind: incremental contract baseline.
- Current implementation status: design frozen for the first Phase 5C runtime
  slice; the installed-Plugin path described here is not implemented yet.
- Continuity owner: `loushang.harness.continuity` owns the Provider payload
  schema, semantic validation, process generation, federation, and retirement.
- Product owner: selects exact admitted contributions, supplies Experience
  inputs and the canonical Session activation bridge, and owns process startup
  and shutdown ordering.
- Plugin lifecycle owner: owns installed state, immutable package and Instance
  identity, `owner_generation` lease families, graceful drain, security
  revocation, cleanup evidence, and package retention.
- Approval owner: is the sole writer of declaration-execution and component-
  activation decisions and their one-use state.
- Component Host: is the only code loader and constructor for external
  Provider components. A Plugin declaration never carries a live callable.

This baseline refines the
[Phase 5B foundation](continuity-provider-phase5b-contract.md), the
[Plugin Architecture V2](architecture.md), and the
[Continuity Stable Reference Boundary](../continuity-stable-reference-boundary.md).
It supersedes no earlier contract. In particular, it does not change the
Product/OEM authority of the existing `continuity.provider_packs` Runtime
Profile slot.

## Decision

An installed Plugin contributes a component to the Continuity owner. It does
not contribute a Runtime Profile layer and does not become a Capability Graph
Provider.

```text
verified package + finalized PluginSelection
                    |
                    v
strict continuity_provider declaration decoder
                    |
                    v
Continuity owner candidate and exact owner admission
                    |
                    v
Product component selection + durable activation approval
                    |
                    v
CapabilityOwnerComponentHost + verified PluginImportRealm
                    |
                    v
private process-scoped Continuity owner generation
                    |
                    v
one Continuity composition + ContinuityHub
                    |
                    v
StableContinuityReference + Product activation bridge
```

This reuses `CapabilityComponentDefinition`, exact owner admission,
`ProductCapabilityComponentResolver`, `CapabilityOwnerComponentHost`,
`CapabilityOwnerComponentRuntime`, and Plugin Instance `owner_generation`
lease families. It creates no second Plugin lifecycle, approval journal,
importer, registry, Runtime Profile Binder, Capability Graph, or stable
reference.

The owner-component runtime is used here as a lifecycle primitive inside the
process Continuity authority. Continuity remains outside the Session Graph.
The Product publishes no Session until its normal Session path is ready, and a
Continuity Provider never receives a Session Graph, canonical Conversation
store, Product runtime, or ambient service locator.

## Narrow declaration contract

Phase 5C adds the owner-scoped `continuity_provider` contribution kind. It is
not a universal public `capability_component` SDK. Its owner must be exactly
`harness.continuity`, and its contribution execution model is exactly
`in_process`. Unknown kinds, payload versions, fields, symbol shapes, owners,
or execution models fail closed.

The v1 payload contains exactly:

| Field | Contract |
| --- | --- |
| `payloadVersion` | integer `1` |
| `continuityProfileVersion` | integer `1` |
| `factory` | exact package-local `PluginSymbolReference` v2 |
| `disposer` | required, non-null package-local `PluginSymbolReference` v2 |
| `bindingInputs` | strict JSON exactly matching Product-effective configuration |

Factory and disposer use the same declared execution model. Their paths and
symbols are inert until the Component Host resolves them from the exact
verified package revision. The declaration contains no package path, trust
snapshot, Product grant, Runtime Profile selection, authority reader, bridge,
or live callback.

The component ID is not a declaration field. The Host derives it from the
exact Plugin and contribution identity, so a Plugin cannot collide with or
impersonate another component by self-reporting an owner-visible name.

The finalized `PluginContributionCandidate` is the only legal decoder input.
The Continuity compiler derives, rather than accepts from a caller:

- package content and dependency-lock digests;
- Plugin and contribution identity;
- exact `PluginInstanceRevisionRef`;
- package source and trust identity;
- Product, scope, and policy revision;
- declaration and evidence fingerprints; and
- effective authority ceiling.

The compiler emits one inert `CapabilityComponentCandidate` against this
owner definition:

```text
capability_id:              harness.continuity
owner_id:                   harness
component_kind:             continuity.provider
payload_schema_id:          loushang.continuity-import-provider-pack
payload_schema_version:     1
compatible_bundle_contract: exactly 1
multiplicity:               aggregate
selection_policy:           ordered_unique
minimum_count:              0
maximum_count:              32
refresh_boundary:           owner_generation
disposer_contract:          required
requested_facets:           none
service_references:         none
```

The first implementation keeps the internal definition and decoder under the
Continuity owner. It is not re-exported as a general Plugin authoring helper.

## Admission, selection, and construction

There is one complete identity chain:

1. Product selection finalizes a `PluginSelection`; unselected declarations
   and raw declaration documents are not owner candidates.
2. The Continuity decoder exact-matches the declaration to its reservation,
   effective configuration, package, evidence, Instance revision, and trust
   snapshot.
3. `CapabilityComponentOwnerAuthority` validates the Continuity definition,
   allowed component IDs, trust class, requested authorities, policy revision,
   revocation epoch, and bounded admission interval.
4. `ProductCapabilityComponentResolver` chooses an ordered unique set. Product
   order is the only Plugin Provider precedence input.
5. Before any import, the process owner acquires one Plugin Instance
   `owner_generation` family per selected Installation. It resolves the
   Installation from the authoritative Instance ledger, never from declaration
   data, and uses the exact staged Continuity generation reference as holder
   identity.
6. The Approval owner records one fresh component-activation decision per
   selected component. `CapabilityOwnerComponentHost.prepare_component`
   consumes it once but keeps import lazy.
7. `CapabilityOwnerComponentBinder.bind` is the first point at which verified
   symbols are imported and factories run. The payload validator accepts only
   a concrete `ContinuityImportProviderPack` satisfying the Phase 5B protocol.
8. All component activation uses reach `COMMITTED` only after the private owner
   generation is published. Only after every commit is durable may Continuity
   compose and expose the new Hub/reference.

The owner generation is private until step 8 completes. A failure or
cancellation before external publication reverse-disposes constructed packs,
aborts every uncommitted activation use, releases newly acquired Instance
families, and publishes neither a Provider nor a stable reference. Cleanup is
cancellation-atomic and retryable; a failed disposer or lease release retains
the exact pending owner state rather than reporting success.

The Provider factory receives only the existing least-authority
`CapabilityOwnerComponentContext`: immutable Product/runtime/generation
identity, the exact resolved component, strict binding inputs, and explicitly
declared dependencies. The initial Continuity definition declares no service
references, so the factory receives no Product service or activation bridge.

## One final Continuity composition

Product/OEM packs continue through the Process-scoped, sealed
`continuity.provider_packs` slot. Plugin packs enter through the private
Continuity owner generation. These are two input authorities, not two output
authorities: the Continuity owner performs one final composition before the
Hub becomes observable.

The final composition:

- flattens Product/OEM and selected Plugin packs in Product-defined order;
- enforces one aggregate ceiling of 32 Providers across every Plugin pack;
- rejects duplicate Provider IDs across every source;
- validates Experience, Domain, profile-version, sort, and action contracts;
- derives Plugin provenance from the finalized selection and owner generation,
  never from Provider JSON or Runtime Profile config;
- narrows Plugin Providers to the read-only query/preview/prepare-import
  contract and the `activate` action; and
- wraps every Plugin call with the generation authority gate described below.

`BoundContinuityProvider` therefore needs an owner-derived source descriptor
for the Plugin arm. Product/OEM provenance remains the existing
`ResolvedRuntimeSelection`. Plugin provenance is a typed projection of the
exact candidate/admission/selection/binding/generation chain. It contains no
factory, filesystem path, secret, approval receipt, or live authority object.

Phase 5C preserves sealed process semantics: graceful disable or update affects
new Product processes, while the current process retains its pinned generation
until orderly shutdown. In-place Provider hot replacement and a swappable
stable reference are separate future work.

## Revocation and activation linearization

An Instance lease pins lifetime; it is not permission to continue executing
after security revocation. Each published Plugin Provider is therefore wrapped
by one Continuity-owned generation gate.

Every query, preview, prepare-import, and activation consume performs a
synchronous admit operation before its first `await`. Admission checks the
exact generation and Plugin Instance revision, registers the in-flight call,
and rejects a security-closing generation. Completion unregisters exactly
once. The Plugin does not receive or implement this gate.

Security revocation follows this order:

1. durably accept the Plugin management operation and security retirement
   intent, so crash recovery cannot forget the requested revocation;
2. synchronously mark the affected generation security-closing;
3. reject new Provider calls and activation consumes;
4. abort every issued-but-unconsumed activation lease;
5. join calls and consumes that linearized before the close mark;
6. durably enter Plugin Instance `REVOKING`;
7. dispose the Continuity owner generation and hand off exact cleanup/package
   retention evidence; and
8. release its `owner_generation` family only after disposal succeeds.

Thus consume and revoke have one observable order. A consume admitted first
may finish the canonical Product publication while revocation waits. A revoke
admitted first prevents that lease from publishing. A process crash loses no
durable prepared Continuity use: unpublished activation leases are process-
local and canonical Session recovery remains Product-owned.

The first implementation closes the whole Plugin-bearing Continuity owner
generation when any member is security-revoked. It does not surgically mutate
an aggregate generation or silently keep a peer Hub alive. Product/OEM and
unaffected Plugin Providers become available again only through a fresh
process composition. If trusted in-process code ignores cancellation and does
not quiesce within the bounded shutdown budget, the generation stays poisoned,
its Instance/package leases stay pinned, cleanup is reported retryable, and
the Product process must terminate or restart; the Host does not claim it can
forcibly contain already executing in-process Python.

`prepare_import` returns source-owned bytes. The Product bridge copy-first
prepares an unpublished canonical Session candidate and closes the source
lease. The returned outer lease remains generation-gated until consume or
abort, even though its bytes are already Product-owned. After a consume wins
the gate and commits, the resulting canonical Session is Product data;
subsequent Plugin revocation does not retroactively delete it.

Graceful drain differs deliberately. No new owner generation may acquire a
`DRAINING` Instance, but the already pinned sealed process generation may
continue until Product shutdown. Shutdown closes the Hub and outstanding
activation leases first, disposes the Continuity generation second, and
releases Instance/package leases last.

## Failure and diagnostic contract

Diagnostics expose stable codes and redacted identities. They may include
Plugin ID, contribution ID, component ID, Instance revision, owner generation,
and structural fingerprints. They do not include payload bytes, cursors,
factory paths, source cwd suggestions, secrets, raw exceptions, or approval
records.

The first implementation must distinguish at least:

- unsupported or invalid Continuity declaration;
- finalized-selection or evidence mismatch;
- owner admission or Product selection rejection;
- missing, stale, denied, or consumed activation decision;
- stale Product policy, owner snapshot, trust snapshot, or Instance revision;
- verified import/factory/payload/disposer failure;
- duplicate or invalid Provider metadata;
- security-closing generation;
- activation authority lost before consume; and
- retryable generation or Instance-family cleanup failure.

## Explicit non-goals

Phase 5C does not add:

- Extension access to `continuity.provider_packs`;
- caller-supplied factories, disposers, grants, trust snapshots, or readers;
- a public universal component SDK;
- untrusted in-process code, Worker/remote Provider topology, or new sandbox
  claims;
- Plugin delete, rename, archive, synchronization, or arbitrary mutation;
- direct local Session path discovery or source cwd authority;
- hot replacement inside a running sealed Product process; or
- automatic deletion of canonical Sessions after Plugin removal or revocation.

## Delivery slices and gates

The runtime work follows four reviewable slices:

1. **5C1 — inert contract:** strict `continuity_provider` reservation/payload
   codec, finalized-candidate compiler, owner definition, and rejection tests.
2. **5C2 — owner lifecycle:** exact admission/selection, activation approval,
   Component Host construction, private generation publication, Instance
   family pinning, and reverse cleanup.
3. **5C3 — composition and activation:** one final Product/OEM/Plugin
   composition, owner-derived provenance, read-only wrappers, Product bridge,
   and generation-gated activation leases.
4. **5C4 — retirement integration:** graceful drain, security quiesce and
   revocation ordering, shutdown/recovery diagnostics, and end-to-end Coding
   opt-in evidence.

Each slice requires architecture, security/lifecycle, and product/test review.
The Phase 5C exit gate is an end-to-end installed Plugin that traverses
published package, finalized selection, exact owner admission, durable
activation approval, verified construction, process publication, query,
preview, canonical Session activation, graceful shutdown, and security
revocation without any peer live path or leaked lease.
