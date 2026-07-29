# Harness Control Plane Runtime Boundary

## Status

Status: implemented on `harness/control-plane-runtime`; integration pending.

The extension-routing portions of this document remain current. Its
tool-shaped Policy and boolean Approval target is superseded by
[Policy And Approval Redesign](policy-approval-redesign.md). During cutover,
this document describes the legacy implementation only; it must not be used to
add new Policy/Approval APIs.

This boundary closes the product-neutral control path from extension
contribution routing through policy evaluation and asynchronous approval. It
builds on the existing extension, approval, policy, workspace-tool, and host
contracts without creating another Agent loop or a general service locator.

## Decision

`loushang.harness` owns the reusable mechanisms for:

- deterministic extension-handler ordering and dependency validation;
- observer, interceptor, reducer, and first-match routing;
- handler failure isolation and explicit chain-failure policy;
- neutral policy subjects, rules, matching, and evaluator composition;
- command-subject normalization used by reusable process tools;
- pending approval request lifecycle, including presentation, resolution,
  cancellation, timeout, fallback, and disposal;
- product-neutral composition of extension routing, policy evaluation, and
  approval resolution.

Products and OEM adapters continue to own:

- risk classification and the default allow, deny, and ask rules;
- approval defaults, remembered grants, trust decisions, and user-facing
  explanations;
- concrete UI, RPC, and event payload projection;
- product event/result schemas and the reducers that interpret them;
- extension activation, permission defaults, and trust policy;
- product tool selection and Agent tool materialization.

The composition direction remains:

```text
product / OEM adapter
  -> harness extension router
  -> harness policy runtime + approval broker
  -> harness workspace-tool enforcement adapter
  -> stable Agent tool value primitives
```

The router, policy runtime, and approval broker are sibling mechanisms. The
router does not import or locate policy, approval, workspace, or Product
services. A Product composes them through narrow typed ports.

Harness must not import Coding, Design, Research, PPT, Cowork, Method, Work,
Channel, TUI, AI, provider, model, credential, or product session modules.

## Motivation

At design time, the ownership declarations were ahead of the implementation:

- `ExtensionSurfaceDescriptor` carried `priority`, but runtime dispatch still
  used extension insertion order and had no `before`, `after`, or `on_error`
  contract;
- `ExtensionDispatcher` supported observers, first-truthy dispatch, and one
  hard-coded input reducer, while Coding still owned the generic loops for
  context, before-agent, session decisions, and tool interceptors;
- `loushang.harness.approval` owned approval value types and headless resolvers,
  but Coding owned pending futures, request ids, presenter binding, and result
  correlation;
- `loushang.harness.policy` only defined a decision and a narrow protocol,
  while Coding owned reusable command-wrapper normalization, tool/path matching,
  and configurable rule mechanics;
- the workspace policy layer defined a second evaluator protocol instead of
  adapting to one Harness-owned policy subject and decision contract.

This duplication makes extension and approval semantics product dependent and
would force another product to copy Coding control-flow code. It also makes a
future Product Session Host depend on a wide callback bag. The control plane is
therefore migrated before higher-level session composition.

## Goals

1. A non-Coding product can route extension hooks, evaluate a tool policy,
   suspend for approval, resume, and execute a tool without importing Coding.
2. Existing Coding extension order, diagnostics, approval payloads, and public
   compatibility paths remain stable unless an explicit ordering declaration
   changes the order. Policy outcomes remain stable for commands that can be
   completely normalized; incomplete or platform-dependent wrapper syntax now
   fails safely to Product approval instead of being allowed implicitly.
3. Extension handlers can declare deterministic relative ordering and failure
   behavior without embedding Product types in Harness.
4. Pending approval requests cannot leak when callers cancel, presenters fail,
   requests time out, sessions dispose, or late results arrive.
5. Product policy remains data and semantics supplied to a Harness mechanism;
   Harness does not acquire Coding's destructive-command defaults.

## Non-Goals

