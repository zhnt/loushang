# H6.2 POSIX Native Managed Launch Preparation Record

## Status

- ID: `HOST-H6.2-POSIX-NATIVE`
- Scope: `hosting`
- Parent: `HOST-H6`
- Authority: descriptive — implementation validation record
- Design status: not-applicable
- Implementation status: implemented
- Native activation: none; the private backend requires explicit trusted injection
- Runtime posture: default-dark; Current remains the default Worker owner
- Delivery parent: `a9c3e9f4`
- Owner: Loushang Hosting maintainers

## Result

H6.2 implements a Linux x86_64-only, private managed-launch preparation backend for
two deliberately closed static-ELF profiles. The release profile,
`posix-static-contained-elf-v1`, captures both a caller-admitted containment
launcher and its payload into separate write-sealed memfds, retains the cwd by
directory descriptor, and invokes the launcher through one fixed private
argument protocol. The caller continues to own the meaning and admission of
the containment profile; Hosting proves only that the admitted launcher,
payload, cwd, profile digest, and invocation reached the sole spawn effect.

No public Hosting contract or factory selects this backend. No Harness Worker
route is activated by H6.2.

## Supported Native Profiles

| Profile | Purpose | Closed execution identity |
| --- | --- | --- |
| `posix-static-elf-v1` | direct native-mechanics oracle | one static payload digest, cwd device/inode, and Linux x86_64 syscall ABI |
| `posix-static-contained-elf-v1` | required-containment release profile | static launcher digest, static payload digest, cwd device/inode, caller-owned containment-profile digest, fixed invocation protocol, and Linux x86_64 syscall ABI |

Both profiles require absolute executable and cwd paths at capture, an empty
effective environment, bounded regular executable files, the current machine
ELF identity, and no `PT_INTERP` or `PT_DYNAMIC` program header. Scripts,
dynamically loaded executables, mutable loader search, and ambient fallback are
therefore rejected rather than described as closed.

This check closes the kernel's startup ELF interpreter/loader chain. It does
not prove that arbitrary admitted static code will never later map executable
content, call `dlopen`, or exec another image. Runtime code-loading and child
execution constraints remain caller-owned semantic evidence bound to the exact
launcher, payload, and containment-profile digests; an adapter without that
evidence cannot admit this profile.

The direct profile remains useful as a smaller descriptor and lifecycle
oracle. Required-containment conformance depends on the contained profile; a
direct static launch is not described as a security sandbox.

## Ownership And Spawn Mechanics

1. The reservation-scoped H6.1 capture capability calls the exact Linux
   backend.
2. The backend opens source paths with `O_NOFOLLOW`, checks stable metadata and
   content digests while copying, seals each memfd against write, growth,
   shrink, and further seal changes, and opens the cwd as a directory.
3. The material attaches synchronously to the active Child Session reservation
   before capture returns.
4. Final verification rechecks memfd identity, seals, complete digest, and cwd
   identity immediately before claim.
5. The matched POSIX Process backend claims the endpoint and preparation
   descriptors, rejects every collision, and supplies only their de-duplicated
   union through `pass_fds` with `close_fds=True`.
6. For the contained profile, the sealed launcher receives the exact protocol,
   profile digest, payload descriptor, preparation descriptor manifest, and
   original payload argv. The test launcher closes preparation descriptors on
   payload exec and applies the admitted profile before that exec, including
   denial of process-group/session escape required by the POSIX tree owner.
7. Process-group ownership and the H6.1 joined lease reclaim the tree, endpoint,
   native material, caller semantic lease, and capacity.

The sole effect authority can distinguish three facts: validation failed
before creation, a future narrow native creation primitive settled with proof
that no process remains, or the outcome is unknown. The current asyncio POSIX
operation spans native creation plus transport and child-watcher setup, so this
backend does not mint the second receipt from its exceptions. Once its effect
gate is crossed, every unreceipted failure remains fenced and blocks retry.

## Retained Native Oracle

`tests/hosting/test_posix_launch_preparation.py` compiles static native fixtures
and proves:

- payload, containment launcher, and cwd replacement after capture cannot
  substitute the launched identities;
- the contained launcher applies `PR_SET_NO_NEW_PRIVS` and a seccomp profile
  that rejects network socket creation plus descendant `setsid`/`setpgid`
  escape before executing the payload;
- dynamic loader/interpreter chains, symlink traversal, non-empty loader
  environment, digest mismatch, cwd mismatch, and inconsistent closure fail
  closed;
- unrelated inheritable descriptors do not reach the child and endpoint plus
  preparation descriptor collisions fail before the effect;
- an exception injected after native creation leaves the reservation and host
  fenced, retains ownership debt, and blocks a fresh retry;
- cancellation after process creation still attaches and reclaims the complete
  process group; and
- a reported Linux `close(2)` failure consumes that descriptor owner before
  the call and never retries a numeric fd that another thread may have reused.

The Ubuntu Hosting workflow emits `h6-posix-native.xml`, rejects an empty,
skipped, failing, or error report, and retains that report as an artifact. A
missing static compiler or unsupported Linux primitive fails the native gate;
it is not converted into a skip.

## Explicit Limits

- This evidence is Linux x86_64-specific. Other Linux architectures, macOS,
  and other POSIX systems do not select either profile until retained native
  evidence is added for a new exact platform identity.
- Hosting does not ship, discover, or approve a containment launcher. Trusted
  composition must supply one whose identity and semantic evidence were
  admitted by the caller-owned Sandbox authority.
- An admitted launcher/profile must forbid descendant process-group escape and
  constrain any runtime code-loading or subsequent exec behavior required by
  its Sandbox policy. The static ELF header check alone is not that evidence.
- The current dynamic bubblewrap Worker path is not silently reclassified as
  this static profile. H6.4 must adapt an eligible exact launcher/profile or
  remain unavailable for that request.
- Product activation, Worker handshake, generation publication, fallback, and
  policy interpretation remain outside Hosting and unchanged.
