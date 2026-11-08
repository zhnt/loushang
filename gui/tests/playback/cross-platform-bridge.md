# Cross-platform native bridge evidence

Date: 2026-11-06. Base: `lane/gui` at `5208ee256`. Task branch:
`feature/gui-cross-platform-bridge`.

## Implementation and internal review

The implementation agent (Codex), within the delegated GUI integration scope,
accepts this bounded design: compile the same AppClient and Tauri live commands
on desktop platforms; isolate private-record admission behind `record_native::read`.
No AppHost protocol, stored record format, workspace, settings or history changes.
No CI trigger, required gate or runner changes.

The reference contract is AppServer's existing
`src/loushang/appserver/_posix_local_record.py` and `_local_record_files.py`.
The POSIX implementation uses rustix owned descriptors and no unsafe Rust. It
opens the root without following its final symlink, opens the record relative
to that descriptor, checks effective owner, owner-only permissions, regular
file type and single link, bounds reads to 8192 bytes, and rechecks identity,
permissions and modification metadata. Nonblocking opens reject FIFOs without
hanging. The existing Windows handle/ACL implementation is moved unchanged.
Platform selection exists only at this native-file port and target dependencies;
connection, authentication, Session control and reconnect remain shared.

The desktop launcher and connection probes use host executable naming through
one helper instead of Windows-only entry points. Default launch remains the
explicit offline fixture; admitted native launch arguments select the live path.

## Linux observations

Ubuntu 26.10 x86_64, Node 24.22.2, npm 11.19.1, Rust 1.98.1:

- `npm --prefix gui run check:full`: passed, including 87 frontend tests,
  production Web build, Rust formatting and both native feature configurations.
- `npm --prefix gui run build`: release executable built successfully (2m 37s).
- Shared Rust probe unit tests, all-target probe Clippy with warnings denied,
  Python Ruff and the 9 lightweight documentation invariants passed.
- `uv run python scripts/gui/check_posix_record.py`: 13 Python/Rust admission
  parity cases passed, including unsafe permissions, symlinks, hardlinks,
  oversized files, directory-as-record and FIFO rejection.
- `uv run python scripts/gui/check_connection_lifecycle.py`: 8 scenarios / 16
  connections passed, including authentication/hello stalls and cancellation.
- `uv run python scripts/gui/check_attachment_lifecycle.py`: 20 scenarios passed,
  including event gaps, membership changes, deadlines and watch cleanup.
- `uv run python scripts/gui/check_apphost_integration.py`: real local AppHost
  Session creation, authoritative snapshots, native submit and synthetic reply,
  controller contention/reacquisition, idle stop, disconnect and owner shutdown
  passed. No external provider call.
- A bounded native launch using the desktop acceptance helper's isolated runtime
  connected the actual release GUI to AppHost, rotated the local listener,
  observed reattachment, triggered a synthetic execution after the GUI's first
  execution snapshot, and verified that the independent peer remained readable.
  The test then terminated only its own GUI and closed its isolated runtime.
  This does not establish normal window-close, visual layout or input acceptance.

Evidence exposed two existing acceptance-helper assumptions. Event probes had
waited for every terminal content event, although production replaces state with
authoritative snapshots that can cover those events. The probes now require a
successful snapshot containing the submitted prompt; the Python integration also
requires the actual synthetic reply, nonempty event publication and contiguous
round sequence. The synthetic model is registered explicitly in its local catalog.
The desktop helper now waits for the GUI's execution binding after attachment;
attachment count alone does not mean its first snapshot has completed.

## Limits

Windows ACL code is preserved, but this revision was not executed on Windows.
macOS uses the same POSIX implementation but was not built or run here. These
are outstanding platform acceptance checks, not feature-disable branches.
Real-provider interaction, normal window close, OS scaling and manual input
remain unverified in this run. Existing live Workspace/Changes/Tasks/Agents
capability gaps remain outside this connection change.

Local logs are retained in `gui/test-results/cross-platform-bridge/` (ignored).
These explicit commands remain opt-in and do not increase PR gates.
