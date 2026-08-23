# Loushang Harness TUI

`loushang.harnesstui` is the product-neutral composition layer between Harness
conversation contracts and the generic terminal UI framework. Its dependency
direction is:

```text
`loushang.coding.ui` -> `loushang.harnesstui` -> `loushang.tui`
`loushang.coding.interaction.*` -> `loushang.harnesstui`
`loushang.coding.model_selection_tui` -> `loushang.harnesstui`
`loushang.coding.presentation.tui.*` -> `loushang.harnesstui`
`loushang.harnesstui` -> `loushang.harness`

`tests/coding/tui_support` -> `loushang.harnesstui.testing`
                           -> `loushang.harnesstui`
                           -> `loushang.tui`
```

The reverse dependencies are forbidden. In particular, `loushang.harnesstui`
must not import `loushang.coding`, `loushang.agent`, AI message/model/provider
Python packages, or product-specific policy. `loushang.harness` and `loushang.tui` are
independent peers: Harnesstui may depend on both, but neither peer may depend on
Harnesstui or on the other peer.

## Responsibilities

This layer owns reusable Harness-oriented terminal interaction, including:

- adapting neutral conversation snapshots and actions to TUI records and
  surfaces;
- coordinating product-neutral conversation projection state such as tool
  timing and duplicate-result suppression;
- neutral tool-result views, transcript blocks, and deterministic presentation
  projection;
- product-neutral plain-terminal conversation rendering and projection targets
  over presentation-ready records and facts;
- shared Harness status profiles that product shells can populate and present;
- reusable settings pages, Harness status configuration, surface framing, and
  model-selection interaction over neutral TUI items;
- reusable conversation reading, pending/working presentation, and input
  coordination;
- UI-side approval presentation and decision routing after the neutral Harness
  approval lifecycle has defined the corresponding ports.

`loushang.tui` continues to own terminal mechanics, rendering, layout, input
decoding, host clipboard-image acquisition, generic widgets, and transcript
presentation primitives.
`loushang.harness` continues to own neutral runtime and durable conversation
contracts. HarnessTUI may interpret the standard normalized Session event and
transcript shapes structurally, while Product adapters supply Agent result
conversion, visibility choices, command policy, and final presentation copy.
`loushang.coding.ui` owns product UI composition, while Coding retains intent
types, policy, branding, and runtime assembly.

## Catalog Interaction Workflows

`loushang.harnesstui.commands.interaction` and
`loushang.harnesstui.selection.interaction` own the product-neutral
snapshot-to-resolution workflow for command and model catalogs. A product
captures one immutable interaction snapshot, Harnesstui projects its generic
palette, and the resolver returns a structural `list`, `selected`, `empty`,
`ambiguous`, or `cancelled` outcome. Sync and async palette choosers are both
supported. Command descriptors remain opaque and the selected descriptor is
returned by identity; model interactions consume only product-prepared
`ModelChoice` values and return the selected choice without applying it.

`loushang.harnesstui.commands.source` materializes a product-supplied sync or
async command source into that immutable snapshot. It does not discover a
Session or define command precedence; those remain product ports and policy.

These workflows do not acquire a Session catalog, parse Coding intents,
normalize model/provider objects, mutate the active model, persist settings,
or choose product wording. Coding continues to own `CodingCommandCatalog`,
which commands count as local and their precedence, Session and model-detail
adaptation, endpoint preference policy, `ModelSelection` application,
default-model persistence, slash-command aliases, and all selection status,
ambiguity-hint, and failure copy. Harnesstui applies caller-selected
source-aware ordering, including local-last ordering, or value-only ordering,
and resolves the prepared catalog. Generic palette widgets, completion
containers, search lists, and terminal interaction mechanics remain in
`loushang.tui`; the existing Harnesstui presentation modules only project
caller-supplied descriptors and choices.

The explicit module paths `loushang.harnesstui.commands.source`,
`loushang.harnesstui.commands.interaction`, and
`loushang.harnesstui.selection.interaction` are the stable entrypoints for
these workflows. Python package initializers do not add convenience re-exports.

