# PLC9B aggregate boundary inventory reconciliation

The aggregate plugin boundary guard predates the PLC9B lifecycle components.
During lmux acceptance its scan found 58 additional `(qualified function,
operation)` entries: 48 functions containing 64 calls. The four scanned plugin
roots have no lmux source changes. This is a baseline inventory reconciliation,
not new plugin authority introduced by lmux.

The reviewed, literal inventory is `PLC9B_BOUNDARY_SINKS` in
`tests/architecture/test_unified_plugin_architecture.py`, plus the installed
distribution top-level metadata reader. Expected values are not generated from
the source scan. Exact sites, operation counts, owner names, all four scan roots,
and the synthetic bypass cases remain checked.

## Ownership rationale

| Component | Boundary owner and responsibility |
| --- | --- |
| Ten lifecycle journal JSON helpers | Their respective journal owns strict duplicate-key decoding and its input read. |
| Quarantine acquisition | Quarantine native boundary owns artifact and verified tree handles. |
| POSIX/Windows role stores | Platform role store owns verified materialization handles and receipts. |
| POSIX/Windows epoch cutover | Platform cutover owner owns pinned roots and ancestor traversal. |
| POSIX/Windows offline restore | Platform restore materializer owns exclusive restore roots, input handles and strict records. |
| Wheel verification | Safe wheel verifier owns archive entry reads, not unrestricted filesystem access. |
| Verified tree transfer | Transfer owner calls the typed sink's verified file-open operation. |
| Retention handoff | Journal constructs its receipt; handoff owner invokes that journal's open protocol. |
| Installed distribution evidence | Existing evidence resolver reads `top_level.txt` metadata; it does not execute the package. |

`path_read` is a syntactic detector label. In particular, archive `.open`, typed
journal `.open`, and the pure retention receipt constructor are not interchangeable
with native filesystem opens. Recording them does not grant callers additional
filesystem authority or exempt future calls from the guard.

The component contracts remain authoritative:
[PLC9B contract](plugin-lifecycle-plc9b-contract.md), and the component inventory in
`tests/architecture/test_plugin_lifecycle_plc9b_contract.py`. This reconciliation
does not claim a fresh full security audit of every PLC9B implementation.
