# App Service Port Rename Plan

## Status

- Authority: descriptive — naming and compatibility delivery plan
- Design status: accepted — bounded canonical-name and compatibility scope
- Implementation status: implemented — in `refactor/appservice-port-names`; not merged to main
- Owner: AppServer contract owner with AppService, AppHost, Coding and Harnesstui consumers
- Revision: R2, reassessed on 2026-11-09; replaces the scope-only R2 proposal
- Review disposition: R1's original ambiguity diagnosis is valid; its selected
  names and migration need changes. The scope-only R2 did not solve the main
  problem and is withdrawn as the recommended direction.
- Baseline: `cfbe1286ff5a7ef7ae90055ca7445ce496a89d76`, the local `origin/main`
  reference used to create the dedicated task worktree; not a claim of current upstream freshness.
- Method consulted: local committed architecture method `master`,
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no method text is vendored.
- Evidence status: prototype history is retained below; the actual implementation
  and final verification are recorded in Implementation Delivery. No additional
  independent R2 reviewer is claimed.
- Follow-up review: user supplied another agent's review. Its source-reading
  benefit, role distinction, split analysis, coverage and budget concerns are
  addressed below; the gate-routing conclusion is based on current source rules.

## Reassessment Of The Other Agent's Proposal

The original diagnosis is sound: `AppServerConnectionV1` stores `_client` and
`dispatch_request` calls `client.create_mux(...)`, although the injected object
handles service operations. This makes the serving path look like a reverse
call to a remote client. The same callable contract is also implemented by an
in-process facade and a remote proxy. Its name should express the shared
semantic surface, while local variables express their role in the call path.

The earlier review gave too much weight to an inferred consumer-naming
convention. Source examples show that convention is defensible, not that it is
a binding rule or that the current serving path is easy to read. Correctness
of an existing interpretation does not settle readability.

| R1 item | Reassessed disposition |
| --- | --- |
| Neutralize the shared contract name | Accept the direction; restore it to delivery scope |
| `AppContractV1` | Avoid: App Contract also denotes values, errors and negotiation; the 17-method surface is narrower |
| `AppOperationsV1` vs `AppOperationV1` | Similar names are not a literal collision; this is a readability tradeoff, not a prohibition |
| Reject every `Port` name because Product ports use it | Reject that veto: required Product ports and provided service ports can both be ports, with their direction made explicit |
| `AppClientScopeV1` to `ScopedPeerV1` | Reject: adds an undefined actor term and loses the App domain without fixing the shared-contract ambiguity |
| Scope must be connection-bound | Reject: application factory and delivery lifetime are the real invariants |
| `__name__` / `vars()` / budget tests prevent a rename | Treat as compatibility and implementation constraints; preserve them with canonical aliases |
| Plain assignment, fixed module paths, unchanged wire | Retain |

The five sibling contracts have the same client/server ambiguity. R2 includes
their canonical names, rather than describing them as defects and leaving the
same-level contract family inconsistent. It does not ban `Client` from genuine
caller facades, proxies, public capability getters or client-scoped authority.

## Canonical Names And Boundary

| Existing public name | New canonical name | Role |
| --- | --- | --- |
| `AppClientV1` | `AppServicePortV1` | Shared 17-method service-operation port |
| `SessionDiscoveryClientV1` | `SessionDiscoveryPortV1` | Optional session-discovery port |
| `ExecutionClientV1` | `ExecutionPortV1` | Optional execution port |
| `ResumeInputLookupClientV1` | `ResumeInputLookupPortV1` | Optional Resume input lookup port |
| `ManagedMuxCreationClientV1` | `ManagedMuxCreationPortV1` | Optional managed-Mux creation port |
| `ManagedMuxCloseClientV1` | `ManagedMuxClosePortV1` | Optional close and result-read port |
| `AppClientScopeV1` | `ScopedAppServicePortV1` | Application-created implementation with scoped controller/delivery authority |

These exact canonical names were absent from the frozen source and tests.
`AppServicePortV1` describes what can be called, not which side of a process
boundary implements it. The existing AppServer package continues to own the
contract declaration. AppService keeps semantic implementation ownership;
the new spelling does not move that contract to a different package or change
the import graph.

