# Windows live AppHost desktop acceptance

Date: 2026-09-21. Status: **initial read-only desktop slice passed**.

This record is narrower than the B1 fixture checklist in
[windows-acceptance.md](windows-acceptance.md). It covers one visible Windows
launch against an isolated, real AppHost and the cleanup observed after a normal
window close. It does not accept ongoing events, mutations, Windows display
scaling or the complete fixture workflow.

## Launch

The release executable was started through:

```text
pnpm --dir gui run accept:live-native
```

The launcher created separate `gui-desktop-acceptance` and
`desktop-acceptance-peer` muxes with real Coding Sessions. The GUI received the
connection-record root and GUI mux name only as native process arguments. The
model transport was a fail-fast synthetic transport and was not invoked.

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

## Exit lifecycle evidence

The window was closed normally. The launcher then verified:

- the GUI process exited with code 0;
- the GUI mux controller was released and could be acquired again;
- the shared AppHost remained accepting; and
- the independent peer Session remained snapshot-readable.

The generated, non-secret run result is written to
`gui/test-results/live-apphost-desktop/result.json` and is intentionally ignored
by Git. The launcher shuts down the isolated AppHost only after these assertions.

## Still pending

- Native interaction at Windows 125% and 150% display scaling.
- Normal/maximized/restore and sidebar-drag interaction coverage beyond the
  single observed wide window.
- Publication of validated ongoing event rounds and reconnect/resynchronization.
- Accepted live contracts for Workspace, Changes, Tasks, Subagents and all
  mutation controls.
