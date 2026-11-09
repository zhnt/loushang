# Product Plugin Approval Coordination Convergence

- Authority: bounded design and implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness PluginDeclarationHost, CapabilityComponentHost and
  ProductPluginCompositionAssembly; explicit Product issuers retain authority.
- Baseline: `2dfe75fee12a9bcf04f2160577fccdcd7348ed6a` (A72 audit, A71 production).
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream synchronization claim.

## Complete Programs And Original Owners

A73 replaces two complete Coding operation bodies: Definition approved-resolve and
Activation approval through Session input binding. Existing Host.resolve owns the
sole Resolver/Coordinator composition and accepted-token handoff, but previously
had no explicit Product issuer round. Existing ComponentHost owns current authority
validation and durable activation lifecycle, but had no whole selection-to-host
construction or explicit issuer/record-validation operation. Assembly already owns
candidate order and exact Session input binding. These gaps justify minimal methods
on those original owners, rather than another service, manager or state machine.

- PluginDeclarationHost.resolve_for_product constructs the original journal,
  realm, evaluator and Host, calls the original resolve, asks the explicit issuer
  about each pending subject in order, retains the original `isinstance` record
  check and subject validation, and calls resolve at most once more. Denied/rejected/still-pending results retain
  the original Product error codes and diagnostic notes.
- CapabilityComponentHost.from_product_selection constructs the original journal
  and immutable trust/current authority/policy readers, then the original Host.
  Constructor recovery still precedes all candidate work, including zero candidates.
  approve_selected_activation asks the explicit issuer and validates type, exact
  raw journal record, subject, approved disposition and AVAILABLE state in order.
- ProductPluginCompositionAssembly.approve_and_bind_session_inputs iterates the
  original candidates and calls its unchanged bind_session_inputs only after all
  approvals validate. It creates no Provider, admission start or Graph publication.

Original resolve/preflight/finalize and all existing Core method bodies remain
AST-identical. The PLC1B contract and Host class documentation distinguish the new
explicit coordination driver from the sole resolve composition path. The issuer
still signs decisions, the original journal persists them, and later admission,
consumption, Provider preparation and Graph/Session publication retain their owners.

Code keeps exact public values, signatures, Protocols, Product id/labels, paths,
required writer capabilities, actual error type and Resume type/open admission.
Its two existing helper signatures now bind pure configuration and delegate.
Small getters preserve late issuer/error/Resume/distribution lookup points; none
perform IO orchestration. No Code history loader, write program or thick stage
callback is injected into Core. This is not a new total Product controller.

Builtin, Product and legacy Capability already shared this Code program before
A73; there were no separate Base approval loops to deduplicate. Continuity has a
different issuer/validation/error contract and is not forcibly merged. Existing
Catalog, Graph, Registration, cleanup and publication reuse earns no new credit.

## Failure, Data And Timing Contract

The original workspace/scope labels, journal paths, format versions, JSONL bytes,
record types and authority rules remain exact. No schema migration is introduced.
Definition does not gain Activation's exact-record check. Activation deliberately
uses raw journal.snapshot(), not the lifecycle/Resume open wrapper. Replacing that
call with a convenient lifecycle API would strengthen the old contract and change
failure ordering, so it is not done.

- Journal creation precedes realm, distribution, Resume context and Host creation.
- Definition preserves first resolve, pending subject order, original `isinstance`
  record/subject validation, then second resolve and diagnostic propagation. Empty pending subjects
  still cause the second resolve; no retry loop is added.
- Activation preserves journal/readers before original constructor recovery, then
  each subject, issuer, raw snapshot, record/subject, disposition, availability,
  decision id and final bind. Zero candidates still construct/recover and bind {}.
- Failure or synchronous interruption at a later issuer preserves earlier durable
  decisions. No rollback, invented cleanup, cancellation swallowing or additional
  consume is introduced. Exceptions and their cause/context/notes remain unchanged.

Admitted immutable plan/seed fields are passed at the thin wrapper boundary, so
some pure field reads occur earlier than before. The compatibility claim concerns
the actual frozen DTO/admitted values, not arbitrary proxy getters, side effects
or concurrent mutation that violates those value contracts.

## Immutable Evidence And Limits

