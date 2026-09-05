# Hosting H6.5 Windows LPAC Managed Preparation

## Status

- ID: `HOST-H6.5-WINDOWS-LPAC`
- Scope: Hosting-private Windows AMD64 containment mechanics
- Parent: `HOST-H6`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented candidate through H6.5b native mechanics;
  H6.5c Product composition is not implemented
- Native activation: mandatory Windows AMD64 evidence gate only; no Product consumer
- Runtime posture: default-dark
- Owner: Loushang Hosting architecture

## Purpose

H6.5 defines the Product-neutral native mechanics required by PLC9C5 C5.5.
It owns Windows profile/SID/DACL operations, LPAC process attributes, exact
handle and Job composition, native token verification, and reversible native
cleanup. It does not know Product, Plugin, Worker, Sandbox policy, admission,
requiredness, Session routing, recovery budgets, or semantic publication.

The existing H6.3 `windows-restricted-direct-import-pe-v1` profile remains a
trusted-payload mechanics profile. H6.5 adds a distinct
`windows-lpac-contained-pe-v1` profile; it does not weaken or rename H6.3.

## Contract Boundary

Trusted composition supplies two private, typed specifications through the
existing H6 reservation-scoped capture model:

1. an attempt provision/verify/cleanup specification containing an opaque
   receipt/attempt key, exact locked runtime-closure identity, fixed grant
   intent, expected profile/SID fingerprints, and a caller-owned durable
   lifecycle witness; and
2. an attempt capture specification containing the provisioned-profile
   fingerprint, exact Process launch request, executable/cwd/content identity,
   scratch settlement generation, platform identity, and attempt token.

Hosting returns only bounded opaque witnesses and H6 native material. It never
returns a path, profile moniker, SID, ACL, token, descriptor, handle, Job, or
backend instance. The future implementation remains private to
`loushang.hosting`; no public author SDK or top-level Hosting export is added.
Profile creation and DACL mutation occur only after the caller has durably
registered the exact attempt as effectful; a pre-admission probe performs no
native mutation.

## Exact Runtime Closure

The grant target is a dedicated immutable Worker runtime closure, not a Plugin
package root. The Package owner must publish a separate root containing only
the exact admitted executable and immutable files required by that Worker.
The executable and cwd are descendants of that root. No manifest, credential,
other contribution, user file, mutable cache, symlink/reparse point, external
hard link, device path, UNC path, or alternate data stream is admitted.

The H6.5 provisioner:

- opens the runtime root, executable, cwd, and their complete local-volume
  ancestor chain without following reparse points;
- validates file kind, volume/file identity, link count, bounded tree shape,
  content digests, and containment inside the dedicated root;
- grants the exact Package SID read, execute, and traverse rights only;
- rejects write, delete, ownership, DACL mutation, recursive inheritance
  beyond the exact closure, or any pre-existing broader grant; and
- rechecks the grant and locked identities immediately before every spawn.

The complete attempt-specific AppContainer profile is the only writable
filesystem and registry authority. Hosting creates a fresh profile for every
attempt; it never reuses a predecessor's private files or registry state.
Because LPAC removes the ambient All Application Packages traversal path,
Hosting grants the Package SID temporary non-inheriting traverse rights on the
private root's ancestor chain. Windows remains the owner of the Package SID
ACL on the profile root and `Temp`; Hosting records both directory identities
in the private-state witness and never rewrites those platform-owned ACLs. The
temporary ancestor grants are covered by the same provision witness,
pre-spawn verification, and reverse cleanup as the immutable-runtime grants.
On cleanup, Hosting performs rooted, no-follow, bounded removal of its exact
`Temp` scratch subtree, rejecting reparse points, foreign hard links, streams,
devices, depth, entry-count, and byte-count overflow. It does not recursively
reinterpret or delete the platform-owned profile layout. With all native
handles closed, `DeleteAppContainerProfile` is the sole owner that deletes the
complete OS profile, remaining filesystem storage, and private registry state.
Cleanup ambiguity or residue blocks a successor.

## Provisioning State Machine

The caller remains the durable transaction owner; Hosting is the native effect
participant. The caller must persist each transition by CAS before asking for
the next effect:

```text
ABSENT
  -> RESERVED
  -> PROFILE_CREATED
  -> GRANTS_APPLIED
  -> VERIFIED
  -> ACTIVE
  -> CLEANING
  -> GRANTS_REVOKED
  -> PROFILE_DELETED
  -> SETTLED

any uncertain native effect -> DEBT
```

Each Hosting result binds the operation nonce, prior-state fingerprint,
receipt/attempt key, native profile/SID fingerprint, runtime/profile identity
fingerprints, grant digest, and platform identity. An exception after a native
call begins is treated as possibly effectful. The caller records `DEBT`; it
does not retry create, grant, revoke, or delete as though no effect occurred.

Windows exposes deterministic Package SID derivation, but no public read-only
API that proves whether an arbitrary profile moniker is registered. Recovery
therefore never fabricates such a query. A `RESERVED`, `PROFILE_CREATED`,
`GRANTS_APPLIED`, `CLEANING`, or `DEBT` record can reconstruct a pathless
cleanup-only witness from its durable attempt id, high-entropy operation nonce,
lifecycle fingerprint, deterministic moniker, and derived SID. That witness
cannot authorize launch or grant creation. It permits only exact Package-SID
DACL revocation and bounded profile/private-state deletion; absent grants and
an absent profile are successful cleanup replay. A profile observed during
ordinary creation as already existing, an unexpected SID, a widened or partial
DACL, a changed closure identity, or an unknown private state is
foreign/ambiguous and cannot be adopted for launch. A conclusive
`ERROR_ALREADY_EXISTS` creation collision created no attempt-owned native
effect and must never mint a cleanup witness or delete that foreign profile.
Cleanup is allowed only
through the exact cleaning attempt record and only after the caller proves that
no admitted attempt can still run. Repeated exact cleanup is idempotent;
unrelated profiles and grants are never touched.

