# ARD-010: Deployment-Bound Source Instances And Identity Lock

Status: Accepted, 2026-08-10.

## Context

ARD-008 v1 locks one compiled Schema and its Adapter manifests, then selects
binding IDs. ARD-009 adds a separately retained immutable Identity Crosswalk.
The two-source ERP plus maintenance reference scenario exposed the remaining
deployment ambiguity:

- an Adapter manifest identifies compatible software, not a concrete ERP,
  maintenance, warehouse, province, or city instance;
- a binding ID alone does not say which concrete source instance it reads;
- the Profile does not prove which Crosswalk bytes were selected;
- checking only `crosswalk.deployment_id` in Product code is not a deployment
  compatibility contract.

There is no deployed Ontology Profile compatibility obligation. Preserving v1
would create two incomplete ways to describe the same greenfield selection.

## Decision

### 1. Replace Profile v1 with v2 directly

The only accepted format becomes:

```text
loushang.ontology.deployment-profile/v2
```

There is no v1 reader, alias, migration, or dual constructor.

Profile v2 contains:

```text
deployment_id
schema_lock
ordered adapter_locks
ordered source_instances
optional identity_crosswalk_lock
fact_store_ref
projection_store_ref
```

The former top-level `enabled_binding_ids` is removed. Its information is now
owned by source-instance selections rather than duplicated.

### 2. Bind concrete source instances to Adapter bindings

Each immutable `SourceInstanceSelection` contains:

```text
source_instance_id
adapter_id
ordered binding_ids
```

A source-instance ID is unique within one Profile. Every selection names one
locked Adapter and at least one binding declared by that Adapter. A binding can
be selected by exactly one source instance in this first whole-snapshot design;
selecting the same binding against several instances would require a distinct
binding-instance input coordinate and is deferred.

The union of all selected binding IDs is the enabled binding set. Every locked
Adapter must contribute at least one selected binding. Source endpoints,
credentials, database paths, and client objects remain Product configuration;
the source-instance ID is only their stable deployment coordinate.

### 3. Lock immutable Crosswalk identity and content

`IdentityCrosswalkArtifactLock` independently records:

```text
identity_namespace
revision
content_digest
```

`lock_identity_crosswalk(...)` derives it from canonical Crosswalk JSON. Profile
validation receives the detached `IdentityCrosswalkSnapshot` selected by the
Product host and checks:

- lock presence or absence agrees;
- Crosswalk deployment ID equals Profile deployment ID;
- namespace, revision, and content digest each match;
- every Crosswalk entry refers to a selected source-instance/binding pair.

The lock is optional so a deployment with no Product source, or an Adapter
whose source already supplies accepted canonical IDs, need not invent an empty
identity system. When a lock exists, exact snapshot bytes must be supplied for
validation.

### 4. Keep validation detached and non-executable

`validate_deployment_profile(...)` still receives values, not loaders. It
validates exact Schema, Adapter, source-instance, and Crosswalk selections and
returns canonical enabled `SourceBinding` values. It does not:

- resolve source-instance IDs into endpoints or credentials;
- instantiate Adapter code;
- open source or Ontology stores;
- mutate, query, or review identity state;
- activate or switch a deployment.

Product constructs concrete Adapters with the source instance and immutable
resolver that passed validation, then reads detached mapped snapshots.

### 5. Define the reproducibility boundary without claiming a global transaction

The Profile digest proves the selected Schema, Adapter manifests, source
instances, bindings, Crosswalk, and opaque store references. A
`MaterializationCut` proves the exact Fact selection and resolved mapped source
payloads. Product must retain the Profile, Crosswalk, and resulting Projection
cut together as deployment evidence.

Projection does not import Deployment or Identity, and `MaterializationCut`
does not duplicate Profile or Crosswalk fields. There is no atomic transaction
across external source databases. Consistency comes from immutable artifact
selection, Adapter-local snapshot reads, exact mapped-payload digests, and
explicit source revision coordinates.

## Dependency Direction

```text
identity -----------------------------> Foundation JSON
deployment.model ---------------------> schema.identity + Foundation JSON
deployment.validation ----------------> deployment.model + schema + source
                                       + identity

schema / source / facts / projection / query / storage -X-> deployment
schema / source / facts / projection / query / storage -X-> identity
deployment -X-> Product endpoints, credentials, Adapter implementations
```

Identity remains a lower-level immutable contract. Deployment may validate an
Identity artifact; Identity does not depend back on Deployment.

## Consequences

- the same Adapter package can be selected for distinct bureau source
  instances without treating its manifest as an endpoint;
- a Profile now records which binding belongs to which source instance;
- Crosswalk content drift is detected independently from its human revision;
- an identity entry for an unselected instance or binding cannot leak into the
  deployment selection;
- v1 JSON fails explicitly instead of being interpreted with incomplete
  semantics;
- Profile validation still does not prove source availability or replace
  Adapter output conformance.

## Acceptance Gates

- v2 values and nested locks have deterministic strict-JSON round trips;
- v1 documents are rejected and no v1 compatibility symbol or reader remains;
- source instances and binding assignments canonicalize deterministically;
- unknown Adapter, wrong-Adapter binding, and unused Adapter locks fail with
  stable validation codes; duplicate source instances or binding assignments
  fail immutable Profile construction;
- Crosswalk absence, deployment, namespace, revision, digest, and unselected
  source scope mismatches fail separately;
- an ontology-only Profile remains valid without source instances or a
  Crosswalk;
- the two-source Product reference slice validates one Profile, maps two
  different source keys to one canonical object, and survives SQLite restart;
- lower Ontology packages remain independent of Deployment and Identity.

## Relationship To Earlier Decisions

- This ARD supersedes ARD-008's Profile v1 shape and its separate
  `enabled_binding_ids`. ARD-008 remains historical rationale for exact Schema
  and Adapter artifact locks.
- This ARD implements ARD-009's deferred Profile lock while preserving Product
  ownership of mutable matching and review state.
- ARD-004 and ARD-005 remain authoritative for mapped source cuts, operational
  origins, freshness, and SQLite projection persistence.
- ARD-006 remains authoritative for Product-hosted Adapter execution and
  detached output conformance.

## Deferred

- endpoint and credential provider references;
- activation, rollback, and atomic deployment switching;
- one binding instantiated against multiple source instances;
- mutable or indexed identity providers, matching, review, and authorization;
- incremental Crosswalk activation and source-read coordination;
- recording Profile or Crosswalk identity directly in Projection state;
- multi-package Profile locks, semantic imports, and version resolution;
  ARD-011 later defines only single-Schema artifacts and exact closed-set
  dependency validation.
