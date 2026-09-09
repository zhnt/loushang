# G18.0 Scenario Inventory

- Source baseline: `9bc69361494293595ae424be225c61e3226a9996`
- Authority: measurement inventory for the [G18 plan](startup-performance-plan.md),
  not a replacement readiness or lifecycle contract
- Status: installed inert-path reference frozen (9/10 stable); native milestone collection pending
- Platform: current Linux first; macOS/Windows adapters and acceptance pending

## A — Installed Inert Paths

The fixed manifest lives in `scripts/dev/measure_g18_startup.py::CASES`.
The collector uses actual wheel console scripts, not calls to Python `main`.
It rejects dirty Product source/lock, compares source/wheel bytes, checks installed
package bytes and provenance before/after, and records its own source hash.
The historical reference uses the **same** wheel in both environments: A/A noise
calibration, not an optimization comparison. The current record-only runner also
accepts explicit wheel A/B and source A/B revisions. Each wheel is checked against
its own immutable commit (ambient Git configuration/replace disabled), including
declared resources and entry targets; the verified hash pins every installation
check. Lock, project metadata, package paths, interpreter and dependencies must
match between variants. This wiring is not yet an accepted end-to-end A/B result.

| Case | Exact action | Output assertion |
| --- | --- | --- |
| import-harness | isolated interpreter imports `loushang.harness` | empty stdout/stderr, exit 0 |
| import-coding | isolated interpreter imports `loushang.coding` | empty stdout/stderr, exit 0 |
| import-cli | isolated interpreter imports `loushang.coding.cli.__main__` | empty stdout/stderr, exit 0 |
| cli-help | `loushang --help` | Loushang help including --help/--model, empty stderr, exit 0 |
| cli-version | `loushang --version` | baseline version 0.1.0, empty stderr, exit 0 |
| tui-help | `loushang-tui --help` | Loushang help including --help/--model, empty stderr, exit 0 |
| hosted-help | `loushang-hosted --help` | matching usage/--help, empty stderr, exit 0 |
| hosted-tui-help | `loushang-hosted-tui --help` | matching usage/--help, empty stderr, exit 0 |
| mux-help | `loushang-mux --help` | matching usage/--help, empty stderr, exit 0 |
| plugin-help | `loushang-plugin --help` | matching usage/--help, empty stderr, exit 0 |

All wall times start before parent Popen and end when output is drained and the
root has exited (observed unreaped with waitid). Output handling is included;
fixture setup, report IO and final cleanup are excluded. Child user/system CPU
seconds are reaped-child accounting deltas in a sequential collector, not RSS.
No profiler is enabled. After code review the current collector runs its
stdlib sample observer inside the existing retained supervisor, with Linux
subreaper admission before target Popen. Normally only the root is reaped;
same-group or detached leftovers are adopted, reclaimed by the existing owner,
and always invalidate the sample. Supervisor work is outside the timing interval.
Output is bounded to 256 KiB, and diagnostic timeout is 60 s. This remains fixed
inert-path tooling, not hostile-process containment or a native Product owner.
The historical A/A reference predates this correction and is qualified accordingly.

Two blocks each contain ten pairs for every case: 20 A/A pairs (40 samples per
case), plus one declared warmup per case/install/block. A/B order alternates by
pair/block; case order reverses in block two. All samples are kept, including
warmups and failures. Reports are atomically replaced after each sample; a failed
case stops collection with partial evidence, never silently retries.

Each child has a fresh `/tmp/loushang-g18-baseline-*/...` app root outside the
checkout, synthetic HOME/config/runtime/temp, a fixed environment allowlist,
and no inherited provider/source/Git configuration. Parent environment is not
modified. All inputs are empty: recovery behavior is not inferred from these cases.
Each installation has a distinct **retained** bytecode prefix; warmup establishes
the warm-bytecode condition. OS page cache is uncontrolled. No global cache or
user home is cleared; task-owned scratch and evidence are retained for diagnosis.

## B — Real Startup / First Use / Settlement

These mappings freeze the existing semantic anchors to reuse; they are **not yet
timed by the A collector**. Test-suite elapsed time must not be substituted for
spawn-to-ready. Freeze the native measurement adapter and per-sample seed manifest
before any optimization claims full G18.0 or `G18-READINESS` acceptance.