## Settings and Prepared Surfaces

`loushang.harnesstui.settings.workflow` owns the reusable settings-dashboard
workflow: tab composition, focus, status and status-line refresh, model-page
refresh, and structural apply effects. Products supply prepared `ConfigRow`
and `ModelChoice` snapshots plus callbacks for applying configuration and model
changes. The workflow never receives a raw Session or SettingsManager.

Coding keeps its six setting ids, labels, getter/setter mapping, validation
copy, model catalog acquisition, endpoint policy, model application, and
default-model persistence. Those product facts live outside `coding.ui`; its
remaining settings-page module is only the composition adapter that turns them
into shared workflow ports.

`loushang.harnesstui.surface.factory` builds framed surfaces from prepared
palettes and neutral selection items. Titles, subtitles, footers, placement,
and sizing remain caller-supplied policy. It does not parse Coding commands,
load models, mutate a composer, or decide approval outcomes.

## Conversation Attachments

`loushang.harnesstui.conversation.attachments` owns product-neutral prompt-image
attachment coordination after the host clipboard has been read. It persists a
neutral `ClipboardImage` into a caller-supplied directory, derives a composer
marker relative to a caller-supplied display root, and tracks pending
attachments so submission order follows marker order in the composed text.
Read, unsupported-type, and persistence failures are returned as neutral
outcomes; products supply their own status copy.

The host clipboard backend and MIME detection remain in
`loushang.tui.clipboard_image`. Products continue to choose workspace and
storage-directory policy and adapt a neutral prompt attachment into model-facing
values such as `ImagePart`. Harnesstui does not import AI message types or
hard-code a Coding workspace layout.

The explicit module path
`loushang.harnesstui.conversation.attachments` is the stable entrypoint for this
capability. The conversation Python package initializer does not add a
convenience re-export.

## Conversation State, Queue, and Reader

`loushang.harnesstui.conversation.screen_state` owns reusable screen
conversation presentation state: retained display records, record revisions,
window generations, live assistant buffers, tool-record replacement, pending
input queues, and presentation-ready status facts. This is UI projection state,
not Harness Session lifecycle, persistence, or runtime orchestration.

`loushang.harnesstui.conversation.window_budget` owns the pure active-window
budgeting algorithm and its generic omission markers. It counts source logical
lines independently of terminal width, includes one separator line between
records, preserves the newest contiguous tail, and may tail-trim only the
oldest retained boundary record. Coding continues to choose the default line
budget, when trimming runs, how fully evicted counts accumulate, and which
render-baseline reset reason is emitted.

The reusable transcript source protocol, active-window source,
record-composition helpers, and modal conversation reader also live here.
Record composition may merge history with a live window, preserve
presentation-only decorations, deduplicate the projected history suffix shared
with the active-window prefix, and select recent assistant text, but it only
operates on product-supplied `DisplayRecord` values. Coding retains the
Session-backed source because it still materializes Coding Session history and
AI message shapes.

`loushang.harnesstui.conversation.queue` owns defensive queue reads, cleared
queue normalization, draft restoration, and `PendingQueueView` composition over
a session-like port. Products retain queue availability policy, tracing sinks,
and the decision about when to present or restore queued input.

This slice does not own session lifecycle, persistence, runtime orchestration,
or Agent/AI object construction. The state and active-window algorithms retain
their existing semantics after moving here. Incremental transcript
segmentation, render caches, committed and draft segments, streaming Markdown
reuse, and tail clipping live in `loushang.tui.ui_parts.transcript`; Harnesstui
does not duplicate or wrap that rendering engine.

Coding product bindings import these owners directly. Compatibility re-exports
must not be recreated; `loushang.harnesstui` must never depend back on Coding.

The stable imports introduced by this slice are the explicit module paths
`loushang.harnesstui.conversation.screen_state`,
`loushang.harnesstui.conversation.window_budget`,
`loushang.harnesstui.conversation.queue`,
`loushang.harnesstui.conversation.reader` and
`loushang.harnesstui.conversation.source`. The conversation Python package does
not yet expose a broader convenience API.

