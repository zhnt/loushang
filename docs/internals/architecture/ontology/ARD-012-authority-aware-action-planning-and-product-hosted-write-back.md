# ARD-012: Authority-Aware Action Planning And Product-Hosted Write-Back

Status: Accepted, 2026-08-11. The ontology-owned Phase 2 slice is implemented;
source-backed write-back remains unimplemented.

## Context

The pre-Phase-2 Ontology runtime could describe operational state, materialize
one immutable read snapshot, and explain whether each value was source-backed,
ontology-owned, or derived. It could not change that state through a published
semantic Action.

Treating every Action as object CRUD would break the authority boundary already
accepted by ARD-003:

- an ontology-owned note may be committed as a Fact;
- an ERP-owned budget must be requested from the ERP through a Product adapter;
- a derived risk score must be recomputed, not edited;
- an accepted external request is not proof that a later read projection
  contains the requested value.

The first Action decision therefore needs to establish planning, concurrency,
idempotency, authorization, execution, acknowledgement, and reconciliation
boundaries before adding code. It must reuse existing Schema identity,
Deployment Profile v2, `MaterializationCut`, Fact commit, and source-binding
contracts without inventing a distributed transaction.

## Decision

### 1. Put published Action semantics in the compiled Schema

`ActionDefinition` is versioned semantic metadata. Phase 2 adds it to the Schema
draft and `CompiledOntologySchema`, so it is content-addressed inside
`OntologyPackageArtifact` and selected by the existing Schema lock in
Deployment Profile v2.

There will not be a second mutable Action catalog or registry beside the
compiled Schema. Phase 2 directly replaces the undeployed schema v3 contract
with `loushang.ontology.schema/v4`; there is no v3 compatibility reader.

The first format is deliberately narrow:

```text
ActionDefinition
  semantic_id
  name
  target_object_type_id
  parameters[]
  effect: SetProperty(property_id, value_parameter)
  policy_requirement_ref
  description
```

The action and every referenced target use package-local stable semantic IDs.
Parameters use the existing Ontology value types. The compiler validates the
target object type, property, parameter, and value-type agreement. The action
does not override the property's `StateAuthority`.

The first effect vocabulary contains only `SetProperty` on one existing object.
Object creation/deletion, property clearing, link mutation, multiple effects,
arbitrary expressions, embedded HTTP, SQL, shell, and Python are deferred.
This is enough to prove both writable authority paths without designing a
general workflow language.

### 2. Make Action planning pure and snapshot-guarded

The implemented `loushang.ontology.action` package accepts immutable values and
returns an immutable plan. It does not open stores, call APIs, write databases,
evaluate identity credentials, or execute tools.

An `ActionRequest` conceptually contains:

```text
deployment_id
deployment_profile_digest
schema_identity
action_id
request_id
target_object_id
strict JSON arguments
ProjectionGuard:
  schema_identity
  projection_version
  materialization_cut
actor_context_ref
valid_from
recorded_at
```

The guard identifies the exact projection against which the user, service, or
Agent chose the action. `built_at` is not part of the semantic guard. The
planner requires one matching immutable `ProjectionSnapshot` and the detached
`FactSelection` that exactly reproduces its Fact IDs, watermark, `valid_at`, and
`recorded_at`. The selection supplies any predecessor Fact envelope needed to
preserve lineage without giving the planner a Store. The planner validates the
target and arguments and emits an `ActionPlan` with a canonical `plan_digest`.
A mismatched Schema, projection version, cut, Fact selection, object type,
parameter, or target fails explicitly; the planner never silently replans
against newer state. Explicit `valid_from` and `recorded_at` values keep Fact
planning deterministic and free from a hidden wall clock.

The accepted target contains one of two mutually exclusive effects:

```text
OntologyFactEffect
  deterministic FactBatch
  expected_fact_watermark

SourceWriteRequirement
  source_instance_id
  adapter_id
  binding_id
  write_capability_id
  expected_source_revision
  semantic SetProperty intent
```

Phase 2 implements only `OntologyFactEffect`. A published source-backed Action
fails with `source_backed_action_unsupported`; `SourceWriteRequirement` is not
present as a placeholder public class. Derived properties fail as non-writable.

Planning uses the exact validated Deployment Profile v2 selection and enabled
`SourceBinding` values to resolve a source-backed property to one concrete
source instance and binding. Zero or multiple matching enabled bindings fail.
The request locks the Profile content digest so the same deployment ID cannot
silently change routing beneath an idempotency key. The plan contains no
endpoint, credential, database handle, or executable adapter object.

### 3. Route strictly by the target property's StateAuthority

The property referenced by the Action effect determines the route:

- `ontology-owned` produces exactly one `OntologyFactEffect`;
- `source-backed` produces exactly one `SourceWriteRequirement`;
- `derived` is rejected as non-writable.

