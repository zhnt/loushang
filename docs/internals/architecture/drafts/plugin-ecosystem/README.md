# Plugin Ecosystem Architecture Draft Package

## Status

- Authority: proposed — non-normative cross-scope draft catalog
- Design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture; affected owners include Harness, Product,
  Resource, Extension, Capability, configuration, execution, and distribution

## Purpose

This package is the single entrypoint for the proposed Product, package,
Plugin, executable Resource, and client authoring architecture. It groups the
proposal documents with their independent review evidence without promoting
either into accepted architecture.

Current source, tests, accepted Harness boundaries, and accepted ARDs remain
authoritative. The documents here must not be implemented as one monolithic
contract or accepted merely because their review findings were incorporated.

## Reading Order

1. [Unified Product, Package, And Plugin Architecture](unified-product-package-plugin-architecture.md)
   defines the ecosystem vocabulary, identity model, lifecycle, and proposed
   cross-product control plane.
2. [Plugin Management And Isolated Execution Improvement Plan](plugin-management-and-isolated-execution-improvement-plan.md)
   maps executable Skills and Plugins onto one-shot and Worker execution shapes
   and the existing Harness delivery spine.
3. [Client Plugin SDK And Embedded Authoring Experience](client-plugin-sdk-and-embedded-authoring-experience.md)
   projects those strict runtime contracts into a deliberately small authoring
   surface for native Resources, packages, built-ins, and Workers.
4. Read the linked reviews when evaluating acceptance, security, authoring
   ergonomics, or delivery readiness. They are validation evidence, not a
   second architecture authority.

## Artifact Map

| Artifact | Type | Authority | Intended use |
| --- | --- | --- | --- |
| [Unified Product, Package, And Plugin Architecture](unified-product-package-plugin-architecture.md) | Architecture proposal | Proposed | Decide shared ecosystem vocabulary, ownership, identity, lifecycle, and distribution boundaries |
| [Plugin Management And Isolated Execution Improvement Plan](plugin-management-and-isolated-execution-improvement-plan.md) | Delivery plan | Proposed | Sequence executable Resource and Plugin runtime work after owner decisions are accepted |
| [Client Plugin SDK And Embedded Authoring Experience](client-plugin-sdk-and-embedded-authoring-experience.md) | Authoring contract proposal | Proposed | Define the smallest author-facing projection over accepted runtime owners |
| [Independent reviews](reviews/README.md) | Validation evidence | Descriptive | Preserve independent findings, dispositions, and remaining acceptance gates |

## Acceptance Boundary

This draft package is intentionally broader than any one decision. Formal
acceptance should extract small owner decisions instead of relabeling the whole
directory as normative. At minimum, acceptance should separate:

1. artifact/source authority, installation scope, release provenance, and
   executable-source revision identity;
2. native Skill script ownership, verified one-shot execution, isolated Worker
   placement, containment, and Approval-use semantics; and
3. contribution selection, configuration ownership, mutable state, and
   exact-owner lifecycle authority.

Each accepted decision must update the affected owner documents and add
executable architecture or conformance gates. Delivery sequencing remains a
plan, SDK examples remain experimental until implemented, and review files
remain validation evidence after acceptance.

## Independent Reviews

### Plugin management and isolated execution

- [Architecture review](reviews/plugin-management-and-isolated-execution-architecture-review.md)
- [Authoring review](reviews/plugin-management-and-isolated-execution-authoring-review.md)
- [Security review](reviews/plugin-management-and-isolated-execution-security-review.md)

### Client SDK and embedded authoring

- [Architecture review](reviews/client-plugin-sdk-and-embedded-authoring-experience-architecture-review.md)
- [Authoring review](reviews/client-plugin-sdk-and-embedded-authoring-experience-authoring-review.md)
- [Security review](reviews/client-plugin-sdk-and-embedded-authoring-experience-security-review.md)

## Adjacent Architecture

- [Cross-Scope Architecture Decisions](../../decisions/README.md)
- [Harness Unified Plugin Architecture](../../harness/unified-plugin-architecture.md)
- [Harness Process Hosting Boundary](../../harness/process-hosting-boundary.md)
- [Harness Workspace Execution Boundary](../../harness/workspace-execution-boundary.md)
- [Project-Declared Configuration And Pluggable Conversation Persistence](../project-declared-configuration-and-pluggable-conversation-persistence.md)
