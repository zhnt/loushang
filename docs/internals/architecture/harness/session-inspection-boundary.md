# Session Inspection Boundary

## Decision

`loushang.harness.session.AgentSessionInspector` owns Product-neutral
read-only operational inspection for one bound Agent transcript session. It
derives common agent run state, context usage, transcript statistics, fork
candidates, entry text, and recent assistant text from public Agent/AI values
and the Harness Agent transcript profile.

The shared result types are `AgentSessionState`, `ContextUsage`,
`SessionStats`, and `TokenUsageTotals`. They are observation values, not a UI
view model and not a persisted transcript schema.

## Product Binding

A Product supplies its active `AgentTranscriptSession`, Agent, session identity
and display-name callbacks, active-tool/maintenance status callbacks, optional
diagnostic availability, model selection, and compaction threshold values.
The inspector does not choose tools, models, compaction policy, diagnostics,
or session naming policy.

### Coding Binding

Coding `AgentSession` binds the Product session record and existing runtime
callbacks directly to `AgentSessionInspector`. The shared
`harness.session.inspection_projection` provides transport-neutral session
statistics and fork candidates using the canonical snake_case shape. TUI,
RPC, and HTML presentation may add Product-specific fields without re-owning
the inspection calculation.

## Dependency Rule

`harness.session.inspection` may depend on the optional Agent/AI transcript
profile, Harness host run state, and public Agent/AI data values. It must not
import Coding, a Product store implementation, Product diagnostics, extension
APIs, configuration, or presentation types.

## Verification

- Harness tests assemble the inspector with a memory transcript and Agent
  without importing Coding.
- Product projection tests preserve context usage, stats, fork candidates, and
  assistant text.
- Architecture tests require the session adapter to use the Harness inspector
  and prevent a Coding import from entering the shared implementation.
