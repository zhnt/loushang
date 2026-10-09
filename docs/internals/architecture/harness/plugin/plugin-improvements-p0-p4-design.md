# Plugin Experience Improvements P0–P4: Candidate Design

## Status And Scope

- Design status: candidate for architecture, integrity/security, and author/user
  experience review. This document does not grant Product rollout or execution
  authority.
- Evidence base: repository source at `7a3673aa`, with the documentation
  corrections at `1e82042b`. Source and executable tests remain authoritative.
- Scope: improve the existing Coding Plugin experience in five ordered
  priorities. These P0–P4 labels belong to this experience design; they do not
  rename the historical PLC9 P0/P1 slices or replace the
  [Plugin lifecycle plan](plugin-lifecycle-coding-pluginization-plan.md).
- Initial Product scope: fresh, B-fenced Linux Coding workspaces and the
  currently admitted local, document-only Skill and Prompt Wheels. Theme,
  Windows, macOS, executable contributions, and remote sources retain their
  separate gates as described in the [support matrix](plugin-support-matrix.md).

The design advances one user path: an author prepares an artifact, the Product
admits its exact bytes, the user chooses its desired state, a new Session
selects it, and the user can explain or repair the result. Each transition
keeps its current owner. There is no second Plugin registry, generic service
bag, universal Profile runtime, or cross-owner atomic transaction.

## Current Code And Decision Boundary

| Current code | What it establishes | Gap addressed here |
| --- | --- | --- |
| [Management service](../../../../../src/loushang/harness/plugin_management/service.py) and [read model](../../../../../src/loushang/harness/plugin_management/application.py) | Durable A1 Desired State operations; Installation, revision, skew, debt, and unknown-dimension projections | A user journey and consistent explanation across its supported surfaces |
| [Coding CLI Product operations](../../../../../src/loushang/coding/cli/application.py) and [TUI commands](../../../../../src/loushang/coding/plugin_management_ui.py) | Fenced Product install/update/uninstall and bounded `/plugins` enable/disable/remove/repair routes | Public Wheel validation, chained command receipts, and stage-aware partial-failure guidance; the lifecycle path itself already works |
| [Preview](../../../../../src/loushang/harness/plugin_management/current_preview.py) and [support status](../../../../../src/loushang/coding/plugin_support_status.py) | Read-only Product projection; `partial_evidence` or `stale_evidence`; `productUse` remains `not_checked` | Exact evidence wording and optional Session-owned use proof |
| [Author CLI](../../../../../src/loushang/plugin/__main__.py) and [offline smoke](../../../../../src/loushang/coding/plugin_author_smoke.py) | Init, data Wheel build, package-directory validation, and disposable Product use proof | Validate the built Wheel publicly and carry its exact identity into a target workspace without confusing smoke with target admission |
| [Composition sets](../../../../../src/loushang/coding/composition_sets.py) and [Coding bootstrap](../../../../../src/loushang/coding/bootstrap.py) | Three Product-owned inert sets and Session assembly; CLI can preview a chosen set | Product-controlled, visible selection for a *new* ordinary Session |
| [Worker candidate inventory](plugin-lifecycle-plc9c-third-party-admission.md) | Explicit native candidate and opt-in paths, with general admission still closed | Narrow public Worker journey after its independent safety and lifecycle gates |

The prior [management and external Skill vertical](plc9-default-management-resource-vertical-design.md)
already delivered its P0/P1 slices. The [Skill](../../../../../examples/plugins/coding_data_skill/README.md)
and [Prompt](../../../../../examples/plugins/coding_data_prompt/README.md) examples
already cover build, install, enable, use, update, disable, and remove; real
CLI/Product/Session regressions also exist. This design consumes that baseline
and closes the remaining public author handoff and explanation gaps. It does
not reopen the A1/A2 transaction model.

## Shared Contracts For Every Priority

1. **Exact owners.** Package lifecycle acquires, verifies, publishes, and
   retires artifact bytes. Plugin management owns Desired State and its
   operation journal. Product policy selects and admits an immutable revision.
   Resource, Capability, Tool, and Extension owners publish their own
   generations. Session owns consumption evidence. A presentation adapter may
   correlate these facts but cannot repair or replace any of them.
2. **Evidence levels.** `built`, `installed`, `enabled`, `admitted`, `selected`,
   and `used by Session` are separate claims. Every user-facing row identifies
   its evidence level and exact Plugin/Installation/revision when available.
   Missing, stale, or contradictory owner evidence remains unknown, partial,
   stale, or blocked; no display infers success from an empty list.
