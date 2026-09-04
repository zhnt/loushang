# Hosting H2 Process Platform And Harness Compatibility

## Status

- ID: `HOST-H2`
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative — accepted H2 process-platform specification
- Design status: accepted
- Implementation status: implemented
- Delivery status: H2a, H2b, and H2c implemented; compatibility remains dark
- Owner: Loushang Hosting architecture
- Public contract version: `loushang.hosting/v1`

## Purpose

H2 turns the fake-backed H1 owner into a locally usable Process Hosting Port
without weakening its ownership rules. It has three separately reviewable
slices:

| Slice | Delivers | Does not deliver |
| --- | --- | --- |
| H2a | exact platform capability contract, backend selection rules, conformance inventory, and Harness migration boundary | OS calls, a public factory, or consumer activation |
| H2b | private POSIX process-group and Windows Job Object backends, public platform-selecting composition factory, and real-platform conformance gates | Harness security meaning or owner cutover |
| H2c | Harness compatibility request/lease/preparation adapters and parity tests | default activation, removal of the Current owner, or Worker/H3 behavior |

H2 does not implement inherited peer endpoints, Child Session Host, Worker
protocol, restart/adoption, daemon service control, or Product readiness.

## Common Platform Contract

The H1 private backend seam remains the only process-mechanism dependency. H2b
extends it with exact owned-tree settlement. A backend must provide:

1. cancellation-recoverable spawn with synchronous ownership attachment;
2. explicit stdin/stdout/stderr mapping with no parent-stream inheritance;
3. one private tree identity created atomically with the root process;
4. initial tree termination, bounded grace, forceful tree kill, root reap, and
   bounded owned-tree settlement;
5. idempotent closure of every process, tree, and stream handle; and
6. an immutable bounded backend/capability identity.

The public lease exposes none of the process ID, process-group ID, Job Object,
native handle, backend object, or spawn registration mechanism. A raw root exit
may be observed before residual descendants finish cleanup, but host capacity
is not released until the bounded tree-settlement attempt and all
preparation/handle cleanup have settled. A failed final observation is reported
as cleanup failure and never described as proof that the owned tree is empty.

After force-kill, tree observation receives one final bounded interval. An
observation failure or a kernel-retained orphan zombie is reported as cleanup
failure, the waiter is cancelled, and all remaining handles/preparation are
still closed. Hosting never waits forever for an unsignalable zombie; such a
PID has no executing code and is not reported as successful tree-empty proof.

An owned tree means membership in the Hosting-created process group or Job
Object. Hosting is not a hostile-code security boundary: a POSIX child that is
authorized to create a new session deliberately leaves that owned group. On
Windows the H2 Job Object enables neither explicit nor silent breakaway.

## H2a Platform Capability Manifest

| Capability | POSIX backend | Windows backend | Required evidence |
| --- | --- | --- | --- |
| minimum platform | Python-supported POSIX with `setsid`/`killpg` | Windows 10 or Windows Server 2016 and later | native CI reports exact backend ID |
| atomic tree attachment | `start_new_session=True` creates the root as process-group leader before exec | `PROC_THREAD_ATTRIBUTE_JOB_LIST` assigns an unnamed Job Object during `CreateProcessW` | child cannot execute before membership exists |
| descendant inheritance | descendants remain in the process group unless they explicitly create another session/group | descendants inherit the Job Object; breakaway flags are not enabled | descendant sentinel is reclaimed with root |
| inherited handles | H2 process-only spawn inherits no extra descriptors | only explicit standard-stream handles are in `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` | unrelated sentinel is absent in child |
| initial termination | `SIGTERM` to exact process group | first `TerminateJobObject` request after caller-owned semantic stop | whole owned set receives the operation |
| forceful kill | `SIGKILL` to exact process group | `TerminateJobObject` with the forceful Hosting exit code | no root-only fallback |
| tree settlement | bounded group-existence observation plus root `wait()` | Job Object active-process count reaches zero plus root process wait | capacity remains charged until both settle |
| final safety close | signal any residual group before closing asyncio pipe transports | `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, then close job/process/pipe handles | repeated close is harmless and no handle remains owned |

Windows does not have a general signal equivalent to POSIX `SIGTERM`. The
application's semantic graceful-stop protocol remains above Hosting, as fixed
by the component model. Once Hosting termination begins, both Windows Job
Object operations are mechanism-level termination; the bounded interval still
separates the initial request from forced final reclamation.

## Backend Selection And Fail-Closed Rules

The composition factory selects only by the running platform; callers cannot
inject or name a backend through the public API.

- `os.name == "posix"` selects the POSIX process-group backend only when
  `setsid`/`killpg` mechanics exist.
- `os.name == "nt"` selects the Windows Job Object backend only when the
  atomic job-list and exact handle-list APIs are available.
- every other platform or construction-time absence of a required API raises
  `platform_unsupported`; a per-launch OS refusal (including Job creation,
  limit setup, or atomic assignment) raises `spawn_failed`, still before lease
  publication and without a weaker retry;
- there is no fallback to root-only `terminate`, root-only `kill`, `taskkill`,
  shell execution, inherited ambient handles, TCP, or stdout discovery.

Backend selection and capability probing are mechanism facts. They inspect no
Product configuration, workspace, cwd fallback, user home, PATH, credentials,
or Sandbox policy.

## POSIX Process-Group Algorithm

Spawn uses `asyncio.create_subprocess_exec` with an exact argv, cwd, complete
environment, `start_new_session=True`, `close_fds=True`, and explicit PIPE or
DEVNULL values for all three standard streams. A shielded spawn task is joined
after cancellation; if OS creation succeeded, attachment and full reclamation
finish before cancellation is propagated.

The root PID is retained only inside the backend transport as the process-group
identifier. Signals use only `killpg`; `ProcessLookupError` means the requested
group operation is already settled. Other errors are reported and never cause
a root-only fallback. Root exit is observed from the child-watcher-updated
return code rather than waiting for pipe EOF, because a descendant may retain a
pipe writer. Tree-empty observation is bounded and fakeable; the asyncio
process transport still performs root reaping.

## Windows Job Object Algorithm

H2b uses standard-library `ctypes` over Win32. It creates an unnamed Job Object,
sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, creates explicit anonymous standard
stream handles, and invokes `CreateProcessW` with `EXTENDED_STARTUPINFO_PRESENT`,
`CREATE_UNICODE_ENVIRONMENT`, `PROC_THREAD_ATTRIBUTE_JOB_LIST`, and
`PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. Thus Job membership and the inheritance
allowlist exist before the primary thread runs.