The shared contract and its scoped implementation are different kinds of
objects. `AppServicePortV1` is a structural Protocol, with no controller table
or lifecycle state. `ScopedAppServicePortV1` names an existing concrete
server-side authority facade implementing that Protocol and exposing optional
capabilities. It is not a second, scoped Protocol, a subclass of the shared
contract or a protocol version. Sharing a name root communicates implementation
of the service port; it does not by itself explain the facade's ownership.
This residual naming tradeoff is accepted for the first delivery, and Current
documentation must state these kinds and ownership separately. The rename
does not claim to solve cohesion or make all roles self-evident from names.

`RemoteAppClientV1`, `StdioAppClientV1`, `LocalAppClientConnectionV1` and
`InProcessAppClientV1` retain their names: they are caller-facing adapters or
connections. Concrete optional client/view implementations also remain where
they are; implementing a neutral port does not make every object the same role.

`ScopedAppServiceV1` remains the application-level accepted-work owner.
`ScopedAppServicePortV1` retains the original scope object's controller
membership, attachment-generation checks, Resume-subject identity and delivery
fence. Its six capability properties retain their current eager/lazy/self
exposure behavior. No controller table, operation owner or interaction
settlement is split or duplicated.

The legacy G11 adapter and wire path share the port contract, not one dispatch
implementation. Authentication belongs to the selected outer connection edge;
opening a scope does not authenticate a caller or require a connection.

## Split-Or-Keep Decision

**Keep the concrete scope facade in this delivery; do not split it merely
because it exposes several capabilities.** The ownership inventory is:

| Existing owner | Retained responsibility |
| --- | --- |
| `ScopedAppServiceV1` | Application-wide scope/controller registry and `_opening` / `_creating` admission counters |
| `_OwnedAppOperations` | Accepted-work admission and settlement lifetime |
| `_ScopeInteractions` | Interaction-response and revocation settlement |
| Existing concrete scope | Per-scope controller membership/index, authority rechecks, delivery fence and capability access |
| Existing execution registry and optional adapters | Execution records and execution/Method/Goal-specific behavior |

The scope does not itself own all admission counters and interaction settlement.
The six properties are not five lazy owners: discovery is eager, managed views
return self conditionally, and three execution-related objects are cached
lazily. Extracting each property into a new owner would duplicate or scatter
the common original-scope, attachment-generation and close-fence checks without
an evidenced independent lifecycle.

This is a present keep decision, not a claim that the facade can never be
split. Reopen it if a concrete change demonstrates independently evolving
state, repeated authority/settlement logic or conflicting lifecycle needs.
Such a proposal must map ownership and failure paths and preserve original
scope identity. It would be a separate responsibility change with its own
evidence, and is explicitly outside this rename's scope.

## Serving-Path Names And Public Compatibility

The serving-path migration includes all of the following:

- `AppServerConnectionV1._client` becomes `_service_port`.
- `dispatch_request` operates on a local `service_port` binding.
- Foreground AppHost composition names its injected operation target
  `service_port`, including the scoped and legacy facade branches.
- Genuine remote-client state and UI caller variables can remain `client`.

Existing public parameter spellings are preserved. In particular, the public
constructor and dispatcher continue to accept `client=`, and existing `.client`
getters and `open_client_scope()` factories retain their names. Their type
annotations use canonical port names. The serving implementation immediately
maps the legacy parameter to its clear internal role:

```python
def __init__(self, client: AppServicePortV1, stream: AppMessageStreamV1):
    self._service_port = client  # public keyword retained for compatibility

async def dispatch_request(client: AppServicePortV1, request: AppRequestV1):
    service_port = client
    # typed operation dispatch calls service_port.create_mux(...), etc.
```

These snippets illustrate binding only. No new `service_port=` constructor
keyword is promised. Removing or replacing public keywords is a separate API
decision. Completion means the active serving path has clear roles, not that
every historical `client` token has disappeared.

`service_port = client` is only a source-reading binding. It introduces no
new authority boundary, validation, owner or runtime behavior. The first
parameter exposed by `inspect.signature(dispatch_request)` remains `client`.
Its benefit must not be counted as a runtime or public-signature improvement.

## Alias Direction And Reflection Compatibility

This delivery renames the canonical import/annotation vocabulary and serving
bindings. It deliberately retains the legacy class declarations as compatibility
anchors rather than physically renaming the Python class objects:

```python
class AppClientV1(Protocol):
    ...  # existing 17 methods, unchanged

AppServicePortV1 = AppClientV1
SessionDiscoveryPortV1 = SessionDiscoveryClientV1

# In appservice/client_scope.py, after the existing concrete class:
ScopedAppServicePortV1 = AppClientScopeV1
```

