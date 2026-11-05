# Harness Source Consolidation Delivery

## Status And Objective

- Authority: delivery evidence; existing capability contracts remain authoritative.
- Design status: accepted for the internal Store consolidation described below.
- Implementation status: partial; the 50,000-line objective is not achieved.
- Responsible implementer and internal reviewer: Codex, under the user's task.
- Method consulted: local archmethod master at
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

Consolidate repeated responsibilities and implementations while retaining every
unique supported capability. The cumulative effective reduction must reach at
least 50,000 product source lines. Work may span five rounds; an individual
batch or round does not replace the cumulative acceptance criteria.

Keep public interfaces, configuration, existing workspaces and persisted data
usable. Preserve permissions, identities/fingerprints, concurrency control,
atomic publication, failure recovery and native platform protections. Existing
[workspace compatibility](../decisions/accepted/ARD-008-workspace-upgrade-compatibility.md)
and [Plugin contracts](plugin/README.md) govern the changes.

## Frozen Accounting

Baseline: `739f947d6099257af1aec56ae587426d8cd8ec7d`.

| Scope | Baseline physical source lines |
| --- | ---: |
| Harness Python | 321,728 |
| Harness HTML/CSS/JavaScript | 349 |
| Harness total | 322,077 |
| All measured Product source, including native GUI | 636,645 |

Use the same [local accounting command](../../../../scripts/dev/harness_reduction_report.py)
throughout delivery, from the repository root:

```sh
python scripts/dev/harness_reduction_report.py --baseline 739f947d6099257af1aec56ae587426d8cd8ec7d
```

It counts physical lines in Git baseline blobs and current Product source,
including new untracked source files. The report records its fixed source roots
and language suffixes. Product bridge source is counted even when generated;
tests, documentation, examples, development tools and build outputs earn no
reduction credit. Every source-file increase outside Harness is debited, without
offsetting that debit with deletions elsewhere. Report whole-Product change
separately. Review any new source root before comparing future batches, including
its baseline contents; never silently exclude relocated implementations.

Code review must also reject moving responsibility to other packages,
repositories, dependencies, runtime-generated implementations or other languages.
Physical-line accounting alone cannot prove that condition. Formatting
compression, removing comments/blank lines for credit, and dropping unique
functions are prohibited.

The accounting command is read-only and is not connected to an Actions workflow
or a merge gate. This delivery does not authorize new or expanded gates.

## Delivery Sequence

1. Resources: shared native Store workflows, lifecycle coordination and inert
   record handling. Retain platform primitives and independent journal authority.
2. Resource catalog and Plugin management: repeated discovery/projection,
   decoding and lifecycle forwarding. Keep trust boundaries and distinct facts.
3. Session, capability and host composition: consolidate equivalent adapters and
   repeated construction paths with one accountable owner per responsibility.
4. Transcript and continuity: consolidate equivalent persistence/projection and
   admission mechanics while preserving writer fencing and recovery semantics.
5. Remaining cross-module duplication and integrated compatibility verification.

These are investigation areas, not claims that entire modules or their unique
capabilities are removable. Determine each batch's safe yield from evidence;
record shortfalls rather than weaken the objective or compatibility constraints.

## Batch 001: Native Materialization Store Workflows

The existing POSIX and Windows Stores duplicated construction validation,
settlement enumeration, receipt validation, publication lock lifetime, adoption
root identity checks, member-read admission and four public role adapters.

`PackageRoleStore` in `_materialization_shared.py` now owns those shared rules.
The two native modules implement narrow root/sink hooks and retain all native
tree verification, file reading, publication and GC operations. Public platform
class names, constructor parameters and method names remain available. No
persisted record class, schema version, canonical encoding or fingerprint changes.

Important differences remain explicit:

- Windows construction-time read-only handles still reject write operations.
- Windows file reads retain non-repairing journal access and their existing
  broad native error translation.
- POSIX reads retain their requested repair/read-only journal policy and their
  authenticated identity prefilter before full settlement comparison.
- Lock acquisition/release order, partial sink cleanup, native reparse/symlink
  protections, handle closure and partial-delete retry remain intact.

The existing boundary inventory now lists each platform's centralized native
`_open_root` call instead of duplicate callers. Its exact-inventory assertions
remain unchanged. Contract assertions follow the shared implementation: no
assertion is removed, and no workflow, route, trigger or platform is added.

| Accounting item | Lines |
| --- | ---: |
| Resources net reduction | 526 |
| Outside-Harness Product source increase | 0 |
| Effective cumulative reduction | 526 |
| Remaining to cumulative objective | 49,474 |

Local validation:

- Store, transfer, staging, artifact and Plugin architecture regressions:
  173 passed; 27 Windows-native cases skipped on Linux.
- Existing publication adversarial cases, real Store transactions, staging
  recovery and dependency GC scenarios: 23 passed; 154 unrelated cases deselected.
- Import boundaries, existing workspace storage and legacy policy reopen:
  170 passed.
- Existing `check-ai`, selected by the unchanged check planner: 937 passed,
  seven live cases deselected; overall coverage 90.77%, runtime core 90.76%.
- Ruff, focused mypy, source dependency freshness, nine existing documentation
  invariants, changed-document links and whitespace checks passed.
- Source inspection established AST equivalence for 112 retained native
  definitions, including native reads and GC. All 46 public method signatures
  retain their parameters, defaults, annotations and decorators.

This is a locally verified batch, not full delivery acceptance. Windows-native
execution remains outstanding and must use the existing platform coverage before
integrated delivery. The unchanged check planner selects broad validation for
the architecture inventory and new development-tool paths; this batch's focused
results do not establish that all selected GUI/TUI/host/platform checks passed.
