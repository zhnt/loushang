# ARD-006: Product-Hosted Source Adapter Contract

Status: Accepted, 2026-08-10.

[ARD-008](ARD-008-immutable-deployment-profile-and-artifact-locks.md) later
locks exact Adapter manifest content and selects enabled bindings without
moving Adapter execution into Ontology.

## Context

Ontology accepts `SourceBinding`, `MappedSourceInput`, and observable source
heads, but those values alone did not define what a vendor adapter artifact
declares or how an external implementation proves conformance. Embedding a
connector registry or executing vendor code inside Ontology would reverse the
subsystem boundary and prematurely introduce credentials, scheduling, and
transport policy.

## Decision

### 1. Add a serializable manifest, not a registry

`SourceAdapterManifest` v1 declares:

```text
adapter_id + adapter_version
ApplicationSchemaIdentity(application_id, schema_version)
target SchemaIdentity
one or more SourceBinding values
```

Each binding already supplies its binding ID, mapping version, stable authority
targets, target schema identity, and declared coverage. Manifest bindings must
be unique and must all target the manifest schema.

The manifest contains no endpoint, credential, deployment instance, cursor,
secret, or executable loading instruction.

### 2. Keep execution in the Product host

`SourceAdapter` is a structural protocol for implementations hosted by a
Product or deployment composition root:

```text
manifest
read_snapshot(binding_id) -> MappedSourceInput
observe_head(binding_id)  -> SourceInputRevision
```

Ontology does not discover, import, schedule, retry, or execute adapters. The
host invokes its implementation and supplies detached public values to
Ontology.

### 3. Validate detached outputs

`validate_source_adapter_outputs(...)` is the reusable vendor conformance
boundary. For one manifest delivery it requires:

- exactly one mapped input and one observed head for every declared binding;
- no duplicate or unknown binding IDs;
- input and head mapping versions equal the manifest binding;
- input coverage equal the binding's declared coverage.

The source head may be newer than the selected input revision. That difference
is legitimate freshness information, not a conformance failure.

Materialization remains responsible for semantic-ID, authority, value,
endpoint, and whole-snapshot coverage validation. The adapter conformance layer
does not duplicate the ontology compiler or materializer.

## Dependency Direction

```text
Product / vendor adapter ---> ontology.source public contracts
Ontology materializer ------> detached bindings and mapped inputs
Ontology core --------------X Product, vendor package, connector runtime
```

## Acceptance Gates

- manifest and nested bindings have deterministic strict-JSON round trips;
- application schema version and target Ontology schema identity are distinct,
  explicit coordinates;
- a structural vendor fixture passes the public conformance function;
- missing bindings, wrong mapping versions, and coverage mismatch expose stable
  error codes;
- Ontology gains no Product, Harness, registry, scheduler, or credential
  dependency.

## Implementation Evidence

The fixed Product-side fixture in
[`tests/integration/ontology/`](../../../../tests/integration/ontology/)
reads one known SQLite ERP schema and exercises the entire public boundary:
ARD-008 Profile validation, manifest delivery, detached output conformance,
source-plus-Fact-plus-default materialization, SQLite v3 restart, typed query,
and stale source-head observation. It is contract evidence only; it is not a
shipped connector or a generic SQL mapping framework.

## Deferred

- package registry, signatures, dependency solving, and installation;
- async transport conventions, connection pooling, retry, and circuit breaking;
- CDC/change-set contracts and partial coverage merging;
- write-back and Action effects;
- deployment credentials and source-instance identity.
