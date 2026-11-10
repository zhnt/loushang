# Canonical Transcript Catalog Custody Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted direction and R5 prototype; actual bounded acceptance on 2026-11-10.
- Implementation status: implemented; bounded technical acceptance on 2026-11-10.
- Owner: existing AppHost/Harness optional integration for application coordination;
  existing Transcript source and StoreAdmission for physical observations.
- Baseline: `489929afd895f5147fa9858d5f1ef9a7a220ecd2` (A79).
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Path And Correct Owners

A80 replaces canonical create/find/list/display-discovery/open, owned post-delivery
candidate custody, claim/close and Managed Store probe/root-observation coordination.
Public Coding classes remain the actual catalog and candidate instances. There is
one original records map, lock, pending-session ledger and pair of claim/closed facts;
no inner catalog manager, new index, execution owner or duplicate registry is added.

AppHost's catalog owns Product/Profile generation admission and leases, rather than
Transcript directory authority. Its existing optional Harness integration is the
correct boundary for AppHost candidate contracts and AppService discovery DTOs.
The dark HarnessAppHostSessionAdapter is neither constructed nor activated. Its
canonical branch previously delegated the complete external owner; wrapping that
Code owner again would leave the old mechanism. Its legacy pinned-byte candidate
and cleanup contract cannot replace an owned writable manager or history binding.
The private `_canonical_transcript_catalog` now supplies the complete operations
within that existing integration boundary. AppHost's stdlib-only core is unchanged.

Transcript's existing summary/index catalog is best effort and cannot replace
strict routing. The original FileLayout scan, authority fingerprint, header loader,
read budget, Factory.new/restore_context, Writer and StoreAdmission are directly
reused. Their existing IO and lifecycle mechanisms are not credited again. The
new internal `_canonical_header` owns directory/file revision and complete
before/read/after header observations; it does not fall back to summaries. The
original StoreAdmission module owns Managed active probes/read bounds, failed-close
retention and root/store identity observations on the same actual catalog object.
It constructs and calls the actual admission owner, without a Code IO program.

Coding retains real public classes and constructors, Scope/Record/binding values,
metadata/version/create/scope identity, compatibility and view policy, exact public
signatures and thin forwards. Header-to-record and manager/candidate constructors
are pure Product projections. Actual owner getters remain lazy at the original
point; capturing their classes in init would lose the existing wrapper-fault window.
Budgets are similarly read at their original point rather than cached.

The main base declares21 abstract value/constructor/policy interfaces, including
the existing pending_sessions observation. At least eight are already-existing
Product overrides. Source error/budget, Managed bounds and candidate policy also
have real costs. They are all counted; a new broad profile or stage DSL is not
introduced to conceal them. Three unconsumed private global shims and two new
single-use pure forwarding helpers were removed after source review. The remaining
Code `_revision` has real history consumers and forwards to the actual Transcript
module-qualified helper.

Candidate's existing history-currentness guard remains an explicit narrow effect
boundary. Its getter returns the original public HistoryBinding guard, which checks
accepting/current revision. It is not described as a pure IO-free callback or a
second read program. The five history preview/navigation methods and the actual
history/transfer classes keep their original AST. This batch does not adopt KD011
navigation/provider or A33's pending Windows publication design.

## Original Ordering And Recovery

- Owned Factory preparation and catalog post-delivery custody remain distinct.
  Once Factory returns, the actual raw lifecycle session is retained without an
  await, before manager wrapping and header admission. pending_preparations can be
  empty while pending_sessions retains that same raw object for close retry.
- Owned admission uses the original sync operation scope around the physical read,
  validates the pure record, checks another sync scope, constructs the candidate,
  rechecks accepting, then removes the raw session from pending. Any primary
  BaseException survives failed cleanup, with the original note and retained debt.
- Legacy open checks revision and constructs its actual manager before entering
  the cleanup try. Its original wrapper-construction failure window is preserved,
  not silently repaired. Legacy create catches Exception and attempts same-key
  find recovery after a possibly committed write; owned create has no such catch.
- Catalog close fences the factory before waiting on the original lock. It retries
  only undelivered sessions and then closes the factory. Delivered candidates keep
  their Writer. It catches only Exception and raises the first retained failure;
  cancellation/interruption is not replaced by CloseGroup or RetryableCloser.
- Candidate close sets its original closed fact before awaiting the unclaimed
  binding close; retry still reaches that binding. Claim transfers its original
  binding once. Code binding take/retain/dispose and ResumeSource's different
  closed-before-await behavior remain exactly their original programs.
- Header IO checks path membership before Managed root_observed.set, then revision,
  the original loader mode, and revision again. Owned reads remain read_only;
  discovery remains blocking=False/create_lock=False; legacy strict reads keep
  default loader flags. No stronger rooted, ownership or mode rule is inserted.
- Strict list refuses any partial/bad/over-budget/ambiguous authority. Duplicate
  detection precedes workspace visibility; Managed permits only the exact original
  same-file two-view case. Only the selected sources' routing cache is replaced.
