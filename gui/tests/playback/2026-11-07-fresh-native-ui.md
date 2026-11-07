# Fresh native GUI UI acceptance

Date: 2026-11-07. Tested `lane/gui` commit
`c817c590f6a114212aa82ea0608696f953fe854e` in dedicated worktree
`feature/gui-fresh-ui-smoke`. Linux desktop, X11 backend under the current desktop
session. No product source changes were made.

## Fresh build and automated UI checks

Created a new worktree without `node_modules`, `dist`, or Rust target artifacts.
Ran `npm --prefix gui ci --no-audit --no-fund`, then
`npm --prefix gui run build`: successful native release build, 2m 37s.
The executable SHA-256 is
`f5b8dd20e5a0965ff7ac08a6bedddc98ec4adad29d553469cc9b5da4b6fcba79`.
Dependency download caches may be reused; no previous native executable or
compiled target tree was reused.

- `npm --prefix gui run check`: TypeScript check and 89 tests in 14 files passed.
- `npm --prefix gui run test:layout`: 23 browser tests passed in 44.2s, including
  responsive layouts, language changes, preserved drafts/focus and shell panels.
  These tests include fixture/simulated-native coverage; the separate desktop
  acceptance below used a real standalone AppHost and real provider requests.

## Real desktop procedure and results

Started `uv run python -m loushang.coding.cli.mux` with explicit endpoint
`workspace`, application ID `gui.fresh-ui`, and isolated state beneath
`/tmp/gui-fresh-ui-it03rp8s`. Created the empty mux `fresh-ui` through the CLI.
Launched this worktree's newly built native executable with
`--loushang-app-record-root /tmp/gui-fresh-ui-it03rp8s/connection`
and `--loushang-mux-name fresh-ui`.

All subsequent session creation, settings changes, input and sending were actual
window operations using AT-SPI actions and system keyboard events. No frontend
mock, injected bridge response, direct model invocation or fabricated transcript
was used. The AppHost used saved provider settings without a test model override.

1. The GUI connected and automatically created the first default session.
2. Clicking New Session created a second session and selected it. Its ID was
   `20eae84e9fa48bf9d193ce29fc9e3519095be27885c8146117f9b4ac2df951b1`.
3. Typed a draft, opened Account menu → Settings, selected English, and closed
   settings. The shell changed language and the draft was unchanged.
4. Clicked Send for `只回复 GUI-FRESH-UI-1107，不要调用工具。`. The actual reply
   was `GUI-FRESH-UI-1107`; the UI reported `Execution succeeded`.
5. Kept the GUI open and stopped the AppHost through its CLI. The window showed
   `Connecting to AppHost…` while retaining the transcript. Restarted the same
   state; the window automatically reconnected, retained both sessions and the
   real messages, and kept the second session selected.
6. The service changed from `75f6053cb5e971d390948498dd4f15e9` to
   `97fb47bc57b52956b42978075bfea5ed`; the session ID stayed unchanged.
7. Through the same restored input box and Send button, submitted
   `只回复 GUI-RESTORED-UI-1107，不要调用工具。`. The actual reply was
   `GUI-RESTORED-UI-1107`, again with `Execution succeeded`. Both turns were visible.
8. Closed the window using its close button, then relaunched the same binary.
   English persisted and the GUI connected. It selected the first session;
   selecting the second session from the sidebar restored both completed turns.
9. Opened Work Dock and collapsed the sidebar. Inspected the actual screenshot:
   transcript, composer and send control remained visible without panel overlap.
   The compact Account menu still opened Settings. Switched back to Chinese.
10. Closed the test window through its UI and stopped the isolated AppHost.

## Remaining UI observations

- The model selector displays `No model · Effort unavailable` even though real
  provider calls succeed. This is a model-state presentation/capability gap;
  this run does not establish its deeper cause.
- Relaunching the GUI selects the first session rather than the last selected
  one. History remains accessible by selecting the original session.
- Immediately after AppHost restoration, the existing historical-session message
  says it is read-only and needs runtime activation. Sending successfully activates
  the runtime and replaces that snapshot with the ongoing conversation.
- Workspace details and Work Dock task capability show unavailable placeholders
  for this AppHost. Opening the panels works; full workspace/task functionality
  is not established by this test.

This is a Linux native UI smoke test, not a repository-wide or cross-platform
test claim. It covers successful text requests, not tool approval, interruption,
long-running execution or provider-failure semantics.

## Local evidence

Ignored artifacts in `gui/test-results/fresh-ui/` contain build/check/layout logs,
actual accessibility snapshots and screenshots `live-success.png`,
`restored-success.png`, and `panels.png`. Screenshots were visually inspected.
The private test state is retained for follow-up; no existing workspace history
was cleared.
