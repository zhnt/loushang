# PLC9C5 C5.0 Product/Native Worker Activation Baseline

## Status

- ID: `PLC9C5-C5.0`
- Scope: `loushang.harness` Worker activation boundary plus one Product-owned
  canary composition
- Parent: `PLC9C`
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented through C5.5b — C5.0 design/guards,
  C5.1 receipt/lifecycle, C5.2 Linux native profile binding, C5.3 Windows
  mechanics/rejection, and the C5.4 Linux Coding Product canary; C5.5a design and the
  C5.5b Windows LPAC native candidate; C5.5c Product composition remains
  unimplemented
- Activation status: explicit Linux Coding canary accepted; default remains
  Current and Windows/every unlisted platform remain closed
- Observation base: merged C5.5a design baseline `68151253`
- Owner: Harness Worker architecture with Product, Hosting, and domain-owner
  review

## Purpose And Acceptance Boundary

C5.0 fixes the design, Current inventory, dependency direction, rollout
matrix, and executable transition/deletion guards for PLC9C5. C5.1 adds the
receipt/lifecycle contract, C5.2 adds only the default-dark Linux native
profile capability, and C5.3 retains the Windows mechanics while proving that
they are not accepted Product containment. C5.4 adds the sole explicit Coding
Product composition that may request Hosting when an exact receipt, stable
Session locator, Linux native-profile capability, and Capability owner all
converge. Omission and every unmatched route retain Current.

The first canary is one exact, read-only `capability_provider` contribution
selected by the Coding Product. Coding is the first evidence Product, not the
owner of the shared Worker mechanism. Work, PPT, Design, or a future AppHost
Product can reuse the same Harness contracts only by supplying their own
explicit Product policy and admission receipt. C5.0 does not add an AppHost,
AppServer, AppService, UI, author-SDK, or remote-service dependency.

This baseline refines the
[PLC9C Local Worker Boundary](plugin-lifecycle-plc9c0-baseline.md), uses the
source-backed [C5.0 Current inventory](plugin-lifecycle-plc9c5-c50-inventory.md),
and implements the G7 planning gate in the
[Hosted Product Runtime V1 delivery plan](../../drafts/hosted-product-runtime-v1-plan.md).
The accepted [HOST-H6 managed preparation design](../../hosting/managed-launch-preparation-h6.md)
and its H6.4 Harness parity evidence remain mechanical prerequisites, not
Product activation authority.

## First-Principles Decisions

1. **Selection is authority, detection is not.** Only an explicit Product
   allowlist entry for one immutable Plugin revision and contribution may ask
   for a Worker owner. An environment variable, host platform, available
   backend, discovered executable, missing setting, or test fixture can never
   choose Hosting.
2. **The receipt is the join.** One immutable, pathless Product activation
   receipt binds Product/scope/Session, Plugin revision, declaration and Worker
   configuration, declared and effective required/optional policy, requested
   owner, allowed native profile catalog and policy closure, policy revision,
   and selection generation.
   Every downstream preparation, attempt, status, and rollback record must
   point to that exact receipt.
3. **A profile is an admitted capability, not configuration text.** Product
   policy chooses from named logical profiles. A narrow Harness/Hosting friend
   adapter maps an already admitted receipt to one exact private H6 native
   profile. Product code never imports H6 private specifications or handles;
   Hosting never reads Product, Plugin, Approval, or generation vocabulary.
4. **One attempt has one owner.** The owner snapshot is taken before the first
   acquisition and stays sticky until that attempt terminates. Failure after
   selection never retries Current or Hosting inside the same attempt.
5. **Health precedes semantic visibility.** A PID, native spawn, endpoint, H6
   lease, protocol handshake, or activation receipt alone publishes no domain
   generation. Required contribution failure aborts Product/Session
   activation; optional failure may produce an explicit degraded state only.
6. **Rollback changes future policy.** A kill switch or rollback latch first
   forbids new Hosting attempts, then fences, drains, and terminates existing
   attempts through their exact owners. Future attempts may use the Current
   process owner only after the prior receipt becomes stale and Product issues
   a new Current-owner receipt. An in-process or different-Worker fallback
   additionally needs a distinct contribution identity.
7. **Recovery proves absence before restart.** The first route never adopts a
   surviving Worker. Restart requires durable attempt evidence, generation
   fencing, and proof that the complete prior process tree was reaped. Unknown
   state fails closed.
8. **Entrypoints share composition, not flags.** Coding CLI, native TUI, RPC,
   channel, prompt, plain, and workflow routes that construct an Agent Product
   Session must consume the same Product receipt at their shared construction
   boundary. Early-dispatch commands that do not construct that Session are
   not canary-capable and must remain unable to activate a Worker.

## System Boundary And Responsibility Chain

```text
Coding Product policy / another explicit Product policy
  -> immutable Product Worker activation receipt
     -> Product-owned canary composition adapter
        -> Harness Worker admission + sticky owner router
           -> Current Process/Sandbox owner
           OR
           -> Harness-to-Hosting native profile friend adapter
              -> Hosting opaque H6 preparation + atomic Child Session
        -> Worker supervisor + exact Capability query adapter
           -> exact Product/domain readiness owner

Session discovery/catalog -> selected locator + Product profile validation
                          -> Product receipt (never the reverse)
```