| Path | Existing fixture / semantic anchor | First use and settlement |
| --- | --- | --- |
| Embedded TUI | `tests/coding/test_hosted_legacy_evidence.py::_embedded`; installed `loushang --tui`, welcome + bracketed-paste/focus mode enabled | local `/hotkeys` completed panel; Enter closes with completed main-screen witness; `/quit`, exit 0, modes restored, reader stopped |
| Foreground hosted TUI | `tests/coding/test_hosted_client_terminal.py::test_G17_TERMINAL_ENTRY_installed_help_ready_and_foreground_exit`; `/exit ends app` frame | reuse picker workflow's `/new cwd`, member `*1`; `/exit` plus native child-settlement observer |
| Local mux | `tests/coding/test_mux_terminal_process.py::test_G16_TERMINAL_NATIVE_installed_attach_creates_scoped_member_and_detaches`; server ready JSON and attach frame are distinct milestones | `/new user_home Review`; detach preserves server, explicit stop settles server |
| G14 hosted stdio | `tests/coding/test_hosted_subprocess.py::test_G14_PRODUCT_installed_entrypoint_help_startup_and_clean_eof` | existing protocol/startup acknowledgement and clean EOF, not TUI first frame |
| cwd/global recovery | `tests/coding/test_hosted_client_terminal.py::_picker_workflow`; explicit canonical history visible after selection/relaunch | complete baseline seed reset for each restored sample; fixed history and Session count, normal owner cleanup; original live-seed regression retained |
| Product first model/tool use | `tests/coding/test_hosted_workflow_terminal.py::test_G17_TERMINAL_PRODUCT_discovery_profile_keeps_turn_approval_and_interrupt` | deterministic model transport only; actual Product/tool/approval/interrupt, separate from shipped CLI evidence |
| G10 canary regression | `tests/coding/test_apphost_canary.py::test_native_canary_leaves_user_session_roots_untouched` | original timeout/ephemeral IO contract unchanged; not a surrogate for the above |

Adapter exit conditions: exact boundary timestamps, fresh/recovery seed hashes,
private-home poison negative control on real default/hosted startup, original
deadline preservation, and retained native process ownership on failure. The A
collector's environment unit test is not this real-startup negative control.
Existing G16/G17 installed/native mandatory gates remain required; source or
skipped-host tests do not satisfy them.

### Native Comparison Policy — Pre-Candidate Review

This policy is proposed before any G18.1 Product change or candidate measurement.
It does not upgrade historical preflights, freeze an unstable baseline, or change
Product deadlines. Accept the numeric policy only after review; accept the native
baseline only after repeated same-wheel calibration under these conditions.

Compare warm and absent conditions separately at the fixed measured prefix with
the fixed baseline observer. The condition applies before the scenario's first
measured process; later processes may be warmed by preceding scenario operations,
so this is not a claim that every attachment starts independently cold.
Each condition requires all seven cases, two blocks
of ten pairs per case (20 pairs), and one declared warmup per case/side/block.
Failure, missing/duplicate sample, missing metric, input/provenance drift or
incomplete settlement cannot produce an accepted comparison. All raw samples and
warmups remain visible; no trimming or automatic retries.

The exact native metric inventory is:

| Case | Required comparison metrics (all suffix `_seconds`) |
| --- | --- |
| embedded | ready_frame, first_command, spawn_through_first_command, panel_close_observation, settlement |
| foreground | ready_frame, first_command, spawn_through_first_command, settlement |
| local-mux | server_ready, attach_frame, first_command, spawn_through_first_command, detach_settlement, stop_settlement |
| g14-stdio | protocol_ready, first_command, settlement |
| recovery-cwd / recovery-global | ready_frame, history_visible, first_command, spawn_through_first_command, settlement |
| product-first-use | server_ready, review_attach_frame, dev_attach_frame, reattach_frame, first_model, spawn_through_first_model, first_approval, first_tool, interrupt, review_detach_settlement, dev_detach_settlement, reattach_detach_settlement, settlement |

These are 41 separately checked metrics per cache condition. Cumulative milestones
are not added together; an improved ready frame does not hide a slower first
command, full spawn-through-first-command path, or cleanup. Product-first-use's
synthetic server remains a fixture composition, not a shipped-console ready claim.

