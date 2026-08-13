# Coding LSP Specification

[Coding LSP Architecture](README.md) | [Requirements](requirements.md)

## Status

- Authority: normative proposed specification
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

## 1. Naming And Packaging

The canonical identifiers are:

```text
Product capability id:  coding.lsp
Tool-family pack id:    coding.lsp.tools
Python package:         loushang.coding.lsp
```

`code.lsp` may be used conversationally, but must not become a second config or
runtime identity.

The initial package shape is expected to follow the accepted components rather
than this exact file list. A representative mapping is:

```text
src/loushang/coding/lsp/
├── model.py
├── catalog.py
├── selector.py
├── client.py
├── supervisor.py
├── documents.py
├── diagnostics.py
├── tools.py
├── tool_pack.py
├── binding.py
├── commands.py
└── status.py
```

## 2. Capability And Startup Semantics

### 2.1 Mount mode

`coding.lsp` uses the existing Product capability mount model:

| Mode | Tool definition behavior | Server process behavior |
|---|---|---|
| `disabled` | LSP tools are not registered for the Session | no Server starts |
| `on_demand` | definitions are admitted but not in the active Agent tool set | activation alone does not start a Server; first relevant operation does |
| `always` | tools are incrementally added to the default active set | first relevant operation still starts the Server lazily |

`always` means “always model-visible”, not “start every language server at
process boot”. This preserves high-frequency usability without paying every
language's cold-start and memory cost.

The first implementation should default to `on_demand`, matching the existing
optional-capability contract and the security sensitivity of external
executables. A later Product decision may promote it to `always` after the
reliability and context-cost gates are measured. Users can select the
high-frequency profile immediately:

```bash
loushang-coding --capability coding.lsp=always
```

### 2.2 Runtime warm-up

P0 has one process-start rule:

```text
lazy       start on first relevant query or sync demand; default
```

Workspace warm-up may later become a separate Coding-owned setting. It must
still start only Servers that pass admission and workspace-root selection, and
must not change tool allow-lists or approval policy.

### 2.3 Activation ownership

Product defaults, CLI/config selection, manual Session tool selection, a Skill,
and a future Method/Work step may all request the same Product capability.
Long-term activation must be owner-aware so one owner cannot deactivate another
owner's request.

P0 may use the current Session active-tool set without temporary Skill leases.
Generic owner-scoped activation is not a prerequisite for the LSP protocol
runtime.

## 3. Configuration Contract

Coding `ControlConfig.capabilities` continues to own the mount selection. LSP
details stay out of Harness configuration and use a Coding-owned `lsp.json`.
The user-level file is `~/.loushang/coding/lsp.json`; the project-level file is
`.loushang/lsp.json`. The implemented shape is:

```json
{
  "servers": [
    {
        "id": "pyright",
        "command": ["pyright-langserver", "--stdio"],
        "language_extensions": {
          "python": [".py", ".pyi"]
        },
        "root_markers": ["pyproject.toml", "setup.cfg", ".git"],
        "priority": 100,
        "environment": {},
        "initialization_options": {},
        "settings": {},
        "startup_timeout_seconds": 20,
        "request_timeout_seconds": 15,
        "shutdown_timeout_seconds": 3
    }
  ]
}
```

The mount remains in ordinary Coding settings, for example
`{"capabilities": {"coding.lsp": "always"}}`, or can be overridden for one
process with `--capability coding.lsp=always`.

Rules:

- `command` is a non-empty argv array; no shell expansion is applied.
- `language_extensions` explicitly maps every document language id to its file
  extensions; extensions are normalized to lowercase with a leading dot and
  cannot belong to two languages within one definition.
- language ids and their extension lists are non-empty and unique within one
  definition.
- P0 root markers are literal relative paths and cannot escape the Coding
  workspace. Glob/pattern markers are deferred until a concrete need appears.
- timeouts are bounded by Product policy.
- `environment` contains explicit overrides, not a serialized inherited
  environment.
- unknown fields produce configuration diagnostics rather than being silently
  interpreted.
