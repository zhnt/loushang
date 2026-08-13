# ARD-008: Immutable Deployment Profile And Artifact Locks

Status: Superseded by
[ARD-010](ARD-010-deployment-bound-source-instances-and-identity-lock.md),
2026-08-10.

This document preserves the rationale for the first immutable artifact locks.
Its Profile v1 shape, including `enabled_binding_ids`, is no longer implemented
and has no compatibility reader.

## Context

ARD-006 defines detached Product-hosted Adapter contracts, while ARD-005 makes
the resulting projection durable. Until this decision, a Product composition
root still passed a compiled schema, Adapter manifests, bindings, and stores as
an ad hoc set. Nothing recorded which exact artifact contents were selected or
prevented a same-version document from changing underneath a deployment.

A full package registry, installer, secret manager, runtime coordinator, and
deployment switch protocol would be premature. The first requirement is only a
small immutable selection contract that can be validated before Product code
executes adapters or materializes a projection.

## Decision

### 1. Lock identity and content independently

`SchemaArtifactLock` records the complete `SchemaIdentity` and SHA-256 digest of
the canonical compiled-schema JSON.

`SourceAdapterArtifactLock` records Adapter ID, Adapter version, and SHA-256
digest of the canonical `SourceAdapterManifest` JSON.

Version remains a human and compatibility coordinate. The digest proves exact
artifact content. Neither substitutes for the other.

### 2. Keep the Deployment Profile minimal

`DeploymentProfile` v1 contains only:

```text
deployment_id
schema_lock
ordered adapter_locks
ordered enabled_binding_ids
fact_store_ref
projection_store_ref
```

The two store fields are opaque host-owned configuration references. They are
not paths, DSNs, credentials, connection objects, or storage factories.

The profile has strict deterministic JSON and a content-derived
`profile_digest`. Adapter locks and binding IDs are canonicalized by stable ID;
duplicates fail construction.

### 3. Do not add an authority override

State ownership remains declared by the locked compiled schema. Concrete source
authority remains declared by the enabled `SourceBinding` values inside locked
Adapter manifests. The Deployment Profile selects bindings; it cannot rewrite
`StateAuthority`, add source precedence, or create a second merge-policy model.

The materializer remains authoritative for semantic target, ownership,
coverage, mapped-value, and conflict validation.

### 4. Validate detached artifacts without running them

`validate_deployment_profile(...)` receives a profile, one compiled schema, and
detached Adapter manifests. It verifies:

- exact Schema identity and content digest;
- exact Adapter ID set, version, and manifest digest;
- every Adapter manifest targets the locked Schema identity;
- binding IDs are globally unambiguous across selected Adapter manifests;
- every enabled binding exists;
- every locked read Adapter contributes at least one enabled binding.

It returns the enabled immutable `SourceBinding` values in canonical order. It
does not load Adapter code, read source data, resolve storage references, open a
database, or invoke the materializer.

A profile with no Adapter locks and no enabled bindings remains valid. This
allows ontology-owned deployments and does not assert that every source-backed
type in a reusable schema must be active in every deployment.

## Dependency Direction

```text
Product composition root
        |
        +--> ontology.deployment --> ontology.schema
        |                       +--> ontology.source contracts
        |
        +--> concrete Product Adapters
        +--> Fact / Projection stores and materializer

schema / source / facts / projection / query / storage -X-> deployment
ontology.deployment -X-> Product, Harness, runtime, credentials, databases
```

Deployment is a composition contract above Schema and Source contracts. It is
not a runtime dependency of the semantic kernel, materializer, query engine, or
storage adapters.

## Consequences

- A Product can prove exactly which Schema and Adapter manifest bytes it
  selected before reading external state.
- Application and Ontology version coordinates remain visible, while digests
  prevent same-version content drift.
- Deployment profiles contain no secrets and do not become executable plugin
  descriptors.
- The fixed Product-side SQLite ERP reference slice now validates its Profile
  before it reads mapped inputs and materializes a projection.
- Profile validity does not imply that source data is available or semantically
  valid; Adapter conformance and materialization remain separate gates.

## Acceptance Gates

- Profile and nested locks have deterministic strict-JSON round trips;
- Schema identity mismatch and same-identity content mismatch fail separately;
- Adapter set, version, and manifest-content mismatches expose stable codes;
- missing, duplicate, and unused binding selections fail before Product
  execution;
- an empty Adapter selection is representable without inventing a connector;
- architecture gates prevent lower Ontology packages from importing
  `ontology.deployment`;
- the Product-side reference slice validates the Profile and remains green;
- no registry, credential, runtime loading, scheduling, or switching code is
  introduced.

## Deferred

- multi-package Ontology dependency locks and package registries;
- artifact signatures, trust policy, distribution, and installation;
- deployment instance lifecycle, activation, rollback, and atomic switching;
- secret-provider, identity-provider, policy-provider, and source-instance
  references; ARD-009 defines a separately selected immutable identity
  crosswalk but does not add it to Deployment Profile v1;
- cross-deployment isolation and tenant authorization;
- generated API profiles and compatibility reports;
- mutable Identity provider persistence, ambiguity review, and a future
  crosswalk artifact lock;
- Action write-back and reconciliation configuration.
