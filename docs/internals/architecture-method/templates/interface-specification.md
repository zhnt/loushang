# <Scope> Human-Facing Interface Specification

> Template: use for a GUI, CLI, TUI, web or multimodal surface whose observable
> navigation, state, actions or accessibility behavior must be stable and
> testable. Remove unused sections. Keep service/domain contracts canonical in
> their owning specifications and link them instead of copying them here.

## Status And Ownership

- Scope: `<owning architecture scope>`
- Authority: normative
- Design status: draft
- Implementation status: not-started
- Owner: `<accountable interface owner>`
- Requirements: `<canonical requirement references>`
- Boundary and domain model: `<canonical references>`
- Reference evidence: `<descriptive inventory, if any>`
- Verification / Current / Delta: `<canonical evidence references>`

## Purpose, Users And Boundary

State the user outcomes this interface makes observable, the actors and access
forms it serves, and what the interface does not own. Identify authority,
security, privacy and lifecycle boundaries that placement must not bypass.

## Evidence And Decision Ledger

| Input | Observed or confirmed fact | Interpretation | Local decision | Status / owner |
| --- | --- | --- | --- | --- |
| `<participant, source, screenshot, implementation fact>` | ... | ... | adopt / adapt / decline | ... |

Keep authoritative external documentation, versioned observations, local
inference and accepted local decisions distinguishable. A screenshot can
establish visible placement in one state; it cannot establish hidden behavior,
complete states, backend identity or authority.

## Interface Vocabulary And Identity

Define each user-facing object and map it to canonical domain identities.
Separate labels, selection from identity, and distinguish entities that are
visually adjacent but have different lifetimes or owners.

## Information Architecture

Use a compact tree or region table to define navigation hierarchy and stable
placement. State which regions are fixed, scroll independently, resize, collapse
or become overlays. Placement is not component ownership.

## Observable States And Actions

For each region or control, specify:

- visible content and source;
- loading, empty, active, waiting, completed, failed, stale, incompatible and
  unavailable behavior as applicable;
- available commands, keyboard behavior and confirmation;
- effects, cancellation and recovery;
- disabled/hidden behavior when capability or permission is absent.

## Capability And Provenance Matrix

| Surface | Required fact/capability | Owner/source | Missing or stale behavior | Forbidden inference |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

The interface may project facts and collect intent. It must not become the
authority for domain state merely because it displays or edits a representation.

## Navigation, Focus And Responsive Behavior

Specify navigation history, focus return, independent scrolling, minimum useful
sizes, resize/collapse order and behavior at supported text scaling. Preserve
critical control, status and recovery access at narrow sizes.

## Accessibility And Localization

Cover keyboard access, landmarks/names, non-color state communication, reduced
motion, live-update behavior, input methods, text expansion and supported
languages. Define platform-native differences where they affect outcomes.

## Acceptance Scenarios

| ID | Initial state / trigger | Observable result | Requirement IDs | Evidence |
| --- | --- | --- | --- | --- |
| `<scope>-UI-AC-001` | ... | ... | ... | planned / test path |

Prefer state-transition and failure scenarios over screenshot-only approval.
Use fixtures for deterministic presentation states and separate them visibly
from real integration evidence.

## Current, Target And Delta

Record evidence-linked current implementation separately from the proposed or
accepted interface. List missing, partial, deviated or unmodeled behavior only
against an accepted Target; candidate layout is not implementation debt.

## Non-Goals, Open Contracts And Change Triggers

List excluded behaviors, missing provider/service contracts, unresolved
decisions and the events that require review. Reference assets and exact pixels
are not copied unless their license, ownership and acceptance are explicit.
