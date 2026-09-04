# H6.3 Windows Native Managed Launch Preparation Record

## Status

- ID: `HOST-H6.3-WINDOWS-NATIVE`
- Scope: `hosting`
- Parent: `HOST-H6`
- Authority: descriptive — implementation validation record
- Design status: not-applicable
- Implementation status: implemented
- Native activation: none; the private backend requires explicit trusted injection
- Runtime posture: default-dark; Current remains the default Worker owner
- Delivery parent: `c3fca03c`
- Owner: Loushang Hosting maintainers

## Result

H6.3 implements one deliberately narrow Windows AMD64 managed-launch profile,
`windows-restricted-direct-import-pe-v1`. It retains a non-reparse executable,
cwd, and their complete local-volume ancestor directory chains by Win32
handle, verifies 128-bit `FileIdInfo`, the executable digest, and PE shape,
creates a restricted primary token and kill-on-close Job Object, and performs
the unique process-creation effect with `CreateProcessAsUserW`.

The profile is private and default-dark. It does not make an arbitrary Windows
executable, Python Worker, AppContainer, or legacy PLC9B restore route
conformant, and it changes no public Hosting factory or Product owner choice.

## Closed Profile

The captured execution closure contains:

- the exact AMD64 PE SHA-256 and locked Win32 volume/128-bit file identity;
- the locked cwd volume/128-bit file identity;
- the fixed restricted-token recipe `DISABLE_MAX_PRIVILEGE | LUA_TOKEN |
  WRITE_RESTRICTED` plus one `WinRestrictedCodeSid` restricting SID;
- the exact direct-import set, currently limited to `KERNEL32.DLL` and
  `ADVAPI32.DLL`; and
- the exact Windows AMD64 major/minor/build platform identity.

The PE verifier rejects non-AMD64 images, truncated or overlapping metadata,
resources/embedded manifests, delayed imports, CLR images, imports outside the
fixed direct-name set, and a digest or direct-import mismatch. The selected
oracle uses no CRT or application DLL.

This is deliberately a **direct-import mechanics profile**, not a Windows
loader-closure or DLL-identity claim. The OS build string is a platform
compatibility fence; it does not identify KnownDLL sections, servicing
revisions, API-set resolution, SxS activation contexts, or every image that the
loader may map. Nor does the profile prove that admitted native code can never
call `LoadLibrary` or create another image. Caller-owned Sandbox admission must
bind any stronger behavior to a separately accepted profile and evidence.

## Ownership And Effect Boundary

1. The Windows material object attaches to the active Child Session
   reservation before acquiring its first handle. Partial acquisition failure
   therefore leaves executable, cwd, ancestor-chain, source-token,
   restricted-token, Job, and stderr owners reachable by rollback. Helpers
   transfer a raw file/Job handle to that material before any validation or
   configuration that can fail.
   It declares the complete 53-slot worst-case handle bound at attachment;
   ancestor discovery cannot grow the reservation after admission.
2. Executable and cwd handles reject reparse points. The executable handle
   permits read sharing only, preventing write/delete substitution; the cwd
   handle permits read/write but not delete sharing. Every resolved ancestor
   directory except the immutable volume root is retained without delete
   sharing, preventing an ancestor rename/rebind from retargeting the string
   passed to `CreateProcessAsUserW` while prepared.
3. Final verification rechecks both handle identities, the complete image
   digest/import table, `IsTokenRestricted`, and Job kill-on-close immediately
   before claim.
4. The matched Process backend rejects endpoint/preparation handle aliasing.
   The only inherited values are the endpoint stdin/stdout and captured stderr
   NUL handle in `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`; the pre-created Job is in
   `PROC_THREAD_ATTRIBUTE_JOB_LIST`.
5. A synchronous Win32 seam crosses the H6 effect gate immediately before
   `CreateProcessAsUserW`. Expected setup failure mints only a pre-effect
   receipt. A false CreateProcess result mints the distinct native
   settled-without-process receipt. Unexpected post-gate failure stays fenced.
6. On success, the process, primary-thread, Job, and child stderr handles move
   to the Process owner before synchronous attachment. The provisional Process
   owner is attached before endpoint transfer can fail; pre-attachment cleanup
   debt is retained by the backend. Executable, cwd, ancestor, and token locks
   remain with the joined preparation lease until process-tree settlement.
7. Close retries only handles whose Win32 close reported failure and preserves
   cleanup debt until every retained owner settles.

## Retained Native Oracle

The Windows-only native gate compiles a no-CRT AMD64 PE fixture and proves in
one endpoint-plus-preparation spawn that:

- executable overwrite plus cwd and ancestor rename are denied while capture
  is paused;
- the child observes a restricted token and an empty caller environment;
- the exact endpoint handle list carries the raw handshake;
- a descendant created by the restricted root remains in the atomically
  assigned Job and the complete Job is empty before close returns; and
- the executable has only the admitted direct-import names.

Cross-platform fake tests retain partial acquisition, exact native argument
composition, endpoint/preparation collision, native no-process settlement,
and retryable handle-cleanup faults. A separate platform test proves that the
native backend either constructs on Windows AMD64 or fails closed.

The Windows Hosting workflow emits `h6-windows-native.xml`, rejects an empty,
skipped, failing, or error report, and retains it as an artifact. Missing MSVC,
restricted-token support, atomic Job-list support, or another required Win32
primitive fails the gate rather than becoming a skip.

## Explicit Limits

- AppContainer is not selected by this profile. Its isolation semantics,
  profile lifecycle, filesystem ACLs, and capability SIDs require a separate
  accepted profile and native oracle.
- Windows ARM64 and older Windows hosts remain unsupported for this profile.
- Only resolved local-volume paths with a bounded complete ancestor chain are
  accepted. UNC paths and reparse-point identities remain outside this profile.
- The fixed direct-import rule is not a loader closure. A stronger profile must
  bind loader redirection, activation-context/SxS inputs, API-set resolution,
  KnownDLL registration/sections, and actual platform-image identities with
  its own native substitution oracle.
- External `.local`/`.manifest` absence is not a stable property of this
  profile: a writable parent can create a new entry after verification. Such
  sidecars are therefore outside the direct-import claim, not an admitted
  security fact.
- The fixed direct-import rule is intentionally too narrow for Python and
  the Current Harness Worker. H6.4 must remain unavailable on Windows unless a
  caller supplies an executable that satisfies this exact profile.
- Product activation, Worker handshake, generation publication, fallback, and
  Sandbox policy interpretation remain outside Hosting and unchanged.
