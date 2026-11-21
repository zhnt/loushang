# Coding Harness Staging Migration

## Status

- Authority: implementation report and migration evidence.
- Owner: Coding Product, with Harness shared-owner boundary review.
- Implementation/review: Codex `/root`, within the authorized Goal.
- Design scope: the user-authorized intermediate `coding.harness` boundary;
  this report does not accept a final public Harness API or claim final extraction.
- Implementation status: the intermediate operations and their existing
  callers are recorded below. Cumulative local validation is complete for
  production candidate `4255d9bbc` with the final test-fixture corrections.
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

The accepted first private-data batch stages **66 complete implementations** in 24 program
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

The accepted first-batch snapshot cost is 2,428 staging lines, 99,638 other Coding lines and 102,066
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

### Formal POSIX Deletion And Custody

The formal private-data migration starts at `588b473bb`. The staged
private-data inventory has 25 Python files and 2,591 physical lines.

The POSIX operator CLI and SDK compose an admitted Product scope in Coding.
The narrow CLI deletion preview and the confirmed deletion owner now both
call Harness `PrivateDataDeletionJournal.preview_plan`. It reads pending
history through the existing non-repairing Journal path and observes a new
target only when no deletion is pending. The existing Journal still owns
the execution checkpoints, recovery and replay. Coding supplies its
Installation layout, confirmation admission, desired-state decision and
historical receipt identity.

Harness owns the offline scopes and private state identity checks used by
those Product entry points. The narrow read scope acquires quiescence in
read-only mode, takes the existing GC read guard and reads Desired state
without creating or repairing lock or journal state. The confirmed delete
scope retains the original exclusive GC gate and checks its Product root
authority before and after the normal operation. Coding owns SDK application
selection and the closure sequence for its bound reader and Product.

The replaced staging programs for POSIX client scopes, deletion admission
and deletion fencing are removed. Backup verification, restore and expiry
queries still have their own staged operations and are covered in later
formal migration batches.

This batch removes 280 temporary Python lines. Coding Product adds 82 lines
of entry binding and compatibility, and formal Harness adds 130 lines of
shared plan and custody code. Production Python decreases by 68 lines.
The existing Linux private-data suite and the Desired-state ownership check
pass all 86 selected cases, including CLI and SDK lifecycle operations,
deletion recovery, and refusal of missing locks or partial state on reads.

### Formal Windows Fencing And Installation Lineage

Windows deletion and restore now share the Harness mutation fence. The
existing native Product writer supplies the state descriptor. Coding binds
the nominal transactions and closes them before releasing the descriptor.
Expiry borrows the same fence through the restore transaction. Native
observation uses the Harness Windows read fence and its existing GC read
guard. The Product SDK owns candidate selection and workspace admission.

Coding chooses the exact Installation and Session path and proves the
selected manifest. The Harness Windows lineage owner binds the Installation
root, prepares the native child directory and rechecks the root identity.
The temporary Installation preparation and Windows SDK scope modules have
been removed. The read preview, confirmation and receipt proofs continue
through their remaining lifecycle migration batches.

This batch removes 215 temporary Python lines, adds 76 Coding Product lines
and adds 44 formal Harness lines. Production Python decreases by 95 lines.
The Windows candidate contracts and POSIX installation and deletion checks
pass all 49 selected cases on Linux. A mock-backed probe also verifies
the bind, prepare, rebind order and rejection of a changed identity.
Native Windows ACL and filesystem behavior require separate platform evidence.

### Formal Backup Archive And Retention

The CLI, SDK and Product backup reads use the existing Harness archive
owners. POSIX verification and archive inventory share the same
rooted archive identity and byte checks. Windows retains its native
archive and ACL checks. The Harness backup topology projects retention
on both platforms. POSIX still distinguishes completed expiry from
an interrupted rename. Windows retains its additional Desired-state,
descriptor, and unpublished-event checks before projecting a status.

Coding binds the Installation, path, source schema, historical receipt
identity and backup manifest codec. The POSIX and Windows archive programs
and the staging record adapter have been removed. The private read owner
verifies retained backups through the same Harness archive path.

This batch removes 347 temporary Python lines, adds 141 Coding Product lines
and adds 108 formal Harness lines. Production Python decreases by 98 lines.
The Linux lifecycle and historical-record checks pass 97 cases. The Windows
archive operation and snapshot probes pass 62 cases using inert native ports
on Linux. The snapshot probe now reads canonical JSON from its existing
codec module after the same stale import was reproduced on the prior commit.

### Formal Windows Preview, Confirmation And Deletion Evidence

Coding preview and confirmation now share the Windows Installation lineage
owner's bound target observation. The confirmation journal checks the exact
immutable record while holding the existing state descriptor. The deletion
consumer uses the lineage owner's native target recheck and the tree I/O
owner's tombstone verification. Deletion keeps the native path check for
an absent target and the separate pending-generation recheck. Coding still
chooses the applicable lineage, binds Product authority and constructs the
compatibility records and tombstone name.

This batch removes 298 temporary Python lines, adds 83 Coding Product lines
and adds 97 formal Harness lines. Production Python decreases by 118 lines.
The selected Windows lifecycle, original fault and lineage observations, and
Harness deletion checks pass all 230 cases on Linux. The lineage probe now
recognizes the current lazy journal import and retains its original trace,
error and wire assertions. Native Windows filesystem checks remain separate.

### Formal POSIX Restore And Confirmation

The POSIX CLI and SDK read and writer owners share the Harness deleted-archive
proof, retained-byte and restored-target verification, and exact confirmation
journal. The writer continues to use Harness archive publication, verified tree
copy and restore checkpoints. The read-only preview verifies any existing
target before checking stage debt. The writer keeps its original pre-effect
check order and the read-only path holds its existing non-repairing fence.

Coding retains the Product removal decision, storage names, restoration
admission and historical wire and type bindings. The named restore records now
reuse their own canonical field construction when creating and verifying
digests. Five restore and read staging modules have been removed.

This batch removes 577 temporary Python lines, adds 306 Coding Product lines
and adds 113 formal Harness lines. Production Python decreases by 158 lines.
All 132 selected Linux tests pass, covering POSIX CLI and SDK, restore and
expiry behavior, original fault observations and history, and the portable
Windows restore journal and preview contracts.

### Formal POSIX Expiry And Shared Expiry Records

POSIX preview, confirmation and expiry use the existing offline custody,
restore confirmation journal and Harness expiry transaction. The formal history
owner verifies the prior restore and exact archive evidence before a rename
or a recovery. Coding binds the Product Desired-state check, backup and
tombstone paths, operator acceptance and the nominal records. The read owner
continues to use the read-only Desired-state snapshot for preview.

Both platform expiry journals now validate phase, original archive and
completion receipts through the same Harness record validator. The bindings
preserve the historical errors and the POSIX-specific receipt type requirement.
The four temporary expiry program and record modules have been removed.

This batch removes 433 temporary Python lines, adds 189 Coding Product lines
and adds 101 formal Harness lines. Production Python decreases by 143 lines.
All 99 selected journal, wire, expiry, failure and replay cases pass on Linux,
including portable Windows native-port probes.

### Formal Windows Restore And Preview

The native restore preview reads the deleted archive through the same
Harness parent scope used by retained verification and the restore writer.
The archive owner binds the completed deletion before verifying bytes and
releases the descriptor before the preview inspects the destination. Both
restore routes share the completed-deletion check and the scoped removal
proof. The writer also checks the exact Installation's transition history.

Coding retains the historical publication codec, target and stage naming,
Product scope and plan construction. Both temporary Windows restore modules
have been removed. Production Python decreases by 18 lines, with 178 removed
from staging, 74 added to Coding Product and 86 added to formal Harness.
All 293 selected Windows contracts pass with inert native ports on Linux,
including the full original preview parent failure and descriptor traces.

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

## Legacy Evidence And Adoption Batch: Local Source Milestone

The next responsibility inventory is **31 files / 7,068 lines**: 30
`legacy*.py` files (6,688 lines) plus `pre_b_snapshot.py` (380). This is the
original responsibility family, not a claim that prefix membership closes the
chain. Actual source-projection, Product-runtime and lifecycle consumers remain
part of dependency/retention review.

The current candidate moves **63 complete implementations**, originally 3,904
physical lines across 27 Product modules. Complete snapshot/inventory
reconciliation, data/builtin/removed/disabled review, accepted-source binding,
acceptance reopening, installation/enablement, adoption and borrowed snapshot
scope programs now dispatch through `coding.harness.package_product`.
Original entry signatures/defaults and nominal records remain at their edges;
the internal staged APIs receive already selected defaults explicitly.

| Original `coding.package` module | Staged `coding.harness.package_product` module | Complete moved operations |
| --- | --- | --- |
| `legacy_binding_catalog` | `legacy_binding_records` | `validate_binding`, `create_binding`, `decode_binding`, `require_accepted_binding` |
| `legacy_builtin_acceptance` | `legacy_builtin_acceptance` | `accept_builtin_review`, `read_builtin_acceptance` |
| `legacy_builtin_adoption` | `legacy_builtin_adoption` | `adopt_builtin_snapshot` |
| `legacy_builtin_review` | `legacy_builtin_review` | `admit_builtin_snapshot`, `review_builtin_snapshot`, `validate_review`, `decode_review` |
| `legacy_classification` | `legacy_classification` | `classify_workspace_evidence`, `classify_source_projection`, `valid_package_source` |
| `legacy_configured_source` | `legacy_source_matching` | `match_configured_source` |
| `legacy_desired_evidence` | `legacy_desired_evidence` | `parse_desired_evidence` |
| `legacy_disabled_acceptance` | `legacy_disabled_acceptance` | `accept_disabled_review`, `read_disabled_acceptance` |
| `legacy_disabled_review` | `legacy_disabled_review` | `review_disabled_snapshot`, `decode_review` |
| `legacy_installation_inventory` | `legacy_inventory` | `read_inventory`, `classify_installations`, `classify_removed_installations` |
| `legacy_local_acceptance` | `legacy_local_acceptance` | `require_frozen_review`, `accept_local_review`, `reopen_local_acceptance`, `read_local_acceptance`, `validate_acceptance`, `create_acceptance`, `decode_acceptance`, `require_live_resource_kind` |
| `legacy_local_adoption` | `legacy_adoption` | `adopt_local_review`, `settle_removed_before_adoption` |
| `legacy_local_adoption_read` | `legacy_adoption_observation` | `adoption_settled` |
| `legacy_local_binding_owner` | `legacy_binding` | `bind_accepted_source` |
| `legacy_local_installation` | `legacy_installation` | `enable_accepted_data_plugin`, `install_accepted_plugin`, `accepted_source` |
| `legacy_local_wheel` | `legacy_local_wheel` | `reacquire_local_wheel` |
| `legacy_lock_evidence` | `legacy_binding_evidence` | `parse_binding_heads` |
| `legacy_operation_evidence` | `legacy_operation_evidence` | `classify_management_members` |
| `legacy_reacquisition` | `legacy_reacquisition` | `reacquire_installed_source` |
| `legacy_removed_acceptance` | `legacy_removed_acceptance` | `accept_removed_review`, `read_removed_acceptance` |
| `legacy_removed_adoption` | `legacy_removed_adoption` | `adopt_removed_snapshot` |
| `legacy_removed_review` | `legacy_removed_review` | `snapshot_has_operations`, `admit_removed_snapshot`, `review_removed_snapshot`, `validate_entry`, `entry_from_evidence`, `decode_entry`, `validate_review`, `decode_review` |
| `legacy_review` | `legacy_local_review` | `review_local_source`, `validate_review`, `decode_review` |
| `legacy_skill_cutover_admission` | `legacy_data_admission` | `admit_local_snapshot`, `require_fenced_local_snapshot`, `require_data_kind` |
| `legacy_source_consumption` | `legacy_source_consumption` | `frozen_sources` |
| `legacy_source_evidence` | `legacy_source_evidence` | `parse_source_evidence` |
| `pre_b_snapshot` | `legacy_snapshot_scope` | `pre_snapshot_scope`, `cutover_store` |

### Reviewed Legacy Retention And Consumer Closure

Every source in the 31-file responsibility family has a concrete disposition.
The reasons below identify Product policy, necessary nominal/wire contracts or
an already shared owner; a historical name alone is not a retention reason.

| Original module | Retained edge and existing shared owner |
| --- | --- |
| `legacy_binding_catalog` | Nominal binding fields and exact wire schema, typed resource/version policy, Code error identity and original catalog configuration. The remaining initializer binds the original path/source/store/scope/policy/acceptance-reader state and durability/load policy to the existing Harness _LegacyLocalSourceCatalog; append/read/publish/extend methods are direct inherited adapters. Validation, decoding, construction and accepted-review correlation are staged. |
| `legacy_builtin_acceptance` | Nominal acceptance receipt, exact acceptance ID domain/path/version/codec and private-receipt projections; complete accept/read programs are staged. Durable receipt publication remains the existing Harness owner. |
| `legacy_builtin_adoption` | Nominal adoption result plus Code builtin/admission declarations and original operation identity; complete adoption program is staged and reuses the existing bootstrap owner. |
| `legacy_builtin_review` | Nominal review fields, required wire layout/identity, supported old builtin/removal/domain/member declarations and exact error type. Full admission, validation, decoding and snapshot review are staged. |
| `legacy_classification` | Nominal inventory facts, actual Product source/projection/filter-key and scope declarations. Both complete classifiers and package-source validation are staged; no second classifier body remains. |
| `legacy_configured_source` | Nominal configured-source scope/path, actual old builtin admission and the explicit max-source quota. Matching is staged; Code keeps its public default/identity. |
| `legacy_data_trust` | Actual Product decision mapping skill/prompt/theme to permitted trust classes and resource owners, including local-data-only policy. This is an intentional Product trust boundary, not an unshared loader or migration engine. |
| `legacy_desired_evidence` | Nominal desired snapshot/digest/transitions, budget and exact duplicate-key diagnostics. The short reader names the historical desired member and uses the existing authenticated snapshot binding; complete decoding and foreign-scope proof are staged. |
| `legacy_disabled_acceptance` | Nominal acceptance, exact filename/ID/version/codec and original receipt IO adapters. Accept/read coordination is staged and uses the existing Harness acceptance/receipt mechanism. |
| `legacy_disabled_review` | Nominal disabled-only record, version, required nonempty disable declaration and exact wire identity/schema. Small post-init binds these nominal requirements to existing canonical hashing; full projection review and decoding are staged. |
| `legacy_installation_inventory` | Nominal local/removed/builtin/inventory evidence records, original state aliases and actual old builtin set. Read/reconcile/active/removed classification are staged; the shared management proof has one owner. |
| `legacy_instance_evidence` | Unchanged 33-line Product envelope: original nominal inputs/byte budget/path projection and error identity call existing Harness inspect_gracefully_retired_instance_capture. The complete retirement/runtime proof was already shared before this Goal. |
| `legacy_local_acceptance` | Nominal acceptance/wire/resource-version policy, typed resource declarations and existing protocol/codec configuration. Accept/reopen/read/frozen-review/live-kind proofs and nontrivial record admission/decoding are staged. |
| `legacy_local_adoption` | Nominal result and compatible Skill entry selecting actual resource_kind=skill; Product builtin key/hash/error projections into already shared preserve_removed_product_plugin. Full adoption and prerequisite settlement are staged. |
| `legacy_local_adoption_read` | Nominal settled result/version and original policy/identity declarations; complete settlement proof is staged. |
| `legacy_local_binding_owner` | Product binding operation identity/path/policy declarations and compatibility entry; complete accepted-source binding program is staged. |
| `legacy_local_installation` | Compatible install/Skill selection entries, Product operation-ID domains/session prefix/error projection and the direct _LegacyLocalInstallation constructor binding. The existing Harness owner executes installation/enablement; whole coordination and exact accepted-source proof are staged. |
| `legacy_local_wheel` | Nominal candidate and original legacy wheel/private-budget/error declarations; reacquisition program is staged over the existing resource wheel/materialization owners. |
| `legacy_lock_evidence` | Nominal binding evidence, exact supported lock/wire/hash/budget and duplicate-key declarations. Short reader binds the historical authenticated snapshot member; full head parsing is staged. |
| `legacy_operation_evidence` | Nominal operation/retirement capture, supported historical service/member shapes and budgets/error identity. Classification is staged. Existing 33-line type/envelope projection calls Harness inspect_settled_management_capture, whose complete parsing/replay is baseline shared capability. |
| `legacy_reacquisition` | Nominal reacquired result and original Product input/policy binding; complete inventory/source/wheel association program is staged. |
| `legacy_removed_acceptance` | Nominal acceptance/wire/ID/path declarations and direct existing receipt publication adapter; complete accept/read coordination is staged. |
| `legacy_removed_adoption` | Nominal removed-adoption result and actual Product builtin/removal policy/identity declarations; complete adoption program is staged. |
| `legacy_removed_review` | Nominal entry/review fields, original wire identity/schema and supported old builtin/domain/member policy. _identity is an explicit wire-field declaration using existing schema traversal; all nontrivial admission, record validation/decoding and read/review proofs are staged. |
| `legacy_review` | Nominal review fields/wire schema, exact legacy wheel/ID/policy patterns and builtin-removal ID domain/allowlist. _identity_dict declares optional wire fields over existing RecordSchema; full validation/decoding/source review are staged. |
| `legacy_skill_cutover_admission` | Actual supported data kinds, max-local quota, old removable builtin set and nominal wheel-inspection projection into the already shared inert-wheel inspector. The Skill entry selects Product kind; full snapshot/admission and operator-kind consistency programs are staged. |
| `legacy_snapshot_member` | Unchanged Product binding to Harness _LegacyFirstSnapshot: exact lifecycle/epoch roots, store/error identity and permitted domains, plus nominal observer/type aliases. Full snapshot authentication/reads already belonged to Harness before this Goal. |
| `legacy_source_consumption` | Original receipt/path/identity and actual Product acceptance/source policy declarations configuring Harness _SourceConsumptionProtocol. Consume/consumed entries directly reuse that existing complete owner; frozen source association proof is staged. |
| `legacy_source_evidence` | Nominal projection bytes/classification/digest, budget, actual settings scope/path and error/JSON hooks. Detached source_patch is the original wire-field projection; reader binds a historical member through the existing snapshot authority. Complete canonical projection validation is staged. |
| `legacy_windows_receipt` | Unchanged Code error identity and byte/attribute/stage policy configuring the existing WindowsPrivateReceiptIO. All receipt/ledger reads, atomic publication/retry and native safety mechanisms were already shared. |
| `pre_b_snapshot` | Nominal preparation/cutover bundles, deployed root geometry, fresh-only admission policy, explicit Windows-candidate admission and Code builtin bootstrap choice. Staging owns preparation, the pinned snapshot lifetime, cutover and native reopen. The existing Harness owners perform the directory and snapshot effects. |

