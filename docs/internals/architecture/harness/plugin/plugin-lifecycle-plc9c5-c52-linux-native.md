# PLC9C5 C5.2 Linux Native Profile Binding

## Status

- ID: `PLC9C5-C5.2-LINUX-NATIVE`
- Scope: `loushang.harness.worker` native-profile friend boundary
- Parent: `PLC9C5-C5.0`
- Authority: normative implemented slice
- Design status: accepted
- Implementation status: implemented
- Activation status: closed; no production Product composition exists
- Production default: Current
- Owner: Harness Worker architecture with Hosting platform evidence

## Purpose

C5.2 binds one already admitted Product Worker receipt to the private Hosting
`posix-static-contained-elf-v1` profile. It closes the Linux shape mismatch
without granting Product code native handles, path discovery, platform-based
owner selection, or a production activation route.

The sole friend module is
`src/loushang/harness/worker/_native_profile_bridge.py`. It exports only the
handle-free `ProductWorkerNativeProfilePort` protocol through the Worker
facade. Its implementation and constructor remain private.

## Boundary

```text
Product receipt + exact ManagedWorkerLaunchRequestV1
  -> private, single-use ProductWorkerNativeProfilePort
     -> hosting_adapter-owned managed H6 seam
        -> _PosixStaticContainedLaunchCaptureSpec
           -> _PosixStaticLaunchCaptureBackend
```

The bridge may lazily import exactly
`_PosixStaticContainedLaunchCaptureSpec` and
`_PosixStaticLaunchCaptureBackend`. It imports no Windows profile, raw POSIX
API, `_launch_preparation` type, Product implementation, AppHost, or domain
generation owner. `hosting_adapter.py` remains the only non-Hosting importer
of the private H6 managed-preparation protocol.

## Admission And Closure

Construction requires exact equality across the receipt and Worker launch
identity for Product, scope, Plugin revision, contribution, declaration, and
Worker configuration. The receipt must explicitly enable Hosting, forbid
same-attempt fallback, select the contained Linux profile, and name the exact
native catalog revision.

The same-domain realized policy closure is recomputed from:

- catalog revision and logical profile id;
- captured Worker payload SHA-256;
- trusted static containment-launcher SHA-256; and
- admitted containment-profile SHA-256.

It must equal the receipt's expected closure before native capture. A separate
`loushang.worker.native-execution-closure/v1` fingerprint binds the launcher,
payload, retained cwd identity, containment profile, fixed invocation, and
Linux x86_64 syscall ABI. Neither fingerprint contains a path, descriptor, or
environment value.

The H6 capture backend remains the authority that seals and verifies the
actual launcher, payload, cwd, endpoint descriptors, and process effect. The
bridge cannot synthesize native evidence from the receipt alone.

## Platform Gate

Platform observation happens only after an explicit Hosting receipt. The gate
accepts Linux x86_64/AMD64 only. Empty, malformed, overlong, or faulting probe
facts are unknown and fail closed. Any kernel release/version containing WSL
or Microsoft markers is rejected before private H6 profile loading. Non-x86,
macOS, Windows, and every other platform remain unsupported.

Detection can reject a selected profile; it never selects Hosting or retries
Current.

## Lifetime

Each port is request-bound and single-use. Capture failure or cancellation
consumes the port. The existing H6 reservation owns attached material and
reclaims it on pre-effect cancellation. Post-effect cancellation and complete
process-tree cleanup remain Hosting ownership and are re-proven by the C5.2
retained native report.

The Harness semantic lease performs a final profile check, followed by the
existing Worker runtime and current-evidence checks. Closing the lease is
idempotent and does not impersonate H6 process-tree settlement. Same-boot
uncertainty remains durable cleanup debt; only trusted changed-boot evidence
may prove a prior local tree absent.

## Required Evidence

`PLC9C5-C5.2-LINUX-NATIVE` is retained at
`.artifacts/plc9c5-c52-linux-native.xml`. The manifest requires exactly these
14 case ids with zero skips, failures, or errors:

`C52-EXACT-CLOSURE`, `C52-CATALOG-MISMATCH`,
`C52-POLICY-CLOSURE-MISMATCH`, `C52-EXEC-CLOSURE-MISMATCH`,
`C52-WSL-MICROSOFT-REJECT`, `C52-UNKNOWN-CLASSIFIER-REJECT`,
`C52-NON-X86-REJECT`, `C52-FD-SUBSTITUTION`,
`C52-CANCEL-PRE-EFFECT`, `C52-CANCEL-POST-EFFECT`,
`C52-DESCENDANT-CLEANUP`, `C52-SAMEBOOT-DEBT`,
`C52-CHANGEDBOOT-ABSENCE`, and `C52-SENTINEL-REDACTION`.

The report deliberately reuses the retained H6.2 native oracles for descriptor
substitution, post-effect cancellation, and descendant cleanup. The exact
closure case additionally drives the new bridge into the real H6 capture
backend; a deterministic seam test proves the port joins the existing managed
adapter without widening Hosting's public surface.

## Retained Fences

- no Product, Coding, AppHost, CLI, presenter, or Session composition imports
  or constructs the bridge;
- default Worker owner remains Current and no same-attempt fallback exists;
- no Windows private profile import or Product activation is admitted;
- no raw descriptor, path, environment, or arbitrary exception text enters
  status/evidence;
- Current Process/Sandbox, H5/H6 owners, supervisor, Capability owner, and
  rollback paths remain retained; and
- C5.3 and C5.4 remain separately reviewed slices.

## Exit Gate

C5.2 is complete when the exact import/public-surface guards pass, the bridge
and managed-seam behavior tests pass, the required 14-case report is verified
and uploaded, existing C5.1 and H6.2 evidence remains green, and no production
composition or default change is present.
