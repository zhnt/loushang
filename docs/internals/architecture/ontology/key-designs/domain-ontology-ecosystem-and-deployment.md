# Domain Ontology Ecosystem And Multi-Application Deployment

## Status

- ID: `ONT-KD-DOMAIN-ECOSYSTEM`
- Kind: key design
- Scope: `ontology`
- Parent: Loushang
- Authority: normative target proposal
- Design status: proposed
- Implementation status: partial
- Owner: Loushang Ontology
- Current evidence:
  - `src/loushang/ontology/schema/`
  - `src/loushang/ontology/source/`
  - `src/loushang/ontology/identity/`
  - `src/loushang/ontology/package/`
  - `src/loushang/ontology/deployment/`
  - `src/loushang/ontology/projection/`
  - `tests/ontology/`
  - `tests/integration/ontology/`

This document proposes how a domain-neutral Loushang Ontology substrate can
support independently delivered domain ontologies, standards knowledge,
external ontology alignments, vendor application adapters, data warehouses,
and one deployment serving several applications. It uses environmental
information systems as the first concrete validation scenario, but no
environmental type, standard, connector, or policy becomes a dependency of
`loushang.ontology`.

Until this design is accepted, the ontology README and accepted ARDs remain
authoritative. This document separates observed Current facts, the proposed
Target, and the remaining Delta; a target-only name below is not a claim that a
corresponding Python symbol or service already exists.

## 1. Strategy And Outcome

Loushang should be an ontology engineering and operational runtime substrate,
not a bundled environmental ontology and not a replacement database for every
participating application.

The desired outcome is that:

- domain teams can author, validate, version, publish, and evolve environmental
  ontology packages without modifying Loushang;
- standards teams can connect versioned HJ, GB, ASTM, or other requirements to
  stable domain semantics without embedding those standards in the core;
- interoperability teams can align domain terms with mature ontologies such as
  ENVO, ChEBI, SOSA/SSN, PROV-O, GeoSPARQL, or QUDT without importing a large
  OWL reasoning runtime into the operational path;
- different vendors can connect incompatible databases and APIs through
  independently versioned adapters;
- an environmental bureau can install one governed deployment profile that
  serves several applications while preserving source authority, identity,
  time, provenance, policy, and failure boundaries;
- province and city deployments can reuse packages and adapter software while
  isolating credentials, identity state, policy, and operational data.

The governing rule is **shared semantics without forced physical-schema
uniformity**.

## 2. Requirements

Only durable cross-artifact requirements receive IDs here.

| ID | Requirement | Acceptance condition |
| --- | --- | --- |
| `ONT-DOM-FR-001` | Domain neutrality | `loushang.ontology` imports no environmental package, standards package, vendor adapter, or Product implementation; its semantic kernel, materializer, and query path import no external ontology runtime. |
| `ONT-DOM-FR-002` | Independent domain authoring | A domain ontology package can be compiled, diffed, validated, versioned, and published without changing Loushang source. |
| `ONT-DOM-FR-003` | Versioned application integration | An adapter binds a declared application/schema version to stable ontology semantic IDs and produces reproducible mapped source input. |
| `ONT-DOM-FR-004` | Multi-application composition | One deployment profile can select several adapters and materialize their declared partial source views without input-order overwrite. |
| `ONT-DOM-FR-005` | Identity uncertainty | A deployment can map source records to canonical IDs, retain alternate keys, and keep uncertain records separate until an explicit resolution is supplied. |
| `ONT-DOM-FR-006` | Standards and mature-ontology interop | Versioned standards knowledge and external term alignments can refer to domain semantics without replacing internal semantic IDs. |
| `ONT-DOM-FR-007` | Warehouse integration | A warehouse table, view, or query result can enter through the same source contract with explicit coverage, revision, and authority rather than becoming global truth by location alone. |
| `ONT-DOM-QR-001` | Reproducibility and isolation | Installed package locks, source revisions, mappings, identities, policy references, and projection state are explicit enough to reproduce one deployment cut without leaking another deployment's state or credentials. |
| `ONT-DOM-QR-002` | Vendor conformance | Adapter and package conformance can be tested without access to Loushang internals or another vendor's implementation. |