The selected Plugin reservation is the source of declared requiredness. The
Product is the sole writer of the effective activation policy after rejoining
that reservation: it may strengthen an optional contribution to required, but
it cannot downgrade a declared required contribution to optional.
Harness Worker is the sole writer of Worker-attempt admission and protocol
state. Hosting is the sole writer of native preparation/process/endpoint
state. The exact domain owner is the sole writer of generation visibility and
retirement. Session discovery is a read model and grants none of those
authorities.

## Dependency Contract

| Scope | May depend on | Receives or returns | Forbidden dependency or authority |
| --- | --- | --- | --- |
| exact Product adapter | public Harness declaration/selection and Worker activation contracts | an explicit allowlist decision that preserves declared requiredness, a pathless activation receipt, and a separate current-evidence port | private Hosting modules, raw Process/Sandbox owners, native paths/handles, environment-driven owner selection |
| Harness Worker activation coordinator | Product receipt plus public Worker, Sandbox, and domain ports | one sticky attempt plan and bounded status | selecting a Product, reading ambient configuration, publishing a domain generation, same-attempt fallback |
| Harness native-profile friend adapter | validated Product receipt, Worker runtime binding, injected H6 capability | one exact private H6 preparation port or a fail-closed unsupported result | Product policy, Plugin management, generation state, raw material export, profile substitution |
| Hosting | Hosting contracts and private platform mechanics only | opaque preparation, atomic process/endpoint lease, bounded evidence | Harness, Product, Plugin, AppHost, domain status, Approval, Authorization, or fallback imports |
| Worker supervisor | launch/session port, protocol transport, durable attempt journal | handshake/health/fence/shutdown evidence | Product selection, native material, semantic publication or retirement |
| Capability canary adapter | healthy supervisor plus exact Capability authority reader | bounded read-only descriptors | mutation, deletion, credentials, arbitrary execution, registrar/Store/ledger access |
| Session discovery/profile validation | configured canonical and compatibility sources plus Product profile codec | selected stable locator, alias/conflict facts, validated Product snapshot | Worker activation, writable root authority, inferring Product from cwd or filename |
| presenter/transport | Product Session application port | Product-owned status projection | constructing receipts, selecting profiles, importing Worker/Hosting implementations |

The only new private cross-package edge contemplated by C5 is
`src/loushang/harness/worker/_native_profile_bridge.py`. That one private
Harness Worker module owns the implemented Linux dispatch and is the sole
possible owner of any later accepted Windows dispatch, loads platform code
explicitly and lazily, and exposes only `ProductWorkerNativeProfilePort` to
the coordinator.
It may import exactly
`_PosixStaticContainedLaunchCaptureSpec` and
`_PosixStaticLaunchCaptureBackend` for the accepted Linux path. The existing
Windows private names remain forbidden until a later transition names the
exact symbols it needs; `_win32_process` and raw platform APIs are never legal
imports. No second friend module and no import from the public
`hosting_adapter.py` are permitted. Public Hosting contracts remain
Product-neutral, and Product packages depend only on public Harness
records/ports.

`src/loushang/harness/worker/__init__.py` is the Worker public API owner. C5.1
adds only `ProductWorkerActivationPolicyV1`,
`ProductWorkerActivationReceiptV1`,
and `ProductWorkerActivationAuthorityPort` to that public surface. The C5.1
`ProductWorkerActivationCoordinator` remains internal until a stable typed
outcome/error and durable-owner seam exists. C5.2 adds only
`ProductWorkerNativeProfilePort`. Private coordinator/store/lease/record,
bridge/profile types, Product adapters, Hosting specifications, native
material, and platform handles must never be exported there.

## Activation Receipt Contract For C5.1

C5.1 introduces an authority-free schema and validator with these exact
semantic fields. Spelling and serialization are fixed by the
[C5.1 contract](plugin-lifecycle-plc9c5-c51-contract.md):

| Receipt fact | Required binding |
| --- | --- |
| Product scope | `product_id`, Product runtime/scope identity, Session identity |
| Session route | new-Session marker or an opaque fingerprint of the exact selected source/locator/revision; no filesystem path is exposed |
| immutable contribution | Plugin id, immutable revision digest, contribution id, reservation/declaration/Worker-configuration fingerprints |
| policy | declared and effective required versus optional, Product policy revision, explicit enabled/disabled decision; effective policy cannot weaken the declaration |
| owner | requested owner, owner-selection generation, no-fallback invariant |
| native eligibility | logical profile id, immutable native-profile catalog revision, exact allowed native profile ids, and an opaque native-policy-closure fingerprint; for Linux this binds the admitted payload, static launcher, and containment-profile digests; no raw path, descriptor, handle, token, or environment |
| freshness | receipt version and issue sequence/nonce plus Product policy, locator, owner-selection, and kill-switch generations; the coordinator separately receives a Product-owned current-evidence port so the receipt remains immutable and serializable |

`WorkerHostingActivationV1` is currently only an owner-selector input and
`WorkerHostingSelectionV1` is only a diagnostic snapshot. Neither is the
Product receipt. `WorkerLaunchEvidenceV1` proves one launch request, not the
Product decision that authorized it. C5.1 must bind those existing records to
one receipt rather than reinterpret any of them.

The expected and realized policy-closure fingerprints share one canonical
hash domain, `loushang.worker.native-policy-closure.v1`. Its length-prefixed
UTF-8 fields, in fixed order, are native-profile catalog revision, native
profile id, payload SHA-256, containment-launcher SHA-256, and containment-
profile SHA-256; absent fields use the contract's explicit empty marker. The
receipt carries the expected fingerprint. Native attempt evidence recomputes
the realized fingerprint from the captured, private H6 material, and admission
requires exact equality. The separate full `execution_closure` fingerprint
also binds cwd identity, invocation, and observed platform facts for audit and
substitution evidence; it is never directly compared with the policy-closure
fingerprint because their hash domains differ.

