# Real AppHost integration

Status: B2 event, resynchronization and existing-Session control evidence,
updated 2026-09-22.

Run from the repository root on Windows:

```text
uv run python scripts/gui/check_apphost_integration.py
```

This opt-in script constructs the real Coding continuity attempt, AppHost
catalog/runtime, AppService, HostedLocalRuntimeV1, authenticated LocalAppServer,
and real Coding session factory. It uses temporary private connection records,
continuity and session stores. Installed-code admission pins are test-owned.
The control case uses a deterministic process-local model transport and submits
one prompt; it makes no network provider call. It does not
connect to an existing user application, read user settings, or start a TUI.

The existing Rust connection probe authenticates to that actual server and
reads a real execution snapshot and two event batches before detaching. The
`event_probe` additionally observes a deterministic, model-local real Coding
execution through the same native AppClient used by Tauri. It publishes only
complete event rounds followed by authoritative snapshots and reaches a
`turn_completed` event. A Python AppClient controls a
different mux in the same application and remains usable afterwards. Another
client's ownership of the selected GUI mux rejects the Rust contender; that
owner can still read its snapshot, then detach and permit Rust to reconnect.
Closing the Python owner without detach releases its controller: a bounded
observer reacquires with a higher generation, detaches, and Rust connects again.
The shared host remains accepting. Finally the explicit test owner closes the
deployment and verifies that its cleanup is settled.

The check also runs `snapshot_probe`, which consumes the exact native adapter
compiled by Tauri. It verifies the emitted service instance, Mux identity,
ordered member/Session identity and one execution snapshot against the real
AppHost. The serialized publication contains neither `attachmentId` nor
`controllerGeneration`; those controller capabilities remain native.

The `control_probe` then uses that same production Rust adapter to attach and
submit on one authenticated connection. AppHost routes the prompt into the real
Coding `AgentSession`; the deterministic assistant stream returns through the
normal execution event and snapshot path. The probe verifies acceptance plus
nonempty event publication. This caught three integration errors that isolated
codecs could not: controller authority is connection-bound, controller
generation is numeric on the wire, and request IDs increase across snapshot,
control and event operations on the connection.

## Integration defect found

The isolated probe previously sent textual request IDs (`attach`, `snapshot-0`,
`detach`). Payload codecs accepted them, but AppServerConnectionV1 additionally
requires positive decimal request IDs increasing across both protocol families
on one connection. The real server closed the connection before replying.

The bounded Rust sequence uses `1` for attach, followed by increasing decimal IDs
for snapshots, event reads and detach (including failure cleanup).
The twenty scripted attachment scenarios also assert these
IDs. Raw controller-generation serialization remains unchanged and lossless.
No server contract or runtime implementation was changed to accommodate GUI.

## Limits and next slice

- The native adapter, connected-window lifecycle and bounded existing-Session
  submit/interrupt path are covered; display scaling and broader mutation remain
  separate work.
- It verifies idle snapshots and empty event batches, real controller arbitration, graceful client EOF
  cleanup and explicit deployment settlement. It does not prove hard process
  termination cleanup or every failed-snapshot/disconnect race in the real host.
- Bounded membership rechecks and local attempt fencing now run in the probe.
  A native CLI continuous-idle-read case also verifies cooperative stop and
  detach against the real AppHost. The desktop uses that same reader to publish
  the barriered initial snapshot and complete validated event rounds. On a
  transport failure or rejected round it establishes a fresh connection epoch
  and replaces state from a new authoritative snapshot. Approval and takeover
  are not added. Submit is never automatically replayed; after a response loss,
  the adapter queries the stable submission ID on a new attachment.
- The deterministic Coding session proves AgentSession routing and streaming,
  not authentication to or behavior of a network AI provider.
- Nonempty contiguous event batches and invalid batches are covered by the scripted
  fixture; metadata/content watermark separation is additionally unit tested in Rust.
- This remains an opt-in GUI integration check, not a TUI/Harness default gate.

Next add an opt-in provider-backed acceptance case and the separate New Session,
approval and attachment contracts. Keep live facts separate from offline
fixtures and never infer mutation results across reconnect.