## 3. Current, Target, And Delta

### 3.1 Current facts

The current implementation already provides:

- a compiled schema with package-local stable semantic IDs and explicit
  `StateAuthority` for object existence, properties, and link families;
- immutable `SourceBinding`, `MappedSourceInput`, mapped object/property/link
  snapshots, declared coverage, exact payload-digested input cuts, and
  observable source revision coordinates;
- Fact v2 records and source bindings bound to one complete single-package
  `SchemaIdentity`, with durable assertions resolved by stable semantic ID;
- atomic Fact selection, deterministic multi-source Memory materialization,
  complete operational origins, `MaterializationCut`, and explicit freshness;
- backend-neutral projection reads and source-aware SQLite v3 projection
  persistence with exact input cuts and all operational origin kinds;
- a serializable Product-hosted adapter manifest, a structural adapter
  protocol, and detached-output conformance validation;
- an immutable, deployment-scoped explicit identity crosswalk with complete
  source-record scope, confirmed/unresolved/conflict states, deterministic
  digest, and a read-only resolver;
- fixed Product-side SQLite ERP and maintenance fixtures proving that two
  different source keys can resolve to one object, contribute non-overlapping
  authority, remain input-order independent, and reject ambiguous identity
  without placing connector or identity-provider code in `loushang.ontology`;
- content-addressed revalidation receipts for rebuilding an exact historical
  Fact selection against a compatible newer schema without rewriting Facts;
- an immutable single-Schema Deployment Profile v2 with exact Schema, Adapter,
  source-instance/binding, and optional Crosswalk selection plus opaque store
  references;
- deterministic single-Schema Ontology package artifacts with exact dependency
  locks and pure closed-set validation, without runtime Schema composition;
- architecture gates forbidding Ontology dependencies on Product and execution
  subsystems including Harness, HarnessWork, Method, and Agent; the observed
  source also contains no domain implementation.

These claims are exercised by `tests/ontology/`, especially source
materialization, storage conformance, and import-boundary tests.

### 3.2 Proposed target

The target adds a domain package ecosystem and deployment composition boundary
around the existing semantic and materialization kernel. It introduces
versioned package and adapter artifacts, deployment profile validation,
identity coordination contracts, interoperability metadata, developer tooling,
and source-aware durable projection storage.

The target does not make Ontology execute arbitrary vendor code. A Product or
deployment composition root loads concrete adapters and supplies their public
outputs to Ontology contracts.

### 3.3 Explicit delta

| Capability | Current | Target delta | Classification |
| --- | --- | --- | --- |
| Package identity | Deterministic artifact bundles one compiled Schema and exact direct dependency locks; closed-set validation detects missing/drifted/duplicate/conflicting/cyclic artifacts | Cross-package semantic imports, version constraints/resolver, registry, signatures, Alignment/Standards payloads | partial |
| Source integration | Schema-bound binding, mapped inputs, exact cuts, adapter manifest, application-schema identity, structural protocol, detached-output conformance, and fixed SQLite ERP plus maintenance reference slices | Concrete adapter SDK/packaging and fixtures across independent vendor implementations | partial |
| Identity | Product injects an immutable deployment-scoped crosswalk; only explicit confirmation yields a canonical UUID, ambiguity fails without selection, and Profile v2 locks its exact content and source scope | Mutable indexed provider, alternate keys, matching/review handoff, and activation consistency | partial |
| Deployment composition | Immutable single-Schema Profile v2 locks exact Schema, Adapter manifests, source-instance/binding selections, and optional Crosswalk content | Multi-package locks, provider references, lifecycle, activation and rollback | partial |
| Durable multi-source projection | Memory and SQLite v3 preserve exact source cuts, origins, restart, and backup semantics | Operational-scale and incremental persistence only after measured need | partial |
| Schema upgrade | Schema diff plus exact-selection Fact revalidation receipt; immutable Facts remain bound to their source schema | Package locks, source-input upgrade evidence, and deployment switch/rollback coordination | partial |
| Mature ontology interop | Directional architecture only | External term alignment metadata, validation, import/export bridges | missing |
| Standards integration | Directional architecture only | Versioned standards knowledge packages and later logic bindings | missing |
| Multi-deployment isolation | Not modeled | Isolated deployment state with reusable immutable package binaries | missing |
| Generated consumer surface | Typed Python query values | Stable generated API/SDK/tool surfaces from installed profiles | partial |