Actual external Code consumers (including deferred imports) are:

`authoring.extension`, `authoring.plugin_smoke`, `cli.package_cutover`, `composition.base_product`, `composition.external_data`, `composition.product_capability_plugins`, `package.cutover_backup`, `package.external_worker_wheel`, `package.installation_private_data`, `package.private_data_windows_backup_expiry_journal`, `package.private_data_windows_confirmation`, `package.private_data_windows_deletion_journal`, `package.private_data_windows_restore_journal`, `package.product_backup_types`, `package.product_preview`, `package.product_revisions`, `package.product_runtime`, `package.product_worker_windows_checkpoint`, `package.product_worker_windows_crash_stage_retirement`, `package.product_worker_windows_history_bases`, `package.product_worker_windows_history_preparation`, `package.product_worker_windows_installed_backend`, `package.product_worker_windows_launch_intent`, `package.product_worker_windows_partial_stage_retirement`, `package.product_worker_windows_persisted_bases`, `package.product_worker_windows_stage_retirement`, `package.product_worker_windows_unlaunched_stage_retirement`.

Their historical imports and nominal bindings remain in place. The old public
operations now enter the single staged implementation; unchanged receipt/trust
bindings continue directly into their existing Harness owners. The complete
31-file review does not accept the unrelated Product runtime, epoch layout,
worker or lifecycle responsibilities that remain in later frozen batches.

### Concrete Reuse And Dependency Debt

Two complete management-history proofs now use one implementation,
`legacy_management_evidence.verify_settled_history`: service-lock bytes,
operation history, retirement journals and graceful retired-runtime evidence
are checked in their original order. Inventory and cutover admission retain
their distinct existing read authorities and error identities. The one read
port preserves original per-read binding lookup and checks; no new snapshot,
journal, lock or mutable authority is introduced. The original caller module
is an explicit temporary receiver for its parser/record fault lookup seams.
This dynamic dependency is recorded alongside static imports, rather than
claimed absent.

The two replaced proof bodies total 171 lines. The shared file including its
documentation/imports is 88 lines, the two actual call sites are 34 lines and
new imports/separation cost four lines: this reuse unit removes **45 lines**.
That local deletion is separate from broader migration growth. Full parent
bodies expand through the actual shared call arguments to the original proof
AST, including IO budgets, types, order and errors. Existing Harness
`_LegacyFirstSnapshot`, source-consumption protocol, source catalog,
retirement/parsing, journal and resource owners remain in use; none is
reimplemented or counted as new migration benefit.

Across both current batches, all original logical dependencies normalize to
the same 1,650 module pairs. Fifty-two staged program/proof modules have
explicit original Code back references, including the shared proof's cycle
through inventory. Final Harness does not import the staging namespace.
These are permitted intermediate debts, not final shared API acceptance.

### Current Cost, Evidence And Remaining Work

| Scope | Python physical lines |
| --- | ---: |
| All Coding, including staging | 104125 |
| `coding.harness` | 6997 |
| Other Coding | 97128 |
| Production change since Goal baseline | +3410 |
| Production change since accepted private-data batch | +2059 |
| Actual Harness / Hosting / other production change | 0 |
| Test / Product development script change | 0 |

The 143 declaration lines and unchanged root boundary are separate. Staging
remains Coding; neither moved source bodies nor the 45-line local reuse unit
establish system net deletion. Nominal/API wrappers, explicit Product policy
and historical error/wire declarations, typed interfaces and qualification
cost more lines than this batch currently removes. Continue assessing concrete
reuse rather than counting Code departure as total simplification.

Before this batch, 68 original inventory/lock/desired/source-custody tests pass
in 77.39 seconds. The first 15-program candidate passes 131 related cases in
141.41 seconds. After the shared-history change, its 56 affected cases pass in
121.75 seconds. The 34-program adoption/Cutover/CLI/platform-selector candidate completed with
304 passed, 49 skipped and one installed Embedded terminal startup failure.
That exact failure also reproduces on committed pre-Legacy `5aa7d44f2` in a
separate clean baseline worktree: `transcript_writer:unsafe` then the unchanged
35-second terminal predicate timeout. Both embedded subcases intentionally
strip source paths and launch the same shared installed entry, whose editable
package points to the control lane, not this candidate. This is not evidence
of the staged source being accepted by an installed-wheel route. No Product
safety or timeout was changed. A private test-directory exception is pending
user reply; final installed-candidate/platform validation remains due.

The later eight-program parsing candidate passes 86 related cases in
111.10 seconds. The record/proof candidate passes 106 related cases in
52.75 seconds; after final cutover/source-kind closure, 47 affected cases pass
in 51.28 seconds. These are layered affected-path results, not a sum of unique
cases or a claim that the earlier broad run covered later changes. Current mypy passes 60 sources and
Ruff passes. All 351 captured original Legacy Code symbol contracts remain
equal, and all 63 moved bodies compare equal to their originals after binding,
policy, relative-import and shared-proof expansion. Original golden records
and tests are unchanged.

The 31-file semantic disposition and 27 actual external Code consumers are
recorded. Four modules retain actual Product trust or preexisting shared
bindings; 27 contain the original nominal/policy entries for staged programs.
Full source-scope closure now includes record admission/decoding, source/lock/
desired parsing, exact accepted-source and operator-kind proofs, snapshot
lifetime and cutover execution. Original paths now dispatch to single staged
implementations; compatibility constructors and wire declarations remain at
Code edges. Existing effect and persistence engines remain the Harness owners.

Codex `/root` accepts this local intermediate source capability milestone
within the authorized responsibility boundary: complete operation dispatch,
31-file/27-consumer closure, record/type compatibility, original state authority
and explicit intermediate dependency debt. This does not accept an installed
candidate or native Windows execution. The installed-terminal
failure and native Windows routes are explicit remaining verification limits;
whole-Goal acceptance, final dependency elimination and remote delivery have
not occurred.

## Package Runtime And Plugin Lifecycle: In Progress

This third batch reviews the frozen 33-file, 10,003-line package-runtime and
plugin-manager inventory. It has not reached batch acceptance. Five original
modules currently dispatch 19 complete runtime, management, preview, repair
and lifecycle operations to five staged modules. These operations occupied
1,217 original lines; this is ownership movement, not net deletion. Original
state objects, locks, public defaults, nominal classes and cleanup authority
remain unchanged. Existing Harness effect owners execute the operations.

The frozen first-19-operation snapshot contains 104,703 Python lines in all Coding, including 8,373
lines in 60 staged files. Coding excluding staging contains 96,330 lines;
the root remains 399 lines and declarations remain 143 lines. Relative to the
original 100,715-line baseline, production grows by 3,988 lines, all inside
Coding. Actual Harness, Hosting, other production code, tests and development
scripts have no changes. This candidate adds 578 lines beyond the accepted
Legacy checkpoint. Compatibility wrappers, explicit Product declarations,
types and binding qualification remain material costs, not deletion benefits.

All 211 captured original symbol contracts compare equal. All 19 moved bodies
compare equal after resolving original bindings, policy declarations and
relative imports; only genuine function docstring indentation is normalized,
never executable strings. Ruff and mypy pass for the ten changed source files.
The nine-file lifecycle/CLI/repair/catalog/preview/resume consumer regression
completed with 324 passed and 5 skipped in 1,645.70 seconds against the frozen
first-19-operation snapshot. That source snapshot is archived separately; its
passing result does not cover later observation, CLI reuse or startup edits.

The baseline revision-custody probe reports 39 failures and 13 passing cases
before these changes. Its exact source-path resolution trace differs from its
frozen expected trace. One failing normal case also reproduces on the clean
pre-Legacy checkpoint `5aa7d44f2`; neither `builtin_wheel.py` nor
`product_revisions.py` has changed from the original baseline. This establishes
that the observed mismatch predates this candidate, not its complete cause.
No expected fixture, Product behavior, timeout or gate was changed. The probe
remains a verification limitation requiring comparison of actual baseline and
candidate observations where affected.

For that first snapshot, logical dependency normalization preserves all 1,650 original internal
module pairs with no added or removed pair. All 57 staged program modules with
original-binding backreferences are recorded as intermediate debt, including
the shared history proof. This does not erase physical import cycles or prove
final Harness neutrality. Product factories and nominal state still borrowed
by this batch must be replaced at complete capability boundaries before final
extraction to actual Harness.

Remaining review includes complete read-only discovery and owner-evidence
joins, external Wheel record validation/encoding, remaining startup/retry
coordination and Product resource preview. UI rendering, actual Product
composition/default declarations, historical nominal contracts and already
shared leaf operations are assessed separately; an existing shared engine is
not migrated or counted again. The wider frozen Worker and execution scope
remains required after this batch.

### Further Observation Chain Work: In Progress

The existing validation worktree runs one immutable candidate at a time.
After its first runtime regression completed, the eleven-file source snapshot
was archived with hashes before refreshing that directory from the active
`harness/coding-harness-staging-batch3` worktree. Both worktrees keep the same
two accepted commits as ancestors. Further edits happen only in the active
worktree; validation snapshots remain fixed through each runtime run. Both
worktrees belong to this Goal and require safe cleanup after delivery.

The subsequent candidate moves another ten complete operations, 884 original
lines, covering bounded settings capture, current preview, read-only discovery,
exact inert artifact classification and management/preview drift rechecks. A
further 202-line resource-preview operation joins selected manifests, Product
composition, catalog resources and before/after revision evidence without live
activation. Product identities, legacy trust-class declarations, actual
composition/catalog factories, capture quotas and CLI guidance remain at Code
edges. Existing Harness catalog, resource projection and revision owners remain
in use; no new settings or lifecycle manager was introduced.

All ten observation programs and the resource-preview body compare equal to
their originals after explicit binding/policy resolution. Ruff passes, mypy
passes for the eight observation sources and the two preview sources, and all
53 original observation symbol contracts and 211 original package/lifecycle
contracts remain equal. These symbol sets overlap and are not summed as unique
coverage. The existing strict Harness settings reader would change duplicate
JSON key acceptance and error priority; it is therefore not silently substituted
for the original bounded raw read. Later final extraction must close that
specific compatibility gap at the existing configuration owner.

The CLI install/update route now reuses the existing
`_plugin_bootstrap._product_plugin_runtime` owner for factory selection,
creation, activation and bound/unbound cleanup. Its other existing consumer is
Plugin bootstrap. Actual CLI IDs, source admission, lifecycle intent, output
and failure reporting remain Code responsibilities. The opened Product belongs
to the CLI workspace, which the shared scope uses for its runtime request.
The old nominal import names remain available. This removes 10 lines from the
complete CLI file including import cost, without changing actual Harness code
or introducing callbacks/another runtime manager. The later nine-route snapshot covers real CLI installation/update, failure
handoff and workspace replacement. It completes with 324 passed, 5 skipped
and four native-discovery failures in 129.96 seconds. All four failures also
reproduce in the unmodified pre-Legacy baseline `5aa7d44f2`, where the exact
local-discovery file reports 4 failed and 1 passed in 17.73 seconds. Native
Skill/Prompt rows are missing and one root-swap expectation does not trigger;
the cause was not established in that snapshot. The follow-up fixture-isolation
evidence below resolves these cases without changing Product source or
expected assertions.
At that checkpoint this remained a baseline verification limitation; the
follow-up identifies ancestor project-context discovery as the cause.

The 30-operation snapshot contains 105,062 Python lines in Coding: 9,610 in 65 staged
files and 95,452 outside staging. Root source remains 399 lines, with 143
separate declaration lines. Production is 4,347 lines above the original
baseline; actual Harness, Hosting, other production code, tests and development
scripts remain unchanged. Thirty complete runtime/lifecycle/observation
operations have moved in this uncommitted batch, covering 2,303 original lines.
This is not whole-batch acceptance or a deletion claim. The additional staged
observation/preview work and CLI reuse cost 359 production lines beyond the
frozen first-19-operation snapshot. Later startup/source-record runtime validation is pending.

### Startup, Source Records And Compatibility Projection: In Progress

Another fifteen complete operations, 568 original lines across five original
modules, now stage first initialization, bootstrap/retry, historical fresh-
snapshot proof, external data/dependency/Worker record admission and wire
operations, and enablement compatibility publication/mutation fencing. The
same original nominal records, registry, locks, resource owners and Product
approval functions remain in use. Actual default plugin IDs, package
distribution identity, historical path/error declarations and snapshot byte
caps stay in Code declarations. Existing catalog, Journal, bootstrap,
configuration-registry and platform owners retain their original effects.

All fifteen bodies match their originals after binding/policy resolution;
the earlier nineteen runtime bodies also still match after distribution
identity was moved to explicit Code declarations. All 86 captured original
startup/source-record/compatibility symbols remain equal. Ruff passes and
mypy passes thirteen affected sources. These checks establish source and
contract evidence. Its affected runtime snapshot completes with 156 passed
and two existing architecture-inventory location failures in 122.72 seconds.
Runtime startup, retry, source publication/failure probes, Worker source facts
and compatibility routes pass. The two failures identify moved source owners,
not additional Desired State writers; the sole-writer assertion still passes.

The 45-operation snapshot contains 105,425 Python lines, including 10,290 in 70 staged
files and 95,135 outside staging. Root source remains 399 lines and separate
declarations remain 143 lines. The current uncommitted runtime/lifecycle batch
contains 45 complete moved operations covering 2,871 original lines, plus the
existing CLI runtime-scope reuse. Production grows by 4,710 lines relative to
the original baseline, all in Coding. Actual Harness, Hosting, other production
code, tests and development scripts remain unchanged. Staged ownership
movement is not system deletion. All 67 staged modules with original-binding
backreferences remain explicit intermediate debt.

