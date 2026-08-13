# Coding LSP Component Boundaries

## Status

- Authority: normative proposed final component model
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

## Boundary Conventions

Commands may change component-owned state. Queries return snapshots or values
without hidden lifecycle changes, except that an active semantic tool may use
the explicitly named `ensure_runtime` and `ensure_document` commands before it
issues its query. Events carry immutable facts and do not expose internal
mutable objects.

All public tool positions are one-based. Protocol adapters convert them to the
server-negotiated position encoding at the `client` boundary.

## `model`

### Role

Provide immutable, transport-independent values shared by LSP components.

### Owns

- `LspServerDefinition`, provenance, and catalog generation values;
- `LspServerSelection` and `LspServerKey`;
- code positions, ranges, locations, bounded hover payloads, symbols, and query
  result envelopes;
- `CodeDiagnostic` and capability/runtime status values;
- stable error categories for unavailable, denied, timeout, crash, protocol,
  stale, invalid-input, and result-truncated outcomes.

### Depends On

Standard library value types only.

### Commands

None.

### Queries

Pure validation, normalization, and serialization helpers.

### Events

None.

### Out Of Scope

Processes, filesystem reads, policy, logging, presentation, and raw JSON-RPC.

## `catalog`

### Role

Turn declarations into one immutable, admitted catalog generation.

### Owns

- source precedence and provenance;
- schema and semantic validation;
- command/environment admission results;
- catalog generation identity;
- rejected-definition diagnostics.

### Depends On

- `model`;
- Product configuration and extension-declaration inputs;
- injected policy/admission port.

### Commands

- `build_catalog(inputs) -> CatalogSnapshot`
- `refresh(inputs) -> CatalogChanged | CatalogUnchanged`

### Queries

- `snapshot()`
- `definition(definition_id)`
- `definitions_for_language(language_id)`
- `rejections()`

### Events

- `CatalogChanged(old_generation, new_generation, changed_ids)`

### Out Of Scope

Server selection, executable discovery side effects, process launch, and tool
registration.

## `selector`

### Role

Deterministically choose one admitted server definition and workspace root.

### Owns

- language inference from explicit language id, extension, and definition data;
- root-marker search within the admitted workspace;
- priority, specificity, provenance, and stable-id tie-breaking;
- stable hot-path reason codes and on-demand no-match/ambiguity explanations.

### Depends On

- `model`;
- immutable `catalog` snapshots;
- injected workspace/path query port.

### Commands

None.

### Queries

- `select(path, language_id=None) -> LspServerSelectionResult`
- `explain(path, language_id=None) -> BoundedSelectionExplanation`

### Events

None.

### Out Of Scope

Policy approval, executable launch, fallback installation, and connection
health.

## `client`

### Role

Own one initialized JSON-RPC/LSP connection to one process.

### Owns

- Content-Length framing and message decoding;
- request ids and bounded pending-request state;
- write serialization and one reader loop;
- timeouts and cancellation;
- negotiated server capabilities and position encoding;
- typed inbound notifications and restricted server-request handling;
- LSP `initialize`, `initialized`, `shutdown`, and `exit` sequencing.

### Depends On

- `model` protocol values;
- an injected byte-stream/process handle;
- clock, task, and logging ports.

### Commands

- `initialize(params)`
- `notify(method, params)`
- `cancel(request_id)`
- `shutdown()`
- `abort(reason)`

### Queries

- `request(method, params, timeout) -> typed response`
- `snapshot() -> LspConnectionSnapshot`

### Events

- `ServerNotificationReceived`
- `ServerRequestReceived`
- `ConnectionClosed`
- `ProtocolFaulted`

Events are delivered through injected callbacks or an event sink. The client
does not import higher-level components.

H4.1 routes `publishDiagnostics` through a bounded synchronous callback to
`diagnostics`. Client closure also invokes a non-blocking lifecycle callback so
runtime-local diagnostic state is released on graceful exit or failure.

### Out Of Scope

Tool schemas, server ranking, document content ownership, diagnostic delivery,
restart policy, and user presentation.

## `supervisor`

### Role

Own and coordinate every LSP runtime belonging to one capability binding.

### Owns

- the map from `LspServerKey(definition_id, root)` to runtime state;
- startup single-flight and state transitions;
- process launch through an injected admitted launcher;
- initialization readiness, replacement-on-demand, and binding-wide disposal.

Idle retirement, automatic restart budgets/backoff, and live catalog-generation
migration are follow-on Product policies, not P0 supervisor behavior.

