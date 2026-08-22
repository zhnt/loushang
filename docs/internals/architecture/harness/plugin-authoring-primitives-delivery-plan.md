# Unified Plugin Authoring Primitives Delivery Plan

## Status

- Authority: implementation plan under the accepted Harness and Product owner
  boundaries; it does not amend those boundaries.
- Baseline: `harness/plugin-resolve-once` after the implemented UPA1 resolve-once
  chain and the first inert UPA2 `capability_provider` preflight/finalize slice.
- Delivery status: PAP0/PLC0 is implemented locally at `25cfc170`. No public
  Plugin SDK, typed Provider declaration codec, executable Plugin Definition
  evaluator, Capability owner admission bridge, or Plugin-sourced Capability
  bind is claimed as implemented by this document.
- Review status: self-reviewed in
  [Plugin Authoring Primitives Plan Review](plugin-authoring-primitives-plan-review.md).
  The first source-changing slice still requires an independent review against
  the source tree and executable gates.

This plan specializes the broader
[Unified Plugin Architecture](unified-plugin-architecture.md). The accepted
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
            facets=("semantic", "tools", "diagnostics"),
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
| Inert reservation/declaration | `PluginContributionReservation` / `PluginDeclaration` | Extend compatibly through typed payload codecs; do not add a second IR. |
| Inert selection | `PluginSelectionResolver` | Retain preflight/finalize; it never performs owner admission or binding. |

The current source does not yet provide:

- a typed `capability_provider` payload codec over
  `CapabilityBundleProvider` and exact factory/disposer locators;
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
optional disposer locator
normalized non-secret binding inputs
source/declaration/config/dependency fingerprints
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

- `PluginSymbolReference`: contained relative module/file locator, symbol,
  expected package digest, and execution model. It is serializable and never
  carries a callable.
- `CapabilityProviderDeclarationPayload`: strict versioned codec containing
  `CapabilityBundleProvider` data, factory/disposer references, normalized
  non-secret binding inputs, and requested authorities.
- `PluginDeclarationBuilder`: reservation-bound builder that can emit exactly
  one matching declaration per reservation and freezes after `build()`.
- `PluginDefinition`: internal Protocol whose `declare()` returns frozen IR via
  the builder. It receives no registries or live services.

### Approval and evaluation layer

- `PluginExecutionDecisionPort`: Approval-owner port for issue/query/consume/
  revoke of digest-bound execution decisions. It is implemented under
  `harness.approval`, not under the Plugin package.
- `PluginExecutionConsumptionReceipt`: immutable evidence binding the canonical
  subject, decision, policy/source-trust revisions, revocation epoch, expiry,
  instance revision, and one consumption transition.
- `PluginDefinitionEvaluator`: verifies the published revision handle and
  dependency lock, consumes the decision, enters the import-realm gate, loads
  the exact definition entrypoint, invokes only the declaration builder, and
  validates the returned IR. It cannot bind a contribution.

### Owner admission and Product selection layer

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
  -> PluginSelectionResolver.preflight()
       inert manifest facts only
       no import
  -> Approval owner issues/retains execution decision
  -> PluginDefinitionEvaluator
       consume current decision
       import exact verified entrypoint
       declaration builder only
  -> PluginSelectionResolver.finalize()
       exact reservation consumption
       PluginContributionCandidate
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
- add the reservation-bound internal builder;
- reject unknown fields, noncanonical values, owner/capability mismatch,
  duplicate requirements/facets, callable payloads, absolute/traversing
  locators, reservation mismatch, and post-freeze mutation;
- keep `PluginContributionKind` limited to the currently supported
  `capability_provider` arm.

Primary files:

```text
src/loushang/harness/resources/plugins/declarations.py
src/loushang/harness/resources/plugins/capability_provider.py    # new
src/loushang/harness/resources/plugins/authoring.py              # internal, new
tests/harness/resources/plugins/test_declarations.py             # new
tests/harness/resources/plugins/test_authoring.py                # new
```

Exit gate:

- JSON round-trip and canonical fingerprint fixtures are stable;
- builder output exact-matches hand-authored IR;
- the builder cannot import, register, bind, or access a Session;
- existing UPA2 preflight/finalize tests remain byte-for-byte compatible except
  for explicitly versioned fixture evolution.

Rollback: remove the new codec/builder; existing generic payload remains valid.

### PAP2: Durable Execution Decision Consumption

Scope:

- define the Plugin execution subject adapter under the existing Approval
  owner;
- persist issue/approve/deny/consume/revoke facts with expected revision,
  expiry, revocation epoch, source-trust revision, and actor/source provenance;