The 33-file batch retains ten reviewed Product/compatibility boundaries;
thirteen modules are partially migrated, one partially reuses an existing
owner and nine still require semantic disposition. Whole-batch acceptance,
the wider frozen Worker/execution scope and unified remote delivery remain due.
The existing architecture inventory also names source scopes that have moved;
its expected owner locations must be reconciled with reviewed mappings while
preserving existing assertions and coverage, without adding or expanding gates.

### Owner Evidence And Exact Inventory Maintenance: In Progress

Six further complete record/proof operations, 185 original lines, now stage
owner-generation validation, construction, wire encoding/decoding, historical
identity and read-only operation handoff evidence. The existing Session
`_OwnerGenerationEvidenceLedger` remains the sole journal/publication owner;
its previous sharing is baseline, not new migration benefit. Original nominal
records, codec identity, historical hash domain, Product scope decisions and
repair guidance remain Code-edge declarations/bindings. All six bodies match
their originals, all sixteen captured original symbol contracts remain equal,
and Ruff/mypy pass the four affected sources. The frozen follow-up run passes
35 cases in 53.24 seconds, covering owner evidence, support projection, real CLI
installation and the updated existing architecture inventory.

The existing PLC9 inventory now points to the reviewed staged owners. A
static mapping proves its 130 `disabled_plugins` source facts remain exactly
130 after relocation, with no unmatched added/removed fact. All 155 existing
assertions and the existing test function names remain unchanged. Only exact
file/scope inventory values and the accompanying inventory document changed;
no workflow, trigger, platform, matrix, coverage or gate assertion was added.
Fresh-state construction is mapped to the staged complete runtime owner;
management still holds the same two actual Desired State write sites. The
updated existing architecture assertions pass in that 35-case follow-up run.

The 51-operation snapshot contains 105,554 Python lines: 10,513 in 72 staged files and
95,041 outside staging, with root source 399 lines and declarations 143 lines.
The current uncommitted batch holds 51 complete moved operations covering
3,056 original lines, plus the ten-line CLI runtime-scope reuse reduction.
Production is 4,839 lines above the original baseline, entirely in Coding.
Actual Harness, Hosting and other production sources remain unchanged. The
existing architecture test inventory grows by 48 lines, reported separately;
Product development scripts remain unchanged. All 69 staged original-binding
backreferences remain explicit intermediate debt.

The 33-file inventory now records seventeen concrete Product/compatibility
retentions, fifteen partially migrated modules and one partial existing-owner
reuse. This is a complete disposition inventory, not complete mechanism or
batch acceptance. Remaining Code operations in those partial modules still
need per-operation closure and consumer validation. In particular, the small
historical CLI workspace-error adapter remains because it refuses identity
mismatch before path resolution and suppresses initial lstat errors; the
existing shared check resolves first and chains lstat failures. Replacing it
without compatible semantics would change failure priority. The wider frozen
Worker/execution range and final unified remote delivery remain required.

### Source Capture And Membership Closure: In Progress

Five more original operations, 116 original lines, now stage complete Source
capture lifetimes, the existing private-directory read proof and dependency
filename admission. Data and Dependency endpoints share one full epoch/fence/
catalog/capture/close implementation; the nominal catalog lookup remains at its
original point after epoch/fence observation, rather than being cached before
opening. Actual filenames and error identity remain Code declarations. Worker
keeps its real Windows/POSIX routes. Read-only directory checks retain the
same flags, owner/mode/inode checks and close ordering. Dependency parsing
reuses the original `packaging` parser through the original fault binding.
All five bodies compare equal after specializing only the fixed source kind
and resolving declarations; the distinct original public docs remain at Code
edges. This is mechanism deduplication plus staging, not a net-line deletion
claim after compatibility and policy cost.

Four more operations, 144 original lines, now stage canonical owner
contributions, holder-reference encoding/validation and the compatibility
projection under the existing capture owner. Foreign/V1 references still
return no inactivity proof and remain fail-closed. Actual Product scope and
holder namespace remain declared in Code; no new ledger, manager or callback
framework was added. All four bodies compare equal, Ruff/mypy pass the two
membership sources, the six source-capture/proof sources pass mypy, and all
211 original package/lifecycle symbol contracts remain equal. The frozen source and membership regression passes 335 cases in 430.22
seconds, including the existing PLC9 inventory and native-discovery tests.

The four native-discovery failures have a demonstrated fixture cause. In the
unchanged pre-Legacy baseline, read-only post-mortem inspection observes
`receipt.project_resource_root == /home/dev/lsspace`, while the intended test
workspace is inside its private RunLease basetemp. The inherited workspace
`AGENTS.md` becomes the nearest legacy project context; therefore native rows
come from that ancestor and the test's workspace-swap hook never fires.
Each of the four existing fixture workspaces now declares its own `AGENTS.md`.
All original assertions and five test names remain unchanged. The exact setup
on unchanged baseline Product source passes all five cases in 16.13 seconds;
the temporary baseline test edit was restored byte-for-byte and that worktree
is clean. The same five cases pass in the 335-case staged candidate run.
This fixture isolation adds no test, assertion, route or PR gate.

The 60-entry snapshot contains 105,700 Python lines: 10,806 in 74 staged files and
94,894 outside staging. Root source remains 399 lines; declarations remain
143 lines. The uncommitted batch now covers sixty original operation entries
and fifty-nine implementation bodies, totaling 3,316 original lines. The
shared Data/Dependency implementation accounts for the one fewer body.
Production is 4,985 lines above the original baseline, all in Coding. Actual
Harness, Hosting and other production code remain unchanged. Existing test
inventory/setup changes total +59 lines; Product development scripts remain
unchanged. All 71 staged original-binding backreferences remain explicit
intermediate debt. Staging and a reviewed inventory do not establish whole
batch or whole-Goal completion.

### Reviewed Retention Within The Runtime/Lifecycle Batch

These ten decisions concern specific Product/compatibility boundaries, not
acceptance of the remaining 33-file batch. None is counted as migrated code.

| Original Code module | Concrete retention reason / existing implementation owner |
| --- | --- |
| `package.__init__` | Namespace only. |
| `package._legacy_names` | Frozen historical import-name compatibility. |
| `plugin_manager.__init__` | Namespace only. |
| `plugin_manager._legacy_names` | Frozen historical import-name compatibility. |
| `package.source_snapshot` | Actual settings keys, projection path and compatibility decisions; `_LegacySourceProjection` and the existing Windows private-directory owner already provide IO/lifetime. |
| `package.cutover_backup` | Historical nominal DTO and wire contract; `inspect_legacy_cutover_backup` already owns snapshot proof. Product entry selects its epoch and read-only route. |
| `package.product_revisions` | Actual builtin IDs, paths, factory/resource admission declarations in `ProductSelectedRevisionPolicy`; existing selected-resolution owner and validators implement the mechanisms. |
| `package.product_repair_rpc` | Product identity/scope and local repair-client endpoint binding. |
| `package.product_repair_ui` | Actual command syntax, action policy, result identity and user rendering; repair effects delegate to the repair client. |
| `plugin_manager.command_rpc` | Actual RPC actor, policy revision and Product authority; submit/resume already call existing Harness desired-command operations. |

The per-file inventory keeps other modules pending or partially migrated.
In particular, remaining discovery/projection, external record mechanisms,
startup retry and resource preview coordination cannot be retained wholesale
merely because they refer to Code nominal types or Product identifiers.

## Package And Plugin Lifecycle Checkpoint

The local checkpoint covers fenced state and runtime opening, startup and
retry, source admission and record custody, read-only discovery and preview,
owner and membership evidence, compatibility projection and CLI runtime
lifetime reuse. The original fifty-nine staged implementations serve sixty
operation entries. The source and membership run closed the four discovery
fixture failures on this candidate and passes all 335 cases. Earlier focused
results cover the affected recovery, replay and fault-order routes listed above.

The wider frozen inventory still includes remaining CLI command transaction
coordination, outstanding Worker chains and the Session execution scope.
This checkpoint records the verified lifecycle and observation paths as a
local batch. Existing platform and installed-entry validation limits continue
to apply to the cumulative Goal.

## Worker Startup And Retained Resume

The Worker slice moves ordinary session selection and both platform paths for
pending graph preparation. The moved operations cover 378 original lines.
They reuse the existing startup selection, receipt, provider and native effect
owners. Coding still supplies the actual Worker capability and owner policy,
selected package quotas, timing policy and nominal receipts. POSIX retains its
optional base guard. Windows retains its exact receipt-owner and pending-launch
type checks, base-owner identity check and recovery check before graph
preparation. The three original public modules remain the compatibility
entry points.

The Resume slice moves six operations covering 256 original lines. It stages
background planning and freshness checks together with retained preparation,
consumption, abort and first input. The existing Harness planning slot,
retained lifecycle operation and Session transport own their original state.
The Coding runtime retains its actual Product selector, embedded approval
binding, nominal results and historical error identities. Each moved
operation resolves the same original checks and owner calls in order.

Ruff and mypy pass for both slices. All 44 Worker and 27 Resume original
symbol contracts compare equal, and all 11 implementation bodies match
after resolving the staged owner bindings. The affected non-live test run
passes 62 cases in 35.63 seconds, including the Resume planning trace,
embedded coordinator and Worker input routes. Host-runtime-only Worker
execution and native Windows still require their existing platform routes.
The staged startup operations use existing Harness owners, so the moved
body count carries no credit for preexisting shared implementation.

The existing architecture run passed 202 test cases across five files. The
sole failing case used the old Worker consumer inventory. Its expected paths
now include the relocated pending preparations alongside the compatibility type
declarations. That exact existing case passed on recheck. The update preserves
the exact consumer equality check and keeps the existing test selection.

The retained-preparation snapshot contains 106,188 Coding Python lines, including 11,598 in 81 staged
files and 94,590 outside staging. This is 5,473 more production lines than
the original baseline. The two slices add 488 lines beyond the preceding
candidate, including repeated typed signatures and explicit policy/error
bindings. Actual Harness, Hosting and other production code have no line
change. The logical Coding import graph retains all 1,650 original module
pairs. The 76 physical original-binding backreferences remain tracked for
later extraction. The broader Worker and Session scope remains open.

### Resume Writer And Selected History

The staged continuation now coordinates protocol negotiation, effect-owner
admission, Writer acquisition, durable intent, graph preparation, first input,
publication and failure cleanup in one operation. The original SessionManager,
Session, approval journals and Worker state journal remain the owners of their
effects. The original Product constructors, accepted protocols, scope values
and durable domains stay in Coding. Failure after an uncertain input commit
still exposes the original input lookup and retains the original cleanup
owner when disposal fails.

The selected-path projector also moves its complete streaming implementation.
The public synchronous and cooperative asynchronous entry points and their
shared iterator preserve coroutine and generator semantics. Unknown versions
still block, exact persisted intent is required for v2, and v1 cannot close a
v2 intent. The projected facts grant no present admission.

This slice covers 515 original lines in four operations. Ruff and mypy pass
for both donor and staged files. The 43 captured original symbol contracts
compare equal and all four implementation bodies match after resolving the
original bindings. The continuation, projection, recovery and embedded consumer run passed all
147 cases in 339.96 seconds. The transaction snapshot
contains 106,544 Coding Python lines, including 12,275 in staging and 94,269
outside it. The system production total grows by 5,829 lines from the Goal
baseline. The new slice adds 356 lines, mainly typed compatibility entries
and Product policy and error declarations. The existing 399-line root and
143 type declaration lines are measured separately.

### Read-Only History And Activation Plan

The bounded snapshot and recent-page readers now live with the planning
mechanism. The existing Transcript reader, repository and Resource preview
owner still hold the original IO and capacity. The snapshot checks the same
source fingerprint before and after a bounded read. The recent page does not
prove selected ancestry. A completed plan retains explicit source, composition
and owner observations. The same checks reject stale results and unavailable
history before requesting Resource work. Product limits and identity domains
remain with the original Product modules.

This slice moves seven original entry points comprising 380 lines. Ruff and
mypy pass, all 30 original symbol contracts compare equal, and the seven
operation bodies match after resolving the original bindings. The targeted
planning, history and original observation-order regressions pass all 97 cases
in 19.42 seconds. The Worker startup, retained preparation, continuation,
history and plan batch covers 22 entry points and 1,529 original lines.
The Worker host-runtime and native Windows routes remain distinct from local
focused verification.

The batch adds 1,057 production lines overall, reduces the Coding edge by
839 lines and adds 1,896 lines to staging. Current Coding contains 106,757
Python lines, with 12,702 in 85 staged files and 94,055 outside staging.
Production grows by 6,042 lines against the startup baseline. The actual
Harness and Hosting owners have no production line change. The 80 staging
backreferences remain in the exit inventory. Normalized logical dependencies
remain at 1,650 module pairs. The only test source change for this batch is
the four-line update to the existing Worker path inventory.

## CLI Package Commands

Removal now stages the revision retry, original idempotency calculation,
Desired State compare-and-submit, follow-up retirement reads and failure
evidence. Coding keeps CLI scope admission and the original success and
failure rendering. The coordinator uses the same Harness command and read
ports. Each operand resets its failure identity before the next attempt, and
an uncertain retirement result is observed through the original read paths.
This preserves the distinction between a committed removal, a pending
operation and unknown cleanup evidence.

Install/update also stages source admission, the existing PackageProduct
runtime scope, operation routing and the independent reads used after a failed
handoff. Coding keeps the success and failure bytes, scope refusal, actual
operation and runtime identity, and follow-up repair guidance. The original
factory lifetime still uses `_product_plugin_runtime`. Neither success output
nor failure reporting changes the replay or cleanup authority.

Ruff and mypy pass for the three files. The core transactions and observed
failure facts match the prior source after restoring the original renderers
and explicit policy values. Uninstall alone passed all eight real CLI tests,
including batch output and retirement interruption. The full CLI candidate then passed the same eight public journey and
failure cases in 145.33 seconds, including exact partial-commit reporting. The command slice removes 120 lines at the
Coding edge and adds 279 staged lines, a net production increase of 159 lines.
Logical dependency review records two actual new edges, to the existing
Product identity and to the nominal Wheel source record used by the renderer.
Neither target has a path back to the CLI. The overall graph has 1,652 logical
module pairs and 82 separately tracked staged backreferences. Current Coding
contains 106,916 Python lines, including 12,981 in staging and 93,935 at the
product edge. The production increase from the startup baseline is 6,201 lines.
The command slice is ready as a local checkpoint.

## Selected Plugin Preparation

The managed and fenced selected-plugin preparation routes now stage the
original selection, approval, compilation, workspace binding inputs and
failure custody sequences. Resume effect settlement checks move with that
preparation chain. Existing Harness composition, selected runtime scope and
cleanup owners continue to hold the effects. Coding retains actual builtin
plugin configuration, approval decisions, source constraints and nominal
prepared results. Two identical preparation-failure paths share one call that
closes the original custodian and attaches it to the original error if close
fails.

The four operations cover 493 original lines. Ruff and mypy passed on the
affected files, all 72 original symbols compare equal, and the original
operation bodies match after resolving the edge bindings and the shared
cleanup call. The existing approval, preview, embedded Resume and
architecture regression passed all 135 cases in 76.56 seconds. The candidate adds 548 staged lines and removes
312 lines at the Coding edge. Current Coding contains 107,152 Python lines,
13,529 in staging and 93,623 at the Product edge. The system production total
grows by 6,437 lines against the initial baseline. The latest slice accounts
for 236 of those lines and adds two temporary owner backreferences. The
existing logical dependency pairs are identical to the CLI checkpoint.
This prepared-plugin work remains in the active composition batch.

## Base And External Resource Composition

The Base and external-only selections stage their resource catalog
composition, selected Store body capture and resource input assembly under
`coding.harness.session`. Both paths use one external trust, declaration and
owner check. The Base path retains its missing-trust check. The external-only
path retains its trust snapshot type and installation identity checks in the
original order. Product trust values, ownership policy and nominal request
and result types stay in the Coding composition modules.

The six operations cover 475 original lines. The original bodies compare
equal after resolving bindings and expanding the common check, and all 22
original symbol contracts compare equal. Ruff and focused mypy pass, and 21
existing preview, architecture and external package cases pass in 296.32
seconds. This slice adds 526 lines in staging
and removes 318 at the product edge. The combined working tree has 107,360
Coding Python lines, including 14,055 in staging and 93,305 at the product
edge. The increase in production lines since the initial baseline is 6,645.

