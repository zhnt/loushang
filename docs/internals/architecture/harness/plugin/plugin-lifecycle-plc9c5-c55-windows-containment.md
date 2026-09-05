# PLC9C5 C5.5 Windows Required-Containment Baseline

## Status

- ID: `PLC9C5-C5.5-WINDOWS-CONTAINMENT`
- Scope: Windows AMD64 Product Worker containment and G7 closure
- Parent: `PLC9C5-C5.0`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented through C5.5c; native mechanics, cleanup
  V2, the sole Harness friend dispatch, and Coding Product composition are retained
- Activation status: exact Windows AMD64 Coding canary accepted; the C5.3
  restricted-token profile and every unlisted route remain rejected
- Production default: Current
- Owner: Harness Worker architecture with Hosting, Product, Package, and
  security-owner review

## Purpose And Exit Boundary

C5.5 defines the only permitted route from the retained C5.3 Windows
mechanics to accepted Product required containment. It does not rename the
existing `windows-restricted-direct-import-pe-v1` profile, treat a restricted
token or Job Object as a Sandbox, or activate Windows because the host happens
to support an AppContainer API.

The target profile is `windows-lpac-contained-pe-v1`: a zero-capability
Less-Privileged AppContainer (LPAC), one immutable AMD64 Worker revision, one
fresh attempt-specific profile and Package SID, one exact read/execute grant
set, fresh profile-private filesystem scratch, no registry authority, an exact
inherited-handle list, and an atomically assigned kill-on-close Job.
The profile is eligible only when an explicit Product receipt selects Hosting
and binds the exact provisioned containment receipt. Every omitted, stale,
foreign, unprovisioned, unsupported, or degraded input fails before spawn.

C5.5 closes G7 only after both the Windows native containment report and the
Windows Coding Product report are retained with no required skip; both reports
are now mandatory gates. It does not
join AppHost; that remains G8. It does not delete Current, the C5.3 mechanics
profile, or any rollback owner; that remains G9.

The Product/Harness boundary in this document is paired with
[HOST-H6.5-WINDOWS-LPAC](../../hosting/managed-launch-preparation-h65-windows-lpac.md),
which owns Product-neutral native provisioning and process mechanics. Neither
document may absorb the other's policy or OS-resource ownership.

## Threat Model And Security Claim

The protected principal is the host Product and its user data. The adversary
is an admitted but malicious or compromised Worker executable running under
the same interactive user. The operating system, kernel, Loushang trusted
composition, and Product/Package/Sandbox authorities are trusted. A malicious
administrator, kernel exploit, hostile host process already running with the
same user's full token, or denial of service outside fixed host quotas is out
of scope.

The accepted claim is deliberately concrete:

- the child token is an LPAC token with the exact expected Package SID;
- the token has zero capability SIDs and opts out of ambient All Application
  Packages access;
- it can read and execute only the exact dedicated immutable Worker runtime
  closure grant plus Windows platform resources necessarily reachable by the
  accepted LPAC platform profile;
- it can write only its attempt-specific profile-private filesystem scratch,
  which is untrusted and removed before a successor attempt; it has no
  registry authority;
- it receives only the Worker endpoint handles and the deliberately discarded
  stderr handle;
- it has no network capability and cannot reach a network sentinel;
- it cannot open an unrelated same-user filesystem sentinel or obtain
  mutation/VM/handle-duplication rights to a same-user process sentinel; and
- descendant creation is denied or its complete descendant tree is owned by
  the exact kill-on-close Job before the initial thread can execute.

The native oracle must test those negative authorities from inside the child.
Source inspection, token flags alone, parent-side ACL inspection, successful
process creation, or Job membership alone cannot establish the claim.

## Immutable-Material And Attempt-Lifetime Separation

C5.5 separates immutable Package material from attempt resources. Their
lifetimes must not be collapsed into one best-effort cleanup callback.

| Resource | Identity and lifetime | Sole owner | Required settlement |
| --- | --- | --- | --- |
| dedicated immutable Worker runtime closure | Product/Plugin revision lifetime; no AppContainer grant while idle | Package/Sandbox materialization owner | exact content/root identities remain immutable; retirement stays separate from an attempt |
| LPAC profile, Package SID, DACL grant, private filesystem scratch, and OS-owned profile state | deterministic opaque profile key bound to receipt, attempt, native catalog, and machine user; one attempt only | Product/Package/Sandbox durable coordinator through one Hosting-private provisioner | create new or exact cleanup-only reconciliation; after tree settlement revoke the exact grant, delete the complete profile/private state, and record retryable containment debt on uncertainty |
| executable/cwd locks, SID memory, security-capability attributes, endpoint handles, stderr handle, and Job | one receipt/request/attempt | Hosting capture material, then Process/Child Session lease | attach before cancellation, transfer atomically, and settle or record C5.1 process cleanup debt |
| Worker protocol and domain generation | one receipt/request/attempt | Harness Worker and exact Capability owner | health before publication; exact-generation revoke/drain and retirement |