- P0 supports stdio only and has no `transport` field that promises an
  unimplemented socket mode.
- Product defaults are admitted only when their executable is found; Loushang
  never installs a language server implicitly.
- Until a general workspace-trust runtime exists, project config may tune a
  Product-default or user-admitted server only when its complete argv exactly
  matches that trusted definition. It cannot introduce process-environment
  overrides; the admitted user-level environment is inherited unchanged. A
  custom command must first be declared in the user-level file.

This conservative project rule is the P0 substitute for the future general
workspace-trust gate.

Built-in presets use these nearest-root contracts:

| Server | Root markers |
| --- | --- |
| Pyright | `pyrightconfig.json`, `pyproject.toml`, `.git` |
| TypeScript Language Server | `tsconfig.json`, `jsconfig.json`, `package.json`, `.git` |
| rust-analyzer | `rust-project.json`, `Cargo.toml`, `.git` |
| gopls | `go.work`, `go.mod`, `.git` |
| clangd | `.clangd`, `compile_commands.json`, `compile_flags.txt`, `.git` |

The TypeScript preset recognizes JavaScript, JavaScript React, TypeScript, and
TypeScript React as distinct language ids. Every built-in preset starts only
after a matching semantic query. If its executable is absent, catalog discovery
reports it as unavailable without installing or starting anything.

## 4. Core Data Contracts

The exact dataclass organization may evolve, but these semantic records are
required.

### 4.1 `LspServerDefinition`

```python
@dataclass(frozen=True)
class LspServerDefinition:
    id: str
    command: tuple[str, ...]
    language_extensions: Mapping[str, tuple[str, ...]]
    root_markers: tuple[str, ...] = ()
    priority: int = 0
    environment: Mapping[str, str] = ...
    initialization_options: Mapping[str, object] = ...
    settings: Mapping[str, object] = ...
    startup_timeout_seconds: float = 20.0
    request_timeout_seconds: float = 15.0
    shutdown_timeout_seconds: float = 3.0
    source: LspDefinitionSource = ...
```

`source` identifies Product/config/package/extension provenance and trust scope.
Inherited environment and resolved executable path are runtime materialization
facts, not part of the reusable declaration.

Workspace warm-up, idle retirement, and automatic restart budgets are deferred
Product policy and are not P0 declaration fields.

### 4.2 `LspServerSelection`

```python
@dataclass(frozen=True)
class LspServerSelection:
    definition_id: str
    language_id: str
    workspace_root: Path
    file_path: Path
    reason_code: str
```

The hot-path selection record is small and deterministic. `reason_code` is a
stable value such as `explicit_override`, `nearest_root`, or `priority`.
Rejected-candidate details such as `not_admitted`, `lower_priority`,
`root_not_matched`, or `binary_unavailable` are computed only by an explicit
selection-explanation/status query; every semantic tool call does not allocate
or return the complete candidate set.

### 4.3 `LspServerKey`

One live Server is keyed by both definition and resolved root:

```text
(definition_id, canonical_workspace_root)
```

This permits one monorepo session to run separate instances for independent
project roots when the language server requires it.

### 4.4 Code locations and results

```python
@dataclass(frozen=True)
class CodePosition:
    line: int       # public API: 1-based
    character: int  # public API: 1-based display/code-point column

@dataclass(frozen=True)
class CodeRange:
    start: CodePosition
    end: CodePosition

@dataclass(frozen=True)
class CodeLocation:
    path: str | None
    uri: str
    range: CodeRange
    external: bool = False
    readable: bool = True

@dataclass(frozen=True)
class CodeHover:
    contents: str
    kind: Literal["markdown", "plaintext"]
    range: CodeRange | None = None

@dataclass(frozen=True)
class CodeQueryResult:
    items: tuple[CodeLocation | CodeHover, ...]
    count: int
    truncated: bool
    server_id: str
    document_version: int | None
    readiness: str
    warnings: tuple[str, ...] = ()
```

The protocol adapter converts public 1-based positions to LSP 0-based positions
using the Server-negotiated UTF-8/UTF-16/UTF-32 encoding. It must not assume
Python string indexing equals the Server's character units.