- Moving Coding prompts, skills, tool descriptions, risk wording, or default
  policy rules into Harness.
- Selecting or trusting extensions on behalf of a Product.
- Defining Method, Work, Channel, model-provider, or storage runtime behavior.
- Persisting approval grants or providing an interactive UI.
- Replacing the Agent before/after-tool hook contract.
- Creating a universal Product manifest, dependency-injection container, or
  arbitrary service registry.

## Extension Routing

### Route Declarations And Resolved Routes

Harness separates extension-owned declarations from runtime-resolved routes
under
`loushang.harness.extensions.routing`:

```python
@dataclass(frozen=True)
class RegisteredExtensionHandler:
    local_route_id: str
    event_name: str
    handler: Callable[[object, object], object | Awaitable[object]]
    priority: int = 0
    after: tuple[str, ...] = ()
    before: tuple[str, ...] = ()
    on_error: Literal["skip", "fail_chain"] = "skip"
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedExtensionRoute:
    route_id: str
    extension: LoadedExtension
    registration: RegisteredExtensionHandler
    registration_index: int
    source_info: SourceInfo[Path]
```

The resolved route retains the extension object required by the existing
per-extension context factory, provenance diagnostics, and runtime-error
callback. `ExtensionRoutePlan.from_extensions()` compiles registrations once
per extension-set generation and exposes event-scoped resolved routes. Dispatch
receives the request-local context factory; constructing a router for a new cwd
does not rebuild the plan or repeat validation diagnostics.

An explicit `local_route_id` is unique within one extension and event. The
canonical route id is:

```text
<extension_id>/<event_name>/<local_route_id>
```

Each normalized, non-empty component is UTF-8 percent-encoded before joining.
RFC 3986 unreserved characters remain readable; `/`, `%`, `#`, Unicode, and
whitespace are encoded. The `#duplicate-N` suffix is therefore reserved for
planner-generated identities and cannot collide with a declared component.
`route:` references use the encoded canonical id exposed by the compiled plan.

Ordering references use an unambiguous qualified grammar:

- `route:<canonical-route-id>` targets exactly one route;
- `extension:<extension-id>` targets all active routes from that extension for
  the current event only.

Automatic ids such as `legacy-0001` are generated from registration order for
legacy handlers and are not a public cross-extension reference contract.
Explicit duplicate local ids, self references, malformed references, and
missing active references produce distinct diagnostics. A reference to an
inactive optional extension is ignored so disabling an extension does not
create ordering noise.

`ExtensionSurfaceDescriptor` grows the same `after`, `before`, and `on_error`
fields. These fields describe contribution order and remain optional so
existing constructors preserve behavior. `LoadedExtension` gains a defaulted
`handler_registrations` field. Registrations are the authoritative runtime
source after load; `hooks` is a compatibility projection.

For `LoadedExtension(hooks=...)` and legacy extension objects that do not carry
registrations, plan compilation synthesizes registrations in extension order,
mapping insertion order, and handler-list order. When explicit registrations
exist, the loader derives the compatibility `hooks` projection from them;
conflicting dual input produces a diagnostic instead of running a handler
twice.

The contribution API remains source compatible:

```python
api.on("context", handler)
api.on(
    "context",
    handler,
    route_id="redact-secrets",
    priority=20,
    after=("extension:base-context",),
    on_error="fail_chain",
)
```

The existing manifest `handler` field is not a reliable runtime route identity
and is not used for ordering in this batch. Runtime ordering is declared by the
registration API or by programmatic surface descriptors. A future manifest
extension must add an explicit route id and exact API/manifest matching with
unmatched and ambiguous diagnostics; it must not infer identity from an event
or Python function name.

### Stable Ordering

Ordering is compiled per event with these precedence rules:

1. active routes only;
2. explicit `before` and `after` edges;
3. higher numeric priority first among otherwise ready routes;
4. original extension and handler registration order as the final tie-breaker.