The parent closes every child-side pipe and thread handle immediately after
successful creation. Failure at any intermediate step closes the attribute
list, pipes, process/thread handles, and Job Object; kill-on-close reclaims a
successfully attached child. Blocking Win32 pipe/wait calls run through a
bounded executor-facing transport. Process cleanup first fences new I/O,
requests cancellation of synchronous stream operations, and closes the Job
Object so kill-on-close reclaims the tree. It then waits for stream and process
wait operations for a fixed interval. A pipe or process handle is closed only
after its corresponding operation settles; an unsettled handle remains owned
for a later retry and is reported as cleanup failure. H2b must prove delayed
cancellation, bounded settlement, and concurrent-spawn handle isolation on
Windows CI.

## H2c Harness Compatibility Boundary

H2c lives under Harness and depends inward on the public Hosting factory and
contracts. It explicitly maps:

- `command` to `argv` without command resolution;
- the already-normalized absolute `cwd` unchanged;
- the complete effective environment unchanged;
- stdin/stdout to pipes and `stream_stderr` to PIPE versus CAPTURE_TAIL;
- Hosting exit/tail/failure values to the existing Harness shapes; and
- `ProcessContainmentPlan` to a Launch Preparation lease whose cleanup remains
  exactly once.

The adapter preserves Current capacity, read/write/tail limit categories,
planner exception identity, close idempotence, cancellation, and ownership
timing for the representable subset. Hosting intentionally redacts raw OS
failure details into stable Harness `ProcessHostError` categories. H2c is dark: no production
composition root switches from `loushang.harness.workspace.process.ProcessHost`
until parity is green and a separate activation change is reviewed.

The Current managed sealed-executable path carries a POSIX descriptor that the
H0 public request intentionally cannot represent. H2c must either keep that
case on the Current owner or introduce a separately reviewed opaque preparation
capability; it must never infer an FD from argv, use `close_fds=False`, or import
a Hosting-private type. H2c completion therefore means a compatible dark
adapter for the representable public contract plus an executable fail-closed
gate for the sealed-descriptor case, not silent authority loss.

## Conformance Inventory

| ID | Platform | Evidence |
| --- | --- | --- |
| `H2-POSIX-SPAWN` | POSIX | exact argv/env/cwd/stdio and new-session options |
| `H2-POSIX-TREE` | POSIX | real root plus descendant termination/kill and capacity release |
| `H2-POSIX-CANCEL` | POSIX | cancellation after OS creation reclaims group and streams |
| `H2-POSIX-FD` | POSIX | unrelated descriptor is not inherited |
| `H2-WIN-SPAWN` | Windows | atomic job-list creation and exact environment/command line |
| `H2-WIN-TREE` | Windows | real descendant reclaimed and Job Object active count reaches zero |
| `H2-WIN-CANCEL` | Windows | every creation fault/cancellation point closes job/process/thread/pipes, while delayed synchronous I/O retains raw handles until settlement |
| `H2-WIN-HANDLE` | Windows | concurrent spawns inherit only their own standard handles |
| `H2-SELECT` | all CI platforms | exact backend selected or explicit unsupported failure |
| `H2-COMPAT` | platform-neutral | request/result/error/lifecycle parity and sealed-FD fail-closed behavior |

Native evidence is supplemental to the H1 deterministic matrix, not a
replacement. Windows-only evidence may be called implemented only after a
non-skipped Windows CI report identifies `windows-job-v1`; POSIX evidence must
similarly identify `posix-process-group-v1`.

The implementation supplies both native suites. A checkout can prove only its
running platform locally; the required Linux, macOS, and Windows workflow is
the authoritative combined platform report. The Harness adapter remains
unreferenced by production composition and its explicit descriptor refusal is
part of the H2 gate.

## H2b Entry Criteria

H2b may begin when:

1. this manifest and fail-closed platform rules are architecture-gated;
2. the H1 fake matrix remains green;
3. root exit versus owned-tree settlement is represented separately in the
   private seam; and
4. CI has Linux, macOS, and Windows Hosting jobs capable of rejecting empty or
   skipped native reports.

## H3 Entry Boundary

H2 establishes the private `_ProcessInheritance` seam: Endpoint Host creates a
backend-bound, single-use claim; Child Session Host is its only orchestrator;
and exactly one matching Platform Adapter may claim and mark it transferred.
The value never enters `ProcessLaunchRequest` or `ProcessHostingPort`. H3 may
now implement that seam and reuse H2's private process-creation builders only
after exact handle inheritance is proved. H3 owns endpoint-pair creation and
single-use child-side transfer; it must not add listener discovery or move
protocol framing into Hosting. At the H2 boundary, H4 was blocked until both
the H2 process owner and H3 endpoint owner had independent real-platform
evidence.
