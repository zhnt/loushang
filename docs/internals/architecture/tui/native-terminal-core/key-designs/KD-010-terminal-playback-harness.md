# KD-010: Terminal Playback Harness

## Purpose

Make terminal behavior testable without relying only on manual `loushang --tui`
sessions.

## Design

The playback harness drives the runtime with scripted events:

- terminal size changes
- key events
- paste events
- product events
- streaming chunks
- tool lifecycle updates
- surface open/close events
- abort, steer, and follow-up actions

Each step records:

- current logical lines
- previous rendered lines
- changed line range
- viewport top and previous viewport top
- logical and hardware cursor rows
- terminal operations
- repaint kind and repaint reason, if any
- clear-scrollback policy and whether a clear-scrollback operation was emitted

The harness must support golden logical-line assertions and operation-level
assertions. Operation assertions are required for flicker, resize repaint, and
clear-scrollback policy tests.

`loushang.tui.playback_suite` owns the generic layer above individual playback
runs: neutral scenario registration, name/tag selection, elapsed-time results,
and artifact dispatch. Products retain their scenario catalogs, product hosts,
and CLI entrypoints while importing this suite directly or through a temporary
compatibility alias.

## Test Obligations

- resize replay reproduces the same logical lines and operation classes
- resize replay can assert full recompose plus resize repaint
- resize replay can assert default clear scrollback and policy-disabled resize
  clear scrollback
- streaming replay never appends one transcript block per token
- diagnostics are deterministic enough for failing test output
