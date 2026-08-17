# Session Facade Boundary

## Decision

`loushang.harness.session.SessionFacade` owns the standard Product-facing
operation surface over an already composed optional Agent session. It combines
existing Harness-owned runtimes through narrow ports; it does not create a new
Agent loop, transcript repository, tool registry, command catalog, or
compaction implementation.

The Facade provides:

- stable session identity and Product-persisted display-name updates;
- queue-aware state and transcript context/record/file reads;
- active-tool and command catalog access, plus ordered command dispatch;
- prompt, steering, follow-up, queue inspection/clear, runtime subscription,
  continue, abort, and idle waiting;
- selected command-tool execution with output forwarding, cancellation, and
  retry controls;
- common transcript inspection for fork candidates and assistant text.
- product-bound prompt-template reads plus explicit asynchronous and
  best-effort resource refresh requests.
- optional diagnostics queries and package operations through Product-supplied
  ports. The Harness facade does not choose a diagnostics store, package
  source, materializer, serializer, or trust policy.

`SessionControlPort` is the narrow, non-generic portion of this Facade used by
standard hosts and Product adapters. It contains identity, prompt/queue/abort
controls, runtime-event subscription, retry controls, and Product-bound
maintenance controls. It intentionally excludes model selection, provider
authentication, extension UI, Product command schemas, Bash options, and
presentation payloads.

`SessionOperationRuntime` is the capability-grouped invocation layer over a
bound `SessionControlPort`. It makes input, queue, lifecycle, identity, retry,
and maintenance availability explicit without defining an RPC command schema.
Products may expose only selected groups and retain their own request/response
mapping, task lifecycle, and error wording.

Hosts receive a `SessionOperationResolver` rather than retaining one runtime
bound to a concrete Session. The resolver constructs the operation runtime
from the Product's current control after new, restore, fork, or clone. Its
dynamic form requires an active runtime Session and never falls back to a
previously captured Session. Fixed-session hosts bind their control explicitly
through `session_operation_resolver`. The
`prompt()` operation returns after the submitted turn has settled; hosts do
not append a second `wait_for_idle()` to ordinary prompt dispatch. Explicit
idle waits remain valid for independently initiated operations such as abort
settlement and the legacy RPC wait command. Scenario and Work adapters share
the same settled-prompt contract and do not expose a configurable
"wait-after-prompt" mode.

The runtime's `abort_turn()` operation stops only the active turn. TUI-level
`stop_active_interaction` remains an explicit composite that also clears the
Session queue and aborts selected command execution.

Optional operation groups fail with `SessionOperationUnavailableError`.
Missing methods and `AttributeError` raised inside a Product implementation are
programming failures and must not be converted into an "unavailable" result.

The Product-facing facade's independently admitted application-input,
settings, model, diagnostics, package, and extension groups are organized in
`harness.session.facade_optional`. `SessionFacade` inherits its stateless
forwarding surface, so existing methods and constructor ports remain unchanged.
The optional layer owns only typed delegation and stable missing-capability
fallbacks; it does not discover Product capabilities or use dynamic attribute
forwarding for the public operation surface.

Legacy RPC command groups consume narrow private Product protocols for their
direct model/settings, transcript, Bash, lifecycle-index, and command-catalog
dependencies. These protocols are local typing boundaries, not a second
Session facade and not a public all-capabilities RPC interface.

Approval presentation is an optional `SessionApprovalInteractionPort`.
It delegates presenter binding, responses, permission snapshots, and permission
actions to the Product's existing resolver. `ApprovalBroker` remains the sole
owner of pending futures, timeouts, fallback, and cancellation. Presenter
bindings return generation-safe leases. Binding a replacement atomically
supersedes the previous lease and replays unresolved requests with their
existing action IDs and futures. Closing the active lease denies all pending
approvals for that Session, while a superseded lease cannot detach a newer
presenter.

`SessionRuntime`, the Agent transcript profile, session capabilities runtime,
and maintenance runtimes remain their own owners. The Facade only makes their
already-bound operations available through one reusable Product surface.

## Product Binding

A Product supplies its already-admitted:

- `SessionRuntime` with turn policy, application-input policy, event routing,
  and transcript-commit binding;
- a `SessionFacadePorts` bundle containing transcript, tools, commands,
  command-execution, view, retry, identity, maintenance, resource, and
  optional diagnostics/package ports;
- prompt content, model/thinking selection, context policy, lifecycle cleanup,
  and channel event projection.

The view port may project state and context usage into the Product's own domain
types. The Facade deliberately does not impose a universal session-state schema
or a universal Product command result schema.

## Coding Binding

Coding `AgentSession` inherits and initializes the Facade directly rather than
owning a private forwarding Facade. It binds its existing transcript, tool,
command, command-execution, inspection, retry, identity, maintenance, and
resource-refresh runtimes to that shared surface, together with its diagnostics
bridge and Coding package controller. The shared facade owns only the
delegation contract; Coding retains package catalog/materialization policy and
diagnostics wording.
It retains model catalog and auth resolution, provider registration, default
tools and prompt content, Coding command handlers, extension API event and
`user_bash` mapping, Pi-style protocol aliases, package/root/trust policy,
diagnostic wording, compaction strategy, lifecycle cleanup, and TUI/RPC/HTML
projection.

Harness exposes the neutral `BashExecutionRuntime` with native snake_case
arguments and result records. There is no Coding Bash controller or Pi-style
`executeBash`/result alias layer.

`AgentSession.session_control` exposes `AgentSession` itself as the Harness
`SessionControlPort`; there is no private facade object. Coding RPC routes
common control commands through `SessionOperationRuntime`, while retaining its legacy event
subscription fallback and Pi JSON projection: the latter carries Coding event
names, aliases, correlation fields, and optional tool rendering, so it is a
Product adapter rather than a Harness event schema.

The standard Coding Channel adapter instead admits a `WorkOperation` into
`loushang.work.WorkRuntime`; it remains an injected Channel port and does not
give Channel a Harness dependency. Its Coding domain executor owns the Work
execution and cancellation linkage to the bound session.

## Dependency Rule

`harness.session.facade` and `harness.session.facade_optional` may depend on
public Agent/AI message values required by `SessionRuntime`, Harness
runtime/event/tool contracts, and workspace output types. Neither may import
Coding, a Product store, model/provider/auth runtime, extension runner API,
Product configuration, or any UI/RPC/HTML type. Product policy is passed
through the bound ports rather than imported. The optional layer must not
import the core Facade; this keeps the dependency direction acyclic.

## Verification

- Harness contract tests compose the Facade with an independent fake Product
  runtime, transcript, tools, commands, command tool, view, and retry port.
- Compatibility tests require optional methods to remain ordinary inherited
  methods and keep the historical `harness.session.facade` protocol exports.
- Coding session regressions preserve the public `AgentSession` behavior while
  it directly inherits the common `SessionFacade` operations.
- Channel tests bind an injected Coding Work operation port; RPC tests preserve
  Coding's legacy event projection while its control commands use the shared
  capability groups.
- Harnesstui controller and queue tests consume `SessionOperationResolver` and
  `SessionApprovalInteractionPort` without concrete Session method discovery.
- RPC tests preserve turn-only abort semantics and resolve the active Session
  control for every shared operation.
- Architecture tests prohibit Coding imports and Pi protocol names in the
  Facade, and require Coding `AgentSession` to adopt it.
