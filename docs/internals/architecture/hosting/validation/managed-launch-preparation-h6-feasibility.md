# H6.1 Managed Launch Preparation Feasibility Record

## Status

- ID: `HOST-H6.1-FEASIBILITY`
- Scope: `hosting`
- Parent: `HOST-H6`
- Authority: descriptive — implementation validation record
- Design status: not-applicable
- Implementation status: implemented
- Native activation: none; this H6.1 record grants no native conformance
- Runtime posture: private and default-dark; Current remains the default owner
- Delivery parent: `82df045d`
- Owner: Loushang Hosting maintainers

## Question And Answer

Can one private, request-bound ownership protocol represent the POSIX and
Windows launch-preparation mechanics without exposing native values or moving
policy meaning into Hosting?

Yes. Both platform probes map to the same lifecycle:

`MINTED -> CAPTURING -> CAPTURED -> VERIFYING -> VERIFIED -> CLAIMED -> ATTACHED -> CLOSED`

with `FAULTED -> CLOSED` for known failures and terminal `FENCED` when the
spawn outcome is not known. The
common protocol needs only a normalized request, a selected profile identity,
an execution-closure identity list, backend and attempt binding, synchronous
owner attachment, final verification, one-use spawn settlement, and idempotent
close where reclamation authority is known. Platform payloads remain private
to the selected adapter.

This is a representation and ownership result, not native correctness
evidence. No production process is launched by these probes, and no public
contract is added.

## POSIX Mapping Probe

| Common operation | POSIX-private realization considered | H6.1 conclusion |
| --- | --- | --- |
| capture | open and retain executable/cwd/launcher/dependency descriptors with non-inheritable defaults | representable by one backend-owned material object |
| attach | synchronously register that object with the active host reservation before returning from acquisition | common callback rule is sufficient |
| verify | compare descriptor identity and required file/native properties immediately before spawn | common asynchronous final fence is sufficient |
| spawn | matched-backend double-dispatch combines the private material with endpoint inheritance inside the selected POSIX adapter | common opaque spawn capability is sufficient without flattening platform material |
| transfer | the same backend-owned operation acknowledges process attachment and descriptor transfer before it returns | common attached/not-created/fenced settlement is sufficient |
| close | close every retained descriptor and profile support object, aggregating failures | common idempotent close is sufficient |

A native H6.2 profile must still prove the actual executable, cwd,
interpreter/loader, launcher, dependency/search policy, containment, descriptor
allowlist, process-group, and cleanup behavior. Path re-open, ambient
inheritance, and mutable-path fallback remain forbidden.

## Windows Mapping Probe

| Common operation | Windows-private realization considered | H6.1 conclusion |
| --- | --- | --- |
| capture | retain executable/directory handles, selected token or AppContainer material, and profile support objects | representable by one backend-owned material object |
| attach | synchronously register the object with the active reservation before any cancellable continuation | common callback rule is sufficient |
| verify | recheck file/image, token/profile, loader/search, and platform-image identities adjacent to spawn | common asynchronous final fence is sufficient |
| spawn | matched-backend double-dispatch supplies private token/profile/image material while composing the exact handle list inside the selected Windows adapter | common opaque spawn capability is sufficient without flattening platform material |
| transfer | the same backend-owned operation acknowledges creation, process attachment, Job attachment, and handle transfer before it returns | common attached/not-created/fenced settlement is sufficient |
| close | close handles, token/profile objects, attribute-list support, and other reachable ownership | common idempotent close is sufficient |

A native H6.3 profile must still prove these Win32 operations on retained
Windows CI. Fake Win32 results, POSIX results, Job ownership alone, or a handle
list alone cannot promote the native gate.

## Frozen Private Core

H6.1 implements the common protocol privately in
`loushang.hosting._launch_preparation` and joins it to the private Child Session
transaction. The core has these deliberate properties:

- the public H0--H5 contracts and factories are unchanged;
- trusted preparation code receives a reservation-scoped capture capability,
  never a backend or native value;
- a non-owning opaque binding is valid only for the backend, attempt,
  reservation, request, profile, and execution closure that minted it;
- captured material attaches to the reservation before capture returns;
- caller semantic cleanup and Hosting native cleanup remain distinct but are
  joined under one preparation lease;
- the captured material participates in the unique spawn through a
  matched-backend double-dispatch; the platform adapter alone composes endpoint
  and preparation resources into one collision-free native manifest;
- the attempt-owned effect gate mints and validates the only explicit
  not-created receipt; a receipt after effect start or attachment is rejected,
  while every unreceipted error after claim enters `FENCED` and keeps cleanup
  debt;
- close, cancellation, replay, retarget, cross-reservation use, ambiguous
  spawn, and cleanup debt fail closed.

Capture authority is attached to Child Session Host because it is the only
current aggregate that owns both endpoint inheritance and the Process Host
start transaction. Process Host recognizes the private managed preparation
lease and invokes its matched-backend double-dispatch. A standalone capture
route remains absent until a concrete consumer requires it and can retain the
same capacity and publication invariants.

## Executable Evidence

`tests/hosting/test_child_session_host.py` covers:

- successful capture, final verification, matched-backend manifest, transfer,
  and close;
- concurrent double capture, double bind, verify replay, and spawn replay;
- callback failure and cancellation after attachment;
- cancellation combined with different returned capture/process objects or a
  missing process callback, with every returned owner retained for rollback;
- retarget and cross-reservation binding rejection;
- per-capture quota rejection and endpoint/preparation slot collision;
- native verification failure and final-fence cancellation;
- missing/different backend attachment contract violations;
- claimed-spawn/close and verify/close linearization;
- known-attached cancellation, unknown-outcome fencing, and host-close races;
- cross-host fresh attempt tokens and pre-spawn identity revalidation;
- caller-owned failed-callback cleanup and recursive capacity refusal; and
- native, orphan, and joined-owner cleanup debt with ordered retry, plus exact
  lower-owner/session debt settlement.

Two executable profile-identity examples use POSIX- and Windows-oriented
labels through the same opaque lifecycle. They prove only that the common
core preserves opaque profile identity and execution-closure metadata; they
do not model platform resource shapes, invoke OS APIs, or replace the H6.2
and H6.3 native evidence.

`tests/architecture/test_hosting_h6_launch_preparation.py` locks the private
surface, dependency direction, source inventory, dark composition, and matrix
presence.

## Subsequent Native Gates

- H6.2: implemented separately by the retained Linux/POSIX adversarial oracle.
- H6.3: implement and retain the Windows adversarial oracle.
- H6.4: adapt the Harness preparation owner and prove Current/Hosting parity
  without changing the default owner or enabling Product activation.

Failure of either native gate does not invalidate the common state machine; it
leaves that platform/profile unsupported and fail-closed.