3. **Read paths stay read-only.** Listing, preview, discovery, status, and
   explanation perform bounded reads. They do not recover operations, publish
   generations, invoke author Python, start Workers, create a Product, or change
   settings. Repairs and mutating commands are separate explicit actions.
4. **No implied cross-owner rollback.** A2 package install/update, A1 Desired
   State mutation, Session binding, retirement, and physical GC have distinct
   commit points and operation IDs. A failed later step reports the earlier
   committed result and the permitted next action. Disable and remove affect
   future selection; they are not physical deletion or emergency revocation.
5. **Exact scope and authorization.** The Product/workspace owner, actor,
   policy revision, selected artifact digest, and optimistic revisions are
   checked at the operation that decides. A UI or CLI preview grants no
   authority. Existing Approval, Sandbox, Process Host, and source-admission
   paths remain in force. Native trusted Extensions do not inherit Wheel
   admission, and data Wheels do not inherit executable authority.
6. **Platform truth.** A passing Linux flow does not open Windows, macOS,
   Hosted Mux, or a global default route. A delivery claims only the Product,
   entry route, platform, and actual consumer exercised by its evidence.

## P0 — Complete The Target-Workspace Data Plugin Journey

### User result and implementation path

For a fresh B-fenced Linux Coding workspace, extend the existing Skill and
Prompt examples into one executable command sequence using the public builder
and Product CLI operations:

```text
init/build -> inert Wheel validation -> disposable smoke
-> --install-package + --package-scope project
-> --list-plugins --list-plugins-format json
-> --enable-plugin -> new Coding Session -> Skill/Prompt invocation
-> --update-package or --disable-plugin -> new Session check
-> --uninstall-package -> retirement/GC status
```

The current `loushang-plugin validate` accepts a package **directory** with
`plugin.json`; neither the scaffold source directory nor the built Wheel is
that input. P0 adds a public `loushang-plugin validate-coding-wheel <wheel>`
command for the currently admitted Skill/Prompt data profiles. It checks the
bounded Wheel bytes and declaration without importing or executing contents;
it reports artifact identity and `productAdmission=not_checked`. The build's
own validation may be shared internally, but no manual extraction or test-only
staging step is part of the public sequence.

The Product installs the exact captured Wheel under its existing source and
Package owner. `--enable-plugin` is a distinct A1 command; installation alone
does not silently enable the Plugin. Existing operation and handoff receipts
remain the recovery authority. Add additive, machine-readable stage/operation
identifiers and safe next-command hints to the public author/target output;
the existing CLI `record` and list fields keep their meanings. The examples
show the exact status/explain query after settlement or refusal. Any shared
journey helper is presentation-only: it may invoke existing typed Product
operations in order, but cannot write owner journals directly or claim the
sequence is atomic. A direct TUI install/update gesture, if later offered,
uses the same Product command port and reports the same per-stage settlement.

The initial journey uses the currently supported one-document Skill/Prompt
envelope. Generic SDK-valid packages, native Extension files, Theme candidate
Wheels, managed actions, dependencies, and Workers keep their own admission
rules. A `smoke` pass proves the disposable workspace only. Target workspace
install and a real new Session prove separate facts.

### Failure and acceptance

- Failed install before the Desired State CAS leaves no enabled selection; A2
  operation and cleanup debt remain inspectable. An update refused before CAS
  retains the prior selection. After `desired_committed`, retention settlement
  can still fail: the new Desired State revision may already be selected while
  the handoff is incomplete. A settled update may separately carry retirement
  debt. Output reports the exact committed revision, incomplete stage, and
  repairable owner operation in each case, without recommending a blind retry.
- Disable changes new-Session selection while a live Session retains its
  legitimate pinned snapshot until retirement; an emergency revoke follows
  its separate owner path. Uninstall records Desired State `absent`; physical
  Package GC is separately reported.
- One chained acceptance run starts from a fresh B workspace and the printed
  public author commands, then uses public CLI lifecycle entrypoints and the
  public Coding Session API. A transport-only offline model substitute is
  permitted for deterministic persisted prepared Model Input; it has no
  Product, Package, Resource, or Plugin selection authority. The run covers
  one Skill and one Prompt, update, disable, remove, and reopen at each state
  transition. Existing internal tests remain baseline evidence, not a
  substitute for this public sequence.
- A separate adversarial run covers changed Wheel bytes, executable members,
  pre-CAS refusal, post-CAS incomplete handoff, failed retirement, and a live
  pinned Session. It uses public explanation/repair commands to verify stage
  and actor-correct guidance. Pre-B inputs refuse without mutation. Keep
  offline and non-live selectors. Persisted input text and Catalog selection
  are separate facts; without an exact Session revision receipt, do not claim
  exact-revision `productUse`.

