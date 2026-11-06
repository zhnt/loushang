# Default Session preparation

Date: 2026-11-06. Branch: `feature/gui-default-session`, based on `lane/gui`
plus the accepted task dependency `feature/gui-cross-platform-bridge` at
`0ceba7711`. No shared integration branch has been changed by this task.

## Scope and internal acceptance

The implementation agent (Codex), acting within the delegated GUI integration
scope, accepts the following bounded design. The native desktop prepares a
default Session before publishing an empty Mux's initial snapshot. It reuses
AppHost's existing authenticated `mux/member/open` operation, controller
ownership, admitted scopes and durable continuity identity. No new AppHost wire
operation, backend default policy, stored format or CI gate is introduced.

The creation context comes from the validated, authenticated connection record:
prefer its `cwd` scope, otherwise use its admitted home scope. The WebView cannot
invent a path, product or scope fingerprint. A default continuity ID derived
from the persistent Mux ID is stable across retries. Existing members always
take precedence; a new controller attachment and membership-barriered snapshot
are acquired after publication. The server remains the owner of session identity
and persistence. This is native launch orchestration, not a React mount effect.

The local GUI creation input now permits an absent `sourceSessionId`; omission
uses the same admitted context. Existing selected-Session requests preserve
their scope and remain compatible. Empty-state creation failures are displayed
instead of silently returning, and users can retry. Normal new-session actions
continue to allocate a fresh continuity identity.

## Automated verification

- GUI `check:full` passed; final frontend check passed 88 tests, including empty
  and populated creation, failure feedback/retry, and selection after replacement.
- The real local AppHost integration passed: an empty Mux initially has zero
  Sessions; preparation produces one; reconnect retains the same Session identity
  and Mux revision; admitted scope/fingerprint match the backend record.
- Existing real-AppHost Session creation, submit/reply, conflict/reacquisition,
  idle cancellation and independent peer checks passed.
- Shared Rust probe tests and all-target Clippy with warnings denied passed.
  Scope tests cover workspace preference even when home appears first, and a
  home-only record. Python Ruff passed.

## Native Linux UI verification

The release build passed. A standalone real AppHost was started with an empty
Mux (zero members, revision 1), without manually seeding a Session. Launching
the native GUI automatically created and selected one Session (revision 2).
Through actual UI input and the Send button, the configured
`openai / gpt-6.1-sol` model returned `GUI-DEFAULT-SESSION-OK`; the GUI displayed
successful completion. No mock provider or playback client was used.

Closing and reopening the GUI against the same running AppHost retained the
same Session and conversation history, with one member and unchanged Mux
revision 2. Clicking New Session in the real GUI created and selected a second
Session, displayed the creation confirmation, and advanced Mux revision to 3.
The GUI and owned test AppHost then exited normally with status 0.

The local screenshot is `gui/test-results/default-session/first-session-reply.png`.
Windows/macOS and a persisted AppHost service restart were not exercised by
this acceptance run. Provider-failure presentation is outside this fix's scope.