All1958 production source hashes and complete four original sources were frozen
outside Product before edits under a73-product-approval-closure. Capture guards
compare actual old bytes with those copies. The committed fixture contains the
original full commit/source hashes and56 complete observations: result/identity,
exception graph plus code, ordered trace, issued DTO values and exact JSONL bytes.
Expected objects were not generated by the replacement. The durable explicit
probe has no capture mode and is outside normal test discovery.

The observer uses actual Definition/Activation journals, validated subject/record
DTOs and physical files. Resolver, evaluator, Provider, authority, constructor
recovery, binding and Resume ports are controlled. A frozen seed is populated
without upstream package admission to isolate the boundary; this is not proof of
actual Definition/Provider execution. Four named cancel cases inject KeyboardInterrupt,
proving synchronous BaseException propagation and first-record retention, not
Task.cancel/asyncio cancellation. raw-resume-error injects OSError at the original
raw snapshot position; Parents returns None, so it does not prove real Resume
enrollment or contextual recovery. Original Resume/Graph consumers provide their
own separately scoped evidence.

Preserved preliminary attempts: the first observer used invalid empty Plan refs
and produced52 setup failures; its accompanying original SDK suite had13 passes
and one transcript_writer:unsafe failure. The next52 observations exposed an
invalid deterministic Definition journal constructor argument, so they were not
adopted as expected evidence. A corrected52 plus one original SDK guard passed53;
then code values/four interruption cases were added under old source guards and
57 passed (56 observations plus the same guard). One mistyped SDK node produced
no test run and is retained. No failing observation was overwritten or derived
from the candidate to make comparison pass.

The old SDK smoke unsafe rejection is before A73 changes. Directory admission
requires safe owner/mode on every ancestor; this machine has /home owned by nobody
and /home/dev/lsspace mode0775. Those paths fail the original predicate. No ancestor
permissions, Product safety policy, normal runtime path or capacity floor changed.
This is a retained full SDK smoke limitation, not a successful regression claim.

Final terminal evidence, using the managed wrapper, mandated private disk runtime,
worktree src PYTHONPATH, outside-sandbox execution and original not-live/host selectors:

1. Fixed original56 on unchanged old production:56 passed in3.62s.
2. Replacement fixed56 plus original Host/ComponentHost/Session-input/Coding LSP,
   Arch, default Base package and owner consumers:138 passed in129.84s.
3. Original execution/activation Resume-context consumers, real foundation Plugin
   Session graph/unload, Assembly mismatch/alternative-provider nodes and unchanged
   unique Host/Coordinator architecture assertions:31 passed in13.84s, with one
   existing allowed_tool_names=None warning. Those owner tests supply only their
   stated scenarios; the probe itself still has the limits above.

No original consumer, assertion, parameter, selector or architecture gate was
changed. The selections overlap existing coverage and are not added into a novel
scenario count. Four-source mypy, five-source Ruff/format, dependency freshness,
existing change-plan generation, documentation invariants and diff checks pass.

## Whole Cost And Acceptance Boundary

| Production owner | Before | After | Delta |
| --- | ---: | ---: | ---: |
| Coding capability composition | 1887 | 1780 | −107 |
| Existing DeclarationHost | 74 | 179 | +105 |
| Existing ComponentHost | 797 | 935 | +138 |
| Existing CompositionAssembly | 1638 | 1667 | +29 |
| Whole system | 645173 | 645338 | +165 |

Coding totals430 files/117008 physical lines; system1958 sources/645338 lines.
All other1954 source hashes remain identical. Costs include new neutral Protocols,
configuration/getters, error mapping, thin compatibility adapters, method and class
documentation and formatting. No source was moved or generated to hide Coding
cost. +165 is necessary bounded coordination/configuration cost accepted under the
user's Nov9 moderate-growth rule; it is not system net deduplication.

All three independent direction/prototype and actual-code views found no bounded
responsibility, runtime or compatibility blocker. Terminal consumer evidence closes their runtime condition; the stated probe and
SDK limitations remain. This slice
only closes the A72 approval coordination candidate. Full P1–P4 and <=15K remain
active; the current gap is102008 lines. KD003 is unimplemented; KD011/A33 retain
original user-pending boundaries. No new gate, discovery route, workflow, platform
or merge-blocking condition is introduced.
