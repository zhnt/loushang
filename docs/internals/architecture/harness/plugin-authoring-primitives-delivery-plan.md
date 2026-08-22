# Unified Plugin Authoring Primitives Delivery Plan

## Status

- Authority: implementation plan under the accepted Harness and Product owner
  boundaries; it does not amend those boundaries.
- Baseline: `harness/plugin-resolve-once` after the implemented UPA1 resolve-once
  chain and the first inert UPA2 `capability_provider` preflight/finalize slice.
- Delivery status: PAP0/PLC0 is implemented locally at `25cfc170` and the inert
  PAP1/PLC1A authoring slice is implemented at `2ebac237` and review-hardened at
  `8a3c94fd`; see the [PLC1A baseline](plugin-lifecycle-plc1a-baseline.md).
  PAP1B/PLC1B is implemented through its inert `coding.base` shadow proof on
  the current delivery branch. No public Plugin SDK, executable Plugin
  Definition evaluator, Capability owner admission bridge, or Plugin-sourced
  Capability bind is claimed as implemented by this document.
- Review status: self-reviewed in
  [Plugin Authoring Primitives Plan Review](plugin-authoring-primitives-plan-review.md).
  The implemented source-changing slice remains local and still requires an
  independent review against the source tree and executable gates before PR
  publication.

This plan specializes the broader
[Unified Plugin Architecture](unified-plugin-architecture.md). The accepted
[PLC1B Contract](plugin-declaration-foundation-plc1b-contract.md) freezes the
exact source/index/declaration/document/approval/evidence records, fingerprint
layers, attempt identity and aggregate state required by PAP1B. The accepted
[Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md),
[Capability Composition Lifecycle Authority Plan](composition-lifecycle-authority-plan.md),
and [Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md)
remain authoritative wherever this plan is silent or ambiguous.

## Decision

The next development priority is a small, owner-preserving Definition / Provider
/ Consumer authoring path, followed by one executable production Capability
slice. Consolidating Skill loading is a subsequent adopter of the same provider
and resource principles; it must not define a Skill-only Plugin runtime first.

The delivery order is:

```text
freeze existing semantic types and authority sinks
  -> add an internal data-only authoring builder and typed payload codec
  -> version document/in-process declaration sources and add strict Resource,
     Tool-pack, and Command-pack declaration codecs
  -> prove those codecs with an inert coding.base shadow declaration
  -> add minimum durable Plugin lifecycle and management control
  -> add durable Approval-owner execution-decision consumption
  -> evaluate one verified Plugin Definition into frozen declaration IR
  -> add Capability-owner eligibility/final admission and Product selection
  -> resolve one approved binding spec through a narrow Component Host
  -> bind through the existing Session Graph Binder
  -> prove the path with a conformance fixture and coding.lsp production slice
  -> stabilize and publish the author SDK
  -> converge Skill discovery/loading on a provider-neutral catalog
```

`coding.base` is not the first executable Capability proof. It contributes
mostly Resource, Tool-pack, and Command-pack content and therefore cannot prove
top-level Provider selection, Graph construction, Consumer facet capture, or
Capability owner disposal. A synthetic conformance fixture proves the narrow
mechanics, then `coding.lsp` is the first production Definition / Provider /
Consumer vertical slice. `coding.base` follows through Resource-owned
contribution kinds after those kinds exist.

## Desired Author Experience

An ordinary Provider author should declare data, not orchestrate a runtime:

```python
from loushang.plugin import (
    capability_provider,
    capability_requirement,
    plugin_definition,
)


@plugin_definition
def declare(plugin):
    workspace = capability_requirement(
        capability="harness.workspace",
        facets=("read", "process.launch"),
        contract=1,
    )
    plugin.add(
        capability_provider(
            contribution_id="coding-lsp-default",
            capability="coding.lsp",
            provider_id="org.loushang.coding-lsp/default",
            implementation_version=1,
            contract=1,
            facets=("semantic", "tool-runtime", "diagnostics"),
            requirements=(workspace,),
            factory="provider.py:create_provider",
            disposer="provider.py:dispose_provider",
        )
    )
```

This is the target public shape, not the first implementation API. Until the
declaration IR, feature negotiation, and two implementation fixtures are stable,
the equivalent builder remains an explicitly internal SPI. The first SPI uses
ordinary functions and exact locator strings; decorators add no authority and
may be deferred without blocking the runtime path.

The author never receives or constructs:

- `RuntimeCapabilityGraphRuntime`, Planner, Binder, or Projector;
- `RegistrationScope` or a foreign registration disposer;
- a global registry, Plugin context, Product Session, or credential bag;
- a live Capability Provider during declaration;
- an import path outside the verified package revision; or
- an owner admission or approval record it can forge.

At live construction time the existing `CapabilityProviderContext` supplies
only declared dependency facets and the Binder-owned
`CapabilityRegistrationCollector`. Product consumers continue to receive a
declared `CapabilityFacetSet` or focused typed wrapper, not a Plugin object.

## Source-Backed Baseline

The following implemented types are reused rather than wrapped by semantic
duplicates:

| Concern | Existing authoritative type/path | Plan treatment |
| --- | --- | --- |
| Capability contract | `CapabilityDefinition` | Retain. Definition publication stays with the Product/Capability owner. |
| Provider metadata | `CapabilityBundleProvider` | Retain. Decode declaration payload into this exact type. |
| Consumer dependency | `CapabilityRequirement` | Retain. Authoring helpers construct this exact type. |
| Live Provider input | `CapabilityProviderContext` | Retain. Do not introduce `PluginContext`. |
| Live Bundle value | `CapabilityBundleValue` and `CapabilityFacetBinding` | Retain. Factory return validation stays in the Graph Binder path. |
| Provider factory/disposer | `CapabilityBundleProviderBinding` | Retain as the Binder input; add provenance outside it until an accepted type revision says otherwise. |
| Graph plan/publication | `RuntimeCapabilityGraphPlan` / `RuntimeCapabilityGraphBinder` | Retain as sole plan validator and publisher. |
| Reversible effects | `RegistrationScope` / `RegistrationLease` | Retain with the Capability generation as owner. |
| Package identity | `PublishedPluginPackage` / `VerifiedRevisionHandle` | Retain. Component Hosts never reopen the mutable source. |
| Inert reservation/declaration | `PluginContributionReservation` / `PluginDeclaration` | Evolve only through strict versioned codecs; PLC1B advances the unpublished draft to runtime-only v2 rather than adding a second IR. |
| Inert selection | `PluginSelectionResolver` | Retain preflight/finalize; it never performs owner admission or binding. |

PAP1 now provides the typed `capability_provider` payload codec and
reservation-bound internal builder. PLC1B/PAP1B must next complete the inert
declaration vocabulary before executable lifecycle work. The current source
still does not provide:

- a versioned document/in-process declaration-source union, source grouping,
  evidence and single-finalization coordinator;
- strict `resource_item`, `tool_pack`, and `command_pack` declaration arms;
- a constrained `PluginDefinition` builder/evaluator;
- durable, consumable Approval-owner Plugin execution decisions;
- Capability-owner eligibility and final admission records;
- Product selection of a complete owner-admitted Provider closure;
- a Component Host that resolves a selected binding spec from the same verified
  revision; or