P0 ends when the new Wheel validation and stage-aware command handoff work in
the maintained examples and the chained acceptance run at the declared Linux
Product boundary, without hidden Product binding or source injection.
It does not wait for general Worker or Windows rollout.

## P1 — One Honest Status And Explanation Experience

### Read model

Project a shared **presentation** over the existing A1 management query,
Product current-composition preview, A2 operation explanation, and optional
Session-owned consumption evidence. The presentation identifies each input's
owner revision, correlation/scope, observation time, and evidence gaps. It may
render differently in CLI, TUI, and RPC/SDK, but the stage names and reason
codes have one Product-owned mapping. Keep old CLI TSV and JSON fields stable;
any new machine-consumed projection gets an explicit version and additive
fields rather than changing the meaning of `enabled` or `source`.

The current preview exposes Plugin ID and admission fingerprint, while the
Catalog summary exposes kind/name/source; the current support-status join is
by Plugin ID and Desired State revision. These fields are insufficient for an
exact artifact or contribution join. Before P1 promotes a row beyond
`partial_evidence`, add narrow owner read ports/receipt fields for the full
Installation key, immutable selected Package revision and source/digest,
contribution identity, Catalog generation and selection receipt, plus
independently observed Product policy and settings revisions. Join only
matching scope, identity, and generations. A missing field, mismatched owner
revision, or policy/settings-only drift is `unknown` or `stale`, never proof
of a different revision's selection or use. The ports expose owner facts;
the presentation does not become a new authoritative registry.

The existing `support_status()` joins management and preview with before/after
Desired State reads. This guard alone does not cover policy or settings drift;
P1 checks those owner revisions too. A2 `explain_operation()` remains keyed by
its own operation ID and never becomes an A1 journal entry. Pending-operation
guidance carries A1 versus A2 kind, originating actor, exact ID, and a repair
command available to that actor. A different surface may explain the pending
operation but must not offer its own actor's repair as if interchangeable.
An A1-only successful enable is not a failed A2 package transaction merely
because no A2 operation exists. A view may say `selected` only from a
Product/Resource owner selection receipt. It may say `used` only from an exact
Session owner receipt or persisted prepared-input evidence bound to the
selected revision, contribution, Session ID, and consumer generation. The
read path never scans arbitrary transcript text or executes a Session to
manufacture proof. If such a Session read port is absent or cannot establish
identity, `productUse` remains `not_checked`.

The default human presentation answers: what is installed, what the user
requested, what a new Session is projected to select, what a named Session
actually used when proven, what is blocked or stale, and which exact operation
can be repaired. Unknown owner dimensions and cleanup debt are visible rather
than omitted. This is a projection over exact owners, not a second management
database.

### Acceptance

- CLI list/status/explain, `/plugins list|status|explain`, and optional Coding
  RPC/local SDK render the same synthetic owner snapshots with consistent
  stage/reason semantics; generic Harness Hosts still omit Coding-only routes.
- Real Product cases cover concurrent Desired State change, policy/settings
  drift with unchanged Desired State, missing owner, A1/A2 identity mismatch,
  pre-CAS refusal, post-CAS incomplete settlement, retirement debt, and an
  unchanged old Session while a new Session uses an updated revision. Include
  same Plugin ID with different Package revisions and same-name native and
  external Resources with identical content; content equality alone cannot
  attribute use. A pending CLI operation viewed from TUI/SDK retains its CLI
  actor and usable CLI repair route.
- Read-only calls preserve all journal bytes, settings, Source bytes, and
  Session state. Scope mismatch and malformed owner evidence fail closed with
  path-free diagnostics.

## P2 — Short Author Path And Local Discovery

### Author journey

Keep the existing `loushang.plugin` compiler and Coding Skill/Prompt scaffold,
builder, package-directory validator, and smoke commands. Reuse P0's new
`validate-coding-wheel` entry for the Wheel path. Make their output one
coherent author journey: source location, artifact digest, Product
compatibility profile, validation result, disposable-smoke result, and an
exact target-workspace installation command. Validation never labels the
target Product as admitted; the smoke report retains its disposable-workspace
label. The Product rechecks the captured Wheel at installation. An optional
read-only target preflight may explain compatibility, but it cannot reserve an
installation or promise that a later mutable workspace will accept it.

Extend the maintained Skill and Prompt examples with public command output
and failure diagnosis. Keep native `SKILL.md` and Prompt files the shortest
route when independent Plugin
lifecycle is unnecessary. Theme and Worker examples continue to label their
candidate gates.

### Local discovery

