# PLC9C5 C5.3 Windows Mechanics And Product Rejection

## Status

- ID: `PLC9C5-C5.3-WINDOWS-MECHANICS`
- Scope: Hosting-private Windows AMD64 trusted-payload mechanics
- Parent: `PLC9C5-C5.0`
- Authority: normative implemented slice
- Design status: accepted
- Implementation status: implemented
- Activation status: closed; Windows is rejected for Product required containment
- Production default: Current
- Owner: Hosting platform adapter with Harness Worker absence guards

## Purpose

C5.3 removes ambient environment trust from the existing Windows restricted
launch fixture and retains its native mechanics as useful platform evidence.
It does not reinterpret a restricted token, direct PE imports, or a Job Object
as complete Product containment. The Linux-only Product bridge therefore
continues to reject the Windows mechanics profile before loading any private
Windows Hosting symbol.

## Boundary

```text
trusted caller request (empty environment, closed/discarded streams)
  -> Hosting-private builder
     -> GetWindowsDirectoryW + temporary locked identity snapshots
        -> opaque _WindowsRestrictedLaunchCaptureSpec
           -> H6 capture reacquires and retains all native owners
```

The builder is private to `loushang.hosting`. It is not exported by the public
facade and has no Harness, Product, Coding, AppHost, AppServer, or UI consumer.
It receives an admitted executable digest but never discovers a payload,
selects an owner, or grants security meaning.

## Trusted Inputs And Rejection

Caller environment is rejected before the Win32 API object is constructed or
any native owner is acquired. The only effective environment entry is the
canonical local absolute Windows directory returned directly by
`GetWindowsDirectoryW`; `os.environ`, including ambient `SystemRoot`, is never
read. Stdin must be closed and both stdout and stderr discarded. This preserves
the H6.3 profile instead of silently adapting the H6.4 Worker's piped stderr.

The builder temporarily locks executable and cwd to record volume/file
identity and closes those snapshot handles before returning. These snapshots
are admission facts, not execution authority. H6 capture opens both paths
again, retains their native handles and ancestor handles, and rejects identity
substitution before the unique process effect.

Every construction failure crossing the builder boundary has a stable Hosting
category and message. Native exception text, paths, environment values, and
sentinels remain only in the exception cause and do not enter status or
evidence.

## Retained Native Mechanics

The required Windows AMD64 report retains:

- locked PE/cwd/ancestor identity and AMD64 bounded direct-import validation;
- canonical OS-sourced `SystemRoot` with ambient poisoning ignored;
- restricted primary token creation with the fixed disable-max-privilege flag;
- atomic kill-on-close Job attachment and descendant-tree reclamation;
- exact inherited handle-list collision rejection;
- pre-effect and post-effect cancellation reclamation;
- same-boot uncertainty and changed-boot absence rules; and
- caller-environment, stream-shape, required-containment, and sentinel gates.

## Required Evidence

`PLC9C5-C5.3-WINDOWS-MECHANICS` is retained at
`.artifacts/plc9c5-c53-windows-mechanics.xml`. The manifest requires exactly 12
case ids with zero skips, failures, or errors. The report is enabled only by
the explicit Windows AMD64 gate so ordinary cross-platform suites do not run
the native Job fixture twice.

The report reuses existing H6 and C5.1 ownership oracles rather than cloning
their semantics. Its Product rejection case supplies a Windows mechanics
profile to the only current native-profile bridge and requires the stable
`worker_native_profile_unsupported` result before any Windows private import
or platform acquisition.

## Retained Fences

- no Windows `ProductWorkerNativeProfilePort` implementation or dispatch;
- no production Product composition, allowlist issuer, or owner-default change;
- no AppContainer, full loader-closure, or required-containment claim;
- no raw handle, path, environment, or native exception text across Hosting;
- no same-attempt fallback to Current; and
- C5.4 may revise only the exact Linux Coding canary absence.

## Exit Gate

C5.3 is complete only when the private builder and API-source guards pass, the
required Windows AMD64 report is verified against the manifest and uploaded,
the H6.3 native report remains green, and source scans prove that Harness and
all Products still lack a Windows private-profile dependency.