### 4.5 `CodeDiagnostic`

```python
@dataclass(frozen=True)
class CodeDiagnostic:
    server_id: str
    uri: str
    path: str | None
    version: int | None
    severity: str
    message: str
    range: CodeRange
    code: str | None = None
    source: str | None = None
    tags: tuple[str, ...] = ()
    received_at: float = 0.0
    stale: bool = False
```

This type remains separate from Harness operational diagnostics.

## 5. Catalog And Admission

### 5.1 Sources

Definitions may eventually come from these source tiers. The default target
precedence, highest first, is:

1. session/CLI override;
2. project Coding config;
3. user Coding config;
4. admitted package or extension contribution;
5. Product distribution defaults.

P0 needs only explicit Coding configuration and optional Product defaults. It
must establish the same normalized contribution record so new sources do not
rewrite the runtime.

### 5.2 Catalog pipeline

```text
discover declarations
  -> parse and normalize
  -> collect diagnostics
  -> merge by Product precedence
  -> apply workspace trust and source policy
  -> resolve executable availability
  -> publish immutable admitted catalog snapshot
```

Catalog refresh prepares a complete new snapshot before publishing it. Invalid
definitions are excluded individually. A generation id prevents stale async
binary probes or initialization from overwriting a newer snapshot.

### 5.3 Execution authority

Catalog admission means the declared executable is eligible under Product
source, trust, and allow-list policy. It does not itself perform or irrevocably
authorize a process launch. `supervisor` must submit the frozen executable,
arguments, root, and environment to the effective Harness execution policy and
profile/Sandbox path when a runtime is first needed.

The P0 Coding policy silently allows an explicitly configured or Product-
default admitted Server. Policy evaluation, fingerprinting, profile ceiling,
Sandbox enforcement and audit still run; an interactive approval is not the
normal LSP startup path. User policy may override this with `ask` or `deny`.

A later model query cannot substitute the command or environment. Authorization
permits one exact spawn rather than creating a continuing authority lease. A
replacement process is evaluated and authorized again under current policy;
an unchanged admitted launch normally remains non-interactive.

Tool inputs never contain Server command, cwd, environment, initialization
options, or arbitrary LSP method names.

## 6. Server Selection

Given a canonical file path, selection proceeds as follows:

1. reject paths outside the Coding workspace/read roots;
2. determine an explicit or extension-derived language id;
3. collect admitted definitions matching the language or normalized extension;
4. search upward from the file for each definition's root markers, stopping at
   the Coding workspace boundary;
5. apply explicit project override, then priority, then the stable definition
   id as a final deterministic tie-breaker;
6. return the selected root and a stable reason code.

An explicit selection-explanation query reruns the same pure decision and
returns bounded candidate/rejection details for diagnostics or status. It is
not part of the model-tool hot path.

No match returns a typed `unsupported_language` result and optional install or
configuration guidance. It does not start a fallback arbitrary executable.

## 7. Runtime And Lifecycle

### 7.1 Scope

`CodingLspRuntime` is created for one Coding Product session and knows its
admitted workspace roots. It owns one `LspServerSupervisor`, which in turn owns
zero or more keyed Server runtimes.

There is no module-global Manager. The complete binding uses one immutable,
execution-scope-bound `AuthorizedProcessLauncher`; runtime-profile replacement
disposes the binding before installing another scope. Session replacement/
disposal owns shutdown.

### 7.2 State model

```text
declared
  -> admitted
  -> stopped
  -> starting
  -> initializing
  -> ready
       |  \
       |   -> stopping -> stopped
       -> degraded/error -> failed
```

`failed -> starting` is permitted only when a later demand obtains a new
launch authorization. P0 has no background `restarting` state.

`readiness` is distinct from lifecycle state. A Server can be `ready` for
requests while still reporting `indexing` or partial workspace results.

### 7.3 Startup

`ensure_started(server_key)` is single-flight. It:

1. Coding freezes executable/argv, cwd, complete scrubbed environment, and its
   LSP startup budget;