The planner computes strongly connected components, preserves edges between
components, and topologically sorts the condensed graph. A ready set uses
`(-priority, registration_index)`. Cycles produce an
`extension_route_order_cycle` diagnostic with the affected route ids; internal
edges of that component are dropped and its routes use priority plus
registration order. Incoming, outgoing, and unrelated acyclic constraints
remain valid. The router never chooses a different winner based on filesystem
enumeration order.

### Dispatch Modes

`ExtensionRouter` provides four product-neutral operations over a compiled
plan:

- `observe`: invoke every route and collect non-`None` results;
- `first`: stop at the first result accepted by an injected predicate;
- `reduce`: let an injected reducer combine each result with opaque state;
- `intercept`: a reduce specialization whose reducer may stop the chain.

The generic reduction contract is:

```python
@dataclass(frozen=True)
class RouteStep(Generic[S]):
    state: S
    stop: bool = False


Reducer = Callable[
    [S, object, ResolvedExtensionRoute],
    RouteStep[S] | Awaitable[RouteStep[S]],
]

async def reduce(
    event_name: str,
    state: S,
    *,
    event_factory: Callable[[S, ResolvedExtensionRoute], object],
    reducer: Reducer[S],
    context_factory: Callable[[LoadedExtension], object],
) -> RouteStep[S]: ...
```

Every route receives an event created from the latest state. A handler result
of `None` skips the reducer. The reducer receives the resolved route so Product
diagnostics retain source identity. Reducers may be synchronous or async;
reducer, event-factory, and predicate errors are Product errors and propagate
unchanged. Only handler invocation is governed by the route's `on_error`.
`stop=True` returns immediately with the latest state. `observe` returns the
ordered non-`None` results and `first` returns the first predicate match or
`None`.

Harness schedules handlers and contains handler failures; Product code
validates and interprets Product-specific results. This replaces duplicated
loops without moving `AgentMessage`, `ToolCall`, session-decision, prompt, or
artifact types into Harness.

`ExtensionDispatcher` remains as a compatibility facade over
`ExtensionRouter`. Its existing `dispatch`, `dispatch_first_truthy`, and
`dispatch_input` behavior remains stable.

When a handler fails:

- `on_error="skip"` records a provenance-bearing diagnostic, invokes the
  runtime error callback, and continues;
- `on_error="fail_chain"` records the same diagnostic and raises a typed
  `ExtensionRouteError` after invoking the callback;
- cancellation exceptions are not converted into diagnostics;
- invalid Product results are reported by the injected Product reducer, not by
  generic Harness routing.

The runtime error callback is best-effort: callback failure cannot turn a
`skip` route into a failed chain. For `fail_chain`, the router always raises
`ExtensionRouteError` chained from the original handler error. The router
catches `Exception`, not `BaseException`, so cancellation, process exit, and
keyboard interruption retain normal propagation.

`ExtensionResourceRuntime` consumes the same compiled route order for resource
hooks but retains contribution aggregation semantics. This avoids a second
ordering implementation while keeping resource result interpretation in the
focused resource runtime.

## Policy Runtime

### Neutral Subjects

Harness replaces the string-only evaluator protocol with focused standard
subjects rather than a free-form attributes bag:

```python
@dataclass(frozen=True)
class CommandPolicySubject:
    command: tuple[str, ...]
    cwd: str | None
    direct_tokens: tuple[str, ...]
    shell_payload: str | None = None
    normalization_complete: bool = True


@dataclass(frozen=True)
class PathPolicySubject:
    raw_path: str
    resolved_path: str | None = None


@dataclass(frozen=True)
class ToolPolicySubject:
    tool_name: str
    arguments: Mapping[str, object]
    cwd: str | None = None
    command: CommandPolicySubject | None = None
    paths: tuple[PathPolicySubject, ...] = ()


@dataclass(frozen=True)
class CustomPolicySubject:
    kind: str
    value: object | None = None
```

