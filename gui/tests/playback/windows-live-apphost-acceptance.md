# Windows live AppHost desktop acceptance

Updated: 2026-10-08. Status: **real AppHost reconnect, controlled composer and
normal desktop exit passed after integration with `main`**.

This record is narrower than the B1 fixture checklist in
[windows-acceptance.md](windows-acceptance.md). It covers one visible Windows
launch against an isolated, real AppHost and the cleanup observed after a normal
window close, plus the native connection behavior under a rotated local listener
and connection record. It does not cover approval or attachment mutations,
Windows display scaling, or the complete fixture workflow.

## Launch

The release executable was started through:

```text
npm --prefix gui run accept:live-native
```

The launcher created separate `gui-desktop-acceptance` and
`desktop-acceptance-peer` muxes with real Coding Sessions. The GUI received the
connection-record root and GUI mux name only as native process arguments. The
model transport is a deterministic process-local synthetic stream. It emits one
fixed assistant response for presentation acceptance and performs no network or
provider call. The launcher registers this synthetic model in its isolated
Session model catalog so the model selector and active identity agree.

## Observed window

A human-observed screenshot in the acceptance thread showed all of the
following in the running native window:

- the top connection badge said `Connected`;
- the sidebar banner said `Live AppHost · read-only` and the account footer said
  `Live · read-only`, with no fixture-data label or playback control;
- the real Coding Session projection was selected;
- the composer said `Read-only live connection`, its access label was
  `Read-only`, and its submit control was disabled;
- Pull requests, Scheduled, Plugins, Changes and Subagents were unavailable;
- the missing Workspace capability was represented explicitly rather than
  inferred from transcript text; and
- at the observed 1440 × 721 window size, the environment surface did not cover
  the composer or the central Session surface.

The native mux selector is deliberately not exposed to the WebView, so the UI
shows the Coding Session label rather than `gui-desktop-acceptance`.

The live sidebar groups attached Sessions under the accepted mux display name.
The environment panel shows the accepted Product, scope, scope fingerprint,
Session, mux and service identities. It still reports Workspace details as
unavailable because the AppHost attachment does not supply a Workspace facet,
repository root or version-control fact.

On 2026-10-08, after merging the latest `main` into the GUI lane, Windows
accessibility inspection of the running native window observed `Connected`,
`Live AppHost · controlled`, the `faux · no-network` model choice, and a completed
execution. The transcript contained a user prompt and the deterministic assistant
reply. This inspection did not obtain a screenshot or exercise Send/Interrupt
through automation; the user prompt was entered while the window was open.

## Exit lifecycle evidence

The window was closed normally. The launcher then verified:

- the GUI process exited with code 0;
- the GUI mux controller was released and could be acquired again;
- the shared AppHost remained accepting; and
- the independent peer Session remained snapshot-readable.

The generated, non-secret run result is written to
`gui/test-results/live-apphost-desktop/result.json` and is intentionally ignored
by Git. The launcher shuts down the isolated AppHost only after these assertions.

## Ongoing events and reconnect evidence

The GUI lane integration check drives a deterministic local Coding execution
through the real AppHost. The Rust adapter observes nonempty contiguous event
rounds, refreshes every member snapshot, rechecks mux membership, and publishes
the round atomically. The frontend rejects an epoch, sequence, member, cursor,
revision or snapshot-watermark mismatch without applying a partial round.

During the visible desktop acceptance the launcher closes only the real local
AppServer listener, waits for its attachments to settle, and starts a replacement
listener that publishes a new private connection record. It then verifies that:

- the GUI rereads the record and authenticates to the replacement listener;
- a new GUI attachment appears without restarting the shared AppHost;
- the GUI accepts a fresh authoritative snapshot before reporting connected;
- the independent peer Session remains snapshot-readable; and
- normal window close releases the replacement attachment.

The result evidence records `transportReconnectObserved` and
`freshSnapshotReattached` as true. The updated run additionally records
`liveProjectionTriggered` after one deterministic real Coding execution. No
send, approval or other mutation is automatically replayed.

The subsequent controlled-composer implementation keeps the attachment,
controller generation and member identity in native Rust. Send and Interrupt
are serialized through the same authenticated connection that owns the
attachment. Automated real-AppHost integration verifies that a desktop submit
reaches the real Coding `AgentSession` and its deterministic response streams
back. The 2026-10-08 visible run confirms a user prompt and reply in the live
transcript. Interrupt interaction still needs a visible run.

## New Session control

The live sidebar now enables **New Session** only while the native AppHost
connection is authoritative. The command stays in native Rust and sends
`mux/member/open` through the controller attachment; the WebView receives only
the created Session identity. The first slice inherits the selected Session's
product, discovery scope and scope fingerprint and uses a newly generated
continuity identity.

Opening a member changes the mux projection, so the adapter treats the old
attachment as invalid, reconnects, installs a replacement snapshot and selects
the new Session only after that snapshot contains its identity. The real-AppHost
integration check creates the Session through the production Rust adapter and
then independently verifies the two-Session authoritative snapshot. A visible
button-click run remains pending.

## Live presentation projection

Validated authoritative snapshots are projected into transcript records, one
bounded streaming draft, Session status and a separate expandable execution
summary. The summary exposes only execution-contract facts: identity, state,
revision, interrupt request, source observation, final cursor and transcript
truncation. It is not presented as a Task. Inactive Session snapshot advances
set an unread marker, while disconnected Sessions display their last state as
stale without continuing the running animation. Tests cover streaming-to-final
replacement, two-member rounds, inactive-Session unread state and malformed
transcript/execution rejection.

## Still pending

- Native interaction at Windows 125% and 150% display scaling.
- Normal/maximized/restore and sidebar-drag interaction coverage beyond the
  single observed wide window.
- Visible Interrupt interaction against the deterministic AppHost launcher.
- Initial model/reasoning selection and first-message submission as part of the
  New Session creation flow.
- Accepted live contracts for Workspace, Changes, Tasks, Subagents, approvals
  and attachments.