Use the same `NewPort = ExistingType` assignment for each optional Protocol.
There is one class object per contract, not a subclass, wrapper, duplicate
Protocol or runtime forwarding layer. New canonical names join existing
explicit `__all__` lists; modules without `__all__` already export their
non-private aliases normally.

Consequences to verify:

- Old imports and new canonical imports resolve to the identical type.
- Existing `__name__`, `__qualname__` and `__module__` remain unchanged.
  `AppClientV1.__name__ == "AppClientV1"` stays true without changing its test.
- `vars(AppServicePortV1)` has the same own 17 methods as `vars(AppClientV1)`;
  optional contracts preserve their own members and remain separate capabilities.
- The three exact-type scope checks still compare the original concrete type.
  Old-name monkeypatches reach the same object.
- `HostedResumeSubjectScope` keeps its name, import path and identity; only
  its RHS uses `ScopedAppServicePortV1`. Its re-export and consumers need no
  separate alias-chain rename.
- Existing public exception text remains unchanged, including the UI error
  that mentions legacy `AppClientV1`; document this as compatibility text,
  not as an unexplained leftover in the migration.

The runtime definition can therefore still display a legacy name during
reflection. That is an explicit compatibility limit of this first delivery,
not evidence that the canonical consumer migration was omitted. Physical class
renaming or old-name removal requires a later, explicit metadata/API decision.
The old names are silent aliases with no warning or automatic removal deadline.

**First-delivery benefit is confined to source vocabulary and call-path
readability.** Logging, serialization or error rendering based on `__name__`
continues to show legacy names. No improvement in runtime observation,
performance, isolation or lifecycle behavior is claimed. Moving those
observations to a new spelling requires a later metadata/API decision.

## Inventory And Existing Budgets

The frozen Product source contains **151 exact-token references across 27
distinct Python files**, including declarations, exports and text:

| Existing token | References | Files |
| --- | ---: | ---: |
| AppClientV1 | 32 | 16 |
| AppClientScopeV1 | 34 | 8 |
| SessionDiscoveryClientV1 | 26 | 13 |
| ExecutionClientV1 | 28 | 13 |
| ResumeInputLookupClientV1 | 5 | 3 |
| ManagedMuxCreationClientV1 | 13 | 7 |
| ManagedMuxCloseClientV1 | 13 | 7 |

Use token boundaries, not substring replacement: `OwnedLocalClientScopeV1`,
`RemoteExecutionClientV1` and similar distinct names are outside that map.
Recount at delivery time rather than carrying these numbers across a rebase.

The verified prototype intentionally retains 18 old-token references: legacy
declarations, assignment RHSs and old explicit export names in six declaration
modules, plus the one public UI error string in `harnesstui/mux/controller.py`.
Other Product consumers use the new canonical names. Test imports and frozen
historical documents may retain old names to prove compatibility or preserve
their original context.

| Existing group | Baseline / limit | Tested multi-line-export prototype | Preferred single-line-export layout |
| --- | --- | --- | --- |
| appserver protocol/client | 2,274 / 2,284 | 2,284 / 2,284 | 2,277 / 2,284; 7 lines spare |
| appservice-core | 1,966 / 1,966 | 1,966 / 1,966 | 1,966 / 1,966 |
| appserver managed-close values | 78 / 80 | 80 / 80 | 80 / 80 |

For the first implementation, preserve the existing single-line export-list
style in `appserver/client.py`. The new assignments are self-explanatory; keep
their rationale in the Current naming table rather than adding a redundant
module comment. This layout adds three lines to that file:

```python
AppServicePortV1 = AppClientV1
SessionDiscoveryPortV1 = SessionDiscoveryClientV1

__all__ = ["AppClientV1", "AppConnectionClosedError", "SessionDiscoveryClientV1", "AppServicePortV1", "SessionDiscoveryPortV1"]
```

The export line is **127 characters** in the measured spelling/order, not
131. This is an explicit local formatting choice; no lint/format rule is
disabled and no runtime statements are packed. Its complete module AST is
identical to the tested multi-line-export version, and Ruff passed for it.
The 1,257-case run below belongs to that original version; it was not repeated
for this formatting/comment-only layout. Removing the redundant comment is
part of the +3 calculation: collapsing the list alone would leave +4 lines.

All other existing G11/G16 budget checks also passed. No line limit is raised,
no owner is moved to escape a limit, and no runtime implementation is compressed.
Do not add a package-level export to the full appservice-core facade. With the
preferred layout, appservice-core and managed-close remain exactly full, while
the appserver group has seven lines of spare capacity. Remeasure all groups
after any formatting/import change; do not rely on this local style remaining
unchanged automatically. Do not promise zero source growth: compatibility names require explicit
small additions, and this task earns no source-reduction credit.

