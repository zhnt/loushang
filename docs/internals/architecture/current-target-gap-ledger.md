# Loushang Current-To-Target Gap Ledger

## Status

- Authority: descriptive — derived Delta summary
- Design status: accepted
- Implementation status: not-applicable
- Owner: Loushang architecture; detailed gaps remain scope-owned

## Scope

This ledger lists only cross-system or architecture-governance deltas that need
top-level visibility. Detailed feature gaps remain in the owning scope. A row is
not a delivery commitment or proof that its Target is accepted; the Target
authority column identifies that source.

| Area | Classification | Current | Target | Target authority / owner |
| --- | --- | --- | --- | --- |
| Capability rollout | partial | Harness owns an implemented pure Planner, transactional Binder, live per-graph Runtime and read-only Projector; `harness.workspace` is role-complete, while selected Harness and Coding capabilities are not all production-mounted | production-mount accepted bundles through the graph and add explicit stable-reference refresh semantics without leaking live graph owners | Harness capability dependency/mount decision and current owner map |
| Durable Work | partial | HarnessWork owns Work lifecycle/event/query/replay kernel; compatibility remains under `loushang.work` | complete run-bound handling, typed results, evidence/artifacts and recovery contracts | HarnessWork/Work scope |
| Channel | partial | accepted boundary values plus narrow JSONL framing/correlation/delivery | capability negotiation, general interaction and resume only when accepted by demonstrated clients | Channel scope |
| Product validation | missing | Coding is the only installed Product entrypoint | a second real Product validates which Harness/HarnessTUI abstractions are genuinely shared | Product/AOD decision required |
| Physical optionality | missing | one Python distribution installs all runtime dependencies | installation profiles/extras and later distribution split only with public contract and consumer evidence | packaging architecture decision required |
| Ontology source write-back | partial | ontology-owned Action planning, guarded Fact commit and authority routing are implemented | Product-hosted source mutation, acknowledgement and reconciliation without moving connector authority into Ontology | Ontology ARD-012 and Product adapter owners |
| Coding LSP | partial | active query, lifecycle, diagnostics, Product binding and an evidence traceability matrix exist | accept the child-scope architecture and complete remaining external-mutation and passive-delivery behavior | `coding.lsp` scope |
| Coding Arch | partial | implemented deterministic analyzer, cache, CLI and tool now have a proposed canonical scope architecture and evidence map | accept the child-scope requirements/component model and retain optional semantic port policy | `coding.arch` scope |
| Architecture documentation | partial | recursive Scope governance, generated facts, selected canonical entrypoints and initial drift guards are implemented; coverage is intentionally incremental | consistent status/authority and Current/Target/History separation across every governed canonical scope | architecture method and documentation gates |

## Update Rule

- A scope updates its own detailed gap when implementation or Target changes.
- This ledger changes only when the delta affects the whole system, Product
  placement, cross-scope ownership, packaging, or architecture governance.
- Closing a gap requires executable evidence for implementation and an update
  to generated Current facts where applicable.
- If a proposed Target is rejected or superseded, remove or replace the row;
  do not call the resulting absence an implementation failure.
