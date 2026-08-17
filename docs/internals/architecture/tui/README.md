# Loushang-TUI Architecture

本目录收纳 `loushang-tui` 子系统的架构文档。

## Current Design Track

Current target design:

- [Loushang TUI Native Terminal Core](./native-terminal-core/README.md)

`native-terminal-core/` is the target whitebox design track for the
`feat/loushang-tui-native` branch. It defines the next `loushang.tui` runtime and
component model. It is not a separate loushang subsystem.

## Historical Material

Older TUI architecture documents are preserved under:

- [History: v1 prompt-toolkit/Rich](./history/v1-prompt-toolkit/README.md)

Those documents describe the previous prompt-toolkit/Rich implementation track
and v1 API release gate. They are useful for migration context, but they are not
the target core runtime strategy for this branch.

## Source Entrypoints

Target source entrypoints remain:

- `src/loushang/tui/`
- `src/loushang/harnesstui/`
- `src/loushang/coding/ui/`
- `src/loushang/coding/presentation/tui/`

`loushang.tui` is the generic terminal UI framework. The
[`loushang.harnesstui`](../harnesstui/README.md) composition layer adapts neutral
Harness conversation contracts into reusable TUI interaction.
`loushang.coding.presentation.tui` owns Coding-specific raw event, tool,
history, plain, and screen projection adapters. `loushang.coding.ui` retains
concrete UI state, product surfaces, terminal bindings, and runtime composition.

For status presentation, `loushang.tui` owns the generic status-bar widget and
its layout, styling, invalidation, and rendering mechanics. A shared Harness
status profile belongs to `loushang.harnesstui`; products populate that profile
and retain their own status policy.

Generic settings rows, themes, formatting, and input helpers live in
`loushang.tui.settings`. Reusable Harness-oriented settings pages, model
selection, and surface framing live one layer outward in `loushang.harnesstui`.
Product shells remain responsible for supplying values and applying decisions.

Host clipboard-image acquisition lives in
`loushang.tui.clipboard_image`. This generic capability owns platform fallback,
neutral image bytes and MIME normalization. Product-neutral persistence into a
caller-supplied directory, composer-marker tracking, and prompt-order recovery
live in `loushang.harnesstui.conversation.attachments`. Product shells remain
responsible for workspace-directory policy, UI copy, and conversion into
model-specific attachment values such as `ImagePart`.

Clipboard-image acquisition resolves the host once into an ordered backend
plan behind a common protocol. On macOS, the system `NSPasteboard` adapter is
preferred, with `pngpaste` retained only as a compatibility fallback.

## Coding UI Residual Boundary

`loushang.coding.ui` is intentionally bounded to product UI composition and
terminal bindings. Its retained owners are the mode/CLI entrypoints, concrete
screen app and surfaces, plain/screen runner bindings, settings-page builder,
input/clipboard policy, run/event context, completion, startup, and hotkey
presentation. Raw intents, action control, model/settings facts, tool/event/
history projection, approval binding, resume discovery, and Session-facing
projection adapters live in their Coding feature Python packages instead.

The `loushang.tui` Python package has a 2,200-line upper-budget gate. This is not
an instruction to move `screen_app.py` into a shared layer: that file
deliberately owns Coding's long-lived transcript presentation, cwd cache token,
glyph/theme mapping, path compaction, tool-output preview, 320-line active-window
policy, and render baseline reset reasons. Those contracts remain covered by
the independent render-performance gate.

Generic terminal diagnostics aggregation lives in
`loushang.tui.terminal_diagnostics`. It combines terminal environment,
capability, and live runtime facts without knowing which product presents the
result. Products decide when and where to expose the formatted text.

Generic playback-suite orchestration lives in `loushang.tui.playback_suite`.
It owns neutral scenario specifications and results, scenario selection,
timing, and artifact dispatch. Product scenario catalogs, command-line runners,
and product-specific playback hosts remain in their Product Adapter Python
packages.

## Why Playback Is An Architectural Capability

TUI playback is an executable specification of terminal behavior, not merely a
test helper and not a synonym for replaying persisted conversation records.

