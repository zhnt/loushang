# Real AppHost read-only integration

Status: first B2 integration evidence, 2026-09-14. Not live GUI publication or
production native adapter acceptance.

Run from the repository root on Windows:

```text
uv run python scripts/gui/check_apphost_integration.py
```

This opt-in script constructs the real Coding continuity attempt, AppHost
catalog/runtime, AppService, HostedLocalRuntimeV1, authenticated LocalAppServer,
and real Coding session factory. It uses temporary private connection records,
continuity and session stores. Installed-code admission pins are test-owned;
model streaming is explicitly forbidden and no work is submitted. It does not
connect to an existing user application, read user settings, or start a TUI.

The existing Rust connection probe authenticates to that actual server and
reads a real execution snapshot and two event batches before detaching. A Python AppClient controls a
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

- This is native adapter evidence, not yet connected-window acceptance.
- It verifies idle snapshots and empty event batches, real controller arbitration, graceful client EOF
  cleanup and explicit deployment settlement. It does not prove hard process
  termination cleanup or every failed-snapshot/disconnect race in the real host.
- Bounded membership rechecks and local attempt fencing now run in the probe.
  A native CLI continuous-idle-read case also verifies cooperative stop and
  detach against the real AppHost. The desktop uses that same reader and can
  publish the barriered initial snapshot; ongoing event publication, submission,
  approval and takeover are not added.
- Model-free real Coding sessions do not establish live provider execution.
- Nonempty contiguous event batches and invalid batches are covered by the scripted
  fixture; metadata/content watermark separation is additionally unit tested in Rust.
- This remains an opt-in GUI integration check, not a TUI/Harness default gate.

Next verify the native window against a real launched host, then publish complete
validated event rounds with gap-triggered resynchronization. Keep live facts
separate from offline fixtures.