- a Session composition input for Plugin-selected top-level Providers and
  matching bindings.

Those are the exact scope of the foundation slices below.

### Known baseline gate

At plan-writing time, the architecture suite had three failures on the
`harness/plugin-resolve-once` source baseline. PAP0/PLC0 closed them at
`25cfc170`: the stale document phrase now targets the accepted invariant, the
duplicate `plugin.json` locator was removed from revision projection, and exact
verified-revision/Package-mount read functions received qualified owners. The
[PLC0 baseline](plugin-lifecycle-plc0-baseline.md) records the inventory and
green gates. PAP1 must preserve that baseline and may not broaden the qualified
owner inventory.

## Canonical Role Model

### Definition

`CapabilityDefinition` is published by the Product or Capability namespace
owner. An ordinary third-party Plugin may reference a compatible Definition but
cannot declare ownership of `coding.*`, `harness.*`, or another Product's
namespace. A future delegated Definition contribution requires a separate
owner-grant design and is out of scope here.

### Provider

A Plugin contributes one inert `capability_provider` declaration. Its payload
normalizes to:

```text
CapabilityBundleProvider metadata
Capability Provider factory locator
required nullable disposer locator
normalized non-secret binding inputs
reservation/group/declaration/dependency fingerprints attached by Host stages
requested authorities
```

The declaration is only a candidate. The Capability owner issues eligibility,
then final admission after Product/OEM normalization. Product selection chooses
only among owner-admitted candidates. The Graph Planner validates the resulting
closed Provider set; it does not select from alternatives.

### Consumer

There are two Consumer forms and no third ambient lookup path:

1. a Provider declares `CapabilityRequirement` values and receives the matching
   narrow dependency bindings through `CapabilityProviderContext`; and
2. a Product runtime declares its required facets and captures a
   generation-scoped `CapabilityFacetSet` or focused typed wrapper after Graph
   publication.

A Tool or higher-level capability such as `coding.arch` consumes a typed facet.
It never looks up a Provider by Plugin ID or reaches through a global service
container.

## New Internal Records And Services

Names below are implementation targets. They may be adjusted for package
cohesion, but their semantics and ownership must not be merged.

### Data-only declaration layer

- `PluginDeclarationSource`: strict versioned `document`/`in_process` union
  that replaces the current peer `entrypoint` and `executionModel` reservation
  fields. Its revision-independent `sourceDescriptorFingerprint` may appear in
  package bytes without a hash fixed point. All source and Resource
  locators are revision-root-relative and are opened only through
  `VerifiedRevisionHandle`; `packageRoot` never creates a second locator base.
- `PluginPreflightProposal`: non-authoritative recomputed Product/scope/policy/
  trust context plus the complete canonical tuple of source proposals. It has no
  identity usable by finalization and is never stored for resume.
- `PluginPreflightContextV1` and `PluginInstanceRevisionRef`: pure Product-
  supplied identity facts frozen by PLC1B. PLC1B validates but never invents or
  persists them; PLC2 later owns their durable lifecycle without redefining
  their fields or fingerprint.
- `PluginDeclarationSourceProposal`: non-authoritative preflight value over one
  package revision and `sourceDescriptorFingerprint`, complete proposed index
  closure, its closure-local projection from the Plan-wide effective
  configuration set, authority ceiling and strict
  `data_only`/`execution_subject(subject)` source disposition. It is never a
  group, gate, reservation or active token.
- `PluginDeclarationSourceGroup`: one package/revision,
  `sourceDescriptorFingerprint`, Host-computed `sourceGroupFingerprint` and
  attempt-specific `sourceGroupId`,
  Product/scope/policy context, one owned `PluginDeclarationGate`, sorted
  reservation closure, and
  canonical group-configuration fingerprint over the per-reservation map. A
  reservation belongs to exactly one group; the same source descriptor cannot
  be split across multiple groups in one preflight. If any
  contribution from a source is selected, the closure contains every index
  entry for that source; later Product selection may emit only its selected
  candidate subset.
  The Plan set covers the union of all proposed closures, but each group hashes
  only its own complete projection; changing a disjoint group's configuration
  cannot change this group's fingerprint, Subject, or approval lookup key.
- `PluginDeclarationGate`: strict `data_only`/`execution_preflight` union over
  a source group's shared package/contribution/source/context facts. Only the
  executable arm carries one positive group-level
  `PluginExecutionApprovalSubject` and decision reference; pending/denied
  outcomes produce no accepted preflight token, reservation, or group. The
  group is its only structural owner; reservations carry only its immutable
  ID/fingerprint and never copy subject/decision/gate facts.
- `PluginPreflightOutcome`: strict `accepted`/`pending_approval`/`denied`/
  `rejected` union. Only `accepted` carries an active token and source groups;
  pending may expose canonical proposed subjects, and every non-accepted arm
  carries diagnostics but no reservation, gate, or finalizable preflight.
- `PluginPreflightAggregateState`: strict `ACTIVE_OPEN`/`CLOSING_ABORT`/
  `CLOSING_EXPIRE`/`FINALIZED`/`ABORTED`/`EXPIRED` state. The Coordinator alone
  drives the Resolver's private CAS port.
  Each group is `PENDING -> CLAIMED -> COMPLETED|FAILED`; closing stops new
  claims/start permits, requests cancellation and waits for each worker to
  settle its own lease before one terminal. Tokens bind `preflightUseId`, the
  same `hostBootId`/local `hostEpoch`, and monotonic deadline. Repeated/
  concurrent terminal calls return one typed error and never replay candidates
  or evidence.
- `PluginDeclarationDocument`: strict document-envelope v1 containing one or
  more source-local v2 declarations. It carries no Product/scope/group/
  approval facts; the coordinator matches its complete declaration identity
  set to the dynamically preflighted source-group closure.
- `PluginDeclarationEvidence`: strict `document_decoded`/
  `in_process_evaluated` union. The first binds verified document bytes/schema
  and both bind the accepted attempt, source group and closure. The second adds
  a durable execution consumption receipt and cannot be constructed in PLC1B.
- `PluginDeclarationBatch`: exact group declarations plus source-appropriate
  Host-attached evidence; a Definition or Builder cannot construct one, and a
  positive but unconsumed execution decision cannot form one.
- `PluginDeclarationCoordinator`: partitions one accepted preflight by exact
  source descriptor/group identity, decodes or evaluates each group once, rejects
  overlapping/extra/missing declarations, joins all completed batches, and
  calls selection finalization once. It exclusively owns the active token and
  aborts it exactly once on failure, cancellation, missing evidence or finalize
  rejection.
- `PluginContributionSemanticFingerprint`: compiler-owned v1 diagnostic over
  SHA-256 of the existing strict canonical-JSON encoding of domain separator,
  kind, owner, owner-qualified payload-schema ID/version, identity-sorted pinned
  catalog revisions, and pre-owner/pre-Host-normalization payload. It grants no
  identity, selection, approval, compatibility, or admission authority; the
  architecture document freezes the exact logical record and empty-list rules.
- `PluginSymbolReference` v2: contained relative module/file locator, symbol,
  version, and contributed-runtime execution model. It is serializable, never
  carries a callable or package digest, and is not the declaration source. The
  Host binds it to the published package digest only in resolved views.
