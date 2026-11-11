# A128 retained Session plan invocation custody

Authority: bounded implementation review under COD-RESP-GOAL-002.
Design status: accepted for the specified retained invocation program.
Implementation status: bounded batch accepted; full Goal remains partial.
Method: local clean archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e.
Full COD-RESP-GOAL-002 P1–P4 and logically Coding-owned <=15K remain active/partial.

The original SessionWorkRuntime submits/accepts/runs/records one prepared plan.
The hosted MethodInvocation separately retains its submission Task and operation
recording/cancellation/join lifetime. The candidate keeps that complete program
in a private same-instance base in the original HarnessWork Session integration.
There is no extra runtime, manager, state object, Task, lifecycle callback pool,
new protocol, or Code/AppService/Method reverse dependency. Core's existing
SessionControlPort supplies only the existing session_id contract via a type-only
import. Constructor state remains on the original MethodInvocation object.

Direct submit_plan is already used and remains the actual execution authority;
it cannot replace the caller's retained Task and reconciliation. Backend-wide
SessionWorkRuntime.settle/dispose would cancel unrelated active operations and
cannot replace per-operation settlement. GoalInvocation has different batch,
initialization and deadline semantics and is not merged through flags.

Code retains preparation, AppService control/outcomes, current Coding step and
Session cleanup. One immediate pure three-result factory is called at original
Outcome construction points to preserve exception windows. It performs no IO
or Method/step/session work. Original four methods and complete task program
leave Code together. Original step then Session suffix remains in Code without
a new protocol: step clear only after success; control clear after Session success.

Task creation failure is outside Work-error mapping and closes the coroutine
before not_submitted is marked. Child checkpoint precedes submit_started; session
ID is read in that child. Cancel flags, actual Task cancellation, recording latch,
active ownership rather than textual status, per-operation cancel/wait and final
recording check are preserved. A cancellation failure can be suppressed if the
original recording check establishes unavailable; this is inherited private
policy, not a proposed general Work policy or broader cleanup guarantee.

Actual cost: Code203->124 (-79), original Core928->1049 (+121), whole system +42.
This is responsibility convergence for one consumer, not algorithm deduplication
or whole-system shrinkage. No new production modules or PR gates are proposed.
Private MRO/qualnames and additional coroutine frames change; public call/data
contracts and real consumed instance fields are retained. The three cold import module sets are exactly unchanged (Core182, Code972,
hosted Method1037); no cold improvement is claimed.

## Verification and acceptance limits

Original consumers76passed/1Windows skip and Work54passed. Original guarded
observer capture2passed; fresh original replay31passed/1capture skip/3setup
deselected, covering30 cases plus source origin. There are20 fault cases and23
confirmed fired faults. It uses actual asyncio Tasks, WorkRun/Recording and
AppService Outcome values; Work/Session/native ports are controlled. Three real
Task modes cover child cancellation before entry, outer cancellation retaining
child, and settlement waiter cancellation retaining child. These complement the
original real Session cancellation, append-failure, cleanup retry and close graph
regressions. Outcome-constructor faults verify the preserved exception windows.

Actual combined161passed/2skip/3setup deselected with2 existing record_property
JUnit warnings:130 original tests +30 observations +source origin, not161 new
cases. Manual portable probe31passed; matrix/canonical/observe AST unchanged,
gzip2683B restores byte-exact old113855B expectation SHA
`78f0758bc141188088815dee021f5b3fba4f62cc04c74f9557b14851c4dc2b01`.
The412-line probe is manual-only, with no generated automatic PR route. Tests,
fixture bytes and documentation are separate costs, not production reductions.

Original architecture tests191passed without gate changes. Ruff/mypy3 and
package dependency freshness passed; graph already includes the existing
HarnessWork->Harness edge. Other1967 source and13 resource SHAs are unchanged.
AI was selected by existing full fallback: lint, mypy79, catalogs/imports and935
tests passed/2skip/7deselected, but make check-ai exited2 because overall
8461/9415=89.87% and runtime6745/7526=89.62% are below90. All79 AI source SHAs
and each executable/covered line set equal A126 (which directly matched A117).
This existing failure is reported, not waived or fixed. Other fallback suites
and native Windows/platform/provider/live coverage are not claimed complete.

Three independent design and actual reviews have no remaining batch blocker;
root accepts this responsibility change within the existing Goal authorization.
Evidence, source frames, old captures, exact commands, XML, cold module sets and
review reports are outside Product in
`coding-convergence-continue/a128-method-invocation-custody`.
Current Coding112052/system648391, Goal deltas−25703/+13597, remaining97052 to15K.
The separate stale remaining-audit aggregate was334 lines high; it was corrected
from all430 source SHAs/28 groups with no production reduction credit. LMUX close
was examined and rejected as a next extraction because existing owners already
contain its transaction, while confirmation/output durability barriers remain
necessary glue. Windows retirement full closure is a candidate, not accepted
implementation. P1–P4, Hosting/construction/AI coverage gaps, KD003 unimplemented
and KD011/A33 user-pending/unadopted boundaries remain.
