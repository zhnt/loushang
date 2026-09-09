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
  -> Hosting
  -> AppHost
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

## Target Acceptance In Loushang

Apply the method's [Target acceptance rule](../architecture-method/README.md#target-acceptance)
to the AOD, scope summaries, traceability and gap ledgers. Accepted scope
placement or an implemented prerequisite does not accept an entire proposal,
a later extension, or default activation.

The [Current-To-Target Gap Ledger](current-target-gap-ledger.md) keeps two
tables:

- `Accepted Target Deltas`: every row declares `Acceptance: accepted`, links
  the decision or accepted contract that establishes its Target, and records
  its Current difference and owner;
- `Candidate Directions`: every row declares `Acceptance: not-accepted`,
  names the decision needed and its owner, and carries no implementation-gap
  classification. An accepted source linked here supplies boundary context,
  not acceptance of the candidate extension.

`Acceptance` is a ledger assertion about the specific claim, not a new
document design status. Draft/proposed document maturity remains unchanged.
The AOD rolls up accepted deltas separately and links candidate directions.
Existing accepted slices retain their authority even when the enclosing scope
proposal is still under review. Promotion requires an owner-accepted contract;
the same change then derives its delta from Current evidence. Rejection or
deferral removes a candidate from the active reading path without treating it
as a completed implementation gap.

The initial documentation gate checks the table distinction, declared
acceptance, and linked acceptance records. Reviewers still verify that each
record accepts the exact claim. Other scope ledgers adopt this rule when their
relevant boundaries or summaries change; this does not promote their proposals.

## Architecture Decision Adoption

Loushang adopts the [Architecture Decision Method](../architecture-method/architecture-decisions.md)
and [ARD template](../architecture-method/templates/architecture-decision.md).
Background/drivers, options/comparison and decision/rationale are parts of one
ARD, linked to existing requirements and validation. A decision selecting
Current is accepted like any other selected option; losing options do not
receive separate rejected records.

New identified ARDs belong in the owning scope's `decisions/<design-status>/`.
The default state directories are `draft/`, `proposed/`, `accepted/` and
`superseded/`; create them on demand. `rejected/` is optional only for retained
whole-record rejections. The scope index groups records by state using the
[decision index template](../architecture-method/templates/decision-index-README.md).
Cross-scope records belong to the nearest common parent; the
[cross-scope catalog](decisions/README.md) owns top-level decisions.

The scope owner records acceptance; changes crossing scopes retain the affected
owners and common-parent review requirements. A small decision may use one
owner's recorded self-review and acceptance. For a customer-facing adoption,
the project's participation policy must identify the contracts requiring
customer confirmation, the confirming role and the recorded revision/scope.
This profile creates no blanket customer-confirmation requirement for Loushang
internal decisions. Review completion never substitutes for acceptance.

Existing root-level or scope-local ARDs and unresolved material keep their
canonical paths and recorded status until migrated. The cross-scope catalog
identifies the current legacy paths. Adopt the state directory layout per
scope, preserving existing IDs, filenames and decision evidence; update the
record status, indexes, inbound references, relative links and path-sensitive
tests together. Migration does not renew or manufacture acceptance. General
exploration and delivery plans continue to use their own draft/plan locations.

Each scope migration includes checks for directory/status/index agreement,
ID uniqueness across states, link validity and replacement references. Current
documentation checks validate the method, templates and catalog links; full
state-directory adoption and its consistency gates remain an explicit part of
the architecture-documentation delta. The reusable method change does not
silently relocate existing records or accept their candidate content.

## Governance Evidence

- [Architecture Artifact Model](../architecture-method/artifact-model.md)
- [Architecture Scope README Template](../architecture-method/templates/architecture-scope-README.md)
- [Architecture Decision Method](../architecture-method/architecture-decisions.md)
- [Architecture Decision Template](../architecture-method/templates/architecture-decision.md)
- [Decision Index Template](../architecture-method/templates/decision-index-README.md)
- [Current Package Dependency Facts](generated/current-package-dependencies.md)
- [Current-To-Target Gap Ledger](current-target-gap-ledger.md)
- `tests/architecture/`
- `make check-architecture-docs`

Changes to the reusable method do not automatically change Loushang
architecture. Changes to this profile must identify the affected Loushang
scopes, gates and remaining Current-to-Target Delta.
