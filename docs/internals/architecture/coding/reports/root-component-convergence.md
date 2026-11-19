# Coding Root Component Convergence

## Status

- Scope and owner: Coding Product; implementation/review: Codex `/root`.
- Design and implementation review: accepted within delegated Coding Product responsibilities for internal placement and compatibility; no Product-policy or platform-contract change.
- Delivery authority: normal PR checks and merge history; local validation below is separate from remote acceptance.
- Accepted base: `923131671bf1cbf84309080355080efd9013acc2` (PR #914).
- Frozen observations: `9146a1d3bcbeaf7e172253a7fcefea5ffdb88769`, whose
  complete tree equals that accepted base. The dependent task was fast-forwarded
  to accepted main without changing any in-progress source bytes.
- Method: clean local `archmethod` master at
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.
- Current work: Coding internal placement and public compatibility; no Coding implementation moves to Harness.

## Whole Goal Root Coverage

At Goal baseline `5b0c18d09`, the root held **299 Python files / 68,085 physical
lines**. All are accounted for: 296 implementation modules move into components,
while the existing public facade, SDK inspection entry and six-line cleanup
compatibility entry remain. The two root modules added by unrelated upstream
work (`foreground_host.py` and `macos_service.py`) are also relocated, so the
three batches cover 298 former root implementation modules in total.

The current root has those three retained entries plus the single shared
compatibility loader: **four Python files / 399 lines**. Seven declarative SDK
stubs add 137 lines, for **536 root Python/declaration lines** without subtracting
imports, exports, comments or blanks. Every relocated implementation exists at
its current owner, and every replaced old Python source file is absent. This
source disposition proof complements the complete local checks below. Remote
platform and delivery evidence remain separate.

## Scope And Owners

Move the remaining 97 root implementation modules as one reviewable batch:
32,492 baseline physical Python lines. Group facts, complete operations and
shared change reasons rather than assigning ownership solely by old prefixes.

| Component | Moved files | Baseline implementation lines | Responsibility |
| --- | ---: | ---: | --- |
| `adapters` | 1 | 281 | Existing subprocess agent invocation adapter |
| `authoring` | 2 | 1,106 | Offline Plugin/Extension author journeys |
| `cli` | 1 | 144 | Plain prompt command and presentation binding |
| `composition` | 16 | 11,104 | Product plans, capability/provider admission, base construction and configured Continuity assembly |
| `control` | 1 | 292 | Product sandbox/permission ceilings |
| `hosted` | 44 | 11,885 | Product Session catalogs, AppHost/Service binding, managed deployment, client policy and explicit offline canaries |
| `interaction` | 2 | 116 | Model/reasoning policy independent of terminal selectors |
| `package` | 3 | 198 | Existing Worker history, preparation policy and tool identity |
| `resources` | 5 | 933 | Product resource/catalog selection and workspace-tool profile |
| `resume` | 14 | 3,349 | Historical intent, current admission, activation correspondence and first-input coordination |
| `session` | 3 | 2,465 | Transcript/state lifetime, Continuity binding and delegated Session adapters |
| `presentation` | 2 | 147 | Feature-local terminal model/reasoning adapters independent of the Coding UI surface |
| `workspace` | 3 | 472 | Workspace inspection, constrained mutations and Git handoff policy |

`composition.plan` remains a low-level declarative Product selection; importing
it does not construct CLI/UI adapters. Configured Continuity assembly belongs
with Product composition, while the live Continuity binding belongs with Session
lifetime. The workspace catalog is a Hosted Product binding; filesystem/Git
policy remains separate. LSP and Arch remain Coding-owned.

## Interface And Dependency Adjustments

Six complete existing bootstrap operations and six existing Session operations
have explicit component names. Real consumers use those names; necessary local
aliases preserve fault injection and the original argument policies. There are
no new Protocols, suppliers, execution wrappers or authority grants. Policy-aware
private bootstrap routes are not replaced with narrower ordinary SDK signatures.

Two existing Plugin-effect admission checks move from Embedded UI coordination
to `resume.plugin_effects`. Hosted Resume uses that owner directly. The exact
current Hosted-subject guard moves to `resume.subject`; permission confirmation
no longer imports the full Hosted execution adapter to validate its subject.
Original compatibility entries borrow the same functions, retaining historical
callable identities and exact admission behavior.

The existing Session exports become lazy while preserving their ten names,
order and owner objects. This prevents a new parent-package import cycle.
Bare Coding import now defers compatibility initialization until a child module
is requested. The same existing loader/finder remains its implementation owner;
the temporary bootstrap delegates to it and is removed after registration.
Registered implementation finders remain respected, with no new custom locks.
The accepted baseline also failed the original strict cold-root test; this
change restores that existing contract instead of weakening it.

Explicit public static declarations move from the runtime facade into
`__init__.pyi`. Six historical public SDK owner stubs re-export their current
owners, justified by the frozen SDK inventory and existing exact-type tests.
Two earlier management component paths have the same declarative type support.
These files duplicate no classes, fields or execution bodies, are packaged
explicitly, and have no generic Any fallback. Python and stub lines/root totals
must be reported separately. The existing 200-line runtime-facade ceiling stays
unchanged; its current runtime file is 151 lines.

The complete transport-neutral management composition bodies also move from
`plugin_manager.cli` to `plugin_manager.binding`, and from
`package.product_management_cli` to `package.management_binding`. Neither body
parses arguments or renders UI/output. SDK, command adapters and Package clients
use these owners directly, reusing the existing Harness state selector and port
carriers rather than copying its fenced/legacy/empty selection. Historical CLI
names remain compatibility identities, not evidence that these bodies implement
a CLI transport. Previous component paths alias the same implementation/module.
No Coding mechanism is extracted into Harness.

The existing Hosted Goal → `adapters._goal_repository` dependency and CLI →
Package repair/review private calls predate this batch. Their complete operations,
argument policies and failure behavior remain unchanged. They are retained
internal interfaces, not new public SDK contracts or evidence of fully decoupled
Goal execution. This batch does not redesign Method/Work/Goal execution.

## Compatibility And Assets

The existing single Coding compatibility finder reads an additional frozen,
pure-data route catalog. No 97 root forwarding files or second loader is added.
Old and canonical module paths resolve to one module/type object. The production
AST review finds no remaining literal `import_module`/`__import__` call to any
of the 97 old root owners. Computed names from users/history remain supported
by compatibility routing; this observation does not claim to enumerate arbitrary
dynamic strings. Historical
module/type names, original slots/fields, pickle lookup and error identities
remain deployed contracts, not strings to rename blindly.

The identity helper also restores callable defaults stored in slotted dataclass
fields and function argument defaults, in addition to existing default factories.
Initial comparison exposed those lambda metadata differences; the helper fixes
them rather than normalizing the difference out of the acceptance comparison.
A deterministic supplemental capture from the same unchanged frozen baseline
removes only hash-seed-dependent set-repr ordering. All 694 original pickle
reference observations are byte-identical to the first immutable capture.

The data-only base Plugin still resolves the actual checked-in/installed
`coding._plugins` tree. Reserved LSP/Arch grants use that existing asset package
as their anchor. Executable canary/managed/launchd module arguments and installed
author commands use canonical paths; historical routes remain available for old
records and imports. Source-identity diagnostics report the real relocated file.
Installed-wheel observations now verify all 1,981 Python/stub source files
byte-for-byte, the actual base/LSP/Arch asset trees, all console target imports,
and both previously published management component aliases. No host/runtime is
started by these observations; native and installed executable behavior remains
subject to the existing platform checks.

## Compatibility Retention And Exit Conditions

| Surface | Current reason | Evidence required before exit |
| --- | --- | --- |
| Frozen original root routes and nominal identities | Existing imports, persisted symbol references, fault hooks and new compatible writers still use the original qualified names; one real implementation serves both paths | An explicitly accepted API/data compatibility change, a versioned writer/reader transition where needed, and replay evidence for all supported retained histories. Removing static callers alone is insufficient, especially while writers still emit old nominal names. |
| Six historical SDK owner stubs and the root SDK declaration | Preserve exact published types and original owner imports; runtime aliases alone cannot satisfy static consumers | The supported SDK contract must explicitly retire or replace those import routes; supported consumer compilation and positive/negative exact-type checks must prove the transition. The root declaration itself remains while Coding publishes this SDK. |
| Two previous management component paths and their stubs | Earlier delivered component imports must continue to resolve to the same neutral binding owners; no second module/type is created | Complete migration of real, dynamic and fault-injection consumers plus an accepted public import deprecation. Original root nominal/pickle routes are a separate contract and cannot be removed with these aliases. |
| Existing private operation names behind public component aliases | Preserve complete argument policy, existing local fault hooks and qualified function identity without adding forwarding execution bodies | Review dynamic/fault/persistence consumers and explicitly accept any qualified-name change; retain a versioned compatibility route if supported records refer to the old callable. No removal based solely on zero static matches. |
| Six-line root cleanup compatibility entry | Preserves the existing Coding import of the same Harness-owned cleanup objects; no cleanup mechanism is duplicated | Establish that supported imports and dynamic/fault consumers have migrated, and explicitly retire the old entry. Harness object identity remains independently supported. |

No arbitrary date or migration percentage substitutes for these conditions.
The public root facade and SDK-surface inspection entry are ordinary Product
APIs, rather than temporary business implementation awaiting relocation.

## Root Target And Cost Rules

The user's target is at most 1,000 root lines apart from imports/exports.
Current frozen source has four root Python files and **399 physical lines**,
including comments and blanks. Seven root type declaration files add 137 lines;
the complete root source/declaration surface is **536 lines**, already below the
target without subtracting any imports/exports. `__init__.py` is 151 lines,
`_component_imports.py` 181, `sdk_surface.py` 61 and `_cleanup.py` six.
No new PR gate enforces this Goal target.

Root retention is explicit: `__init__.py` is the public Product facade;
`sdk_surface.py` selects the public Coding SDK contract over Harness inspection;
`_component_imports.py` preserves supported module/type lookup; `_cleanup.py`
retains its existing six-line compatibility entry. Pure route metadata lives
in the compatibility component, with no execution behavior hidden in it.

Moving 32,492 baseline implementation lines inside Coding is not system deletion.
Cost against accepted main `923131671` follows; physical lines include blanks and
comments. Stubs are separate because their type declarations are executable-tool
inputs even though they contain no runtime implementation.

| Category | Baseline lines | Candidate lines | Change |
| --- | ---: | ---: | ---: |
| Coding Python | 100,443 | 100,715 | +272 |
| Harness Python | 380,073 | 380,073 | 0 |
| Hosting Python | 14,235 | 14,235 | 0 |
| Other production Python | 154,018 | 154,018 | 0 |
| All production Python | 648,769 | 649,041 | +272 |
| Production type declarations | 0 | 143 | +143 |
| CI/development Python scripts | 19,944 | 19,986 | +42 |
| Test Python | 706,028 | 706,326 | +298 |
| Documentation Markdown | 288,601 | 289,118 | +517 |

All production Python plus type declarations grows by **415 lines**. No business
mechanism is counted as duplicate deletion: this batch relocates owners and
adds necessary compatibility/public declarations. Added runtime cost comprises
component initialization, the lazy compatibility bootstrap/catalog, explicit
operation aliases and the complete asset-location fact. Three existing Resume
guard bodies change owner without being reimplemented. No existing numeric line
budget is raised. Documentation and test costs are separate from production
code; configuration/source-pointer edits do not count as mechanism deletion.

## Current Component Sizes

Physical Python lines include blanks/comments; child directories are recursive.
Type declaration lines remain separate.

| Component | Python files | Python lines | Type declaration lines |
| --- | ---: | ---: | ---: |
| `package` | 192 | 31,568 | 3 |
| `hosted` | 46 | 11,902 | 0 |
| `composition` | 17 | 11,124 | 0 |
| `cli` | 27 | 9,428 | 0 |
| `adapters` | 26 | 7,179 | 0 |
| `lsp` | 21 | 5,228 | 0 |
| `session` | 5 | 4,450 | 0 |
| `plugin_manager` | 16 | 4,133 | 3 |
| `arch` | 13 | 3,571 | 0 |
| `resume` | 17 | 3,427 | 0 |
| `ui` | 14 | 2,191 | 0 |
| `authoring` | 3 | 1,107 | 0 |
| `resources` | 10 | 937 | 0 |
| `interaction` | 7 | 907 | 0 |
| `runtime` | 3 | 844 | 0 |
| `workspace` | 4 | 473 | 0 |
| `compaction` | 4 | 440 | 0 |
| `(root)` | 4 | 399 | 137 |
| `control` | 3 | 344 | 0 |
| `diagnostics` | 3 | 233 | 0 |
| `prompt` | 3 | 132 | 0 |
| `_plugins` | 6 | 124 | 0 |
| `_compat` | 2 | 114 | 0 |
| `presentation` | 6 | 256 | 0 |
| `workflow` | 2 | 82 | 0 |
| `domain` | 3 | 72 | 0 |
| `platform` | 2 | 50 | 0 |

The whole Goal time interval changes Coding from 100,058 Python lines at
`5b0c18d09` to 100,715 (+657), but **442 of these lines belong to unrelated main
changes before the first batch delivery**. That interval also includes unrelated
Harness +11 and other production Python +10; none is attributed to this work.

Measured against each PR's accepted first-parent base, the componentization
batches change Coding Python by: Package PR #913 **−126**, Plugin Manager PR #914
**+69**, and this root batch **+272**, totaling **+215 Python lines**. The nine new
type declaration files add 143 lines, so the three batches together add **358
production Python/declaration lines**. No business-mechanism deletion or Harness
migration is inferred from these placement changes. Accounting includes every
Git-visible staged and unstaged file, including new component files.


## Validation And Gate Preservation

### Current Candidate

The current source/declaration inventory contains 1,981 files; its SHA-256 is
`b17ba9b4df4ab90953ae38548929fe60ba2ae0f90810708b77c71bd8b089d5c4`.
The serial local runner checks that inventory before each scope. Source changes
require reassessment rather than borrowing results from the earlier placement.

| Existing check | Current candidate evidence |
| --- | --- |
| Architecture generation and governed documents | Commands return zero; documentation also rechecked after report updates |
| CI routing | All 150 existing regressions pass |
| AI | 943 passed, seven live cases deselected; 90.86% coverage and all original coverage targets, lint, types, catalog and boundaries pass |
| Foundation / Agent | 112 / 167 tests pass |
| Coding | Complete command returns zero: 4,321 passed, 24 skipped, 77 deselected; four existing JUnit property warnings; 3,224.40 seconds |
| Feature-local UI boundaries and model selection | All 66 existing cases pass with original budgets and assertions |
| Changed-file Ruff | All 469 modified/new Python and declaration files pass |
| Harness | Complete command returns zero: 6,356 passed, 116 skipped; 36 existing tool-selection warnings; 886.91 seconds; lint and mypy pass |
| Hosting | Complete command returns zero: 515 passed, 61 skipped; 92.32 seconds; lint and mypy pass |
| HarnessTUI | Complete command returns zero: 1,078 passed, 87 deselected; 121.37 seconds |
| Coding UI | Complete command returns zero: 614 passed, 68 deselected; 147.08 seconds; lint and mypy pass |
| Terminal unit / playback | Complete commands return zero: 1,322 passed / 319 passed, with 243 / 8,234 deselected; 33.59 / 49.32 seconds |
| AppHost | Complete command returns zero: main regression 3,246 passed / 23 skipped (1,025.42 seconds); existing G8/G9/G10 evidence checks pass 19/16/15 cases; installed G10 canary passes with actual `posix-process-group-v1` backend; lint and mypy pass |
| AppService | Complete command returns zero: 2,652 passed, 18 skipped; 1,075.22 seconds; lint and mypy pass |
| Component unit routes | All seven selected routes complete, reusing identical covered cases where recorded and running uncovered example contracts |
| GUI | TypeScript compilation passes; all 22 test files and 167 existing tests pass with original assertions/deadlines |

The complete Coding route includes the existing persistence/resume/close and
terminal cancellation smoke cases. The original full UI manifest, 2,200-line
package budget, 355-line mode budget and feature-local no-UI dependency assertions
remain unchanged. Model/reasoning terminal adapters belong in `presentation.tui`;
no UI budget exception or general mypy argument-deduplication helper is retained.
The source inventory drops one explicit selector-file argument already covered
by its `presentation/tui` directory: its expanded ten-file set stays identical,
and all 198 implementation plus 18 declaration gate comparisons remain equal.

### Compatibility And Installed Content

All three batches pass their immutable source and installed-wheel comparisons:
298 original module identities, 1,082 original public definitions and 1,912
original protocol 4/5 pickle symbol references. The 97-root subset includes 423
public definitions and 694 original symbol references. Reflection, slots/fields,
legacy root attributes and source-loader lookup are included. The rebuilt wheel
has exactly the current Python/declaration file set, with all 1,981 installed
files byte-identical to source. Actual base/LSP/Arch asset trees, console-target
imports and both previous management component aliases are checked as well.
Installed SDK positive and negative type probes retain their original exact
expectations: no errors for the positive probe, and three expected diagnostic
kinds for the negative probe. No generic Any fallback is introduced.

These are inert API, content and symbol-reference proofs. They do not prove live
Product instance serialization, native resource transactions or frozen executable
behavior. Existing runtime tests and actual native jobs provide separate evidence.

### Ownership And Check Scope

The normalized static graph changes from 449 to 459 modules and from 1,655 to
1,662 unique imports. Nontrivial strongly connected groups change from 12 to 13;
every current group is contained in an original group, with no new or enlarged
cycle. This includes literal dynamic imports and lazy/type references, but does
not prove all runtime import-order or deadlock behavior. The original ten Session
exports retain their order and owner objects through a lazy initializer.

Normalized explicit cross-component private imports change from 67 to 51. No
private operation/type import is added; the only new private package reference
anchors existing `coding._plugins` assets. Existing Hosted Goal adapter and CLI
Package repair/review integrations remain explicitly retained internal coupling.
Computed imports and runtime object attributes lie outside this AST count.

The implementation-body audit checks 693 original class/function definitions
across the 97 root moves and two additional management moves. Imports and three
executable module arguments follow canonical paths; three asset locators receive
the required package anchor. Extracted guard bodies are checked at their owner.
Route catalogs are literal data, and stubs contain only declarations/reexports.

Per-file selection preserves 198 implementation comparisons and 18 declaration
comparisons against the accepted selector/inventory: checks, workflows, unit jobs,
Windows flags and E2E selection stay equivalent. Routing does not import Product
code. Seven machine-consumed inventories update source pointers while retaining
schemas, identities, dispositions and authority. Existing AppHost workflow lint
and mypy commands receive 22 path replacements for 11 moved owners; reversing
only those substitutions reproduces the accepted workflow byte-for-byte. No
trigger, job, platform, assertion or numeric budget changes. Actionlint v1.7.12
passes, and no literal reference to the 97 old root owners remains in workflows.

### Diagnosed Failures And Remaining Limits

Earlier validation exposed a real relocated asset-anchor bug. Package revision
policy now uses the complete source-location fact from the dependency-grant
owner; exact-root trust checks remain unchanged, with no path-search fallback.
G9's raw text rule now excludes only the audited pure historical route catalog.
Its implementation dependency assertions remain unchanged. AppHost's consumer
inventory also records the exact current-subject guard extracted into
`resume.subject`; its complete signature/body AST matches the original Hosted
owner. The G11 inventory and AST import references follow the same operation;
G10's current component/launch references also follow canonical owners, preserving
its accepted requirements and historical baseline facts. All 95 existing AppHost
architecture cases pass after these source-reference updates. PLC9A1's owner-site
expectation follows `composition/continuity.py`; its original ten cases pass.
The initial selector placement failed the original no-UI dependency boundary;
its two complete bodies now belong to feature-local `presentation.tui` instead.
Earlier complete-suite counts from the rejected placement are historical only.

An earlier AI deadline run was interrupted after 695 passes, and an isolated
native probe also stalled. The unchanged accepted-main case passed separately;
the full current AI route passes with verbose names and thread-only faulthandler
diagnostics. An observation-only scheduling probe is excluded from acceptance.
No AI implementation, assertion or deadline changed. The unchanged frontend's
complete check passes all 167 tests using its supported single-worker threads
pool, unchanged assertions and original 5,000 ms deadlines. No GUI source,
configuration or PR gate changes are introduced by this execution choice.

The isolated Windows probe-collection test initially loaded accepted main from
the shared editable virtual environment: `-I` intentionally ignores the task
PYTHONPATH. Its unchanged original case passes with the current candidate wheel
installed in a private test environment using the same dependency versions.
Remaining checks use that interpreter so isolated children observe the candidate.
No probe confinement, Product code or assertion is relaxed; no native Windows
scenario is executed by this collection test.

Eight selected scopes require workflow-specific execution and have not run
locally: `tui_native`, `harness_native`, `hosting_sustained`, `host_runtime`,
`windows_shell`, `registered_reboot`, `install` and `lsp`. The accepted selector
already pauses Harness, Hosting, AppService, host-runtime, Windows-shell and
Worker reboot workflows; those pauses remain unchanged. Selected platform flags
do not imply remote execution. Final evidence must name jobs actually run and
retain remaining platform gaps. No native Windows or frozen-executable result
is inferred from Linux simulation or inert installed-wheel observations.

All 23 runnable local scopes return zero. The eight workflow-only exclusions
above remain explicit. Normal remote checks, accepted merge and local sync are
separate delivery evidence; local success alone does not establish them.

## Exact Baseline Mapping

Paths below are relative to `src/loushang/coding`; lines include comments/blanks.
The two new shared Resume files above contain existing extracted guard bodies,
not additional root migrations or duplicate implementations.

| Original root file | Canonical path | Baseline lines |
| --- | --- | ---: |
| `_apphost_canary_child.py` | `hosted/_canary_child.py` | 26 |
| `_apphost_canary_control.py` | `hosted/_canary_control.py` | 419 |
| `_hosted_execution_work.py` | `hosted/_execution_work.py` | 159 |
| `_hosted_goal_config.py` | `hosted/_goal_config.py` | 58 |
| `_hosted_goal_work.py` | `hosted/_goal_work.py` | 183 |
| `_hosted_method_config.py` | `hosted/_method_config.py` | 100 |
| `_hosted_method_work.py` | `hosted/_method_work.py` | 124 |
| `_hosted_repository_config.py` | `hosted/_repository_config.py` | 114 |
| `_hosted_repository_work.py` | `hosted/_repository_work.py` | 218 |
| `_hosted_work_observation.py` | `hosted/_work_observation.py` | 53 |
| `apphost_canary.py` | `hosted/canary.py` | 1,012 |
| `apphost_composition.py` | `hosted/composition.py` | 566 |
| `apphost_product.py` | `hosted/product.py` | 484 |
| `hosted_application.py` | `hosted/application.py` | 762 |
| `hosted_bootstrap.py` | `hosted/bootstrap.py` | 313 |
| `hosted_catalog.py` | `hosted/catalog.py` | 969 |
| `hosted_continuity.py` | `hosted/continuity.py` | 171 |
| `hosted_execution.py` | `hosted/execution.py` | 354 |
| `hosted_execution_goal.py` | `hosted/execution_goal.py` | 119 |
| `hosted_goal.py` | `hosted/goal.py` | 216 |
| `hosted_goal_application.py` | `hosted/goal_application.py` | 70 |
| `hosted_goal_commands.py` | `hosted/goal_commands.py` | 191 |
| `hosted_goal_recovery.py` | `hosted/goal_recovery.py` | 119 |
| `hosted_goal_review.py` | `hosted/goal_review.py` | 59 |
| `hosted_local.py` | `hosted/local.py` | 214 |
| `hosted_method.py` | `hosted/method.py` | 138 |
| `hosted_method_application.py` | `hosted/method_application.py` | 52 |
| `hosted_models.py` | `hosted/models.py` | 53 |
| `hosted_resume.py` | `hosted/resume.py` | 749 |
| `hosted_session.py` | `hosted/session.py` | 702 |
| `hosted_session_goal.py` | `hosted/session_goal.py` | 261 |
| `hosted_user_choice.py` | `hosted/user_choice.py` | 255 |
| `managed_bootstrap.py` | `hosted/managed/bootstrap.py` | 150 |
| `managed_catalog.py` | `hosted/managed/catalog.py` | 228 |
| `managed_local.py` | `hosted/managed/local.py` | 182 |
| `managed_process.py` | `hosted/managed/process.py` | 196 |
| `managed_service.py` | `hosted/managed/service.py` | 75 |
| `appservice_adapter.py` | `hosted/service_adapter.py` | 242 |
| `foreground_host.py` | `hosted/foreground.py` | 132 |
| `macos_service.py` | `hosted/macos_service.py` | 198 |
| `app_tunnel.py` | `hosted/tunnel.py` | 64 |
| `_product_worker_canary.py` | `hosted/_worker_canary.py` | 852 |
| `bootstrap.py` | `composition/bootstrap.py` | 3,540 |
| `_base_plugin.py` | `composition/base_plugin.py` | 977 |
| `_base_plugin_owners.py` | `composition/base_owners.py` | 522 |
| `_capability_plugin_composition.py` | `composition/capability_plugins.py` | 1,661 |
| `_capability_plugin_specs.py` | `composition/capability_specs.py` | 103 |
| `_product_capability_plugin_composition.py` | `composition/product_capability_plugins.py` | 700 |
| `_base_product_composition.py` | `composition/base_product.py` | 618 |
| `_external_data_product_composition.py` | `composition/external_data.py` | 235 |
| `composition_sets.py` | `composition/sets.py` | 236 |
| `product_plan.py` | `composition/plan.py` | 46 |
| `embedded_resume.py` | `resume/embedded.py` | 390 |
| `_resume_cleanup.py` | `resume/_cleanup.py` | 54 |
| `resume_activation_attempt.py` | `resume/activation_attempt.py` | 281 |
| `resume_activation_attempt_v2.py` | `resume/activation_attempt_v2.py` | 223 |
| `resume_activation_plan.py` | `resume/activation_plan.py` | 400 |
| `resume_activation_projection_v2.py` | `resume/activation_projection_v2.py` | 228 |
| `resume_binding.py` | `resume/binding.py` | 389 |
| `resume_binding_v2.py` | `resume/binding_v2.py` | 194 |
| `resume_composition_comparison.py` | `resume/composition_comparison.py` | 82 |
| `resume_continuation.py` | `resume/continuation.py` | 486 |
| `resume_history.py` | `resume/history.py` | 233 |
| `resume_input_lookup.py` | `resume/input_lookup.py` | 52 |
| `resume_model_outcome.py` | `resume/model_outcome.py` | 134 |
| `resume_permission_confirmation.py` | `resume/permission_confirmation.py` | 203 |
| `continuity.py` | `session/continuity.py` | 1,212 |
| `continuity_bootstrap.py` | `composition/continuity.py` | 1,603 |
| `session_manager.py` | `session/manager.py` | 749 |
| `agent_invocation.py` | `adapters/agent_invocation.py` | 281 |
| `multiagent.py` | `session/multiagent.py` | 504 |
| `_invocation_product_profile.py` | `composition/invocation_profile.py` | 108 |
| `runtime_capability_admission.py` | `composition/runtime_admission.py` | 350 |
| `plugin_author_smoke.py` | `authoring/plugin_smoke.py` | 740 |
| `extension_author.py` | `authoring/extension.py` | 366 |
| `resource_runtime.py` | `resources/runtime.py` | 128 |
| `_resource_catalog_adapter.py` | `resources/catalog.py` | 445 |
| `_resource_catalog_shadow.py` | `resources/catalog_compatibility.py` | 52 |
| `tool_pack.py` | `resources/tool_pack.py` | 266 |
| `_tool_authority.py` | `resources/tool_authority.py` | 42 |
| `workspace_catalog.py` | `hosted/workspace_catalog.py` | 217 |
| `workspace_inspection.py` | `workspace/inspection.py` | 196 |
| `workspace_operations.py` | `workspace/operations.py` | 118 |
| `worktree.py` | `workspace/worktree.py` | 158 |
| `model_reasoning.py` | `interaction/reasoning.py` | 49 |
| `model_reasoning_tui.py` | `presentation/tui/reasoning.py` | 58 |
| `model_selection.py` | `interaction/model_selection.py` | 67 |
| `model_selection_tui.py` | `presentation/tui/model_selection.py` | 89 |
| `prompt_command.py` | `cli/prompt.py` | 144 |
| `client_settings.py` | `hosted/client_settings.py` | 66 |
| `composition_provenance.py` | `composition/provenance.py` | 214 |
| `capabilities.py` | `composition/capabilities.py` | 85 |
| `plugin_dependency_grants.py` | `composition/dependency_grants.py` | 106 |
| `sandbox.py` | `control/sandbox.py` | 292 |
| `_worker_history_access.py` | `package/worker_history_access.py` | 11 |
| `_worker_preparation_inputs.py` | `package/worker_preparation_inputs.py` | 182 |
| `_worker_tool_identity.py` | `package/worker_tool_identity.py` | 5 |

## Additional Complete Composition Owner Moves

| Previous component path | Current implementation owner | Compatibility |
| --- | --- | --- |
| `plugin_manager/cli.py` | `plugin_manager/binding.py` | Original root and published component imports share one module; old static imports re-export the same public types |
| `package/product_management_cli.py` | `package/management_binding.py` | Same module/type/callable identities and fenced-port behavior; historical pickle names unchanged |

Path routing additionally preserves four original local/PR selections for these
two owners. Eighteen comparisons cover the nine declaration surfaces against
their original Python owner selections. All 150 original CI regressions pass.
No original numeric line budget was raised. A fixture's exact expected module
set now includes only required namespace parents, compatibility data and legacy
aliases; unrelated runtime imports remain rejected, while the bare-root test
still permits no Loushang child import at all.
