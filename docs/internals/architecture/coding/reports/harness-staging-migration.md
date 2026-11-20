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
| `pre_b_snapshot` | Nominal preparation/cutover bundles, actual private root/path list, fresh-only settings/input policy, explicit Windows-candidate admission and Code builtin bootstrap choice. Root preparation/projection/reopen entries directly bind existing native Harness owners. Whole pinned snapshot lifetime and cutover execution are staged. |

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

## Cost And Final Acceptance

Count the Product edge, `coding.harness`, all Coding, actual Harness, Hosting,
other production code and the whole system separately; tests, development
scripts and docs are separate costs. Staging remains inside Coding and is not
system deletion. Report actual duplicate removal separately from ownership
movement; explain any necessary generic/compatibility growth.

At `9f336e480`, the four earliest batch commits account for 6,042 of the 6,587
net production lines added against the Goal baseline. The largest is Legacy
package migration at 2,059 lines. An AST count of the changed Product modules
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
