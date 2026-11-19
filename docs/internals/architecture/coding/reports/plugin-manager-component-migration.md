# Coding Plugin Manager Component Migration

## Status

- Owner: Coding Product; implementation and internal review: Codex `/root`.
- Design status: accepted; implementation locally verified; remote delivery pending.
- Baseline: `d066681982c07e2aacdff9de466a1972a35797b6`.
- Method consulted: clean local `archmethod` master,
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.
- Scope: Coding internal componentization; no Harness extraction.

## Responsibility And Boundaries

The component groups Coding's installation lifecycle binding, owner-generation
evidence, enablement compatibility, management commands, read projections and
transport adapters. Existing Harness management, journal and resource owners
continue to execute their shared mechanisms. This component does not create a
new ledger, worker framework or recovery engine.

`lifecycle` binds Coding policy and workspace state to those Harness owners.
`owner_generations` owns Coding's evidence interpretation. CLI, SDK, RPC and UI
adapters bind the management interfaces to their respective callers. Importing
the component itself must not eagerly assemble these adapters. Product plugin
composition and plugin authoring are separate responsibilities, even though
their root filenames also contain `plugin`.

Package operations require the lifecycle layout and product decisions; this
does not authorize their core implementation to depend on a CLI adapter.
Read-only discovery and preview must retain their existing authority limits.
Persistent workspace hashes, state paths and policy identifiers remain deployed
contracts rather than directory names to rename during this move.

## Frozen Batch Mapping

All paths below are relative to `src/loushang/coding`. Lines are baseline Python
physical lines, including comments and blank lines.

| Previous root file | New path | Baseline lines |
| --- | --- | ---: |
| `_plugin_lifecycle.py` | `plugin_manager/lifecycle.py` | 1,035 |
| `_plugin_owner_generations.py` | `plugin_manager/owner_generations.py` | 301 |
| `plugin_enablement_compatibility.py` | `plugin_manager/enablement_compatibility.py` | 159 |
| `plugin_local_discovery.py` | `plugin_manager/local_discovery.py` | 559 |
| `plugin_management_cli.py` | `plugin_manager/cli.py` | 282 |
| `plugin_management_command_rpc.py` | `plugin_manager/command_rpc.py` | 92 |
| `plugin_management_command_sdk.py` | `plugin_manager/command_sdk.py` | 218 |
| `plugin_management_explanation.py` | `plugin_manager/explanation.py` | 125 |
| `plugin_management_preview.py` | `plugin_manager/preview.py` | 239 |
| `plugin_management_read_sdk.py` | `plugin_manager/read_sdk.py` | 275 |
| `plugin_management_rpc_scope.py` | `plugin_manager/rpc_scope.py` | 132 |
| `plugin_management_ui.py` | `plugin_manager/ui.py` | 292 |
| `plugin_operation_guidance.py` | `plugin_manager/operation_guidance.py` | 67 |
| `plugin_support_status.py` | `plugin_manager/support_status.py` | 330 |
| **Total** | **14 implementations** | **4,106** |

## Compatibility Strategy

One existing bounded import compatibility mechanism serves both relocated
components. Its implementation moves from `package/_imports.py` to the Coding
compatibility boundary `_component_imports.py`; frozen per-component mappings
remain explicit. The fourteen historical root modules do not get individual
forwarding files. Old and canonical routes must resolve to one module and one
type identity, with historical pickle lookup preserved.

Actual production consumers use canonical component paths. Historical strings
must be reviewed individually before any update. In particular, fault injection
must still reach the implementation owner, and nominal types must retain their
fields, slots and historical metadata.

The frozen routes remain necessary for supported historical imports, nominal
error names and pickle lookup, including the two former private lifecycle and
owner-generation modules. A route can exit only when its public/dynamic
consumers and supported stored identities have a compatible migration or a
governed end to their compatibility contract. Routing and nominal identities
must be reviewed together; zero static imports alone cannot justify removal.
The former `package._imports` helper is not a historical implementation route:
its sole production caller was the Coding initializer, which now installs the
shared helper directly. Neither component nor the public Coding facade exports
that helper; it defines no Product record or nominal public type.