The authority port returns an exact current witness over
`(receipt fingerprint, Product-policy revision, selected-locator revision,
owner-selection generation, kill-switch generation)`. The coordinator must
validate it while holding one serialized admission lease before first native
acquisition and retain that lease until the attempt is registered and the H6
process effect has either begun or settled without a process. Before domain
publication, the coordinator reacquires that same serialized admission gate;
current-witness verification and the domain-owner publication CAS occur inside
one lease with no awaitable/user callback gap. The CAS compares the receipt's
Product-policy, locator, owner-selection, and kill-switch generations as well
as `(receipt fingerprint, attempt id, owner generation)`. A kill switch latches
and stales generations under the same gate, so an old receipt either publishes
before the latch and enters the enumerated active set or its publication CAS
fails with no visibility. Retirement uses the exact receipt/attempt/owner key,
and a stale attempt can retire only its own exact generation. A restart-budget
claim is legal only after protocol terminal, exact domain retirement, and
durable tree cleanup settlement have all joined by CAS.

The H6 attempt evidence records the immutable native-profile catalog revision,
the realized policy-closure fingerprint, the separate full
`execution_closure` fingerprint, and the logical/native profile ids. The
coordinator compares catalog/profile identity and the same-domain expected and
realized policy-closure fingerprints before publication. H6 remains
Product-neutral: it validates captured material against its private spec,
while the serialized Harness admission lease closes the policy-change race
through process-effect registration.

C5.1 also introduces a Product-neutral durable cleanup settlement/debt
contract keyed by receipt fingerprint, attempt id, owner generation, host
identity, boot identity, and a construction-pinned evidence-authority identity
and fingerprint. Record APIs accept only opaque witnesses and cannot replace
that authority per call. A protocol terminal record is not cleanup settlement.
On coordinator restart, an unknown same-boot tree is durable debt and blocks
restart; a trusted changed-boot witness may prove the old local OS tree absent.
An uncertain committed `registered` record is settled on the same boot when
possible or through exact changed-boot lease-expiry recovery; it can never be
promoted to effect. Platform-specific crash settlement evidence is an exit gate
of C5.2/C5.3, not something deferred to Product composition.

The guard ledger reserves these transition tokens so later slices revise an
exact absence instead of inventing a neighboring contract:

| Token | First permitted slice | Meaning |
| --- | --- | --- |
| `ProductWorkerActivationPolicyV1` | C5.1 | authority-free explicit Product policy input |
| `ProductWorkerActivationReceiptV1` | C5.1 | validated pathless decision join |
| `ProductWorkerActivationAuthorityPort` | C5.1 | separate Product-owned current-evidence fence |
| `ProductWorkerActivationCoordinator` | C5.1 internal | Product-neutral deterministic aggregate over injected owners; no public facade or Product selection |
| `WorkerCleanupSettlementV1` | C5.1 | durable exact-attempt tree-settlement witness |
| `WorkerCleanupDebtV1` | C5.1 | durable unknown/unsettled tree fence |
| `ProductWorkerNativeProfilePort` | C5.2 | confined native-profile binding port implemented per accepted platform |
| `bind_coding_product_worker_canary` | C5.4 | the sole first production Product composition root |

## Native Compatibility Delta

H6.4 proves that a caller-managed preparation port survives the Harness
semantic fence. It does not prove that either native profile can consume the
Current Worker shape.

| Platform/profile | Already proven | Blocking C5 delta | Owning slice |
| --- | --- | --- | --- |
| Linux x86_64, excluding WSL, `posix-static-contained-elf-v1` | H6.2 seals one static launcher and payload, retains cwd, transfers only the exact endpoint/preparation descriptors, and owns process-group cleanup | implemented in C5.2: Product policy admits the exact payload/launcher/containment-profile closure; the unique bridge rejects WSL/unknown/non-x86 before H6 selection; same-boot crash uncertainty remains durable cleanup debt | C5.2 Linux native report retained; consumed only by the exact C5.4 Coding Product root |
| Windows AMD64 `windows-restricted-direct-import-pe-v1` | H6.3 locks PE/cwd/ancestors, creates a restricted token and kill-on-close Job, constrains the handle list, and proves direct-import mechanics | **Not accepted as Product required containment.** It is a trusted-payload mechanics profile only. A Hosting-private opaque builder must obtain locked file identities and query `GetWindowsDirectoryW` for a canonical absolute `SystemRoot`; it never reads `os.environ`. Ambient `SystemRoot` poisoning is ignored, while any caller-supplied environment/SystemRoot is rejected before acquisition. Harness/Product never receives raw handles or environment. The builder preserves H6.3 discarded stderr and cannot reuse H6.4's piped-stderr mapping. Windows Product canary remains closed until a separate security-reviewed containment profile is accepted | C5.3 retained mechanics/fail-closed gate; no Product activation |
| macOS, WSL, unknown Linux classifier result, non-x86_64 Linux, non-AMD64 Windows, every unlisted environment | no accepted PLC9C5 Product native profile | remain unsupported with a stable fail-closed result; no best-effort/current same-attempt downgrade | retained through C5.4 |