| Mechanism | Question answered |
|---|---|
| Conversation/transcript replay | What durable conversation state should be reconstructed? |
| Render snapshot | What logical content should one render state contain? |
| Terminal playback | Which logical frames and terminal operations occur across an interaction sequence? |
| Screen-loop playback | Does scripted TTY input traverse the real async input/router/screen lifecycle correctly? |

The distinction matters because the final visible screen cannot reveal many
terminal regressions. A UI may end with the expected text while having flickered,
cleared scrollback, moved the cursor through transcript content, emitted an
unbounded number of bytes, duplicated streaming blocks, or briefly routed input
to the wrong surface.

### Playback fidelity layers

The current architecture provides complementary levels rather than one giant
end-to-end fixture:

1. `loushang.tui.playback` drives scripted events through render planning and a
   `FakeTerminalPort`. Every step can capture logical lines, changed ranges,
   viewport and cursor coordinates, terminal operations, repaint kind/reason,
   clear-scrollback behavior, cache reuse, materialization counts, and the
   flushed terminal frame.
2. `loushang.harnesstui.testing.input_playback` adds the real `InputReader`,
   keybindings, conversation router, overlay host, neutral routed action
   results, and per-step conversation-state snapshots.
3. `loushang.harnesstui.testing.screen_loop_playback` drives the reusable async
   conversation screen loop with timed TTY-like chunks, then captures raw
   output, control-sequence-free text, exit state, Product-supplied result facts,
   and state artifacts.
4. `loushang.tui.playback_suite` supplies product-neutral scenario selection,
   tag filtering, timing, budgets, failure capture, and artifact dispatch.
   Products own only their scenario catalogs, fakes, copy, and policy.

This split keeps tests close to the owner of each invariant. Pure rendering
does not require a Product, conversation routing does not require Agent/AI
objects, and Product scenarios do not fork the generic playback engine.

### What playback proves

Playback assertions cover both semantic output and physical terminal effects:

- visible and scrollback text;
- operation classes and exact terminal frames;
- maximum operations, serialized bytes, and changed visible lines per step;
- cursor agreement, stable screen anchors, synchronized frames, and clear-screen
  policy;
- resize/reflow and recovery repaint behavior;
- streaming draft promotion, transcript block reuse, and bounded hot-path work;
- paste, completion, selection, surface focus, queue, abort, steer, and follow-up
  ordering; and
- long-transcript rendering budgets and failure artifacts.

This is stronger than relying only on golden final frames or manual smoke tests:
the trace explains *how* the terminal reached a state and preserves intermediate
evidence for a failure. JSONL traces and optional frame/screen/terminal/state
artifacts also make regressions reviewable without reproducing the original
interactive terminal session.

### Why the capability remains valuable as models improve

Playback validates the UI substrate rather than a particular model's prose or
reasoning strategy. More capable models may change response shape, tool choice,
or streaming cadence, but the invariants around input routing, terminal effects,
cursor safety, resize, bounded rendering, cancellation, and queue semantics
remain. Product-neutral playback therefore protects a stable part of Loushang
that stronger models do not absorb.

The accepted low-level design is [KD-010: Terminal Playback Harness](./native-terminal-core/key-designs/KD-010-terminal-playback-harness.md),
with test layering and live-smoke obligations in
[Testing Strategy](./native-terminal-core/testing-strategy.md). Harness-oriented
composition is documented in
[HarnessTUI Conversation Playback Testing](../harnesstui/README.md#conversation-playback-testing).

## Screen Transcript Region

The explicit entrypoint `loushang.tui.ui_parts.transcript` owns the generic
incremental transcript region used by full-screen layouts. It owns stable and
transient record caches, committed and draft render segments, streaming
Markdown segment reuse, tail clipping, cache promotion, and bounded eviction.
These are terminal rendering mechanics over `DisplayRecord` values; the module
does not know about Harness conversations, Coding sessions, tools, or products.

Products bind a long-lived `TranscriptPresentation` implementation that
projects presentation-ready records, chooses record width, decorates rendered
lines, and supplies a cache token. Coding therefore keeps its glyphs, theme,
path compaction, tool-output preview, and cwd policy. The presentation object is
not recreated per frame, and the region preserves the frozen cache keys,
segment identities, records-list identity, and streaming call shape.

`loushang.tui.ui_parts.layout.CappedRenderable` owns the corresponding generic
height cap used when the transcript and bottom frame share a screen layout.