## Tool Transcript and Status Profile

This migration slice keeps the reusable presentation core independent from
Agent, AI, and Product modules. Optional Agent composition lives in a separate
binding module.

`loushang.harnesstui.conversation.tool_transcript` owns the neutral tool-result
view and the display contracts used to project tool activity into conversation
records. Its inputs describe presentation-ready facts rather than Agent or
provider objects. Deterministic transcript status, block construction, and
record projection belong here because they are reusable across Harness-backed
terminal products.

`MappingToolTranscriptViewAdapter` and
`build_mapping_tool_transcript_projection` extend that existing owner for the
standard mapping-shaped Session event contract. The adapter reuses
`ToolTranscriptProjectionBinding` and `ToolTranscriptProjector`; it is not a
second projector.

`loushang.harnesstui.conversation.agent_binding` is the optional Agent profile.
It composes the existing neutral history, tool-transcript, plain-target, and
screen-target owners with stable Agent event and message contracts. It owns the
standard Agent history dispositions and result conversion without duplicating
their projection engines. Products import this module when they need an Agent
conversation; the neutral modules do not import it eagerly.

`loushang.harnesstui.conversation.agent_application` owns prepared Agent screen
and plain application state. For live screen Products it also owns the atomic
session-switch refresh of transcript history, event subscription, status
context, completion provider, and approval presenter. Products inject their
completion loader and problem logger. The adjacent
`loushang.harnesstui.conversation.agent_surfaces` module composes the standard
resume, delete, fork, rename, agent-tree, and side-question workflow ports from
the existing surface components; it does not own Product continuity providers,
settings, diagnostics, hotkeys, model policy, or copy.

Coding no longer owns a parallel intent parser, conversation controller,
action host, history disposition table, tool projector, or plain/screen event
adapter. Its product binding supplies the command catalog, callbacks, Product
copy, attachment-to-AI conversion, settings surfaces, approval presentation,
and final renderer profile. This keeps the dependency pointing from Coding into
HarnessTUI while preserving an Agent-free neutral conversation core.

`loushang.harnesstui.status.line` owns a shared Harness status profile and its
product-neutral presentation rules. A product shell supplies the profile's
values and decides when those values change. This capability is not the generic
`loushang.tui` status-bar mechanism: TUI continues to own the widget, layout,
styling primitives, invalidation, and frame rendering. Harnesstui must not
reach into those mechanics or introduce a second status-bar runtime.

`loushang.harnesstui.status.snapshot` owns the neutral status facts.
`loushang.harnesstui.status.provider` owns the callback-fed status profile and
product-neutral status-line setting transitions.
`loushang.harnesstui.status.persistence` adapts those settings to a
caller-supplied duck-typed settings store without importing a product manager.
`loushang.harnesstui.status.plain` owns the compact, line-oriented toolbar
projection over presentation-ready status values. Coding continues to own live
Session reads, the concrete settings store, scope choice, and provider update
timing. Removed Coding status modules are not compatibility re-exported.

These explicit module paths are the stable imports for this slice. The Python
package initializers do not need to provide convenience re-exports.

## Conversation Event Projection

`loushang.harnesstui.conversation.projection` owns the reusable state machine
that projects neutral conversation facts into a `ConversationProjectionTarget`.
It coordinates run starts, queue snapshots, assistant streaming, tool-call
snapshots and elapsed time, duplicate tool results, and duplicate assistant
errors. `SessionConversationEventAdapter` extends this existing owner to route
the standard normalized Session event mapping. It consumes message roles and
text structurally and delegates tool values through an injected
`ToolTranscriptProjectionBinding`; it never imports Agent, AI, or Coding.

`loushang.harnesstui.conversation.plain_target` owns the reusable Plain
projection target and its generic retry/compaction status copy. Coding injects
visibility flags and Agent tool-result conversion directly into the shared
adapter; the former `coding.presentation.tui.events` facade is deleted.
`loushang.harnesstui.conversation.screen_target` owns the reusable Screen
projection target: it maps neutral facts onto a product-neutral Screen app
port, including optimistic user-echo handling, assistant lifecycle calls, tool
record upserts, and compaction-record dispatch. Coding injects its running-tool
title resolver, tool-record projector, and retry/compaction status copy, so
tool labeling and all product wording remain outside Harnesstui.

