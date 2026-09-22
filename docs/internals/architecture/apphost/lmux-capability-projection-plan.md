# lmux shared conversation capability projection

Status: accepted implementation slice after three-perspective design review;
implementation and its code review pending.
Authority: implementation plan under the accepted
[lmux design](../drafts/lmux-managed-service-design.md#63-复用单元完整-harnesstui-会话视图不只是-tui-控件).

## Boundary

The shared view needs immutable availability facts, not a new authority or wire
protocol. Preserve `ConversationInputCapabilities` and its existing Embedded
input behavior. Add a neutral presentation value beside the existing conversation
input policy/state; Hosted must not import a local Product to fill missing facts.
Do not introduce another task owner, RPC, permission check or terminal loop.

Each presentation entry has a closed operation name, availability
(`available`, `read_only`, `unavailable`), and a closed reason code. The adapter
supplies a snapshot for its current opaque binding key. The key is equality-only
view identity, not a controller token. A retained snapshot for another key must
resolve as unavailable; it cannot authorize a request.

Initial operations: transcript, submit, steer, follow_up, interrupt,
approval_details, approve, deny, image_paste and product_commands. Transcript
and available approval details are read-only. Distinguish protocol
support from current eligibility: an available operation means the UI can offer
an intent, not that policy will approve it or that execution will succeed.

## Adapter behavior

Hosted derives the key from the exact attachment, controller generation, member
and Session tuple already used by its action binding. No active member, required
snapshot, closing or membership transition disables member actions. Rebinding
recomputes the matrix; never transfer an old approval-presented receipt.

The admitted v1 AppClient supplies text submission/steering/follow-up/interruption
protocol support. Existing runtime input policy still chooses running-submit
behavior. Approve eligibility needs the current pending interaction and the
existing exact-content presentation receipt; the matrix never substitutes for
that receipt. Deny requires a current eligible pending interaction but not a
presentation receipt. Details remain independently readable while approval is
disabled for lack of presentation, so the user can obtain that receipt. Never
hide deny or the details entry merely because approve is unavailable.
Unsupported image and Product commands remain unavailable
with explicit protocol-unavailable reasons, as required by the accepted scope.

Embedded projects only facts supplied by its existing composition/input ports.
Keep older bindings working when they do not supply the optional richer matrix;
absence of the richer value is not evidence of additional capabilities. Do not
probe Product objects from shared view code or change clipboard ownership.

For the current Coding composition, declaration-only input and operation groups
are available through the existing resolver metadata, without resolving a Session.
Interrupt requires lifecycle and queue groups. The standard clipboard profile
declares its entry point, not clipboard contents or model image support. Local
commands come from the bound Coding surface/dispatch, not its completion list.
The current local approval port has no pending/presented/outcome eligibility
snapshot. Mark these entries `unavailable/not_projected` (projection unavailable),
not unsupported or no-interaction, and do not use them to disable the existing
local approval surface. `not_supported` is reserved for an explicit negative
declaration. Only Hosted currently filters suggestions through its complete
protocol-derived projection; Embedded retains its existing input/surface routing.

## Consumers and invalidation

Expose the current matrix in shared screen state and use it in operation/help
presentation. Hosted command suggestions and unsupported notices consume the
same facts, avoiding a second independent availability table. Existing explicit
target capture, scope/controller checks, approval receipt checks, bounded action
admission and server-side authorization remain mandatory.

Invalidation includes Tab selection, attachment/controller replacement, Session
replacement, snapshot-required state, pending membership mutation and close.
Recompute the small matrix synchronously from current state when presenting or
offering an operation, without a separate capability cache or asynchronous
publisher. Screen projection cache keys must include changing eligibility facts,
not just transcript revision. If later implementation introduces retained
publication, both the binding key and the current eligibility revision must
match; binding equality alone is insufficient. In particular, changes to approval
content, its presentation receipt, snapshot-required, membership or closing can
invalidate eligibility inside the same binding. An old result must not republish
availability in either the same binding or a new one. Local text editing remains possible where already supported even
when remote submission is unavailable.

## Acceptance

- Validate closed values, duplicate operations and immutable snapshots.
- Project exact member identity and explicit unsupported reasons.
- Show transcript read-only without granting any remote mutation.
- Reject retained snapshots after Tab/attachment/Session replacement.
- Invalidate availability without a transcript change when close, membership,
  snapshot or pending approval facts change.
- Retain an old available snapshot, change approval content or closing with the
  same binding and transcript revision, then offer the old value: current shared
  presentation/help/suggestions must remain derived from the new state, and
  must not restore old approve/submit eligibility.
- Keep approval receipt and stale action/result rejection regressions intact.
- With an unpresented pending interaction, offer deny and read-only details,
  explain that approve requires presentation; enable approve after the exact
  details were presented. Rebinding or changed content invalidates approval
  eligibility. Verify both presentation and command suggestions.
- Preserve Embedded input/clipboard behavior; test bindings with and without the
  richer presentation value.
- Test rendered help/suggestions as well as values, so a disconnected matrix
  cannot satisfy acceptance.

This slice does not add image transport, structured tool cards, usage transport,
GUI or cross-machine connections, and does not replace full PTY/performance
acceptance or the final goal-wide three-perspective review.

## Design review resolution

Architecture: preserve the distinction between no richer matrix (legacy adapter)
and an explicit unavailable entry; no additional authorization is inferred.
Interaction: split approval details, approve and deny, preserving their different
presentation-receipt requirements. Lifecycle: same-binding eligibility changes
invalidate prior observations, not merely attachment replacement. These local
design findings are resolved above; runtime and final goal acceptance remain open.
