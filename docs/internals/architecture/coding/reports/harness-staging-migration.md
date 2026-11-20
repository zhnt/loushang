# Coding Harness Staging Migration

## Status

- Authority: implementation report and migration evidence.
- Owner: Coding Product, with Harness shared-owner boundary review.
- Implementation/review: Codex `/root`, within the authorized Goal.
- Design scope: the user-authorized intermediate `coding.harness` boundary;
  this report does not accept a final public Harness API or claim final extraction.
- Implementation status: complete coverage and primary extraction range frozen;
  first private-data semantic batch accepted locally after operation, consumer
  and compatibility review; other frozen migration batches remain incomplete.
- Accepted starting source: `df0dca779aaf4211a673dc77ae87470b6c579087`.
- Method: clean local `archmethod/master` at
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`, consulted locally, not vendored.

## Authorized Intermediate Boundary

Move complete reusable operations into `coding.harness`, while keeping actual
Coding domain and Product configuration at the Product edge. Intermediate
implementations may depend on other Coding components. Record each remaining
dependency, its reason, eventual owner and exit path; immediate dependency
elimination must not fragment transactions into numerous small adapters.

Name the staged components and their own APIs for generic responsibilities.
Prefer the eventual existing owner families: `package_product`,
`plugin_management` and `worker`. Coding-named public types and persistent
identities stay at necessary compatibility edges. A temporary reference to one
of those types is explicit debt, not permission to embed Product defaults in
the shared mechanism.

The existing `loushang.harness` must not import `coding.harness`. Intermediate
code reuses the original Harness/Hosting/AppHost/AppService owners; it does not
create another Worker, journal, recovery engine or resource manager. Final
movement into `loushang.harness` is a later stage requiring Product dependency
elimination. This Goal does not require that final movement.

## Complete Review Scope

The frozen source inventory covers all **459 Coding Python files / 100,715
physical lines** and the existing public type declarations. The current major
component review covers **260 files / 56,483 lines**:

| Component | Python files | Physical lines | Review responsibility |
| --- | ---: | ---: | --- |
| package | 192 | 31,568 | Complete private-data, package, compatibility and Worker chains |
| plugin_manager | 16 | 4,133 | Lifecycle, layout, state and management boundaries shared by Package |
| session | 5 | 4,450 | Remaining reusable execution and ownership programs |
| runtime | 3 | 844 | Remaining lifecycle and execution coordination |
| resume | 17 | 3,427 | Remaining generic coordination versus Product admission |
| composition | 17 | 11,124 | Generic execution versus actual Product selection and assembly |
| resources | 10 | 937 | Shared mechanism versus Product resource selection |

These are review inventories, not promised migration quantities. Every candidate
needs a semantic move/retain decision, and the other 199 files remain part of
the complete coverage review. LSP/Arch domain behavior, Product choices,
approval/trust policy and final presentation remain Coding-owned. A Coding type,
historical format or error identifier alone does not establish that an entire
operation is Product policy.

The complete 459-file coverage and 260-file primary extraction range are frozen
in the task evidence. This freezes responsibility coverage, not a claim that
every candidate file moves wholesale or that its review is finished. Refine
operation/retention decisions inside each complete batch. Generic mechanisms
found in a retained Product/adapter candidate join their owning chain. Removing
an extraction responsibility requires concrete source/consumer evidence. Neither
first-batch completion nor source review establishes whole-Goal acceptance.

## First Complete Batch: Private Data Lifetime

The initial prefix inventory is **31 files / 6,519 lines**, spanning Product
root selection, read-only observations, backup, deletion, restore, confirmation,
expiry and their history/cleanup. Inspect the actual dependency closure before
freezing the operation/file mapping. Prefix membership does not prove generic
ownership or a closed transaction.

Existing owners include Harness Plugin Management's backup, deletion,
confirmation, restore/expiry records and Windows operations; Package Product's
selected roots and backup topology; Resources' rooted/platform IO; and Journal's
original persistence and locking. Reuse them directly. Preserve the distinction
between Product admission to delete/restore and the mechanism executing an
already admitted operation. Keep historical Arch identities, wire prefixes,
Profile choices and diagnostic policy at the Product edge.

Before editing, capture original DTO fields/slots and nominal identities, codec
and error observations, supported old import/pickle paths, fault injection
consumers and the actual callers. Preserve one state/transaction owner. Public
compatibility must not produce a forest of per-file root forwarders.

### Current Coordinating Programs

The current candidate stages **66 complete implementations** in 24 program
modules. The 31-file review distinguishes 24 original nominal/policy modules
with moved programs from seven Product edges that already use existing shared
engines. Staged custody keeps the original objects, gates, descriptors and
cleanup. Record admission and manifest/history proofs use the original nominal
values; existing `RecordSchema` traversal is reused rather than duplicated.

Original dataclass fields, slots, bases, signatures, pickle routes, Product
path/admission/policy values and fault lookup globals remain at their edges.
Each staged module temporarily imports its original binding, resulting in
24 explicit physical module cycles. At the original logical owner level, all
1,650 module pairs remain equal, with no added/removed dependency pair. This
normalization documents intermediate coupling; it does not eliminate it.

The current cost is 2,428 staging lines, 99,638 other Coding lines and 102,066
Coding lines total: Product edges decrease by 1,077 lines, but all production
code increases by **1,351 lines**. Actual Harness, Hosting and other production
code, tests and development scripts are unchanged. Type declarations remain
143 lines. Staging is still Coding, not system deletion. Signatures/compatibility
wrappers, explicit Product identity/diagnostic declarations and qualified
borrowed bindings account for growth; the first batch has no net-deletion
claim. Documentation is accounted separately.

### File And Operation Disposition

All original paths below are beneath `coding.package`; staged paths are beneath
`coding.harness.plugin_management`. Historical public/nominal entries continue
to dispatch to the single staged body; the original coordinating body exits.
Future owners are the existing Harness Plugin Management private-data family,
using its existing Package Product, Journal and Resources owners. Necessary
nominal type and Product policy projections remain at Coding's boundary.

| Original module | Staged module | Moved operations |
| --- | --- | --- |
| `private_data_backup` | `private_data_backup` | `retain`, `verify`, `retention_snapshot` |
| `private_data_backup_expiry` | `private_data_backup_expiry` | `preview`, `expire`, `require_pre_effect_plan`, `require_recovery_authority`, `_expiry_preview`, `confirm` |
| `private_data_backup_expiry_journal` | `private_data_expiry_events` | `validate_event` |
| `private_data_backup_expiry_records` | `private_data_expiry_records` | `validate_plan`, `validate_confirmation`, `validate_receipt` |
| `private_data_backup_records` | `private_data_backup_records` | `validate_receipt`, `decode_manifest`, `decode_posix_archive`, `decode_windows_archive`, `make_backup_receipt` |
| `private_data_backup_sdk` | `private_data_clients_posix` | `read_retention_status`, `read_scope`, `product_scope` |
| `private_data_deletion_owner` | `private_data_deletion_owner` | `plan_for`, `delete_confirmed` |
| `private_data_deletion_preview` | `private_data_deletion_preview` | `offline` |
| `private_data_read_owner` | `private_data_read` | `assert_current`, `offline`, `open_read_scope`, `verify_backup`, `deletion_preview`, `verify_restore_confirmation` |
| `private_data_restore` | `private_data_restore` | `confirm`, `verify_confirmation`, `preview`, `restore`, `_current_completed_restore`, `_restore_preview` |
| `private_data_restore_confirmation` | `private_data_restore_confirmation` | `validate_confirmation`, `create_confirmation`, `matches_restore_result`, `require_restore_confirmation` |
| `private_data_restore_journal` | `private_data_restore_events` | `validate_event`, `create_event` |
| `private_data_restore_records` | `private_data_restore_records` | `validate_plan` |
| `private_data_windows_archive_snapshot` | `private_data_windows_archive_records` | `validate_archive`, `decode_archive` |
| `private_data_windows_backup` | `private_data_windows_backup` | `retain`, `verify` |
| `private_data_windows_backup_client` | `private_data_clients_windows` | `backup_scope` |
| `private_data_windows_backup_expiry_journal` | `private_data_windows_expiry_journal` | `require_pre_effect_archive`, `validate_event`, `decode_event` |
| `private_data_windows_backup_expiry_preview` | `private_data_windows_expiry_preview` | `preview_locked` |
| `private_data_windows_backup_expiry_recovery` | `private_data_windows_expiry_recovery` | `require_expiry_recovery_authority` |
| `private_data_windows_confirmation` | `private_data_windows_confirmation` | `record_confirmation`, `is_confirmed` |
| `private_data_windows_deletion_journal` | `private_data_windows_deletion` | `transaction`, `capture_current_target`, `require_staged_start_target_unchanged`, `require_windows_tombstone` |
| `private_data_windows_preview` | `private_data_windows_preview` | `snapshot_for`, `offline` |
| `private_data_windows_restore_journal` | `private_data_windows_restore` | `transaction`, `validate_publication`, `decode_publication`, `require_plan_current` |
| `private_data_windows_restore_preview` | `private_data_windows_restore_preview` | `preview` |

| Original retained module | Concrete retention reason and existing mechanism owner |
| --- | --- |
| `arch_private_cache` | Five-line Product/platform admission to the existing atomic inherited-ACL snapshot writer in Harness Resources; no private writer implementation remains here. |
| `installation_private_data` | Actual Coding/Arch installation and Session path hashing, selected plugin/manifest admission, Product-source and state-root policy. Bind/inspect/intent/publication/history methods already call Harness _WindowsInstallationRootLineage; native directory preparation uses existing Resources. These shared engines predate this Goal. |
| `private_data_deletion_journal` | Required nominal deletion-event subclass, wire schema/type projection, historical tombstone identity, Product journal path/diagnostic/error identity. Locking, event/history validation, execution checkpoints and durable append already belong to Harness PrivateDataDeletionJournal and PluginPrivateDataDeletionEventV1. |
| `private_data_windows_deletion_owner` | Product command/owner/fingerprint admission and original callback/type projections into existing Harness execute_windows_private_deletion and remove_started_windows_private_tree. Full effect/replay and native tree IO were shared before this Goal; moving this adapter would add forwarding without moving an unshared engine. |
| `private_data_windows_restore_owner` | Product plan/path admission and exact nominal result projection to Harness WindowsPrivateRestoreTransaction.execute_restore/confirm_restore/verify_confirmation through the existing transaction scope. No restore/copy/replay engine remains in the nominal owner. |
| `private_data_windows_backup_expiry_owner` | Product confirmation/plan admission and exact nominal receipt projection into Harness WindowsPrivateExpiryTransaction.execute_expiry; original journal scope and plan/archive/history proof implementations are staged. No second expiry engine is implemented here. |
| `product_backup_types` | Closed Product decision that only Arch private data is supported and Worker backup support is false; exact Product topology/wire identity and GC/admission requirements. Durable topology IO and validation already call Harness Package Product read_backup_topology. |

Remaining bodies in moved modules consist of nominal/wire declarations,
Product path, identity and admission policy, exact error factories, and direct
bindings to already shared archive/tree/journal/schema mechanisms. The read
owner's restore/expiry query adapters call the staged complete proofs while
preserving the existing read-only authority. The SDK keeps actual local actor
and policy revision decisions and Product factories; staged client scopes own
borrowed application/read lifetime and the original failure cleanup order.

The expiry owner's confirmation program also revalidates the exact current
plan and hands it to the existing journal. The actual local actor and approval
policy revision stay in the SDK. Its focused confirmation/replay tests pass;
it is included in the complete operation mapping above. This closes the first
private-data semantic batch, while the remaining package/lifecycle and frozen
execution-component migrations remain incomplete.

### Consumers And Borrowed Authorities

Actual external consumers are `arch._provider_api`, `cli.plugin_private_data`,
`composition.bootstrap`, `package.management_binding`, `package.product_runtime`,
`package.product_worker_history_retention`,
`package.product_worker_windows_package_references` and
`package.product_worker_windows_recovery_inventory`. CLI/SDK invoke original
entries now backed by staged programs; management reads the staged retention
snapshot. Startup still uses the actual selected Arch path policy. Worker
retention/recovery still consumes the Product decision that Worker backups are
unsupported; this statement is not a generic backup capability.

Borrowed direct authorities are `package.epoch_layout`,
`package.legacy_windows_receipt`, `package.product_runtime` and
`plugin_manager.lifecycle`. They supply original Product layout, admission,
nominal errors and shared receipt/tree bindings. Their unrelated generic
mechanisms remain in their later frozen package/lifecycle batches; this first
batch does not claim those whole components accepted. The existing final
`loushang.harness` does not import the new staging namespace.

## Validation And Commit Rhythm

Use static/import checks and focused tests during a batch. Run affected
components and consumers at important milestones, for substantial complete
chains and for changes to startup, restore, locking, persistence or cleanup.
Do not defer all regression until the entire Goal, and do not repeat full suites
or create commits merely because a few hundred lines moved.

Commit locally only after a coherent batch has connected consumers, retired its
old duplicate implementation and passed relevant checks. Publish no task
commits or PRs until all frozen migration goals and cumulative candidate checks
are complete. Follow the existing task PR to `lane/harness`, then integration
PR to `main`; both remain subject to normal checks and accepted intermediate
compatibility documentation. No PR gate is added or expanded.

Pytest and pytest-invoking Make commands run outside the managed sandbox from
the first attempt, through the existing managed wrapper, with the prescribed
runtime directory and absolute worktree `PYTHONPATH`. Keep non-live/platform
selectors. Explicit exceptions must be applicable to this Goal; changing
Product security to accommodate an environment failure is not an alternative.

### Baseline Evidence

Before production edits, the existing deletion-journal and confirmation-binding
tests pass: **4 passed**, 12.35 seconds. They establish the selected replay and
state-authority observations, not complete private-data or native Windows
acceptance. Full source/test/script/architecture baseline material and per-file
AST/field inventories are retained outside the Product repository in task
runtime evidence. Existing golden fixtures are unchanged.

The 65-program private-data candidate passes all **385** existing selected
private-data/SDK/CLI/replay/cleanup cases in 372.04 seconds. After the final
confirmation extraction, **78** related confirmation/replay, native-record
format/error-order and fresh-process facade compatibility cases pass in
41.95 seconds. The latter is an affected-path check after the last change, not
a claim that the earlier 385-case run included that final extraction.

Current mypy passes all 54 selected private-data/staging sources. Ruff, source
diff checks and the nine existing lightweight documentation invariants pass.
The 31-file nominal observation includes 360 Coding-owned symbols, covering
fields/slots/bases, signatures, method identities and protocol-4/5 symbol
pickle paths; all remain equal. These observations do not claim arbitrary
instance-pickle acceptance. All 66 current staged bodies match their original
implementation after resolving explicit binding/policy references, relative
import rebasing and cast annotation qualification. Original golden fixtures
and runtime tests are unchanged.

Native Windows execution remains unperformed on this POSIX machine. Controlled
Windows algorithm/fault/format routes preserve their original distinct
contracts and are local regression evidence, not native platform acceptance.
No new or broader gate is introduced. The existing change plan selects the
architecture, Coding, documentation and existing applicable platform routes;
whole-candidate local checks and normal platform CI remain due before final
whole-Goal PR publication.

Local batch acceptance is by Codex `/root` for the authorized intermediate
Coding/Harness responsibility boundary. It accepts the private-data operation
mapping, real consumer dispatch, preserved original state/resource authority
and explicit temporary Product dependencies. It does not accept a final
public Harness API, final dependency elimination or whole-Goal completion.

## Cost And Final Acceptance

Count the Product edge, `coding.harness`, all Coding, actual Harness, Hosting,
other production code and the whole system separately; tests, development
scripts and docs are separate costs. Staging remains inside Coding and is not
system deletion. Report actual duplicate removal separately from ownership
movement; explain any necessary generic/compatibility growth.

Whole-Goal acceptance requires all frozen migration targets, their real
consumers, single implementation owners, complete mappings, explicit permitted
dependency debt, compatibility/security evidence and cumulative checks. Only
then publish the task, complete normal integration/merge/local sync and safely
remove its accepted clean worktree/branch. The first private-data batch is one
milestone, not the complete migration.
