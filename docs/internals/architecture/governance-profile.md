# Loushang Architecture Governance Profile

## Status

- Authority: normative — Loushang method adoption profile
- Design status: accepted
- Implementation status: partial
- Owner: Loushang architecture

## Purpose

This document binds the project-neutral
[Architecture Design And Governance Method](../architecture-method/README.md)
to the Loushang repository. The method defines how architecture work is done;
this profile defines which Loushang artifacts, scopes, owners, evidence, and
local practices realize that method.

The profile is deliberately separate from both the method and the
[Architecture Overview](architecture-overview.md):

- `architecture-method/` owns reusable process, artifact semantics and
  templates;
- this profile owns Loushang-specific adoption and governance policy;
- `architecture/` owns Loushang Current, Target, Delta and History;
- source, generated facts and executable tests establish repository Facts.

## Adopted Local Practices

Loushang combines four proven practices:

- the AI design method for black-box framing, candidate discovery, function
  mapping and component refinement;
- the [Harness Current Owner Map](harness/current-owner-map.md) pattern for
  concise Current ownership and authority ordering;
- the [TUI Traceability Matrix](tui/native-terminal-core/traceability-matrix.md)
  pattern for requirements-to-design-to-test traceability;
- the [TUI Glossary](tui/native-terminal-core/glossary.md) pattern for one
  normative vocabulary source and optional localized terminology mappings.

## Recursive Scope Profile

The initial Loushang Architecture Scope tree is:

```text
Loushang
  -> Coding
       -> coding.lsp
       -> coding.arch
  -> Harness
       -> harness.multiagent
  -> AI
  -> Agent
  -> TUI
  -> HarnessTUI
  -> Method
  -> HarnessWork / Work compatibility
  -> Channel
  -> Ontology
```

This tree records architectural ownership, not necessarily Python distribution
or repository boundaries. Each node owns only its direct children;
cross-scope relationships are governed by the nearest common parent.

## Vocabulary And Principle Ownership

| Level | Vocabulary ownership | Principle ownership |
| --- | --- | --- |
| Loushang | one global index routes cross-system terms to canonical definitions | [Loushang Architecture Principles](loushang-architecture-principles.md) owns cross-system principles |
| Top-level scope | local glossary only for a substantial domain vocabulary | local principles only for durable scope-specific constraints |
| Nested scope | inherit by default; define only genuinely local terms | inherit by default; add only constraints the parent should not own |
| Component/module | use scope vocabulary; keep local names in specifications or code | do not create a principles package unless promoted to an Architecture Scope |

The existing Product, AI, Agent, Channel and design-difference terminology
documents remain canonical inputs. Loushang should add a global glossary index
over them rather than copy their definitions into one large file.

## Incremental Governance

1. Assign every cross-system term one canonical owner and record aliases,
   translations, deprecated names and consumers in a global glossary index.
2. Give cross-system architecture principles stable IDs and link each one to
   architecture tests, generated evidence or an explicit review check.
3. Require each Architecture Scope README to link inherited vocabulary and
   principles; small scopes may keep a few local additions inline.
4. Retain the native TUI glossary as a local normative source and promote only
   genuinely cross-system terms to the global owner.
5. Establish local glossary/principles files first for vocabulary-heavy scopes
   such as Harness and Ontology. Coding, LSP and Arch inherit until their local
   vocabulary or constraints justify separate files.
6. Extend documentation gates to validate glossary ownership, links,
   translation direction, principle IDs and declared verification evidence.

## Governance Evidence

- [Architecture Artifact Model](../architecture-method/artifact-model.md)
- [Architecture Scope README Template](../architecture-method/templates/architecture-scope-README.md)
- [Current Package Dependency Facts](generated/current-package-dependencies.md)
- [Current-To-Target Gap Ledger](current-target-gap-ledger.md)
- `tests/architecture/`
- `make check-architecture-docs`

Changes to the reusable method do not automatically change Loushang
architecture. Changes to this profile must identify the affected Loushang
scopes, gates and remaining Current-to-Target Delta.