### Depends On

- `model`;
- `client` factory;
- immutable catalog definitions selected by `selector`;
- injected Harness `AuthorizedProcessLauncher` and lifecycle ports.

### Commands

- `ensure_runtime(selection) -> LspRuntimeHandle`
- `stop(key)`
- `dispose()`

Follow-on commands may add explicit restart and catalog-generation retirement
after their policies are accepted.

### Queries

- `runtime(key)`
- `snapshots()`

### Events

- `RuntimeStateChanged`
- forwards typed client inbound events tagged with runtime key and generation.

### Out Of Scope

Global singleton state, server definition precedence, document versions, tool
result shaping, and automatic executable installation.

## `documents`

### Role

Keep each server's view of admitted workspace documents ordered and current.

### Owns

- canonical path/URI mapping;
- language id, content hash, open/closed state, and monotonic version;
- ordered `didOpen`, `didChange`, `didSave`, and `didClose` emission;
- disk reconciliation before active queries;
- per-document size and ignore-policy enforcement.

### Depends On

- `model`;
- runtime handles exposing the narrow client-notification port;
- injected workspace read/path policy;
- committed `WorkspaceMutationFact` input in the later passive slice.

### Commands

- `ensure_document(runtime, path) -> DocumentSnapshot`
- `synchronize_from_disk(runtime, path)`
- `apply_mutation(runtime, fact)`
- `mark_saved(runtime, path)`
- `close_document(runtime, path)`
- `retire_runtime(key)`

`apply_mutation` and `mark_saved` are H4 commands. P0 uses only
`ensure_document`, `synchronize_from_disk`, runtime retirement, and any
explicit close required while the Server remains alive.

### Queries

- `snapshot(runtime, path)`
- `open_documents(runtime)`

### Events

- `DocumentSynchronized(key, path, version, content_hash, cause)`
- `DocumentClosed(key, path)`
- `DocumentSyncRejected(key, path, reason)`

### Out Of Scope

Editing files, inferring edits from tool-result text, selecting servers,
parsing language syntax, and presenting diagnostics.

## `diagnostics`

### Role

Maintain bounded current code-diagnostic state. H4.2 adds model-delivery deltas.

### Owns

- replacement sets keyed by runtime, canonical document, and accepted version;
- normalization, deduplication, severity mapping, and stale rejection;
- per-document and total-memory limits;
- H4.2 pending-delivery markers, per-turn limits, and bounded expiry;
- H4.2 distinction between current state and newly deliverable delta.

### Depends On

- `model`;
- canonical path and document-version query ports;
- context-budget policy.

### Commands

- `replace_publication(runtime, uri, version, diagnostics)`
- `clear_runtime(key)`
- H4.2 `mark_delivered(delivery_id)`
- H4.2 `expire(now)`

### Queries

- `current(path=None)`
- H4.2 `pending_delta(budget) -> DiagnosticDelivery`
- `snapshot()`

### Events

- `DiagnosticStateChanged(paths, delivery_id)`

### Out Of Scope

Harness operational `DiagnosticRecord`, process restart, file mutation, model
calls, and append-only retention of every publication.

## `tools`

### Role

Expose Coding Product semantic queries as bounded, structured tools.

### Owns

- tool names, descriptions, input schemas, and output schemas;
- path/position/query validation;
- selection, runtime, and document orchestration for one invocation;
- LSP method-to-Product-result normalization;
- per-query truncation, pagination token, and error projection.

### Depends On

- `model`;
- `selector` query port;
- `supervisor` runtime command port;
- `documents` synchronization command port;
- narrow `client` request port from the selected runtime;
- Harness tool-definition and context-budget abstractions.

### Commands

- `register(tool_runtime, activation)`
- `unregister(tool_runtime)`

### Queries

- `invoke(tool_name, arguments) -> LspToolResult`
- `definitions() -> tuple[ToolDefinition, ...]`

The P0 family contains `inspect_symbol` and `document_outline`.
`inspect_symbol` covers definition, references, hover, and implementation.
Workspace symbols and call hierarchy are later compatible extensions.

### Events

- ordinary Harness tool invocation/result events; no private parallel event
  universe.

### Out Of Scope

Raw method access, command selection, process maps, passive-diagnostic storage,
and architecture judgments.

## `binding`

### Role

Compose one target `coding.lsp` Mounted Capability for one Coding Session.
`coding.lsp` remains the Capability ID; the live binding additionally records
its Session scope instance and generation. Workspace identity is an explicit
configuration and binding-signature input rather than a second scope. P0 does
not share the live runtime across Sessions.

