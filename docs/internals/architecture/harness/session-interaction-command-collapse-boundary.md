# Session Interaction And Command Collapse Boundary

Status: implemented on `lane/harness` as the shared action/source composition
slice.

This slice moves execution mechanics out of Coding without moving Coding's
content. The shared owners are:

- `loushang.harnesstui.conversation.controller.ConversationUiController`
  brackets prompt, steer, follow-up, abort, bash, command dispatch, and
  transport-safe action failures. Products inject intent types, command
  catalog construction, bash options, and diagnostic logging.
- `loushang.harness.session.command_controller.SessionCommandController`
  composes builtin, extension, and resource command sources, command
  preflight, source diagnostics, completion, and capability-pack dispatch.
  Products inject builtin descriptors, handlers, result factories, and source
  matching.
- `loushang.harness.context.serialize_context_usage_payload` owns strict JSON
  validation and recursive key normalization. It accepts dataclass snapshots
  without importing a Product profile.
- `loushang.harness.events.project_session_runtime_event` owns conversion of
  shared queue, compaction, retry, branch, package, metadata, and tool-policy
  facts to the standard session event payload. Product transports still decide
  view selection, rendering, and final wire shape.
- `loushang.harness.extensions.runtime_bindings.ExtensionRuntimeBindingFactory`
  composes the shared extension binding record. Coding supplies model,
  session, tool, and UI callbacks; the factory itself has no Coding policy.

Coding keeps only:

- Coding intent types and slash-command vocabulary;
- `CodingUiController` as a binding of those types and `CodingCommandCatalog`;
- Coding builtin command descriptors, handlers, result wording, and resource
  policy;
- Coding JSON event aliases/serialization and presentation skins.

No Pi-specific projection was added. The old runtime projection module was
removed; the package-level name remains only as a source migration alias for
existing Coding callers and points at the Harness implementation.

## Accounting

Measured with physical Python lines in `src/` at the slice boundary:

| Coding source | Before | After | Owner after |
| --- | ---: | ---: | --- |
| `interaction/controller.py` | 237 | 48 | HarnessTUI controller + Coding binding |
| `session/command_controller.py` | 239 | 78 | Harness session controller + Coding binding |
| `session/usage_payload.py` | 33 | 0 | Harness context usage |
| `event/runtime_projection.py` | 120 | 0 | Harness events runtime projection |
| `session/extension_runtime_bindings.py` | 111 | 5 | Harness extension binding factory + source alias |
| **Selected source total** | **740** | **131** | **-609** |

Across the complete `src/loushang/coding` package, the physical count moved
from 27,674 to 27,053 lines in this working tree (the extra few lines are
import-boundary cleanup around the moved owners).

The shared implementation grows in Harness/HarnessTUI; this is an ownership
transfer, not a deletion of capability. Historical note: the subsequent
Session RPC cutover is complete. Harness Host now owns Product command JSONL
framing/routing and Harness Session owns operation execution; Channel framing
is reserved for Channel envelopes, not Product RPC.

## Gates

- Coding behavior tests for UI controller, command sources, session events,
  runtime projection, and AgentSession remain green.
- HarnessTUI does not import AI, Agent, or Coding; product diagnostics are
  injected through a logger port.
- Harness session command composition has no Coding import.
- Shared runtime event projection has no Coding import.