This caller-owned journal prevents a crash between `CreateAppContainerProfile`
and receipt publication from silently converting an unknown profile into
authority. It also prevents two Product or host processes from concurrently
provisioning or cleaning the same attempt.

Process-tree settlement and containment settlement are distinct results.
Closing the last Job handle may prove the tree absent but cannot prove that
the DACL grant, profile filesystem, or private registry state was removed.
Hosting emits separate opaque observations for those edges; only the caller
may join them into its versioned durable cleanup settlement.

## LPAC Process Construction

The attempt capture owner follows the existing H6 attach-before-cancellation
and one-use state machine. Its final synchronous effect composes one
`STARTUPINFOEX` attribute list containing exactly:

- `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES` with the expected Package SID
  and zero capability SIDs;
- `PROC_THREAD_ATTRIBUTE_ALL_APPLICATION_PACKAGES_POLICY` with
  `PROCESS_CREATION_ALL_APPLICATION_PACKAGES_OPT_OUT`;
- `PROC_THREAD_ATTRIBUTE_JOB_LIST` with the exact kill-on-close Job; and
- `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` with only Worker endpoint stdin/stdout
  and the Hosting-owned discarded stderr handle.

The process is created suspended. Hosting attaches the process owner, verifies
the child token is an LPAC token with the exact Package SID and zero
capabilities, and verifies Job membership before resuming the sole initial
thread. The parent-side exact attribute manifest is the inheritance authority;
child self-report is never production authorization evidence. A verification
failure terminates and drains the Job before the thread can execute. Failure
before OS creation receives the
H6 pre-effect receipt; a conclusive false process-creation result receives the
settled-without-process receipt; every ambiguous post-effect result is fenced.

No inherited environment is permitted. A fixed environment block is built
from explicit OS APIs and the provisioned profile location, with every value
and key covered by the execution-closure fingerprint. `PATH`, proxy variables,
credentials, user shell configuration, Python variables, loader controls, and
caller-supplied values are absent. The native child oracle reports only
boolean/categorical results and bounded fingerprints.

## Native Security Oracle

The mandatory Windows AMD64 oracle launches a purpose-built no-CRT child and
proves from inside that child:

- LPAC token, exact Package SID, zero capability count, and All Application
  Packages opt-out are effective;
- the exact runtime closure is readable/executable but not writable or
  deletable;
- profile-private filesystem and registry scratch are writable and cannot
  escape through reparse, link, stream, or path traversal;
- an unrelated same-user file cannot be opened and a same-user process cannot
  be opened with mutation, VM, or handle-duplication rights;
- a parent-created loopback listener is reachable by an unrestricted control
  process but unreachable by the zero-capability child;
- only the exact endpoint and stderr handles are inherited; and
- a descendant remains in the atomically assigned Job and the complete tree
  is gone before settlement.

The report also injects profile/SID/DACL/runtime/private-state/platform/handle
substitution, cancellation at every acquisition and both sides of the process
effect, early exit, failed token verification, failed resume, containment-
cleanup faults, concurrent provisioning/cleanup, same-boot uncertainty, and
path/secret/handle sentinel redaction. Missing LPAC, opt-out, Job-list, token
inspection, DACL, or native compiler support fails the required CI job rather
than skipping it.

## Source Placement And Dependency Rules

The implementation may extend only:

- `src/loushang/hosting/_windows_launch_preparation.py` for the private
  provision/capture specifications and native owner state;
- `src/loushang/hosting/_win32_process.py` for raw Win32 bindings and exact
  attribute/token/DACL operations; and
- `src/loushang/hosting/_windows_process.py` for the matched Process backend
  double dispatch.

A separate file may be introduced only if the H6.5 implementation review shows
that provisioning and attempt ownership cannot remain cohesive in the current
module; it must still be Hosting-private. Hosting imports no Harness module.
H6.5b itself adds no Harness consumer. The later C5.5c transition allows only
the existing `src/loushang/harness/worker/_native_profile_bridge.py` to lazily
import the exact reviewed private H6.5 symbols.

The existing PLC9B AppContainer adapter remains Package-owned. It may later be
rewired to consume an accepted Product-neutral injected Hosting capability,
but H6.5 does not import it, copy its Package coordinator, change its behavior,
or use its report as H6.5 evidence.

## Non-Goals

- arbitrary Windows executables, Python runtimes, dynamic Plugin loading, or a
  general AppContainer SDK;
- network capabilities, COM/registry/device capabilities, UI, clipboard, or
  interactive desktop access;
- remote services, surviving-process adoption, or cross-user/service profiles;
- Product selection, required/optional interpretation, Session discovery,
  Worker protocol, readiness, fallback, or domain publication; and
- Current-owner deletion or default activation.

## H6.5b Native Exit Gate

H6.5b is accepted only when the C5.5 ownership/receipt design, exact Current
inventory, reviewed Hosting-private runtime symbols, deterministic mechanics
tests, and mandatory Windows AMD64 native report agree. Executable guards prove
that no Harness or Product consumer exists and that Current remains the
production default.

The paired five-view C5.5a review accepted this boundary after separating
Hosting ownership, replacing persistent deployment profiles with exact
attempt-owned profiles, and making the parent attribute manifest—not child
self-report—the launch authority. H6.5b implements that candidate without
granting activation authority; H6.5c Product integration and its separate
evidence report remain open. No unresolved high or medium design issue remains
in the H6.5b native boundary.