Architecture review found gaps in the initial 36-metric proposal: installed
`create` and the Product fixture's two `/new` operations precede the narrower
first-command/model timers, while three attachment detaches precede final stop.
The five additional metrics close those gaps: local server spawn through the
existing first-member `*1` witness; synthetic Product server spawn through the
first real model reply; and each of review/dev/reattach's detach input through
its existing terminal context and reader settlement. These additions are still
test-side observations and preserve every Product action, owner and deadline.
They require implementation plus fake-clock/report negative controls before
native baseline acceptance; older 36-metric preflights are not upgraded.

Proposed conservative decision boundaries, in seconds:

- For same-wheel A/A calibration, the four side/block medians must span no more
  than `max(minimum median * 0.10, 0.020)` for every metric. Each group's MAD must
  be at most `max(group median * 0.10, 0.010)`.
- For A/B, apply the same block-span/MAD stability checks independently within
  each variant, so a genuine optimization does not count as cross-variant noise.
- A stable candidate metric may regress by no more than
  `max(baseline pooled median * 0.10, 0.020)`. Every required metric must pass;
  no averaging a regression against improvements elsewhere.
- Missing validity is a failed/invalid run. Excess dispersion is inconclusive,
  never success. Report nearest-rank p95 descriptively, not as a tail guarantee.

The relative allowance covers second-scale process/startup milestones; the
20 ms absolute allowance bounds small command/cleanup differences without making
near-zero baselines unusable. This is an explicit engineering acceptance choice,
not an inferred timer resolution or Product SLO. The native driver uses condition
notification and a 50 ms maximum wait, not a mandatory 50 ms sampling quantum.
The strict proposal intentionally does not widen native allowances to accommodate
the previously observed host noise. If baseline calibration is unstable, retain
the evidence and resolve measurement conditions, rather than adjust thresholds
after observing candidate benefit.

The separate A-group priority-help target remains a median reduction of at least
30%; passing native no-regression alone is not a performance delivery. The native
comparator and negative controls are implemented and reviewed; actual calibration
remains pending. Observer changes require their own review and new matched inputs;
runtime contracts remain unchanged.

The current native adapter requires a third `--observer-install` containing wheel
A, distinct from both measured installations. Every sample runs the same observer
Python, Product/test helpers and observer-only bytecode cache; explicit measured
prefixes select console commands. Receipt fields distinguish observer origin and
prefix from the measured prefix. Initial/final checks pin the observer installation
to source A and require the same interpreter/dependencies as the measured pair.
This controls observer import-graph differences, not external scheduler/page-cache
noise. Existing preflight failures are not promoted to timing evidence.

G14 alone uses an explicitly scoped CPython 3.11 `SafeChildWatcher` in the private
Linux observer. It waits only for registered PIDs on the event loop, without a
background waitpid thread. Main thread, no running loop and default SIGCHLD are
required before the Product operation; there is no fallback. The original
asyncio.run, fixture cleanup and retained owner remain authoritative, and the
original policy/signal are restored even on failure. The G14 receipt binds
`stdio_observer.backend=cpython311-safe-child-watcher-v1`, the actual watcher type
and the independently verified observer Python version. This reviewed change
addresses the observed ThreadedChildWatcher handoff window; it does not change
the Product or its three timing anchors. All new A/A and A/B runs use this same
condition; earlier Threaded receipts are retained, not mixed or upgraded.

`product-first-use` observes the original discovery-enabled G16/G17 workflow, with
the original synthetic-transport Product server and three real mux attachments.
It records server-ready, review/dev/reattach frames, first model reply, approval
request, approved tool result, interrupt completion and final stop settlement as
distinct milestones. Replayed history does not replace the first-model timestamp.
The server uses the measured Python/wheel, but remains a test transport composition,
not a shipped-console server startup claim. Installed native preflight 08 completed
four valid workflows (two warmups and one A/A pair); unit tests are recorded
separately. One pair does not freeze timing or complete the B-group acceptance.

### Real HOME Isolation Negative Control

Architecture review selected a bounded four-launch control, now implemented by
`measure_g18_native.py --home-isolation-only`; installed acceptance passed in
`home-isolation-03` (two installations, eight controls, runner exit 0).
`ai/model/registry.py` reads `Path.home() / ".loushang/models"`; a task-only
`g18-poison.json` containing `{` deterministically raises the loader's invalid-JSON
error. Ordinary settings use platform home and do not replace this regression.