Platform observation may choose among the receipt's already allowed native
profiles only after the receipt explicitly requests Hosting. It may reject an
unsupported host, but it cannot cause Hosting selection.

The first Product canary is therefore Linux-only. The parent G7 Windows
required-containment row remains deliberately open: current H6.3 evidence
cannot satisfy it, and C5.3 must prove both that its mechanics are retained and
that Product required-containment policy rejects that profile. A future slice
may reopen Windows only with a separately accepted profile and exact guard
transition; C5.0 does not pre-authorize an AppContainer or claim equivalence.

## G7 Acceptance Coverage

The rows below reproduce the parent G7 matrix without narrowing it. C5.0 adds
slice ownership and evidence rules; a later slice cannot declare G7 complete
by testing only its platform.

| Dimension | Required cases | Owning slice and evidence |
| --- | --- | --- |
| Product route | explicit selected Product, missing Product, wrong Product, disabled contribution | C5.1 receipt validation; C5.4 real Coding Product composition |
| Session route | canonical and cwd/home compatibility projections, tampered/unknown Product envelope, alias, conflict, and changed locator | C5.4 selects a stable locator and validates Coding's persisted Product profile before issuing a receipt; generic pre-routing AppHost behavior remains G5/G8 |
| contribution policy | required success/failure and optional success/degraded failure | C5.1 deterministic aggregate contract; C5.4 Product readiness conformance |
| native platform | Linux required containment and Windows required containment; unsupported hosts fail closed | C5.2 retained Linux native report; C5.3 retained Windows mechanics and required-containment rejection report; C5.4 unsupported-host conformance; C5.5b/C5.5c plan separate Windows native/Product reports; G7 stays open until both are implemented and accepted |
| preparation | executable/cwd replacement, stale authority, handle/fd substitution, unsupported profile | C5.2/C5.3 adversarial native tests plus C5.4 receipt-freshness tests |
| lifecycle | cancellation at each acquisition, early exit, handshake failure, heartbeat loss, clean stop, forced kill | C5.2/C5.3 platform ownership tests and C5.4 aggregate lifecycle tests |
| recovery | prior attempt absent, confirmed reaped, uncertain tree, restart-budget exhaustion, host restart | C5.1 durable settlement/debt contract; C5.2/C5.3 platform crash evidence; C5.4 Product recovery drill; adoption remains forbidden |
| publication | no generation before handshake/domain admission; stale attempt cannot publish or retire successor | C5.1 fake owner contract and C5.4 real Capability owner conformance |
| rollback | future attempts return to Current owner; in-flight owner is sticky; no same-attempt fallback | C5.1 serialized admission/active-registry contract and C5.4 forced rollback drill |
| entrypoint | every Current canary-capable CLI/TUI/Product composition path shares the exact activation receipt; hosted paths join only after A0.4 is separately accepted | C5.4 cross-entrypoint receipt identity report; early-dispatch non-Session routes remain unable to activate |

For the Session row, Coding already persists a Product-bound runtime profile
and refuses a foreign Product snapshot when restoring. C5.4 may reuse that
Product-owned validation after discovery selects a stable locator. It must not
claim the generic pre-routing Session Identity Envelope proposed for AppHost,
and G7 remains independent of AppHost G5/G6.

## Product Activation And Rollback Matrix

| State or event | Required contribution | Optional contribution | Owner/publication invariant |
| --- | --- | --- | --- |
| receipt omitted or disabled | Product/Session uses Current behavior and reports `disabled_by_policy` for the canary | same | no Hosting construction, native acquisition, process, handshake, or generation |
| receipt invalid, stale, foreign, or ambiguous | activation fails atomically as unavailable | degraded continuation is legal only when an independent current reservation/policy witness proves the contribution optional; an invalid receipt's optional bit is never evidence | if current requiredness cannot be proven independently, fail closed; no process and no domain publication |
| native profile unsupported or preparation rejected before spawn | activation fails atomically | explicit degraded result is allowed | selected owner is not retried; no spawn/publication |
| spawn or handshake/domain admission fails | activation fails and owned native/process/endpoint state is reclaimed | explicit degraded result after complete reclamation | no generation; no other owner within the attempt |
| healthy and domain-admitted | Product may become ready | Product may become ready | exact receipt/attempt becomes visible only through the domain owner |
| runtime health lost after visibility | Product becomes unavailable until explicit recovery/replacement | Product becomes degraded while unrelated contributions continue | stale attempt fenced; exact generation revoked/drained before restart |
| rollback or kill switch | new Hosting attempts are forbidden; required Product readiness reflects the disabled state | new Hosting attempts are forbidden and Product may remain degraded | under the same serialized gate: atomically close Hosting admission, bump/stale the generation, then enumerate the complete active registry; in-flight owners stay sticky while fenced/drained/terminated; the durable latch is restored closed after host restart; a future Current attempt requires a new receipt/selection snapshot |
| cleanup debt or uncertain old tree | recovery remains unavailable | degraded only if Product policy permits omission | no restart, no fallback, no success settlement |

Status and diagnostics are pathless, bounded, and versioned. They distinguish
at least disabled policy, unsupported platform/profile, stale authority,
containment/preparation failure, launch failure, handshake/protocol failure,
runtime loss, cleanup debt, and restart exhaustion.

## Delivery Slices