Surface-interest checks happen in the shared adapter before queue reads, text
joins, or tool rendering. This preserves Plain and Screen's distinct event
interests and prevents ignored or duplicate events from mutating the injected
Product tool-render runtime. Queue readers reuse
`conversation.runtime_view.stable_string_queue_reader`; the projection module
does not create another queue abstraction. Tool elapsed time brackets result
adaptation and neutral projection, while each target keeps its prior cleanup
behavior if projection fails.

Assistant text deltas form a strict pass-through hot path. The shared adapter
must call `ConversationProjector.assistant_delta` directly, and that method
must call the target directly without constructing an intermediate event,
action list, tuple, mapping, generator, or concatenated buffer. Render caching,
segmentation, invalidation, frame composition, and terminal writes remain in
`loushang.tui` and the product renderer; this projection layer does not replace
or bypass the frozen TUI render-performance contract. A marked Product-binding
test exercises the complete adapter-to-projector-to-target delta path, so the
existing `make test-tui-render-contract` gate covers this new boundary.

The explicit `projection`, `plain_target`, and `screen_target` module paths
above are the stable imports for this capability. The Python package initializer
does not provide convenience re-exports.

## Conversation Screen Composition

`loushang.harnesstui.conversation.screen_frame` builds the product-neutral
working line, pending queue, status bar, and bottom-frame geometry from
`ScreenConversationState`. Products inject immutable copy once when the screen
binding is constructed; no copy profile is allocated while rendering.

`loushang.harnesstui.conversation.screen_app` owns the reusable full-screen
conversation shell: state transitions, assistant streaming coordination,
transcript-reader surfaces, render requests, elapsed-time scheduling, active
window replacement, transcript-region synchronization, and screen layout.
It holds the canonical `loushang.tui.ui_parts.transcript.TranscriptRegion`
directly and preserves the records list, cache, and segment identities.

Coding retains a real `ScreenCodingTuiApp` subclass. That binding supplies its
composer prompts, frame copy, theme, welcome panel, transcript presentation,
320-line budget, compaction wording, path compaction, and tool-output preview
policy. The shared app does not import Coding, AI, Agent, or raw product events.
The explicit `screen_frame` and `screen_app` module paths are stable; the
conversation Python package initializer does not re-export them.

## Conversation Transcript Styling

`loushang.harnesstui.conversation.transcript_style` owns the reusable
presentation-ready transcript grammar that maps semantic spans to theme
tokens. It recognizes tool markers, verbs, flags, activity actions,
connectors, timing and omission metadata, errors, and worked dividers, then
adds ANSI styling without changing plain text or visible width.

Coding still owns the glyph and rail transformation in `_coding_line` and
`_coding_lines`, its default theme token values, path compaction, duplicate
command/timing suppression, and tool-output preview policy. The shared styler
does not participate in segmentation, cache invalidation, frame planning, or
terminal writes; its module-level regular expressions, span ordering, and
per-line call shape remain part of the frozen render-performance contract.
The explicit module path above is stable and is not re-exported by the
conversation Python package initializer.

## Conversation Interaction Control

The reusable control plane for a full-screen conversation lives behind eight
explicit entrypoints:

- `loushang.harnesstui.conversation.clipboard_policy` owns the standard
  workspace staging path and user-facing copy for conversation clipboard
  images;
- `loushang.harnesstui.conversation.input_policy` owns neutral projected input
  capabilities, steer-first/fallback policy, and conversation keybinding
  definitions;
- `loushang.harnesstui.conversation.input` coordinates decoded input,
  completion, surfaces, running-submit modes, and neutral attachments;
- `loushang.harnesstui.conversation.control` coordinates abort, steer, and
  follow-up actions over caller-supplied controllers and status callbacks. It
  also defines the immutable `ConversationTextAction` and the structural
  `ConversationActionHost` product port;
