# ARD-009: Explicit Identity Crosswalk Snapshots

Status: Accepted, 2026-08-10.

## Context

Mapped source objects and links already carry canonical Ontology object UUIDs,
but ARD-003 deliberately deferred the contract that turns a source record key
into that UUID. The fixed ERP reference Adapter previously generated UUIDs
inside Adapter code. That was deterministic, but it silently made one Adapter
the owner of an enterprise identity decision and could not represent ambiguity.

Identity matching, review queues, and mastered identifiers vary by Product and
deployment. Bringing those capabilities into the Ontology kernel would create
a second operational system of record before its persistence, review, and
governance requirements are known. The first needed boundary is smaller: an
Adapter must consume an explicit, immutable identity-provider result and must
refuse to guess when that result is missing or ambiguous.

## Decision

### 1. Add a leaf `ontology.identity` contract

`loushang.ontology.identity` owns only serializable identity result values and
a read-only resolver port. It depends on Foundation JSON and the standard
library. Schema, Source, Facts, Projection, Query, Storage, and Deployment do
not depend on it.

A Product composition root may inject the resolver into a concrete Product
Adapter. The Adapter may then emit ordinary `MappedSourceInput`; the existing
Source and materialization contracts remain unchanged.

```text
Product identity provider --> immutable CrosswalkSnapshot --+
                                                           |
Source system -----------> Product Adapter + Resolver -----+
                                                           |
                                                           v
                                                  MappedSourceInput
                                                           |
                                                           v
                                                   Ontology materializer
```

Ontology does not host or invoke a matcher, review UI, or mutable identity
registry.

### 2. Scope source record identity explicitly

`SourceRecordIdentity` is the tuple:

```text
source_instance_id
binding_id
record_type
source_record_key
```

The same vendor key may occur in different database instances, bindings, or
record types; none of those dimensions may be omitted. Display values are not
identity keys. Alternate-key discovery and entity matching remain provider
responsibilities.

### 3. Represent confirmation, absence, and ambiguity without guessing

Each `IdentityResolution` has exactly one state:

- `confirmed`: contains one canonical UUID and a non-empty decision reference;
- `unresolved`: contains no canonical UUID and no candidates;
- `conflict`: contains at least two candidate UUIDs, a decision reference, and
  no selected UUID.

Only `confirmed` may become an object ID. `require_confirmed_identity(...)`
returns that UUID or raises a stable failure code: `identity_missing`,
`identity_unresolved`, `identity_conflict`, or `identity_source_mismatch`.
Candidate order cannot influence selection because the helper never selects a
candidate.

The decision reference is opaque. It can point to a Product-owned master-data
record, review case, approval, or another durable explanation without making
Ontology understand that system.

### 4. Make provider output immutable and content-addressed

`IdentityCrosswalkSnapshot` contains:

```text
format
deployment_id
identity_namespace
revision
ordered resolution entries
```

It has strict deterministic JSON and a SHA-256 `crosswalk_digest`. Entry order
is canonicalized by the complete source-record identity, and duplicate source
records fail construction. `identity_namespace` identifies the provider's
canonical object-ID space; it is not an instruction for Ontology to generate
UUIDs.

The snapshot is deployment-scoped provider output, not the mutable source of
truth for identity decisions. Product is responsible for selecting and
retaining it and for ensuring that its `deployment_id` matches the deployment
being composed.

### 5. Keep this cut separate from Deployment Profile v1

ARD-008's Deployment Profile v1 remains unchanged. It locks Schema and Adapter
manifest artifacts, but does not yet lock an identity provider or crosswalk.
Adding a provider reference or identity-snapshot digest requires a separate
profile-version decision together with activation and retention semantics.

The current `MaterializationCut` remains exact for the detached mapped payload:
canonical object UUIDs are part of that payload and therefore affect its
digest. It does not record the crosswalk revision or digest, so audit of the
source-key-to-UUID decision additionally requires the Product host to retain
the selected crosswalk snapshot. This limitation is explicit rather than
papered over with a second implicit provenance model.

ARD-010 later supersedes this transitional Profile relationship: Profile v2
locks the selected Crosswalk namespace, revision, and digest and binds its
source scopes to selected source instances. The immutable Crosswalk and refusal
semantics in this ARD remain current.

## Dependency Direction

```text
ontology.identity -------------------> Foundation JSON
Product Adapter ---------------------> ontology.identity + ontology.source

schema / source / facts / projection / query / storage / deployment
                            -X-------> ontology.identity
ontology.identity           -X-------> Product, database, matcher, review UI
```

## Consequences

- Concrete Adapters no longer manufacture canonical identities from local
  conventions hidden in their implementation.
- Missing and ambiguous records fail before they can be silently fused.
- Multiple application instances can reuse the same Adapter without colliding
  solely because their vendor record keys are equal.
- Identity-provider technology and persistence can vary by Product without
  entering the Ontology kernel.
- A large or frequently changing identity registry will need an indexed
  provider implementation; the in-memory snapshot is a contract and reference
  slice, not a claim of production-scale storage.

## Acceptance Gates

- all identity values have strict deterministic JSON round trips;
- crosswalk digests are independent of input entry ordering;
- source identities differ when any scope dimension differs;
- only a confirmed result yields a canonical UUID;
- missing, unresolved, conflicting, and mismatched results expose stable
  failures without candidate selection;
- the Product-side SQLite ERP Adapter consumes an injected resolver instead of
  generating UUIDs internally;
- architecture gates keep identity a leaf and prevent Ontology runtime packages
  from importing it;
- no identity matcher, mutable registry, persistence adapter, review workflow,
  confidence score, or automatic merge policy is introduced.

## Relationship To Earlier Decisions

- ARD-003's requirement to preserve uncertain identities as separate records
  now has an executable explicit-resolution boundary; its broader multi-source
  identity policy remains deferred.
- ARD-004 still owns canonical UUIDs in mapped inputs and their content-digested
  cuts. This ARD only defines how Product Adapter code may obtain those UUIDs.
- ARD-006 still keeps concrete Adapter execution in Product. The new resolver
  is injected at that same Product boundary.
- ARD-008 was the exact Deployment Profile v1 contract when this decision was
  accepted. ARD-010 now supersedes that shape with Profile v2 and an explicit
  Crosswalk lock.

## Deferred

- a mutable identity-provider service and persistent indexed resolver;
- alternate keys, probabilistic matching, confidence, merge/split history, and
  human review workflow;
- cross-source precedence and automated entity-resolution policy;
- identity-provider service references and Product retention/activation beyond
  the immutable Crosswalk lock now defined by ARD-010;
- incremental crosswalk changes and activation consistency with source reads;
- authorization and tenant isolation for identity decisions;
- exposing identity-decision provenance directly in `MaterializationCut` or
  projected `ValueOrigin`.