| Slice | Delivery | Exit condition | Production default |
| --- | --- | --- | --- |
| C5.0 | this target baseline, exact Current inventory, G7/mismatch/rollback matrices, and deletion/absence guards | five-view design review passes; targeted architecture/static checks pass | unchanged Current; no Product activation symbols or composition |
| C5.1 | authority-free Product activation receipt, explicit allowlist/policy validation, serialized admission/active registry, durable cleanup settlement/debt, status vocabulary, and deterministic fake aggregate | required/optional, stale/foreign/disabled, receipt-to-attempt identity, pre-acquire freshness, atomic pre-publication witness+CAS including the kill-switch interleaving, exact-generation retirement CAS, restart latch, settlement/debt, and sticky rollback tests pass | receipt omission disables Hosting; no native or production composition |
| C5.2 | Linux x86_64 contained-profile implementation in the unique private bridge and canary oracle | exact catalog/expected-realized policy/full execution closure, static payload/launcher/profile, WSL/unknown/non-x86 classifier rejection, fd inheritance/substitution, cancellation, same-boot crash debt, changed-boot absence, process-tree cleanup, and sentinel redaction rows pass in the retained required report | no production Product composition |
| C5.3 | Windows AMD64 Hosting-private trusted-payload profile builder, restricted-mechanics oracle, and Product rejection gate | native file identity, `GetWindowsDirectoryW` canonical absolute `SystemRoot`, ambient poisoning ignored, caller environment rejected, discarded stderr, token/Job/handle-list substitution, cancellation, restart uncertainty, sentinel redaction, and explicit required-containment rejection pass in the retained required report | no Windows Product activation and no production Product composition |
| C5.4 | one explicit Linux Coding Product canary composition, Session/entrypoint convergence, recovery, rollback, status, and publication closure | all non-Windows G7 rows and Linux required containment pass with no required skip; Windows and every unsupported profile fail closed; ordered rollback/recovery and receipt identity reports pass | Current unless the exact Product allowlist/receipt explicitly selects Hosting on accepted Linux; parent G7 remains open on Windows |
| C5.5a | Windows LPAC threat model, immutable-material-versus-attempt ownership, exact Current delta, evidence matrix, and architecture guards | five-view design review passes with no production source change | Windows remains closed |
| C5.5b | Hosting-private zero-capability per-attempt LPAC provisioner/native profile and mandatory native report | exact SID/capability/LPAC/grant/private-state/environment/handle/Job/lifecycle/containment-cleanup evidence passes on Windows with no skip | default-dark; no Harness/Product consumer |
| C5.5c | cleanup V2 migration, exact same-file Harness friend dispatch, and Coding Product Windows convergence | Windows reproduces the Product/Session/publication/native-cleanup/recovery/rollback/entrypoint matrix and no-fallback evidence; all retained reports pass | explicit Windows canary only; Current remains default; G7 closes |

C5.1 through C5.3 may add callable construction mechanisms for deterministic
and native conformance, but they may not bind them from a production Product
root. C5.3's Windows builder stays Hosting-private and remains rejected by
Product required-containment policy. C5.4 is the only slice allowed to revise
the exact Linux production-composition absence guard.
Even then, default owner selection remains Current.

## Future Evidence Manifest And Drill Ledger

The [executable evidence manifest](plugin-lifecycle-plc9c5-evidence-manifest.json)
tracks these reports. Later slices replace each named absence with a required,
uploaded JUnit report.
`scripts/dev/verify_pytest_xml.py` must observe a nonempty report with zero
skips, failures, and errors. A C5 manifest verifier added with C5.1 must also
enforce the minimum count and exact case ids below; every case is a required
row, never an optional test hidden behind a skip.

