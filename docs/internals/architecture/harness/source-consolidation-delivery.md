# Harness Source Consolidation Delivery

## Status And Objective

- Authority: delivery evidence; existing capability contracts remain authoritative.
- Design status: accepted for the internal Store and record-field consolidation
  described below; durable contracts remain unchanged.
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

## Batch 002: Inert Record Field Traversal

54 existing lifecycle record decoders now share field traversal through the
private `_record_schema.py` helper. Their 480 field declarations supply the
constructor attribute, original diagnostic label and original value decoder.
Conventional camel-case keys are derived once per declaration; all keys were
checked against the original allowed-field sets before applying this change.
Object admission still runs through each record's original `_exact_dict` or
`_wire_object` helper, before decoding in the original constructor argument order.

These are static field descriptions, not generated record implementations. The
existing record classes, constructors, cross-field validation, encoding,
fingerprints, version constants and exports remain in their original modules.
Custom decoders remain explicit. There are no new dependencies or external
Product implementations, and no test assertion or Actions configuration changes.

Per-record review retained six small explicit decoders whose shared-field forms
offered no aggregate source reduction. These include native Store identities
that are decoded frequently. This avoids adding traversal overhead where the
existing implementation is already concise. Shared traversal has a fixed
dispatch cost; this batch does not claim a startup performance improvement.

| Accounting item | Lines |
| --- | ---: |
| Batch 002 Resources net reduction, including its new helper | 661 |
| Outside-Harness Product source increase | 0 |
| Effective cumulative reduction | 1,187 |
| Remaining to cumulative objective | 48,813 |

Local validation:

- Record, transaction, Store, recovery and owner regressions: 203 + 140 passed.
- Existing Plugin architecture and import-boundary regressions: 269 passed.
- Existing workspace storage, legacy policy reopen and pre-B snapshot routes:
  27 passed.
- Complete existing adversarial suite: 176 passed, one failed. The exact failure,
  `test_posix_local_wheel_product_composition_uses_live_epoch_and_owners[session-False]`,
  was reproduced on the clean frozen baseline `739f947d6`: the fixture exposes
  `standard` but expects a `review` Skill. The assertion and test route remain
  unchanged; it is not classified as a passing result.
- A repository-external old/new decoder experiment exercised valid fixtures for
  all 60 considered records, then compared missing/extra fields, wrong scalar
  types, nested values and constructor failures: 176,288 comparisons, zero
  mismatches. After retaining the six explicit decoders, the affected four-module
  regression subset passed 86 cases, with 28,583 further comparisons across all
  60 records and zero mismatches.
- AST comparison preserves 513 existing helper/class definitions apart from
  the selected decoder bodies, including all fields, validation and encoding.
  All original decoder signatures/decorators and 13 explicit export lists remain
  intact. Ruff, formatting, focused mypy, source dependency freshness and the
  nine documentation invariants passed.

The batch-local check plan selects Harness, architecture and existing native/host
routes. It does not select AI; the branch's prior AI result belongs to Batch 001.
Outstanding integrated platform validation and the cumulative 50,000-line target
remain open.
