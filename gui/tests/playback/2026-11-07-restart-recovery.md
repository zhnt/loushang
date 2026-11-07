# GUI restart recovery repair

Date: 2026-11-07. Base: `lane/gui` at `17fa92920`.
Delivery: `feature/gui-restart-recovery`.

## Change and review

The production Rust source decoder now accepts the existing canonical optional
`submissionMode: "execution"` field emitted by restored writable Coding sessions.
Omission remains valid. Explicit null, legacy, unknown values and unrelated
unknown fields remain invalid. Frontend validation, independent contract probes
and generated bridge shapes agree with the Python codec.

Acceptance recorded by the implementing agent within the delegated GUI repair
scope: reviewed against `appserver/protocol/codec.py` and its existing optional
field behavior. This consumes an existing protocol field; it does not introduce
a server schema revision, storage migration, platform split or CI gate.

## Validation

- `npm --prefix gui run check:full`: passed; 14 frontend test files, 89 tests,
  TypeScript checks, Rust formatting, Clippy and native checks.
- `npm --prefix gui run check:contract`: passed; 70 accepted and 112 rejected
  vectors across Python, Rust and TypeScript.
- Generator unit tests: 5 passed; generated artifacts verified.
- Production adapter tests through `snapshot_probe`: 22 passed, including
  strict optional-field handling and preserved transcript projection.
- `uv run python scripts/gui/check_restart_recovery.py`: passed twice.
  This opt-in test starts the real standalone Coding CLI AppHost, prepares a
  default session through the production Rust adapter, stops and restarts the
  same state twice, verifies execution submission mode after restoration, and
  checks stable session/mux identity and byte-identical transcript files.
  Each service instance must differ. No provider request or mock service is used.
- Native release build: passed on Linux.
- Change-aware plan selected GUI and docs; documentation checks: 9 passed.
  Ruff and diff whitespace checks passed. No repository-wide suite was run.

## Real native window acceptance

Launched the built `harness-gui` with `GDK_BACKEND=x11`, pointing at the real CLI
AppHost under `/tmp/gui-recovery-ui-1107/connection`, mux `restart-regression`.
The test directory was restricted to the current user. No developer workspace
history or settings were reset.

With the GUI window open, stopped the AppHost normally, observed stale session
state and `正在连接 AppHost…`, then restarted the AppHost against the same
application and transcript directories. The GUI automatically returned to
`已连接`. Service instance changed from `eeefcd0eb6859cc630cd43054ae36c5b`
to `7efa3e74a9b92ca242aec8d98884b3dc`, while the session remained
`2628ac785519ade182561b729980a51bf4685b45acba276516e66880da8776ee`.

Used the actual window close button via AT-SPI, relaunched the native executable,
and again observed `已连接` with the same restored session and service. Local
screenshot evidence: `gui/test-results/restart-recovery/reconnected.png`
(ignored build/test artifact). Connection state and identities were also read
from the actual accessibility tree, not a mocked frontend.

## Limits

This validates restored attachment, snapshot delivery, automatic reconnect and
GUI relaunch. The fresh isolated session has no prior provider conversation;
byte preservation here covers its persisted session file. The restored UI also
shows the existing historical-session activation message. No new provider turn
was submitted, so this run does not establish successful model execution after
restoration. Windows/macOS native acceptance was not run. Failure presentation
semantics remain outside this repair, as requested.