| Report id | JUnit path | Minimum tests | Exact required case ids |
| --- | --- | --- | --- |
| `PLC9C5-C5.1-CONTRACT` | `.artifacts/plc9c5-c51-contract.xml` | 65 | `C51-CURRENT-REQUIREDNESS`, `C51-INVALID-RECEIPT`, `C51-STALE-RECEIPT`, `C51-FOREIGN-RECEIPT`, `C51-POLICY-CLOSURE-CODEC`, `C51-PREACQUIRE-FRESHNESS`, `C51-PREPUBLISH-ATOMIC-CAS`, `C51-KILLSWITCH-PUBLISH-BLOCKED`, `C51-RECEIPT-ATTEMPT-CLOSURE`, `C51-EXACT-RETIRE-CAS`, `C51-KILLSWITCH-ADMISSION-BLOCKED`, `C51-RESTART-LATCH`, `C51-CLEANUP-SETTLED`, `C51-CLEANUP-DEBT`, `C51-STICKY-OWNER`, `C51-NO-FALLBACK`, `C51-REQUIRED-SUCCESS`, `C51-OPTIONAL-DEGRADED`, `C51-PUBLICATION-FENCE`, `C51-SENTINEL-REDACTION`, `C51-MONOTONIC-SETTLEMENT`, `C51-DURABLE-POLICY-BUDGET`, `C51-CAPACITY-PREWRITE`, `C51-KILLSWITCH-DURABLE-RETRY`, `C51-GATE-RELEASE-IMMEDIATE`, `C51-NOEFFECT-NORMAL`, `C51-NOEFFECT-EXCEPTION`, `C51-NOEFFECT-EXPLICIT`, `C51-EFFECT-EXCEPTION`, `C51-COMMIT-BEFORE-RETURN`, `C51-DUAL-COORDINATOR-CAS`, `C51-PUBLISH-THEN-KILL-RACE`, `C51-KILL-THEN-PUBLISH-RACE`, `C51-DYNAMIC-PORT-REENTRY`, `C51-PORT-FAULTS`, `C51-COUNTERFEIT-EVIDENCE`, `C51-REGISTERED-RECOVERY`, `C51-GATE-RELEASE-PREFAULT`, `C51-GATE-RELEASE-POSTFAULT`, `C51-CROSS-THREAD-AUTHORITY-REENTRY`, `C51-CROSS-THREAD-STORE-REENTRY`, `C51-CROSS-THREAD-EVIDENCE-REENTRY`, `C51-RELEASE-DEBT-PUBLISH`, `C51-RELEASE-DEBT-ADMISSION-VALIDATION`, `C51-RELEASE-DEBT-ADMISSION-CAS`, `C51-RELEASE-DEBT-DRAIN-JOIN`, `C51-SHARED-AUTHORITY-DOMAIN`, `C51-SHARED-STORE-DOMAIN`, `C51-SHARED-EVIDENCE-DOMAIN`, `C51-DISJOINT-OWNER-PARALLEL`, `C51-SHARED-RELEASE-DEBT-DRAIN`, `C51-CROSS-OWNER-CALLBACK-FENCE`, `C51-SHARED-DOMAIN-WRAPPERS`, `C51-DOMAIN-TOKEN-WEAKREF`, `C51-ENTER-AMBIGUITY-CLEANUP`, `C51-EXIT-CALLBACK-DRAIN-REENTRY`, `C51-RETIRE-RELEASE-PREFAULT`, `C51-RETIRE-RELEASE-POSTFAULT`, `C51-LATCH-RELEASE-PREFAULT`, `C51-LATCH-RELEASE-POSTFAULT`, `C51-HELD-GATE-NO-EARLY-RELEASE`, `C51-RESERVED-GATE-NO-DRAIN`, `C51-RELEASING-RETRY-FAILFAST`, `C51-RELEASE-FAULT-RETRY-TAKEOVER`, `C51-SHARED-EXIT-CALLBACK-RETRY-REJECT` |
| `PLC9C5-C5.2-LINUX-NATIVE` | `.artifacts/plc9c5-c52-linux-native.xml` | 14 | `C52-EXACT-CLOSURE`, `C52-CATALOG-MISMATCH`, `C52-POLICY-CLOSURE-MISMATCH`, `C52-EXEC-CLOSURE-MISMATCH`, `C52-WSL-MICROSOFT-REJECT`, `C52-UNKNOWN-CLASSIFIER-REJECT`, `C52-NON-X86-REJECT`, `C52-FD-SUBSTITUTION`, `C52-CANCEL-PRE-EFFECT`, `C52-CANCEL-POST-EFFECT`, `C52-DESCENDANT-CLEANUP`, `C52-SAMEBOOT-DEBT`, `C52-CHANGEDBOOT-ABSENCE`, `C52-SENTINEL-REDACTION` |
| `PLC9C5-C5.3-WINDOWS-MECHANICS` | `.artifacts/plc9c5-c53-windows-mechanics.xml` | 12 | `C53-REQUIRED-CONTAINMENT-REJECT`, `C53-LOCKED-IDENTITY-SUBSTITUTION`, `C53-TRUSTED-SYSTEMROOT`, `C53-AMBIENT-SYSTEMROOT-POISONING`, `C53-CALLER-ENVIRONMENT-REJECT`, `C53-DISCARDED-STDERR`, `C53-RESTRICTED-TOKEN`, `C53-JOB-TREE-CLEANUP`, `C53-HANDLE-SUBSTITUTION`, `C53-CANCEL-PRE-POST-EFFECT`, `C53-RESTART-UNCERTAINTY`, `C53-SENTINEL-REDACTION` |
| `PLC9C5-C5.4-LINUX-PRODUCT` | `.artifacts/plc9c5-c54-linux-product.xml` | 25 | `C54-PRODUCT-SELECTED`, `C54-PRODUCT-MISSING`, `C54-PRODUCT-WRONG`, `C54-PRODUCT-DISABLED`, `C54-SESSION-CANONICAL`, `C54-SESSION-CWD`, `C54-SESSION-HOME`, `C54-SESSION-TAMPERED`, `C54-SESSION-ALIAS`, `C54-SESSION-CONFLICT`, `C54-SESSION-CHANGED`, `C54-REQUIRED-SUCCESS`, `C54-REQUIRED-FAILURE`, `C54-OPTIONAL-SUCCESS`, `C54-OPTIONAL-DEGRADED`, `C54-CLOSURE-FRESHNESS`, `C54-HANDSHAKE-HEALTH-PUBLICATION`, `C54-UNSUPPORTED-WINDOWS`, `C54-UNSUPPORTED-WSL`, `C54-UNSUPPORTED-NON-X86`, `C54-UNSUPPORTED-MACOS`, `C54-ORDERED-ROLLBACK`, `C54-RECOVERY-MATRIX`, `C54-SHARED-ENTRYPOINT-RECEIPT`, `C54-SENTINEL-REDACTION` |
| `PLC9C5-C5.5B-WINDOWS-LPAC-NATIVE` | `.artifacts/plc9c5-c55b-windows-lpac-native.xml` | 24 | `C55B-PROFILE-CREATE`, `C55B-CLEANUP-REPLAY`, `C55B-FOREIGN-PROFILE-REJECT`, `C55B-PROFILE-SID`, `C55B-ZERO-CAPABILITIES`, `C55B-LPAC-OPTOUT`, `C55B-RUNTIME-RX`, `C55B-RUNTIME-WRITE-DENY`, `C55B-PRIVATE-FS-SCRATCH`, `C55B-PRIVATE-REGISTRY-SCRATCH`, `C55B-UNRELATED-FS-DENY`, `C55B-PROCESS-MUTATION-DENY`, `C55B-NETWORK-DENY`, `C55B-EXEC-CWD-IDENTITY`, `C55B-DACL-SUBSTITUTION`, `C55B-PROFILE-SUBSTITUTION`, `C55B-NO-AMBIENT-ENV`, `C55B-HANDLE-LIST`, `C55B-HANDLE-ALIAS-REJECT`, `C55B-CANCEL-PRE-POST-EFFECT`, `C55B-TOKEN-VERIFY-BEFORE-RESUME`, `C55B-JOB-TREE-CLEANUP`, `C55B-CONTAINMENT-CLEANUP-DEBT`, `C55B-SENTINEL-REDACTION` |
| `PLC9C5-C5.5C-WINDOWS-PRODUCT` | `.artifacts/plc9c5-c55c-windows-product.xml` | 28 | `C55C-PRODUCT-SELECTED`, `C55C-PRODUCT-MISSING`, `C55C-PRODUCT-WRONG`, `C55C-PRODUCT-DISABLED`, `C55C-SESSION-CANONICAL`, `C55C-SESSION-CWD`, `C55C-SESSION-HOME`, `C55C-SESSION-TAMPERED`, `C55C-SESSION-ALIAS`, `C55C-SESSION-CONFLICT`, `C55C-SESSION-CHANGED`, `C55C-REQUIRED-SUCCESS`, `C55C-REQUIRED-FAILURE`, `C55C-OPTIONAL-SUCCESS`, `C55C-OPTIONAL-DEGRADED`, `C55C-POLICY-CLOSURE-FRESHNESS`, `C55C-PROVISIONING-FRESHNESS`, `C55C-HANDSHAKE-HEALTH-PUBLICATION`, `C55C-WINDOWS-AMD64-ACCEPT`, `C55C-UNSUPPORTED-WINDOWS-NON-AMD64`, `C55C-UNSUPPORTED-WSL`, `C55C-UNSUPPORTED-MACOS`, `C55C-ORDERED-ROLLBACK`, `C55C-RECOVERY-MATRIX`, `C55C-NATIVE-CONTAINMENT-SETTLEMENT`, `C55C-SHARED-ENTRYPOINT-RECEIPT`, `C55C-NO-FALLBACK`, `C55C-SENTINEL-REDACTION` |

