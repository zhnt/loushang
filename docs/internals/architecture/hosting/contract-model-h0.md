# Hosting H0 Contract Model

## Status

- ID: `HOST-H0`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted H0 public contract
- Design status: accepted
- Implementation status: implemented
- Owner: Loushang Hosting architecture
- Contract version: `loushang.hosting/v1`

## Purpose

H0 creates the dependency-safe seam on which later Hosting resource owners can
be built. It fixes immutable request, result, failure, observation, and port
vocabulary without performing process creation, endpoint creation, filesystem
mutation, environment discovery, or Harness migration.

The implementation is `src/loushang/hosting/contracts.py` and
`src/loushang/hosting/errors.py`. The public surface is exported by
`loushang.hosting`.

## H0 Delivery Boundary

H0 implements:

- `ProcessLaunchRequest`, including shell-free absolute executable, absolute
  cwd, complete effective environment, and explicit non-inherited stdio intent;
- `ChildSessionRequest`, which composes that launch request with the future
  inherited peer-endpoint operation without exposing inheritance material;
- raw `ProcessExit` and bounded `ProcessStderrTail` facts;
- closed Hosting failure categories and bounded lifecycle observations;
- required preparation and observation ports;
- provided Process Hosting and Child Session Hosting lease protocols; and
- a standard-library-only import gate.

H0 does not implement:

- a process, endpoint, session, or platform owner;
- a composition factory or default backend;
- Harness compatibility adapters or consumer migration;
- Sandbox, Approval, Policy, Worker, Product, AppHost, or AppServer meaning;
- durable state, logs, traces, temporary roots, clipboard, or images; or
- a public raw PID, descriptor, handle, spawner, endpoint factory, or backend.

## Materialized Launch Contract

`ProcessLaunchRequest` is immutable after construction. Its validation is
lexical and side-effect free:

| Field | Contract |
| --- | --- |
| `argv` | non-empty string sequence; `argv[0]` is an absolute local executable path; no NUL; never a shell string |
| `cwd` | non-empty absolute local path with no NUL; validation does not expand home, resolve symlinks, or inspect the filesystem |
| `effective_environment` | complete sequence of string pairs; names are non-empty, contain neither `=` nor NUL, and are case-fold unique; values contain no NUL |
| `streams` | explicit stdin/stdout/stderr modes; parent-stream inheritance is not representable |

An empty environment is valid and means exactly no environment variables. H0
never merges `os.environ`, resolves `PATH`, expands `~`, consults cwd, or applies
Product defaults. Later platform adapters may reject a request that the local
OS cannot represent; they may not silently weaken it.

## Lease And Port Semantics

- `LaunchPreparationPort.prepare` returns one caller-owned
  `LaunchPreparationLease`. Hosting will own when it verifies and closes that
  lease, but never interprets it as authorization or containment proof.
- `ProcessHostingPort.start` will return one exclusive `ProcessLease` after a
  later Process Lifetime Host publishes the process.
- `ChildSessionHostingPort.start` will return one `ChildSessionLease` containing
  one process lease and one host byte endpoint, or return neither.
- H0 keeps `ChildSessionRequest` construction compatible with any valid
  process request. The H4 Child Session Host rejects unsupported stream
  topology before reserving capacity or acquiring resources; its v1 endpoint
  requires `stdin=CLOSED` and `stdout=DISCARD`, while stderr remains explicit.
- lease protocols expose lifecycle operations but no ownership transfer,
  detach, PID, raw handle, backend selection, or reconnect surface.

These are structural Python protocols. H0 does not use runtime protocol checks
as security or lifecycle evidence.

## Failure And Observation Contract

`HostingFailureCategory` is mechanism-only. A category such as
`preparation_rejected`, `spawn_failed`, or `cleanup_failed` does not claim that
Policy denied an action, Sandbox containment succeeded, a Worker is unhealthy,
or Product publication failed.

`HostingObservation` has a closed schema: component, lifecycle transition,
bounded opaque owner/session/backend identifiers, and an optional typed failure
category. It has no arbitrary mapping, message, environment, command, path,
handle, protocol payload, or caller-domain field. Failed observations require a
failure category; non-failed observations cannot carry one.

An observation sink is optional and non-owning. Later resource owners must
prevent sink failure from changing resource ownership or skipping cleanup.

## Compatibility Rule

The current `loushang.harness.workspace.process` API remains authoritative for
existing consumers. H0 introduces no re-export and changes no Harness runtime
behavior. A later compatibility slice must map fields explicitly, retain
current default-dark Worker gates, and prove equivalent cleanup before any
consumer switches owner.

## Executable Evidence

- `tests/hosting/test_contracts.py` proves immutable request validation,
  no-secret representations, closed observations, and raw result behavior.
- `tests/architecture/test_hosting_h0_contract.py` proves the package is
  standard-library-only and exports no caller-authority, raw-platform, or
  arbitrary-observation surface.
- `tests/architecture/test_hosting_architecture_baseline.py` keeps the H0
  Contract Model, AppHost/AppServer boundary, and later-slice implementation
  status mutually consistent.
- `make check-hosting` and the Hosting Quality workflow run Ruff, mypy, H0
  contract tests, and Hosting architecture gates without coupling them to the
  Harness quality target.

## Delivery Sequence

1. H1: private backend seam plus fake-backed bounded Process Lifetime Host —
   implemented by [the H1 specification](process-lifetime-host-h1.md).
2. H2: exact POSIX/Windows process-tree conformance and Harness compatibility
   adapter.
3. H3: inherited peer-endpoint feasibility and private endpoint owner.
4. H4: atomic Child Session Host and rollback matrix.

The numbering is a delivery plan, not evidence that a later slice is accepted
or implemented.