2. calls the scope-bound launcher with an operation correlation id; Harness
   authorizes the frozen process effect, resolves the effective execution/
   Sandbox profile, and launches without a shell;
3. starts stderr capture with a rolling hard limit;
4. starts one JSON-RPC reader task;
5. sends `initialize` with honest client capabilities;
6. validates the response and negotiated position encoding;
7. sends `initialized`;
8. publishes state and readiness facts.

The caller then invokes `documents.ensure_document` for the requested file
before issuing the semantic query. Supervisor startup does not own document
selection or reopen policy.

### 7.4 Requests and notifications

- One reader task parses all inbound messages and dispatches by id/method.
- One write lock preserves message framing and ordering.
- Pending requests live in a bounded id-to-future table.
- A request timeout removes its pending entry and sends `$/cancelRequest` when
  supported.
- Notifications are dispatched to bounded handlers without allowing a slow
  diagnostic consumer to block the protocol reader.
- Server-to-client requests are handled only by an explicit allow-list.

P0 handlers:

| Server request | Behavior |
|---|---|
| `workspace/configuration` | return only the admitted definition's settings |
| `workspace/applyEdit` | reject |
| `window/showMessageRequest` | reject or select no action |
| unknown request | JSON-RPC method-not-found/error response |

H4.1 routes `textDocument/publishDiagnostics` notifications synchronously to a
bounded session-local Inbox. The handler accepts only already-open documents,
normalizes at most a fixed number of items, and never performs I/O or awaits a
consumer on the protocol reader. Rejected publications increment a bounded
status counter. No diagnostic payload is injected into model context or logged.
Unknown notifications are ignored with at most bounded metadata diagnostics.

Client capabilities must disable dynamic features that the client does not
implement.

### 7.5 Shutdown and recovery

Graceful shutdown sends `shutdown`, awaits its response within budget, sends
`exit`, then waits for process exit. Timeout falls back to terminate and then
kill.

Unexpected process exit:

- fails all pending requests;
- records an operational Problem/diagnostic;
- marks document state as needing reopen;
- marks the runtime failed and performs no background retry;
- allows a later demand to obtain a new authorization and start a replacement.

Automatic retry budgets and exponential backoff are later Product policies.

## 8. Document Synchronization

### 8.1 State

For each `(server_key, document_uri)`, the document component stores:

- canonical path and URI;
- language id;
- open/closed state;
- monotonic version;
- last synchronized content hash;
- last committed workspace mutation sequence, when available;
- content snapshot only while needed and within a per-document size limit.

### 8.2 Ordering

All transitions for one document use a per-document async queue/lock. P0 active
reconciliation is:

```text
read authoritative disk content
  -> didOpen(version=1) when not open
  -> otherwise, if content changed:
       increment version
       await didChange
  -> release queue
```

`didOpen` uses version 1. Every content change increments exactly once.
Unchanged content does not emit `didChange`.

P0 has no native committed-save signal and therefore does not synthesize
`didSave` during pre-query reconciliation. H4 emits ordered `didChange` then
`didSave` after a successful native write/edit mutation. `didClose` is sent only
if an open document is retired while its Server remains alive; Server/session
shutdown does not require a separate P0 close policy.

P0 uses full-text synchronization and declares the corresponding client
capability. Incremental changes are an optimization after correctness tests.

### 8.3 Mutation sources

The later target source is a Harness-owned Product-neutral
`WorkspaceMutationFact` emitted after a native workspace operation commits.
Its first shape contains mutation identity, canonical path, `created|updated`
kind, per-path sequence, and occurrence time. Delete/move, actor, content hash,
multi-path operations, watcher coverage, and source content are deferred.

Until that event exists, P0 may synchronize the requested file immediately
before each semantic query. Passive edit feedback is completed only after the
committed event path is available; Edit/Write must not import `coding.lsp`.

For shell/external-editor changes, pre-query hash comparison is mandatory. A
future bounded file watcher may provide lower-latency sync.

### 8.4 Close

Documents close when:

- the owning Server stops;
- the Coding session disposes;
- the document is evicted by an explicit bounded-open-document policy;
- an applicable context/working-set policy requests close.

Conversation compaction alone does not imply LSP close unless the Product has
defined that working-set relationship.

## 9. Model-Facing Tools

The first tool pack is:

```python
CODING_LSP_TOOL_PACK = ToolPackDefinition(
    name="coding.lsp.tools",
    tools=(
        "inspect_symbol",
        "document_outline",
    ),
    metadata={"product_capability": "coding.lsp"},
)
```

`search_workspace_symbols` is added later only after non-empty query and
paging/limits are implemented.

### 9.1 `inspect_symbol`

```text
inspect_symbol(
    path,
    line,
    character,
    query="definition|references|hover|implementation",
    include_declaration=true,
    limit=50,
)
```

Rules:

- `path` must resolve through the existing workspace read boundary;
- line/character are positive and public 1-based values;
- unsupported Server capabilities return `readiness="unsupported"` plus a typed
  warning without sending a speculative protocol request;
- `include_declaration` is sent only in the LSP references context;
- definition, references, and implementation normalize `Location` and
  `LocationLink` responses into bounded `CodeLocation` items;
- hover normalizes `MarkupContent` and legacy `MarkedString` variants into one
  bounded `CodeHover`; the initial hard content limits are 12,000 characters
  and 64 legacy parts;
- every result is bounded and normalized.

Call hierarchy is a later compatible extension and, when added, uses
prepare-call-hierarchy followed by the appropriate callers/callees operation.

### 9.2 `document_outline`

```text
document_outline(path, depth=4, limit=200)
```

It returns a bounded hierarchy of symbols. It does not require dummy position
fields.

### 9.3 `search_workspace_symbols`

```text
search_workspace_symbols(query, root=".", kinds=None, limit=50)
```

`query` must be non-empty. The Server selection/root are explicit in the
result. Empty-query whole-workspace enumeration is forbidden.

### 9.4 Output projection

Tool outputs preserve structured items for the model and SDK/RPC projections.
Presentation renderers may additionally produce concise text rows, but rendered
text is not the authoritative result.

Each operation has its own maximum. A generic 100,000-character escape hatch is
not the primary bounding mechanism.

## 10. Passive Diagnostic Feedback

### 10.1 Authoritative current set (H4.1 implemented)

LSP diagnostics are published as a complete set for a Server/document. The
Inbox replaces the current set for that key, including replacement by an empty
set.

If a version is present:

- older-than-current diagnostics are retained only for debug metrics and not
  delivered;
- current-version diagnostics are eligible;
- future-version diagnostics are treated as protocol anomalies.

If no version is present, records are marked unversioned and tied to the latest
observed document state without claiming exact version authority.

The initial implementation scans at most 512 raw items per publication, retains
at most 100 normalized diagnostics per document, 128 documents, 2,048 total
diagnostics, and a 256K-character diagnostic accounting budget per session. It
also bounds individual message, code, source, and tag values. The Inbox evicts
the least-recently-replaced document set when a total limit is exceeded and
records omission, truncation, malformed, version-anomaly, and eviction counters.

### 10.2 Pending delivery (H4.2 deferred)

The Inbox derives a delta against delivered keys. A diagnostic key includes
Server, URI, version class, range, severity, code, source, and message.

The following values are illustrative H4 starting points, not P0 defaults or
acceptance gates:

```text
maximum per file: 10
maximum per turn: 30
delivered-file LRU: bounded
priority: error -> warning -> information -> hint
```

Measured H4 implementation work selects the exact Coding Product defaults. The
projection reports how many diagnostics were omitted.

### 10.3 Delivery point (H4.2 deferred)

Pending diagnostics are attached after a completed tool batch or before the
next model turn, not injected while a model response is streaming. A debounce
may coalesce rapid Server publications.

The model sees only new, actionable, bounded diagnostics. TUI/SDK inspection may
query the full bounded current set independently of model delivery state.

## 11. Security And Policy

### 11.1 Trust and launch