Using a fresh LPAC profile per attempt prevents a crashed or malicious Worker
from supplying filesystem or registry state to its successor. It also makes
the temporary DACL grant part of the same attempt's containment cleanup. A
host crash closes the Job and therefore the process tree, but the profile,
private state, and DACL may remain. Restart is blocked until C5.1 proves the
tree absent and the exact native containment cleanup has revoked the grant and
deleted the profile. Unknown or partial cleanup remains durable debt.

## Responsibility And Dependency Boundary

```text
Product policy + selected immutable Worker revision
  -> pathless Product Worker activation receipt
     -> Product/Package/Sandbox durable provisioning authority
        -> sole Harness _native_profile_bridge.py
           -> Hosting-private LPAC profile + exact grant receipt
     -> the same sole Harness _native_profile_bridge.py
        -> Hosting-private LPAC capture spec/backend
           -> Hosting Process/Child Session owner
              -> Worker supervisor -> Capability generation owner
```

| Concern | Sole writer | Receives | Must not own |
| --- | --- | --- | --- |
| Product enablement, requiredness, owner, and rollback policy | exact Product adapter | selected immutable contribution | SID, ACL, handle, Job, platform probing |
| immutable Worker material and retirement | Package/Sandbox composition | dedicated runtime-closure identity and revision key | Process/Session lifetime, protocol, generation publication |
| LPAC profile/grant mechanics | Hosting-private provisioner | opaque attempt containment key, exact locked roots, fixed grant intent | Product/Plugin vocabulary, policy interpretation, Worker protocol |
| receipt-to-native-profile join | sole Harness `_native_profile_bridge.py` | receipt, Worker request, pathless provisioned-profile evidence | raw Win32 API, public native material, Product selection |
| process/native resource lifecycle | Hosting | exact private capture specification | Product readiness, fallback, publication |
| handshake, health, recovery, and attempt fencing | Harness Worker | injected session/transport and durable ports | profile provisioning, domain publication |
| semantic visibility | exact Capability owner | healthy admitted attempt | native/process cleanup, owner selection |

Hosting continues to import no Harness, Product, Plugin, AppHost, AppServer,
or AppService module. The Package/Sandbox composition calls the sole Harness
bridge and never imports Hosting; Hosting therefore does not discover a
Product or package. Coding imports no Hosting module. Only the existing
`src/loushang/harness/worker/_native_profile_bridge.py` may lazily import the
exact new private Windows capture symbols; a second friend module is
forbidden. `_win32_process.py` and raw Win32 APIs remain illegal Harness
imports.

PLC9B's `package_windows_legacy_runtime.py` is evidence and a semantic
precedent, not a reusable dependency. C5.5 may factor common Win32 mechanics
down into Hosting only if PLC9B consumes a Product-neutral injected capability
without changing its Package ownership. Hosting must never import
that Harness module, and copying its complete Package-specific coordinator
into Hosting is also forbidden.

## Provisioning Receipt And Policy Closure

The provisioned-profile evidence crossing into Harness is pathless and
authority-free. Its canonical fingerprint binds at least:

1. profile version and logical native profile id;
2. opaque receipt/attempt profile key and native catalog revision;
3. Product id, Plugin immutable revision digest, and contribution id through
   their existing Product receipt fingerprints, not as Hosting fields;
4. Package SID fingerprint, never the SID bytes or profile name;
5. executable digest plus locked executable/package-root/cwd identity
   fingerprints;
6. exact grant-manifest digest (`read+execute` package root, no write grant);
7. zero capability count and LPAC All Application Packages opt-out;
8. attempt-private filesystem/profile identity and cleanup generation;
9. accepted Windows AMD64 platform identity; and
10. provisioner authority identity, attempt generation, and cleanup generation.

The C5.1 expected native-policy closure adds the provisioned-profile digest as
the containment-profile digest. The realized closure is recomputed from the
captured private native material. A stale provisioning generation, changed
SID, widened ACL, pre-existing profile state, changed path identity, platform
mismatch, or closure mismatch fails closed. Profile creation/DACL mutation
occurs only after the C5.1 attempt is durably registered as effectful.

The policy closure binds the accepted LPAC recipe and grant intent, not an
attempt SID that does not yet exist when Product policy is issued. A separate
pathless provisioning witness binds `(receipt fingerprint, attempt id, owner
generation)` to the realized profile/SID/grant/private-state fingerprints.
Both witnesses must be current before publication.