- `CapabilityProviderDeclarationPayload` v2: strict codec containing
  `CapabilityBundleProvider` data, required factory, required nullable disposer,
  and package-default non-secret binding inputs exact-matched to the Index. It
  has no package-digest or configuration-fingerprint peer; reservation/group
  identities bind package-default/Product-effective configuration separately.
- `PluginDeclarationBuilder`: source-group-bound builder that can emit exactly
  one matching declaration per reservation in that group, rejects a different
  source/gate or overlapping closure, and freezes after `build()`.
- `PluginDefinition`: internal Protocol whose `declare()` returns one frozen
  `tuple[PluginDeclaration, ...]` for its group via the builder. It receives no
  registries or live services and cannot create evidence or a Batch.

### Approval and evaluation layer

- `PluginExecutionDecisionPort`: Approval-owner port for issue/query/consume/
  revoke of digest-bound execution decisions. It is implemented under
  `harness.approval`, not under the Plugin package.
- `PluginExecutionConsumptionReceipt`: immutable evidence binding the canonical
  group subject, decision, complete reservation closure, policy/source-trust
  revisions, revocation epoch, expiry, instance revision, `preflightUseId`,
  `sourceGroupId`, unique `executionUseId`, and one evaluated transition.
- `PluginExecutionApprovalSubject` v2: one group-level subject replacing the
  draft v1 per-contribution schema. `PluginExecutionDecisionRecord` also becomes
  a strict v2 Approval-owner selection view with independent
  `decisionRecordVersion: 2` and `subjectSchemaVersion: 2`. Old subject and
  unversioned decision shapes fail their separate exact unsupported-version
  diagnostics and are never reinterpreted.
- `ContributionActivationApprovalSubject`: independent complete activation
  subject over admitted candidate, package/dependency/source trust, contributed
  runtime/factory/service locators, configuration, Product/owner/scope/instance,
  requested/effective grants and revocation facts. It never depends on a
  declaration execution subject that a document source does not have.
- `PluginDefinitionEvaluator`: verifies the published revision handle and
  dependency lock, consumes the decision, enters the import-realm gate, loads
  the exact definition entrypoint, invokes only the declaration builder, and
  validates the returned IR. It cannot bind a contribution.

### Owner admission and Product selection layer

- `PluginContributionCandidate`: removes the current unconditional
  `decision_id` and carries source-group identity plus strict
  `PluginDeclarationEvidence` copied exactly from its validated Batch. Document
  evidence binds the current accepted attempt. Document candidates serialize no
  execution fields; executable
  decision identity exists only inside receipt evidence.
- `CapabilityProviderCandidateFingerprint`: canonical identity over definition,
  declaration, normalized Provider metadata, configuration, source/dependency
  revision, Product/scope, and requested authority.
- `CapabilityProviderEligibilityGrant`: Capability-owner data fact that permits
  bounded normalization; it is not final admission.
- `CapabilityProviderAdmissionRecord`: Capability-owner final decision over the
  complete normalized candidate and effective grants.
- `CapabilityProviderBindingSpec`: data-only verified factory/disposer
  references and normalized binding inputs matching one admitted Provider.
- `ResolvedCapabilityProviderSet`: one selected metadata/spec/admission tuple per
  Capability plus deterministic closure provenance.
- `ProductCapabilityProviderResolver`: pure Product selector over already
  owner-admitted candidates. It imports and constructs nothing.
- `ProductCapabilityConsumerRequirementSet`: one Product-owned immutable union
  of mandatory Product roots and normalized Tool/Command requirements returned
  by exact owner admission. It is the only external-Consumer input to Provider
  closure selection. It preserves canonically sorted per-Consumer requirements
  and admission provenance rather than synthesizing one merged requirement per
  Capability.

The initial Capability owner implementation may be a Product-owned explicit
allowlist/codec for `coding.lsp`; it must still produce the generic grant and
admission records. A universal mutable owner registry is not introduced.

### Binding layer

- `CapabilityComponentHost`: verifies the selected package/revision and
  activation approval receipt, resolves the declared factory/disposer symbols,
  and produces one existing `CapabilityBundleProviderBinding` plus adjacent
  immutable provenance.
- `SessionCapabilityCompositionInputs`: root-owned immutable definitions,
  selected Provider set, Graph plan request, binding specs, and provenance.
  It stays separate from `StagedResourceCompositionCandidate`.

The Component Host does not call the Graph Binder. The Session composition root
collects all bindings and invokes the existing Binder once.

## End-To-End Control Flow

```text
plugin.json
  -> PluginManifestParser
  -> PluginResolutionAuthority
  -> PublishedPluginPackage + VerifiedRevisionHandle
  -> PluginDeclarationHost.resolve()
       owns one long-lived Resolver/Coordinator pair for the composition root
  -> PluginSelectionResolver.preflight()
       inert manifest facts only
       no import
       PluginPreflightProposal + exact source proposals
       accepted directly when every proposed source requirement is satisfied
         (all data_only is the no-decision special case)
       OR, only when a current executable decision is missing,
          pending_approval(proposed subjects only; no token/group/reservation)
          -> Approval owner records decisions
          -> fresh PluginSelectionResolver.preflight()
             revalidate revision/trust/policy/scope/config/decisions
             accepted(active token + exact PluginDeclarationSourceGroups)
  -> data_only group
       VerifiedRevisionHandle.open_file(revision-root-relative locator)
       strict PluginDeclarationDocument decoder
       document_decoded evidence
     OR execution_preflight group
       consume current decision atomically
       PluginDefinitionEvaluator imports exact verified entrypoint once
       Definition/Builder returns declarations only
       Host attaches in_process_evaluated receipt evidence
  -> PluginDeclarationCoordinator
       claim each group through the one aggregate CAS protocol
       join every non-overlapping source-evidenced batch
       abort active token exactly once on failure/cancellation
  -> PluginSelectionResolver.finalize()
       exact full-preflight reservation consumption once
       PluginContributionCandidate
  -> PluginDeclarationHost returns PluginSelection only
  -> Capability owner eligibility
  -> Product/OEM bounded normalization
  -> Capability owner final admission
  -> ProductCapabilityProviderResolver
       complete deterministic Provider closure
  -> RuntimeCapabilityGraphPlanner
       metadata validation only
  -> CapabilityComponentHost
       consume activation decision
       resolve exact factory/disposer
       CapabilityBundleProviderBinding
  -> RuntimeCapabilityGraphBinder
       stage Provider values and RegistrationScopes
       validate facets
       publish one Mount generation
       retire replaced nodes
  -> Product captures typed Consumer facets
  -> Product Session publishes as usable
```

Failure before the Binder publication point produces no Mount generation. A
declaration or admission failure has no live disposer because no Provider was
constructed. A construction failure is rolled back by the existing Binder. A
post-publication retirement failure remains an owner-visible retryable cleanup
fact and never rolls back the committed graph.

## PAP/PLC Sequencing Crosswalk

PAP describes the author-facing dependency slices. PLC is the coordinating
source-change order across declarations, lifecycle management, trust, binding,
and Coding production cutovers. PLC order wins whenever the two plans appear
to permit different implementation timing.