This table is the only place in this design that intentionally combines Current
and Target statements.

## 4. Proposed Terminology

These are architecture terms, not promises of current class names.

| Term | Meaning |
| --- | --- |
| Ontology Package | Immutable, versioned semantic definitions and package metadata; contains no deployed credentials or concrete source connection. |
| Domain Ontology Package | An Ontology Package containing domain semantics such as environmental sites, samples, observations, pollutants, risks, or remediation concepts. |
| Alignment Package | Versioned mappings between internal semantic IDs and external ontology terms, including mapping relation and reviewed external version. |
| Standards Knowledge Package | Versioned structured representations of standards editions, clauses, applicability, metrics, thresholds, methods, and evidence requirements. |
| Adapter Package | Independently delivered integration software plus a manifest describing compatible application and ontology versions, mapping version, source bindings, and capabilities. |
| Source View | One application's declared, partial semantic projection; it is not the application's whole database and not the combined Ontology projection. |
| Deployment Profile | An immutable selection and lock of ontology packages, adapter packages, authority bindings, policy references, and deployment-scoped configuration. Secrets are referenced, not embedded. |
| Identity Crosswalk | Deployment state relating source-record identities and alternate keys to canonical ontology object IDs. |
| Deployment | One operational isolation boundary for profile lock, credentials, identity crosswalk, source heads, policy state, Facts, and projections. |

`Workspace`, `HarnessWork`, and `Deployment` are not aliases. This design does
not assign Ontology state or types to HarnessWork.

## 5. Logical System Context

The logical context is defined before transport, process, SDK, or database
choices:

```text
Mature ontology curator -------- external terms and versions --------+
Environmental standards body --- editions and clauses --------------+
Domain ontology developer ------- definitions and mappings ----------+
                                                                   v
                                                       +-----------------------+
                                                       | Ontology authoring,   |
                                                       | validation and compile|
                                                       +-----------------------+
                                                                   |
                                                        versioned packages
                                                                   v
Environmental bureau operator ---- deployment selection ---> Deployment Profile
                                                                   |
Vendor application / warehouse -- Product Adapter -- mapped input -+
Host identity and policy -------- authenticated context -----------+
                                                                   v
                                                       +-----------------------+
                                                       | Loushang Ontology     |
                                                       | operational runtime   |
                                                       +-----------------------+
                                                                   |
                                              typed query / future action contract
                                                                   v
Application developer / regulator / analyst / Agent-enabled Product
```

Logical actors and external systems are not automatically Ontology components.
In particular, a standards body, source database, transport, vendor, identity
provider, or Agent remains outside the black-box boundary unless a later
placement decision assigns a concrete responsibility to Ontology.

## 6. Scope Boundary And Responsibility Split

### 6.1 Ontology owns

- domain-neutral schema, package, mapping, alignment, profile, materialization,
  origin, freshness, query, and later action contracts;
- validation that referenced semantic IDs, package versions, mappings,
  authorities, and source inputs agree;
- deterministic projection and explicit conflict/failure semantics;
- the canonical identity requirements that a mapped object must satisfy;
- import/export contracts for optional standards interoperability;
- conformance rules by which independently implemented packages and adapters
  can be certified;
- generated semantic API shapes derived from a validated installed profile.

### 6.2 Product or deployment composition owns

- selection and loading of concrete vendor adapters;
- database/API credentials, network endpoints, secret providers, and host
  lifecycle;
- application-specific field extraction and source-record identity extraction;
- the deployed identity-crosswalk implementation and human-review workflow;
- synchronization scheduling, retry, operational monitoring, and optional use
  of HarnessWork for durable orchestration;