## Session Catalog Preparation And Refresh Inputs

Five startup and refresh sites share one receipt read and admission check.
Both fenced Base routes share the requested-plugin observation and selected
root preparation. The observed history still records disabled and previously
removed plugins. A requested plugin with no installation history still fails
at its original point. The Base, capability and resource refresh checks share
one manifest recheck while retaining each original restart reason and their
relative order.

The staged catalog preparation module uses the existing Harness loader and
Package Product runtime. Coding supplies the nominal admission error and keeps
its requested plugin IDs, root paths, cleanup policy and publication
composition. The pinned package's resource-only plan filter now uses the
same staged module. The Coding entry supplies the Product plugin identifier
and retains the nominal seed construction and original owner bindings.
Initial composition uses one Base fallback when there is no prepared
capability composition. This preserves the original peer composition
refusal, plugin preparation order and preparation custody.

The two product-edge modules drop 101 Python lines, and staging adds 94.
This startup and refresh slice removes seven production lines. The complete
composition candidate has 107,353 Coding Python lines: 14,149 in staging
and 93,204 at the product edge. The candidate adds 437 production lines
since the package command checkpoint and 6,638 relative to the Goal baseline.

The 81-case run on the earlier source snapshot reported 70 passes. Nine
failures matched the unchanged baseline by test and message. Six were
resource fixtures with undeclared standard project resources or inherited
ancestor context. They now use the supported workspace layout, explicit
standard loader mode and a fixture-specific context filename where necessary.
Three persisted Composition Set cases report the same
`transcript_writer:unsafe` on the baseline and remain an environmental limit.
The two candidate-only failures pointed to the original receipt read path.
Their existing assertions now follow the receipt call into its staged owner.

The corrected resource and architecture run passed 51 cases. Its remaining
assertion enforced the original private composition import boundary. Keeping
seed construction at the Coding edge preserved that boundary without an
allowlist change. That assertion and three affected refresh cases then passed
on the final source. The six repaired resource fixture scenarios also pass
on the unchanged baseline source. Ruff, focused mypy, the existing dependency
documentation check and lightweight documentation checks passed.

## Reviewed Worker History And Retirement Owners

Linux checkpoint publication, repair and tail rollback already use Harness
checkpoint commands and the Linux history program. Anchor IO and the
retirement preview likewise use the shared rooted journal and preview
owners. Coding retains the nominal history records, exact Product and
attempt checks, historical errors and proof declarations.

Windows crash lease repair and both partial and settled crash stage
retirement already execute through Harness recovery and retirement owners.
The three Coding modules supply nominal review/receipt records, native
observation bindings and established Product admission. These six reviewed
modules contribute no new staged implementation count.

The POSIX and Windows payload modules bind the existing Harness payload
custody owners for materialization, planning and launch binding. The POSIX
registered and gated recovery entries use the existing review and repair
programs. Their distinct admission rules and nominal recovery contracts stay
at the Coding edge.

## Managed Plugin Startup And Cleanup

The managed startup program now runs in
`coding.harness.session.managed_plugin_preparation`. It opens the selected
state layout, checks the supplied package storage authority before recovery,
records lockfile diagnostics, shares one startup lease and temporary root
across the selected consumers, and transfers the cleanup claims after the
existing Harness lifecycle completes recovery. The failure route preserves
the order of the diagnostic, claim releases, lease release and root cleanup.
Coding selects the managed route, declares its path and diagnostic identity,
and supplies the existing Base composition operation and its Profile
settings. The staged module temporarily borrows the bootstrap bindings that
also serve fault injection.

The Base and capability consumers share one result for the lifecycle and
materializer.
The startup extraction removes 125 lines from `composition/bootstrap.py`
and adds 163 to staging. Separately, seven fixed resource validation messages
use the original literals at their raise sites and drop the intermediate
lookups. The candidate adds 31 production lines against the prior local
checkpoint. The normalized dependency graph has the same 1,652 logical
module pairs. The additional original-module backreference is recorded.

All 22 focused bootstrap, lifecycle, catalog refresh and architecture cases
passed, including injected Base assembly and LSP preparation failures and
the original lock diagnostic assertion. Ruff and focused mypy passed. The
platform and persisted Session limits from earlier batches still apply.

## Shared First-Snapshot Acceptance

The builtin-only, disabled-only and removed-local acceptance entries use
one staged review acceptance and reopen program. The Coding entries retain
their review selection, nominal records and errors. The original Harness
receipt journal still owns native reads, lock order, publication and replay.
The shared read preserves the builtin epoch checks around a missing receipt,
the disabled-only distinction between a missing journal and an empty record
set, and the native Windows selection on the builtin path.

Three staged modules totaling 225 lines were replaced with 75 shared lines.
The Coding entry modules add 17 lines net, for 133 production lines removed.
The replacement imports existing Harness owners and standard library types.
It removes all three original-module backreferences. The 64 synchronous
baseline trace comparisons cover rejection, replay, inspection order and
platform dispatch. All 79 focused Linux cases passed, including durable
acceptance and replay, receipt replacement refusals, the original receipt
publication probe, real CLI adoption and the existing lifecycle architecture
checks. Native Windows validation remains pending.

Together with managed startup and the resource validation lookup cleanup,
the batch removes 102 production lines since the previous local checkpoint.
Coding contains 107,251 Python lines, including 14,162 in staging and
93,089 at the product edge. The Goal baseline comparison still shows 6,536
additional production lines.

## Configured Continuity Startup

The staged Continuity program opens the startup lease, reconciles existing
compatibility state, verifies the request fingerprint, replays or publishes
revisions, recovers the existing lifecycle and transfers publication custody.
The three base-only completion routes share one finish operation. The Coding
entry retains configured source admission and the Product route refusal.
Product paths, original error identity, approval policy and status reporting
remain at the Coding edge. The staged program borrows those bindings from
the original module during the intermediate phase.

The original composition module drops 252 Python lines and staging adds 270,
for a net increase of 18 production lines. Static inspection preserves the
original effect order and the normalized graph adds no module pairs.

Ruff and focused mypy passed. The first runtime and architecture run passed
49 cases. The two assertions affected by moving the startup program and one
older compatibility locator passed their targeted owner recheck. The real
Provider restart also fails on the unchanged baseline. Its wrapped exception
reports a writable ancestor in the configured test temporary path. The
Provider restart remains an open validation route.

## Current Session Selection And Composition Evidence

The ordinary Session and Resume paths retain the same Coding entry methods
for rechecking live owners and building a composition receipt. The staged
selection program rechecks the workspace witness, Worker, Desired records,
Base and capability manifests, external selections and the active deferred
capability in their original order. One exception boundary sends the
existing failure details to the Coding diagnostic and error policy.

The staged observation program builds the detached revisions, owner
generations, catalog fingerprint and Worker facts. Coding retains the
receipt version, selected composition set, fingerprint domain and
historical publication boundary. The recomposed receipt projection matches
the original AST including field ordering. All 26 synchronous comparisons
match the original check sequence, first failure, diagnostics and cause.
The staged module uses a type-only Coding import and reads the existing
Session fields during the intermediate phase.

The Coding Session module drops 241 Python lines and staging adds 274.
This slice adds 33 production lines. All 37 focused tests passed, including
the persisted receipt and single-writer cases, deferred capability
revocation, disabled-Base resources and the Resume publication barriers.
Both persisted receipt cases also pass on the unchanged baseline. Ruff,
focused mypy and dependency and documentation checks passed. The
normalized graph adds no module pairs.

## Legacy Acceptance And Adoption Reuse

The local acceptance record shares one identity calculation between
construction and validation. Accept and reopen share the current-epoch check.
The existing Harness journal owns locking, Desired State checks, publication
and replay. Product keeps the public entries, nominal record and error
classes, configured identity, source member and diagnostic label. Installation,
source consumption, classification and removal review call their existing
implementations directly. The batch removes eight private forwarding functions
and seven numbered value maps across seven owner pairs.

Relative to `9f336e480`, the batch removes 142 Python lines at the Coding
edge and 21 in staging, for 163 fewer production lines. The local acceptance
pair drops from 628 to 529 lines. All 86 Legacy runtime cases pass. Five public
entries, three wire and pickle cases, and 23 rejection traces match the
preceding Legacy source. All 13 current architecture cases pass after recording
the retired forwarding entry in the location inventory. Ruff, mypy,
documentation and the normalized dependency check pass.

## Continuity History And Selection Authority

The same read path now handles bounded history preview, tail fallback and
identity checks. Resume and delete share the listed-reference and source
revision checks. The provider retains rendering, Resume planning admission,
and the compatibility and active-session checks before deletion. Native reads
keep the original cancellation custody. The existing Harness owner still
handles owner receipt publication and retirement ordering.

The provider drops 101 Python lines and staging adds 130. The slice adds
29 production lines. The 55 focused Continuity, preview and planning tests,
Ruff, mypy and the normalized dependency comparison passed. Reader lookup,
nominal history types and native runtime dependencies remain recorded for
later extraction.

The Runtime Binding, v1 activation and v2 activation projections now share
one parent-link and duplicate-record check and the same length-prefixed
ancestry digest. Each projection retains its historical namespace, codec,
failure order and version rules. The v2 iterator still yields after each
validated record. This part adds 12 Python lines, so the complete Session
history batch adds 41. A further 208-case run verifies Binding, versions,
activation, bounded previews, Continuity, Resume planning, continuation and
the Windows launch intent regression. All 135 projection outcomes and
errors compare equal with the preceding implementation. The ancestry owner
has no dependency on Coding implementation modules.

## Windows Worker Entry Admission

Twenty Windows Worker entry modules use a shared exact owner check at 22
sites. Complete, partial and reserved stage review, plus launch-intent lookup,
use one attempt ID validator. The callers retain the expected Product
identity, platform observation, public error wording and types. The existing
Harness owners still control locking, pinned read scopes, writes and
retirement. Explicit owner types preserve five original fault-injection sites.
All 20 caller modules match their prior ASTs after expanding the shared checks.

This part removes 50 Python lines at the product edge and adds 30 in staging.
The Linux run passes 638 cases, skips two native or host-runtime cases and
reports 107 failures in two historical probe suites. The same 107 cases fail
with the same normalized assertion details on the unchanged baseline.
Native Windows routes remain pending. Ruff, mypy and the normalized import
graph check pass. The staged module depends only on the existing Harness
Windows Product owner and the standard library.

The four complete, partial, unlaunched and crash retirement entries all bind
the existing Harness retirement transactions and Windows retirement record
reader. Coding retains each route's Product admission, receipt and review
types, historical diagnostics and links to the original native/recovery
observers. Existing retirement implementations contribute no migration credit.

## Resume Writer Acquisition And Input Lookup

The selected-history projection now provides validated input record matches
while verifying the parent chain and the exact v1 or v2 binding. Input lookup
uses one history walk. It no longer redecodes the whole path or searches it
again for each v2 intent. An unknown or invalid suffix still invalidates an
earlier match. The Session manager retains pending-input selection, exact
record digest and conflict checks, and delegates the durable lookup to the
original Transcript authority.

Writer acquisition now coordinates the bounded source read, current Plan
comparison, original Transcript factory acquisition and in-factory
publication fence. It checks all acquired records and restores the verified
selected branch before returning the Session. The Coding entry retains its
required-capability gate and historical header policy. Source changes after
the initial read still reject and release the original owned preparation.

The batch removes 131 Python lines at the Coding edge and adds 146 in
staging, for 15 additional production lines. The lookup and Hosted run has
193 passes and one skip. The subsequent Writer and lookup run passes all 87
selected cases. All 136 comparative lookup outcomes and durable read calls
match the baseline. Writer validation and restore projection match the
original body after resolving the local diagnostic label. Ruff, focused
mypy, docs and the normalized dependency graph checks pass.

## Resource Catalog Product Evidence

Initial Session construction and Catalog refresh use one retained evidence
check for capability Desired State and a disabled Base. Refresh also compares
external membership and revalidates selected Base, capability and resource
manifests in the original order. The shared check calls the original Package
Product authority and the existing external-data and manifest proofs. The
startup path preserves its original exceptions and does not perform the
refresh-only membership checks.

Both external resource capture paths and the capability manifest handoff
use the same ordered reader and Product-selected limits. The Coding edge
still selects plugins, composition and sources, and binds each Catalog's
product-specific policy. The temporary type references to the two Product
compilations are recorded. The Catalog authority guard and manifest batch
reader add 118 Python lines in staging and remove 87 at the Coding edge,
for a net increase of 31 production lines.

All 59 Catalog, external-data and architecture cases passed on the first
candidate. All nine targeted cases passed with the final Product budget
binding. An exact comparison covers 2,112 original startup and refresh
observation and failure traces, plus nine ordered manifest-read cases.
Ruff, mypy, documentation and the normalized dependency checks pass.

## Fenced Package Product Catalog Preparation

The staged Package Catalog module now owns the ordered startup preparation
that supplies the retained evidence used by Session construction and refresh.
Base-enabled startup captures the Base manifest, compiles its Profile inputs
and requires the loader receipt before observing requested capabilities.
Base-disabled startup observes external resource membership and prepares
enabled capabilities before requiring the receipt. Both routes reuse the
existing Package Product runtime, plugin preparation and root-custody
owners. The enabled route keeps cleanup notes on the original failure and
the disabled route retains its original sequential cleanup behavior.

Coding chooses Base availability, capability IDs and configuration, Profile
contributions, private paths and the Catalog source policy. Managed and
fenced preparation reuse the same local root and LSP/Arch configuration
assembly while supplying their original prefixes and persistent Arch paths.
The Catalog evidence checker moved into the preparation module unchanged.

The batch removes 115 Python lines at the Coding edge and adds 164 in
staging, for a net increase of 49 production lines. There is one reviewed
typing-only dependency on the original Capability configuration union. The
target has no path back to the startup caller. All 76 Catalog, Resume and
architecture cases pass on the staged preparation. All nine targeted cases
pass after the root/configuration reuse. The final source matches 1,430
startup and fault-injection traces and 164 managed configuration traces,
including failure precedence and cleanup. Ruff, mypy and documentation
checks pass.

## Initial And Refreshed Catalog Composition

The same Package Catalog owner now prepares the initial ordinary composition
and its refresh. Both use the existing Base assembly and Harness custom
composition owner. Initial startup still finishes an admitted plugin plan,
while refresh uses the resource-only plan or the retained fenced composition.
Each keeps its original missing-plan behavior and effect order. Coding still
chooses the Product policy, reconciles historical source configuration, and
projects the prepared Catalog onto the Session adapter.

This batch removes 70 lines at the Coding edge and adds 119 in staging, for
a production increase of 49 lines. The staged owner temporarily borrows the
original Base plans and the explicit Product Catalog input. All 60 affected
Catalog, Hosted Session, plugin lifecycle and architecture cases pass. The
two existing Hosted timing probes now instrument the moved compiler at its
actual call site. An exact comparison matches 2,848 initial and refresh
composition traces, including failure precedence and root custody.

## Shared Private-Data Verification And Preview

The POSIX read-only owner and the writable backup owner now call the same
retained archive verifier. The original Harness reader and tree checker still
own the actual I/O. The read-only caller retains its non-repairing quiescence
and computes the backup path under that lock. The writable caller still
computes its path before acquiring the original quiescence guard.

Read-only verification, normal restore verification and expiry previews use
the same confirmation journal lookup and exact evidence match. The callers
keep the original snapshot authority, lock scope and failure diagnostics.
Backup writers on both platforms call the existing receipt factory directly.
Five private Product forwarding functions are removed. The issued receipts,
plan records and their public import paths retain the same nominal classes.
The read owner imports its two plan types from their declaring modules.
The two added logical edges have no return path to the read owner.

This batch removes 119 Product lines and adds 22 staging lines across 13
modules, removing 97 production lines overall. All 31 affected tests pass,
including the CLI and SDK paths through backup, restore, confirmation and
expiry. All 52 existing record, journal, POSIX restore and expiry compatibility
cases pass. Comparison against the prior checkpoint matches 88 archive and
420 confirmation traces, including read failures and cleanup. The four
affected record classes retain their historical imports and pickle identity.
Native Windows validation remains pending.