- Display discovery may omit bad rows, retains exact completion/omission flags,
  and downgrades row availability for incomplete or duplicate observations. It
  never populates strict routing cache or promises authority from a display row.
- Discovery keeps submitted/admitted thread receipt, real completed Future,
  cancellation stop and shielded wait until native work ends. Worker BaseException
  becomes its original None result; caller cancellation has original precedence.
  A cancelled to_thread Task is not substituted for actual read completion.
- Managed observation retains a probe before native inspect, checks exact store
  and root identity and marks unknown observation as seen. Failed close remains
  retryable; active reads/probes remain owned by the worker and are never freed by
  catalog close. Root creation is the same one-shot grant, never missing-root
  inference or permission to recreate a previously observed root.

## Source, Original Oracles And Failures

The complete original1964-source frame and13 tracked non-source package resources,
source copies, full external snapshots, manifests, independent reviews, raw
observations and failures are retained in workspace runtime
`coding-convergence-continue/a80-hosted-catalog`. Runtime and value observers guard
original origins/bytes and use immutable original expected values. No candidate is
used as an expected-value oracle.

The first builder used an incorrect AST body offset and failed before output;
targeted statement selection corrected it. Initial mypy used incomplete candidate
package paths and found relative-import diagnostics plus three real missing-property/
scope-type findings. Full-package R3 and final R5 scoped mypy pass five sources,
without Any or ignores. Cold import verifies the actual Code classes, MRO and docs.
Unchanged definitions retain original byte layout rather than unrelated full-file
formatting; new and changed programs keep readable formatting. All costs remain.

The original source snapshot initially copied frame sources without13 JSON/Markdown
package resources. This caused the original full AgentSession scene to fail in
setup. The resources were copied from the same clean baseline and SHA guarded.
An intervening narrow replacement scene was explicitly abandoned and excluded from
all final oracles; the complete original AgentSession create/prepare/append/resume
scene was restored and passed. This is a fixture correction, not Product behavior.

Value capture initially failed on builtin reflection and malformed operation IDs.
The failures remain. Final31 original observations passed15.02s; original31 plus
source guard passed32/4.75s. Raw full Header bytes in three actual canonical create/
retry paths are stable. Expected SHA256 is
`2b064ad331a52c80b2b4101b31327b9544cef528e59af99b59fd284397dd9c9f`.
R5 compares the same31 plus full1966-source/13-resource/import guard:32/12.11s.
Two private effect hooks move from the old Code revision alias to the actual
Transcript helper; inverse AST proves all other observer inputs/assertions unchanged.
The first Root external-test command loaded no conftest and rejected the safety
option before running tests; its log remains separate from these passing results.

The portable value fixture is deterministically converted only from those original
raw observations. Per-test private inputs replace a shared fixed directory.
Normalization computes allowed scope/create identities from frozen original
formulas and actual inputs, then maps only those exact strings to virtual-input
values. Unknown/wrong hashes remain visible. Full Header bytes retain every byte
apart from declared input strings/derived IDs; normalized length/SHA are recomputed.
All31 scenarios remain. Original portable31/4.22s and R5 portable31+guard32/5.07s
pass; an anti-mask check plus original source guard separately pass2/9.45s. Wrong
scope hash, Header identity/fingerprint and extra payload are not erased. Portable
fixture SHA256 is
`70abc6eee9d60668f8aee769b021c5f88fa266b7d7fbbcacab476d0407f42271`.
Original raw bytes, source guards and conversion/input/hook proofs remain external.

Runtime's35 scenes reuse complete original functions from five consumer modules,
plus explicit legacy wrapper/cleanup/commit windows. Early captures retain30/5 and
34/1 setup failures: missing selector parameter, lingering scandir fault affecting
source guard, unsafe writable input ancestors and missing package resources. Inputs
use private /tmp and a private per-case Home; managed test RunLease remains on the
mandated disk root. The full restored35 capture passes107.77s. Fixed replay first
exposes six path-derived or ordering differences; normalization validates original
Managed continuity, exact title-to-session relation and input-derived filename
order, preserving full raw traces. Concurrent identical create inputs have two
actually observed native completion orders. Finite allowed variants retain complete
traces and require the identical-input precondition; no trace sorting or event
removal is used. R5 compares all35 with full source/resource/origin guard:35 passed64.68s.
The portable draft directly reuses current original test modules rather than
copying five test files; it passes the same35 on R5 (63.10s).

The five unchanged original consumer modules pass88/57.84s at baseline and the
same88 pass26.90s on R5, with private input fixture and isolated Home. The actual
busy/reopen catalog child inherits selected source PYTHONPATH. One contention
helper explicitly uses the unchanged original journal owner to hold a real lock;
it does not execute changed catalog programs. Parent source/import guards do not
claim a separate guard inside every helper subprocess.

## Actual Verification And Acceptance