- binding authenticated actor context and policy-provider decisions;
- presentation and application-specific workflows.

### 6.3 Domain and standards teams own

- environmental concepts, terminology, constraints, examples, and package
  evolution;
- interpretation of mature ontology alignments;
- interpretation and licensed storage of standards content;
- jurisdiction-specific extensions and standard applicability;
- review and publication of machine-executable logic derived from normative
  text.

### 6.4 Ontology must not own

- environmental classes or HJ/GB/ASTM content in `loushang.ontology`;
- vendor SQL, REST clients, credentials, or source-specific retry behavior;
- a bureau's identity matching heuristics or adjudication UI;
- source-system authentication and authorization;
- Product UI, Harness execution, HarnessWork records, or Method assets;
- an automatic claim that similarly named records are the same entity;
- a generic write-through path that bypasses declared StateAuthority.

## 7. Artifact Model

The unit of ecosystem delivery is:

```text
Ontology Package(s) + Adapter Package(s) + Deployment Profile
```

### 7.1 Ontology packages

An Ontology Package should carry stable package identity, version, namespace,
semantic definitions, dependency constraints, compatibility metadata, and
optional alignment or standards resources. It contains no deployment secrets
and cannot import a Product implementation.

The accepted first artifact slice in
[ARD-011](../ARD-011-deterministic-ontology-package-artifacts.md) bundles one
compiled Schema with exact direct dependency locks and validates a closed set.
It does not yet implement dependency constraints, cross-package semantic
imports, registry metadata, multi-Schema runtime composition, or the distinct
Alignment and Standards payload contracts described below.

Domain-specific package layers remain outside Loushang. An environmental
distribution can use:

```text
L0 alignment packages
   env-alignment-envo
   env-alignment-chebi
   env-alignment-sosa
   env-alignment-geosparql

L1 environmental core packages
   env-core
   env-soil-contamination
   env-water-monitoring

L2 standards knowledge packages
   env-standard-hj-<standard>-<edition>
   env-standard-gb-<standard>-<edition>
   env-standard-astm-<standard>-<edition>

Jurisdiction and organization extensions
   env-cn-<province>-extension
   env-org-<bureau>-extension
```

L0 is alignment, not bulk runtime inheritance. Internal semantic IDs remain
canonical. An alignment records external namespace, term IRI, version, review
provenance, and a relation such as exact, broader, narrower, or related. It
does not infer `owl:sameAs` from a matching label.

L1 is stable operational domain language. Standards editions should not force
core objects such as Site, Sample, Observation, Receptor, RiskAssessment, or
RemediationPlan to change identity when a standard changes.

L2 separates normative source, structured requirement, executable logic, and
evaluation evidence:

```text
StandardEdition -> Clause -> Structured Requirement
                                  |
                         versioned LogicBinding
                                  |
                 Assessment / ComplianceFinding
```

Executable logic remains target-only until a computation-origin contract is
accepted. Copyrighted standards text is stored only under an appropriate
license; packages may retain citations and structured semantics without
copying unlicensed full text.

### 7.2 Adapter packages

An Adapter Package should declare at least:

```text
adapter identity and version
supported source application/schema versions
supported ontology package/version constraints
mapping version
provided source bindings
read capabilities
optional future write capabilities
conformance fixtures
```

An application upgrade produces a new adapter or mapping version. It does not
silently mutate an installed mapping and does not require a rename of stable
domain semantics.

The accepted initial read contract is deliberately narrow:
`SourceAdapterManifest` declares the application schema, target Ontology schema,
and source bindings; a Product-hosted structural adapter produces reproducible
`MappedSourceInput` values and observable source heads; and Ontology validates
the detached outputs. A connector registry, CDC engine, scheduler, arbitrary
transformation DSL, and generic write-back are not implied by the Adapter
Package concept.

### 7.3 Deployment profiles

A Deployment Profile selects exact compatible artifacts and declares the
composition boundary:

```text
ontology package lock
adapter package lock
source-binding and StateAuthority assignments
identity-provider reference and namespace
policy-provider references
projection storage configuration
source-head observation configuration
generated API profile
```

Credentials and raw secret values stay in the host secret system. A profile
refers to them by deployment-owned identifiers.

The accepted current slice in
[ARD-010](../ARD-010-deployment-bound-source-instances-and-identity-lock.md) is
narrower than this Target: Profile v2 locks one compiled Schema, exact Adapter
manifest contents, concrete source-instance/binding selections, an optional
Crosswalk, and opaque Fact/Projection store references. It does not yet model
multi-package selection, endpoint/credential providers, generated API profiles,
lifecycle, activation, or rollback. ARD-008 preserves the superseded v1
rationale only.

## 8. Data-Island Mechanics

Data islands combine at least five independent problems. Treating all five as
"field mapping" would hide the hard contracts.

| Difference | Owning mechanism | Required failure behavior |
| --- | --- | --- |
| Semantic names and structures | Stable semantic IDs and versioned source mappings | Unknown or incompatible targets fail validation. |
| Record identity | Source identity extraction plus deployment Identity Crosswalk | Uncertain matches remain separate; ambiguous merges require explicit resolution. |
| Time and refresh cadence | Source revisions, MaterializationCut, and freshness | Missing heads are unknown; changed heads make the installed cut stale. |
| State ownership | StateAuthority and concrete source bindings | Duplicate ownership or unconfigured overlap fails rather than using adapter order. |
| Trust and visibility | Host IAM plus explicit policy contracts | Missing authenticated/policy context cannot become implicit broad access. |

Ontology combines partial Source Views; it does not require one source to
provide a complete environmental object. For example:

```text
registry or permit system -> enterprise identity and permit status
monitoring platform       -> observations and measurement results
GIS                       -> parcel geometry and spatial relations
warehouse                 -> declared historical metrics
Ontology FactStore        -> ontology-owned review notes
published logic           -> derived risk or compliance result
```

Each object existence, property, and link family has one declared primary
authority or an explicit merge policy. A later-connected warehouse does not
override an operational source merely because it presents a wider table.

## 9. Identity Coordination

Field mapping cannot solve cross-system identity. The target interaction is:

```text
binding ID + source record identity + alternate keys
                         |
                         v
             deployment Identity Crosswalk
                         |
         +---------------+----------------+
         |                                |
 resolved canonical ID          unresolved / ambiguous candidate
         |                                |
         v                                v
MappedSourceObject             separate objects + review handoff
```

The Product Adapter owns extraction of source keys. The deployment identity
provider owns mutable crosswalk and review state. Ontology owns validation that
materialized canonical IDs and origin references are explicit and deterministic
for the selected cut.

The accepted identity-value slice in
[ARD-009](../ARD-009-explicit-identity-crosswalk-snapshots.md) is intentionally
narrower than this Target. It defines an immutable explicit provider-output
snapshot, a read-only resolver, and confirmed/unresolved/conflict failure
semantics. It does not implement matching, alternate keys, persistence, or
review. ARD-010 now locks the selected Crosswalk in Profile v2 and validates its
source scope; Product still retains the Profile and Crosswalk alongside the
`MaterializationCut`, which locks resolved mapped payloads but does not duplicate
their deployment coordinates.

An environmental company name, address, or similar label is evidence, not an
automatic identity key. Cross-bureau federation must not reuse one identity
namespace without an accepted policy and reconciliation design.

## 10. Warehouse Integration

A data warehouse is one Source View provider. It can map tables, views, or
query results and use a partition, batch, snapshot, or watermark as its source
revision. It is not automatically authoritative for every copied field.

The first warehouse contract should be read-only and full-snapshot based. A
later change-set contract must retain a reproducible base-revision chain; it
cannot present an unanchored delta as a complete mapped input. SQL pushdown,
CDC, and distributed materialization remain separate optimizations.

## 11. Target Physical Context, Composition, And Deployment Isolation

No transport or process topology is accepted yet. The target physical context
must nevertheless keep these carriers distinct:

