# Cross-Scope Architecture Decisions

## Status

- Authority: normative — cross-scope decision catalog and placement policy
- Design status: accepted
- Implementation status: partial — existing catalog is implemented; state-directory migration remains pending
- Owner: Loushang architecture

## Purpose

This directory owns Architecture Record Documents whose decisions span two or
more top-level Architecture Scopes. It provides one stable entrypoint for their
ownership, status and reading order. Its current records are accepted decisions
at legacy root paths; new records use the state directories defined below.

An accepted decision in this directory is normative for the boundary it owns.
Its implementation status and supporting evidence remain determined by the
individual record, current source and executable tests.

## Placement Rule

- A decision crossing two or more top-level Architecture Scopes belongs here.
- A decision owned by exactly one scope belongs in that scope's architecture
  package under `decisions/<design-status>/` for new records.
- An identified ARD starts in `draft/` or `proposed/` here when this is its
  common parent. General exploration and delivery plans may remain under
  [`drafts/`](../drafts/README.md); they do not acquire decision authority there.
- Moving a decision does not change its authority by itself; the record's
  status and adoption links establish that authority.

## Naming And Lifecycle

Decision files use:

```text
ARD-NNN-short-decision-name.md
```

Numbering is local to this directory. Once published, an ARD number is not
reused across any state directory. Each record keeps its ID and filename during
state changes. Unselected options remain in the ARD's options/comparison, even
when the accepted choice is to keep Current.

Normal decision states are:

```text
draft -> proposed -> accepted -> superseded
```

`accepted -> superseded` requires an accepted replacement. Reconsideration
creates a new draft/proposal while the old decision remains effective. Review
records are separate from design status. `rejected` is optional for retained
whole-record rejections, not for unselected options.

New records use `draft/`, `proposed/`, `accepted/` and `superseded/` directories,
created only when occupied. Migrate existing records with `git mv` as part of
the scope's documented adoption: update document status, this index, incoming
references and relative links inside the moved record together. Directory,
document and index disagreement is a defect to repair, not a source of inferred
acceptance. Follow the
[Architecture Decision Method](../../architecture-method/architecture-decisions.md)
and [local adoption policy](../governance-profile.md#architecture-decision-adoption).

## Decisions

The following accepted records retain their canonical legacy root paths until
state-directory migration. Their decision status is unchanged. Add future
draft/proposed and superseded groups only when they contain records.

| Record | Status | Boundary | Decision summary |
| --- | --- | --- | --- |
| [ARD-001: Agent Loop Ownership And Extension Shape](ARD-001-agent-loop-ownership-and-extension-shape.md) | Accepted | Agent, Harness and Product adapters | Agent owns the fixed loop skeleton; Harness and Products extend it through explicit injected ports rather than replacing the loop. |
| [ARD-002: Hosting Top-Level Placement And Scope](ARD-002-hosting-top-level-placement.md) | Accepted | Hosting, Harness and trusted host composition | Hosting owns Product-neutral local process, inherited peer endpoint, and atomic child-session mechanisms; caller scopes retain admission, security, protocol, and domain authority. |
| [ARD-003: AppHost Top-Level Placement And Contract Boundary](ARD-003-apphost-top-level-placement.md) | Accepted | AppHost, Product packages, Harness, and optional hosted/launcher siblings | AppHost owns explicit cross-Product routing and scoped Product Runtime bindings; core remains independent of concrete Products, AppServer, Hosting, and UI frameworks. |

## Reading And Change Rule

For a cross-scope change:

1. read the affected top-level scope documents;
2. read the relevant ARDs in this catalog;
3. verify Current behavior against source and tests;
4. record Current-to-Target differences explicitly;
5. update every directly affected scope and their nearest common parent when
   adopting a new boundary decision;
6. add or update executable architecture gates for enforceable dependency or
   ownership rules.

This catalog is not a substitute for the
[Architecture Design And Governance Method](../../architecture-method/README.md)
or the [Loushang Architecture Governance Profile](../governance-profile.md).
