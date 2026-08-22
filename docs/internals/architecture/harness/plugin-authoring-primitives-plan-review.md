# Review: Unified Plugin Authoring Primitives Delivery Plan

## Verdict

**Approve with staged implementation gates.** The plan is suitable to begin
PAP0; PAP1 may begin only after PAP0 restores the architecture baseline to
green. PAP2 and every later security/lifecycle slice require a fresh
source-backed review before implementation; this verdict is not approval to
merge PAP0-PAP7, including PAP1B, as one change or to publish the public SDK
early.

The review found four priority errors in the initial proposal and the delivery
plan now incorporates their corrections:

1. a Resource-heavy `coding.base` slice could not prove the executable
   Definition / Provider / Consumer lifecycle, so the plan now uses a synthetic
   conformance fixture followed by `coding.lsp`;
2. a public author API before durable execution-decision consumption would make
   an unsafe path easy to use, so the builder remains internal until Approval,
   verified evaluation, admission, and binding gates pass;
3. ordinary Plugin authors cannot publish arbitrary Capability Definitions, so
   Definition ownership remains with the Product/Capability namespace owner;
4. publishing a stable SDK after only one production Provider would contradict
   the UPA delivery sequence, so PAP7 now requires the `coding.arch` and
   `coding.base` production evidence or an explicit accepted UPA revision.

The baseline blocker identified by the original review is closed locally at
`25cfc170`. PAP0/PLC0 removed the duplicated manifest locator, classified exact
verified-revision/mount sinks under named owners, and restored the architecture
suite to green. The
[PLC0 baseline](plugin-lifecycle-plc0-baseline.md) records the evidence. PAP1
was implemented locally at `2ebac237` and review-hardened through `8a3c94fd`
without a public export or live effect.
Its source review also corrected the planned placement from
`resources.plugins` to the higher internal `plugin_authoring` composition layer
after the dependency gate demonstrated that the original placement would form
a `resources <-> capabilities` cycle. A tracking issue and independent review
are still required before remote PR publication.

The implementation review found and closed three issues before PLC1B: Windows
drive/backslash locators could bypass a POSIX-only containment check; Builder
identity facts could be independently assembled instead of deriving from one
preflight reservation; and a weaker public `from_declaration()` method sat
beside the reservation-bound decoder. The hardened slice rejects both POSIX and
Windows traversal forms, derives a narrow retained view from an exact
`PluginDeclarationReservation`, and exposes only the reservation-bound
declaration decoder.

No unresolved finding requires a second Graph, Profile resolver, Registration
owner, effective projector, Plugin context, or Skill-specific Plugin runtime.

## Review Scope And Evidence

The review compared the plan with:

- [Unified Plugin Architecture](unified-plugin-architecture.md), especially its
  non-negotiable invariants, current UPA1/UPA2 baseline, delivery sequence, and
  acceptance gates;
- [Capability Composition Lifecycle Authority Plan](composition-lifecycle-authority-plan.md),
  especially one publication authority per owned live object and the completed
  Session-owned Graph;
- `harness.capabilities.contracts`, `providers`, `provider_binding`,
  `graph_planning`, `graph_binding`, and `graph_runtime`;
- `harness.runtime.registration`;
- `harness.resources.plugins.declarations`, `selection`, `authority`,
  `revisions`, and the public Plugin export surface;
- `harness.session.agent_product`, where the current built-in Session Graph
  definitions, Providers, bindings, and roots are assembled directly;
- the current Coding LSP binding, discovery, supervisor, tools, and deferred
  runtime paths; and
- the architecture bypass inventory in
  `tests/architecture/test_unified_plugin_architecture.py`.

This is a self-review. It does not replace an independent reviewer for PAP2,
PAP3, PAP5, or the `coding.lsp` cutover.

## Findings

### P0-01 — Do not use `coding.base` as the executable primitive proof

