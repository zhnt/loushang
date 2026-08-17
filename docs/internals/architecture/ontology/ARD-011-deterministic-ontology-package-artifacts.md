# ARD-011: Deterministic Ontology Package Artifacts

Status: Accepted, 2026-08-10.

## Context

The compiled Ontology Schema already has package ID, namespace, and version,
but it is still consumed as one detached value. The environmental ecosystem
target needs independently delivered domain packages and, later, alignment and
standards knowledge packages. Before adding a registry, version solver, or
multi-package runtime, Loushang needs a deterministic artifact boundary that
can answer two smaller questions:

1. Which exact compiled Schema bytes constitute this package?
2. Which exact package artifacts does it directly require?

Attempting runtime schema merging at the same time would mix artifact closure,
semantic import rules, deployment selection, and materialization behavior.

## Decision

### 1. Add a pure `ontology.package` artifact contract

The package format is:

```text
loushang.ontology.package/v1
```

`OntologyPackageArtifact` contains:

```text
format
package_identity       # complete SchemaIdentity
schema_digest          # canonical compiled-Schema SHA-256
ordered dependencies   # exact direct package locks
compiled_schema        # the complete canonical Schema document
```

The complete artifact has its own content-derived `artifact_digest`. Schema
identity and Schema content digest remain independent coordinates, and both
must match the bundled compiled Schema.

### 2. Make dependencies exact, not speculative constraints

`OntologyPackageDependencyLock` records one complete dependency
`SchemaIdentity` and its whole `artifact_digest`.

The v1 contract deliberately has no version ranges, optional dependencies,
features, exclusions, or conflict-resolution policy. Those require a package
resolver and publication model that do not yet exist. Exact locks are enough to
build and verify immutable local bundles without inventing that system.

`build_ontology_package_artifact(...)` is a pure helper that derives direct
dependency locks from supplied immutable artifacts. Dependency order is
canonicalized by complete package identity.

### 3. Validate a closed set without composing runtime schemas

`validate_ontology_package_set(...)` verifies:

- package IDs are unique in the selected set;
- namespaces are unique across package IDs;
- every direct dependency is present;
- dependency identity and artifact digest match separately;
- dependency edges are acyclic.

It returns artifacts in canonical package-ID order. It does not merge object
types, resolve imports, compile cross-package inheritance or links, or produce
one runtime Schema.

Semantic IDs remain package-local. Equal semantic IDs in two packages are not
a conflict because their globally resolvable identity includes the package
identity. A future import/composition ARD must define how one package refers to
another package's semantic definitions before runtime composition is added.

### 4. Keep package artifacts outside runtime dependencies

```text
ontology.package --------------------> ontology.schema + Foundation JSON

facts / source / identity / projection / query / storage / deployment
                              -X-----> ontology.package
ontology.package              -X-----> registry, filesystem, network, Product
```

Deployment Profile v2 remains a single-Schema selection and does not import
package artifacts. Connecting a package closure to Deployment requires a later
multi-package Profile decision; this ARD does not silently widen ARD-010.

### 5. Reserve, but do not fake, alignment and standards payloads

Environmental domain, mature-ontology alignment, and standards knowledge can
later be distributed as separately identified package artifacts. Their payload
contracts are not equivalent to a compiled operational Schema and are not
represented by an arbitrary generic JSON resource in v1.

Alignment relations, external ontology version references, standard clauses,
applicability, metrics, thresholds, and executable logic remain separate
future contracts. The artifact envelope established here supplies the content
addressing and dependency precedent, not those semantics.

## Consequences

- independently built Schema packages have canonical portable bytes and exact
  dependency evidence;
- same-version content drift changes both Schema and artifact digests;
- missing, changed, duplicated, namespace-conflicting, and cyclic packages fail
  before a registry or runtime is involved;
- package validation can be used by authoring and CI tooling without loading a
  deployment;
- the current single-Schema materializer and SQLite layout remain unchanged.

## Acceptance Gates

- package and dependency values have strict deterministic JSON round trips;
- dependency input order cannot change package JSON or digest;
- bundled Schema identity and content are checked independently;
- missing dependency, identity mismatch, digest mismatch, duplicate package ID,
  namespace conflict, and dependency cycle have stable validation codes;
  duplicate or self-dependency locks fail immutable artifact construction;
- validation performs no registry, filesystem, network, plugin, or deployment
  action;
- architecture gates prevent runtime packages from consuming package artifacts;
- no multi-package Schema merge, version solver, Alignment model, Standards
  model, or environmental content is introduced.

## Relationship To Earlier Decisions

- ARD-003 and ARD-004 remain authoritative for package-local semantic IDs and
  complete Schema identity.
- ARD-008 and ARD-010 remain authoritative for the current single-Schema
  Deployment Profile and artifact selection. Package artifacts are not yet
  deployment locks.
- The proposed Domain Ontology Ecosystem design remains the Target for domain,
  alignment, standards, Adapter, and deployment composition. This ARD
  implements only its first immutable Schema-package artifact primitive.

## Deferred

- package registry, publication, download, signatures, and trust policy;
- semantic version ranges and dependency resolution;
- cross-package semantic references, imports, inheritance, and link endpoints;
- multi-package Schema composition and conflict diagnostics beyond artifact
  identity, namespace, dependency, and cycle checks;
- Deployment Profile package-set locks and activation;
- Alignment Package and Standards Knowledge Package payload schemas;
- OWL/RDF/SHACL/JSON-LD import and export;
- environmental or other industry package content.