`PolicySubject` is the union of these records. Product-defined kinds use
`CustomPolicySubject`; Harness does not interpret their payloads. Constructors
copy tool argument mappings and sequence fields into immutable JSON-like
snapshots with string-only mapping keys; unsupported mutable or opaque leaves
are rejected. `CustomPolicySubject.value` remains the explicit escape hatch for
Product-owned opaque values. Workspace enforcement creates this snapshot once
before any await and uses it for evaluation, legacy adapters, audit events,
approval requests, and error projection. An injected `policy_subject` must
match the explicit execution tool, arguments, cwd, paths, and comparable command
projection or evaluation fails closed.

The canonical command subject is built from the final `ExecRequest.command`,
`stdin`, and cwd after command prefix, selected shell path, spawn-hook rewriting,
and other execution adapters have run. Reconstructing it from raw bash
arguments is not allowed. When a supported shell reads a script from stdin,
that script is the shell payload; stdin supplied to a `-c` command or script
file remains data and is not reclassified. Relative operands are anchored to
the effective cwd (or the process cwd when execution inherits it); controlled
path-identity checks recognize symlinks and `/proc/*/root` aliases to stdin.
Restricted shell names and `+` invocation options share the corresponding
shell parser. Shell entrypoints are classified by executable identity, using
the last `PATH` value in the final execution environment for bare names. Empty
and relative `PATH` entries are anchored to the effective execution cwd, not
the host process cwd. Absolute, relative, and `PATH` aliases therefore use the
parser for the shell they actually reference; a deceptive basename cannot
select a different parser. An independently copied executable with a known
shell basename uses that shell parser but remains incomplete because its
physical identity is not trusted. Suspected stdin/fd aliases and unresolved
stdin-consuming entrypoints set
`normalization_complete=False`. Tool-name and path policy may run earlier, but
command policy runs against the final spawn argv, cwd, environment, and stdin
projection supplied to the backend.

Before any policy or approval await, the Bash execution boundary materializes
the final `ExecRequest`. Materialization resolves an inherited cwd to an
absolute path and snapshots the complete environment after applying the public
`ExecRequest.env` overrides. The override tuple remains the Product-visible
projection used by approval and audit records; the complete
`effective_environment` snapshot is execution-only state and may contain
credentials. Policy normalization and the executor consume the same
materialized request. `ExecService` also materializes requests at its boundary
and passes that exact request to custom `ExecBackend` implementations. A custom
backend or `BashOperations` implementation must honor the
materialized `cwd` and `effective_environment` instead of rereading process
state. Bash materializes unconditionally before policy or the first async tool
update, including when no policy evaluator is configured. This binds cwd and
environment across asynchronous evaluation, approval, presentation, and
execution without rewriting argv semantics.

Command policy is a control-plane guardrail, not a filesystem sandbox. Shell
and wrapper normalization may inspect executable identity to project the
current command, but Harness deliberately does not rewrite or freeze executable
paths, `argv[0]`, shebang interpretation, executable bytes, files sourced by a
shell, or lookup performed inside wrappers and shell payloads. Concurrent
filesystem or executable-alias mutation is therefore outside this contract. A
Product requiring adversarial check-to-execute isolation must combine policy
with a sandbox or immutable execution image. Harness preserves native process
semantics instead of claiming an incomplete executable snapshot.

### Rules And Evaluation

The evaluator protocol supports sync or async implementations and explicit
abstention:

```python
class PolicyEvaluator(Protocol):
    def evaluate(
        self, subject: PolicySubject, /
    ) -> MaybeAwaitable[PolicyDecision | None]: ...
```

`None` means that an evaluator does not apply; it is not an implicit allow.
`evaluate_policy()` is the only invocation path. It awaits results, validates
the result type and disposition, propagates cancellation, and wraps evaluator
failures or invalid results in `PolicyEvaluationError`. Runtime failures never
silently allow an operation. Invalid contributed evaluator shapes are rejected
during activation.