**Evidence.** The accepted UPA classifies `coding.base` as optional prompts,
Skills, commands, Tool packs, and adapters aggregated into existing
`harness.resources` and `harness.session`; it does not add a top-level Graph
node. The current Graph contracts prove Provider construction and Consumer
facets only for mounted Capabilities.

**Risk.** Calling a Resource contribution sample the Definition / Provider /
Consumer production proof would leave owner admission, Product Provider
selection, Graph binding, Consumer facet capture, and exact Capability disposal
untested.

**Correction applied.** The plan uses a synthetic Capability fixture to prove
the mechanism and `coding.lsp` as the first production executable vertical
slice. `coding.base` remains a later Resource/Composition Set adoption.

### P0-02 — Approval consumption must precede executable authoring

**Evidence.** Current `PluginSelectionResolver` accepts an inert
`PluginExecutionDecisionRecord`, but the UPA current-gap section explicitly says
durable Approval-owner consumption, entrypoint loading, Provider construction,
and Graph publication are not implemented. Current approval runtime contracts
do not yet provide the Plugin-specific digest/policy/trust/revocation/start
reservation protocol required by UPA.

**Risk.** Loading a Plugin Definition after a positive in-memory record would
collapse “selected” into “authorized to execute,” make revocation races
undefined, and allow a crash between one-shot consumption and external process
tracking.

**Correction applied.** PAP1B first groups exact reservation closures by source
and distinguishes a document `data_only` gate from an in-process
`execution_preflight` gate, so strict document decoding never invents execution
authority. Those gates are not final evidence: document decoding emits
`document_decoded`, while PAP2/PAP3 must produce `in_process_evaluated` bound to
one durable group consumption receipt before candidate finalization. The Plugin
subsystem does not own another approval store. The second PLC1B documentation
review further requires pending to expose proposed subjects only, a fresh full
preflight after approval, one group-owned gate, Host-only Batch/evidence
construction, and one Coordinator-owned finalize/abort/expire transition.

### P0-03 — Stable public SDK cannot precede production combination evidence

**Evidence.** The accepted UPA delivery sequence places public SDK publication
after the LSP, Base, and Architecture Coding slices. The initial draft of this delivery
plan allowed PAP7 after only a synthetic fixture and LSP.

**Risk.** A stable API could freeze Provider-only assumptions before Resource
composition, a second Capability, optional dependencies, and Product
Composition Sets prove the declaration IR and feature negotiation.

**Correction applied.** PAP7 may maintain an internal SDK candidate, but stable
`loushang.plugin` exports require the accepted UPA5 `coding.base` and UPA6
`coding.arch` evidence.

### P0-04 — The source baseline is not currently architecture-test green

**Evidence.** Running
`tests/architecture/test_unified_plugin_architecture.py` on the current branch
reports three failures: the UPA document phrase assertion, an additional static
`plugin.json` site under verified revisions, and additional qualified read/open
sinks under verified revisions and package mounts.

**Risk.** Starting PAP1 from a red inventory would make it impossible to tell
whether a new parser/path bypass came from the authoring slice or the preceding
resolve-once work.

**Closure.** PAP0/PLC0 inspected each site at `25cfc170`, removed the duplicated
manifest path derivation, and updated only exact qualified functions for
verified revision publication/opening and Package Resource reads. No broad
directory exemption was added, and the architecture suite is green.

### P1-01 — Definition ownership and Provider authoring must stay distinct

**Evidence.** `CapabilityDefinition` requires an owner-qualified Capability ID.
The Graph Planner rejects Capabilities owned by another Product. UPA assigns
eligibility and final admission to the exact Capability owner.

**Risk.** A generic `define_capability()` available to every Plugin would let a
package claim another owner's namespace or create an alternate Definition
catalog.

**Correction applied.** The plan reuses the existing owner-published
`CapabilityDefinition`. Ordinary authors declare Providers and
`CapabilityRequirement` Consumers only. Delegated Definition publication is
explicitly deferred.