| PAP slice | Coordinating PLC slice | Relationship |
| --- | --- | --- |
| PAP0 | PLC0 | Same baseline and authority inventory. |
| PAP1 | PLC1A | Same typed `capability_provider` codec and reservation-bound internal builder. |
| PAP1B | PLC1B | Same source union, Resource/Tool/Command declaration expansion, and inert `coding.base` shadow proof. |
| No original PAP slice | PLC2 | Minimum lifecycle and management control is an integrated prerequisite before executable declaration work lands. |
| PAP2 + PAP3 | PLC3 | Approval-owner consumption followed by verified Definition evaluation. |
| PAP4 + PAP4R + PAP5 | PLC4 | Capability and Resource/Tool/Command exact-owner admission, external-Consumer root compilation, Product selection, Component Host, and existing owner publication. |
| PAP6 | PLC5 | First production Graph proof through `coding.lsp.default`. |
| No original PAP slice | PLC6 + PLC7 | Production `coding.base` Resource cutover, then `coding.arch.default` as the second Provider proof. |
| PAP7 + PAP8 | PLC8 | Public SDK stabilization and single provider-neutral Skill Resource path after production evidence. |
| No original PAP slice | PLC9 | Management surfaces, isolation, GC, and cleanup closure. |

PAP2/PAP3 design and adversarial review may proceed while PLC1B and PLC2 are
being prepared. Their source implementation may not bypass PLC1B's canonical
declarations or PLC2's durable Plugin-instance lifecycle. This prevents an
executable Definition path from becoming the accidental lifecycle authority.

## Delivery Slices

Each slice uses a task branch from the current Harness integration baseline,
adds a failing behavioral contract first, and remains independently reviewable.
Do not merge all slices as one change.

### PAP0: Baseline And Review Fixtures

Scope:

- create a tracking issue and record the exact UPA1/UPA2 source commit;
- reconcile the three known architecture-baseline failures against the current
  source and restore the qualified inventory to green without broadening an
  allowlist merely because a new sink exists;
- freeze the current public exports for Capability contracts, Provider binding,
  Graph Planner/Binder, Registration Scope, Plugin declaration, selection, and
  verified revision use;
- extend the architecture inventory with forbidden bypasses: declaration import
  before decision consumption, direct candidate-to-Binder conversion,
  Product-issued owner admission, raw mutable-path reopen, a second Graph bind,
  and public Plugin SDK exposure before feature negotiation;
- add a reusable test fixture that represents a published synthetic Plugin but
  cannot execute yet.

Primary files:

```text
tests/architecture/test_unified_plugin_architecture.py
tests/harness/resources/plugins/conftest.py
docs/internals/architecture/harness/plugin-authoring-primitives-delivery-plan.md
```

Exit gate:

- baseline tests pass without production behavior changes;
- every future mutation sink has an explicit owner and test seam;
- no public import path is added.

Rollback: remove inventory/fixture additions only.

### PAP1: Typed Capability Provider Declaration Payload

Scope:

- add strict JSON codecs for `CapabilityContractRange`,
  `CapabilityRequirement`, `CapabilityBundleProvider`, and symbol references;
- add `CapabilityProviderDeclarationPayload` and bind it to one existing
  `PluginDeclaration.payload` arm;
- add the internal builder bound to exact `PluginDeclarationReservation`
  preflight facts;
- reject unknown fields, noncanonical values, owner/capability mismatch,
  duplicate requirements/facets, callable payloads, absolute/traversing
  locators, reservation mismatch, and post-freeze mutation;
- keep `PluginContributionKind` limited to the currently supported
  `capability_provider` arm.

Primary files:

```text
src/loushang/harness/resources/plugins/declarations.py
src/loushang/harness/plugin_authoring/capability_provider.py     # new
src/loushang/harness/plugin_authoring/builder.py                 # internal, new
tests/harness/plugin_authoring/test_capability_provider.py       # new
tests/harness/plugin_authoring/test_builder.py                   # new
```

Exit gate:

- JSON round-trip and canonical fingerprint fixtures are stable;
- builder output exact-matches hand-authored IR;
- the builder cannot import, register, bind, or access a Session;
- existing UPA2 preflight/finalize tests remain byte-for-byte compatible except
  for explicitly versioned fixture evolution.

Rollback: remove the new codec/builder; existing generic payload remains valid.

Implementation placement note: the initial file sketch placed the codec under
`resources.plugins`. The executable dependency gate proved that placement
would add `resources -> capabilities` while Capability consumers already use
Resources. PAP1 therefore lives in the internal top-level `plugin_authoring`
composition layer. `PluginDeclaration` and `PluginSelectionResolver` continue
to freeze and fingerprint an opaque payload; explicit
`from_reserved_declaration()` performs the owner-specific strict decode before
any future admission or binding. This preserves the acyclic package graph and
does not create a second declaration IR.

### PAP1B: Data-Only Declaration Source And Consumer Expansion

Scope:

- advance `ContributionIndex` and `PluginDeclaration` to runtime-only v2,
  introduce `PluginDeclarationDocument` v1, and reject draft v1 at runtime
  without retaining a peer compatibility parser;
- advance the unpublished `CapabilityProviderDeclarationPayload` and
  `PluginSymbolReference` to v2, remove package digest from package-internal
  symbol references plus the redundant payload configuration fingerprint, add
  Index-owned `contributionExecutionModel`, and bind the Host-resolved reference
  to the exact published package digest and Index model after publication;
- add one versioned `PluginDeclarationSource` tagged union with strict
  `document` and `in_process` arms;
- bind source kind and the revision-independent descriptor fingerprint into
  reservation/declaration bytes; Host-only group/evidence/candidate records bind
  package revision and accepted context. Every locator is revision-root-relative
  and may be opened only through `VerifiedRevisionHandle`;
- distinguish `package_source_identity` (installation/trust provenance) from
  `sourceDescriptorFingerprint`, Host-computed `sourceGroupFingerprint`, and
  attempt-specific `sourceGroupId`; rename the
  contributed factory/service enum to `PluginContributionExecutionModel` so it
  cannot be reused as a declaration-source kind;
- group by exact source/revision within one preflight context; selecting any
  contribution closes the proposed group over every index entry sharing that
  source, one source group is decoded or evaluated once, one reservation
  belongs to one group, and a package may contain several distinct document and
  in-process groups;
- remove the reservation's unconditional execution subject/decision fields;
  the accepted source group alone owns one strict `data_only` or
  `execution_preflight` gate, while its reservations reference only the group
  fingerprint. Document declarations never carry a fake execution approval;
- return the strict preflight outcome union and atomically materialize groups/
  one-use reservations only when every selected source is data-only or the
  Approval-owner lookup port returns a positive executable decision; before
  PAP2 the production lookup is pending-only and only a private routing test
  double can exercise the mixed-source abort fence;
- introduce Product-supplied pure-data `PluginPreflightContextV1` and
  `PluginInstanceRevisionRef`; PLC1B validates but never invents or persists
  them, and PLC2 later owns their durable lifecycle without redefining them;
- make `PluginSelectionPlanV2` the sole Product context/trust/configuration/
  authority input: Product supplies an already-resolved exact effective map and
  versioned non-secret secret references, while PLC1B validates/hashes and does
  not own a second overlay/merge/sensitivity-classification algorithm;
- implement the exact records, domains, canonical byte acceptance and distinct
  version diagnostics frozen by the PLC1B Contract;