`PolicyRule` contains a stable id, matcher, and `PolicyDecision`.
`RulePolicyEvaluator` returns the first matching rule or `None`; it has no
hidden default. The Product or enforcement adapter supplies the final explicit
default after the composed chain abstains. `PolicyEvaluatorChain` composes
injected evaluators with one of these strategies:

- `first_non_allow`: deny or ask stops the chain; otherwise the first explicit
  allow is returned after all evaluators run, or `None` when all abstain;
- `most_restrictive`: all evaluators run in resolved order; deny wins over ask,
  ask wins over allow, and the first result at the winning level supplies the
  stable reason and code;
- `first_decision`: the first non-`None` decision is authoritative.

Harness supplies reusable exact-name, token-sequence, shell-payload, and path
substring matchers. Command normalization unwraps supported `env` and `sudo`
forms, recognizes shell `-c` payloads, and matches direct argv by token rather
than accidental substring. These are process-execution mechanics, not Coding
policy. Platform-dependent or lossy forms such as `env -S`, unknown wrapper
options, and `sudo` shell/login mode retain the best available projection but
set `normalization_complete=False`. Harness exposes an incomplete-command
matcher; the Product owns the fallback. Coding defaults unresolved command
syntax to approval instead of allowing it silently. Wrapper operations that
change executable lookup, including inline `PATH`, `env -u PATH`, and
environment clearing (`env -i`, `--ignore-environment`, or lone `-`), are
incomplete until their resulting lookup environment can be projected exactly.
The same applies to `env --argv0`, shell-startup environment changes
(`BASH_ENV`/`ENV`), and a `sudo` environment assignment that changes command
projection. Explicit Bash startup files (`--rcfile`/`--init-file`) are
incomplete; when they resolve to stdin, their payload is combined with the
command payload. Common BusyBox/Toybox `sh`, `ash`, and `env` applet forms are
projected without treating unrelated multicall applets as shells.
Reusable Bash execution parses string commands through the configured shell.
For argv commands it selects a shell parser only from executable identity or a
known shell name; other resolved executables remain direct argv, while an
unresolved stdin entrypoint is incomplete. The Workspace gateway materializes
the effective environment before building the canonical subject, so executable
resolution never falls back to the host's unrelated `PATH`.

`harness.policy_engine.PolicyEngine` is the only default evaluator. Products
inject configuration, not evaluator subclasses or compatibility wrappers.
Every evaluator implements only `evaluate(subject)`; the retired
`evaluate_action` and `evaluate_tool_call` call shapes are rejected.

The reusable workspace enforcement path owns a neutral audit vocabulary from
action freeze through policy, approval, execution start, and terminal outcome.
It emits correlation IDs, one stable action fingerprint, capability and
structurally redacted action/command summaries, Policy code, Approval ID,
execution-profile summary, and result status. It never emits final command
argv, cwd/path values, contents, environment data, free-form reasons, or
exception text into the common event stream.

Products inject the sink and own projection into their session/event schemas,
persistence, RPC/UI presentation, and compatibility field aliases. A
deployment that needs complete raw evidence must explicitly bind a separate
restricted evidence store; Product projection is not permission to copy raw
arguments into common audit events. This keeps the mechanism observable
without making Coding's event protocol a Harness contract.

## Approval Broker

`ApprovalBroker` is a Product-neutral `ApprovalResolver`. Each active pending
set is confined to one event loop; after the set is empty, the same broker may
be reused on a later loop. It owns correlation and lifecycle but not
presentation:

```python
broker = ApprovalBroker(
    fallback=HeadlessApprovalResolver(mode="deny"),
    timeout_seconds=None,
)
broker.set_presenter(presenter)
request = ensure_approval_action_id(request)
decision = await broker.resolve(request)
broker.resolve_request(action_id, ApprovalDecision.allow())
```

