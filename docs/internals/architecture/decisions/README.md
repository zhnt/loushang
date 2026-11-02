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
acceptance. Follow the [local decision adoption policy](../governance-profile.md#architecture-decision-adoption).

## Decisions

The following accepted records retain their canonical legacy root paths until
state-directory migration. Their decision status is unchanged. Add future
draft/proposed and superseded groups only when they contain records.

| Record | Status | Boundary | Decision summary |
| --- | --- | --- | --- |
| [ARD-001: Agent Loop Ownership And Extension Shape](ARD-001-agent-loop-ownership-and-extension-shape.md) | Accepted | Agent, Harness and Product adapters | Agent owns the fixed loop skeleton; Harness and Products extend it through explicit injected ports rather than replacing the loop. |
| [ARD-002: Hosting Top-Level Placement And Scope](ARD-002-hosting-top-level-placement.md) | Accepted | Hosting, Harness and trusted host composition | Hosting owns Product-neutral local process, inherited peer endpoint, and atomic child-session mechanisms; caller scopes retain admission, security, protocol, and domain authority. |
| [ARD-003: AppHost Top-Level Placement And Contract Boundary](ARD-003-apphost-top-level-placement.md) | Accepted | AppHost, Product packages, Harness, and optional hosted/launcher siblings | AppHost owns explicit cross-Product routing and scoped Product Runtime bindings; core remains independent of concrete Products, AppServer, Hosting, and UI frameworks. |

### Accepted In State Directories

| Record | Status | Boundary | Decision summary |
| --- | --- | --- | --- |
| [ARD-004: Separate Resume History From Current Execution Authority](accepted/ARD-004-resume-history-and-current-authority.md) | Accepted | Coding, Harness, AppHost, AppService, HarnessTUI | Decode readable history independently of current environment snapshots; admit new execution only under current authority and a separate activation contract. |
| [ARD-005: Commit Resume Binding With The First User Message](accepted/ARD-005-resume-continuation-commit.md) | Accepted | Coding and Harness transcript/session | Co-commit bounded RuntimeBinding and resource evidence with one `agent.message`; reconcile fixed input identity and define reader versus writer rollback boundaries. |
| [ARD-006: Keep Hosted Resume Readiness Inside One Product Binding](accepted/ARD-006-hosted-resume-readiness-and-admission.md) | Accepted | Coding, AppHost, AppService, AppServer, HarnessTUI | Keep preparing inside AppHost's one live Product binding; preserve Ack timing and use durable input lookup for hosted retry. |

| [ARD-007: Correlate Resume Effects In Their Original Journals](accepted/ARD-007-resume-native-effect-correlation.md) | Accepted | Coding, Harness Approval and native Worker owners | Co-register parent context in original native journals; require frozen participation, fenced sealed enumeration, original-owner reconciliation and versioned writer boundaries before writable Resume. |
| [ARD-008: Preserve Workspace Compatibility Across Upgrades](accepted/ARD-008-workspace-upgrade-compatibility.md) | Accepted | Product startup, Plugin storage and Session recovery | Retain compatible storage owners for existing workspaces; future storage changes preserve ordinary startup and data without user resets. |
| [ARD-009: Unified Loading Input And Terminal Adapters](accepted/ARD-009-unified-loading-input-and-terminal-adapters.md) | Accepted | Coding, HarnessTUI and TUI | Share loading ownership and adapt transferable native input; native macOS/Windows validation pending. |
| [ARD-019: Work Facts And Transcript Sharing](accepted/ARD-019-work-facts-and-transcript-sharing.md) | Accepted | HarnessWork, Harness Session/Transcript, Product composition and Goal consumption | HarnessWork supplies default recording and reading mechanisms; Product configures policies and resources. R3.1 semantics accepted 2026-10-29; opt-in full-fact recording/confirmation slice implemented locally; source-binding and migration obligations retained. |
| [ARD-020: Hosted Goal Budget And Observation](accepted/ARD-020-hosted-goal-budget-and-observation.md) | Accepted | Coding, AppService/AppServer, HarnessWork | Product configures effective budgets; original owners enforce them; optional progress preserves full query/wait and completion validation. |

### Draft

| Record | Status | Boundary | Decision question |
| --- | --- | --- | --- |
| [ARD-011: Stage The Immutable Prefix Of A Tool Continuation](draft/ARD-011-stage-tool-continuation-prefix.md) | Draft | Agent, AI, Harness and Coding | Can a proven append-only prefix move historical request and Model Input work into the tool interval while retaining the final durability barrier? |

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
[Loushang Architecture Governance Profile](../governance-profile.md).
