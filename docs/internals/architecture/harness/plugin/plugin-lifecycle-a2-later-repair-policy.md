# PLC9 A2 Later-Phase Repair Policy

## Status and owner boundary

- Tracking: #509. This document is the policy for extending the existing
  bounded Coding Package repair actions; it does not itself enable another
  repair route.
- The Package lifecycle journal owns the operation phase and attempt epoch.
  Product owns the admitted route, source and lease preflight, selected
  admission, and handoff. Quarantine, staging set, publication, retention pin,
  and Desired State remain with their existing owners.
- A1 Desired State repair and A2 Package repair keep different operation IDs,
  actor checks, journals, and commands. A Package commit is not an enabled
  installation; a Desired State commit is not a Package publication.

## Current executable boundary

`PackageLifecyclePhase` has twelve phases, from `accepted` through
`committed`. `CodingPackageRepairClientV1` currently exposes eleven exact actions
through one fenced Product runtime. The action is chosen by the operator and
checked again by the corresponding Product owner; it is never inferred from a
free-form operation ID or an A1 explanation.

| Durable Package phase or state | Existing Product action | Proof required before a new effect |
| --- | --- | --- |
| An unstarted selected attempt, including `classified` or `acquiring` only while its owner proves no effect | `repair-unstarted` | Original request/classification, current Source, exited prior admission, exact selected attempt, and no acquired or later effect |
| `acquired`, `inspecting`, `extracted` with interrupted root work | `repair-acquired` | Exact bounded acquisition and quarantine evidence, old attempt cleanup, Source and lease recheck, and no pin, staging, publication, or handoff |
| `resolving_closure` | `repair-resolving` | Exact node set, closure evidence and cleanup debt; no later transaction effect |
| `closure_verified` before a transaction pin | `repair-verified` | Verified closure and Source evidence, old attempt cleanup, and no pin or later effect |
| `transaction_pinned` before a staged node | `repair-pinned` | Complete verified plan, still acquired matching transaction pin, Source, Store and exited leases; preserve the same attempt |
| `transaction_pinned` with staged nodes | `inspect-staging`, then `repair-staging` | Exact checkpoint and all node receipts, pin, Source, Store and selected admission; resume only missing nodes |
| `set_published` | `inspect-published`, then `repair-published` | Exact published set, transaction pin, Store, Source, and owner-bound replacement admission; no second publication |
| `committed` with incomplete handoff | `repair-handoff` | Exact committed Package status and Product handoff identity; settle or report the handoff outcome without replaying publication |
| `retryable_failure` in the operation retry domain | `repair-retryable` | Exact retryable status, original request and selected admission; the phase-specific owner still decides whether retry is safe |
| Terminal `rejected`, `cancelled`, or fully settled `committed` | No new repair effect | Return the terminal owner evidence; do not create a fresh attempt through repair |

These rows describe the currently exposed Coding POSIX actions, not a
cross-platform guarantee or a permission to skip any owner-specific preflight.
The runtime and owners remain authoritative when an observed phase and action
disagree. `repair-retryable` does not bypass the phase-specific owner checks.

## Policy for later-phase expansion

1. **Classify the durable state first.** Read the exact Package request,
   status, attempt chain, failure retry domain, and any selected Product
   admission. Also inventory quarantine cleanup, transaction pin, staged set,
   published set, handoff, and Desired State references. Missing or corrupt
   owners are an indeterminate result, not proof of absence.
2. **Choose one effect boundary.** Before pin acquisition, a new attempt may
   restart only after old quarantine effects are durably cleaned. With an
   acquired pin, preserve the attempt and adopt an admitted runtime; never
   reacquire the same dependency as a fresh transaction. After publication,
   only resume the exact committed set and handoff. Once Desired State commits,
   its own CAS and repair owner decide the next step.
3. **Bind the decision durably.** A repair proposal must include operation ID,
   original request fingerprint, attempt epoch/revision, Product/Store/scope,
   Source digest, old and proposed admission identities, and the exact
   phase-specific pin/checkpoint/publication/handoff fingerprint. The Package
   owner selects it by CAS. An orphan Product proposal has no effect authority.
   Supersession needs proof that the selected prior admission has exited.
4. **Reopen under mutation custody.** Immediately before a physical effect,
   Product rechecks epoch admission, owner revisions, Source bytes, Store and
   cleanup inventory, lease liveness, and phase-specific references while
   holding the required guards. A stale review or mismatch refuses before
   mutation. Replaying the winning decision is idempotent; a losing decision
   cannot act after a newer one wins.
5. **Keep terminal claims precise.** Success means the relevant owner reports
   its durable terminal state. A committed Package with pending handoff is not
   a settled installation. A cleanup retry is not a new install. Do not report
   a disabled or removed Plugin from an incomplete process, GC, or data-deletion
   step.

## Remaining acceptance gates

The existing actions are individually bounded; a general A2 repair policy is
not yet implemented. Before promoting one shared operator decision over all
phases, add a read-only phase classifier with explicit `repairable`,
`retryable`, `terminal`, and `indeterminate` results. It must name the exact
owner and evidence still missing, and it must never expose a mutation handle.
Then make the selected action use the existing Product owner path above. Do not
introduce a generic rollback or a second Package writer.

Acceptance requires process-crash and reopen cases at every phase edge and at
each proposal/CAS/effect/terminal-return boundary. Cover changed Source,
owner, scope, Store bytes, checkpoint, pin, handoff, live or superseded lease,
cleanup debt, and concurrent repair or GC. Repeat on the supported POSIX
Product routes, then establish a separate Windows Product checkpoint and
retained Windows CI evidence before advertising Windows repair. CLI, SDK,
optional RPC, and TUI must return the same pathless decision and refusal code
for the same owner evidence.