Actual installed five-source nonimport AST and flattened import facts match R5.
Project isort removes one blank line in each of four sources; the new abstract
property header is formatted over two more lines and trailing empty Code lines
are removed after the actual run. Its full
execution AST remains identical to R5; that layout-only change does not trigger a
second154-node run. All costs are included below. Actual66 immutable observations plus the same88 original consumers
pass154 (38.07s), with no skipped nodes. Original five consumer source files remain
byte-identical. Durable probes retain reviewed execution AST after import/layout
formatting, and both immutable fixtures retain their original-only bytes.

The154-node process did not load the external shadow source tracker. Its explicit
actual-src command, installed-source/MRO proof and running assertions are distinct
from R5's in-process full shadow guard. A separate actual cold import checks all
loaded Product origins plus complete1966 sources and13 original resources. That
separate proof is not described as an in-process154 tracker or a child-process guard.

Existing Hosting/import boundaries record172 passed/1 failed (94.68s). The exact
optional-file inventory lacked two baseline files and the new private integration.
The original1964-source replica with exact original node/config/docs independently
reproduces its two old omissions (1 failed/0.29s). Only that existing AppHost RHS
adds the three actual paths; AppServer's36 paths and other predicates stay. Inverse
RHS transformation restores the entire test module AST, including its original8
test functions and this node's7 assertions. The same failed node passes after the
fact repair (0.86s); the passing172 are not rerun or combined into a fictitious full
173-node green run. No gate, selector, scanner or dark consumer is expanded.

Additional actual AppHost shutdown/Continuity-reopen and discovery-to-interaction/
recovery consumers record14 passed/1 failed (52.73s). The failed unreadable case
still patched a non-exported loader alias that moved out of Code. The unchanged
original node passes on the frozen original source (3.76s). Only its hook target
moves to the actual Transcript jsonl_file loader, which the shared reader imports
at the operation point. Reversing that one string restores the entire module AST;
all five functions,29 asserts, three failure inputs and the original10s timeout
remain. The same failed node passes after retargeting. The original14 passing
nodes are not rerun or reported as a second complete15-node green batch. Production
sources remain unchanged throughout this test-hook maintenance.

Three independent reviewers accept responsibility/reuse, runtime/failure and
public data/compatibility for the actual scope after reading the terminal records.
Actual five-source mypy and touched-source/probe Ruff pass. New shared sources and
two probes pass format. Original unchanged definitions retain baseline layout;
the existing fact file also keeps its original single scan-expression format hunk.
Source dependency graph
freshness and the existing changed-path/document checks have separate records.
No broad or native planned route is claimed executed merely from plan selection.

The complete custody fixture is stored as deterministic gzip:5,948,968 original
JSON bytes become129,303 container bytes. Decompression is byte-identical to the
immutable original fixture, SHA256
`36eb7f62716a7a459a80f94ccf30ae2a8bc352507a424b537b7ef65e237d7f46`.
No trace or value is reduced to a digest-only summary. Reversing the container
path/load expression restores the reviewed probe AST; one existing idempotency
node verifies the new container reader separately. That is packaging verification,
not another full35/154 run or new default coverage. The original raw JSON stays
in external evidence for direct review.

## Cost, Acceptance And Remaining Work

| Production scope | Before | Actual | Change |
| --- | ---: | ---: | ---: |
| Code hosted catalog | 1216 | 931 | -285 |
| Code Managed catalog | 301 | 228 | -73 |
| Existing Transcript StoreAdmission | 479 | 586 | +107 |
| Transcript canonical source | 0 | 101 | +101 |
| Existing AppHost integration private program | 0 | 739 | +739 |
| Entire Coding /430 files | 114864 | 114506 | -358 |
| Entire system | 647041 /1964 sources | 647630 /1966 sources | +589 /+2 |

The full actual frame independently confirms these counts. R5 was Code-352,
Core+947/system+595 before four isort blank-line and two property-header differences; full-file formatted
R2's Code-234/system+839 also remains in external history, not credited as algorithm
reduction. Actual Code-358/Core+947/system+589 includes all format costs. All
other1961 original sources are unchanged. Every generic/Protocol, hook, constructor,
public typed forward, narrow history guard and format/import cost is included.
This is responsibility migration and common header-program convergence, not net
system source deduplication. The original scanner/factory/writer mechanisms were
already shared. The increase separates application coordination and physical
custody from Product identity/compatibility rather than hiding a Code-exclusive
implementation in another directory.

Responsibility/reuse, runtime/failure and compatibility reviewers accept the actual
scope with the documented finite limits. Root records bounded acceptance under the
existing delegated Goal. The optional-module inventory is factual reconciliation;
scanner roots, assertions, test nodes, workflows and gate coverage do not expand.
No persisted migration is required. Rollback restores all five production sources
and the exact inventory fact together.

This does not prove every scheduler interleaving, native Windows authority or full
history/Continuity/Session publication. Full P1–P4 remains partial and the Goal
active, with99506 physical Coding lines still above15K. No
irreducible lower bound is established. KD003 stays unimplemented; KD011/A33 stay
user-pending and unadopted. Remaining ordinary Worker, startup/Plugin/Session,
hosted/Continuity and entry/history responsibilities continue under the full Goal.
