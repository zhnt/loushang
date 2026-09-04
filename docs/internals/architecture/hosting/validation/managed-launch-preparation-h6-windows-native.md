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
`windows-restricted-known-dll-pe-v1`. It retains a non-reparse executable and
cwd by Win32 handle and file identity, verifies the executable digest and PE
shape, creates a restricted primary token and kill-on-close Job Object, and
performs the unique process-creation effect with `CreateProcessAsUserW`.

The profile is private and default-dark. It does not make an arbitrary Windows
executable, Python Worker, AppContainer, or legacy PLC9B restore route
conformant, and it changes no public Hosting factory or Product owner choice.

## Closed Profile

The captured execution closure contains:

- the exact AMD64 PE SHA-256 and locked Win32 volume/file identity;
- the locked cwd volume/file identity;
- the fixed restricted-token recipe `DISABLE_MAX_PRIVILEGE | LUA_TOKEN |
  WRITE_RESTRICTED`;
- the exact direct-import set, currently limited to `KERNEL32.DLL` and
  `ADVAPI32.DLL`; and
- the exact Windows AMD64 major/minor/build platform identity.

The PE verifier rejects non-AMD64 images, truncated metadata, delayed imports,
CLR images, imports outside the fixed platform-image set, and a digest or
direct-import mismatch. The selected oracle uses no CRT or application DLL.
Its direct dependencies are admitted as Windows platform KnownDLL identities
bound to the exact OS build rather than copied application files.

This is a startup image-closure claim, not a proof that arbitrary admitted
native code can never call `LoadLibrary` or create another image. Caller-owned
Sandbox admission must bind any stronger runtime behavior to the executable
digest and this exact restriction profile. H6.3 proves the selected native
mechanics and retained oracle only.

## Ownership And Effect Boundary

1. The Windows material object attaches to the active Child Session
   reservation before acquiring its first handle. Partial acquisition failure
   therefore leaves executable, cwd, source-token, restricted-token, Job, and
   stderr owners reachable by rollback.
2. Executable and cwd handles reject reparse points. The executable handle
   permits read sharing only, preventing write/delete substitution; the cwd
   handle permits read/write but not delete sharing, preventing direct
   rename/replacement while prepared.
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
   to the Process owner before synchronous attachment. Executable, cwd, and
   token locks remain with the joined preparation lease until process-tree
   settlement.
7. Close retries only handles whose Win32 close reported failure and preserves
   cleanup debt until every retained owner settles.

## Retained Native Oracle

The Windows-only native gate compiles a no-CRT AMD64 PE fixture and proves in
one endpoint-plus-preparation spawn that:

- executable overwrite and cwd rename are denied while capture is paused;
- the child observes a restricted token and an empty caller environment;
- the exact endpoint handle list carries the raw handshake;
- a descendant created by the restricted root remains in the atomically
  assigned Job and the complete Job is empty before close returns; and
- the executable imports only the admitted platform KnownDLL set.

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
- Holding the executable and final cwd objects closes direct replacement. A
  future profile that treats ancestor path mutation as hostile must retain and
  verify its complete ancestor chain or use a stronger image-by-handle
  primitive.
- The fixed platform-import rule is intentionally too narrow for Python and
  the Current Harness Worker. H6.4 must remain unavailable on Windows unless a
  caller supplies an executable that satisfies this exact profile.
- Product activation, Worker handshake, generation publication, fallback, and
  Sandbox policy interpretation remain outside Hosting and unchanged.