- implement atomic one-shot consumption and idempotent query/recovery;
- persist `ExecutionUseReservation` before import/launch start and define
  recovery for `CONSUMED_NOT_STARTED`, `STARTING`, and `STARTED`;
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
- crash recovery never replays a consumed decision into an untracked process;
- the Plugin package owns no second Approval store or pending lifecycle.

Rollback: disable executable declaration evaluation; inert inspection and
selection remain available.

### PAP3: Verified Plugin Definition Evaluation

Scope:

- introduce the internal `PluginDefinition` Protocol and evaluator;
- load only from the `VerifiedRevisionHandle` and locked import closure;
- consume the PAP2 decision immediately before crossing the import start point;
- invoke the PAP1 builder in a context containing only immutable locators,
  normalized configuration, engine features, and reservation views;
- finalize exact declaration/index identity and close unused reservations;
- record declaration provenance and evaluation diagnostics without leaking
  paths, environment values, secrets, or raw exceptions.

Primary files:

```text
src/loushang/harness/resources/plugins/definition.py              # new
src/loushang/harness/resources/plugins/import_realm.py            # new/private
src/loushang/harness/resources/plugins/selection.py
tests/harness/resources/plugins/test_definition.py                # new
tests/harness/resources/plugins/test_import_realm.py              # new
```

Exit gate:

- disabled/denied code is observably never imported;
- source mutation after publication cannot affect evaluation;
- undeclared transitive imports and conflicting locked closures fail closed;
- evaluation cannot publish any registry, registration, Resource, or Mount;
- definition failure consumes no second decision on retry.

Rollback: stop at inert preflight/finalize fixtures; no live owner state exists.

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

### PAP5: Owner-Preserving Component Host And Bind Bridge

Scope:

- add the narrow Capability Component Host;
- consume final activation approval against the admitted fingerprint and
  effective grants;
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
  semantic/tool/diagnostic facets;
- package the default LSP Bundle Provider through the PAP1 authoring SPI;
- adapt existing discovery/catalog/supervisor/document/tool objects behind one
  Provider factory and disposer;
- declare `harness.workspace` read/process requirements and consume only those
  facets;
- mount LSP through PAP4/PAP5 and delete deferred runtime and early Tool
  registration only after compatibility tests pass;
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
- Tools appear only with the mounted LSP Bundle and use its typed runtime facet;
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

Prerequisite: the existing UPA5 `coding.arch` and UPA6 `coding.base` production
slices are complete, or an accepted UPA revision explicitly changes that gate.
The public SDK must not be declared stable after only a synthetic fixture and
one LSP implementation. Before the prerequisite is met, this slice may maintain
an internal SDK candidate and author conformance suite, but it may not add the
stable `loushang.plugin` re-export shown in the target example.

Scope:

- freeze declaration IR v1 and engine-feature negotiation against the synthetic
  fixture and `coding.lsp` package;
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

This slice may begin after PAP5 if it consumes only internal stable records. It
must not delay PAP6 and must not publish a public SDK ahead of PAP7.

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
- mutable source changed after publication;
- wrong or missing dependency lock;
- declaration not reserved, reserved twice, or reservation left unconsumed;
- Definition tries to return a callable or access a registry;
- decision digest/scope/config/policy/trust mismatch;
- consume/revoke and consume/crash races;
- Product attempts to admit an owner-rejected candidate;
- owner admission expires between selection and activation;
- selected metadata and binding spec disagree;
- factory returns wrong facets or fails after staged registrations;
- cancellation before and after the Binder publication window;
- active Session observes disable/update;
- package source disappears before replay;
- disposer fails retryably; and
- same interpreter receives incompatible package/import closure.

## Definition Of Done

The authoring-primitives milestone is complete only after PAP0-PAP7 and PAP7's
UPA5/UPA6 prerequisites, not after the first builder lands. Completion means:

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
| PAP2 | 4–7 days | store/recovery and Product presentation adapter may split |
| PAP3 | 4–6 days | import-realm work dominates and should not be rushed |
| PAP4 | 3–5 days | owner admission and pure Product resolver can split |
| PAP5 | 4–6 days | Component Host and Session integration split after interfaces freeze |
| PAP6 | 6–10 days | LSP Provider migration, Session adoption, and peer-route deletion split by commit |
| PAP7 | 2–4 days | guide/fixtures after runtime contracts freeze |
| PAP8 | 3–5 days | filesystem/package adapters can split after catalog contract freezes |

PAP1 and PAP4 are data/pure-logic work. PAP2, PAP3, PAP5, and PAP6 are
security/lifecycle work and require regression-first sequencing. Schedule
estimates are not acceptance criteria.

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

These remain later UPA slices and must not be pulled into PAP0-PAP7 merely to
make the first authoring API appear feature-complete.