## Implementation Sequence

Continue the named task in its dedicated task branch/worktree, following the
current repository workflow. The control lane's five uncommitted prior changes
and original plan remain untouched. Its AppServer runtime documentation
correction is independent; reconcile its scope docstring factually during any
later integration rather than overwriting the work.

1. **Introduce canonical aliases and export them.** Add the seven assignments
   in the six existing declaration modules. Preserve class definitions,
   method members, diagnostic metadata and old exports. Verify alias identity,
   old contract assertions, imports and all affected budgets.
2. **Migrate consumers and serving roles together.** Update the 27-file
   inventory's imports, annotations and exact-type operands while retaining
   the declared compatibility sites. Change `_service_port` and the serving
   local bindings. Preserve public `client=` keywords/getters, factory names,
   capability property names and the Coding public alias. Do not migrate only
   the base contract and silently abandon its sibling contract inventory.
3. **Reconcile Current documentation and record delivery.** Add the canonical
   name/legacy alias/role table to [AppServer Current](../appserver/README.md),
   update the class reference in [AppService Current](../appservice/README.md),
   and correct live docstrings that confuse serving objects with remote peers
   or claim a shared dispatch. Update other live summaries only where they
   actually name the changed contract. Frozen accepted records, earlier drafts
   and historical plans retain their terminology under the
   [architecture history rule](../README.md).

There is no module rename, package move, new runtime capability, scope split,
wire/schema/version change, Rust change or changed default route. Preserve
all 17 base methods and every optional method/property shape. AppServer's
Product-port bundle remains a distinct required-port direction; its name and
ownership do not change. No new ARD is implied solely by the spelling change;
any actual ownership/authority change would fall outside this plan.

Do not add or broaden a workflow, job, trigger, matrix, test route, make target,
budget exception or merge condition. Existing tests remain collected through
their existing routes. Local external probes are review evidence, not a new
permanent PR gate. Existing test assertions are not removed or weakened.
Rollback reverses consumer migration before alias introduction; no new-name
import may be left without its declaration. No workspace/data migration or
state reset is involved.

## Reassessment Evidence And Verification

The old scope-only prototype's **167 passing tests** established only that
earlier narrow mechanism's feasibility. It did not show that its rename
addressed the main problem, and is not counted as proof of this expanded plan.

The expanded temporary prototype on the frozen baseline established:

- 27 source files and the 151-reference inventory migrated; normalized class
  ASTs matched after accounting for type/local/private-name substitution.
- **1,257 passed, 10 skipped in 96.73s**, comprising 1,253 existing test cases
  and four external compatibility probe cases. Original tests were not edited.
- Existing coverage included all appserver/appservice tests, AppHost
  foreground/application/continuity, Coding execution and Resume confirmation,
  boundary traces, Hosted Mux profile/capability tests and G11/G14/G16
  architecture checks. Native Windows cases skipped here are not claimed as
  executed Windows evidence.
- External probes verified all seven old/new type identities, legacy metadata,
  base/optional Protocol members, old `client=` constructor use with the new
  private serving binding, Coding/factory identity and scope monkeypatching.
- Ruff passed after canonical import ordering; mypy passed on all 27 source
  files with `--follow-imports=silent`. No configuration was changed.
- Budget results are recorded above. All 27 prototype source files were then
  restored byte-for-byte after checking their candidate fingerprints. The
  retained Product changes are this plan and its draft index only.

This was a contract-related subset, not a repository-wide regression. It did
not run the full Harness, Agent, AI, TUI, Ontology, Foundation, Hosting or GUI
suites, nor the full AppHost, Coding, Harnesstui or architecture suites. The
full-repository test denominator was not collected, so no whole-repository
coverage percentage is claimed. Existing tests may import other packages;
that does not count as running those packages' full suites. There was no
complete native/isolated-wheel G16/G17 three-platform acceptance run.

## G16/G17 Native Evidence And Existing CI Routing

The [G16 native/wheel manifest](../appserver/detachable-local-workspace-g16-evidence-manifest.json)
and [G17 wheel manifest](../apphost/hosted-session-workflow-g17-evidence-manifest.json)
retain their exact platform/case/property requirements. The verifier rejects
skipped cases in a report submitted against them. The local subset's ten
skips cannot be presented as those acceptance reports or replace earlier
native evidence.