- `loushang.harnesstui.conversation.dispatch` owns product-neutral dispatch,
  result-presentation, and stable event-stream lifecycles;
- `loushang.harnesstui.conversation.run_context` owns UI subscription cleanup,
  stable emission, tracing, and context-exit ordering;
- `loushang.harnesstui.conversation.host` owns the standard
  abort-settling/follow-up/steer/local/dispatch routing state machine and the
  action-host port;
- `loushang.harnesstui.conversation.screen_runner` owns the reusable terminal
  read/route/run loop over explicit screen, router, and result ports.

`ConversationInputRouter` is the sole Harness conversation-input semantic
owner. It interprets idle/running Enter, running-submit steer or follow-up,
pending queue restore, and conversation cancellation. It reuses TUI
`ComposerInputTarget` and editor helper functions, but does not delegate whole
events to generic `loushang.tui.InputRouter` as a second run-state router.
Generic TUI emits only neutral prompt/editor signals and has no conversation
running state.

These modules build conversation interaction from neutral UI values. They do
not own a Harness Session, runtime construction, Product intent classes,
model-facing image types, or command policy. `ConversationRoutingProfile`
receives the parser, exit predicate, local action mapping, follow-up projection,
command effect resolver, and lifecycle as explicit callbacks, then compiles
them into the existing `ConversationHostProfile`. Harnesstui's standard
clipboard profile owns `.loushang/clipboard` staging and generic outcome copy;
Coding keeps `PromptIntent` and `BashIntent`, `ImagePart`, Session and
observability setup, and its interruption, queue, and error messages.

The action host is a dependency-inversion seam, not a second lifecycle or
dispatch engine. Plain products may compose the existing run-control,
dispatch, and result presenter behind it. Screen products may keep lifecycle
ownership in `screen_runner` and only bind the host's four action methods.
`loushang.harnesstui.testing.action_host` provides the corresponding callback
adapter for playback without introducing product policy into the shared layer.

The screen runner coordinates existing rendering calls but does not move or
replace transcript segmentation, invalidation, render caches, frame
composition, or terminal writes. Those hot-path responsibilities and the
independent render-performance contract remain unchanged. The conversation
Python package initializer intentionally does not re-export these entrypoints.

`AgentScreenConversationApplicationBinding` and
`AgentPlainConversationApplicationBinding` compose these existing ports for
Agent Products. They bind shared history, event projection, status, queues,
resume hints, trace events, transcript sources, and reverse cleanup without
creating another screen/plain host. Coding's `ui.mode` remains the Product
composition root for the screen app, surface manager, controller/action host,
renderer, completion, copy, theme, and policy. The former
`loushang.coding.presentation.tui.runtime` reflection facade is retired.
Resume-hint discovery and standard Agent session history projection live in
`loushang.harnesstui`; reusable footer state lives in
`loushang.harness.session.footer` so non-UI session code never imports the UI
layer. Coding supplies only Product command prefixes, persisted-session
loading, final presentation, and copy.
Agent approval presenter binding and Session transition cleanup extend the
existing `AgentScreenConversationApplicationBinding` module. They depend only
on structural Agent session and screen-surface ports, so every Agent Product
uses the same binding and cleanup mechanics. Products continue to own approval
policy, surface presentation, and fallback copy supplied to the binding.

## Conversation Playback Testing

`loushang.harnesstui.testing` is opt-in test support for exercising the
product-neutral interaction ports above. Its dependency direction is
`tests/coding/tui_support` -> `loushang.harnesstui.testing` ->
`loushang.harnesstui` / `loushang.tui`. The reverse direction is forbidden:
production Harnesstui must never import its testing Python package, and the
generic TUI remains independent of both Harnesstui layers.

Playback is an architectural boundary test, not only UI snapshot convenience.
It proves that a Product can bind neutral Harness conversation facts into the
shared TUI without creating Product-specific input, routing, rendering, or
screen-loop semantics. The production dependency remains one-way even though
the testing layer can drive the same public ports with deterministic fixtures.

Three playback forms cover different failure classes:

| Playback form | Real boundaries exercised | Evidence captured |
|---|---|---|
| Direct render scenario | prepared app state -> render planning -> fake terminal | logical/visible frames, terminal operations, repaint diagnostics |
| Decoded-input playback | raw chunks -> `InputReader` -> keybindings -> conversation router -> render loop | routed actions, per-step state, frames and terminal trace |
| Screen-loop playback | timed TTY-like chunks -> reusable async screen runner -> Product callbacks | raw terminal output, normalized text, exit/result facts and final state |

This layering detects sequence bugs that isolated widget tests and final-screen
goldens cannot: an intermediate wrong focus owner, duplicate optimistic user
echo, stale pending queue, abort/steer/follow-up misrouting, transient cursor
movement, unnecessary repaint, accidental clear-screen, or state that looks
correct only after a later frame repairs it.

The testing contracts are intentionally Product-neutral. Coding supplies its
app factory, scenario catalog, policy, copy, and Product-only assertions, while
future Research, PPT, or Cowork products can reuse the same input, render, and
screen-loop drivers. This makes playback evidence useful when extracting shared
behavior: reuse is demonstrated through explicit ports rather than inferred by
copying Coding fixtures into HarnessTUI.

Playback artifacts also separate semantic and physical evidence. Neutral action
results and conversation state explain what the router decided; logical frames
explain what the renderer intended; serialized terminal output explains what
the host would receive. Keeping all three prevents a passing high-level state
assertion from hiding a terminal regression, and prevents a visual golden from
hiding incorrect conversation control flow.

The shared testing Python package must not import Coding, AI, Agent, or Harness
runtime Python packages. It owns only reusable terminal test mechanics over
neutral ports:

- `loushang.harnesstui.testing.ports` defines the application, router,
  snapshot, result, and factory protocols used by playback drivers;
- `loushang.harnesstui.testing.input_playback` owns decoded-input playback,
  neutral routed results, state snapshots, artifacts, and the fluent input
  scenario;
- `loushang.harnesstui.testing.render_scenario` owns deterministic direct
  rendering against a fake terminal and controllable clock;
- `loushang.harnesstui.testing.screen_loop_playback` owns scripted TTY chunks,
  real screen-loop playback, captured output and state artifacts, and the
  fluent loop scenario;
- `loushang.harnesstui.testing.performance` owns neutral long-transcript
  fixtures, visible/full-plan timing, render-loop operation metrics, and
  optional plan commits over a narrow render app port;
- `loushang.harnesstui.testing.scenarios.factory` binds those drivers to a
  product-supplied app, router, screen runner, artifact adapters, and frame
  contracts;
- the `composer`, `lifecycle`, `terminal`, `transcript`, and `surface` modules
  under `loushang.harnesstui.testing.scenarios` provide reusable recipe
  builders. They do not construct a product catalog at import time.

These explicit modules are the stable testing entrypoints. The testing Python
package initializer intentionally does not re-export them.
`ConversationRenderScenario`, the input and screen-loop drivers, and the
scenario factory own the reusable fixture mechanics;
`loushang.tui.playback_suite.run_playback_cli` owns catalog selection and
reporting. Repository-local support in `tests/coding/tui_support` only binds
those facilities into a concrete Coding catalog and retains product-only
scenarios, fakes, copy, fixture volumes, and render-performance budgets. The
repository manual runner is `scripts/run_tui_playback.py`; none of this product
test support is part of the installed Coding Python package. The temporary
`loushang.coding.ui.playback*` and `loushang.coding.ui.perf_probe` compatibility
paths were retired after their consumers moved to the canonical testing Python
packages. Persisted Coding Session materialization remains in
`loushang.coding.presentation.tui.history`.

## Prepared Conversation Application Hosts

The reusable application shell is split into narrow, explicit entrypoints:

- `loushang.harnesstui.conversation.application_host` owns prepared plain and
  screen run sequencing, subscription lifetime, history installation, and
  clean-exit callbacks;
- `loushang.harnesstui.conversation.plain_app` composes the neutral plain
  lifecycle, routing, status/settings view, information presentation, and
  result presentation from injected product ports;