## Reviewed Legacy Plugin Choices And Replay

Builtin-only, removed-local and active-local adoption now share one staged
removal replay. The shared implementation constructs the workspace installation
key and calls the original Harness Package Product writer for each reviewed
removal. Coding keeps the original historical operation IDs and policy. The
removed-local route retains its sorted order and performs its removals before
projecting disabled choices. The other routes retain the review tuple order
and project disabled choices before their first removal. The read-only
adoption observation reuses the projection under its existing read authority.

The three writers call the existing Harness bootstrap owner directly. The
retired Product functions include three tombstone adapters and the workspace
key adapter shared by two Product modules. They remove 93 Product lines. The
shared code and its consumers add 66 staging lines, yielding 27 fewer Python
lines in production. The dependency check resolves four staged consumers and
three nominal review typing imports. It verifies all new edges are acyclic
and records the removed Product-to-Product key dependency.

The three CLI interruption probes now intercept the real tombstone call at
the shared replay owner. All 49 CLI and Legacy inventory cases pass, including
three adoption routes, acceptance checkpoints and replay after the first
tombstone. The five public entry bodies remain identical to the prior
checkpoint. All 13 lifecycle architecture checks pass with the single
disabled-choice reader recorded in the existing location inventory.
The comparison against the prior checkpoint matches 810 traces across all
three writers, including historical IDs, strictness modes, partial failures
and cleanup. Native Windows replay remains unverified.

## Authorized Workspace And Prepared Plugin Binding

The staged workspace startup owner now intersects the injected and delegated
execution ceilings and binds the sandbox, process launcher and workspace
provider to one authority. The existing sandbox and operation adapters still
enforce the underlying native and workspace policies. Coding supplies its
writable-workspace choice, provider identity and fingerprint namespace,
diagnostics and the Session audit sink. The workspace provider's historical
fingerprint encoding and startup guard before the audit sink has a Session
remain the same.

The same workspace binding now mounts the admitted combined builtin, separate
capability, Base plugin and Base Product preparations through their existing
owners. Combined builtin preparation retains precedence. Both the failure
handoff and the distinction between the Product's LSP and Arch modes remain
at the original boundaries. Coding retains the worker selection, tool
conflict checks and deferred LSP configuration.

This checkpoint removes 110 Product lines and adds 217 staging lines. The
107-line production increase includes the typed boundary and original policy
inputs. The mechanism bodies have one implementation each. The staged owner
borrows the same Product sandbox and file-operation adapters and references
existing plugin types for checking. The logical dependency graph keeps the
same 1,661 module pairs. An exact comparison against the preceding local
checkpoint matches 936 workspace authority and provider traces and 80 plugin
binding traces, including injected failures and provider fingerprints. All 24
composition authority and Catalog architecture checks pass, including the
original one-workspace-provider assertion at the current owner.

The full 126-case Linux run passes 117 cases, including sandbox and workspace
operation checks, both Hosted Session cases and all three plugin lifecycle
cases. The nine startup failures also fail at the same assertions on both
unchanged `c7972f93d` and unchanged `df0dca779`. They cover legacy extension
flags, tool interception and discovery, local skill and prompt discovery,
and the ancestor `AGENTS.md` included in an exact prompt expectation. The
comparison uses the same managed runtime and retains the failures in the
reported result. Native Windows startup was not exercised.

## Deferred Plugin Preparation And Binding

The managed plugin preparation owner now supplies the original materializer,
lifecycle and Session owner to both eager and deferred preparation. The same
staged module opens the deferred state directory, builds the chosen configuration,
captures fenced Desired selection and its manifest, binds the workspace and
hands the recheck to the published generation. Fenced activation still requires
an enabled selection. If preparation or binding fails, the original sequential
preparation and temporary-root cleanup retains its failure precedence.

Coding supplies LSP discovery, the selected plugin and tool mode, persistent
and temporary path policy, the admission error and the existing generation
factory. The generation still starts preparation off the event loop and
retains the original cancellation-aware join. The staged module keeps the
existing Product preparation imports as fault-injection seams.

This batch removes 73 Product lines and adds 132 staging lines, for a net
increase of 59 Python lines. The typed preparation interface and the bound
Product inputs account for the extra declarations. The existing Harness
owners continue to hold the runtime and plugin lifecycle. The normalized
dependency graph retains the same 1,661 module pairs. The comparison against
the preceding checkpoint matches 480 selection, workspace binding and
cleanup traces, including faults in directory allocation, evidence capture,
revalidation and resource release. All 17 Linux runtime cases pass, including
managed and fenced activation, revoked selection, retirement retry, dormant
resume, eager startup, shared LSP and Arch composition and interactive input
during preparation. The existing neutral-composer architecture check passes.
Native Windows activation was not exercised.

## Prepared Session Selection Admission

The staged Session selection owner now admits the prepared graph and its
package evidence before Session construction. It uses the original Harness
Worker composition validator, confirms the shared Base and capability graph
objects, and verifies the original workspace, Session scope and Product
runtime binding. Coding retains nominal assembly checks, historical LSP
aliasing, the Worker Tool request and its workspace witness.

Full Base composition still compares package name order. Capability-only
Product composition still compares counts and includes an explicitly empty
selection. Both routes use one package digest reconciliation. Construction
and later composition observation now share the same Base, Capability and
external-data manifest projection. The staged function borrows the original
Product types and the existing conditional Worker validator import.

This batch removes 92 Product lines and adds 112 staging lines, for a net
increase of 20 production lines. The normalized internal graph retains the
same 1,661 pairs. A baseline comparison matches all 35,840 prepared selection
traces across 12 distinct outcomes, including Worker graph failures and the
original rejection precedence. All 59 focused Linux regression cases pass,
covering ordinary construction, Worker composition contracts, mixed Base and
Capability publication, resume and external-data admission.

The additional live-epoch POSIX Session test fails at the same workspace
skill refresh assertion on this batch, `e6ed71b6e` and `df0dca779`.
All three runs discover only the selected standard skill and fail to find
the fixture's workspace review skill. The comparison leaves that test and
its later assertions intact. Native Worker and Windows execution were not
exercised in this batch.

## Session Owner Registration And Construction Rollback

The staged Session binding owner prepares the original command registry and
owner generation bindings. It preserves the empty registry for a
Catalog-owned Session with Base disabled. The binding order is Base Tool,
Base commands, LSP, then Arch. Once the Session controller exists, its tool
registration slots still connect in LSP, Arch, Base order. Their nominal
Product types and diagnostic labels remain intact.

Construction failure releases the original Worker Tool, capability assembly,
Base plugin evidence, locally acquired side-question binding and locally
acquired capability runtime in that order. The existing Harness cleanup
runner preserves the primary error and records failures of later steps.
The existing Harness publication and retirement authorities still own
receipt and graph state.

Coding selects the nominal owners, command policy, tool options and Worker
query registration. The staging module temporarily borrows the original
Product assemblies and slot classes. It reuses the Harness command registry,
deferred slot interface and cleanup runner. The change removes 138 Product
lines and adds 180 staging lines, for a net increase of 42 production lines.
The comparison against the preceding checkpoint matches 16,320 registration
and late-binding traces and 972 rollback and cleanup-error traces.

The Linux regression run passed 35 Session construction, publication,
lifecycle and command cases. Two failure routes passed again after final
rollback edits, and 17 architecture checks passed. The normalized Coding
module-pair count remains 1,661, and the runtime import scan found no path
from the new binding module back to itself. Native Windows and Worker
execution remain unverified in this batch.

## Shared First-Input Intent And Effect Settlement

Embedded and Hosted Resume now use the same intent construction and effect
settlement before the existing continuation and Writer boundary. The shared
path keeps the exact v2 intent fields and rejects unsupported attempt types
before checking current subject admission or receipt evidence. When Plugin
effects are present, it prepares the approved directory at settlement and
uses the existing execution and activation Journals. The no-Plugin branch
validates the receipt without preparing a directory. Embedded's allowance
for its Worker owner and its Plugin settlement injection point remain
intact.

The callers retain source and subject custody, Product epoch and Plugin
selection, ID policy, and the existing continuation handoff. Hosted retains
the stable submission-derived input ID. Embedded retains the order of its
generated IDs and native approval checks. Bootstrap and both Resume entries
share the historical Session Plugin state path calculation at the Product
edge. The new staged path adds one typing-only plan dependency and no
runtime import cycle within Coding.

The Product edge removes 58 Python lines and staging adds 107, for a net
increase of 49 lines. One new typed binding preserves the original effect
checks and their call shape across both routes. Compared with the previous
checkpoint, 144 intent and settlement traces match, as do eight historical
path calculations. The Linux regression run passed 115 cases and the
Hosted architecture run passed 32. All 39 selected Embedded and Hosted
cases passed on the final settlement path. Native Windows and Worker
execution remain unverified in this batch.

## Shared Legacy Removal History Proof

Removal admission before the first fence and authenticated review after the
fence both use the existing settled-management-history owner. That owner now
checks operations, retirement records and retired Instance evidence for four
paths, including the existing installation inventory and local-data
admission. Both removal paths also share their lock checks and Installation
evidence reads. Each continues to use its original snapshot authority and
checks the same members with the original byte budget and error order.

The pre-fence check retains the current cutover owner's default operation
read limit. The post-fence review retains its second-stage owner, explicitly
bounds the read and captures the operations digest before checking Instance
evidence. The Product entry retains the historical record types, the
installed/removed decision and the admissible disable set. The shared proof
grants no repair access. Its normalized module graph remains at 1,662 pairs,
and the added staged edge to the shared proof has no return path.

This batch deletes four duplicate journal names in the Product layer and
cuts 42 lines from staging, for 46 fewer production lines. The three proof
routes match the preceding snapshot code across 864 comparisons covering
read kwargs and ordering, missing evidence, rejected locks, parser failures,
digest timing and the effective error chain. All 29 final Linux regression
cases passed across removed and active local-data histories, including actual
management journals and retired Instance records. The existing lifecycle
architecture location check and the broader 185-case regression passed.
Native Windows was not exercised.

## Session Composition Receipt And Model History

The staged Session receipt codec reads the original header identity and
startup record, including exact version, selected Plugin revisions, Worker
evidence and owner generation ordering. The current-plan route invokes the
existing Product registry at the original validation point. Historical
reads avoid that registry and return detached data. The Coding entries retain
the public nominal provenance record, header key, extension type, and
current-plan policy. The same identity format supports Session forks and
startup output. Session readiness, built-in Session information and Resume
preview reuse the same receipt/header identity comparison.

The existing staged selection owner now coordinates publication over the
original Session lock and Transcript writer. It checks historical evidence
before observing current selections, and marks readiness only after the
original rejection or append points. The Product supplies its existing
header key, extension type and diagnostic label. The receipt codec and the
new read-only Model History helper have no imports from other Coding
components. The Model History helper delegates invocation projection to
Harness Transcript, keeps conflicts and missing evidence distinct, and
reports the initial main invocation. Coding retains the original v1
input binding checks and nominal outcome shape.

The Product layer removes 180 physical Python lines and staging grows by
335, for a net increase of 155. The retained Product boundary, expanded
validator formatting and explicit typed inputs account for the cost. The
base comparison matches 256 header, 8,192 receipt, 864 publication and
8,865 Model History traces, including chained errors and the order of
publication. The focused Linux run passed 21 cases. All four final
publication rechecks and both architecture checks passed. The 85-case
regression passed 82 cases. Three Session and CLI cases hit
`transcript_writer:unsafe` at the same Harness lease check on this batch and
on the prior checkpoint. Native Windows
and Worker execution were not exercised.

## Catalog Adapter Admission And Refresh

One staged adapter binds current loader receipts for Session startup,
package previews, local Plugin discovery and refresh. It checks scope,
time, supply routes and exact Resource admissions in the original order.
It then uses the existing Harness loader selection, adapter and bootstrap.
Coding retains its canonical source policies, Product ID and diagnostics,
and the original compiler that selects and assembles Product Plugins.
The adapter's only back-reference to Coding is the source policy annotation.

The staged Package Product catalog owner now rechecks authority, captures
the next receipt, reuses the existing composition selection and supplies
the same adapter to the original Session bootstrap generation. Fenced
startup and refresh share snapshot input projection, including the explicit
empty snapshot for a disabled Base with a composition. The existing
projection hook still receives the same clock and policy. The Harness
refresh transaction remains the owner of publication, rollback and cleanup.

This batch removes 119 Product lines and adds 232 staging lines, for a net
increase of 113 production Python lines. The introduced function boundaries
carry the original typed inputs, Product compiler and projection callback.
The normalized graph remains at 1,662 pairs. Comparisons against the
preceding checkpoint match 113,400 adapter and 384 refresh traces, including
validation order, snapshot selection, clocks, failure and bootstrap calls.
The Linux run passed 42 cases. The legacy direct-Session watcher case
failed at the same system-prompt assertion on the prior checkpoint.
Six final adapter and refresh cases and both architecture checks passed.
Native Windows and Worker execution were not exercised.

## Shared Legacy Local Source Evidence

First-fence data admission, frozen adoption admission and removed-installation
review now index the exact configured local Sources once per snapshot. The
same parser backs the original single-source API. Before live bytes are
opened, the pre-fence route verifies the full installed set. Each Wheel
is still captured and inspected in the original order. Pre-fence and
review reuse the existing Resources capture with their original disposable
directory prefixes and cleanup. Reopening acceptance shares the original
review's authenticated Source observation, with its own missing-evidence
error and no live Source access.

The Product review, acceptance and builtin removal ID retain one unchanged
allowlist. Removed Product aliases had no remaining callers. Ten stale
journal names were removed from the earlier settled-history duplication.
This batch removes 38 Product lines and adds 30 staging lines, for eight
fewer production Python lines. The normalized graph drops three direct
Product dependencies to 1,659 module pairs. Four new staged uses have no
runtime return path. The existing disabled-plugin source constraint follows
the implementation's moved scope and retains the same two tracked uses.

The comparison matches 4,806 single-source, 445 whole-set, 56 frozen
snapshot and eight Wheel cleanup traces. For 16 installed sources, a full
set proof now calls the source classifier once, down from 16 calls. All 29
focused Linux cases and three final cutover rechecks passed. The architecture
run passed 12 cases, and the moved location constraint passed its final
recheck. Native Windows routes were not exercised.

## Installation Private Root And Offline Previews

Session private-root preparation now uses the staged Installation owner.
It checks the exact Desired selection, then captures and verifies the
selected manifest before creating any directory. The Windows route reuses
the existing generation binding and ACL owner, rechecks identity after
preparing the child, then recaptures the authoritative manifest. The POSIX
route uses the original private-tree preparation. Coding retains the
historical Installation and Session path hashes, plugin identity, and
nominal generation and receipt declarations. The three Windows inspection
and restore entries reuse one Product state-root check. Inspection still
uses the existing read-only lineage entry.

POSIX restore and expiry previews now use the staged read owner for
generation and archive proof. They take the existing epoch, runtime and GC
read scopes, preserve failure order and use the original Desired snapshot.
Backup, deletion and restore publication authorities stay with their
existing owners. The error text, path rule and compatibility hooks remain
at the Product edge. The root staging import borrows that Product seam at
runtime. Its physical module cycle is recorded, with the normalized graph
unchanged at 1,659 pairs.

The Product edge removes 83 lines and staging adds 153, for a net increase
of 70 physical Python lines. The previous checkpoint matches 5,832 root
admission, 42 Windows lineage entry and 60 preview traces. The existing
Linux-based Windows compatibility probe has the same 17 passes and 69
historical trace-digest failures as the previous checkpoint. All 86
normalized observations match. The Linux runtime run passes all 18 cases,
including actual Session cache creation, read-only preview, cleanup and
deletion replay. Native Windows remains unverified.

## First Package Cutover Preparation And Reopen

The staged Package Product snapshot scope now owns private-root preparation,
fresh-input checks around root creation, projection lifetime through the
first fence, and native reopen dispatch. One preparation program orders
state roots before data roots, with the Windows projection parent prepared
in its existing position. Native private-directory and fence owners still
perform validation, writes, snapshot publication and reopen. Backup status
continues to pass through the read-only reopen flag. Coding retains the
deployed root geometry, the Windows fresh-only admission decision, and
the original public types and function bindings.

