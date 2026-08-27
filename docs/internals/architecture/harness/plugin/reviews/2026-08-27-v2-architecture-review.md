# Plugin Architecture V2 Independent Architecture Review

## Result

- Date: 2026-08-27
- Reviewer: independent agent `/root/plugin_arch_review`
- Final verdict: **PASS**
- Scope: architecture authority, cohesion/coupling, current-to-target accuracy,
  document convergence, and executable architecture gates.

## Initial Blocking Findings And Disposition

1. Architecture tests still referenced the retired master path and its exact
   prose. They now point to `harness/plugin/`; V2 tests freeze first principles,
   while PLC/PAP contract tests retain exact wire, owner, security, lifecycle,
   and rollback gates.
2. The install-without-execution invariant did not disclose that current
   Python materialization may run sdist/PEP 517 builds. V2 and PLC9 now record
   the current gap and require verified wheel-only artifacts or a separately
   contained build service before untrusted executable admission.
3. `manifest.enabled` and `source.enabled` were unexplained peer vetoes beside
   management desired state. The compatibility ledger and PLC9 now assign the
   one-time migration and remove runtime selection authority from both fields.
4. Active plans disagreed about retired UPA milestones, V2 acceptance, and the
   closed-schema delivery owner. Active references now use PLC6/PLC7/PLC8/PLC9,
   and historical review evidence is explicitly non-authoritative.
5. The glossary still described a Plugin as Resource roots plus Extensions.
   It now defines the independently selectable activation identity and its
   typed declarations into exact owners.

The reviewer also verified that the existing Coding LSP importer list can name
both Product adapters without creating another Product composition root: both
reuse the same private Harness assembly authority.

## Verification Evidence

- Plugin architecture focus: `59 passed`.
- Complete architecture suite after the importer-inventory correction:
  `280 passed`.
- Same reviewer re-reviewed the corrections and returned **PASS**.
