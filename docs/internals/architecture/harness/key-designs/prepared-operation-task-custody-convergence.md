# Prepared Operation Task Custody Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness SessionLifecycleRuntime and
  PreparedSessionLifecycleOperation; Coding retains Resume domain admission.
- Baseline: `20033880e9033a4174c907d53e4a0c21fc071c4f`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream synchronization claim.

## Complete Responsibility And Reuse

A75 converges the complete opt-in retained preparation lifetime: preparation Task,
original candidate binding, delivery Task, abort, cancellation settlement, ordered
drain and cleanup-debt retry. The same original SessionLifecycleRuntime now owns
five state values previously in Coding: preparation Task set, delivery Task map,
retained operation set, cleanup-debt list and bound event loop. The old Code
collections and cancelled-task helper exit; no aliases or duplicate ledgers remain.

The existing _prepare_candidate already owns transition locking and construction.
PreparedSessionLifecycleOperation already owns prepared/consuming/consumed/abort
state, rollback, its original abort Task and failed cleanup retry. Those programs
remain AST-identical and are directly called; no operation engine or new manager
is introduced. Their existing APIs did not retain preparation/delivery Tasks or
cross-operation cleanup debt, which is the actual gap closed here.

SessionExecutionScope was considered and rejected for this purpose: it owns
quiesce/settle/release stages, external invocation interruption and close-task
reconstruction, with different error and cancellation policy. A generic gather
or failure-first join would likewise change the original three waiting programs.
Moving the whole Code prepare coroutine behind a task wrapper would leave native
candidate/debt coordination in Code, so that option was also rejected.

The new prepare_retained_candidate directly invokes the original native operation,
retains its specific cleanup failure, binds its result, records the original
operation, constructs the public result, and owns Task shielding/cancellation.
Its three Code adapters are values only: deferred immutable Transition construction,
nonlocal operation assignment plus original assertion, and actual Code DTO
construction. None loads history, disposes a Session or coordinates IO. The
Transition factory, including str(session_file), runs inside the original Task
and narrow try window; it is not evaluated early in the outer entry.

Code retains history-view/current actor/epoch/admission policy, original domain
continuation construction, native host binding/fencing policy, actual public DTO
and first-input dispatch. Root closed state remains one Code fact. The original
Root fence -> drain -> Session disposal -> dependent factory close sequence stays
unchanged; drain is not automatically added to ordinary Lifecycle dispose.
Default prepare_restore/import users do not enroll in these opt-in ledgers.

## Failure, Ordering And Compatibility Contract

- Loop binding stays after view/factory/selection admission, before consumed
  pruning and pending checks, and before synchronous owner-check validation.
  Pending checks intentionally exclude delivery Tasks, exactly as before.
- Only await _prepare_candidate (including its request value construction) is
  inside the cleanup exception catch. The original debt object is retained.
  bind_operation assigns the caller's original local and asserts the continuation,
  then Core records the operation, then the public DTO factory runs. A failed
  DTO construction therefore still leaves the original candidate to abort.
- Preparation cancellation cancels the same Task, repeatedly shields until done,
  and aborts a result if cancellation was suppressed and it completed successfully.
  If that late abort fails, its cleanup error can replace the caller cancellation;
  the operation stays available for drain retry. No blanket cancellation rule is
  substituted for this original behavior.
- Consume retains closed/root/membership/delivery-pending checks in their original
  order. Its cancellation cancels the delivery Task, observes its eventual error
  and rethrows the original cancellation; final removal of the delivery entry is
  unchanged. Successful consume leaves the operation until the next idle prune.
- Abort keeps only the original Root identity check, then cancels/joins a current
  delivery and aborts the native operation. It does not gain closed, loop or set
  membership checks; a same-Root wrapper around a foreign operation can still abort.
- Drain first checks an already-bound loop, snapshots preparation and delivery
  references, cancels all, joins preparation Tasks, settles delivery Tasks, aborts
  retained operations and retries debts in list order. A cancelled drain waiter
  with an unfinished preparation rethrows immediately, unlike preparation joining.
  Each reference is removed only after that stage succeeds; a failure stops later
  cleanup and preserves the same objects for retry.

Two private structural Protocols express only the real result.abort and
cleanup-debt.retry_cleanup contracts. The narrow cast after catching the supplied
exception class preserves the actual original object; Python typing cannot express
an exception class intersected with that structural retry protocol. The sole real
binding supplies CodingResumeContinuationCleanupFailure, which already implements
retry_cleanup. No runtime validation or new error policy is added.

