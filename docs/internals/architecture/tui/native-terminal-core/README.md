# Loushang TUI Native Terminal Core

## Status

Draft for `feat/loushang-tui-native`.

## Purpose

This directory defines the target architecture and requirements for rebuilding
`loushang.tui` as a native terminal TUI core.

The goal is not a fullscreen terminal app and not a prompt-toolkit application.
The goal is a terminal-native framework with deterministic visual stability:

- native terminal operation without requiring fullscreen alternate screen
- a runtime-owned bottom frame for composer, surfaces, and status
- a single terminal writer
- full logical screen composition with line-level differential rendering
- resize full repaint when that is the most stable path
- resize stability with clear scrollback enabled for resize by default
  and overridable by policy
- renderable and UI part boundaries that product adapters and extensions can
  use safely

## Core Mental Model

A native terminal TUI does not draw on a blank canvas. It runs inside the
terminal the user is already using: shell output may already exist above it, the
user may scroll through history, the window may resize at any time, and model
streaming can happen while the user is editing input. The runtime therefore
manages only the part of the terminal that belongs to the current TUI as a
predictable logical screen. Each render tick builds the complete current UI,
compares it with the last UI that was successfully flushed, and writes only the
terminal operations needed for the next frame. This is the foundation for
avoiding flicker, duplicated rows, cursor drift, input corruption, and damaged
scrollback.

## Intended Audience

This document set is written for three groups:

- TUI core implementers who need render-loop, terminal, input, and layout
  invariants
- product adapter implementers, especially `loushang.coding.ui`, who need to
  project product state into generic TUI records, UI parts, surfaces, and intents
- extension authors who need to understand public UI boundaries without direct
  terminal access

## Document Map

- [Architecture Decisions](./architecture-decisions/README.md)
- [Functional Requirements](./functional-requirements/README.md)
- [Non-Functional Requirements](./non-functional-requirements.md)
- [Layout Requirements](./layout-requirements.md)
- [Scenarios](./scenarios.md)
- [Traceability Matrix](./traceability-matrix.md)
- [Glossary](./glossary.md)
- [Glossary Chinese Terms](./glossary-zh.md)
- [Key Designs](./key-designs/README.md)
- [Render Framework Spec Inventory](./render-framework/README.md)
- [UI Part Spec Inventory](./ui-parts/README.md)
- [Display Record Spec Inventory](./display-records/README.md)
- [Renderer Spec Inventory](./renderers/README.md)
- [Terminal UX Reference Alignment](./reference/terminal-ux-feature-alignment.md)
- [Testing Strategy](./testing-strategy.md)
- [Render Performance Contract](./render-performance-contract.md)
- [Development Slices](./development-slices.md)

Later design passes may add:

- `migration-plan.md`
  - concrete API specs under `render-framework/`
  - concrete UI part specs under `ui-parts/`
  - concrete record schemas under `display-records/`
  - concrete renderer specs under `renderers/`

## Source Notes

The initial product interface requirements were extracted from the older
`feat/loushang-tui` design branch. That branch targeted a prompt-toolkit + Rich
implementation. This native terminal core keeps the useful user-facing behavior
and drops the old implementation choice.

The runtime stability requirements use these terminal UX goals as input: native
operation, full logical-line rendering, previous-line line-level diffing, append
updates, resize repaint, overlay-before-diff composition, cursor marker mapping,
synchronized terminal flushes, an ordered screen region stack, paste markers,
editor wrapping, undo/kill-ring behavior, transient pending/working/editor/status
regions, surfaces, selectors, markdown, thinking blocks, and tool execution
records.

The guiding tradeoff is: deterministic visual stability first, native terminal
history preservation best effort. Resize defaults to full repaint with clear
scrollback so row mappings are rebuilt deterministically. Steady-state streaming
still preserves scrollback through append and changed-line updates, and clear
scrollback can be disabled by policy for deployments that prioritize shell
history over resize stability.

## Boundary

`loushang.tui` is a generic TUI framework. It must not know coding product
concepts such as sessions, models, tools, slash command semantics, diagnostics,
provider policy, or Harness conversation contracts.

`loushang.harnesstui` composes product-neutral Harness conversation contracts
with generic TUI records, widgets, surfaces, and interaction. It may depend on
`loushang.harness` and `loushang.tui`, but never on Coding.

Coding feature-local interaction, presentation, and policy adapters interpret
raw Coding semantics. `loushang.coding.ui` is the final product shell: it owns
runtime composition, concrete Coding surfaces, and terminal bindings rather
than reusable conversation behavior.