Run the existing retained Python/PTY owners in a separate fixture wrapper whose
explicit HOME/USERPROFILE point at a synthetic ambient home. Each actual Product
launch gets fresh workspace/platform/temp roots. The correctly isolated group
uses `private_environment`; the sensitivity group differs only by putting
HOME/USERPROFILE back on the poison home, leaving LOUSHANG_HOME private.

| Entry | Sensitivity control: leaked HOME | Correct private HOME |
| --- | --- | --- |
| installed `loushang --tui` | autonomous nonzero exit, poison path + invalid JSON, no ready | original ready, `/quit`, clean exit/modes/reader |
| installed `loushang-hosted-tui` | original ready then `/new cwd` gives `session_unavailable`, no successful member | same `/new cwd` gives `*1`, clean `/exit` |

Both hosted branches must finish normal `/exit` and owned-child settlement. Empty
hosted ready alone does not create Session services and therefore cannot prove
model-path isolation: the services factory reaches ModelCatalog/default registry
on first member creation. Keep original deadlines; no real prompt/provider IO.
Compare ambient file inventory/bytes and wrapper/outer-parent environments before
and after. Do not compare atime or require a rejected Session creation to leave no
private canonical files. This verifies these fixed paths, not arbitrary file
access containment; no additional runtime hook or monitor is proposed.

The collector supplies separate per-installation/per-control bytecode paths under
its output directory. These correctness controls do not measure cache warmth;
their HOME/config/state/cwd/temp remain fresh. Do not put disposable bytecode in
the quota-limited temporary filesystem alongside the retained cleanup receipts.

`home-isolation-01` failed: hosted-leaked ready exceeded the original 35 s budget,
then `/tmp` user quota prevented probe/result publication. The retained owner
completed cleanup after space was recovered; the final outer report is failed,
not a passed isolation control or baseline. See the review follow-up for evidence.
The corrected third run preserves both earlier failed runs. It proves the HOME
control only, not timing stability, recovery correctness, or candidate speedup.

## Recovery Input Boundary: Fixed-Prefix Preflight, A/B Pending

`native-preflight-09` completed real CLI1 creation/close and CLI2 picker/history
selection/exit, but failed before CLI3: recursively treating every `.jsonl` under
session roots as a canonical Session also counted nested capability Plugin
decision journals. That strict validator had only passed a simplified fixture.
The replacement's baseline-only `restored-recovery-preflight-01` completed both
scopes: two real setup launches plus two independently restored CLI3 launches per
scope. Its original raw report is retained; a subsequent receipt-validation fix
requires fresh acceptance and does not retrospectively upgrade that report.

The actual recovery input also contains platform continuity journals, materialized
Plugin revisions and a package lock. The implemented baseline-only alternative is
to preserve them as opaque input bytes, rather than duplicating their decoders
and volatile-field normalization in a performance tool:

- Produce a pristine seed through real baseline CLI1/CLI2 and normal settlement;
  retain canonical mux/member/history semantic checks at the actual scope root.
  The generating retained observer must also return before the outer coordinator
  copies state: observer-side SDK work can hold process-scoped startup leases.
- Snapshot the complete private Product file namespace (workspace, HOME,
  config/state/data/cache/runtime/temp). Keep the snapshot, coordinator, owner
  registries, receipts, reports and interpreter/bytecode outside the reset tree.
- At a fixed task-owned absolute path, restore every sample, including the first
  and warmups, only after the preceding owner has fully settled. Bind all file
  bytes, empty directories and modes; reject special files/symlinks or unexplained
  live-runtime state. Preserve failed sample evidence before any reset.
- Ordinary lease/lock files are opaque state, not evidence of a live OS lock.
  Preserve their bytes; never delete them or fabricate terminal journal events
  to manufacture a clean seed. Actual Product restart must perform its normal
  inactive-startup recovery.
- Record seed generation time, age at each launch and baseline provenance. Do
  not restore in-memory admission, freeze the Product clock, refresh stored lease
  deadlines or call baseline-state upgrade recovery candidate-native state.
- Snapshot restore does not preserve inode/ctime. Do not relabel this as the
  existing warm/current Store-head condition or edit sidecar bytes to fake it.
  Validate and report Store identity separately; whether CLI3 actually exercises
  its fallback requires evidence. The content-bound replay index is distinct.

