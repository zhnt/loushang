# Coding LSP Traceability

[Coding LSP Architecture](README.md) | [Requirements](requirements.md) |
[Specification](specification.md) | [Component Boundaries](component-boundaries.md)

## Status

- Authority: descriptive — evidence map
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

This matrix connects stable LSP requirements to owning components and
executable Current evidence. It does not replace the detailed requirements,
specification or tests.

| Requirement | Primary components | Executable evidence | Status |
| --- | --- | --- | --- |
| R1 Product capability identity | binding, tools | `test_runtime.py`, CLI capability override tests | implemented slice |
| R2 Editor independence | client, supervisor | fake and real Harness launcher vertical slices | implemented |
| R3 Declarative Server definitions | model, catalog | `test_discovery.py` | implemented slice |
| R4 Admission before execution | catalog, binding, Harness launcher | trusted-command and unavailable-server tests | implemented |
| R5 Deterministic Server selection | selector, catalog | preset/root-marker and monorepo selection tests | implemented |
| R6 Lazy reusable lifecycle | supervisor, binding | lazy ordinary Session, single-flight launch and restart tests | implemented slice |
| R7 Correct protocol lifecycle | client, supervisor | initialize, cancellation, shutdown and terminate-fallback tests | implemented slice |
| R8 Active semantic queries | tools, client, documents | definition/references/implementation/hover/outline vertical slices | implemented slice |
| R9 Structured bounded results | model, tools | workspace escape, result bounds, hover and outline bounds | implemented |
| R10 Document synchronization | documents, client | `test_documents.py` and ordered-sync vertical slice | implemented slice |
| R11 Native/external mutation handling | documents, binding | document snapshot/rollback and edit-sync slices | partial |
| R12 Passive diagnostics | diagnostics, documents, supervisor | `test_diagnostics.py` and passive-diagnostic lifecycle slices | implemented H4.1 slice; broader delivery partial |
| R13 Separate code diagnostics | diagnostics, status | diagnostic normalization/replacement/bounds tests | implemented slice |
| R14 Session/workspace isolation | binding, selector, supervisor | workspace escape, Session binding and monorepo tests | implemented slice |
| R15 Refresh and disposal | binding, supervisor, catalog | explicit stop, shared close, shutdown and catalog-freeze tests | implemented slice |
| R16 User control and inspection | status, commands, CLI | `test_cli.py`, `test_commands.py`, runtime-status tests | implemented slice |
| R17 Extension safety | catalog, binding | rejected project executable/argument/environment tests | implemented slice |
| R18 Optional Arch integration | future consumer-owned semantic-fact port | architecture documents only; no initial Capability edge | not-started |

## Evidence Groups

- `tests/coding/lsp/test_discovery.py`: catalog, admission, configuration and
  deterministic selection;
- `tests/coding/lsp/test_fake_launcher_vertical_slice.py`: protocol, tools,
  documents, diagnostics, lifecycle, cancellation and recovery;
- `tests/coding/lsp/test_harness_launcher_vertical_slice.py`: real Harness
  Process Hosting integration;
- `tests/coding/lsp/test_runtime.py`: Product binding and mount behavior;
- `tests/coding/lsp/test_cli.py` and `test_commands.py`: user control and
  inspection;
- `tests/coding/lsp/test_diagnostics.py` and `test_documents.py`: focused state
  contracts.

New LSP requirements update this matrix, the final component model and
executable evidence together. A passing test for one slice does not promote a
broader Target requirement to implemented automatically.