CodingRuntimePreparedResume's complete class, three own fields, annotations and
methods remain identical. The native PreparedSessionLifecycleOperation class is
also unchanged. Existing entry signatures and persisted bytes/schema do not
change. Five private Root bookkeeping fields are deliberately removed: searches
of src/examples/scripts found no external production reader, while UI still calls
the preserved _consume_resume_preparation entry. Seven original test observations
now read the same objects from their actual Lifecycle owner. Inverse-mapping only
those paths makes the entire original test module AST identical, including97
assert/raises and all parameter/identity predicates. Arbitrary old __dict__ or
private coroutine-source reflection is not a new compatibility promise.

## Immutable Execution Evidence And Limits

All1959 production source hashes and complete original Code/Lifecycle/cleanup
sources were frozen outside Product under a75-prepared-operation-custody. Capture
guards compare actual old bytes; fixture source/observer hashes and all37 raw
observations match that baseline. The durable explicit probe has no capture mode
and does not expand normal test discovery or PR gates.

The probe uses actual asyncio Tasks, Task.cancel(), repeated cancellation and
original Lifecycle/PreparedOperation objects, plus the actual public Code wrapper
and cleanup-failure objects. Root/domain/Session/Product/cleanup effects are
controlled ports. It does not prove actual Writer, Model transport or filesystem
behavior; real consumer tests below supply their own scoped evidence.

The completed factory is a controlled already-finished Future on Python3.11,
not Python3.12 eager_task_factory. Rejected coroutines are observed unclosed at
original failure return, then explicitly closed by the observer; Product was not
changed to conceal that old behavior. The bind-error case intentionally substitutes
a native prepare result without running build, isolating the original assertion
window rather than claiming it is an admitted real domain path.

The first37 plus original SDK guard passed38. Before freezing final expected data,
the foreign-root case was corrected to call the actual Root guarded entry and the
drain-error case changed from ordinary cancellation to an actual preparation error
during drain. The second37 plus guard passed38; both raw captures remain intact.
Expected objects come exclusively from the unchanged original implementation.

Terminal evidence uses the managed wrapper, mandated private disk runtime,
worktree src PYTHONPATH, outside-sandbox execution and original non-live/host
selectors:

1. Original real Resume continuation and default Lifecycle consumers:55 passed
   in110.00s, before migration.
2. Durable fixed37 on unchanged production:37 passed in4.37s.
3. Replacement same37 plus original55:92 passed in114.72s.
4. Original first-input/UI/Product/Transcript boundary consumers:35 passed in
   174.86s. These selections are not a novel summed scenario count and prior
   evidence is not relabeled as a broader run.

Two-source actual mypy and three-source Ruff checks pass. Both original production
files already failed whole-file format checks at baseline; their unrelated layout
is preserved, rather than generating broad reformatting and claiming its line
changes as responsibility reduction. The new explicit probe is formatted.
Dependency freshness, nine documentation invariants, the existing change plan
and diff checks pass. No workflow, route, runner, platform or merge condition is added.

## Whole Cost And Remaining Goal

| Production owner | Before | After | Delta |
| --- | ---: | ---: | ---: |
| Coding runtime | 917 | 829 | −88 |
| Original Session Lifecycle | 957 | 1117 | +160 |
| Whole system production | 645560 | 645632 | +72 |

Coding430 files/116791 physical lines; system1959 sources/645632 lines; all1957
other old source hashes stay equal. Every new Protocol, state field, type cast,
request/value binding, thin entry, documentation and formatting line is included.
This is responsibility migration with minimal necessary custody on the original
owner, not net system deduplication or a second session manager. Validation costs
are separate: explicit probe618 lines, JSON fixture4163 lines, seven original
private observation paths replaced with zero net test lines.

Three independent direction/prototype and actual-code views find no bounded
responsibility, runtime or API blocker; final boundary evidence and static closure
complete acceptance. Full P1–P4 and <=15K remain active with101791 lines above the
limit. This does not adopt KD011's pending Transcript Continuity provider/navigation
or A33's Windows publication design; no dependency on them was found. KD003 bytes
import remains unimplemented, and other startup, Worker and Product responsibilities
retain their inventory obligations.