- immutable package artifacts live in an artifact registry or deployment
  bundle;
- a deployment host owns Product composition, adapter loading or remote
  clients, credentials, identity and policy bindings;
- `loushang.ontology` remains a domain-neutral library/runtime behind public
  contracts;
- deployment-scoped Fact and projection stores persist operational state;
- Channel or Product APIs expose generated contracts to consumers.

An adapter may run in the deployment host or behind a process/network boundary.
That transport variation does not change the Ontology source contract. The
proposed composition relationship preserves the dependency direction:

```text
immutable domain/alignment/standards package artifacts
                          |
                          v
                deployment composition root
                  |          |          |
             loads/binds  configures  provides
                  |          |          |
            vendor adapter  identity   policy/actor context
                  |          |          |
                  +----------+----------+
                             |
                    public Ontology contracts
                             |
                             v
       compiled profile -> materializer -> durable projection -> query/API
```

For one bureau, a deployment can bind several applications into one governed
projection. When a province hosts several city bureaus, immutable package and
adapter binaries may be shared, but each deployment normally isolates:

- exact profile lock;
- credentials and network access;
- identity crosswalk and namespace;
- source heads and materialization cuts;
- Facts and projection stores;
- policy bindings and audit records.

Province-city data exchange is federation or export between deployments, not
an accidental global graph. Its protocol, policy, and identity reconciliation
require a separate design.

## 12. Critical Interactions

Composition, runtime interaction, and static dependency are separate views.
Section 11 describes composition; this section describes temporal interaction;
Section 15 declares intended dependencies.

### 12.1 Install and compile a deployment profile

```text
Bureau operator -> deployment composition: select exact package/adapter versions
deployment composition -> profile compiler: validate dependencies and authority
profile compiler -> package compiler: compile selected semantic definitions
profile compiler -> deployment composition: immutable profile lock or diagnostics
deployment composition -> adapter host: bind approved adapters and secret references
deployment composition -> Ontology runtime: install compiled profile and empty state
```

An incompatible dependency, unknown semantic target, ambiguous ownership, or
missing required binding fails before a source is read. Profile compilation
does not load arbitrary vendor code or resolve secrets.

### 12.2 Observe, map, and materialize source state

```text
adapter host -> source application: read selected snapshot/revision
adapter host -> identity provider: resolve source keys or record ambiguity
adapter host -> Ontology runtime: submit SourceBinding + MappedSourceInput
Ontology runtime -> materializer: combine immutable source inputs + FactSelection
materializer -> projection store: atomically replace one complete snapshot
Ontology runtime -> consumer: expose new projection version and freshness
```

If identity remains ambiguous, the adapter submits separate canonical objects
or withholds the disputed mapping according to the accepted identity contract;
it must not silently merge records. A mapping, authority, endpoint, or origin
failure rejects the complete materialization. It does not partially install a
projection or rewrite an earlier materialization cut.

### 12.3 Refresh and stale observation

```text
adapter host -> source application: observe source head
adapter host -> Ontology runtime: report binding/mapping/source revision
Ontology runtime -> freshness evaluator: compare observed vector with installed cut
freshness evaluator -> consumer/operator: current / stale / unknown / degraded
```

Observation of a new source head does not mutate the installed snapshot.
Rebuild and replacement are separate explicit interactions.

## 13. Developer Experience And Conformance

The target supports three developer roles:

1. A domain author creates ontology, alignment, or standards packages.
2. An integration developer creates an Adapter Package for an application or
   warehouse version.
3. An application developer consumes generated query, SDK, tool, and later
   action contracts without importing materializer or storage internals.

A useful authoring and integration toolchain should eventually provide:

- package and adapter scaffolding;
- schema and dependency validation;
- source metadata inspection and sample-data mapping preview;
- coverage, unit, code-list, identity, authority, and conflict diagnostics;
- generated typed SDK/API shapes;
- deterministic test fixtures and conformance suites;
- package/profile diff and compatibility reports;
- publishing and immutable version locks.

