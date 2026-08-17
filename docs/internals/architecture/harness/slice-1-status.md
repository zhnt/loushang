# Harness Slice 1 Closure Status

## Status

Current status: closed on `lane/harness`.

This closes Slice 1 as a harness-lane migration slice. It does not mean the
harness migration is complete, and it does not make `lane/harness` ready to
merge directly to `main`. The lane remains the integration branch for follow-on
harness slices and product-adapter verification.

This document is a historical closure record. The later
[Control Plane Runtime Boundary](control-plane-runtime-boundary.md) moves
pending approval lifecycle and neutral policy mechanisms into Harness while
preserving Coding presentation and risk defaults; its ownership supersedes the
"Coding Still Owns" snapshot below.

Slice 1 delivered neutral approval, tools-core, tool-contribution, and
presentation substrate while preserving coding behavior through compatibility
adapters.

## Closed Scope

Slice 1 closed the following neutral owner modules:

- `loushang.harness.approval`
- `loushang.harness.tools.core`
- `loushang.harness.tools.contribution`
- `loushang.harness.presentation`

The implementation was merged through focused PRs into `lane/harness`:

- PR #247: Slice 1 hardening and owner-module boundaries.
- PR #248: tool contribution resolver and coding adapter verification.
- PR #249: approval compatibility hardening.
- PR #250: presentation adapter verification and renderer fail-soft behavior.

## Closure Audit

Architecture boundaries:

- Harness still has no import of `loushang.coding`, `loushang.tui`,
  `loushang.work`, `loushang.method`, or `loushang.ai`.
- Slice 1 symbols are not exported from top-level `loushang.harness.__all__`.
- No new top-level `loushang.workspace`, `loushang.context`,
  `loushang.memory`, `loushang.session`, `loushang.product`, or
  `loushang.runtime` package was introduced.
- Harness depends only on stable `loushang.agent` primitives where needed.

Behavior preservation:

- Coding default tool names and activation order remain coding-owned.
- Built-in coding tool registration may use `harness.tools.contribution`, but
  concrete tool creation, factory options, policy wiring, and execution remain
  in coding.
- Bootstrap-time extension tool registration may use resolver output, but
  extension runner binding and concrete execution remain in coding.
- Runtime dynamic extension registration remains coding-owned.
- Approval risk policy, `PolicyDecision`, audit payloads, and interactive UI
  behavior remain in coding.
- Presentation notices, `fullOutputPath` projection, `[Full output: ...]`
  labels, truncation wording, builtin renderer semantics, transcript layout,
  and TUI behavior remain in coding.

Compatibility shims:

- Existing coding import paths continue to work for public and internal coding
  surfaces.
- Harness-owned approval and presentation contracts keep their harness
  `__module__`; coding shims preserve import paths, not class identity.
- Public SDK compatibility paths remain until an explicit deprecation or
  long-term support decision is accepted.
- Internal-only shims can be deleted only after in-repo imports move to focused
  harness modules and product adapters no longer depend on the old path.

## Migrated Neutral Mechanisms

Approval:

- `ApprovalRequest`
- `ApprovalDecision`
- `ApprovalResolver`
- `DenyApprovalResolver`
- `HeadlessApprovalResolver`
- `resolve_approval`
- fail-fast contract validation for invalid dispositions and invalid resolver
  results

Tools core:

- neutral `ToolDefinition`
- decorator metadata and `tool`
- schema inference and schema override helpers
- neutral tool registry mechanics
- adaptation to stable `loushang.agent` tool primitives

Tool contribution resolver:

- `ToolContribution`
- `ToolPackDefinition`
- `ToolResolutionDiagnostic`
- `ToolResolutionResult`
- `ToolResolutionError`
- `resolve_tool_contributions`
- deterministic ordering, transitive pack includes, enable/disable filtering,
  duplicate diagnostics, missing reference diagnostics, and opaque metadata
  passthrough

Presentation:

- `ToolResultPresentation`
- ANSI stripping and line-ending normalization
- generic collapse helpers
- `ToolRenderContext`
- `ToolRenderResultOptions`
- `ToolDefinitionResolver`
- `ToolRenderRuntime` state, last-rendered, invalidation, and renderer
  fail-soft behavior

## Coding Still Owns At Slice 1 Closure

Coding still owns product semantics and concrete runtime behavior:

- concrete coding tools: `read`, `ls`, `find`, `grep`, `write`, `edit`, `bash`
- tool factories, `ToolsOptions`, operation protocols, external tool download
  policy, and default tool-pack activation
- `ToolContext`, context provider injection, and product runtime fields
- decorated plain-return normalization into AI content parts
- provider schema projection
- `PolicyDecision`, `PolicyEngine`, destructive command and path heuristics,
  approval audit payloads, `PolicyEnforcementError`, and
  `InteractiveApprovalResolver`
- coding presentation helpers, protocol projection, artifact key conventions,
  notices, truncation wording, builtin renderers, transcript blocks, and UI
  rendering behavior
- command catalog, slash semantics, prompt templates, session store, coding
  runtime, CLI, mode adapters, package/resource/plugin semantics, and settings

## Deferred Items

Deferred items remain outside the Slice 1 closure.

The following items are explicitly deferred beyond Slice 1:

- runtime dynamic extension registration
- concrete coding tools
- command handlers and slash semantics
- prompt templates and prompt/resource semantics
- TUI controller/render loop and screen surface state
- coding session store
- AI provider/model/auth
- agent loop and tool-call orchestration
- work/method/channel implementations
- neutral execution context and live session context binding
- connector authorization and product skill semantics

## Validation Matrix

Validation matrix: the commands below are the required closure audit surface.

Slice 1 closure should be validated with:

- `uv --cache-dir .uv-cache run --extra dev pytest tests/architecture/test_import_boundaries.py -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/harness -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_approval_compatibility.py tests/coding/test_policy_engine.py tests/coding/test_tool_policy_integration.py -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_tool_registry.py tests/coding/test_tool_public_types.py tests/coding/test_tool_schema.py tests/coding/test_tool_wrapper.py tests/coding/test_tool_authoring.py -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_bootstrap.py -k 'extension_tool or extension' -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_extension_runner.py tests/coding/test_extension_api.py -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_presentation_compatibility.py -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/coding/test_tool_policy_integration.py tests/coding/test_tool_presentation.py tests/coding/test_tool_render_runtime.py tests/coding/test_tool_builtin_renderers.py tests/coding/test_tool_transcript_blocks.py tests/coding/test_session_exports.py -q`
- `uv --cache-dir .uv-cache run --extra dev pytest tests/harnesstui/commands/test_catalog.py tests/harness/commands/test_catalog.py tests/coding/test_session_command_controller.py tests/coding/test_screen_coding_tui_surfaces.py tests/coding/test_prompt_assembly.py -q`
- `uv --cache-dir .uv-cache run --extra dev ruff check <changed files>`
- `git diff --check`

## Next Slice Recommendation

The next slice should start with design, not implementation.

Recommended focus:
[Slice 2 Execution Context Design](slice-2-execution-context-design.md),
covering neutral execution/contribution context boundaries that can serve
coding and future products without importing product runtime state into harness.
That design should precede any migration of runtime dynamic extension
registration or live tool execution context.