Starting a Server is an effectful runtime operation even when the eventual
query is read-only. Project-local or extension definitions require workspace
trust and Product admission before launch, and launch still follows Harness
execution policy. Explicitly admitted P0 definitions normally receive a silent
`allow`; interactive approval is a policy override, not the default workflow.

The launch request freezes:

- resolved executable and argv;
- canonical cwd/root;
- scrubbed effective environment;

Harness resolves the current effective execution/Sandbox profile during the
authorized start. Host process, stderr, write, and termination limits come
from session-owned Harness configuration and cannot be enlarged by the launch
request. Coding-owned protocol timeouts are not Process Hosting fields.

### 11.2 Environment

Coding materializes the complete effective environment from a Product-approved
minimal baseline plus explicit definition overrides. Harness freezes that
supplied environment and must not reread or merge `os.environ` after the launch
request crosses the boundary. Secrets must not be copied into status,
diagnostics, approval records, or model-visible results.

### 11.3 Returned locations

Every returned URI is parsed and canonicalized:

- workspace paths are projected workspace-relative;
- paths inside additional admitted read roots are marked external;
- unreadable/unadmitted targets retain an opaque identity but are not opened or
  exposed as readable local paths;
- non-file URIs remain typed external locations.

The LSP Server cannot expand the Agent's filesystem authority.

### 11.4 Server-initiated actions

P0 denies:

- `workspace/applyEdit`;
- arbitrary command execution;
- arbitrary configuration reads;
- dynamic registration that would imply unsupported filesystem watching or
  mutations.

Future support requires a normal Product policy/approval path and must never be
granted by Server capability negotiation alone.

## 12. Status And Operational Diagnostics

The target status surface returns bounded records for:

- catalog generation and definition provenance;
- admitted/rejected/unavailable definitions;
- selection decisions;
- Server lifecycle/readiness;
- initialization/crash/replacement failures;
- request latency and timeout counts;
- open document count;
- current/pending diagnostic counts;
- result and diagnostic truncation counts.

H4.1 exposes accepted/rejected publication counts and current diagnostic
document/item counts per live runtime. Detailed Inbox omission and truncation
counters remain internal until H4.2 defines their stable SDK/TUI projection.

Source text, request payload contents, inherited environment, and unrestricted
stderr are excluded. Stderr is kept in a bounded operational buffer or artifact
with existing policy.

Recommended non-model commands/queries are:

```text
loushang lsp status                     # offline Catalog scope
loushang lsp doctor                     # offline Catalog scope
/lsp status                             # current Session runtime scope
/lsp stop <server-id> <root>            # current Session runtime scope
session.get_lsp_status()                # SDK, read-only
await session.stop_lsp_server(...)      # SDK, explicit mutation
```

The independent CLI never constructs a Session and therefore cannot claim to
inspect a live child process. Session commands use the normal Product command
catalog: TUI dispatches that catalog locally, while RPC uses the generic
`execute_command` route after discovery. Neither surface needs an LSP-specific
Harness route.
These are Product operations, not model tools. A richer explicit restart
command may be added after the replacement policy is measured; in P0, stop plus
the next demand is sufficient.

## 13. Package And Extension Contributions

P0 config is Product-owned. The normalized future contribution is:

```python
@dataclass(frozen=True)
class CodingLspServerContribution:
    definition: LspServerDefinition
    source_info: SourceInfo
    permission_requirements: tuple[str, ...]
```

The contribution is adapted by Coding into its catalog. It is not a new
`ExtensionSurfaceType = "lsp"` in Harness unless a later cross-product need
justifies a generic provider-contribution surface.

An extension contributes declarations only. Refresh can replace its
definitions. Live replacement policy is deferred; P0 adopts changed definitions
on a new binding/session rather than migrating a running Server.

## 14. Relationship To Harness

This design reuses existing Harness mechanisms for:

- tool definitions, packs, materialization, and active-tool rebinding;
- policy, approval, execution profile, and sandbox constraints;
- workspace canonicalization and, for the later passive slice, mutation
  serialization;
- context budgets and result truncation;
- Product session lifecycle/disposal and refresh order;
- operational diagnostics/status records.