Session startup and the offline cutover now share the staged historical
state probe for fresh inputs. It reads lifecycle before Package state and
skips a root only for an allowed missing-path result. The offline CLI uses
one Product namespace derivation and one existing-fence identity check.
The disabled-only review shares the first-fence entry with other reviews
and runs its original preflight before a new fence. Existing fences reopen
without that preflight or a new snapshot admission.

The Product edge removes 98 lines and existing staging modules add 105
for a net increase of seven physical Python lines. No new module or
normalized dependency pair is introduced. Both existing staged modules
still borrow their Product binding for historical paths, settings checks,
types and test seams. Controlled comparison against the previous checkpoint
matches 24 root ordering and failure, 576 preparation and custody, 24
native dispatch, 300 read-only state and 120 CLI review observations.
Historical import aliases and nominal export identity also pass. The
non-live Linux snapshot, offline CLI, plugin lifecycle and architecture
run passes all 216 cases. Native Windows execution remains unverified.

## Session Tool And Command Registration Generations

The staged Session registration program prepares workspace Tool and
standard Command packs, binds the Graph lifecycle, and retires the
generation. Workspace facets still pass through the existing Harness
process backend and revocable operation set. The Graph retains admission
and publication authority. The existing Tool registration port, Command
registry, and RegistrationScope still implement lease staging, publication,
rollback and disposal. The Tool stage invalidates
its captured operations before withdrawing registrations on failure.
The retirement receipt still comes from the same live scope.

Coding retains the exact selected catalog and identities, admitted workspace
requirement, Product messages, and original nominal owner and generation
types. Historical imports, fields, slots, and the original generation's
commit fault seam remain in the Product module. The staged program
temporarily borrows those Product bindings through a recorded import cycle.

This batch removes 177 physical Python lines at the Product edge and adds
225 in staging, for a net increase of 48. The increase keeps the original
method entry points while introducing typed staging entry points. The
existing source-location assertion points to the sole new Command staging
and catalog site with no test line increase. Logical dependency
normalization retains 1,659 pairs.

All 16 focused Linux tests pass, including real Session publication, CLI
settings, failures during Tool and Command staging, and a failure during
the second owner commit. Controlled comparisons match 1,008 staging
observations, and seven historical nominal contracts match. Windows
environment selection and capture are exercised in Linux tests. Native
Windows execution remains unverified.

## Registration Authority For Compiled And Selected Plugins

Base Tool and Command owners and selected capability Tool owners now bind
their current authority readers in one staged Session module. It resolves
an exact owner and reads its live snapshot, requires one exact Plugin
source trust snapshot, and uses the existing Harness registration gate for
admission, stale evidence rejection and the single-use start witness.

The compiled route still verifies the ordered owner snapshot inventory
before constructing the gate and reads trust and policy from its compiled
context. The selected route still checks the single owner's live policy,
pins the selected plan trust snapshots and reads the plan policy revision
when the gate is checked. Coding supplies the exact contribution choices,
Product and scope, and diagnostics.

This batch removes 71 Python lines from the Product edge and adds 138 in
staging, for a net increase of 67. The staged module has typed entry points
for both evidence sources and no Coding imports or intermediate Product
dependency. The normalized Coding graph remains at 1,659 pairs.

Controlled comparisons match 180 compiled and 180 selected observations
covering invalid scope, missing or ambiguous trust, live owner changes and
policy revision changes. All 37 focused non-live tests pass, including the
actual Base, LSP and Arch owner paths and Harness revalidation after an
asynchronous stage. The final LSP and Arch paths pass both rechecks.
Native Windows execution remains unverified.

## Preview And Membership Forwarding Cleanup

Read-only Plugin preview and local discovery now call their staged settings
and inert artifact readers directly. One staged workspace check and fence
guard serve the three preview entries. The entries retain their original
check order, error code and cause, settings revision hash, read-only
Package owner and bounded regular-file checks. The historical preview
import and the two externally exercised settings helpers remain available.

The existing Harness Session membership policy invokes the staged holder
codec via deferred callbacks. Direct module initialization exposed an
import-order cycle, and the callbacks preserve the original late lookup.
The staged decoder reuses its own owner-contribution validation. The
historical holder prefix, canonical JSON, error identity and fail-closed
treatment of unknown versions stay exact.

The Product edge removes 80 physical Python lines, and staging removes
eight more. The reduction comes from six retired private forwarders,
repeated guards and indirect constant lookups. No production module is
introduced. The dependency graph remains at 1,659 normalized pairs.
Sixteen program bodies match after resolving the former wrappers and
expanding shared guards. Seventy-two holder input cases match, including
malformed and unknown-version evidence.

An existing Catalog architecture assertion reproduces on the unchanged
preceding commit. The inventory now records the exact existing private
Catalog symbols already used by four staged Session modules. Imports of
other private Catalog symbols at those four paths still fail the inventory.
Test source gains 13 lines.

The preview and discovery runtime run passes 56 cases and skips five
platform cases. All 12 final Catalog architecture cases and all 69 lifecycle
and lifecycle architecture cases pass. A concurrent focused run reports
three subprocess handshake timeouts. All three cases pass in isolation
against the final code with their original time limits. Native Windows
execution remains unverified.

## Legacy Lock Markers And Local Adoption Eligibility

One staged management evidence reader now checks old journal lock markers
for builtin review, removed-local review, active-local admission, and
ordinary first-fence inventory. Each route still supplies the original
snapshot read authority, marker set, read order, byte bound and error.
Builtin and settled-history proof share the four service lock names.
Settled history still requires the additional runtime markers when its
journal is present. No route acquires a repair or write capability.

The pre-fence and fenced local admission paths now share the installation
count, requested Plugin and removal eligibility checks before matching
configured Sources. Live resource reacquisition and first-fence observation
retain their original execution points. The Product declaration shares one
set of supported resource types and their historical refusal codes.

The Product edge removes 19 lines and staging adds one, for a net reduction
of 18 physical Python lines. Normalized dependencies remain at 1,659 pairs.
All 42 focused non-live Linux cases pass, covering old management journal
shapes, configured sources, removal replay and the existing architecture
constraints. Controlled comparisons match 1,008 settled-history and removal
traces and 360 local eligibility observations. Native Windows execution
remains unverified.

## Extension Runtime Profiles And Declaration Refresh

The staged Session owner now converts Extension declaration snapshots into
named layers and executable Provider factory descriptors, and checks pure
declaration changes before refresh. Existing Harness admission, Profile
resolution, resource projection and side-question binding retain their
authority. Startup and refresh use the same declaration translation.
The declared implementation key and the executable descriptor now use
one formatter. Resource and Session restart evidence use one projection
with the original capability grouping, order and fingerprint kinds.

Coding retains the exact permitted Extension slot and permission, default
Profile, Product diagnostics and the public preflight and resolution
types. The staged module has no Coding imports. The edge removes 239 Python
lines and staging adds 270, for a net increase of 31. The independent
typed interface and the original Product entrypoints account for the
adapter cost. Normalized dependencies remain at 1,659 pairs.

All 53 focused non-live Linux cases pass, including live Session reload
logic under controlled test owners, factory disposal and the existing
authority constraints. Baseline comparisons match 239 declaration, 717
refresh and 48 factory observations, including errors, restart evidence
and effect order. The five public exports and historical import location
remain compatible. Native Windows execution remains unverified.

## Resume Record Construction And History Proof

The staged Session record owner now constructs both generations of
activation intent and user input records through the existing Transcript
factory. Both generations share the intent field comparison. The original
Coding entrypoints retain the record kinds, metadata keys, encoding
domains, exact nominal types and version admission rules. Input and
persisted payload digests share one implementation with their original
domains and image handling. Transcript remains the owner of durable commit.

The legacy Binding projection and the unified history reader both validate
the decoded Binding from the same immutable record. Before using it to
close an intent or publish historical evidence, the original validation
checks still cover record identity, parent, exact intent and stored user
payload as applicable to each version. Unsupported schemas remain inert.
Each known Binding is decoded once per projection. The staged record
owner has two type-only Coding dependencies for historical DTOs. The
unified history reader still borrows the original wire authorities.

The Product edge removes 7 Python lines and staging adds 98, for a net
increase of 91. The shared factory, typed interfaces and retained public
validation entrypoints account for the added source. All 154 focused
non-live Linux cases pass. A comparison against the preceding local
commit matches 58 projection results and errors. The legacy reader and
both unified reader versions each go from two decodes to one for a known
Binding. Normalized dependencies remain at 1,659 pairs, with the two
physical type-only imports recorded separately. Native Windows execution
remains unverified.

## Fenced Management Operation Custody

The staged Package Product management scope now owns open, success
revalidation and release for six operations. Snapshot, operation lookup,
package and Plugin explanations and handoff reads use the existing read-only
owner path. Desired command submission uses the existing writable path.
Operations still run at their original workspace guard checkpoints, and
every acquired runtime closes after success or failure. The exact Desired
transition reader retains its distinct order between epoch proof and
ambiguity rejection.

The CLI read and command strategies share one implementation for binding
fenced ports to an already captured workspace identity. Legacy startup,
compatibility publication and the read-only fallback remain in their
separate original paths. POSIX Package repair reuses the existing Harness
directory identity check both before opening the owner and after
acquisition, with the same Product error and filesystem cause.
Windows private-data backup keeps its native exception behavior. The CLI
Desired repair retains the caller's pre/post guard and its distinct
ordering between identity comparison and canonical path resolution.

The Product edge removes 48 lines and staging adds 29, for a net
decrease of 19 production Python lines. No new Coding import edge is
introduced. Comparisons with the previous checkpoint match 96 owner
lifetime traces, 12 Package repair identity traces and 88 CLI binding
outcomes, including failure order, error causes and release. The final
non-live Linux regression reports 107 passing cases and five Windows
skips, covering repaired or rejected owner acquisition, private-data
replay, management commands, and architecture constraints. Native Windows
execution remains unverified.

## Initial Catalog Preparation And Session Handoff

The existing staged Package Catalog module now owns the initial projection
handoff for both startup paths. Legacy startup resolves the receipt and
prepares its composition before the Product compatibility operation and
projection. Fenced startup projects the already admitted Base, capability
or disabled selection, then hands off the authority, builtin preparation
and adapter together. Both paths keep the original duplicate-preparation
and single-adapter intake checks. A failed fenced projection leaves the
previous authority and adapter in place. Legacy sets its preparation
before compatibility reconciliation, at the same point as before.

The selected adapter still mints and transfers its Resource bootstrap
through the existing Harness Session constructor. Failure releases the
unpublished Capability assembly with the original error and cleanup notes.
The caller's diagnostics and fenced runtime release retain their original
order. Coding supplies compatibility reconciliation, selected plugin and
source policies, diagnostic labels and the original projection hook. The
historical bootstrap import still resolves to the same preparation type.

The Product edge removes 89 Python lines and staging adds 154, for a net
increase of 65. The staged state and typed boundary account for the cost.
The normalized graph stays at 1,659 module pairs. The existing Product
references remain explicit, including the assembly type used for failure
cleanup. Against the prior checkpoint, 137 comparisons match preparation
order, admission diagnostics, projection state, adapter intake, error
identity and cleanup outcomes. All 52 focused non-live Linux cases pass,
including Hosted and Resume construction and the existing architecture
constraints. Native Windows startup remains unverified.

## Delegated Child Session Construction

The staged Session builder validates the requested Tool subset, projects the
platform Tool names, and checks the selected exact owners before constructing
the child. It keeps the plan, role and parent model precedence, and uses the
existing registry projection and delegated execution profile. The same
actor-bound approval and leased workspace reach the original runtime builder.
The original Harness factory still owns the child, its history, its lease and
its failure and disposal paths.

Coding supplies roles, prompts, workspace policy, platform names and exact
Tool identities. The public factory and legacy import retain their identity
and signature. Recipe context now calls the original Product prompt function
directly. The staged builder has no Coding imports and receives Product
policy through the bounded assembly inputs.

The Product edge removes 121 Python lines and staging adds 126, for a net
increase of five. Normalized dependency pairs remain at 1,659. All 67 focused
non-live Linux cases pass, and the recipe recheck passes. A comparison matches
251 construction and refusal traces. The extra Repository Goal integration
case reaches the same `transcript_writer:unsafe` rejection on the previous
checkpoint and current sources, before the root Session can create a child.
Windows Tool projection is covered by host fixtures. Native Windows
execution remains unverified.

## Guarded Workspace Selection And Owner Replacement

Ordinary Session factory acquisition and Resume activation now use the same
staged selection scope directly. Both preserve workspace admission before
selection and keep the same lock through acquisition. Only Resume invokes
the current owner check and projects the fenced epoch. A cached current
owner returns without reopening. First acquisition and stale-owner
replacement share one open path. Replacement retains the old owner only
after the new owner opens, and keeps it for the original cleanup route.

Legacy and fenced Resume observations share canonical encoding and a size
check. They keep their distinct evidence fields, the legacy fence-absence
proof and the second live observation of a fenced owner. The bytes and
wire identities are preserved. The existing startup recovery program now
has a direct staged caller. The public Base and builtin runtime-owner
entrypoints call the same staged opener with their original options.

The 15 prior forwarders were reviewed for live callers, faults and nominal
contracts. Three internal forwards are gone, along with the redundant
selection context adapter. Public Product operations, legacy import paths,
the catalog freshness seam and the timed fresh startup hook are retained.
The Product edge removes 76 lines and staging adds 18, for a net reduction
of 58 production Python lines. The normalized dependency graph stays at
1,659 pairs. All 650 comparisons against the previous checkpoint match,
including admission order, cached-owner retention, legacy and fenced
fingerprints and public opener arguments. The non-live Linux route reports
35 passing cases and one native Windows skip. Native Windows execution
remains unverified.

## Resume Plan Owner Input Reuse

Plan construction and live owner-input comparison now share the same nominal
type, order and uniqueness checks. Construction keeps its separate reference
budget; live comparison still rejects changed observations after checking
their shape. Background setup and async planning use the same Product
declaration for subject and policy references.

Both planning paths call the staged compiler directly. Unavailable history
still skips Resource work, and compilation still compares the history after
preview. The public builders, stale error and stored Plan identities keep
their existing contracts. The current Writer remains responsible for actual
admission, and each caller keeps its original order of source and input checks.

The Product edge adds seven Python lines for its shared owner declaration.
Staging removes seven lines, leaving the total unchanged. All 59 focused
non-live Linux cases pass, including background cancellation, cache
revalidation, Writer acquisition and Hosted Resume. Across 978 controlled
comparisons, the Plan results, error precedence and synchronous Resource
call order match the prior checkpoint. Normalized dependencies remain at
1,659 pairs. Native Windows execution remains unverified.

## Resume Input And Model Evidence

The staged Session history proof now selects the exact input record for
unattached Hosted Resume, the live Session manager and the legacy Model
Outcome observer. The three consumers share record multiplicity and digest
checks. The legacy observer validates the already decoded V1 Binding once
per record and still uses the existing initial model invocation projection.

Hosted keeps the retained-request fallback when the latest Binding belongs to
another input. Ambiguous record identity stays unknown there. The live
Session manager keeps the exact pending record and delegates settlement to
the original Transcript owner. The legacy observer keeps whole-scan failure
precedence, so a malformed later record still makes the observation unknown.

The Product edge removes 19 Python lines and staging adds 77, for 58 net
production lines. The new history entry points carry distinct lookup rules
and share their record checks. The Model Outcome observer now reaches the
original V1 codec through staged activation history, replacing its direct
Binding dependency. The normalized graph retains 1,659 module pairs. All
121 focused Linux cases and 2,076 controlled comparisons with the prior
checkpoint pass. Native Windows validation remains open.

## Configured Continuity Plugin Replay And Instance Selection

The staged configured Continuity owner now reads desired state and historical
Source identities, honors removal tombstones, reopens exact Package revisions,
inspects new sources and owns the combined runtime publication. It reconciles
legacy enablement and selected instances through the existing Plugin Management
owners, then releases excluded revisions before the ready composition takes
ownership. Product layout, durable identities, approval, and final Hub
selection remain at the Coding edge.

