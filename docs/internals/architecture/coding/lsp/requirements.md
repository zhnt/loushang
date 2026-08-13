# Coding LSP Requirements

[Coding LSP Architecture](README.md)

## Status

- Authority: normative proposed requirements
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

Where a requirement contains a later target,
the narrower P0 contract in [Specification](specification.md#16-initial-implementation-slice)
is normative for the first implementation.

## Purpose

Coding agents currently obtain code facts primarily through file reads, text
search, deterministic analyzers, and explicit compiler/test commands. Those
mechanisms remain necessary, but they do not provide a low-latency,
language-aware answer to questions such as:

- What definition does this symbol resolve to?
- Which references and implementations will this change affect?
- What type or documentation is attached to this expression?
- Which new syntax or type diagnostics appeared after the last edit?

`coding.lsp` must add that semantic feedback without turning an editor, a
language-specific compiler, or arbitrary subprocess logic into Agent-core
responsibilities.

## Stakeholders And Actors

- Coding users configuring or consuming code intelligence.
- Coding sessions and agents issuing semantic queries.
- Coding CLI, SDK, RPC, and TUI surfaces exposing status and results.
- Coding Product policy admitting capability and Server definitions.
- Packages or extensions contributing optional Server definitions.
- External language-server executables.
- Harness tool, policy, approval, workspace, lifecycle, and context mechanisms.
- `coding.arch`, as a future optional consumer of semantic facts.

## Functional Requirements

### R1. Product capability identity

The feature must be represented as the opaque Coding Product capability
ID `coding.lsp` and use the existing `disabled | on_demand | always` Mount
Policy. The ID names the definition; the initial target activation is a
Session-scoped Mounted Capability and must retain its Session scope and
generation identity. Workspace identity is configuration and a required
binding-signature input, not a second Mount scope. P0 does not pool a live LSP
runtime across Sessions.

The capability id must not be replaced by a Harness tool-pack id. Family packs
may use qualified ids such as `coding.lsp.tools`.

The accepted target top-level plan declares
`coding.lsp -> harness.workspace`, meaning LSP depends on the Harness workspace
Capability. Required read and authorized process-launch facets are admitted
separately and do not become additional DAG nodes. Dependency and Mount
terminology follows
[Capability Dependency And Mount Lifecycle](../../harness/capability-dependency-and-mount-lifecycle.md).

### R2. Editor independence

The capability must work without VS Code, Cursor, or another IDE. Loushang is
the LSP client; a separately available language-server executable provides the
language semantics.

### R3. Declarative Server definitions

Coding must accept validated Server definitions that describe at least:

- stable Server id and source provenance;
- executable command and fixed arguments, without shell interpolation;
- supported languages and file extensions;
- workspace-root selection hints;
- deterministic priority;
- initialization options and allowed settings;
- environment overrides and inheritance policy;
- startup, request, and shutdown budgets.

Idle-lifetime and automatic-recovery policy are later Product settings, not
part of the initial Server definition.

The first implementation must accept explicit Coding configuration. Package and
extension contributions may be added through the same Product-owned data shape.

### R4. Admission before execution

Discovering a Server definition must not grant execution authority. Coding
Product policy must admit the definition after workspace trust, extension or
package policy, and configured allow-list checks. Actual process launch must
also pass the effective Harness execution policy; catalog admission and launch
authorization are separate gates.

The first version must not silently install missing binaries.

Launch authorization permits exactly one frozen spawn. The resulting process
continues under the Sandbox restrictions actually enforced for its lifetime;
the authorization is not a lease or reusable token. Starting a replacement
Server is a new launch under current policy.

P0 explicitly configured or Product-default admitted Servers should receive a
silent `allow` Policy decision and must not require routine interactive
approval. User policy may still choose `ask` or `deny`, and future untrusted
project/extension contributions may use stricter defaults. Silent launch does
not bypass fingerprint, profile-ceiling, Sandbox, audit, or cleanup checks.

The injected launcher is bound to one immutable execution scope containing the
actor, approval/audit bindings, and execution-profile ceiling. One LSP binding
must not reuse a Server process across launcher scopes. The exact executable,
argv, cwd, and complete effective environment participate in launch consistency
validation even though environment values remain absent from approval and
audit presentation.

### R5. Deterministic Server selection

For a file, Coding must select a Server using deterministic inputs including:

- canonical file path;
- language/file-extension match;
- nearest valid workspace root;
- configured root markers;
- explicit priority and user override;
- admission and availability state.

Hot-path selection must return a stable reason code. An explicit inspection
query may compute bounded candidate/rejection details on demand. Registration
order alone must never be the conflict resolver.

### R6. Lazy, reusable lifecycle

Loading configuration or activating tools must not eagerly start every Server.
A Server should start on first relevant query or document-sync demand, then stay
warm within its owning runtime. In P0 it remains until Session disposal,
explicit stop, or failure. Idle eviction is a later Product policy.

Concurrent first requests for the same Server/root must share one startup.
The injected Harness launcher must atomically register every started process
with its internal session-owned `ProcessHost` before returning the handle, so
Product cleanup failure cannot leave an orphan. Coding does not receive or
operate the Host.

Pending containment/spawn work after Policy authorization must reserve Host
capacity and be settled by Session close. An approval wait remains owned by the
existing authorization/session lifecycle and consumes no process quota.
Natural process exit must release its Sandbox scope, Host registration, stderr
task, and process quota exactly once.

### R7. Correct LSP protocol lifecycle

The runtime must support:

- stdio `Content-Length` framing in the first slice;
- JSON-RPC request/response correlation;
- one ordered reader loop per connection;
- notifications and a bounded set of Server-to-client requests;
- initialize/initialized;
- request timeout and cancellation;
- graceful shutdown/exit with forced termination fallback;
- crash detection and clean replacement on later demand.

P0 fails current pending requests when a Server crashes. A later demand may
reauthorize and start a replacement; automatic retry, restart budgets, and
backoff are deferred.

The client must advertise only behavior it actually implements.

### R8. Active semantic queries

The initial model-facing capability must support bounded queries for:

- definition;
- references;
- hover/type/documentation;
- implementations;
- document outline.

Workspace-symbol search and call hierarchy are later operations unless their
bounded contracts are completed in the same slice.

### R9. Structured, bounded results

Tool results must use typed, JSON-compatible records rather than one large
formatted string. Every collection must have a hard limit and expose truncation,
Server identity, document version, readiness, and warnings.

Paths must be canonicalized and projected according to workspace/read policy.

### R10. Document synchronization

The runtime must track each open document by canonical URI and monotonically
increasing version. P0 must order `didOpen` and full-text `didChange` for active
pre-query reconciliation. H4 adds `didSave` after a committed native mutation;
`didClose` is required only when a document is retired while its Server remains
alive.

The first implementation may use full-text change synchronization. It must not
send a change for a write that failed, was cancelled, or did not commit.

### R11. Native and external mutation handling

Successful Loushang workspace edits should eventually emit a product-neutral
committed mutation fact that `coding.lsp` can consume without Edit/Write tools
importing Product LSP code.

Before every file-scoped semantic request, the runtime must also compare the
target document with disk state and resynchronize if necessary. This preserves
correctness for shell commands, external editors, or mutation sources not yet
covered by the event path.

### R12. Passive diagnostics (H4.1 reception; H4.2 delivery)

The capability must be able to receive `publishDiagnostics`, retain the latest
diagnostic set per Server/document, recognize empty sets as clearing previous
diagnostics, and project only new, relevant diagnostics to the model.

Diagnostic reception must be version-aware where the Server supplies a version,
bounded per document and session, severity ordered, and capable of recognizing
unversioned or stale information. Diagnostic delivery must additionally be
bounded per turn and deduplicated across turns.

H4.1 retains normalized current replacement sets for already-open documents and
clears them on empty publication, document advance, runtime retirement, crash,
or session disposal. It does not inject model context. H4.2 adds committed
mutation consumption and bounded model delivery.

### R13. Separate code diagnostics (H4.1 data)

LSP diagnostics must use Coding-owned `CodeDiagnostic` records. They must not be
stored as Harness operational `DiagnosticRecord` values, which represent
runtime/configuration problems rather than source-code findings.

Runtime failures such as missing binaries, startup timeouts, or crashes may use
the existing operational diagnostics/status path.

### R14. Session and workspace isolation

The first implementation must scope mutable LSP runtime state to one Coding
session and its workspace roots. It must not use a process-global singleton.

Sharing a Server between sessions is a future optimization requiring explicit
leases, document-overlay isolation, compatible policy, and independent cleanup.

### R15. Refresh and disposal

The target refresh path must prepare a replacement catalog and runtime state
without letting stale asynchronous initialization overwrite the new state.
Live catalog-generation migration is deferred from P0. Session replacement and
shutdown must close Servers and settle all pending requests, notifications, and
tasks.

Coding performs graceful LSP shutdown first. Harness `ProcessHost` disposal
is the final termination/kill safety net and must run even when Coding cleanup
raises or is cancelled.

### R16. User control and inspection

Users and embedding hosts must be able to:

- set `coding.lsp` mount mode through Coding config and generic CLI capability
  overrides;
- list configured, admitted, selected, running, failed, and unavailable
  Servers;
- inspect selection reasons and initialization errors;
- explicitly restart or stop a Server;
- run a doctor/readiness check without invoking the model.

P0 provides status/doctor and explicit stop. Explicit restart is equivalent to
stop followed by the next demand; richer restart controls are a later Product
operation.

### R17. Extension safety

An extension or package may contribute a declarative Server definition, but it
must not directly own the Product session's Server process, tool activation, or
diagnostic context injection. Product admission and lifecycle remain
authoritative.

### R18. Optional architecture integration

`coding.arch` may later request semantic facts through an injected protocol, but
must retain its deterministic language providers and must not acquire a hard
runtime dependency on `coding.lsp`. A later accepted plan may represent the
relationship as an optional `coding.arch -> coding.lsp` Capability dependency;
the current plan contains no such edge.

## Non-Functional Requirements

### N1. Security

- Server commands are argv arrays, never shell strings.
- Project-local definitions activate only after workspace trust.
- The Server environment is frozen and scrubbed before launch.
- Server-initiated workspace edits and command execution are denied by default.
- Returned locations cannot bypass workspace/read policy.
- Missing binaries produce guidance, not implicit installation.

### N2. Concurrency correctness

- One reader owns each JSON-RPC stream.
- Writes to a connection are serialized.
- Request ids are unique within a connection.
- Document changes are ordered per document.
- Startup, replacement-on-demand, and shutdown are race-safe and idempotent.

### N3. Bounded resource use

- Every model-visible result and diagnostic batch has a hard item/token budget.
- Open-document state, delivered-diagnostic keys, stderr capture, and pending
  requests are bounded.
- Server startup, requests, and shutdown have time budgets.

### N4. Failure isolation

A malformed or failing Server definition must not disable other Servers or the
Coding session. LSP is optional; failure must degrade to ordinary read/search/
compiler/test workflows.

### N5. Testability

Protocol, lifecycle, selection, synchronization, and diagnostics must be
testable with deterministic fake Server processes. Unit and contract tests must
not require Pyright, rust-analyzer, gopls, or network access.

Optional integration tests may use explicitly installed real Servers.

### N6. Performance

- Config/catalog construction must not start Server processes.
- Warm semantic requests should reuse the same initialized Server.
- Unchanged target documents should not be resent.
- Tool result shaping and diagnostic projection must be linear in the bounded
  returned set, not the entire workspace.

Exact latency budgets belong to implementation performance gates after a
baseline is measured.

### N7. Observability

The runtime must expose state transitions, request latency, timeout/crash counts,
open-document counts, diagnostic counts, replacement counts, and truncation facts
without exposing source text, inherited secrets, or unrestricted Server stderr.

### N8. Compatibility

- Public Python objects use `snake_case`.
- Wire/protocol adapters use LSP field names where required.
- Position encoding is negotiated and converted explicitly.
- Unknown Server capabilities must not be assumed.

## Constraints

- The existing capability mount vocabulary remains
  `disabled | on_demand | always`; this proposal does not add `auto`.
- `on_demand` currently means available but not active until Session tooling or
  Product activation selects the tools.
- Current Harness `ExecService` is a short-lived command service and remains
  one-shot. Long-lived bidirectional processes use the separate Process Hosting
  contract described by [Harness Foundation](harness-foundation.md).
- Current extension manifests do not have an LSP-specific surface; P0 must not
  add an LSP concept to Harness merely for symmetry with CC.

## Non-Goals

- Bundling every language server with Loushang.
- Building an editor, completion UI, rename UI, or code-action UI in P0.
- Supporting TCP/socket LSP transports in P0.
- Accepting Server-originated `workspace/applyEdit` in P0.
- Replacing compiler, lint, tests, `coding.arch`, read, or grep.
- Guaranteed full-workspace indexing or deterministic CI results from LSP.
- Cross-session Server pooling in the first implementation.
- Automatic semantic selection of a language server from the internet.

## Acceptance Criteria

The architecture is implementable when:

1. every functional requirement maps to a specified component and contract;
2. Product/Harness/extension ownership is unambiguous;
3. Capability ID, Mount Policy, Mounted Capability, and process startup
   semantics are separate;
4. document version and notification ordering are explicit;
5. code diagnostics and operational diagnostics are separated;
6. no component requires a global singleton or IDE process;
7. model-visible results and passive feedback are bounded;
8. the first slice can be tested entirely with a fake stdio Server;
9. `coding.arch` remains independently usable;
10. capability failure leaves the Coding session usable.