- advance `PluginExecutionApprovalSubject` to group-level v2 and fail closed on
  the draft per-contribution v1 subject schema; advance the decision record to
  v2 with independent `decisionRecordVersion` and `subjectSchemaVersion` fields
  and reject its current unversioned draft;
- distinguish the preflight gate from final `document_decoded` or
  `in_process_evaluated` evidence; PLC1B can finalize document batches, while
  isolated in-process Builder codec output has no Coordinator ingress; an
  executable group fails `execution_not_consumed` before any declaration input,
  Batch or candidate creation;
- add the inert `PluginDeclarationCoordinator` and document decoder. PLC1B
  uses the one low-level `resources.plugins` strict JSON primitive for manifest
  and document schemas; the Coordinator imports no raw JSON decoder and its private
  byte-ingress method accepts a concrete `VerifiedRevisionHandle`, permits only
  exact `open_file`/stream `read`/document-codec `decode_bytes` call edges, and
  accepts no reader/decoder callback. The stateless class/static codec entrypoint
  is called directly and no codec instance is stored; mutable injection/
  rebinding, import shadowing, decoder-symbol aliases, and local helper calls are
  included in the architecture guard. PLC1B
  pre-scans all groups and finalizes document-only one/multi-group preflights
  exactly once; a mixed document/in-process preflight accepts no executable
  declaration/Builder input, proves routing/no-import, aborts with
  `execution_not_consumed`, and invokes `finalize()` zero times;
- replace candidate `decision_id` with strict group/evidence provenance and add
  attempt-bound evidence plus the claim-aware
  `ACTIVE_OPEN -> FINALIZED|CLOSING_ABORT|CLOSING_EXPIRE` aggregate protocol;
- install the expiry reaper before accepted publication, let only the actual
  execution unit settle its opaque claim lease, and make close wait for physical
  completion rather than treating cancellation request as completion;
- privatize direct subject construction and Resolver finalize/rollback; only the
  higher `plugin_authoring` Coordinator receives the internal terminal handle;
- add strict `resource_item`, `tool_pack`, and `command_pack` declaration
  payloads while retaining the existing `capability_provider` arm;
- model Skill, prompt, method, theme, asset, and raw source as owner-versioned
  Resource subtypes, not Plugin kinds;
- keep Provider, Tool pack, and Command pack as sibling contributions joined
  only by typed requirements and Product selection closure; and
- compile an inert document-backed `coding.base` shadow declaration for
  pre-owner/pre-Host-normalization canonical payload/semantic-fingerprint
  parity with hand-authored and internal-builder IR while retaining source-
  bound full fingerprints.

Canonical manifests and IR add no mutually exclusive top-level `pluginType`,
hierarchical numeric type code, or capability bitmap. Contribution kind,
Resource subtype, declaration source, Host-verified provenance/trust, and
Product/OEM selection remain separate dimensions. Derived catalog or UI labels
grant no authority and do not participate in identity, compatibility,
admission, or binding.

Primary files are expected under:

```text
src/loushang/harness/resources/plugins/declarations.py
src/loushang/harness/resources/plugins/manifest.py
src/loushang/harness/plugin_authoring/
tests/harness/resources/plugins/
tests/harness/plugin_authoring/
tests/harness/resources/plugins/fixtures/coding_base_shadow/
```

Exit gate:

- both source arms exact-match the verified package revision and descriptor
  fingerprint through Host validation. Host-created Batch/Evidence, not the
  document/source record, binds the accepted SourceGroup Product/scope/policy
  context, effective configuration map, attempt and reservation closure;
- v1 index/IR input fails with an exact unsupported-version diagnostic; v2
  index/IR and document-envelope v1 have stable canonical round trips;
- payload/symbol-reference v1 fail their separate version diagnostics; a real
  document-backed Capability Provider package contains no `packageDigest`, is
  publishable without a hash fixed point, and its Host-resolved reference binds
  the exact published digest plus Index-owned contributed execution model;
  payload v2 has a required `SymbolReferenceV2|null` disposer and no redundant
  configuration fingerprint;
- same-source multi-contribution and same-package document multi-source fixtures
  prove one decode per group and one finalization per preflight;
- a two-group configuration fixture proves the Plan set covers both closures
  while each group hashes only its local projection; changing only group B
  leaves group A's configuration/group/Subject digests unchanged;
- mixed document/in-process fixtures prove exact grouping, zero import, zero
  executable declaration ingress, typed `execution_not_consumed`, one aggregate
  abort and zero finalization; PLC3 owns the successful mixed-source evaluation/
  join/finalize fixture;
- document finalization carries `document_decoded` evidence without an
  execution subject/decision/receipt, while isolated in-process Builder output
  cannot enter the Coordinator until PLC3 supplies the evaluator and exact
  group-level receipt evidence;
- document candidate serialization contains no subject/decision/receipt field,
  and draft subject/decision record v1 shapes fail with their separate exact
  unsupported-version diagnostics;
- declaration source kind and contributed factory/disposer/service execution
  model are separately fingerprinted and cannot substitute for one another;
- every new payload has strict canonical JSON round-trip and negative fixtures
  for unknown fields, duplicate identities, owner mismatch, path escape, and
  callable/live-object capture; the Contract's exhaustive condition-to-code
  table drives those fixtures and Manifest preserves every nested code;
- the canonical manifest boundary rejects duplicate keys and unsorted Index
  items without swallowing the typed codec diagnostic, and architecture scans
  count concrete calls across `plugin_authoring`, freeze the Coordinator's exact
  import/call edge and concrete verified-handle receiver, reject imported local
  helper calls, mutable codec routes/import shadowing,
  assignment/module/third-party decoder aliases, or a
  second decoder/read even inside an allowed function, and freeze the sole
  declaration `VerifiedRevisionHandle.open_file()` callpoint plus one low-level
  strict JSON primitive;
- a Capability Provider cannot contain arbitrary contributions, admit/select/
  bind itself, or explicitly require its own Capability; duplicate requirements
  also fail in the strict payload codec;
- Provider/Tool/Command sibling declarations cannot import, resolve, register,
  bind, or publish anything; and
- the `coding.base` shadow has no Resource generation, Tool registration,
  Session, Model Input, disposer, or other live effect.

PLC1B-1 deletes or private-scopes the old top-level
`build_execution_approval_subject`, `PluginPreflight`, direct `finalize()` and
`rollback()` paths and adds forbidden-peer scans. It does not wrap those paths
with a second Coordinator API.

Shadow parity compares only `PluginContributionSemanticFingerprint` v1 over
kind, owner, payload schema/version, pinned catalog/schema revisions and strict
canonical payload before owner or Host-environment normalization. Complete
declaration and candidate fingerprints remain bound to source kind, source
descriptor/group identity, reservation and evidence provenance, so different source models
are expected to differ there. Host-specific Tool normalization and live
behavior parity are PLC4/PLC6 gates, not PLC1B claims.

Rollback: remove only the inert codecs, builder arms, and fixtures. No owner or
live runtime cleanup is required.

### PAP2: Durable Execution Decision Consumption

Implementation-order note: this slice is part of PLC3. Its source may land only
after PAP1B/PLC1B and the PLC2 minimum lifecycle command core; designing and
reviewing its records earlier does not authorize an executable peer path.

Scope:

- define the Plugin execution subject adapter under the existing Approval
  owner; one subject binds one exact in-process source group and its complete
  sorted reservation closure, not one arbitrary contribution or contributed-
  runtime launch;
- persist issue/approve/deny/consume/revoke facts with expected revision,
  expiry, revocation epoch, source-trust revision, and actor/source provenance;
- add one installation/workspace-scoped durable Plugin decision journal inside
  `harness.approval`; it is recovered before Plugin preflight, survives Session
  close, and projects the strict v2 selection view. The current Session grant
  store is not reused as durable Plugin authority;
- implement atomic one-shot consumption and idempotent query/recovery;
- require the already-claimed worker to win one aggregate
  `PluginExecutionStartPermit` before calling Approval: permit-before-close may
  continue while close waits for real completion; close-before-permit forbids
  consumption and loader entry; release the aggregate lock before Approval;
- create consumption and the attempt-bound
  `ExecutionUseReservation(CONSUMED_NOT_STARTED)` in the same Approval-owner
  transaction; there is no observable consumed-without-reservation orphan;
- persist that attempt-bound `ExecutionUseReservation` before declaration import:
  `CONSUMED_NOT_STARTED -> CANCELLED_BEFORE_START|STARTING`, then
  `STARTING -> EVALUATED|FAILED_AFTER_START`.
  `STARTING` commits before loader invocation; recovery treats started/failed
  use as possibly executed and the exact `importRealmId`/`hostBootId` as
  polluted, while an external-boot not-started use becomes
  `CANCELLED_BEFORE_START` and is never resumed. Reservation and current-realm
  `EVALUATED` receipt both carry the exact boot/realm IDs frozen by the Contract;
  no Approval callback runs while the aggregate lock is held. Factory/service
  launch remains solely under activation approval;
- keep UI/presentation and Product wording as adapters over the Approval owner;
- remove the current ability to treat an arbitrary in-memory
  `PluginExecutionDecisionRecord` as execution authority. It may remain an inert
  selection input only when backed by a durable decision reference.

Primary files are expected under:

```text
src/loushang/harness/approval/
src/loushang/harness/resources/plugins/selection.py
src/loushang/harness/resources/plugins/execution.py              # new adapter
tests/harness/approval/
tests/harness/resources/plugins/test_execution_approval.py       # new
```

Exit gate:

- denied, missing, expired, stale-policy, stale-trust, wrong-scope,
  wrong-digest, consumed, and revoked decisions all fail before import;
- consume-versus-revoke has one tested linearization result;
- consume/import-start versus abort/expire has one tested lease/close
  linearization result, waits for physical worker completion, and cannot leave
  an orphan or resumable before-start use reservation;
- crash recovery never replays a consumed decision/receipt across accepted
  attempts and conservatively fences a possibly started import realm;
- the Plugin package owns no second Approval store or pending lifecycle.

Rollback: disable executable declaration evaluation; inert inspection and
selection remain available.

### PAP3: Verified Plugin Definition Evaluation

Scope:

- introduce the internal `PluginDefinition` Protocol and evaluator;
- load only from the `VerifiedRevisionHandle` and locked import closure;
- consume the PAP2 group decision immediately before crossing the import start
  point, persist `STARTING` before calling the loader, and import each source
  group once;
- invoke a source-group-bound PAP1 builder in a context containing only
  immutable locators, normalized configuration, engine features, and that
  group's exact reservation closure;
- emit `in_process_evaluated` evidence bound to the complete consumption receipt
  and let the coordinator join all source groups before one exact
  declaration/index finalization;
- return only frozen declarations from Definition/Builder; the trusted
  evaluator validates them and alone attaches receipt evidence to construct the
  executable Batch;
- on any group failure/cancellation, abort the aggregate once; a previously
  consumed decision remains consumed and explicit retry requires a fresh
  preflight, decision and clean Host unless an accepted idempotent re-evaluation
  contract applies;
- record declaration provenance and evaluation diagnostics without leaking
  paths, environment values, secrets, or raw exceptions.

Primary files:

```text
src/loushang/harness/plugin_authoring/evaluator.py                 # new
src/loushang/harness/plugin_authoring/import_realm.py              # new/private
src/loushang/harness/resources/plugins/selection.py
tests/harness/plugin_authoring/test_evaluator.py                   # new
tests/harness/plugin_authoring/test_import_realm.py                # new
```

Exit gate:

- disabled/denied code is observably never imported;
- source mutation after publication cannot affect evaluation;
- undeclared transitive imports and conflicting locked closures fail closed;
- document/in-process mixed-source success evaluates each executable group once,
  joins the complete evidence set and finalizes exactly once;
- a later-group failure after decision consumption aborts the aggregate once,
  publishes no candidate, and cannot reuse that decision on retry;
- evaluation cannot publish any registry, registration, Resource, or Mount;
- a failed preflight never auto-consumes a second decision; explicit retry uses
  the fresh-attempt/clean-Host rule above.

Rollback: stop at inert preflight/finalize fixtures. No owner generation exists,
but durable decision/use audit remains and a started import realm may require a
clean Host restart.

### PAP4: Capability Owner Admission And Product Closure Selection

Scope:

- add generic candidate fingerprint, eligibility grant, final admission,
  binding spec, and resolved Provider-set records;
- implement an explicit `coding.lsp` owner policy adapter as the first real
  owner, plus a synthetic Harness owner fixture for conformance tests;
- implement the pure `ProductCapabilityProviderResolver`;
- prove optional requirements, zero/multiple candidates, extra/missing closure
  members, policy revisions, expiry/revocation, and fingerprint skew;
- pass only the already unique Provider metadata set to the existing Graph
  Planner.

Primary files:

```text
src/loushang/harness/capabilities/provider_admission.py           # new
src/loushang/harness/capabilities/provider_selection.py           # new
src/loushang/coding/lsp/capability_contract.py                    # new
tests/harness/capabilities/test_provider_admission.py             # new
tests/harness/capabilities/test_provider_selection.py             # new
tests/coding/lsp/test_capability_admission.py                     # new
```

Exit gate:

- Product selection cannot manufacture or widen owner eligibility/admission;
- the Graph Planner receives exactly one Provider per closed Capability;
- no Runtime Profile slot is created for a top-level Capability ID;
- all outputs are immutable, serializable, and contain no callables.

Rollback: remove the pure records/resolver; no import or Graph behavior changes.

### PAP4R: Resource/Tool/Command Owner And Consumer-Root Bridge

Scope:

- add exact Resource, Tool, and Command owner codecs/admission records for
  `resource_item`, `tool_pack`, and `command_pack` without introducing a global
  Plugin contribution owner;
- require Tool/Command owner admission to return normalized typed
  `CapabilityRequirement` values alongside admitted catalog identities;
- make `ProductCompositionCompiler` combine mandatory Product roots and those
  admitted external-Consumer requirements into one immutable
  `ProductCapabilityConsumerRequirementSet` before PAP4 Provider selection;
- preserve every normalized requirement with Tool/Command owner, contribution
  and admission provenance; required entries extend roots and are conjunctive,
  optional-only entries require an explicit satisfied/unsatisfied Product
  decision (`satisfied` adds the root, `unsatisfied` adds no root/view), and
  incompatible required constraints fail without lossy merging;