Continuity and the two managed plugin assembly routes use one Harness factory
for the published Package revision reference. This replaces six repeated
projections while retaining the original Source binding and wire record.
Coding Product removes 320 Python lines, staging adds 344, and formal Harness
has zero net line change. The staged imports and durable error/identity
contracts account for the 24-line production increase.

The focused Linux tests pass in 224 cases, including 69 managed plugin
consumer cases, tombstone restart, and replay after source replacement or
removal. Another lifecycle case reproduces
the same prepare failure at the prior checkpoint. On this machine the configured
test storage has a group-writable workspace ancestor, and the Continuity
staging guard rejects that path. The 524 controlled comparisons match the
previous checkpoint's source association, activation, publication and handle
release traces.
Architecture checks pass. Native Windows validation remains open.

## Continuity Selection And Approval Assembly

The configured Continuity startup now assembles the exact selected Plugin
closure, resolves definitions through the Harness host, and prepares the owner
component host and its activation decision IDs in staging. Coding supplies
the original configured-source trust facts, approval subject validation,
durable identities, authority ceiling and approval expiry.

The managed Capability path and Continuity share one definition preflight,
approval iteration and re-resolution operation. The managed caller still
checks each issuer receipt and reports its existing diagnostics. Continuity
still issues through its original journals, preserves the durable decision
snapshot and compare-and-swap order, and returns the same redacted Product
errors. An existing activation decision remains eligible for reuse only when
it matches the Subject, is approved and available, and has not expired.

This batch removes 214 Product Python lines, adds 211 staging lines, and
adds 18 formal Harness lines, for 15 net production lines. The selected
Linux checks record 186 passes and three platform skips. Two Provider
prepares fail at the same site on the prior checkpoint under the configured
test directory. The previously reproduced Coding Continuity prepare is
excluded from this run. The 288 controlled comparisons preserve plan
inputs, approval order, error identity and diagnostics, and decision reuse.
Native Windows verification remains open.

## Continuity Session Index And Listed Target Operations

The staged Session history owner queries the existing Transcript index,
retains the bounded target cache, handles expired traversals and schedules
recovery for stale or bounded views. It shares one listed-target proof
between history resolution, activation preparation and deletion. The live
Runtime still owns the mutations and the prepared lease. Preparation retains
its post-acquisition identity check and abort, and deletion retains its
compatibility and active-Session restrictions.

Coding keeps the entry methods, default query policy, availability messages
and preview rendering. The staged code uses the original index generation,
cursor, authority checks and directory normalization. Provider preview uses
one computed revision for both display and the stale check.

The Product edge removes 166 Python lines and staging adds 194, for a net
production increase of 28 lines. The separated policy inputs and retained
entry methods account for the extra connection code. All 109 selected
Linux tests pass and 1,105 controlled comparisons match page, cache,
authority and effect traces against the prior checkpoint. The known
Continuity import test remains excluded under this machine's configured
test root. Native Windows verification remains open.

## Built-In Wheel Publication And Inspection

Eight existing POSIX and Windows entry points now share the base Wheel
and ordered capability Wheel assembly in staging. The edge supplies the
explicit inspect or publish operation. Harness ExactProductSourceFiles
and InstalledProductWheelRecipe retain native ACL and descriptor checks,
deterministic bytes, fsync behavior and failure handling. Product policy
keeps its installed assets, fixed filenames and nominal return records.

The Product edge removes 71 Python lines and staging adds 48, for a net
production reduction of 23 lines. The selected suite records 63 passes
and one Windows-only skip. The resource refresh assertion for the
workspace `review` skill reproduces with the same failure trace on the
prior checkpoint. Across all eight entry points, 120 controlled
comparisons match ordering, selected native operation, artifact facts
and failure precedence. Native Windows verification remains open.

## Legacy Package And Lifecycle Member Observation

The two pre-B member readers share one staged operation for read-only member
discovery and ordered domain grouping. The existing Harness snapshot reader
checks the root and members before any projection. The deployed Package lock
still belongs to both binding and lock history, while each lifecycle journal
and lock belongs to its declared historical domain. The original consumers
retain their required read order, including the startup first-result behavior
and the two-root snapshot preparation.

Coding keeps the canonical paths, allowed names, domain declarations and
nominal results. The staged program depends only on the existing Harness
read authority. It removes 22 Python lines from the Product and adds 31 in
staging, for nine net production lines. The 332 filesystem comparisons
match the prior checkpoint's membership, errors and read-only behavior.
All 56 selected Linux tests pass, including offline review, fresh startup
and POSIX cutover. The two Windows-only cases are skipped on this host.

## Catalog Receipt And Package Composition Binding

The staged Catalog adapter now takes the one-shot loader receipt, checks the
canonical Product source policy, and assembles the package composition through
the existing Harness plan, selection and owner-binding steps. Startup, refresh
and preview callers share the same adapter. Coding supplies the original trust
and owner policy, required Capability definitions and rejection identities.

The legacy receipt transfer retains its original error translation and
precedes fallback wall-time observation. Adapter construction still rejects
an invalid receipt before inspecting Product policy. The default package
compiler runs once when package resources are enabled and no composition was
supplied. The existing bootstrap and refresh authority checks and publication
order still govern the returned adapter.

The Product edge removes 44 Python lines and staging adds 42, for two net
production lines removed. Across 13,320 controlled cases, receipt transfer,
clock observation, Product admission, error order and native assembly inputs
match the previous checkpoint. All 67 selected Linux cases pass. Four
existing architecture assertions reproduced stale importer paths on the
prior checkpoint and now track the exact staged owners. Native Windows
verification remains open.

## Resume Permission Request And Confirmation

Staging assembles approval evidence and revalidates it against the current
session before delegating confirmation to the existing Harness interactive
resolver. It reuses Harness execution profile expansion, native Policy
fingerprints and the staged canonical Resume encoder. Coding retains the
original public entry and nominal confirmation type, Hosted subject policy,
Embedded Root identity, historical hash namespaces and approval vocabulary.

Revalidation checks the original target, Embedded approval owner and Hosted
subject before comparing exact native profiles and current Policy evidence.
It rebuilds the request through the public entry to observe current authority
again before resolving the original action.

Coding Product removes 96 Python lines and staging adds 201, for a net
production increase of 105. Applying the current formatting to the original
file alone would expand it from 209 to 273 lines. Explicit product constants
and the retained public signatures also contribute to the cost. All 138
selected Linux tests pass across confirmation, publication, first input,
continuation and history. The 4,176 controlled comparisons match the previous
checkpoint's request evidence, authority observations and failure order.
Native Windows verification remains open.

## Resume Plugin Effect Settlement

Embedded and Hosted Resume freeze the same pair of Plugin effect owners
through staging. The parent pair and owner preparation share construction
of the original Definition and Activation journals. Preparing owner facts
leaves the native clock and Writer requirements at their defaults and
performs no journal I/O. Existing Harness parent enrollment, open checks
and sealing still use the scoped journal paths, explicit clock and original
Writer protocol requirements.

First-input settlement shares the exact effect-owner and effect-class guard
for both routes. The active route observes Definition before Activation and
matches the original sealed records to selected Plugin revisions. The
no-Plugin route verifies the expected set and absence of selected Capability
Plugins without opening either journal. Coding supplies the Capability Plugin ids,
Product identity and journal names, and keeps the parent type, diagnostics
and legacy Embedded aliases. The staged journal route retains its explicit
Product binding, including the original constructors used for fault injection.

Coding Product removes 56 Python lines and staging gains 117 for 61 net
production lines. The addition covers the shared constructor options,
nominal entry points and an explicitly bound Product policy. All 75 selected
Linux cases pass, including first input and native Worker settlement.
Across 12,369 controlled comparisons the original results, failure causes
and call order match. Native Windows verification remains open.

## Composition History Comparison And Resume Evidence Digests

The staged composition history comparison supplies the unchanged results
used by foreground and background planning, Hosted preview and stale Plan
source validation. It classifies identity, provenance, ancestry, Binding and
activation in their deployed precedence before comparing the recorded set
and plan fingerprint. Coding checks the nominal input types and membership
in its canonical set registry and constructs the original result type.

The canonical set keeps its original ASCII JSON fingerprint format.
Activation Plan construction and exact bound-input lookup reuse the staged
Resume encoder with their original labels and hash domains. Input lookup
continues to encode the complete record through the existing Transcript
codec, including the persisted payload, metadata, timestamp and parent.
Plan budgets and source checks remain in their original order. The staged
composition history code imports Coding only for type annotations.

Coding Product removes 55 Python lines and staging gains 67, for 12 net
production lines. An activation Plan error table and duplicate Resume
encoding paths exit. All 117 selected Linux cases pass, with three previously
reproduced `transcript_writer:unsafe` cases deselected under the configured
test root. Across 7,268 controlled cases the original digests, comparisons,
Plans and error outcomes match. Five legacy values also retain their nominal
pickle identity. Native Windows verification remains open.

## Workspace Tool Selection And Delegation

Workspace profiles, startup defaults, parent Tool intent and delegated child
selection now share the staged platform mapping. Windows maps the neutral
bash intent to shell. Ordered intent lists keep each resulting name once,
and the native Workspace Tool profile still validates both explicit name
lists. Coding supplies the profile, default names, prompt text and exact
owner declarations.

Bootstrap preserves declared default order within the selected base, followed
by enabled peers in registry order. The parent uses the same intersection and
resolves the fallback once from its frozen host facts. Delegated child construction checks published
exact-owner identities before selecting peer definitions. It reads host facts
and exact owners directly, removing the two selection callbacks. The existing
Harness registry retains Tool construction, contribution resolution and
registration.

Coding Product removes 34 Python lines and staging adds 79, for 45 net
production lines. The staged owner imports Harness types directly and can
serve both Workspace Tool profiles and Session activation without a Product
import. All 14,800 controlled cases match ordered selections, constructor
outcomes and error behavior. The selected Linux run has 82 passes and one
dynamic extension assertion that reproduces on the prior checkpoint.
Windows target selection is exercised from Linux. Native Windows
verification remains open.

## Capability Mounts And Exact Dependency Grants

Bootstrap, Resume and the LSP CLI resolve mount modes through the staged
composition evidence owner. The CLI parser uses the same declared mode
validation. Deferred mount selection keeps the original short circuits and
uses the existing startup receipt. Missing receipts on historical sessions
retain the eager route. Coding declares the capability defaults, the Plugin
identity and the legacy disabled choice.

The existing Package Materializer calls the original grant resolver, which
now uses the staged exact-source logic. Construction observes the declared
directories in order and reuses Harness canonical Plugin source identity.
A foreign source for a reserved Plugin receives the original Harness error
and Product rejection code. Coding declares the source locations, reserved
identities, distribution and editable-checkout evidence policy. The original
resolver class, state, constructor and method paths stay at the Product edge.

Coding Product removes 21 Python lines and staging adds 101, for 80 net
production lines. Compatibility entry points, source-policy arguments and
module boundaries account for the added plumbing. All 64 selected Linux cases
pass across exact source grants, default Plugin publication, Resume and
bootstrap. All 1,776 controlled cases match original settings and receipt
reads, CLI errors, exact source checks and grant outcomes. Native Windows
verification remains open.

## Resume Failure Cleanup And Writer Fencing

Resume bootstrap, continuation and Runtime host binding share a staged cleanup
path. The original Session releases its graph and Transcript together. A
manager-only failure releases through the manager. Before any cleanup after
input commit or publication, continuation still reports the original input
identity when evidence is available. A cleanup failure already retained by
bootstrap keeps the whole candidate in custody.

If disposal fails, the staged helper fences the admitting Transcript factory
and raises the existing Product error with the original owner and both
failures. It preserves the call-site notes and original error as the cause.
The existing Session lifecycle retains and retries the error through the same
owner's disposal method. The failure type and historical import paths stay at
the Product edge.

Coding Product removes 11 Python lines and staging adds 54, for 43 net
production lines. Three inlined disposal handlers become one staged path.
All 77 selected Linux cases pass across preparation, publication and Runtime
handoff. All 924 controlled cases match original ownership, cleanup order,
fence behavior and error chains, including cancellation and failures during
retry. Native Windows verification remains open.

## Explicit Worker Query And Existing Receipt Custody

The explicit POSIX Worker query keeps Product and symbol admission at its
original Coding entry. Staging resolves the selected transcript, loads the
existing Session, creates its Package Product runtime and opens the selected
receipt through the native receipt owner. The existing Harness operation
executes the query and settles Worker, Hosting, C5 and Runtime custody.
Coding continues to supply the query Capability, Provider selection and
query-only Session configuration.

Receipt history, payload materialization and payload repair already execute
through the existing Harness `ReceiptHistory`, native receipt authority
and `PosixProductWorkerPayloadCustody`. Coding binds the original records,
codec, selected policy and compatibility aliases. The payload probes use
the original private debt-verification and remainder hooks.

Coding Product removes 49 Python lines and staging adds 96, for 47 net
production lines. The 1,344 controlled comparisons match original
validation, acquisition order, receipt outcomes and exception causes.
The selected Linux run has 19 passes, including the existing receipt and
payload coverage and architecture guards. The host-runtime query route
is skipped under the local selectors.

## Shared Epoch And Legacy Source Identity

Application state open, runtime open, fresh bootstrap retry, Legacy
acceptance and binding, POSIX backup and Windows preview now use one
Store-ID and control-root comparison. Each entry retains its original
admission, error and follow-up checks. The Windows preview still checks
the selected Store parent after verifying the epoch identity. The
comparison has a typing-only dependency on the Coding epoch layout. The
final Package Product owner can take its existing native Store identity
and control root when the product-neutral layout contract is ready.

The original Coding lifecycle component owns its deployed workspace
digest. Persistent and ephemeral layouts, runtime admission and resource
preview use the same filesystem encoding and namespace. Frozen Legacy
acceptance uses the existing Harness Legacy Wheel owner for its expected
prefix, which keeps the review and materialization identities aligned.

Coding Product removes four Python lines and staging adds three, for
one net production line removed. The existing formal Harness Wheel owner
keeps the same line count. The seven epoch entry guards match the original
comparison order and failure paths in 1,568 controlled checks. Workspace
scope and layout match in 35 cases, and Legacy Wheel identity matches in
40 cases.

The current source and 31 selected Worker cases also confirm that formal
Harness owns Linux retention and checkpoint mechanics and Windows
recovery inventory. Six selected Installation and revision cases pass.
Their Product bindings carry the existing policy, labels and nominal
records. These implementation owners predate this batch. Native Windows
execution remains open.

The 14 POSIX cutover scenarios pass, including replay and read-only
preview. The combined package and architecture run has 301 passes and
two child-handshake timeouts. The same two tests report the same failures
on the unmodified starting commit `c55af7c8f`. Both cases pass when rerun
on their own after the other suites finish.

## Scoped Plugin Management Clients

SDK and TUI command clients share staged workspace admission and guarded
port acquisition. CLI, TUI support and JSONL reads use staged read-client
admission and scoped fenced projections. Both reuse the Harness Workspace
identity capture alongside its existing identity assertion. The read path
captures the directory identity before layout resolution. The command
path checks the admitted Product fence before capturing the directory
identity. Read-only admission still uses its original query route.

JSONL read, Desired State and Package repair share the original Session
witness, workspace and identity checks. The command and repair bindings
reuse one matching-workspace check before they can return a mutation
client. The existing formal Harness command owner still performs
submission, inventory CAS and owned replay. Coding retains its nominal
clients and errors, actor and Product policies, legacy bindings, and
presentation. The temporary programs still borrow these declarations.
The next owner can take the neutral scope, identity, ports, and admitted
Session witness.

Coding Product removes 107 Python lines. Staging adds 167 and formal
Harness Workspace adds 18, so production adds 78 lines. The extra source
covers staging entry definitions and the original signatures retained by
callers. The complete client paths share directory capture, the command
fence check and the JSONL mutation rebind check. Existing Harness
submission and replay were already shared.

All 18 selected SDK/TUI/JSONL integration cases and 24 consumer cases
pass on Linux. The 11,880 controlled traces match original exception
identity, error codes and call order across directory, fence, and
projection faults. Four JSONL scope code paths retain their normalized
operation bodies. Native Windows validation remains open.

## Shared Command Rules And Private Data Admission