The rollback drill has this fixed order:

| Step | Required observation |
| --- | --- |
| `R1-LATCH-FUTURE` | atomically latch future Hosting admission closed and stale its generation |
| `R2-FENCE-ATTEMPTS` | fence every exact attempt in the complete active registry |
| `R3-REVOKE-DRAIN` | revoke and drain only each attempt's exact domain generation |
| `R4-TERMINATE-TREE` | terminate each exact owner's complete process tree |
| `R5-SETTLE-OR-DEBT` | durably record tree settlement or cleanup debt |
| `R6-SETTLE-READINESS` | settle required/optional Product readiness |
| `R7-ISSUE-CURRENT` | only now issue a new Current-owner receipt |

The recovery report records these ordered durable observations:

| Step | Required observation |
| --- | --- |
| `V1-PRIOR-ABSENT` | no prior attempt exists |
| `V2-EXACT-REAPED` | the exact prior tree has a settlement witness |
| `V3-SAMEBOOT-UNKNOWN` | same-boot uncertainty remains durable debt and blocks restart |
| `V4-CHANGEDBOOT-ABSENT` | trusted changed-boot identity proves the old local tree absent |
| `V5-BUDGET-EXHAUSTED` | restart budget exhaustion remains terminal |
| `V6-HOST-RESTART` | durable latch, receipt, generation, settlement/debt, and budget facts reconstruct the decision |

No protocol terminal phase or PID absence substitutes for tree settlement.
Every slice injects path, secret, descriptor/handle, and ambient-environment
sentinels at these exact points:

| Step | Injection point |
| --- | --- |
| `S1-POLICY-REJECTION` | policy/receipt rejection |
| `S2-NATIVE-REJECTION` | native preparation rejection |
| `S3-LAUNCH-FAILURE` | launch failure |
| `S4-PROTOCOL-FAILURE` | protocol or health failure |
| `S5-CLEANUP-DEBT` | cleanup debt serialization |
| `S6-STATUS-SERIALIZATION` | final Product/status serialization |

Reports and bounded diagnostics must contain only stable reason codes and
opaque fingerprints.

## Guard Transition And Deletion Ledger

