# Session Product Adapter Collapse

## Decision

`loushang.harness.session` is the only owner of common live-session
mechanics. `SessionRuntime` owns the Agent loop subscription, prompt and queue
ordering, ApplicationMessage delivery, ordered runtime events, and abort/idle
coordination. `SessionFacade` owns the reusable Product-facing operation
surface. `AgentSessionInspector` owns product-neutral state, context usage,
statistics, and transcript text/fork-candidate observation. The Agent
transcript maintenance runtime owns retry state and retry lifecycle.

Coding must bind those components through explicit Product ports. It must not
recreate a session runtime, a session event stream, a retry state machine, or
an inspection controller merely to adapt Coding policy.

## Implemented Collapse

- `SessionFacadePorts` groups the transcript, tools, commands, selected
  command-tool, inspection, retry, diagnostics, and package adapters supplied
  by a Product. It keeps those Product decisions separate from
  `SessionRuntime` ownership. Diagnostics and package operations are optional
  ports: a Product that does not expose either capability gets an empty query
  result or an explicit unavailable-operation error rather than a second
  implementation in Coding.
- `AgentSession` now supplies `AgentSessionInspector` directly as its Facade
  inspection port. The removed `coding.session.SessionViewController` was only
  a binding wrapper around the Harness inspector.
- Session statistics and fork-candidate projection now live in
  `harness.session.inspection_projection` with a canonical snake_case shape.
  They are shared inspection facts, not a Product state model or session
  controller.
- `AgentSession` now binds Coding retry settings, its Agent state, and the
  overflow classifier directly to `AgentTranscriptRetryRuntime`. The removed
  `coding.session.RetryController` was only a constructor wrapper.
- Historical private forwarding methods that had no production consumer have
  been removed from `AgentSession`; callers use the composed Harness runtime
  or Product adapter directly.
- `AgentSession` no longer owns public forwarding methods for session-file and
  prompt-template reads, diagnostics queries, or package operations. It binds
  its existing diagnostics bridge and Coding package policy to the Harness
  facade. The package catalog, materialization policy, serialization, and
  trust decisions remain Coding ports; Harness owns only the common delegation
  surface.
- `AgentTranscriptSessionRuntime` owns the optional diagnostics query surface
  through a Product-supplied provider. `AgentSessionRuntime` keeps its Coding
  lifecycle, cwd, file-store, and package-policy adapters while no longer
  repeating diagnostics forwarding methods or a current-session accessor.
- `ProductSessionRuntime` now composes the existing lifecycle transaction,
  transcript directory runtime, and public lifecycle operation adapter through
  one neutral Product-port bundle. `AgentSessionRuntime` is a Coding binding
  of that composition boundary rather than a second lifecycle owner.
- `ProductSessionRuntime` now also owns common after-commit index scheduling,
  replacement callback execution, restore/import failure routing, and
  session-scoped diagnostic fallback. The standard
  `ProductTranscriptSessionBinding` removes repeated create/open/fork/dispose
  adapters for Product transcript subclasses.
- `AgentSessionAdapterMixin` is the typed Agent Product adapter base over
  `SessionFacade`. It supplies the standard lifecycle-hook binding for
  approvals, runtime-host rebinding, extension start/switch/fork/shutdown, and
  session-only disposal. Product sessions inherit this single base instead of
  combining an untyped mixin with the Facade through multiple inheritance.
- `ExtensionInputRuntime`, `ExtensionAgentHookRuntime`, and
  `ExtensionAgentEventRuntime` own standard extension input delivery, Agent
  hook composition, and lifecycle-event mirroring in the optional
  `harness.extensions.agent` profile, where lifecycle is observation-only and
  typed ports prevent a reverse Session dependency. `ExtensionSessionRuntime`
  owns bind/refresh/invalidation coordination. The removed Coding controllers
  were implementation-only wrappers around these product-neutral mechanics.
- `harness.extensions.agent.input_adapter` owns normalized extension input
  delivery, `harness.extensions.agent.replacement` owns replacement callback
  plumbing, and `harness.extensions.provider_config` owns native provider
  value-object parsing. Coding supplies only its provider/model policy
  callback and extension API surface.
- Transcript export, settings binding, tool coordination, and session
  inspection projection are Harness-owned. Coding no longer has parallel
  `session/export.py`, `session/session_settings_controller.py`,
  `session/types.py`, `session/tool_controller.py`, or platform inspection
  projection modules.

## Product Boundary

Coding retains only:

- model registry, model/auth resolution, provider registration, and model or
  thinking selection policy;
- Coding prompt content, default tool selection/materialization, `bash` and
  other code-tool semantics, command handlers, and summary prompts/model calls;
- Coding extension API/hooks, package/root/trust policy, diagnostics wording,
  session index policy, cwd/session-file acceptance, and lifecycle cleanup;
- Product RPC/TUI/HTML presentation contracts, command aliases, and display
  state.

These are Product semantics, not reusable Host/Session mechanics. Moving them
to Harness would create false neutrality and make Research, Design, PPT, and
OEM adapters depend on Coding vocabulary.

`ProductSessionRuntime` composes the common lifecycle transaction with the
transcript directory/catalog runtime. `AgentSessionRuntime` binds that
composition directly and retains only the Coding transcript subclass,
`before` fork default, cwd/error adapter, session factory event, diagnostic
service, and copy callback. This wave does not move ModelRegistry,
authentication, Coding extension APIs, code tools, or UI projection.

## Verification

- Harness Facade tests compose `SessionFacadePorts` with independent fake
  Product ports.
- Coding session tests verify the direct inspector and shared inspection
  projection preserve context usage, stats, fork-candidate, retry, and
  `AgentSession` behavior.
- Architecture tests require Coding to adopt the Harness Facade, inspector,
  and retry runtime while prohibiting the removed controller paths.