**Unresolved comparability prerequisite:** actual package-lock source identities
contain the absolute measured installation prefix. One snapshot from install B
given unchanged to independent A/B prefixes creates different source-matching or
reconciliation work. A fixed Product-visible measured installation slot (switch
and verify outside timing, fixed independent observer) is under review. It must
also preserve explicit per-variant bytecode conditions, including isolated Hosted
children, before the snapshot method can be accepted for A/B timing.

The opaque state component and fixed-prefix owner/reset integration are reviewed;
the full A/B recovery baseline is not approved. Keep the original G17 three-launch
history/settlement preflight requirement and preserve the failed ninth run. No
candidate timing has been observed and no Product behavior changed.

### Fixed Measured Installation Slot — Same-Wheel Preflight Passed

Use one fresh, task-owned absolute installation prefix and two parked whole venvs
on the same filesystem. Build/install each variant at that prefix, verify it,
then park it with directory rename. Never execute the parked paths. Switching
renames the inactive venv into the same prefix only after the previous existing
retained owner has completely returned. Console shebangs, `sys.prefix`, resolved
module paths and builtin Plugin source identities therefore use the same path.
Do not use an active-prefix symlink: resolved Plugin paths would expose the parked
variant. Do not rewrite Product source records or copy OS locks.

This is tooling storage coordination, not another process supervisor. A single
coordinator owns the fresh slot, and failure in install, switch, source validation
or owned execution stops further activation while retaining the failed state.
The serial guard covers venv creation and dependency installation as well as both
rename steps and measured execution. Installers and validation processes also use
the existing retained owner; marking failure cannot substitute for settling them.
Use exact active/a/b sibling directories, same-filesystem dev/inode binding and
non-overwriting rename only, with no copy fallback or automatic rollback.
The fixed baseline observer, control receipts, baseline/candidate wheels and
Product-state snapshots are separate from the installation and reset tree.

Verify the active wheel bytes, source receipt, interpreter, dependency versions
and console wrappers before and after each operation, outside timing. Both venvs
must be built at the active path, not copied from foreign-prefix installations.
Keep per-variant adjacent bytecode with its parked venv and use separate external
bytecode roots for measured console processes. Hosted children using `-I` ignore
Python environment controls; their adjacent caches must be accounted for too.
Warmup remains once per case/variant/block, with caches retained across switches.

For the absent condition, the order is: activate → installation verification →
Product input reset → clear task-owned adjacent and external bytecode → file-only
absence verification → measured launch → complete owner settlement → postverify.
No slot Python may run between the absence scan and the measured launch. The
Python executable and base standard-library cache outside the owned installations
remain shared/as found; never clear them. This condition must be explicitly named
**absent task-owned installed Product/dependency bytecode**, not OS-cold or absence of every
stdlib cache. Cache write policy and inventories belong in each sample receipt.
Recovery-subject bytecode is a separate **seed-preserved** layer: inventory it in
the snapshot and never delete it after restore while claiming identical full-tree
input. It is not a per-variant cache retained across warmups. A claim of absent
bytecode throughout all Product state would require a separately frozen seed.

Generate the opaque seed using baseline at the fixed prefix. Every measurement,
including warmups, starts from the same snapshot at the same Product-state paths.
Candidate consumption is baseline-state upgrade recovery, not candidate-native
state. Record seed creation time and age at launch without altering Product
clocks or persisted lease deadlines. Baseline source/seed provenance and candidate
source provenance remain separate. Three-view design review accepts these bounded
constraints. The directory component, retained offline installer and pre/post
verification are implemented and reviewed; `slot-recovery-preflight-01` completed
both scopes' A/B/A restored history and settlement with two same-wheel venvs.
That preflight explicitly uses bytecode as found. Cache-policy implementation,
comparison wiring and a subsequent full seven-case warm preflight are now reviewed
and complete; formal warm/absent calibration remains pending. See the review record
for the separate raw evidence, failures and negative controls.
Stable paths alone do not prove equal recovery work for different wheels.

## Separate Acceptance States

The A baseline may be frozen as a scoped reference before B is implemented.
The first such reference is [G18-LINUX-INERT-AA-01](startup-performance-g18-linux-freeze.md).
That does not complete all of G18.0 or authorize a help-only G18 delivery.
Absent-bytecode measurements, RSS/module attribution, native milestones, candidate
A/B support and external-platform evidence remain explicit follow-up work.