- `loushang.harnesstui.conversation.plain_prompt_host` owns the one-shot and
  multi-turn plain prompt loop over prepared callbacks;
- `loushang.harnesstui.conversation.history` dispatches durable neutral
  `ConversationRecord` payloads into presentation-ready transcript records;
- `loushang.harnesstui.conversation.transcript_display` owns generic display
  transforms such as duplicate command suppression, render-width selection,
  and absolute-path compaction;
- `loushang.harnesstui.conversation.startup`, `.resume`, `.runtime_view`, and
  `.debug_action` own small presentation-ready view models and deterministic
  UI-side sequencing.

These hosts never acquire a Coding Session or Runtime and do not interpret raw
Agent/AI events. Coding supplies its command/model/debug policy, raw event and
transcript adapters, tool titles and previews, startup facts, resume command,
copy, and product effects through the declared profiles and ports.

## Canonical Import Cutover

The temporary Coding UI re-export paths for conversation control and state,
status and settings primitives, transcript reading and styling, playback, and
performance probes are retired. New and existing consumers import their owners
directly:

- terminal settings and playback-suite primitives from `loushang.tui`;
- neutral conversation, status, and performance support from
  `loushang.harnesstui`;
- Coding playback catalogs, fakes, and scenarios from repository-local
  `tests/coding/tui_support`, invoked through
  `scripts/run_tui_playback.py`;
- persisted-session transcript loading from
  `loushang.coding.presentation.tui.history`.

`loushang.coding.ui.cli` remains the product console entrypoint, while real
Coding UI adapters that own product policy, copy, or runtime binding remain in
`loushang.coding.ui`. The retired-module manifest in
`tests/coding/test_ui_import_boundaries.py` prevents the compatibility paths
from being recreated accidentally.

Coding's screen input binding now constructs the canonical
`ConversationInputRouter` directly. Harnesstui keeps staged prompt images as
neutral `PromptImageAttachment` values through routing, provides the standard
workspace clipboard profile, and exposes clipboard outcomes through an optional
caller callback. Coding consumes that shared profile and converts neutral
attachments to `ImagePart` at the model-dispatch boundary. Its screen loop is a
thin binding around `run_conversation_screen`; test-only aliases for shared
runner and terminal helpers are not product APIs.

Harness `SessionOperationRuntime` declares and enforces steering and follow-up
input delivery through `SessionInputCapabilities`. The standard Agent binding
projects those Harness-owned declarations into Harnesstui's neutral
`ConversationInputCapabilities`; the shared input policy is steer-first and
falls back to follow-up when steering is unavailable. Coding accepts that
default and may bind another `ConversationInputPolicy` without changing the
Harness capability declaration. Capability projection reads resolver binding
metadata and must not resolve an active Session during application preparation.

Generic TUI exposes an immutable, duplicate-safe `KeybindingCatalog` and owns
only its Core action definitions. Harnesstui composes separate conversation and
continuity catalogs over Core. The conversation catalog owns
`conversation.input.followUp`, `conversation.input.pasteImage`, and queue edit;
the continuity catalog owns preview, domain, and sort. User settings remain raw
until the applicable catalog is composed, so plugin actions can be configured
without moving their defaults into TUI. Coding formats its hotkey help from the
resolved conversation catalog. The generic TUI router is not part of this
conversation state machine.

## Plain Conversation Presentation

`loushang.harnesstui.plain.renderer` owns the reusable plain-terminal renderer:
stdout flushing, assistant buffering, transcript-buffer projection, Markdown
and terminal blocks, status/error/tool presentation, width handling, and a
neutral presentation profile. It consumes only TUI records, neutral tool
blocks, and presentation-ready status values.

Coding retains a thin `PlainCodingUiRenderer` profile adapter. That adapter
owns the `Loushang TUI` title, `/feedback` interruption copy, Coding glyphs,
line mapping, and the Ran/Tested command fallback. The existing shared event
adapter and Plain target own event routing; Coding retains Agent tool-result
adaptation and injects Plain-specific event-interest flags.