### P1-02 — The authoring layer must be a codec/builder, not a second semantic model

**Evidence.** Existing source already defines `CapabilityDefinition`,
`CapabilityRequirement`, `CapabilityBundleProvider`,
`CapabilityBundleProviderBinding`, `CapabilityProviderContext`, and
`CapabilityBundleValue`. It also already has canonical Plugin declaration and
selection records.

**Risk.** New public `ProviderContribution`, `ConsumerRequirement`, or
`RegistrationLease` classes with overlapping semantics would create conversion
skew and ambiguous ownership.

**Correction applied.** PAP1 adds a strict payload codec and reservation-bound
builder over existing semantic types. New admission and selection records exist
only where current types have no equivalent authority fact.

### P1-03 — Owner admission and Product selection cannot be one resolver result

**Evidence.** UPA invariant 3 gives the Capability owner eligibility and final
admission authority, while a Product-owned resolver chooses among already
admitted complete-Bundle candidates. The Graph Planner is a validator, not a
Provider selector.

**Risk.** A single `resolve_provider()` result could allow Product policy to
invent effective grants, or let the Capability owner silently select Product
composition.

**Correction applied.** PAP4 retains separate eligibility, final admission,
Product selection, and Graph validation records with exact fingerprint
matching.

### P1-04 — Session integration must not absorb top-level Providers into the Resource candidate

**Evidence.** CLA preserves one root-owned `StagedResourceCompositionCandidate`
for Resource/Bundle-private Profile state. Current `AgentProductSession` owns
the Graph runtime and directly assembles definitions, Provider metadata, and
bindings beside that candidate.

**Risk.** Adding Plugin Provider inputs to the Resource candidate would make the
Resource owner a peer Graph composition authority and obscure rollback.

**Correction applied.** PAP5 introduces separate immutable Session Capability
composition inputs, retains the existing Resource candidate shape, and invokes
the existing Binder once from the Session root.

### P1-05 — Skill is a later Resource-provider adopter, not the first Plugin runtime

**Evidence.** Current Skill behavior is represented by `SkillDescriptor`,
filesystem/resource discovery, activation, and prompt projection. UPA classifies
Skill as a `resource_item` and explicitly rejects making every Skill a top-level
Capability.

**Risk.** Refactoring Skill first could create a parallel Provider registry,
precedence engine, and disposer contract that the common authoring/runtime path
would later replace.

**Correction applied.** PAP8 retains individual Skills as Resources and
pluginizes only source/provider mechanisms where executable discovery is
required. It may consume stable internal records after PAP5 but cannot publish
the public SDK early or delay LSP.

### P2-01 — PAP2 is a separate high-risk design, not a helper class

**Evidence.** Durable issue/consume/revoke, expected revisions, recovery, and
process-start reservations cross approval persistence, source trust, Plugin
instance state, and host process tracking.

**Risk.** Implementing PAP2 inside `selection.py` as an in-memory convenience
would appear to close the security gate while leaving crash and revocation
behavior undefined.

**Required gate.** Before PAP2 source changes, write a focused Approval-owner
boundary note or amend the accepted approval boundary, including storage,
transaction, lock order, recovery, redaction, and presenter adapter ownership.
PAP2 must merge independently before PAP3.

### P2-02 — Verified Python import closure may be unavailable on some platforms

**Evidence.** Python imports can traverse `sys.path`, `sys.modules`, native
extensions, and transitive dependency loaders. A content-addressed top-level
file path alone does not prove the imported closure.

**Risk.** A nominal `VerifiedRevisionHandle` could still load undeclared or
changed transitive modules.

**Required gate.** PAP3 must demonstrate locked-closure loading behavior with
negative fixtures. Unsupported/native/incompatible cases return a structured
restart/isolated-worker requirement; they must not fall back to ordinary import.

### P2-03 — The LSP cutover must delete direct and deferred peers