LLM-assisted mapping may suggest drafts, but publication requires deterministic
validation and review. A graphical Studio is optional presentation over these
contracts, not the first required runtime component.

## 14. Candidate Responsibility Map

The following are candidate direct capability groups for the Target. Their
final promotion to components or nested scopes requires a component-design
review; they are not current source-package claims.

| Candidate capability | Primary responsibility | Collaborators | Explicit non-ownership |
| --- | --- | --- | --- |
| Authoring and Package Toolchain | Draft, validate, diff, compile and publish domain-neutral packages | Domain authors, artifact registry | Domain content ownership, credentials |
| Package and Profile Compiler | Resolve compatible immutable package/adapter locks and authority bindings | Deployment composition | Loading arbitrary vendor code, secrets |
| Mapping and Adapter Contracts | Describe mapping compatibility, mapped inputs, source heads and conformance | Product adapters | SQL/API implementation, scheduling |
| Identity Coordination Contract | Define canonical-ID input and ambiguity handoff | Product adapter, deployment identity provider | Matching heuristics, review UI |
| Materialization Runtime | Deterministically combine schema, source inputs and Facts with exact origins and cuts | Projection storage | Source extraction, UI workflows |
| Interoperability Bridges | Validate alignments and import/export domain artifacts | Alignment/standards package authors | Making an OWL reasoner the operational core |
| Generated Consumer Surface | Produce stable query/SDK/tool shapes from an installed profile | Product/Channel | Product presentation and actor authentication |

## 15. Intended And Forbidden Dependencies

```text
domain ontology package ------uses-contract------> ontology package contracts
alignment/standards package --uses-contract------> ontology interop contracts
vendor adapter ---------------uses-contract------> ontology source contracts
deployment composition -------binds--------------> packages + adapters + stores
consumer application ---------uses---------------> generated/query contracts

ontology -X-> environmental packages
ontology -X-> mature ontology runtime libraries by default
ontology -X-> vendor adapters and Product implementations
ontology -X-> source databases, credentials and IAM implementations
ontology -X-> Harness / HarnessWork / Method / Agent
```

Optional export tooling may depend on a standards serialization library behind
an interoperability adapter. That does not authorize the semantic kernel,
materializer, or query engine to depend on the external ontology runtime.

## 16. Critical Validation Scenarios

This proposed design is not implementation-ready until separate delivery plans
can validate at least these scenarios:

1. Two vendor applications with incompatible schemas map partial views of one
   environmental domain package through independently versioned adapters.
2. One confidently shared source identity resolves to one canonical object;
   one ambiguous match remains separate and produces a review handoff.
3. Overlapping property or link authority fails unless the deployment profile
   declares a primary source or supported merge policy.
4. A warehouse contributes a declared historical metric without taking
   authority over copied operational fields.
5. One internal term carries a reviewed mature-ontology alignment while its
   internal semantic ID remains stable across an external version change.
6. One standards edition and clause refer to L1 environmental semantics and
   are superseded without rewriting historical assessment provenance.
7. A restart restores the exact multi-source cut and all origins from durable
   storage.
8. An application upgrade selects a new adapter/mapping version without
   silently changing an installed historical profile.
9. Two bureau deployments reuse package binaries but cannot observe each
   other's credentials, identity crosswalk, Facts, or projections.

## 17. Traceability

| Requirement | Proposed owner/capability | Primary contract or validation |
| --- | --- | --- |
| `ONT-DOM-FR-001` | Ontology scope boundary | Import-boundary architecture gate |
| `ONT-DOM-FR-002` | Authoring and Package Toolchain | Package compile/diff/publish conformance |
| `ONT-DOM-FR-003` | Mapping and Adapter Contracts | Adapter manifest and mapped-input conformance |
| `ONT-DOM-FR-004` | Package/Profile Compiler + Materialization Runtime | Multi-adapter profile scenario and conflict tests |
| `ONT-DOM-FR-005` | Identity Coordination Contract | Resolved and ambiguous identity scenarios |
| `ONT-DOM-FR-006` | Interoperability Bridges | Alignment and standards-version fixtures |
| `ONT-DOM-FR-007` | Mapping and Adapter Contracts | Read-only warehouse adapter fixture |
| `ONT-DOM-QR-001` | Deployment composition + durable stores | Restart, lock, cut, origin and isolation tests |
| `ONT-DOM-QR-002` | Authoring/Adapter conformance toolchain | Third-party package and adapter conformance suite |

