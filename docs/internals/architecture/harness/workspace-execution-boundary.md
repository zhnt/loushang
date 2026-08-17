# Harness Workspace Execution Boundary

## Status

Status: accepted for `lane/harness`.

This document defines ownership for bounded workspace output and process
execution. It moves product-neutral execution mechanics into
`loushang.harness.workspace`.

## Decision

Harness owns two focused workspace capabilities:

- `loushang.harness.workspace.truncation` owns deterministic line/byte bounded
  text truncation, UTF-8 suffix handling, neutral truncation metadata, and the
  shared baseline limits already used by tools and exec previews.
- `loushang.harness.workspace.exec` owns process request/result records,
  incremental output records, backend/update callback protocols, and the local
  `ExecService` implementation.

Coding remains a product adapter. It owns command risk classification,
approval policy, session cwd resolution, extension semantics, tool result
projection, prompt wording, and user-facing notices.

## Truncation Split

Move to harness:

- `DEFAULT_MAX_LINES`
- `DEFAULT_MAX_BYTES`
- `TruncationKind`
- `TruncationResult`
- `truncate_head`
- `truncate_tail`
- limit validation, line/byte accounting, and UTF-8-safe suffix helpers

`loushang.harness.tools.workspace.truncate` owns the workspace grep line limit,
line truncation, size formatting, and structured detail projection. Products
choose user-facing wording but do not re-export these mechanisms.

`harness.presentation.collapse_text` remains a rendering helper. It adds display
wording and does not replace byte-bounded capture or artifact decisions.

## Execution Split

Move to harness:

- `ExecRequest`
- `ExecOutputChunk`
- `ExecUpdateCallback`
- `ExecResult`
- `ExecBackend`
- `ExecService`
- local subprocess, cancellation, streaming, rolling capture, preview, and
  artifact mechanics

Keep in coding:

- policy evaluation for command content and paths
- relative cwd resolution against a coding session
- extension runtime binding behavior
- bash tool result conversion and notices
- the explicit `loushang.coding.exec` compatibility path

The request capture fields remain caller-supplied neutral configuration. Their
current defaults are preserved for compatibility; harness does not decide which
commands a product may run.

`retain_output_artifacts` defaults to `True`, preserving the diagnostic artifact
contract for existing callers. A finite consumer that never publishes artifact
paths may set it to `False`; the execution backend must then return bounded
preview metadata without retaining capture files. Artifact creation and cleanup
remain backend-owned mechanics rather than a tool-specific `unlink()` escape
hatch.

`materialize_exec_request()` freezes inherited cwd and the complete merged
environment before a request crosses an asynchronous policy or execution
boundary. `ExecRequest.env` remains the caller-visible override set;
`effective_environment` is the execution-only snapshot and must not be copied
into approval, audit, or transcript projections. `ExecService` passes the
materialized request to custom `ExecBackend` implementations, which must honor
its `cwd` and `effective_environment` without rereading host process state. A
caller that performs policy evaluation separately must materialize once and use
the same request for evaluation and execution.

Materialization deliberately preserves the requested command and native
`argv[0]`/shebang/wrapper behavior. It does not freeze executable lookup,
executable bytes, or arbitrary files read by a child process. It is a cwd and
environment binding contract, not a sandbox or immutable filesystem guarantee.

## Public Owner

Harness-owned classes keep their harness `__module__` and are not exported from
top-level `loushang.harness.__all__`. Product-internal code imports the focused
Harness modules. `coding.tools.truncate` is removed with the complete Coding
tool facade.

## Dependency Direction

The target direction is:

```text
coding tools / sessions / extensions / policy
  -> loushang.harness.workspace.exec
  -> loushang.harness.workspace.truncation
```

Harness workspace modules must not import coding, TUI, work, method, or AI.
This move does not introduce a neutral execution context and does not by itself
satisfy the neutrality evidence gate for that contract.

## Validation

The migration must prove:

- neutral truncation behavior and UTF-8 byte limits under the harness path;
- exec subprocess, streaming, timeout, cancellation, rolling capture, preview,
  custom backend, and artifact behavior under the harness path;
- direct Harness imports preserve object identity;
- coding tools, policy, extension, session, and prompt behavior remain intact;
- architecture import boundaries and top-level export discipline still pass.