This naming-only proposal does not introduce a new platform capability or
claim renewed G16/G17 acceptance. That does **not** create an automatic rename
exemption from existing CI. For the frozen 27-file implementation inventory,
the unmodified `scripts/ci/select_checks.py` returns `checks.appservice=true`
and `windows.appservice_full=true`. At this baseline, `appservice` is explicitly
in `PAUSED_WORKFLOWS`, so `workflows.appservice=false`; offline appserver and
appservice module regressions remain selected. This is an existing user pause,
not an exception granted by this plan or evidence that all Windows jobs skip.

The reusable `.github/workflows/appservice-quality.yml` retains native/wheel
jobs and manifest verification when selected. Formal implementation must use
the actual existing routing at its delivery head. Do not re-enable the paused
workflow, broaden it, or bypass an active requirement for this rename. If that
workflow is active and selected then, its applicable platform checks and
zero-skip manifest checks remain required as configured. Unchanged historical
acceptance records are not claims that the new head was executed on Windows.

All pytest runs must use the managed `scripts/dev/run_pytest.py` wrapper,
the local venv, the private disk runtime directory and the task worktree's
absolute src on PYTHONPATH, outside the managed sandbox:

```bash
LOUSHANG_RUNTIME_DIR=/home/dev/lsspace/.runtime/loushang-tests \
PYTHONPATH=/absolute/path/to/task-worktree/src \
/home/dev/lsspace/loushang/.venv/bin/python scripts/dev/run_pytest.py \
  tests/appserver tests/appservice \
  tests/apphost/test_foreground.py tests/apphost/test_application.py \
  tests/apphost/test_continuity.py tests/coding/test_hosted_execution.py \
  tests/coding/test_resume_permission_confirmation.py \
  tests/coding/test_hosted_boundary_trace.py \
  tests/harnesstui/test_hosted_mux_profile.py \
  tests/harnesstui/test_hosted_mux_capabilities.py \
  tests/architecture/test_hosted_application_g11.py \
  tests/architecture/test_foreground_stdio_hosted_app_g14.py \
  tests/architecture/test_detachable_local_workspace_g16.py \
  -m 'not live and not requires_host_runtime' --skip-host-runtime --strict-markers -q
```

The four external probes use the same runner and environment; their extra
cases are explicitly distinguished from existing repository coverage. Each
additional test/make invocation must independently receive those settings and
retain its existing safety selectors. There is no `check-appserver` target;
`check-appservice` already covers AppServer.

Final delivery must rerun checks for its actual source revision, audit canonical
and legacy token locations, old keyword behavior, Protocol method shapes,
scope identity/fencing, budgets, forbidden imports, Current doc links and
unchanged wire fixtures. The temporary prototype is not a full-product,
release-runtime, all-platform or delivered-rename claim.

## Implementation Delivery

Implemented on 2026-11-09 in the dedicated `refactor/appservice-port-names`
branch and `.worktrees/appservice-port-names` worktree, based on
`cfbe1286ff5a7ef7ae90055ca7445ce496a89d76`. The user requested implementation
in a separate worktree. Internal technical acceptance by the implementation
agent covers the seven canonical aliases, their existing consumers, serving
role bindings and compatibility behavior described here; no additional
runtime capability, owner, protocol or gate is accepted by implication.

The 27 Product source files now use the canonical names. Six declaration
modules export the seven aliases, preserving the original class objects and
metadata. Serving `_service_port` and foreground/dispatch local bindings are
implemented. Public `client=` parameters/getters, factories, the Coding
`HostedResumeSubjectScope` alias, method shapes and compatibility error text
retain their existing contracts. The scope docstring accurately separates
application authority, transport/authentication and accepted-work ownership.
Current AppServer/AppService documentation records the canonical/legacy roles.

Verification on the final source contents:

- **1,424 passed, 10 skipped in 328.51s**: 1,420 existing cases and four external
  compatibility probe cases. This extends the contract subset above with the
  existing import-boundary suite and two Coding CLI help/startup checks.
- Ruff and mypy passed on all 27 modified source files. The generated Current
  package-dependency facts passed their freshness check.
- Runtime class/function ASTs match baseline after normalizing identifier
  substitutions, the dispatch local binding and the documented docstring
  correction. There is no added authority or operation owner.
- Final budgets: appserver 2,277/2,284, appservice-core 1,966/1,966 and
  managed-close 80/80. The 18 intentional legacy source tokens match the
  declaration/alias/export/error allowlist.