The authority of object existence may differ from the property authority. For
example, a source-backed ERP project may have an ontology-owned review note.
Setting the review note still follows the property and commits a Fact.

The first slice has one effect and therefore one primary authority. A future
multi-effect Action must not be accepted until a separate decision defines
cross-authority ordering and partial failure. It must not claim database-level
atomicity across Ontology and external systems.

### 4. Commit ontology-owned effects as guarded Fact batches

The Fact effect uses the current immutable Fact model and an idempotent
`FactBatch`. Its batch identity is deterministically scoped by deployment,
action, and request ID; reusing that identity with different content remains a
conflict.

Normal Fact ingestion remains unconditional. Action execution, however,
atomically compares the plan's `expected_fact_watermark` and commits its
Fact batch. A caller-side read followed by an ordinary commit is not sufficient
because it creates a time-of-check/time-of-use race. Phase 2 therefore adds an
explicit guarded Fact commit operation to both Memory and SQLite rather than
pretending `commit_fact_batch(...)` supplies optimistic concurrency. Existing
same-content replay and same-ID content conflict are evaluated before the
watermark guard, so a recovered request can retrieve its prior result after the
journal has advanced.

An accepted Fact commit is durable semantic state. It does not mutate the
installed Projection. Materialization and atomic Projection replacement remain
a separate read-model refresh, and refresh failure leaves the previous
Projection installed and observably stale.

### 5. Execute source-backed effects only in Product-hosted adapters

Ontology emits a detached semantic requirement. A Product-hosted write adapter
translates it to the vendor operation, whether the concrete integration uses an
application API, a supported direct database write, or another governed
transport. Ontology does not distinguish those transports and never imports
their clients.

The selected binding and source instance provide routing. The write adapter
must bind `expected_source_revision` to a source-native conditional-write or
equivalent concurrency mechanism. If it cannot enforce the precondition, the
first source-backed slice is not safe to publish as writable and must reject
execution. A successful API or database acknowledgement means only that the
external system accepted the command; it does not mutate Ontology Facts or the
Projection.

A source route is not writable merely because its read binding owns the
property. A future Adapter manifest format must explicitly declare a stable
write capability for the Action, binding, and semantic target, including
conditional-write and idempotency support. The capability is covered by the
Adapter manifest digest already locked by the Profile. The planner emits its
`write_capability_id`, and the Product write adapter must present the same
manifest. The current read-only `SourceAdapterManifest` v1 declares no write
capabilities, so it authorizes no source-backed Action and is not widened by
this decision.

The changed value becomes observable only after the Product read adapter reads
a later immutable source snapshot and the ordinary materialization path installs
a Projection whose `MaterializationCut` includes that source revision.

### 6. Bind authorization to the exact plan, outside Ontology

`policy_requirement_ref` is an opaque semantic requirement, not an embedded
policy language. Product supplies authenticated actor context and invokes its
policy/approval boundary. Ontology does not authenticate actors, load policy,
manage credentials, or grant capabilities.

The order is:

```text
read guarded Projection
        |
        v
pure semantic planning --> plan_digest
        |
        v
Product policy / approval decision bound to plan_digest
        |
        v
guarded Fact commit OR Product-hosted source write
```

Execution accepts a stable authorization-decision reference that covers the
exact plan digest. A decision for one plan cannot authorize another plan after
arguments, target, route, or projection coordinates change. Product must also
enforce object visibility and action discovery before exposing sensitive data
to an untrusted caller.

### 7. Separate request idempotency, execution receipt, and observation

The canonical request digest covers deployment and exact Profile digest,
Schema, Action, request ID, actor context reference, target, arguments, and
Projection guard. Within one deployment and Action:

- the same request ID and digest returns the same durable execution record;
- the same request ID with another digest fails as an idempotency conflict;
- changing the guard for a retry requires a new request ID.

Product owns the durable Action execution ledger because it owns authorization,
external effects, and process recovery. FactStore does not become a generic
Action-run log, and ProjectionStore remains a disposable read model.
HarnessWork may be selected by Product as the durable executor/evidence host,
but it is optional and shares only stable references; Ontology does not import
HarnessWork types.

The minimum execution acknowledgement is one of:

- `accepted`: the guarded Fact commit succeeded, or the external endpoint
  accepted the idempotent command;
- `rejected`: execution definitely did not accept the effect;
- `unknown`: the caller cannot prove whether the external effect occurred.

An external `accepted` acknowledgement is never reported as observed Ontology
state. Reconciliation is a separate comparison against a later Projection cut
and reports `observed`, `not_observed`, or `unknown`. An `unknown` external
result must not be blindly retried under a new idempotency key. Safe retry uses
the same key only when the external adapter can preserve its semantics;
otherwise the Product reconciles or requests manual resolution.