- pass only resulting root Capability IDs and the complete selected Provider
  set to the existing `RuntimeCapabilityGraphPlanner`, which remains the sole
  transitive-cycle validator;
- after Graph publication, capture generation-scoped typed facets through the
  Product runtime Consumer path and hand them to the exact Tool/Command owner
  while staging that owner's generation; and
- preserve `StagedResourceCompositionCandidate` as the one Resource candidate
  rather than adding a Plugin Resource runtime.

Exit gate:

- a required Tool/Command Capability requirement deterministically extends
  Provider roots or fails before any owner publication;
- same-Capability requirements retain deterministic ordering and every
  provenance record; required/optional, contract, facet and binding semantics
  are evaluated per entry rather than overwritten by a last-writer merge;
- contract/facet mismatch is diagnosed before Graph construction;
- no Tool, Command, Plugin, or catalog code looks up a Provider by Plugin ID or
  ambient container;
- direct Provider self-requirement fails in the payload codec, while every
  transitive Provider cycle is reported only by the existing Graph Planner;
- Tool/Command generations remain exact-owner registrations and become visible
  only with the usable Product Session containing their captured facets; and
- no second Graph request, Resource candidate, registry bag, or cross-owner
  rollback transaction is introduced.

Rollback: remove the pure admission/root bridge and owner staging adapters; no
canonical declaration or Capability Graph type is replaced.

### PAP5: Owner-Preserving Component Host And Bind Bridge

Scope:

- add the narrow Capability Component Host;
- consume final activation approval against the admitted fingerprint and
  effective grants, returning a token-bound one-use activation lease rather than
  treating the approval receipt as reusable authority;
- create an exact-owner `ActivationUseReservation` for every factory/bind/spawn
  attempt and move `CONSUMED_NOT_STARTED -> STARTING -> STARTED|COMMITTED|FAILED`
  at the real Binder/Host execution point; a new attempt requires a fresh
  decision and an external-service restart never replays an old receipt;
- resolve factory/disposer symbols from the same verified revision and produce
  the existing `CapabilityBundleProviderBinding`;
- add root-owned `SessionCapabilityCompositionInputs` and integrate it beside,
  never inside, the existing `StagedResourceCompositionCandidate`;
- make the Session composition root plan once, bind once, capture Consumers,
  then publish the Session;
- preserve existing built-in direct bindings through an explicit adapter until
  their production Plugin migrations land.

Primary files are expected under:

```text
src/loushang/harness/capabilities/component_host.py               # new
src/loushang/harness/session/capability_composition_inputs.py     # new
src/loushang/harness/session/agent_product.py
tests/harness/capabilities/test_component_host.py                 # new
tests/harness/session/test_plugin_capability_composition.py       # new
tests/architecture/test_unified_plugin_architecture.py
```

Exit gate:

- an end-to-end synthetic Plugin traverses published package, preflight,
  declaration, owner admission, Product selection, planning, construction,
  execution through a typed Consumer, and exact disposal;
- Binder construction remains the first point at which a live Provider exists;
- one failed factory or invalid facet set publishes nothing and reverse-disposes
  only newly staged registrations;
- disabling/replacing a Provider affects new Sessions; active sealed Sessions
  return `restart_required` and retain their pinned generation;
- no second Graph runtime, Binder, Projector, registration scope, or effective
  clock is introduced.

Rollback: switch the Session input adapter back to built-in bindings; the new
records remain inert and safe to retain.

### PAP6: `coding.lsp` Production Vertical Slice

Scope:

- define the owner-qualified `coding.lsp` Capability contract and focused
  semantic/tool-runtime/diagnostic facets;
- package the default LSP Bundle Provider through the PAP1 authoring SPI;
- adapt existing discovery/catalog/supervisor/document runtime objects behind
  one Provider factory/disposer, and package model-visible Tool definitions as
  a sibling `tool_pack` consuming the admitted tool-runtime facet;
- declare `harness.workspace` read/process requirements and consume only those
  facets;
- mount LSP through PAP4/PAP5 and delete deferred runtime and early Tool
  registration only after Provider and sibling Tool-pack compatibility tests
  pass;
- keep individual language-server routes as owner-internal data for this first
  slice; generic `capability_component` authoring follows only after the
  complete-Bundle path is stable.

Primary migration surfaces include:

```text
src/loushang/coding/lsp/
src/loushang/coding/bootstrap.py
src/loushang/harness/session/agent_product.py
tests/coding/lsp/
tests/coding/test_bootstrap.py
tests/architecture/test_unified_plugin_architecture.py
```

Exit gate:

- default and alternate Providers can be selected without changing LSP Tool or
  Session implementation code;
- sibling Tool definitions become Session-visible only with the mounted LSP
  Bundle and use its typed runtime facet without entering the Provider's owner
  generation;
- startup cancellation/failure leaks no process, document, Tool, or
  registration;
- Session restart reconstructs selection from pinned package/declaration/
  admission facts;
- complete Model Input facts remain replayable after the package source is
  removed;
- legacy deferred LSP and pre-binding routes are removed from the executable
  inventory, not merely hidden behind a facade.

Rollback: select the existing built-in LSP adapter for new Sessions. Do not
attempt to roll an active Mount generation backward.

### PAP7: SDK Stabilization And Author Conformance

Prerequisite: the accepted UPA5 `coding.base` and UPA6 `coding.arch` production
slices are complete, or an accepted UPA revision explicitly changes that gate.
The public SDK must not be declared stable after only a synthetic fixture and
one LSP implementation. Before the prerequisite is met, this slice may maintain
an internal SDK candidate and author conformance suite, but it may not add the
stable `loushang.plugin` re-export shown in the target example.

Scope:

- freeze the post-PLC1B declaration IR v2 and engine-feature negotiation against
  the synthetic fixture and `coding.lsp` package; draft PLC1A v1 remains an
  explicit unsupported-version fixture, not a runtime compatibility path;
- publish the minimum author surface under one stable module;
- add a package validation command that performs manifest/IR/schema checks
  without import and a separate explicitly approved execution conformance run;
- publish a short provider-authoring guide and one non-example conformance
  package fixture;
- keep owner Definition publication APIs separate from ordinary Provider author
  APIs.

Exit gate:

- a Provider author imports only documented authoring records/helpers;
- no public symbol exposes a Graph, scope, registry, approval store, or mutable
  Plugin context;
- two engine/IR versions have explicit compatible or incompatible fixtures;
- diagnostics identify manifest path, contribution ID, owner, and stable code.

Rollback: keep the internal SPI and remove the public re-export; runtime
semantics do not change.

### PAP8: Skill Provider And Lazy Resource Convergence

Scope:

- keep each `SKILL.md` as a `resource_item`, not a Plugin instance or Graph node;
- define a provider-neutral Skill catalog snapshot and lazy body loader;
- adapt filesystem, admitted package, and embedded Skill sources to that one
  catalog path;
- use owner-specific Resource registration/refresh and deterministic precedence;
- bind every loaded model-visible Skill to source revision/content digest and
  commit the actual content through Model Input;
- route Skill-referenced scripts through existing Tool/Policy/Approval/Sandbox
  execution rather than importing them as Plugin code.

Exit gate:

- CLI listing, enable/disable, prompt catalog, explicit load, and refresh use
  one catalog;