C5.5c must version the C5.1 cleanup schema rather than reinterpret
`WorkerCleanupSettlementV1.tree_settled`. A V2 settlement adds an explicit
`native_containment_settled` edge; a V2 debt can distinguish unknown process
tree state from unknown profile/DACL/private-state cleanup. Existing V1
Current/Linux records migrate losslessly and remain valid only for profiles
whose contract has no persistent native containment residue. Windows retry,
rollback completion, and readiness settlement require protocol terminal,
exact domain retirement, tree settlement, and native-containment settlement.

No path, profile name, SID, ACL, environment value, descriptor, handle, token,
or scratch content appears in Product receipts, status, logs, JUnit case ids,
or domain publications.

## Native Launch Profile

The private Hosting H6.5 implementation extends the existing H6 state machine;
it does not add a parallel process host.

1. A Product/Package/Sandbox-owned durable provisioning coordinator asks the
   sole Harness bridge to invoke H6.5 create/verify/cleanup mechanics. The
   coordinator CASes `reserved`, native-effect, active, cleaning, settled, or
   debt state and never calls Hosting directly.
2. The H6.5 provisioner creates a fresh deterministic attempt LPAC profile
   with zero capabilities and an exact Package SID, applies the exact grant,
   and rejects any pre-existing state except cleanup-only recovery backed by
   the matching durable attempt record.
3. The Harness bridge validates the Product receipt, Worker request, catalog,
   provisioning receipt, expected policy closure, and explicit Windows AMD64
   observation before importing private Windows symbols.
4. H6 capture attaches an empty material owner, then acquires executable/cwd/
   ancestor locks, owned SID memory, Job, and discarded stderr in bounded
   order. Every acquired resource is attached before cancellation can land.
5. Final verification rechecks content/path identity, grant and profile
   generations, LPAC/zero-capability policy, Job kill-on-close, and the exact
   request immediately adjacent to the effect.
6. One attribute list contains the LPAC security capabilities, All Application
   Packages opt-out, Job list, and exact inherited handle list. Any alias,
   extra handle, missing attribute, or inability to combine them fails before
   process creation.
7. The child is created suspended with atomic Job-list assignment. It cannot
   execute before Job ownership, endpoint transfer, and token verification are
   established. The parent-side exact attribute manifest is the inheritance
   authority; it does not trust child self-report.
8. After creation but before resume, Hosting verifies the child token's LPAC
   flag, exact Package SID, zero capabilities, and Job membership. Only then
   may the initial thread resume and the Worker handshake eventually publish
   health. A separate native fixture validates handle-list enforcement but is
   not a production authorization witness.
9. Close fences I/O, terminates and drains the exact Job tree, closes process
   resources, revokes the attempt's exact DACL grant, deletes the complete
   AppContainer profile/private state, and records combined tree/containment
   settlement. Unknown state becomes C5.1 cleanup debt and never permits retry
   or fallback.

The process environment is an exact Hosting-built allowlist. Caller-supplied
environment is rejected. No `PATH`, user profile, credential, proxy, loader,
Python, or ambient activation variable is inherited. Any minimum platform
bootstrap values must come from OS APIs and be part of the realized execution
closure.

## Delivery Slices

| Slice | Delivery | Exit condition | Activation |
| --- | --- | --- | --- |
| C5.5a | this threat model, lifetime/owner split, source inventory, evidence matrix, and architecture guards | five-view review has no unresolved high/medium issue; no production source change | Windows remains closed |
| C5.5b | Hosting-private LPAC provisioner, capture material, Process backend extension, native oracle, and mandatory Windows report | token/SID/capability/LPAC, grants, private state, environment, handle list, Job tree, cancellation, crash, containment cleanup, and redaction cases pass on Windows with no skip | default-dark; no Harness or Product consumer |
| C5.5c | cleanup V2 migration, exact same-file Harness friend dispatch, and Coding Product Windows composition with retained Product report | receipt/provisioning/closure freshness, required/optional, Session/entrypoint, native-containment recovery, rollback, publication, unsupported-host, and no-fallback rows pass | explicit Windows canary only; Current remains default; G7 closes |

C5.5b did not add a public author SDK, production composition, or platform
auto-selection. C5.5c began only after the retained native report proved the
actual LPAC security claim, and CI continues to run that native report before
the Product report. A fake profile, token flag mock, or PLC9B report cannot
substitute for the native gate.

## Required Evidence Matrix

The C5.5b native report must include exact cases for:

- profile create, cleanup-only exact replay, foreign pre-existing profile
  rejection, and containment-cleanup debt/retry;
- zero capabilities, exact Package SID, LPAC opt-out, and no ambient All
  Application Packages reachability;
- exact runtime-closure read/execute, runtime write denial, profile-private
  filesystem scratch-only write, registry denial, and
  unrelated same-user root denial;
- network denial plus a local network sentinel that proves the test actually
  attempted egress;