## Outstanding Acceptance Work

- Complete the existing remote platform routes and normal PR acceptance.
- Record merge, local sync and safe task-worktree cleanup after acceptance.

All 23 selected locally executable scopes pass. The eight separately selected
routes remain explicit: native TUI, native Harness, sustained Hosting, host
runtime, Windows shell, registered reboot, installed-package integration and
real LSP. They need their existing platform/Actions environments; no paused gate
was restored or expanded. Moving 4,106 lines inside Coding is not a system code
deletion.

The full Coding Goal also includes the remaining mixed root responsibilities;
this batch cannot establish completion of that broader goal.

The user's subsequent root target is to approach at most **1,000 lines apart
from imports and exports**. This candidate still has 101 direct-root Python
files / 32,925 physical lines. Conservatively excluding only AST import spans
and literal `__all__` declarations leaves **29,014 lines**; comments, blanks,
export resolvers and compatibility implementation remain counted. This is an
open Goal target, not a new PR gate or a claim that the root is converged.
Large startup/product-composition and hosted/session responsibility groups
still require complete owner review and migration.

## Implemented Boundary Adjustments

The fence-existence query now lives in `package.epoch_layout`. Its AST is
identical to the baseline function: it performs `lstat`, reports absence only
for `FileNotFoundError`, and grants no repair authority. Actual consumers use
that owner; `package.product_management_cli` re-exports the same callable and
its historical pickle identity is retained. Existing star-export lists remain
unchanged; the new owner is used through explicit imports.

Lifecycle exposes four names for existing objects: private-tree preparation,
runtime boot identity, startup lease acquisition and startup lease release.
The three Package consumers and Continuity composition import these public
names. Local aliases preserve existing fault-injection sites. There is no new
mechanism or forwarding implementation.

The SDK read adapter still uses CLI's existing read-binding assembly, and
fenced management port assembly still resides in `package.product_management_cli`.
These are remaining composition-review items for the wider Goal; moving the
fourteen files does not establish complete adapter independence throughout
Coding.

## Verification

Fourteen implementation bodies preserve the baseline non-import AST except
for four public aliases; no existing comment was lost. The original 50 public
definitions preserve reflected signatures, fields, slots and identities, and
all 100 original protocol 4/5 pickle references pass. The earlier 187 Package
modules preserve 609 definitions and 1,118 original pickle references. Both
components pass these checks from source and an actual installed wheel, whose
canonical files and status console entry are verified. The installed status
command's `--help` exits successfully before Product runtime construction.
Synthetic registered-loader probes pass in both import orders; this does not
establish native frozen-binary acceptance.

| Existing local route | Result |
| --- | --- |
| Component and real consumers | 195 passed, 5 host-runtime skips |
| Architecture contracts and SDK | 88 passed |
| G9 composition and closure, complete files | 28 passed |
| Coding selected offline route | 4,321 passed, 24 skipped, 77 deselected |
| Harness | 6,356 passed, 116 skipped; Ruff and mypy (917 sources) pass |
| Hosting | 515 passed, 61 skipped |
| HarnessTUI | 1,078 passed, 87 deselected |
| Coding UI | 614 passed, 68 deselected; Ruff and mypy (24 sources) pass |
| TUI unit | 1,322 passed, 243 deselected |
| TUI render/playback | 319 passed, 8,234 deselected |
| AppHost main route | 3,246 passed, 23 skipped; Ruff and mypy (162 sources) pass |
| AppHost G8 / G9 / G10 supplements | 19 / 16 / 15 passed; original report verifiers pass |
| GUI | 22 files, 167 tests; TypeScript passes |
| Original AI target | 943 passed, 7 deselected; overall coverage 90.86%, core 90.83% |
| Foundation / Agent | 112 / 167 passed |
| CI / architecture renderer / documentation | 150 CI tests and existing static checks pass |
| AppService | 2,652 passed, 18 skipped; Ruff and mypy (106 sources) pass |
| Remaining unit routes | Original static checks pass; Agent / Harness examples pass 2 / 3 cases; proven subset coverage reused |