The shared Plain renderer and target do not participate in the Screen pipeline's
transcript segmentation, invalidation, caching, frame composition, or terminal
writes. Those frozen hot-path responsibilities remain in the Screen product
renderer and `loushang.tui`.

The stable imports are the explicit module paths
`loushang.harnesstui.plain.renderer` and
`loushang.harnesstui.conversation.plain_target`; their Python package
initializers do not provide convenience re-exports.

## Settings, Selection, and Surface Composition

Generic settings vocabulary belongs to the terminal framework.
`loushang.tui.settings` owns `ConfigRow`, the shared settings theme, value
formatting, row lookup, input helpers, and the reusable `SettingsListPage`.
It has no Harness or product dependency and can be used by any terminal
application.

Harnesstui owns the reusable interaction assembled from those generic widgets:

- `loushang.harnesstui.settings.page` provides the compatibility name
  `ConfigSettingsPage` for the generic TUI settings list;
- `loushang.harnesstui.settings.dashboard` owns the tabbed settings shell,
  static information pages, focus/footer interaction, and neutral status and
  usage view-models;
- `loushang.harnesstui.settings.model` owns model-settings interaction over
  product-supplied neutral choices;
- `loushang.harnesstui.status.settings` owns status-line settings rows, preview,
  and interaction over the neutral status profile;
- `loushang.harnesstui.surface.view` owns the framed bottom-surface view and its
  information-panel scrolling behavior;
- `loushang.harnesstui.surface.factory` owns pure information and command
  surface builders over presentation-ready text and neutral `SelectItem`
  values;
- `loushang.harnesstui.surface.controller` owns application-side surface intent
  normalization, submit dispatch, bottom/overlay placement bookkeeping, and
  transient approval-presentation serialization;
- `loushang.harnesstui.selection.model` owns scoped/all model selection over
  product-supplied `SelectItem` values;
- `loushang.harnesstui.selection.catalog` owns the opaque `ModelChoice` and its
  text, completion, palette, matching, settings-list, and selector-row
  projections;
- `loushang.harnesstui.commands.presentation` owns duck-typed command text,
  completion, palette, matching, display ordering, and selector-row
  projection.

These modules own reusable interaction mechanics, layout, existing shared copy,
and visual behavior, but not product data or decisions. The surface coordinator
normalizes UI intents and serializes approval presentations; it never resolves
approval policy, executes a guarded action, or owns approval audit state.
Coding continues to own settings-manager persistence, model and command
discovery, model application, command-catalog and slash-command policy,
status-provider updates, approval resolver/runtime binding and product copy,
and adaptation of product data into neutral labels and choices. Generic
`Surface`, `SurfaceHost`, `SelectionSurface`, and `SearchableList` mechanics,
including actual focus, stack, geometry, and host lifetime, remain in
`loushang.tui`. The coordinator does not participate in transcript rendering,
render invalidation, cache management, frame composition, or terminal writes.

The model settings page emits the shared UI intent
`InputIntent(kind="setting", text="model.current", note=<choice value>)`.
Products decide how that opaque choice value is resolved, applied, and
persisted; Harnesstui never calls a Session or settings manager.

The explicit module paths above are the stable imports. Coding binds prepared
product data and callbacks directly, without subclassing or re-exporting these
shared implementations; Python package initializers do not add convenience
exports.

## Quality Gate

Run `make check-harnesstui` for the product-neutral composition boundary. The
gate lints and type-checks Harnesstui, its shared TUI settings vocabulary, and
the explicit Coding adapters, then runs Harnesstui, import-boundary, and direct
Coding integration tests. Marked render-contract cases are excluded from this
behavior gate and remain owned by the independent render-performance job.
Known dynamic dataclass-replacement typing limitations are suppressed only at
the exact expressions involved; the enclosing adapters remain under the normal
mypy gate so new diagnostics are enforced.

The deterministic render-performance contract remains a separate gate. Run
`make test-tui-render-contract` independently when changing render-path code or
moving a marked contract test; `check-harnesstui` does not change or duplicate
its thresholds.