It also requires the Product-neutral additions specified by the
[Harness Foundation](harness-foundation.md):

```text
Authorized process launch and live raw-byte `ProcessHandle`
Session-owned `ProcessHost` and close-all safety net
Lifetime sandbox binding for hosted processes
Later WorkspaceMutationFact emitted after a committed workspace mutation
```

LSP protocol names, Server definitions, document state, CodeDiagnostic, tools,
and Product defaults remain in Coding.

The current short-lived `ExecService` remains a one-shot API and is not reused
as a bidirectional LSP connection. Coding receives an injected authorized
`AuthorizedProcessLauncher` from Harness. Harness owns process mechanics and
fallback disposal; Coding owns process pooling, LSP readiness, protocol
shutdown, and replacement-on-demand. Future idle/restart policy also belongs to
Coding, not Harness.

## 15. Relationship To `coding.arch`

No P0 dependency exists in either direction.

Later, `coding.arch` may define a consumer-owned semantic-fact protocol and the
Coding Product may inject an LSP-backed adapter. The optional facts can improve
symbol ownership, implementation discovery, and change-impact evidence.

Import graph construction, SCC, dependency direction, boundary rules, and CI
gates remain deterministic and LSP-independent.

## 16. Initial Implementation Slice

P0 is intentionally narrower than the full target:

Harness Foundation H1-H2 is a prerequisite for production use. Protocol unit
work may proceed against fake Process Hosting ports, but Coding must not ship a
direct subprocess launcher as a temporary production bypass.

### Included

- `coding.lsp` capability id and `coding.lsp.tools` pack;
- explicit Coding config and catalog validation;
- deterministic extension/language/root selection;
- session/workspace-scoped stdio Server runtime;
- single-reader JSON-RPC client;
- initialize/shutdown and lazy startup;
- document open and pre-query full-text resync with monotonic versions;
- definition, references, hover, implementation, and document outline;
- structured bounded output;
- status/doctor;
- explicit stop; after a crash or stop, the next demand may reauthorize and
  start a replacement;
- H4.1 bounded, version-aware passive diagnostic reception and lifecycle
  cleanup, without model delivery;
- fake Server tests;
- path-scoped CI compatibility gates against pinned real Pyright, TypeScript,
  gopls, and rust-analyzer Servers; the TypeScript gate pins the language-server
  wrapper and its TypeScript runtime as a tested pair, the gopls gate pins both
  Go and gopls, and the rust-analyzer gate uses the component from one pinned
  Rust toolchain;
- clean degradation when no Server exists.

### Deferred

- committed workspace mutation event and H4.2 diagnostic delivery;
- workspace warm-up and idle eviction;
- automatic restart budgets and exponential backoff;
- live catalog-generation migration;
- package/extension contributions;
- workspace symbol and call hierarchy;
- Server pooling across sessions;
- TCP/socket transport;
- automatic installation;
- Server-initiated edits/actions;
- integration into `coding.arch`.

This ordering validates the risky protocol/lifecycle core before adding
background context injection.

## 17. Requirement Traceability

| Requirement | Primary specification area | Owning components |
| --- | --- | --- |
| R1, R6 | capability/startup and lifecycle | `binding`, `supervisor`, `tools` |
| R2-R4 | configuration, catalog, and admission | `catalog`, `binding` |
| R5 | Server selection | `selector` |
| R7 | runtime/protocol lifecycle | `client`, `supervisor` |
| R8-R9 | model-facing tools and result projection | `tools`, `model` |
| R10-R11 | document synchronization | `documents`, `binding` |
| R12-R13 | passive diagnostics | `diagnostics`, `model`, `binding` |
| R14-R15 | scope, refresh, and disposal | `binding`, `supervisor` |
| R16 | status and Product operations | `status`, `binding`, `supervisor` |
| R17 | package/extension contributions | `catalog`, `binding` |
| R18 | `coding.arch` relationship | Product binding through an optional port |
| N1-N8 | security, invariants, budgets, tests, status | all components; enforced at each owning boundary |