- same-name precedence is order-independent and source-explainable;
- refresh affects the next model input, never a committed current request;
- a Provider disposer cannot remove another Provider's Skills;
- no per-Skill Plugin activation identity is created.

PAP8 schema design and review may begin after PAP5 if it uses only internal
stable records. Source implementation and merge remain PLC8 work and may not
begin before the LSP, Base, and Arch production gates; early design must not
delay PAP6 or publish a public SDK ahead of PAP7.

## Commit And Review Shape

Each PAP slice should normally use three commits:

1. `test(...): freeze <slice> contracts`
2. `feat(...): implement <slice> owner path`
3. `refactor(...): remove <slice> peer route`

The third commit is omitted when the slice adds only inert records. A migration
is incomplete while both paths can construct or publish the same live object.
Compatibility adapters must have an explicit caller inventory and deletion
gate; forwarding through the new path is acceptable only when the old path can
no longer independently execute.

Review every slice for:

- one authority per published object;
- data-only declaration before approval and binding;
- exact package/revision/decision/admission fingerprint continuity;
- least-authority Provider and Consumer views;
- cancellation and reverse-disposal behavior;
- cold resume and Model Input reconstruction;
- Product neutrality and import direction; and
- deletion of the displaced peer route.

## Verification Matrix

### Focused gates

```text
.venv/bin/python -m pytest tests/harness/resources/plugins -q
.venv/bin/python -m pytest tests/harness/capabilities -q
.venv/bin/python -m pytest tests/harness/session -q
.venv/bin/python -m pytest tests/architecture/test_unified_plugin_architecture.py -q
.venv/bin/python -m pytest tests/coding/lsp -q
```

Use only the subsets affected by each inert slice, then expand through PAP5 and
PAP6. Python test commands must follow the repository sandbox guidance and add
`--skip-host-runtime` when running the normal sandbox suite.

### Static and repository gates

```text
.venv/bin/ruff check <changed Python files>
git diff --check
```

Architecture scans remain defense-in-depth. Behavioral tests at the real
parser, Approval owner, evaluator, admission owner, Component Host, Graph
Binder, and Session publication seams are the completion evidence.

### Mandatory adversarial scenarios

- same Plugin ID/version with changed bytes;
- package publication and document decode attempted with a revision-dependent
  descriptor fingerprint or other self-referential package field;
- mutable source changed after publication;
- wrong or missing dependency lock;
- declaration not reserved, reserved twice, or reservation left unconsumed;
- same source with multiple reservations, one package with multiple sources,
  mixed document/in-process groups, and overlapping group closures;
- approval granted after a pending proposal while revision/trust/policy/config
  changes before the mandatory fresh preflight;
- draft v1 index/IR and per-contribution execution-subject v1 presented to the
  runtime-only v2 parsers;
- document candidate serialization attempts to retain an empty/nullable
  decision field;
- concurrent finalize/abort/expire and later-group failure after one execution
  decision is consumed;
- group claim or execution-start permit racing aggregate close, permitted
  consumption continuing under close, and stale
  document/execution evidence replayed under a new `preflightUseId`;
- duplicate JSON keys, BOM, noncanonical whitespace/key order/escaping and raw
  bytes unequal to canonical document re-encoding;
- CJK/combining-form semantic fingerprints and an unpaired surrogate payload;
- executable Builder output carrying only a positive decision reference and no
  current consumption receipt;
- Definition tries to return a callable or access a registry;
- decision digest/scope/config/policy/trust mismatch;
- consume/revoke and consume/crash races;
- import failure/cancellation after durable `STARTING`, followed by retry in the
  same polluted Host;
- Product attempts to admit an owner-rejected candidate;
- admitted Tool/Command requirement omitted from Product Capability roots;
- incompatible same-Capability required constraints and optional-only Consumer
  requirements without an explicit satisfied/unsatisfied decision;
- owner admission expires between selection and activation;
- selected metadata and binding spec disagree;
- factory returns wrong facets or fails after staged registrations;
- cancellation before and after the Binder publication window;
- active Session observes disable/update;
- package source disappears before replay;
- disposer fails retryably; and
- same interpreter receives incompatible package/import closure.

## Definition Of Done

The authoring-primitives milestone is complete only after PAP0-PAP7, including
PAP1B, and PAP7's UPA5/UPA6 prerequisites, not after the first builder lands.
Completion means:

1. one documented Provider declaration compiles to the canonical IR;
2. executable declaration and activation both have current durable consumption
   receipts;
3. Capability owner admission and Product selection are separately visible and
   cannot impersonate each other;
4. the existing Planner/Binder/RegistrationScope remain the only Graph/live
   publication path;
5. a production `coding.lsp` Plugin executes and unloads through that path;
6. its Consumer code depends only on typed facets;
7. disabled/denied/untrusted code is never imported;
8. rollback, cancellation, restart, replay, and retirement gates pass;
9. the displaced direct LSP construction and Tool pre-binding routes are
   deleted; and
10. the public SDK exposes no broader authority than the internal SPI proved.

PAP8 Skill convergence is the first lightweight Resource-provider adoption,
not part of the executable Capability authoring completion gate.

## Estimate And Parallelism

Indicative focused effort, excluding unrelated failures:

| Slice | Estimate | Parallelism |
| --- | ---: | --- |
| PAP0 | 1 day | none; baseline first |
| PAP1 | 2–3 days | codecs/tests can split after record names freeze |
| PAP1B | 6–10 days | source grouping/coordinator, Resource/consumer codecs, and shadow fixture split only after v2 identity fields freeze |
| PAP2 | 4–7 days | store/recovery and Product presentation adapter may split |
| PAP3 | 4–6 days | import-realm work dominates and should not be rushed |
| PAP4 | 3–5 days | owner admission and pure Product resolver can split |
| PAP4R | 4–6 days | exact owner codecs and pure Consumer-root compilation can split before owner staging |
| PAP5 | 4–6 days | Component Host and Session integration split after interfaces freeze |
| PAP6 | 6–10 days | LSP Provider migration, Session adoption, and peer-route deletion split by commit |
| PAP7 | 2–4 days | guide/fixtures after runtime contracts freeze |
| PAP8 | 3–5 days | filesystem/package adapters can split after catalog contract freezes |

PAP1, PAP1B, PAP4, and the admission/root-compilation half of PAP4R are
data/pure-logic work. PAP2, PAP3, PAP4R owner staging, PAP5, and PAP6 are
security/lifecycle work and require regression-first sequencing. PAP1B remains
inert even though it prepares executable-source descriptors; descriptor
parsing never imports the source. Schedule estimates are not acceptance
criteria.

## Explicit Deferrals

The authoring milestone does not add:

- generic typed events, durable subscription outboxes, Agent Definitions, or
  private Plugin data migration;
- a universal `capability_component` SDK before the complete-Bundle LSP path is
  proven;
- per-Agent service recomposition;
- cross-owner live hot replacement;
- dynamic MCP Tool discovery or `tools/list_changed` publication;
- remote marketplace/signing UX;
- untrusted in-process Python;
- one Plugin object per Skill;
- a global Plugin context, service locator, or generic registration bag; or
- a second Runtime Profile, Graph Binder, Registration owner, or projector.

These remain later UPA slices and must not be pulled into PAP0-PAP7, including
PAP1B, merely to make the first authoring API appear feature-complete.
