# Internal Architecture

[Internals](../README.md)

## Status

- Authority: normative — architecture catalog and reading-order policy
- Design status: accepted
- Implementation status: implemented
- Owner: Loushang architecture

This directory contains normative architecture, descriptive Current
architecture, generated facts, proposed designs, validation, references, and
history. Their authority is intentionally different.

The canonical design and governance process is
[Architecture Design And Governance Method](../architecture-method/README.md).
Its Loushang-specific binding is the
[Architecture Governance Profile](governance-profile.md).

## Start Here

For a whole-system architecture reading:

1. [Architecture Overview (AOD)](architecture-overview.md)
2. [Cross-Layer Architecture Principles](loushang-architecture-principles.md)
3. [Architecture Governance Profile](governance-profile.md)
4. [Subsystems And Architecture Scopes](subsystem.md)
5. [Current Observed Package Dependencies](generated/current-package-dependencies.md)
6. [Current-To-Target Gap Ledger](current-target-gap-ledger.md)
7. the relevant scope README and its accepted decisions

For a current implementation question:

1. source and executable tests;
2. generated Current facts;
3. current owner maps, especially
   [Harness Current Owner Map](harness/current-owner-map.md);
4. accepted boundaries and ARDs;
5. proposed designs, plans, ledgers, reports, references, and history.

For a design question:

1. strategy and requirements;
2. the AOD and architecture principles;
3. parent-scope placement and boundary;
4. scope requirements, specification and final component model;
5. accepted key designs and ARDs;
6. proposed and validation material.

## Truth Planes

| Plane | Role | Normal location |
| --- | --- | --- |
| Facts | Objective repository state produced by source, tests, or generators | `generated/`, source, tests |
| Current | Evidence-linked interpretation of implemented ownership and runtime shape | owner maps and scope README Current sections |
| Target | Accepted normative architecture | AOD, principles, requirements, specifications, component models, accepted ARDs |
| Delta | Explicit Current-to-Target difference | scope gap ledgers and concise README summaries |
| History | Superseded decisions and completed migration material | `history/`, ledgers, reports |

Do not treat Target as implemented, Current as automatically desirable, or
History as a current ownership source. When Current and Target differ, record a
Delta rather than blending the two in one unlabeled diagram.

## Architecture Scope Tree

The top-level scopes are:

- [AI](ai/README.md)
- [Agent](agent/README.md)
- [Channel](channel/README.md)
- [Coding](coding/README.md)
- [Harness](harness/README.md)
- [Harness TUI](harnesstui/README.md)
- [HarnessWork](harnesswork/README.md)
- [Method](method/README.md)
- [TUI](tui/README.md)
- [Work compatibility/integration](work/README.md)
- [Ontology](ontology/README.md)
- Foundation, represented in the AOD and subsystem map because it is a small
  product-neutral base rather than a large independent architecture package

Established nested Architecture Scopes include:

- [Coding LSP](coding/lsp/README.md), a Coding-owned Product Capability;
- [Coding Arch](coding/arch/README.md), a Coding-owned architecture-analysis
  Product Capability;
- [Harness Multi-Agent](harness/multiagent/README.md), a Harness-owned technical
  capability.

A nested scope is not automatically a top-level subsystem. The parent owns its
placement, composition policy, and sibling relationships; the child owns its
black-box contract and internal component model.

## Scope Documentation Rule

Each scope expands only its direct children. The AOD does not describe LSP
Client internals, Coding does not duplicate Harness internals, and nested scopes
represent their parent and neighboring scopes as black boxes.

Complex scopes may use glossary, local principles, requirements, system
context, boundary, specification, component model, interaction, dependency,
traceability, interfaces, key designs, decisions, generated facts, validation,
reference, and history. Glossary and principles inherit from the parent; local
files contain only domain-specific additions. Smaller scopes should combine
these concerns rather than create empty files.
Use the
[Architecture Scope README Template](../architecture-method/templates/architecture-scope-README.md)
when establishing or normalizing a scope entrypoint.

## Current Facts And Architecture Gates

[Current Observed Package Dependencies](generated/current-package-dependencies.md)
is generated from Python source. It is an observed physical import graph, not a
normative dependency policy or semantic runtime sequence.

Architecture tests under `tests/architecture/` enforce intended, required, and
forbidden dependency direction. Generated facts and normative gates complement
each other:

- facts reveal what exists;
- gates decide what is allowed;
- current owner maps explain ownership;
- target designs describe accepted evolution.

Run `make check-architecture-docs` to verify the generated package graph,
canonical document status metadata, repository-relative links, and retired-mode
drift guards.

## Current And Target Examples

- [Harness Current Owner Map](harness/current-owner-map.md) is the descriptive
  owner-map pattern.
- [Harness Capability Dependency And Mount Lifecycle](harness/capability-dependency-and-mount-lifecycle.md)
  is an accepted Target whose graph owners are implemented while accepted
  Capability IDs may still differ from production-mounted coverage.
- [TUI Traceability Matrix](tui/native-terminal-core/traceability-matrix.md)
  demonstrates requirements-to-design-to-test traceability.
- [Coding LSP](coding/lsp/README.md) demonstrates a nested Product Capability
  architecture package.

## Draft, Validation, Reference, And History

- [Architecture Drafts](drafts/README.md) contain unresolved proposals and are
  not accepted requirements.
- `validation/` records architecture conclusions drawn from tests, comparisons,
  or spikes.
- `reference/` records external or comparative material and is never Loushang
  architecture authority.
- `history/` preserves superseded designs and terminology for traceability.

Historical terminology and old paths may remain in non-live material. Do not
rewrite history merely to match current package names, but make its historical
status unmistakable and keep it out of the current reading path.

## Change Governance

A change that crosses an Architecture Scope boundary must update the affected
child and its nearest common parent. New sibling dependencies require both
child contracts, the parent dependency graph, and an executable architecture
gate. Top-level ownership changes also require the AOD, subsystem map, and an
ARD or accepted boundary decision.

Completed migration records remain traceability evidence but must not be used
as the resulting architecture specification.