Counts describe executions in existing routes, not unique tests across their
overlapping inventories. Coding's offline route is not all Coding integration,
native or UI coverage. Existing host-runtime exclusions and skips do not prove
native or sustained-runtime behavior; separately selected platform routes still
require their actual execution environments.

The first broad Coding attempt found G9's JSON entrypoint inventory still
pointing at the removed status source. Only that `source` field changed to the
canonical path; identity, disposition and authority remain unchanged. The
complete G9 files and subsequent complete Coding route pass with their original
assertions. The failed initial attempt is retained as failure evidence.

The 59 modified test files retain their assertion counts, which supplements
review without proving semantic equivalence by itself. The lifecycle source
owner allowlist retains all three original OR terms and adds only the exact
canonical owner path. Its test executes and passes within Harness. No new test
cases, assertions, routes, workflows or merge-blocking conditions were added.
Production source remains the fingerprint recorded below throughout these
checks. All 31 selected scopes are accounted for: 23 passed locally and eight
require the existing platform routes. Remote results remain pending.

## Internal Design Review

Codex `/root`, acting within the delegated Coding Product implementation and
architecture-review responsibilities, accepts the fourteen-file placement and
bounded shared compatibility mechanism. This is internal design acceptance,
not user acceptance, an independent review, or completion of the wider Goal.

The review checks that the batch includes the actual state/lifecycle owner,
retains existing Harness mechanisms, keeps persistent identities unchanged,
exposes the four necessary component names without new implementations, and
retains exact historical module/type identities at the compatibility edge.
The epoch fact has one implementation owner and the two Package core clients
no longer import CLI for that fact. The SDK/CLI assembly relationship identified
above remains explicit work for the broader componentization.

Source-observed Coding dependencies, including lazy and type-only imports,
change from 1,650 to 1,654 edges after normalizing relocated owners. Both graphs
have twelve nontrivial strongly connected components; none is new or enlarged.
This is a static import comparison, not a whole-system runtime or deadlock
proof. Existing cycles remain work to classify, rather than a claimed removal.

The complete selected local plan and source/test cost accounting pass internal
review. Normal remote checks, merge and synchronization still govern delivery
acceptance. No user or independent-reviewer acceptance is claimed.

## Production Cost At The Candidate Source Snapshot

Physical Python lines include comments and blank lines. The source snapshot is
`e6bea94d9d093ede5f4ab137df81bb7b4e908a92e25265cdb385e4c5b2392e51`;
the baseline is the commit recorded above.

| Area | Baseline lines | Candidate lines | Change |
| --- | ---: | ---: | ---: |
| Coding | 100,374 | 100,443 | +69 |
| Harness | 380,073 | 380,073 | 0 |
| Hosting | 14,235 | 14,235 | 0 |
| Other production `src` Python | 154,018 | 154,018 | 0 |
| **System `src` Python** | **648,700** | **648,769** | **+69** |
| Test Python, separately | 706,025 | 706,028 | +3 |
| Repository `scripts` Python, separately | 19,944 | 19,944 | 0 |
| Documentation Markdown, separately | 288,346 | 288,601 | +255 |

Coding gains two Python files overall: the component initializer and its frozen
route catalog. The existing loader moves from Package to the Coding boundary.
Four lifecycle aliases reuse existing objects, and import rewrites/reflow account
for the remaining physical-line cost. No duplicate business mechanism is
claimed deleted. Direct-root Python files change from 114 / 36,859 lines to
101 / 32,925 lines; that decrease is internal placement, not system reduction.
The machine-consumed G9 JSON changes one source pointer with no net line change.
Remote delivery remains to be recorded.