| Transition | Guard intentionally revised | Guards retained |
| --- | --- | --- |
| PLC9C4 -> C5.0 | index this design/inventory and freeze Current source/mismatch facts | every runtime symbol, private-profile import, Product composition, default Current, no-fallback, author-SDK, unsupported-platform, and `remote_service` absence |
| C5.0 -> C5.1 | only the named receipt/policy/internal-coordinator/cleanup contracts and the three named Worker public exports | native profile imports outside Hosting, production Product composition, default Current, unsupported platforms, other domains, remote topology; all other Worker public exports remain exact |
| C5.1 -> C5.2 | create only `src/loushang/harness/worker/_native_profile_bridge.py`, add only `ProductWorkerNativeProfilePort` publicly, and admit its two exact POSIX private imports plus retained Linux report | Windows private imports, a second friend module, raw platform APIs, production Product composition, default Current, WSL/unknown classifiers, other domains, remote topology |
| C5.2 -> C5.3 | only one Hosting-private trusted-payload builder using `GetWindowsDirectoryW` plus retained Windows mechanics/rejection evidence; no Harness consumer or Windows private friend import is added | production Product composition, Windows required-containment activation, ambient/caller environment trust, default Current, unsupported platforms, other domains, remote topology |
| C5.3 -> C5.4 | only the exact Linux Coding Product canary composition and named Product report absence | default Current, explicit allowlist, no same-attempt fallback, Windows/unsupported platforms, other domains, author-SDK runtime owners, remote topology |
| C5.4 -> C5.5a | only the proposed LPAC design, exact inventory delta, and architecture guards | every runtime and activation absence remains; Windows and G7 stay closed |
| C5.5a -> C5.5b | only the accepted Hosting-private LPAC provisioner/profile, raw Win32 bindings, and required native report | no Harness consumer or Product activation; default Current and every unsupported platform remain closed |
| C5.5b -> C5.5c | only the exact same-file Windows friend imports, Coding Windows canary dispatch, and required Product report | every Product/contribution/platform not named by the acceptance remains closed; G8 cannot close earlier |

The Current Worker owner, `WorkerSessionOwnerRouter`, H6 native profiles and
their retained native oracles, Session discovery/profile validation, and the
Capability generation owner cannot be deleted during C5.1--C5.4. Their
deletion requires G9 evidence that every supported consumer has converged and
rollback no longer needs the Current path. A new implementation is not proof
that the old owner is unused.

## Per-Slice Executable Guards

With C5.4 delivered, architecture tests must prove:

- the baseline and inventory are indexed once and reproduce every G7 matrix
  dimension and required case from the parent plan;
- every Current inventory source exists and the documented source set is exact;
- only the named C5.1 receipt/coordinator contracts, C5.2 profile port, and
  exact C5.4 Coding Product root exist;
- only the C5.4 Coding root outside Worker composes the H5 owner selector, H6
  adapter, or C4 Capability adapter; Sandbox remains the sole non-Worker
  importer of the existing Worker launch capability;
- the sole `_native_profile_bridge.py` friend imports exactly the two accepted
  private POSIX profile symbols and no Windows/raw platform API; the H6.4
  private preparation edge remains confined to the existing Worker adapter;
- only the exact Coding canary imports the reviewed C5.1 coordinator and C5.2
  friend binder; no Coding or presenter module imports Hosting;
- owner selection still defaults to Current, performs no environment lookup,
  and contains one direct call with no cross-owner exception retry;
- `remote_service`, author-SDK runtime owners, AppHost coupling, unsupported
  platform fallback, and every Product activation outside the exact Linux
  Coding canary remain absent; and
- the retained deletion symbols/files for Current launch, rollback, native
  preparation, Session identity validation, and domain authority still exist.

Static syntax cannot exclude computed imports, reflection, or callable
laundering. Those routes are forbidden; focused runtime side-effect tests and
five-view review complement the executable static guard in every later slice.

## Five-View Review Packet

Review C5.0 independently through these views:

1. **Architecture and dependency:** sole writers, Product-neutral Harness,
   confined private friend edge, and AppHost independence.
2. **Product and Session:** explicit Product/Contribution selection,
   required/optional semantics, Coding-specific restore evidence, and exact
   cross-entrypoint convergence.
3. **Security and native containment:** immutable catalog/policy/execution
   closure, Linux launcher/profile and WSL-classifier admission, Windows
   trusted-mechanics-only rejection, unsupported-host fail closure, and no raw
   material escape.
4. **Lifecycle and rollback:** acquisition attachment, cancellation, cleanup
   debt, process-tree proof, serialized admission and active registry,
   exact-generation publication/retirement CAS, sticky attempts, recovery, and
   kill-switch ordering.
5. **Testing and operations:** exact Current inventory, deletion/absence guard
   strength, retained Linux/Windows reports, required-skip policy, pathless
   diagnostics, and rollback drill observability.

The review must confirm these resolved decisions before C5.1 begins:

- The existing Coding Agent Product construction boundary is the narrowest
  accepted first canary route; every non-Session early dispatch is excluded.
- The single `_native_profile_bridge.py` friend is the only platform-profile
  consumer; C5.2 admits exactly the named POSIX symbols and does not widen the
  Hosting public API.
- The Linux canary requires both a static payload and static containment
  launcher, an admitted containment-profile digest, and a non-WSL exact
  classifier result.
- H6.3 Windows restricted-token/Job mechanics are not accepted Product required
  containment. C5.3 preserves Hosting-owned trusted `SystemRoot` and discarded
  stderr, and proves Product rejection; Windows activation needs a separate
  accepted profile and transition.
- The receipt binds immutable native catalog plus the canonical expected policy
  closure; same-domain realized policy closure is compared for authorization,
  while separate full H6 execution-closure evidence, serialized authority
  witnesses, exact-generation CAS, and durable cleanup settlement/debt make
  status, publication, recovery, and rollback independently auditable.

## C5.0 Exit Gate

C5.0 is accepted only when the design and exact inventory land together, all
five review views report no unresolved high/medium risk, focused architecture
and documentation checks pass, and the diff contains no production source
under `src/loushang`. Acceptance leaves every runtime route default-dark and
does not permit Product activation.
