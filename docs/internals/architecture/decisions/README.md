# Cross-Scope Architecture Decisions

## Status

- Authority: normative — cross-scope decision catalog and placement policy
- Design status: accepted
- Implementation status: implemented
- Owner: Loushang architecture

## Purpose

This directory contains accepted Architecture Record Documents whose decisions
span two or more top-level Architecture Scopes. It provides one stable entrypoint
for their ownership, status and reading order.

An accepted decision in this directory is normative for the boundary it owns.
Its implementation status and supporting evidence remain determined by the
individual record, current source and executable tests.

## Placement Rule

- A decision crossing two or more top-level Architecture Scopes belongs here.
- A decision owned by exactly one scope belongs in that scope's architecture
  package, normally as an `ARD-NNN-*.md` file or in a scope-local decisions
  directory.
- An unresolved proposal remains under [`drafts/`](../drafts/README.md) until
  the appropriate owners accept or reject it.
- Moving a decision does not change its authority by itself; the record's
  status and adoption links establish that authority.

## Naming And Lifecycle

Decision files use:

```text
ARD-NNN-short-decision-name.md
```

Numbering is local to this directory. Once published, an ARD number is not
reused. Superseded or rejected records remain available for traceability and
must identify their replacement or rejection rationale.

Normal decision states are:

```text
proposed -> accepted -> superseded
                   \-> rejected
```

The exact status declared by an individual ARD takes precedence over the table
below if the catalog has not yet been refreshed.

## Decisions

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
