# Loushang Current-To-Target Gap Ledger

## Status

- Authority: descriptive — derived Delta summary
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture; detailed gaps remain scope-owned

## Scope

This ledger records cross-system architecture differences and candidate
directions that need top-level visibility. Detailed feature gaps remain in the
owning scope. Apply the method's
[Target acceptance rule](../architecture-method/README.md#target-acceptance):
only the first table records implementation differences from accepted Target.
The ledger's own status does not accept a row, and design acceptance does not
set a delivery date or authorize activation.

## Accepted Target Deltas

Each row identifies an accepted contract and its acceptance evidence. Optional
or conditional boundaries remain bounded by that contract; a later extension
needs its own acceptance. Current summaries link to scope evidence rather than
claiming acceptance from implementation alone.

| Area | Acceptance | Classification | Current | Accepted Target | Acceptance evidence / owner |
| --- | --- | --- | --- | --- | --- |
| Capability rollout | accepted | partial | Planner, transactional Binder, live Runtime and read-only Projector are implemented; the [Capability boundary](harness/capability-dependency-and-mount-lifecycle.md) records production-mounted bundles and remaining Process-scoped continuity rollout | complete accepted owner-scoped bundle rollout within declared facets and dependency contracts; broader refresh mechanisms are a separate candidate below | [Accepted Capability direction](architecture-overview.md#accepted-target-architecture) and [Capability contracts](harness/capability-dependency-and-mount-lifecycle.md) / Harness |
| Durable Work | accepted | partial | HarnessWork owns the Work lifecycle/event/query/replay kernel; compatibility remains under `loushang.work` | complete the accepted observable WorkHandle and persisted typed-result boundaries; crash recovery still requires a separate decision | [HarnessWork accepted boundary](harnesswork/README.md) / HarnessWork |
| Ontology source write-back | accepted | partial | ontology-owned Action planning, guarded Fact commit and authority routing are implemented | Product-hosted source mutation, acknowledgement and reconciliation without moving connector authority into Ontology | [Ontology ARD-012](ontology/ARD-012-authority-aware-action-planning-and-product-hosted-write-back.md) / Ontology and Product adapter owners |
| AppHost | accepted | partial | A0.1--A0.4 and G8--G10 are implemented; G9.3 retains Current because all eight deletion conditions were unmet; G10 supplies the exact default-dark canary; the [AppHost scope](apphost/README.md) records later G14/G16 routes, while A0.5 remains not-started | implement the accepted A0.5/G15 foreground launcher boundary; neither G16 shell reuse nor this row authorizes a default-route change | [G15 accepted foreground boundary](apphost/foreground-hosted-tui-g15.md) and [AppHost ARD-003](decisions/ARD-003-apphost-top-level-placement.md) / AppHost and Product composition owners |
| Architecture documentation | accepted | partial | recursive Scope governance, generated facts, selected canonical entrypoints and initial drift guards are implemented; decision records still use legacy paths, with the new method and templates available | consistent status/authority, Target acceptance and Current/Target/History separation across every governed canonical scope; adopt decision state directories per scope with matching indexes, links and consistency gates | [Architecture method](../architecture-method/README.md) and [governance profile](governance-profile.md) / architecture method owner |

## Candidate Directions

`not-accepted` applies to the specific direction in this table, not to an
already accepted prerequisite or implemented slice in the same scope. These
rows have no implementation-gap classification. Linked accepted documents
establish existing boundaries; only a subsequent owner decision can accept
the additional contract. This table neither rejects nor demotes those existing
accepted contracts.

| Area | Acceptance | Current context | Candidate direction / decision needed | Context / decision owner |
| --- | --- | --- | --- | --- |
| Capability refresh | not-accepted | the initial Binder fails closed for `stable_reference`; the accepted boundary constrains any future refresh | accept a concrete stable-indirection/refresh transaction before expanding the live Binder contract | [Harness Current Owner Map](harness/current-owner-map.md) and [Capability lifecycle constraints](harness/capability-dependency-and-mount-lifecycle.md#dependency-and-lifecycle-validation) / Harness |
| Work crash recovery | not-accepted | the accepted WorkHandle and typed-result boundaries do not supply a crash-resume checkpoint/fencing protocol | resolve the separate recovery ARD and its handler/checkpoint contract before treating crash resume as implementation debt | [HarnessWork open questions](harnesswork/README.md#open-questions) / HarnessWork |
| Channel | not-accepted | boundary values and narrow JSONL framing/correlation/delivery exist | establish demonstrated client requirements and accept any capability negotiation, general interaction or resume contract | [Channel boundary](channel/README.md) / Channel and consuming Product owners |
| Product validation | not-accepted | Coding is the only installed Product identity | decide whether and which second real Product should validate shared Harness/HarnessTUI abstractions | [AOD](architecture-overview.md) / Product and system architecture owners |
| Physical optionality | not-accepted | runtime packages share one Python distribution | accept installation profiles/extras or a distribution split only with public-contract and consumer evidence | [Hosting packaging boundary](decisions/ARD-002-hosting-top-level-placement.md) / packaging and system architecture owners |
| Hosting activation | not-accepted | H0--H6.5b mechanisms, the default-dark Harness adapter and PLC9C5 Product/native canaries are implemented with retained platform evidence | accept any activation beyond existing admitted routes while preserving mechanism/authority separation; default-dark operation is not itself an implementation gap | [Hosting ARD-002](decisions/ARD-002-hosting-top-level-placement.md) and [Hosting scope](hosting/README.md) / Hosting, Harness and Product owners |
| Hosted application extensions | not-accepted | G13 implements strict one-writer storage, atomic coordination recovery, lease-last lifecycle, current-generation cwd/user-home resume and fresh Harnesstui reattach; later accepted G14/G16 routes are recorded by AppServer and AppHost | accept any further daemon/service control, active-execution recovery, default activation or external surface beyond the already accepted contracts | [G11--G13 implemented designs](apphost/durable-hosted-application-continuity-g13.md), [AppServer](appserver/README.md) and [AppHost](apphost/README.md) / application architecture and Product owners |
| Coding LSP scope proposal | not-accepted | active query, lifecycle, diagnostics, Product binding and an evidence traceability matrix exist; individual accepted boundaries retain their authority | review the complete child-scope proposal and its remaining behavior before deriving gaps against newly accepted contracts | [LSP proposed architecture](coding/lsp/README.md) / Coding and LSP owners |
| Coding Arch scope proposal | not-accepted | the deterministic analyzer, cache, CLI and tool exist; individual accepted Capability contracts retain their authority | review the proposed child-scope requirements/component model; its status does not demote the separately accepted optional semantic-edge policy | [Arch proposed architecture](coding/arch/README.md) / Coding and Arch owners |

## Update Rule

- A scope updates its own detailed gap when implementation or accepted Target
  changes, and its candidate entry when a pending design decision changes.
- This ledger changes only when the delta affects the whole system, Product
  placement, cross-scope ownership, packaging, or architecture governance.
- Closing a gap requires executable evidence for implementation and an update
  to generated Current facts where applicable.
- Promote a candidate only after linking acceptance of its specific contract;
  compare that contract with Current before adding an accepted delta row. If
  it is already implemented, no implementation-gap row is needed.
- Rejection or deferral moves the candidate out of the active reading path;
  it does not close an implementation gap. Superseding an accepted contract
  requires replacement acceptance evidence and a fresh Current comparison.