`ensure_approval_action_id()` returns an immutable request with a generated id
when needed. Enforcement calls it before emitting the approval-requested audit
event, then passes the same request to the broker so requested, resolved, and
error records use one id. `ApprovalBroker.resolve()` also calls the helper
idempotently, so the broker remains substitutable for any `ApprovalResolver`
when a direct caller supplies no id. The broker atomically reserves the final id
before calling the presenter. An action id that is pending or was already
presented interactively by the same live broker raises
`ApprovalRequestCollisionError`; this tombstone prevents a late result from an
older session generation from approving a new request. Presenter absence and a
disposed broker go directly to fallback resolution. `dispose()` clears the
tombstones because presenter rebinding is then forbidden.

`ApprovalRequest.arguments` accepts JSON-like mappings, sequences, strings,
numbers, booleans, and null. Construction copies and freezes that tree; mutable
or opaque leaves are rejected. `approval_request_to_dict()` is the stable
Product projection and returns detached ordinary dictionaries and lists. It
deliberately omits the evaluator-owned `policy_decision` object, which is not a
wire contract.

An `ApprovalPresenter` implements
`present(request) -> MaybeAwaitable[None]`. The Product adapter converts the
request into UI, RPC, or event payloads. Only presenter absence uses the
fallback resolver. Presenter exceptions remove the pending request and
propagate; they do not leave a hidden future. A synchronous presenter may
resolve the request reentrantly because reservation happens before
presentation. A presenter may also expose optional `dismiss(request)` lifecycle
projection. Synchronous dismissal runs during broker cleanup; an awaitable is
detached and its result consumed, so UI cleanup cannot delay or replace the
authorization result. If an asynchronous presenter resists cancellation and
finishes after broker cleanup, the broker dismisses the request again after
that late completion so the stale presentation cannot remain visible. Product
dismissers must therefore be idempotent and tolerate repeated cleanup for the
same action id.

Lifecycle rules are explicit:

- caller cancellation removes and cancels the pending future;
- timeout delegates to the fallback resolver while the request remains pending;
  explicit cancellation or disposal can still win before fallback completes;
- `cancel_request` accepts an injected `ApprovalDecision` and completes one
  request;
- `cancel_all` and `dispose` accept an injected decision and complete every
  pending request deterministically;
- `dispose` is idempotent and rejects new interactive requests through the
  fallback resolver;
- unknown, duplicate, or late results return `False` without mutation;
- presenter replacement affects only requests created after replacement;
- snapshots expose immutable request records, never futures.

All externally supplied terminal `ApprovalDecision` values are revalidated,
including already-instantiated values that may have been deserialized or
mutated outside normal dataclass construction.

Normal result, timeout, cancellation, and disposal compete through one
complete-once primitive. Fallback resolution always uses `resolve_approval()`
for sync/async handling and result validation; a broker rejects itself as its
fallback. An unfinished fallback is cancelled and detached when an explicit
decision wins. Presenter and fallback failures propagate after cleanup. The broker
does not manufacture Product cancellation or disposal wording.

Coding's `InteractiveApprovalResolver` becomes a composition facade over
`ApprovalBroker`. It retains `set_request_presenter` and
`handle_result`, converts request objects to the existing Coding dictionary
payload, hides broker internals, and preserves accepted import paths and
`__module__`. The resolver is runtime-owned and shared by tool definitions and
successive sessions. Session disposal cancels only that generation's pending
requests; it does not unbind the presenter. The host UI owns presenter binding
for its lifetime and unbinds it on UI shutdown, so new/resume/fork replacement
does not silently fall back to headless denial. `AgentSession` seals and
cancels its approval generation before waiting for the host to become idle;
replacement candidates remain staged and cannot change shared approval state.
Every runtime replacement entrypoint reopens the shared resolver only in host
activation, after the old session has been released. This ordering prevents a
running operation waiting for approval from deadlocking session teardown while
ensuring repeated cleanup from the old session cannot close the new one. Coding's
Screen TUI projects
Escape as rejection and queues concurrent approvals FIFO, ensuring that closing
or replacing an overlay never leaves a broker future hidden. It subscribes to
the host's post-release, pre-activation invalidation notification without
replacing the primary fail-fast lifecycle callback. Notification failures are
isolated after the old session is disposed, so early UI cleanup cannot make a
rolled-back live approval invisible. The TUI clears old-generation surfaces on
replacement and consumes broker
dismissal for timeout or caller cancellation. Approval callback failure
terminates the TUI path only after presenter teardown cancels all pending
requests fail-closed.