Detailed code and test links belong in the traceability document created when
these Target capabilities receive an accepted component model. This proposal
must not claim future validation as current evidence.

## 18. Non-Goals And Deferred Decisions

- No environmental ontology package is implemented by this design change.
- No HJ, GB, ASTM, ENVO, ChEBI, SOSA, PROV-O, GeoSPARQL, or QUDT dependency is
  added to `loushang.ontology`.
- No national, province-wide, or city-wide universal physical database schema
  is prescribed.
- Existing vendor applications are not required to rewrite their databases.
- No source is made authoritative merely because it is a data warehouse.
- No automatic entity resolution or label-based merge is accepted.
- No unanchored change set, CDC engine, connector registry, scheduler, or
  distributed materializer is introduced.
- This Target design does not decide generic Action write-back, overlay, saga,
  reconciliation, or federation. ARD-012 separately accepts only a narrow
  single-authority `SetProperty` planning and Product-hosted write-back boundary.
- No multi-tenant security model is inferred from deployment isolation; policy
  and federation require their own requirements and decisions.
- No OWL reasoner becomes the operational query or action runtime.

## 19. Decision And Reading Relationships

- [ARD-003](../ARD-003-declared-state-authority-and-multi-source-materialization.md)
  controls declared state authority, mapped source inputs, origins,
  materialization cuts, and current deferred write-back semantics.
- [ARD-004](../ARD-004-schema-identity-semantic-references-and-source-input-cuts.md)
  controls single-package schema identity, stable Fact predicates, source
  coverage, exact mapped-payload cuts, and the separation between installed
  cuts and observable source heads.
- [ARD-005](../ARD-005-source-aware-sqlite-v3.md) controls durable source cuts,
  operational origins, and the one supported SQLite physical format.
- [ARD-006](../ARD-006-product-hosted-source-adapter-contract.md) controls the
  Product-hosted adapter manifest, structural protocol, and detached-output
  conformance boundary.
- [ARD-007](../ARD-007-fact-schema-revalidation-receipts.md) controls exact
  Fact-selection revalidation and the evidence required to build a target
  projection without mutating historical Facts.
- [ARD-008](../ARD-008-immutable-deployment-profile-and-artifact-locks.md)
  preserves the historical Profile v1 artifact-lock rationale; its Profile
  shape is superseded by ARD-010.
- [ARD-009](../ARD-009-explicit-identity-crosswalk-snapshots.md) controls the
  accepted immutable explicit-crosswalk contract, complete source-record scope,
  and the rule that ambiguity cannot produce a canonical ID.
- [ARD-010](../ARD-010-deployment-bound-source-instances-and-identity-lock.md)
  controls Profile v2 source-instance/binding selection, exact Crosswalk lock,
  and pure deployment compatibility validation.
- [ARD-011](../ARD-011-deterministic-ontology-package-artifacts.md) controls the
  accepted single-Schema package artifact and exact closed-set dependency
  validation boundary.
- [ARD-012](../ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md)
  controls the accepted single-authority Action planning, guarded Fact commit,
  Product-hosted source write, acknowledgement, and reconciliation boundary;
  its implementation has not started.
- [Ontology Architecture README](../README.md) controls Current implementation
  status and the accepted reading order.
- [Operational Infrastructure Draft](../drafts/loushang-ontology-operational-infrastructure.md)
  contains the broader research synthesis and environmental reference notes;
  it is not a substitute for this scoped Target design.
- A later package/profile decision must define cross-package semantic imports,
  version resolution, multi-package deployment locks, and runtime composition.
- ARD-012 now defines the first source-effect, acknowledgement, idempotency, and
  reconciliation boundary. Cross-authority Actions remain deferred.