- executable/cwd/ancestor, SID, DACL, scratch, platform, and policy-closure
  substitution;
- caller environment rejection and OS-sourced bootstrap closure;
- exact endpoint/stderr handle list, alias rejection, and no extra inherited
  handle;
- cancellation before and after effect, early exit, descendant tree cleanup,
  native-containment cleanup/debt, same-boot uncertainty, changed-boot absence,
  and sentinel redaction.

The C5.5c Product report must reproduce every C5.4 Product/Session/policy/
publication/rollback/recovery/entrypoint row for Windows, replace the
`C54-UNSUPPORTED-WINDOWS` expectation with exact Windows acceptance, retain
macOS/WSL/non-AMD64 fail closure, and prove no same-attempt Current fallback.

CI must generate separate native and Product XML files, verify nonempty
zero-skip/zero-failure/zero-error reports, validate exact case ids through the C5
manifest, and retain both artifacts. Linux C5.2/C5.4 and Windows C5.3 reports
remain mandatory; a new report cannot erase an earlier regression.

## Guard Transition And Retained Fences

C5.5a changes documentation and architecture tests only. C5.5b may add exact
Hosting-private LPAC symbols and Win32 bindings but no Harness consumer.
C5.5c may revise only these absences:

- the sole `_native_profile_bridge.py` Windows-private import absence;
- the exact Coding canary's Windows-profile rejection; and
- the parent G7-open status, but only after both new reports pass.

Every other fence remains:

- Current is the default and future rollback owner;
- one attempt has one sticky owner and no same-attempt fallback;
- the C5.3 restricted-token profile remains mechanics-only and cannot satisfy
  required containment;
- macOS, WSL, non-AMD64 Windows, and every unlisted profile fail closed;
- Hosting owns no Product/Plugin policy and exports no raw native material;
- AppHost/G8, author SDK, remote service, live adoption, and other Product or
  domain activations remain absent; and
- no Current owner, immutable runtime closure, or compatibility path is deleted
  before the G9 reverse-consumer inventory and rollback drill.

## Five-View Review Packet

1. **Architecture:** dependency direction, sole writers, one friend bridge,
   immutable-material-versus-attempt lifetime separation, and G7/G8 independence.
2. **Security:** LPAC rather than restricted-token relabeling, zero
   capabilities, opt-out, exact DACL grants, fresh per-attempt profile state,
   negative in-child
   authority probes, and a stated threat model.
3. **Native lifecycle:** attach-before-cancel, one attribute list, atomic Job
   membership, post-create token verification, complete-tree settlement,
   containment-cleanup debt, and host-restart behavior.
4. **Product and recovery:** exact receipt/provisioning closure, explicit
   allowlist, required/optional behavior, Session/entrypoint convergence,
   cleanup V2 migration, sticky owner, rollback ordering, and no
   adoption/fallback.
5. **Testing and operations:** mandatory Windows-native and Product reports,
   exact ids, negative sentinels, bounded pathless diagnostics, retained prior
   reports, attempt containment cleanup, and G9 deletion evidence.

## Five-View Review Resolution

The C5.5a review found and corrected three material design defects before any
runtime implementation:

1. Hosting mechanics now have their own H6.5 design rather than being defined
   only by a Product lifecycle document.
2. A persistent per-deployment profile was rejected because its private
   filesystem and OS-owned profile state could poison a successor. The
   accepted design uses one profile/SID/grant per attempt and blocks restart
   on incomplete cleanup.
3. Pre-resume child verification of inherited handles was rejected as an
   impossible authorization dependency. The parent-side attribute manifest is
   authoritative; the in-child handle probe is retained only as native
   implementation evidence.

Architecture, security, native lifecycle, Product/recovery, and
testing/operations views have no unresolved high or medium issue. C5.5b must
still prove feasibility on the required Windows runner; design acceptance is
not native or Product activation acceptance.

## C5.5a Exit Gate

C5.5a is accepted only when this document, the exact source/inventory delta,
and executable architecture guards land together; five-view review leaves no
unresolved high or medium risk; and the diff contains no production source
change under `src/loushang`. Acceptance grants no runtime or Product
activation authority.

## Platform References

The platform assumptions are grounded in Microsoft's Win32 documentation:

- [Launch an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
  defines the Package SID/capability model, LPAC opt-out attribute, profile
  creation, `SECURITY_CAPABILITIES` process attribute, and LPAC requirement
  for an explicit `registryRead` capability before registry access;
- [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
  defines the file, network, process, window, device, and credential isolation
  claim; and
- [CreateAppContainerProfile](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile)
  confirms the per-user persistent profile and its private filesystem/registry
  storage. The zero-capability LPAC is deliberately granted no access to the
  registry portion; C5.5 nevertheless treats the complete profile as
  attempt-owned and requires explicit deletion before a successor attempt.