Session generation state and presenter attachment are separate. Detaching a
presenter denies the active pending set and removes the UI binding, but the same
active generation may later attach a presenter and reopen interactive
resolution. Staged or closed generations cannot rebind or unbind the shared
presenter. TUI shutdown always resolves the runtime's current session instead
of using the session captured at initial startup.

The Coding CLI passes the runtime-owned interactive resolver to runtime
builders that declare `approval_resolver` or accept arbitrary keyword
arguments. Injected legacy builders with the previous fixed keyword signature
continue to receive only that signature; normal startup and help-time runtime
discovery use the same compatibility invocation helper.

## Policy And Approval Extension Contributions

This batch adds executable `policy` and `approval` contribution paths, not only
surface type strings. It does not allow an extension to bypass Product
activation or trust checks.

`ExtensionContributionAPI.register_policy()` and `register_approval()` create a
focused `RegisteredControlContribution` containing a descriptor and a separate
runtime value. Implementations are never hidden inside descriptor `metadata`.
`LoadedExtension.control_contributions` carries these records and focused
projection functions validate their evaluator or resolver protocol shape.

Active policy contributions are interceptors composed by
`PolicyEvaluatorChain` in resolved extension order. Policy contributions default
to `on_error="fail_chain"`; `skip` must be selected explicitly for an advisory
policy whose failure may safely abstain. Approval is an exclusive
replacement slot: after Product/OEM activation filtering, the first resolved
active contribution wins and additional active values produce a deterministic
conflict diagnostic. The selected resolver may be supplied as the broker
fallback; it is not a presenter. Product activation may select a different
winner, but Harness never chains approval resolvers implicitly.
`register_approval()` therefore fixes `on_error="fail_chain"` and does not expose
a skip option. Directly constructed active approval records with skip semantics
are rejected with an activation diagnostic. Harness wraps the selected resolver
with its resolved route identity, validates synchronous and asynchronous
results through `resolve_approval()`, and records a provenance-bearing
`extension_approval_resolution_failed` diagnostic before propagating failure.
Cancellation propagates without adding a failure diagnostic.

The generic inventory indexes descriptors while the focused record carries the
runtime value. Harness does not import Method or Channel to add their surface
names; those owners must define their own processing paths first.

Product/OEM code supplies each extension's activation decision. Harness then
applies that decision uniformly at executable boundaries: hook and resource
routes, policy and approval contributions, command/tool/flag/shortcut registry
projection, message renderers, and runtime binding. Inactive extensions remain
visible to inventory and diagnostics, but none of their capabilities are
executable. A missing policy on a directly constructed legacy extension retains
the compatibility meaning "already accepted by the caller."

## Coding Cutover

The Coding migration is completed in the same branch:

| Current Coding owner | Result |
| --- | --- |
| `coding.extensions.hooks.HookDispatcher` | Compatibility facade using `ExtensionRouter`; Product Agent result coercion remains in Coding. |
| Generic loops in `coding.extensions.runner.ExtensionRunner` | Replaced by router observe/reduce/first operations. Context creation and Product reducers remain in Coding. |
| removed `coding.policy.approval.InteractiveApprovalResolver` | Harness owns lifecycle and payload projection. |
| removed command parsing and generic matching in `coding.policy.engine` | Harness policy matchers/normalizers. |
| removed `coding.policy.engine.PolicyEngine` | Products inject settings into the Harness evaluator. |
| Workspace tool policy protocol | One `evaluate(subject)` contract; audit and Product error projection remain stable. |

No compatibility module may retain a parallel routing, pending-request, command
normalization, or rule-evaluation implementation.