Add a bounded read-only local directory view over Product-declared package
sources, installed Plugin revisions, and the existing native Resource Catalog.
Use exact source authority and immutable artifact identity for package rows;
native loose files remain Resource rows without invented Plugin IDs. Show
contribution kind, owner, version where a Plugin exists, source scope, Product
compatibility, and current installation/selection evidence. Search and filters
operate on inert metadata; discovery does not recursively scan unrelated
workspace paths, import Extension Python, fetch remote URLs, or auto-install.
Duplicate names and conflicting scopes use the existing Product/Catalog
diagnostics rather than an arbitrary display-order winner.

The initial public route is `loushang --discover-local-plugins` with a
versioned JSON form selected by `--discover-local-plugins-format json`; it is
a new read-only CLI route, not an internal-only helper. Rows distinguish
installed Plugin and loose Resource identities. The response reports source
completeness and truncation explicitly. An unavailable Product source or
malformed native entry yields a partial result with diagnostics when other
sources can be read; an untrustworthy scope/authority boundary blocks the
listing. Neither case silently returns a complete empty inventory.

### Acceptance

- A clean checkout can scaffold, build to two separate output directories
  with identical bytes, validate the Wheel through P0's public command, run
  an offline disposable smoke, and install the exact artifact in a fresh
  B-fenced Linux workspace using the printed instructions. The target Product
  and Session supply the final admission/use evidence.
- The public local-discovery command lists installed packages and loose native
  Resources with distinct identities. It handles same-name native and
  installed Skills, disabled rows, removed sources, stale bytes, malformed
  metadata, source unavailability, and bounded truncation without writes or
  author-code execution; JSON consumers can distinguish complete, partial,
  and blocked results.
- No public author SDK gains management, Approval, Process Host, or registry
  authority. A remote marketplace remains a separate source-admission design.

## P3 — Make Existing Coding Composition Sets Selectable And Explainable

The three Product-owned sets stay canonical: `coding-minimal`,
`coding-standard`, and `coding-architecture`. The current CLI
`--preview-composition-set` only changes a read-only preview; it is never
presented as a runtime selection. The public Coding Session creation API
already accepts `composition_set`; P3 exposes that existing Product choice
through an ordinary CLI `--composition-set` option for **new** Sessions. An
explicit CLI choice takes precedence over the CLI's current inference of
`coding-architecture` when a `coding.arch` setting key exists. With no explicit
choice, that inference remains; otherwise the default is `coding-standard`.
The set is resolved to its canonical immutable plan, then current settings,
Desired State, Capability owner admission, and Resource Catalog selection
apply. An explicit set does not grant a disabled or unconfigured Provider and
cannot accept an arbitrary list of Plugin IDs or alter a running Session.

Preview and start use this same precedence rule. Preview displays the set's
requested contributions separately from the exact currently projected
Product outcome, including disabled or unavailable Providers, external data
Resources selected independently of the set, and
unknown authorized preflight. The start operation rechecks scope, settings,
Desired State, and Product policy; a changed preview is recomputed or refused
before committing Session input. Add a durable Session-owned startup
provenance record for the selected set ID, plan fingerprint, and effective
owner generation/revision evidence; resume and diagnostics cannot silently
switch sets. Existing `coding.arch` mount policy and delegated read-only invocation
profiles retain their current authority; this feature must not widen them.

Acceptance uses real minimal, standard, and architecture Sessions with
enabled and disabled Base/LSP/Arch states, exact new-Session Resource Catalog
and Tool evidence, preview/start drift, resume, and a pinned old Session after
selection changes. It includes explicit `coding-minimal` with a present
`coding.arch` settings key, plus omitted-choice inference. It verifies that
preview alone writes nothing and never claims a Capability or Resource was
consumed. TUI selection should reuse the
same Product request after the CLI/Session contract passes. This is a narrow
Coding choice, not a general user-authored Profile or Bundle system.

## P4 — Open One Third-Party Worker Path After Its Own Gates

Start from the [PLC9C third-party admission candidate](plugin-lifecycle-plc9c-third-party-admission.md)
and the current explicit native release/opt-in path. The first public contract
is one document-declared `capability_provider`, one versioned owner protocol,
and one read-only, effect-free query on an explicitly supported Linux x86-64
native profile. It uses the existing immutable Wheel, Package transaction,
Product Source catalog, exact Capability owner admission, H6 containment,
Worker supervisor, Approval, Session lease, and C5 retirement/cleanup owners.
An author-facing template and smoke must distinguish inert artifact checks,
native release checks, selected candidate, and an actual Product Session
query. The existing explicit SDK candidate query is baseline evidence; P4
requires an independently gated ordinary Coding-turn entry for the selected
query before claiming general user availability. Dependency-bearing candidates
remain refused for execution until their selected runtime environment and
complete closure have Product proof.