The Harness management record owner now supplies the Desired State action
domain and target states for TUI preflight, command submission, journal
validation and repair admission. Install keeps its own package requirement.
The operation ID, command codec, original actor and compare-and-set
behavior remain at their existing owners.

Plugin CLI readers, POSIX and Windows backup clients, and the Package
repair client reuse Harness Workspace directory observation. Each entry
keeps its original error mapping. The Coding lifecycle owner keeps the
historical workspace layout rule used by both management clients and the
POSIX backup client. The original POSIX platform and fence check is shared
across backup status, reads, and write-owner admission. All nine Arch
Installation key call sites use the same Product declaration for backup,
restore, expiry and deletion.

This removes 29 Coding Product lines and 10 staging lines. Formal Harness
adds 22 lines, so the system removes 17 production lines. The Windows
deletion, expiry and restore wrappers and the POSIX deletion journal were
also reviewed against their existing shared owners. Their 14 selected
record and controlled transaction contract cases passed on Linux.
Native Windows execution remains open.

Across the related Linux routes, 155 cases passed. The FIFO refusal
case reached its subprocess timeout during parallel verification and
passed on its own. Five native Windows cases were skipped on Linux.

## Worker Checkpoint Writer Custody

Start-gate, receipt, and Supervisor writers now use one bound checkpoint
read and error translation in the existing Harness checkpoint owner.
Scope and Store identity still resolve inside the original translation
region. The operation uses the caller's pinned root and writer authority.
The separate owner-required checks for C5 and opt-in remain in their
stream owners.

The unused Coding checkpoint guards and cast-only writer forwards have
been removed from receipt, start-gate and C5. The existing prefix and
retired-ID tests exercise the Harness functions called by the live
streams. The C5 source test uses its actual journal owner. The Product
edge retains the historical class/module identity and event schemas.

Coding Product removes 102 Python lines, staging has zero line change,
and formal Harness adds 11. That removes 91 production lines and five
normalized Coding module dependencies. Existing tests add 21 lines while
retaining the same cases. All 84 controlled read and fault comparisons
match return content, error codes, causes and resolution order.

The current Windows payload plan, native stage materialization, launch
binding, retained receipt, backend release, and history capture use their
existing formal Harness owners. POSIX registered payload repair and gated
orphan review and settlement also use their existing formal owners. The
143 selected recovery and controlled Windows contract cases pass on
Linux. Native Windows and the original host-runtime scenarios remain
open.

The selected Linux routes have 233 passes after the C5 test fixture
was corrected to the required journal filename. Seven host-runtime
scenarios were skipped by the local selector.

## Windows Worker Stage Retirement Custody

The existing Harness Package Product owner now uses the same offline
write scope and bound state root for complete, partial, unlaunched, and
crash stage retirement. Each route retains its own history and replay
proof. They persist the start review through one records owner, build the
receipt from the reviewed identity, and check for a retained stage before
publishing the receipt. The unlaunched route still checks the native
revision after reading the persisted review.

Harness Worker History now owns the review and receipt byte limits used
by both the wire types and the retirement records. Coding retains its
nominal records, error types, Product admission and historical paths.
Coding Product removes 69 Python lines and formal Harness adds 37, for a
net reduction of 32 production lines.

The selected Linux regression has 282 passes. All 6,048 controlled
comparisons match the prior result, error and lock or publication trace
across the four routes. Native Windows execution was not run.

## POSIX Worker V2 History Cutover

The existing Harness Package Product owner shares the runtime and GC
write scope across preflight, staging, rollback, owner commit, retirement,
and V1 sealing. Staging, rollback, commit, and retirement validate and
recheck the pinned state root in one scope. Retirement and sealing still
reject active leases before acquiring the GC write gate. History review
and the GC settlement reader retain their existing read-only routes.

The existing Worker History owners provide the preparation, publication,
and snapshot limits. Preflight and commit apply a single cutoff rule at
their original admission points. Coding keeps the Product checks, public
entry points and record identities for the five historical streams.

Coding Product removes 87 Python lines and formal Harness removes 21.
The system removes 108 production lines and two normalized Coding module
dependencies. The 65 selected Linux cases include real fenced Product
sealing. The manual seal probe now injects faults at the active Harness
owner. All 273 cases match the original historical bytes, errors and
custody traces. Another 129 publication and proof cases pass. A direct
comparison of 20 legacy modules matches all 77 exports, including record
slots and pickled class identities.

## Linux Worker C5 Recovery Evidence

Harness Package Product constructs the recovery evidence under the
existing runtime and GC custody. Coding supplies the nominal evidence
types with the static ID and fingerprint required by the Worker C5
coordinator. The same Product bindings now reach the evidence constructor
without rebuilding them through a second Coding entry.

Initial registered-lease settlement and its durable replay share one
runtime revision check and one GC write scope. Both revalidate the state
root before and after their distinct proof and state operations. Registered
lease repair, payload repair, and C5 CAS still have separate commitments
and retries. The crash route keeps its independent boot and native
settlement proofs. Fault injection now targets the implementations called
under real recovery custody.

Coding Product removes 101 Python lines and formal Harness adds seven.
The system removes 94 production lines and four normalized Coding module
dependencies.

All 218 selected Linux contract and history cases pass. The 85
before-and-after recovery observations match results, errors, persisted
bytes, lock order, injected faults and file descriptor release. The
Coding consumer route has 18 passes and three host-runtime skips.

## Windows Worker History Wire And Persisted Read

The six existing Harness Worker History owners now bind their wire fields
to the nominal Product dataclasses. The shared binder builds the full and
digest schemas from the same field declarations. Coding supplies its typed
records, Product receipt rules, and the Product-specific launch-intent
error. The cutover marker uses its existing Harness proof and wire owner.

The persisted reader uses the original checkpoint, marker, and six base
paths and limits from Harness history definitions. It still opens each
base with the original 32 MiB storage limit. Launch-intent decoding keeps
its 16 MiB cap. It still decodes the marker only when required and
rechecks the snapshot while it holds the original GC and pinned-root scope.

Coding Product removes 212 Python lines and formal Harness adds 159, for
a net reduction of 53 production lines and one Coding module dependency.

The 378 selected Linux cases include 171 persisted-read custody traces.
The six codecs match 656 historical wire observations and load all 12
legacy pickle fixtures. The persisted-read probe now targets the actual
cutover codec binding. Its former import hook reproduced the same 40
failures on the parent commit. The original expectations pass with the
updated hook. Native Windows execution was not run.

## Windows Worker Decision Journals

Harness Worker History owns the three fixed journal profiles for native
approval, opt-in, and receipts. Their existing commands now carry their
original filename, admission rules, byte and record limits, and publication
errors. The Coding adapters supply the Product record families, codecs and
error types. POSIX and Windows use the same native approval journal name
and default limits. Opt-in input admission uses the original identifier
rule and keeps each platform's error.

Windows approval reads and mutations and opt-in reads and revocation use
the existing History Access owner for the Product GC gate and pinned state
root. The scope rechecks the Product after closing the descriptor and
before releasing the gate. Opt-in allow keeps its selection and backend
proof in its existing position inside the GC writer.

Coding Product removes 89 Python lines and formal Harness adds 30. The
system removes 59 production lines. All 308 selected journal and decision
checks pass, and 130 root-custody comparisons match the parent. The 80
controlled backend consumer observations also match exactly. The wider
197-case consumer run has 130 passes and the same 67 older frozen-fixture
assertion failures as its parent. No native Windows execution was run.

## Pending Worker Session Preparation

The Linux and Windows pending hosts use one staged Session preparation
program over the existing Harness provider and native owners. The entry
points keep their platform-specific admission and diagnostics. Linux
accepts the original pending value family and optional base policy at
native preparation. Windows keeps exact receipt and pending types, its
base-policy owner check, and C5 recovery refusal. The recovery check runs
after graph-generation and base-policy validation and before native work.

The shared program removes 41 staging lines and 22 Coding Product lines.
The system removes 63 production lines. Normalized Coding dependencies
stay at 1,651. The staged module has six direct Product bindings
previously reached through the platform adapters. It refers to the
nominal pending hosts for typing only and has no eager import cycle.

The Worker, Session, and Resume regression routes have 85 unique passes,
including a real Linux Product transaction. The existing source check now
lists the shared program and the actual C5 consumers. Forty-two controlled
before-and-after cases match admission, error and preparation order on
both platforms. Native Windows execution was not run.

## Native Worker Release Publication

Linux install and repair share the existing Harness approval, pinned
Product root, stage verification, and publication sequence. Install
still owns its temporary staging directory and exact installed replay.
Repair only accepts one complete existing stage. The shared operation
verifies under the pinned descriptor, rechecks current approval and root
identity, publishes without replacement, verifies the published identity,
and flushes the parent. Each caller keeps its original final read order.

The Coding install adapters remove two private test forwards. The
fixtures construct the same interrupted state with the actual Harness
release owner. Coding Product removes 19 Python lines and formal Harness
removes 11. The system removes 30 production lines.

The Linux suite has 336 passes, including 50 install and 30 repair
observations. The native host repair case is skipped by the local
selector. The existing Windows Harness owners for cleanup evidence,
Supervisor and native settlement, and lease repair pass 11 controlled
checks. Windows C5 recovery was inspected at its actual owner. Native
Windows and the complete Windows C5 recovery route were not executed.

### First-fence Source projection reuse

Package Product's existing `_LegacySourceProjection` now owns settings
capture, read-only freshness checks and verification of the archived Source
projection. Its writer and verifier use one canonical encoder. Archived
reads retain the original scope and path checks, strict JSON and duplicate-key
rejection, byte budget, error precedence and digest. Consumption reopens the
same settings facts through this owner, under the original transaction and
receipt order. Coding supplies the historical projection name, source-key
policy, classifier and nominal result.

The standalone staged Source verifier and its original-module dependency
retire. Coding keeps the first-B read/list domain allowances and nominal
errors, while `_LegacyFirstSnapshot` still checks fence authority for each
operation. Existing Harness owners also perform the cutover backup proof,
retired Instance inspection, durable backup topology custody and attached
Transcript discovery. Retention in Coding covers Product trust classes,
layout, closed backup-kind policy, and the operator's RPC and TUI bindings.

This batch reduces Python production code by 53 lines. Coding outside staging
loses 34 lines and staging loses 74. The formal Harness owner grows by 55.
The comparative probe matches 287 parent outcomes for wire bytes, nominal
results and pickle bytes, error causes and failure order. Native Windows
execution remains pending. The read-only settings admission comparison also
matches 468 decisions and settings-scope read traces.

The Linux regression passes 240 cases across Source capture, installation
inventory, offline cutover and replay. Four native Windows cases are skipped
on Linux. The POSIX/controlled-Windows settings custody probe reproduces all
77 outdated injection-hook failures on the parent. After pointing the probe
at the active Config reader and projection budget, all 77 existing trace
assertions pass on both revisions.

The cumulative PLC9 inventory exposed a second declaration of the legacy
enablement key in the consumption binding. The Source policy now declares
the keys that block consumption and derives the captured key set from them.
The original inventory assertion passes with one enablement-key declaration.
Eight consumption, refusal and replay cases pass. This follow-up removes
another three production lines.

### Cumulative candidate verification

The frozen inventory contains 459 Python files and 260 extraction candidates.
Each candidate has operation-level evidence for its current owner and callers.
The dependency audit accounts for 177 temporary imports from staging into
Coding and finds zero explicit reverse imports from formal Harness.

The installed wheel resolves 300 historical module aliases, contains all 121
staging modules, and round-trips five historical Source snapshot pickles.
The affected-path runs pass 92 private-data cases, 154 Resume cases, 125
Worker receipt and payload cases, and the native Linux cross-process Worker
operator case. The Linux PLC9C5 contract, native profile and Product canary
reports satisfy their existing manifests. The existing Actions plan selects
native Windows AppHost checks, ConPTY and terminal contracts, and
three-platform Resume smoke. Dedicated Worker coverage remains subject to the
existing Harness, Windows Shell, and Worker Reboot workflow pauses.

Resource loader and Continuity tests create independent fixture workspaces
while pytest storage stays in the managed runtime. This exercises actual
ancestor discovery and filesystem permission checks in both suites. The
candidate runs 125 cases successfully with one existing platform skip. The
same two fixtures give 52 passes and one skip against the parent source,
resolving the 33 failures reproduced in both revisions under the previous
fixture placement.

Managed launch, local commands, catalogs, store discovery and output capture
pass 112 cases using isolated fixture workspaces. The Mux read, start and
stop recheck passes 24 cases. A wider Mux run passes 121 cases and reports
one initial session-creation failure. The exact failing case passes when
rerun with the same workspace fixture and the existing redacted diagnostics.

Another 38 focused cases pass with independent fixture workspaces across
Bootstrap, CLI, Continuity, settings and Session persistence, resource
watching, foreground restart and the simulated launchd adapter. The fixtures
place test Product state outside the developer checkout. The pytest wrapper
still manages the invocation's scratch directory.

Standalone fixture workspaces also pass the 79 Repository and interactive
Goal cases and the 15 hosted interactive Goal cases. These cover planning,
original Work and Session ownership, verification, review and cancellation.

Managed model restore and hosted review cancellation pass when run serially
after the other suites have exited. They exercise the original 60-second
and 20-second deadlines. Earlier concurrent runs reached those deadlines
on both the baseline and candidate.

The final fixture recheck passes 13 Work Shell cases and the Workspace
Preview scope-admission case. Each of the 251 failures or setup errors
from the first 4,345-case Coding run has a passing focused recheck.

The cumulative local runs passed 4,321 Coding, 6,359 Harness, 519 Hosting,
3,246 AppHost, and 2,652 AppService cases. AppHost also passed its G8, G9,
and G10 evidence checks and the installed Linux CLI canary. The remaining
selected local checks and two end-to-end smoke cases passed.

The existing five-file integration plan covered 247 tests. Of these, 245
passed on the initial run with inputs unaffected by the fixture corrections.
The two native Worker cases failed store admission under the workspace's
group-writable ancestor. Both passed in isolated reruns using the existing
standalone-workspace fixture. The CLI case exercised native Worker use,
same-boot crash recovery, and prior-boot crash recovery with the same
platform state directory in parent and child. The Hosted case exercised
first-session persistence, Worker access, and revocation. The managed pytest
runtime and the production storage checks remained in use.

## Cost And Final Acceptance

Count the Product edge, `coding.harness`, all Coding, formal Harness, Hosting,
other production code and the whole system separately. Tests, development
scripts and docs have separate counts. The Coding total includes staging.
Track duplicate removal and ownership changes with their own evidence, along
with the cost of generalization and compatibility.

The production Python counts use Goal baseline `df0dca779` and the last
implementation commit `4255d9bbc`.

| Scope | Baseline | Candidate | Change |
| --- | ---: | ---: | ---: |
| Coding Product | 100,715 | 87,707 | −13,008 |
| `coding.harness` staging | 0 | 19,816 | +19,816 |
| All Coding | 100,715 | 107,523 | +6,808 |
| Formal Harness | 380,073 | 380,398 | +325 |
| Hosting | 14,235 | 14,235 | 0 |
| Other production Python | 154,018 | 154,018 | 0 |
| System production Python | 649,041 | 656,174 | +7,133 |

The four earliest implementation batches account for 6,042 of the 7,133
added lines. Legacy package migration added 2,059, fenced package and plugin
lifecycle added 1,575, private-data lifecycle added 1,351, and Worker startup
and Resume added 1,057.

At `9f336e480`, an AST count of the changed Product modules
finds 206 entries with a single call to staging, occupying 2,108 physical
lines, and 75 newly introduced numbered value maps occupying 695 lines. These
are structural footprints. The original signatures, diagnostics and stored
values already contributed to the baseline, and some must stay for
compatibility. Legacy local acceptance illustrates the combined cost: 419
original lines became 256 Product lines and 372 staging lines. Its repeated
typed signatures, calls through internal Product forwarders, and numbered
value maps are candidates for consolidation at the owning boundary.

Whole-Goal acceptance requires all frozen migration targets, their real
consumers, single implementation owners, complete mappings, explicit permitted
dependency debt, compatibility/security evidence and cumulative checks. Only
then publish the task, complete normal integration/merge/local sync and safely
remove its accepted clean worktree/branch. The first private-data batch is one
milestone, not the complete migration.