- Existing documentation invariants and changed-document links passed.
  Tests, workflows, routing, manifests, wire schema and Rust sources were not
  modified. `make plan-checks` was inspected; no additional gate was introduced.

Concurrent Coding work is isolated. At the inspected snapshot, only
`apphost/application.py` and `apphost/continuity.py` overlap with
`harness/coding-responsibility-convergence`. Read-only three-way merge previews
for both files completed without textual conflicts, and normalized class ASTs
preserved that branch's lifecycle changes. No file in that agent's worktree was
written or committed by this task. These are snapshot previews, not a claim
that future concurrent edits cannot conflict or that combined-branch tests ran.

The control worktree's prior five modifications and original plan, and the
separate plan-review worktree, remain untouched. Only this implementation
branch is delivered locally. Full-repository regressions, real native Windows
and three-platform native/wheel re-acceptance were not run; the subset and
existing-routing limits above still apply. Remote publication and integration
are separate from this local implementation.

## Review History And Closure

The initial independent review correctly found scope/connection inaccuracies,
inventory errors, unsafe test commands and migration overreach. Its conclusion
that these justified abandoning the shared-contract rename was too strong and
is superseded by this reassessment. The scope-only R2 is also no longer the
recommended solution. Its successful prototype remains historical feasibility
evidence, not architecture acceptance.

At the proposal checkpoint the disposition was **direction accepted for this
proposal, concrete implementation not yet delivered**; Implementation Delivery
now records the local implementation. This is one reviewing/authoring agent's
explicit conclusion, not a fabricated user acceptance or extra reviewer vote.
The original three-perspective R1 record follows verbatim as historical input;
its old measurements and rejected choices do not govern this revision.

## Review Record — R1 Historical Copy

Three independent perspectives, 2026-11-09, each ran its own measurements
against `main`.

### P1 — architecture & boundary: REJECT

Confirmed the dispatch path and the `AppClientScopeV1` diagnosis. Rejected the
`AppClientV1` rename as contradicted by the repository's consumer-naming
convention (`AppServerProductPortsV1`, `HostedSessionPortV1`). Rejected
`ConnectionAuthorityV1` as asserting a connection binding the class lacks.
Found: third exact-type check at `coding/_hosted_execution_work.py:48`; the
`HostedResumeSubjectScope` alias; `coding/` absent from the migration plan;
`make check-appserver` does not exist; budgets recomputed correctly
(2,214/2,221 and 1,961/1,961).

**Accepted.** The primary rename is withdrawn; scope narrowed to
`AppClientScopeV1`; `ConnectionAuthorityV1` rejected; all five corrections
applied.

### P2 — mechanical feasibility: APPROVE-WITH-CHANGES

Independently reproduced 34 refs / 17 files, 24 refs / 7 files, and both budget
figures. Found: `tests/appservice/test_runtime.py:708` asserts
`AppClientV1.__name__ == "AppClientV1"` and would fail under the withdrawn
primary rename; `tests/appserver/test_connection.py:200` compares against
`vars(AppClientV1)`, so a subclass alias fails while plain assignment passes;
`client_scope.py:673` `__all__` was unaddressed; `INITIAL_GOVERNED_DOCUMENTS` has
**47** entries; `drafts/README.md` is link-checked by `scripts/ci/check_docs.py`
on change; no `check-appserver` target; a new file under `tests/appserver/` would
require `test-classification.json` registration.

**Accepted.** Verification rewritten; `__all__` added; guard test placed in an
already-collected file; 47 corrected.

### P3 — governance: REJECT

Agreed the document classification is right (`proposed` / `not-started`, per
`decisions/README.md:14-16`) but rejected using that status as proof reviewers
may not treat this as an architecture change. Found: "App Contract" appears 52
times in `docs/` (58 repo-wide), not 61, and is **not** used consistently for
this Protocol — it is defined as a wider value/versioning concept in
`future-loushang-architecture-v3.1.md:388-402` and
`appservice-embedded-tui-hosted-boundary-plan.md:173`, which makes
`AppContractV1` a superset name. Found: the frozen-document authority is
`architecture/README.md:246-248`, not `drafts/README.md:18`; the plan missed the
normative-Current documents and `docs/internals/plans/`; Phase 0 was
unsatisfiable; two open questions were self-answered.

**Accepted.** `AppContractV1` withdrawn with the superset objection recorded as
the primary reason; Phase 0 rewritten; document categories expanded from two to
four; term count corrected; governance basis cited properly; self-answered
questions removed.