**Evidence.** Current Coding source exposes direct LSP definitions at bootstrap,
`bind_coding_lsp_runtime`, `DeferredCodingLspRuntime`, early Tool-pack
registration, and Session construction arguments. The architecture inventory
already tracks LSP Tool registration as a live-binding sink.

**Risk.** Adding a Plugin Provider while retaining those paths would produce a
facade over duplicate construction and Tool publication authority.

**Required gate.** PAP6 needs an explicit before/after caller inventory and a
final peer-route deletion commit. Compatibility may forward into the new path
temporarily but cannot independently construct or publish LSP state.

### P3-01 — Decorators are ergonomics, not the primitive

**Evidence.** The target example uses `@plugin_definition`, while the security
boundary is the strict serializable IR and verified evaluator.

**Risk.** Freezing decorator behavior before payload/feature compatibility is
proven would make source sugar a de facto versioned API.

**Disposition.** Retain the example as a target. Implement explicit internal
builders first; publish decorators only with PAP7 if they reduce code without
adding implicit discovery or authority.

## Retain / Rewrite / Defer

### Retain

- existing Capability semantic records and typed facets;
- existing Graph Planner/Binder/Runtime/Projector;
- existing Registration Scope ownership;
- resolve-once published package/revision path;
- inert Plugin reservation, declaration, preflight, and finalize split;
- CLA Resource candidate and Session composition root;
- complete committed Model Input as replay authority.

### Rewrite through one-way adapters

- generic declaration payload into a typed `capability_provider` codec;
- arbitrary in-memory Plugin decision input into a durable Approval-owner
  reference and consumption receipt;
- direct Session Provider tuple construction into root-owned immutable
  composition inputs;
- direct/deferred LSP construction and early Tool registration into one mounted
  `coding.lsp` Bundle;
- later, Skill discovery/load callers into one Resource-owned catalog.

### Defer

- stable public SDK until UPA5/UPA6 evidence;
- generic `capability_component` authoring until complete-Bundle LSP is stable;
- generic event/hook and Agent Definition SDKs;
- private Plugin data generations;
- dynamic MCP surfaces;
- marketplace and remote publication UX;
- per-Agent recomposition and cross-owner live HMR;
- untrusted in-process Python; and
- per-Skill Plugin identity.

## First Production PR Gate

The first source-changing PR should be PAP1, after PAP0 baseline fixtures. It is
approved only if it remains inert and satisfies all of the following:

1. imports no Plugin entrypoint and launches no process;
2. adds no public stable SDK export;
3. uses existing Capability semantic types rather than semantic duplicates;
4. round-trips one strict `capability_provider` payload through canonical JSON;
5. binds the payload to exactly one existing manifest reservation;
6. rejects callables, unknown fields, traversal/absolute locators, owner
   mismatch, duplicate facets/requirements, and post-freeze mutation;
7. leaves `PluginSelectionResolver` as inert preflight/finalize only;
8. changes no Graph, Profile, Registration, Resource, Extension, or Session
   publication behavior;
9. passes focused Plugin tests, the architecture inventory, Ruff for changed
   Python, and `git diff --check`; and
10. can be rolled back by deleting the codec/builder without data migration or
    live-state cleanup.

## Review Conclusion

The priority decision is sound after revision: build the common owner-preserving
authoring path first, prove it with a real executable Capability, and converge
Skill afterward as a lightweight Resource-provider user. The plan preserves the
stronger Loushang properties that a universal Plugin context would erase:
owner admission, pure Product selection, one Graph publisher, exact reversible
registration ownership, and complete Model Input reconstruction.

PAP0/PLC0 and inert PAP1/PLC1A are complete locally. PAP1B/PLC1B is the next
source-changing declaration slice; PAP2 remains the next high-risk design
review boundary and may not land before PLC2's management core. Skipping either
boundary to reach an impressive Plugin demo would invalidate the architecture's
execution-trust claim. Issue/PR attachment and independent review remain
publication gates, not reasons to weaken the local implementation.
