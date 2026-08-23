# Plugin Capability Admission PAP4 Contract

Status: PAP4-1 generic Capability-owner eligibility/final admission and pure
Product Provider-closure selection implemented. The production `coding.lsp`
owner adapter, Component Host, activation approval, live Graph binding,
Resource/Tool/Command admission, public SDK and MCP expansion remain closed.

This document is the normative incremental companion to
[Unified Plugin Architecture](unified-plugin-architecture.md),
[Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md),
and
[Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md).

## Ownership And Non-Effect Boundary

`CapabilityProviderOwnerAuthority` is an immutable authority for exactly one
owner-qualified Capability and one `CapabilityProviderOwnerPolicy`. It is not a
global mutable owner registry. Only that authority constructs
`CapabilityProviderEligibilityGrant`, `CapabilityProviderAdmissionRecord`, and
the current `CapabilityProviderOwnerSnapshot`; their public constructors fail.

`ProductCapabilityProviderResolver` owns only Product selection over those
already-admitted records. It cannot construct or import the Owner authority or
policy and cannot manufacture, renew, widen, or revoke owner records. The
existing `RuntimeCapabilityGraphPlanner` remains the only graph validator and
receives only the resolver's already-unique Provider metadata tuple.

Neither module imports a factory, resolves a symbol, opens package bytes,
constructs a live Provider, binds a Graph, creates a Registration Scope,
publishes a generation, changes a Runtime Profile, or adds an MCP surface.

## Finalized Candidate Preparation

The internal upper-layer
`plugin_authoring.provider_admission.prepare_capability_provider_candidate()`
bridge accepts only one `PluginContributionCandidate` contained in the exact
finalized `PluginSelection`. It reuses the single strict
`CapabilityProviderDeclarationPayload.from_dict()` decoder and rechecks:

- selected Plugin/contribution identity and the published reservation envelope;
- Provider Capability, Plugin-derived source, and declaration selection rule;
- requested authorities and contribution execution model;
- Product-effective configuration against inert binding inputs;
- package content/dependency-lock digests, declaration/evidence fingerprints;
- Product, scope, policy, source-trust and Plugin-instance revision facts; and
- the selected Product authority ceiling.

The Capability layer never imports `plugin_authoring`; the bridge projects the
validated result into its pure records, preserving the acyclic dependency
direction. The adjacent candidate fingerprint canonically covers the complete Capability
Definition, Provider metadata and requirements, binding spec, declaration and
evidence fingerprints, package/dependency identities, Product/scope/policy,
source trust, instance revision and authority ceiling. The older semantic
fingerprint remains diagnostic only and is not admission identity.

`CapabilityProviderBindingSpec` contains only immutable package-local
factory/disposer locators projected into the lower Capability data type, exact
package and dependency digests, the Plugin and contribution identities, and
frozen non-secret JSON binding inputs. It contains no callable or upper-layer
authoring object.

## Owner Eligibility And Final Admission

The explicit policy fixes one Capability/owner, policy revision, revocation
epoch, allowed Provider IDs, allowed source-trust classes and authority
ceiling. Eligibility rejects a different owner, Provider or trust class,
untrusted source, incompatible contract, facets outside the Definition, or
authorities outside either Definition/Product/owner ceiling.

The eligibility record binds the exact candidate fingerprint, allowed facets
and authorities, source-trust policy revision, owner policy revision,
revocation epoch and half-open issue/expiry interval. It is not final admission
or Product selection.

Final admission exact-matches the same candidate and eligibility. It cannot
widen facets or authorities, outlive the eligibility interval, cross the owner
policy revision/revocation epoch, or start at/after eligibility expiry. Its
record binds the complete candidate, eligibility fingerprint, effective
facets/authorities and its own half-open issue/expiry interval.

## Product Closure Selection

`ProductCapabilityProviderSelectionPlanV1` contains Product ID, mandatory roots,
Product policy revision and explicit choices over Capability ID, Provider ID
and exact candidate fingerprint. Starting at every root, the resolver:

1. requires exactly one explicit choice;
2. requires exactly one matching owner admission and current Definition;
3. exact-matches Product ID, owner policy revision and revocation epoch;
4. rejects a not-yet-current or expired admission;
5. follows every required Provider requirement;
6. follows an optional requirement only when the Product supplied a choice and
   records either the satisfied or unsatisfied decision; and
7. rejects every choice outside the resulting transitive closure.

Unselected admitted alternatives are inert inputs and do not become closure
members. Cycles are retained as metadata for the existing Graph Planner to
diagnose; this resolver does not become a second graph validator.

`ResolvedCapabilityProviderSet` is Resolver-constructed, immutable and strictly
serializable. It contains one sorted Definition/Provider/binding/admission/
choice entry per closed Capability, sorted optional decisions, Product
provenance and one deterministic closure fingerprint. Its `providers` property
is the sole metadata tuple handed to the existing Graph Planner.

## PAP4-1 Regression Gate

- real document declarations traverse publish, preflight, decode, finalized
  Candidate preparation, owner eligibility and final admission without factory
  import;
- direct owner-record and resolved-set construction remains closed;
- required and optional closure behavior reaches the existing Graph Planner;
- zero, multiple, extra, fingerprint-skewed, stale, revoked and expired inputs
  fail closed with stable codes;
- outputs contain strict JSON data and no callables; and
- the new symbols remain absent from the frozen public Capability surface.

The next PAP4 slice adds the explicit `coding.lsp` owner policy adapter and
production declaration fixture. PAP4R/PAP5 and live binding follow separately;
they must not be folded into this pure selection layer.