## Compatibility

The following behavior remains stable, except that incomplete or
platform-dependent command normalization now deliberately returns Product
approval rather than implicit allow:

- existing `api.on(event, handler)` calls;
- existing `LoadedExtension.hooks` inspection;
- insertion order when no ordering metadata is supplied;
- Coding extension hook result types and validation diagnostics;
- Coding approval presenter dictionaries and `handle_result` calls;
- Coding approval payloads use the detached `approval_request_to_dict()`
  projection rather than dataclass internals;
- tool-policy audit event names and detail keys;
- top-level `loushang.harness.__all__` remains unchanged.

New focused APIs are imported from `loushang.harness.extensions.routing`,
`loushang.harness.policy`, and `loushang.harness.approval`; they are not promoted
to the top-level Harness facade.

## Delivery Plan

1. Add route records, stable ordering, generic router, and compatibility
   dispatch facade.
2. Cut Coding observer, decision, context, before-agent, and tool hook loops over
   to the router.
3. Add neutral subjects, matchers, rules, evaluator chain, and workspace policy
   adapter; rebuild Coding policy defaults on those mechanisms.
4. Add `ApprovalBroker`; convert Coding interactive approval to a payload
   adapter and wire session disposal.
5. Add policy/approval extension-surface projection and a non-Coding OEM fixture
   that exercises the complete control path.
6. Remove duplicate implementations, update ownership documents, and add
   architecture import guards.

Each step must land with its focused tests in the same semantic branch. The
branch is not integrated while Coding still has a second generic mechanism.

## Validation Matrix

### Extension Routing

- stable insertion order with no metadata;
- priority and before/after ordering;
- missing-reference and cycle diagnostics;
- skip and fail-chain behavior;
- async and sync handlers;
- cancellation propagation;
- observer, first, reducer, and interceptor behavior;
- Coding input, context, before-agent, session decision, and tool hooks.

### Policy

- exact tool matching and ordered rule precedence;
- shell payload and direct argv normalization;
- `env` and `sudo` wrapper handling;
- executable identity, copied shell, wrapper-basename, relative/empty `PATH`,
  and BusyBox/Toybox applet handling;
- stdin script aliases use cwd-relative lexical normalization plus controlled
  path-identity checks for symlink and proc-root aliases;
- shell startup input through `--rcfile`, `--init-file`, `BASH_ENV`, and `ENV`;
- incomplete and platform-specific wrapper syntax uses a Product fail-safe;
- path raw/resolved candidate matching;
- evaluator-chain strategies;
- Coding default and configured outcomes;
- workspace policy audit and enforcement compatibility.

### Approval

- presentation and result correlation;
- missing presenter fallback;
- presenter failure cleanup;
- caller cancellation, timeout, explicit cancellation, and disposal;
- duplicate and late results;
- multiple concurrent requests;
- UI Escape rejection and FIFO presentation of concurrent requests;
- presenter continuity across runtime session replacement;
- Coding dictionary projection compatibility.

### Architecture And Integration

- an independent OEM-shaped fixture registers an interceptor, contributes a
  policy evaluator, suspends for approval, resumes, and reaches tool execution;
- Harness import-boundary tests cover the new modules;
- Coding compatibility identity and import tests remain green;
- Ruff, mypy for touched packages, focused Harness/Coding tests, the complete
  architecture suite, and the full non-live suite pass;
- `git diff --check` reports no whitespace errors.

## Exit Criteria

This boundary is complete only when:

1. Routing, policy matching, and pending approval lifecycle have one Harness
   implementation each.
2. Coding contains only Product defaults, Product result coercion, Product
   presentation, and compatibility facades for these capabilities.
3. A non-Coding fixture exercises the end-to-end control path without Product,
   AI, Method, Work, Channel, or TUI imports.
4. Existing Coding public behavior and snapshots remain compatible.
5. The architecture documents and migration inventory describe implemented
   ownership rather than planned ownership.