The Linux ordinary-query candidate selects
`posix-static-query-contained-elf-v1`, separate from the earlier general H6
static containment profile. The checked-in launcher closes all inherited
descriptors on payload exec, admits the exact sealed payload memfd, denies
pathname execution with Landlock, and uses a seccomp allowlist for framed
stdin/stdout/stderr and static runtime computation. File, process, network,
and new executable authority are denied. Missing Landlock or descriptor
closure support refuses the launch. The query profile also bounds address
space and CPU time; the Product still binds its source digest and compiled
launcher digest into the exact native release decision. These controls and
their adversarial tests are required evidence, not proof that the entire P4
lifecycle has closed.

The Product first admits the exact artifact and native release, then records
an explicit per-install trust/opt-in decision. A fresh Session resolves the
same identity, policy revision, containment proof, and bounded admission;
the Host launches only after the current owner rechecks them. IPC cannot
convey ambient Host authority, reusable Approval tokens, or direct registry
access. Disable, revoke, update, crash, and partial cleanup retain distinct
effects and receipts; a pinned Session and new Session may select different
revisions under the existing lifecycle rules. Missing native closure,
expired admission, altered bytes, stale generation, orphaned process, or
unsettled GC/cleanup debt fail closed with a repairable owner diagnostic.

For a Linux ordinary turn whose Product process dies after Tool use, offline
recovery first proves the native group absent, repairs only its orphan runtime
lease, settles its exact Supervisor record, and removes its recorded payload
debt. A separate C5 step holds runtime quiescence and the GC writer guard while
it revalidates the completed repair intent and historical receipt, retires the
activation attempt, and records cleanup settlement. Package GC remains closed
until that C5 settlement is durable.

P4 public activation waits for a focused security and platform review, real
Product journey, native containment and crash/reopen evidence, bounded durable
Worker history retention, and explicit owner approval for the exact route.
The linked PLC9C contract's anti-reuse, checkpoint, process-tree retirement,
and cleanup requirements remain prerequisites; this summary does not relax
them.
Windows requires its own complete native candidate and private-data/GC gates;
ordinary unflagged Windows and default Worker routing remain closed until
those decisions. Effectful Tools, arbitrary Python/native imports, broader
dependency execution, browser UI, and `remote_service` require separate
contracts. Successful inert build or candidate smoke alone never opens P4.

## Sequence, Evidence, And Stop Points

| Stage | Dependency | Delivery evidence | Stop point |
| --- | --- | --- | --- |
| P0 target workspace | Existing A1/A2 and data Wheel Product path | Public Wheel validation, chained author/CLI/Session journey, stage-aware receipts, interruption and pinned-Session negatives | Keep installed/selected/used claims separate; do not claim atomic rollback |
| P1 status | P0 operation identifiers and new exact owner receipt/read fields | Cross-surface semantic parity, actor-correct repair, read-only identity/drift negatives, optional exact Session use proof | Without exact owner/Session receipts, remain partial or `not_checked` |
| P2 author and local discovery | P0 Wheel validation and target command path; P1 evidence vocabulary | Reproducible author-to-target flow and public write-free local inventory | No remote fetch, implicit install, or executable admission |
| P3 composition choice | P1 status and current canonical Coding sets | New-Session selection and resume tests for all three sets | Preview is not runtime selection; no arbitrary user profile |
| P4 Worker | PLC9C general admission, native release, history/GC and platform gates | Explicit end-to-end contained query, revocation, crash/reopen, cleanup and update evidence | No general/default routing from candidate evidence |

P2 and P3 can be implemented independently after P0/P1. Each implementation
slice follows the workspace high-risk-change workflow: a tracking issue,
isolated branch/worktree, focused baseline, regression-first changes, and
exact-platform evidence. Design review may reorder the slices if a concrete
owner dependency or Product gate requires it; the support matrix changes only
after the corresponding Product evidence and decision.

## Three-Perspective Design Review

Three independent GPT-6-astra reviews examined this candidate against the
repository source: architecture/ownership, lifecycle integrity/security, and
author/user experience. The architecture review found no P0/P1 owner-boundary
blocker and requested explicit P3 precedence. The integrity review required
post-CAS incomplete-handoff handling and exact identity/read-port contracts.
The experience review required a public Wheel validation path, a reproducible
offline target run, actor-aware repair, and a discoverable local-inventory
route. These findings are incorporated above. This review closes design
contradictions; it is not Product rollout approval or implementation evidence.
