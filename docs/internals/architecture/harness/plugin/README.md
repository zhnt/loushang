# Loushang Plugin Architecture

## Status

- Authority: normative catalog for active Harness Plugin documents; it does
  not make a proposed child design accepted.
- Design status: mixed and explicitly labeled per document. Architecture V2 is
  independently reviewed and ready for owner acceptance; incremental contracts
  record implemented slices; plans remain delivery records; baselines and
  reviews are evidence.
- Implementation status: partial, summarized by `architecture.md` and tracked
  in the lifecycle plan.
- Owner: `loushang.harness` Plugin architecture scope; contribution runtime
  authority remains with each exact domain owner.

This directory is the single entrypoint for active Harness Plugin architecture,
delivery, frozen contracts, baselines, and review evidence.

## Authority Order

When documents disagree, use this order:

1. current source and executable tests for implemented behavior;
2. accepted exact-owner runtime boundaries linked below;
3. [Plugin Architecture V2](architecture.md) for the canonical target and
   cross-document decisions;
4. frozen incremental contracts for their exact implemented slices;
5. the lifecycle plan for sequencing and delivery status;
6. baselines and reviews as evidence, not current design authority; and
7. retired drafts and historical Coding designs only for design archaeology.

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

These contracts refine the architecture only inside their stated versions and
implemented slices. An unimplemented Worker, Skill-action, remote-service, or
public SDK shape cannot be inferred from them.

## Baselines And Prior Reviews

- [PLC0 Baseline](plugin-lifecycle-plc0-baseline.md)
- [PLC1A Baseline](plugin-lifecycle-plc1a-baseline.md)
- [Resource Catalog RCP0 Baseline](resource-catalog-rcp0-baseline.md)
- [Lifecycle Plan Review](plugin-lifecycle-coding-pluginization-review.md)
- [Authoring Plan Review](plugin-authoring-primitives-plan-review.md)

Baselines freeze earlier source and authority facts. Reviews record why prior
plans changed. They are not alternate architecture documents and may contain
commit-relative or line-relative citations from the revision reviewed.

The independent V2 acceptance reviews required by issue `#502` passed after
blocking findings were corrected and re-reviewed:

- [Architecture Review](reviews/2026-08-27-v2-architecture-review.md)
- [Security Review](reviews/2026-08-27-v2-security-review.md)
- [Developer Experience Review](reviews/2026-08-27-v2-developer-experience-review.md)

These reviews make V2 ready for owner acceptance; they do not self-approve its
status. A conditional or rejected review never counts until the same reviewer
verifies the correction.

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

## Retired Design Inputs

The former
[Plugin Ecosystem Draft Package](../../drafts/plugin-ecosystem/README.md)
is retained as design history. Its package/plugin ecosystem, isolated execution,
and client SDK proposals were reconciled into `architecture.md`. It no longer
defines a competing target or PLC8/PLC9 sequence.

Historical Coding Plugin V1 documents and superseded Coding package/plugin
facades are likewise non-authoritative. New work starts here and follows the
exact owner documents above.

## Placement Rule

Place a document in this directory when its primary subject is Plugin identity,
manifest/declaration, desired state, Plugin execution trust, authoring, Plugin
Instance lifecycle, or Plugin-to-owner admission. Keep a document with its
domain owner when Plugin is only one consumer of that boundary.

New documents must declare:

- whether they are architecture, an incremental contract, a delivery plan, a
  baseline, or review evidence;
- current versus target implementation status;
- the sole writer for every new state;
- the architecture or owner boundary they refine; and
- which earlier document, if any, they supersede.