### 8. Keep the dependency direction one-way

The accepted future dependency direction is:

```text
ontology.action ---------------------> schema + projection read/model
                                       + facts contracts + source + deployment

Product write adapter --------------> ontology.action contracts
Product execution composition ------> ontology + harness + optional harnesswork

ontology.action -X-> Product implementation, vendor SDK, network, database
ontology        -X-> harness, harnesswork, method, agent
```

No existing Ontology package depends on `ontology.action`. In particular,
Schema, Facts, Source, Projection, Query, Storage, Package, and Deployment stay
below it. Product remains the composition root.

## Failure Contract

- invalid Action definition, request, value, target, authority, or route fails
  before authorization or effect execution;
- a changed Projection guard fails as stale rather than replanning silently;
- an ontology-owned watermark mismatch commits no Action Fact;
- a source revision precondition failure is rejected, not accepted as a local
  overlay;
- an external timeout or lost acknowledgement is `unknown`, not success;
- Action execution never writes Projection tables directly;
- materialization or Projection replacement failure cannot undo an accepted
  Fact or external effect and cannot make the old Projection claim freshness;
- derived properties cannot be changed by routing through another authority.

## Consequences

- one published Action has portable semantic meaning while deployment selects
  its concrete source route;
- API and direct-database integrations can share the same Ontology contract
  without placing connector code in Ontology;
- ontology-owned and source-backed writes have different commit mechanics but
  the same planning, authorization-binding, idempotency, and acknowledgement
  concepts;
- write success, read-model refresh, and semantic observation remain distinct;
- the first implementation can be tested without a workflow engine, policy
  engine, environmental package, or external vendor connector.

## Implementation Boundary And Acceptance Gates

Phase 2 implements only ontology-owned `SetProperty` and proves:

- deterministic Action definition/request/plan serialization and digests;
- compile-time target and value-type validation;
- exact Projection guard validation;
- deterministic FactBatch planning;
- atomic watermark-guarded commit and idempotent replay in both Memory and
  SQLite conformance suites;
- accepted Fact state remains separate from later Projection refresh;
- architecture gates preserve the dependency direction above.

The fixed Product-boundary integration slice uses a source-backed Project with
an ontology-owned review note. It proves plan, guarded commit, stale old
Projection, rematerialization, and typed query without adding a connector or
execution runtime.

The later source-backed slice must additionally prove:

- exactly one selected source-instance/binding route;
- one exact write capability declared by the Profile-locked Adapter manifest;
- a detached requirement and Product-hosted structural write-adapter boundary;
- conditional source revision enforcement;
- stable `accepted` / `rejected` / `unknown` receipts;
- no Projection change before adapter reread and materialization;
- restart-safe request idempotency in the Product-owned execution ledger.

## Relationship To Earlier Decisions

- ARD-001 remains authoritative for FactStore semantic records. Ontology-owned
  Action effects use Facts rather than a mutable ObjectStore.
- ARD-003 remains authoritative for `StateAuthority`; this ARD resolves its
  first write-routing, acknowledgement, idempotency, and reconciliation
  deferrals, and explicitly rejects cross-authority Actions in the first slice,
  without adding an overlay or saga.
- ARD-004 and ARD-005 remain authoritative for exact source cuts, immutable
  Projection state, freshness, and durable read-model persistence.
- ARD-006 remains authoritative for Product-hosted source reads. This ARD uses
  the same detached-contract pattern for future writes but does not widen the
  existing read-only `SourceAdapter` protocol or manifest v1.
- ARD-010 remains authoritative for source-instance/binding selection. Action
  routing consumes that validated selection and does not add endpoints or
  credentials to Deployment Profile v2.
- ARD-011 remains authoritative for package artifacts. Schema v4 Action
  definitions now enter the existing package digest without changing the
  package envelope format.

## Non-Goals And Deferred Decisions

- no source-backed Action planning or execution in Phase 2;
- no mutable edit overlay or optimistic local claim for source-backed state;
- no object creation/deletion, property clear, link mutation, bulk mutation,
  or multi-effect Action;
- no cross-authority Action, saga, compensation, distributed transaction, or
  automatic retry engine;
- no policy engine, identity system, approval queue, credentials, endpoint,
  connector registry, or vendor adapter implementation;
- no arbitrary action DSL, embedded code, HTTP template, SQL, or shell;
- no Decision, Scenario, Outcome, Method, Agent, or HarnessWork integration;
- no Action-run persistence inside FactStore or ProjectionStore;
- no project-management or environmental domain Action;
- no generated SDK, REST, GraphQL, RPC, or MCP Action surface;
- no general external-effect reconciliation scheduler.
