# Windows B1 acceptance handoff

Date: 2026-09-14. Status: **pending native acceptance**.

This is an offline fixture delivery, not a real AppHost connection. Keep the
delivery on `lane/gui` until its remaining acceptance obligations are closed.

## Automated evidence

The current source passed 27 Vitest tests, nine Chromium layout scenarios
(36 panel states), 43 CI selector tests, six documentation checks, and Actions
syntax validation. Chromium device pixel ratios 1.25 and 1.5 are not evidence
of Windows display scaling. Generated browser evidence lives in
`gui/playwright-report` and `gui/test-results/layout`.

## Native checklist

Build with `pnpm --dir gui run build:fixture-native`; launch
`gui/src-tauri/target/release/harness-gui.exe` without a Vite server.
Record the executable SHA-256, OS scaling, window dimensions and screenshots
with the results. Do not infer a pass from a successful build or live process.

- [ ] The standalone window renders the offline fixture and reports the Rust
  invoke/event canary, without a localhost connection error.
- [ ] Menus and window controls occupy one title row. Dragging the empty title
  region moves the window; double-click and maximize/restore work.
- [ ] Minimize and restore from the taskbar work. Close exits this GUI window.
- [ ] Ctrl+B and the sidebar icon toggle the same sidebar. Dragging its edge
  resizes it within 200–420 px; reopening preserves the chosen width.
- [ ] At normal and maximized sizes, environment and work panels do not cover
  the transcript or composer; their content remains scrollable.
- [ ] Repeat at Windows 125% and 150% display scaling. Verify aligned reading,
  playback and composer edges, and accessible send/interrupt hit targets.
- [ ] Advance playback, inspect Task/Subagent and Review, interrupt, and submit
  a subsequent fixture run. Session switching preserves each draft.

The current agent environment does not expose the `node_repl` entry point
required by the computer-use skill. Native UI actions above have therefore not
been performed by the agent. A human acceptance result or a supported native
automation environment is required to close these items.

## Next contract boundary

GUI-C1 prepares cross-language contracts, test vectors, numeric fidelity,
profile/capability compatibility and rejection behavior. It may proceed beside
B1, but it is not the snapshot/events/send/interrupt real-service milestone.
That connection is GUI-B2 and must reuse the existing detachable AppHost
application and its accepted execution profile. See
[the engineering plan](../../../docs/internals/architecture/drafts/gui-engineering-bootstrap-plan.md).
Neither the fixture protocol nor passing this checklist establishes C1 or B2.