### Owns

- capability mount interpretation;
- construction and lifecycle order for all components;
- tool-family registration/activation;
- notification routing from client/supervisor to documents/diagnostics;
- catalog refresh coordination and complete disposal.

Workspace warm-up and subscription to committed mutations are follow-on
behaviors.

### Depends On

- all other LSP component ports;
- Coding Product capability/profile/configuration APIs;
- the top-level `harness.workspace` Capability, narrowed to admitted read and
  authorized process-launch facets;
- Harness policy, tool, lifecycle, and context interfaces that remain internal
  enforcement or injected wiring rather than more top-level DAG nodes;
- Coding session diagnostic/context integration ports.

The static dependency uses `coding.lsp -> harness.workspace`; `A -> B` means A
depends on B. Concrete Protocol and adapter names are implementation wiring,
not public dependency identities. See
[Capability Dependency And Mount Lifecycle](../../harness/capability-dependency-and-mount-lifecycle.md).

### Commands

- `mount(configuration)`
- `activate_tools(owner=None)`
- `deactivate_tools(owner=None)` when the generic runtime supports leases;
- `refresh(inputs)`
- `dispose()`

The later passive/warm-up slice may add `warm_workspace()` and
`handle_workspace_mutation(fact)`.

### Queries

- `capability_snapshot()`

### Events

- `CodingLspCapabilityChanged`

### Out Of Scope

Agent-loop implementation, Method execution, tool approval decisions, UI
rendering, and ownership of cross-session global state.

## `status`

### Role

Project catalog, runtime, document, and diagnostic health without mutating it.

### Owns

- stable status and doctor output schemas;
- aggregation and redaction rules;
- user-facing remediation hints for missing, denied, crashed, or incompatible
  servers.

### Depends On

Read-only snapshots from `catalog`, `supervisor`, `documents`, and
`diagnostics` plus Product configuration.

### Commands

- Session `/lsp status` projects the current runtime snapshot without mutation;
- Session `/lsp stop <server-id> <root>` calls `binding`/`supervisor` explicitly;
- the independent `loushang lsp status|doctor` commands remain Catalog-only.

Richer restart controls are follow-on Product operations. The current Session
command is contributed by Coding through the shared command catalog; Harness
does not acquire an LSP command identifier. Remote clients execute it through
Harness's Product-neutral `execute_command` RPC route.

### Queries

- `status(path=None)`
- `doctor(definition_id=None)`
- `render_cli(snapshot)`
- `project_sdk(snapshot)`

### Events

None.

### Out Of Scope

Hidden process startup, repair, executable installation, tool invocation, and
protocol logging with unredacted source content.

## Cross-Component Boundary Scenarios

### Active query

```text
tools -> selector.select
      -> supervisor.ensure_runtime
      -> documents.ensure_document
      -> client.request
      -> tools normalize and bound result
```

### Later passive diagnostic feedback

```text
workspace mutation -> binding
                   -> documents.apply_mutation
server notification -> binding
                    -> diagnostics.replace_publication
Coding turn assembly -> diagnostics.pending_delta
                     -> mark_delivered after attachment commits
```

### Later live refresh

```text
binding -> catalog.refresh
        -> supervisor retires changed definitions
        -> documents/diagnostics clear only retired runtime state
        -> status exposes the new generation
```

### Disposal

```text
binding stops mutation subscriptions and tool activation
  -> supervisor cancels requests and shuts down processes
  -> documents and diagnostics release runtime state
  -> lifecycle owner confirms no child task/process remains
```

## Hard Boundary Decisions

1. A mounted tool family does not imply an eager process.
2. A declaration is data, not execution authority.
3. The workspace filesystem is authoritative after committed mutations.
4. The client accepts only typed, admitted operations; tools never expose raw
   JSON-RPC methods.
5. `CodeDiagnostic` is not a Harness operational diagnostic.
6. The runtime is owned by one session/workspace binding, never a module-level
   singleton.
7. `coding.arch` integration uses an optional semantic-fact protocol and cannot
   own LSP processes. The current Capability plan has no `coding.arch ->
   coding.lsp` edge; a future optional edge requires a separate accepted
   Product decision.
8. Harness provides a generic authorized `ProcessHandle` and internal session
   cleanup safety net; Coding retains LSP pooling, readiness, protocol, and
   graceful-shutdown semantics. If restart or idle policies are later added,
   Coding owns them.
