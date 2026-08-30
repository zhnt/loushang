# Loushang Plugin Architecture

## Status

- Authority: normative catalog for active Harness Plugin documents; it does
  not make a proposed child design accepted.
- Design status: mixed and explicitly labeled per document. Architecture V2 is
  independently reviewed and owner accepted under issue `#502`; incremental
  contracts record implemented slices; plans remain delivery records; baselines
  are implementation evidence.
- Implementation status: partial, summarized by `architecture.md` and tracked
  in the lifecycle plan.
- Owner: `loushang.harness` Plugin architecture scope; contribution runtime
  authority remains with each exact domain owner.

This directory is the single entrypoint for active Harness Plugin architecture,
delivery, frozen contracts, and baselines.

## Authority Order

When documents disagree, use this order:

1. current source and executable tests for implemented behavior;
2. accepted exact-owner runtime boundaries linked below;
3. [Plugin Architecture V2](architecture.md) for the canonical target and
   cross-document decisions;
4. frozen incremental contracts for their exact implemented slices;
5. the lifecycle plan for sequencing and delivery status;
6. baselines as implementation evidence, not current design authority; and
7. superseded ARDs only for design archaeology.

The architecture document answers what the Plugin system is and which owner
controls each state. The lifecycle plan answers when a target is delivered.
Neither may silently override a narrower implemented owner contract.

## Start Here

- [Plugin Architecture V2](architecture.md) is the only active Plugin
  architecture master document. It defines first principles, orthogonal
  artifact/identity/contribution/execution/trust/lifetime axes, exact ownership,
  Skill semantics, Worker and remote-service topology, security, and the public
  authoring ladder.
- [Plugin Lifecycle And Coding Pluginization Plan](plugin-lifecycle-coding-pluginization-plan.md)
  is the only coordinating PLC0-PLC9 delivery plan. Its status section tracks
  the current implementation, including the production `coding.lsp` route.
- [Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md)
  refines Definition/Provider/Consumer, Component Host, declaration builder,
  admission, and future public SDK delivery.
- [Resource Catalog And Source Pluginization Plan](resource-catalog-pluginization-plan.md)
  owns the Resource/Skill catalog convergence and the rule that mechanisms may
  be Plugin components while individual Skills remain Resources.

## Frozen Contracts

- [PLC1B Declaration Foundation](plugin-declaration-foundation-plc1b-contract.md)
  freezes declaration sources, strict wire records, contribution kinds,
  fingerprints, aggregate claims, and version diagnostics.
- [PLC2 Lifecycle Contract](plugin-lifecycle-plc2-contract.md) freezes durable
  install/enable/disable/update, retirement handoff, Instance leases, cleanup,
  repair, and GC evidence.
- [PLC3 Execution Trust Contract](plugin-execution-trust-plc3-contract.md)
  freezes one-shot execution decisions, use consumption, verified Definition
  evaluation, and recovery.
- [PAP4 Capability Admission Contract](plugin-capability-admission-pap4-contract.md)
  freezes exact Capability-owner admission and Product Provider selection.
- [Phase 5B Continuity Provider Foundation](continuity-provider-phase5b-contract.md)
  freezes portable read-only Provider contracts, Product lifecycle bridging,
  and the handoff requirements for later Plugin admission.
- [Phase 5C Continuity Provider Plugin Lifecycle](continuity-provider-phase5c-contract.md)
  implements the installed-Plugin declaration, exact owner-component
  lifecycle, sealed process composition, revocation linearization, durable
  recovery barrier, and Package cleanup handoff.
- [Phase 5D Continuity Mutation Foundation](continuity-mutation-phase5d-contract.md)
  implements exact deletion proposals, opaque Product authorization evidence,
  cancellation-safe settlement, and the lifecycle handoff required before an
  installed Plugin may expose mutation.
- [Phase 5E Installed Continuity Mutation Lifecycle](continuity-mutation-phase5e-contract.md)
  implements the durable Product deletion journal, generation-gated installed
  Provider adapter, startup recovery barrier, and explicit Coding binding.
- [Phase 5F Continuity Production Composition and Operations](continuity-production-phase5f-contract.md)
  binds that lifecycle to real Coding configuration, `--resume`, TUI stable
  references, canonical machine state, recovery diagnostics, retry, and
  process-owned shutdown.
- [RCP5 Resource Catalog Skill Convergence](resource-catalog-rcp5-contract.md)
  freezes the conservative, exact-generation typed Skill Consumer and the
  ordered deletion of legacy Skill/Resource peer authority. Its first slice is
  internal and does not authorize Product cutover.

These contracts refine the architecture only inside their stated versions and
implemented slices. An unimplemented Worker, Skill-action, remote-service, or
public SDK shape cannot be inferred from them.

## Baselines

- [PLC0 Baseline](plugin-lifecycle-plc0-baseline.md)
- [PLC1A Baseline](plugin-lifecycle-plc1a-baseline.md)
- [Resource Catalog RCP0 Baseline](resource-catalog-rcp0-baseline.md)

Baselines freeze source and authority facts required by later contracts. Review
discussion and acceptance evidence belong to issue `#502`, its delivery PR,
and Git history; they are not maintained as parallel architecture documents.

## Runtime Boundaries That Remain Outside This Directory

Plugin contributions must integrate with these existing authorities rather
than reimplement them:

- [Capability Dependency And Mount Lifecycle](../capability-dependency-and-mount-lifecycle.md)
- [Product Capability Composition Core](../product-capability-composition-core.md)
- [Capability Variation And Replacement](../capability-variation-and-replacement-boundary.md)
- [Extension And Resource Generation Lifecycle](../extension-generation-lifecycle-boundary.md)
- [Extension Runtime Core](../extension-runtime-core-boundary.md)
- [Contribution Inventory](../contribution-inventory-boundary.md)
- [Effective Runtime Diagnostics](../effective-runtime-diagnostics-boundary.md)
- [Runtime Provenance](../runtime-provenance-boundary.md)
- [Capability Catalog](../capability-catalog.md)
- [Current Owner Map](../current-owner-map.md)
- [OEM Extension Architecture](../oem-extension-architecture.md)
- [Process Hosting Boundary](../process-hosting-boundary.md)
- [Sandbox Runtime Boundary](../sandbox-runtime-boundary.md)

They remain outside `plugin/` because their primary reason to change is their
own runtime domain. Moving them here would make Plugin appear to own the Graph,
Resource generations, process mechanics, or containment.

## Superseded Decisions

Superseded ARDs may remain in their owning domain as explicitly historical
decision records. Retired drafts, dated replacement designs, and review
transcripts are recovered from Git/issue history rather than kept as searchable
competitors. New Plugin work starts here and follows the exact owner documents
above.

## Placement Rule

Place a document in this directory when its primary subject is Plugin identity,
manifest/declaration, desired state, Plugin execution trust, authoring, Plugin
Instance lifecycle, or Plugin-to-owner admission. Keep a document with its
domain owner when Plugin is only one consumer of that boundary.

New documents must declare:

- whether they are architecture, an incremental contract, a delivery plan, or
  a baseline;
- current versus target implementation status;
- the sole writer for every new state;
- the architecture or owner boundary they refine; and
- which earlier document, if any, they supersede.
