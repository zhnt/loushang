# Plugin Support Matrix

This is the current Product-facing support projection. Source code and executable
tests remain the authority for behavior. A successful author build or `validate`
checks an artifact only; it does not establish Product admission, selection, or
consumer use. The owner of each Product route makes those decisions. This page
does not add a second Plugin registry or change a default route.

| Kind and entry | Artifact build/validation | Product admission | Selection and consumer evidence | Platform and default | Remaining gate |
| --- | --- | --- | --- | --- | --- |
| Native Skill | `.loushang/skills/<name>/SKILL.md` | Native Resource discovery; no Wheel installation | New Coding Session selects the Skill; `/skill:<name>` injects its text into model input | Coding workspace; no package lifecycle | Verify a concrete Session when asserting use |
| Native Prompt | `.loushang/prompts/<name>.md` | Native Resource discovery; no Wheel installation | New Coding Session expands `/<name>` into model input | Coding workspace; no package lifecycle | Verify a concrete Session when asserting use |
| Native Extension | `.loushang/extensions/<name>.py` or `<name>/extension.py`; single-file `loushang-coding-extension init` | Native Resource/Extension discovery; trusted Python loaded in the Coding process | Can register hooks, tools, commands, flags, and dynamic resources; `loushang-coding-extension smoke` proves one Tool through an offline Session | Coding workspace; separate from Wheel Package lifecycle | No general self-service executable Wheel admission follows from this route |
| Native Theme | `.loushang/themes/<name>.json` | Native Catalog discovery | Catalog visibility exists; native file alone does not change Coding Screen colors | Coding workspace | Screen selection/application remains Product controlled |
| Native Method | `methods/<name>/SKILL.md` | Method loader, separate from Plugin Package | Non-interactive `--method` path; no TUI/RPC Method execution | Coding | No public Method Wheel profile |
| Data Skill Wheel | `build-coding-skill` | Fenced Coding Product admits the constrained document-only profile | Enabled selected revision appears in a new Session; `/skill:<name>` reaches persisted prepared model input | Linux/POSIX Product path verified; not a default global Plugin selection | Per-workspace install/enable and exact Session proof |
| Data Prompt Wheel | `build-coding-prompt` | Same constrained data profile | Enabled selected revision expands `/<name>` into persisted prepared model input | Linux/POSIX Product path verified | Per-workspace install/enable and exact Session proof |
| Screen Theme Wheel | `init-coding-theme` then `build-coding-theme`; disposable Screen smoke | Explicit Coding Screen candidate profile | Exact selected revision and `theme: plugin:<name>` setting change a new Screen; no model-input use | Candidate route; Hosted Mux and live refresh excluded | Separate Product rollout decision |
| Native Worker Wheel | `build-coding-worker-candidate`; Linux disposable `loushang-coding-plugin-smoke --kind worker` checks admission and selection only | Linux operator `candidate-capture`, `candidate-install`, `candidate-enable`, `candidate-update`, `candidate-disable`, and `candidate-remove` stage exact capture, Product installation, version replacement, and Desired State; separate `loushang-package-gc --worker-candidates` deletes exact retired roots after settlement | Explicit Linux Python SDK Session query can use the selected Worker. P4 adds a candidate `--worker-query-plugin` standard Session Tool path; default Coding Session remains Current | Local Linux x86-64 native ordinary-turn CLI/direct, disable, update, hosted first-Session, bounded history, and independent-process same-boot crash/reopen through C5 and GC passed at the P4 worktree head; independent architecture, integrity, and experience reviews passed. Explicit Windows AMD64 Direct, Hosted, crash/reopen, C5 reopen, normal-exit cleanup, and disable while a Session is pinned passed the seven-case native Session gate on `cd25e160`; unflagged Windows routing remains closed | Current-head remote Linux native and shared Windows CI, then exact Linux route owner approval; prior-boot recovery, Windows ordinary turns, general third-party self-service, and default routing remain closed |
| Other declared Resource kinds | Declaration/IR may exist | No corresponding public Coding Wheel profile for Method, Asset, or Source | No Product consumer proof from declaration alone | None claimed | Open each kind only with its Product owner and evidence |

The local Extension row is the simple file-based author path comparable in
shape to pi extensions. It runs trusted Python in-process. A Wheel is the
versioned Package path with installation, enablement, Product admission, and
retirement; the two paths have different authority and lifecycle guarantees.
The removed `--extension`/`-e` raw CLI flags are not a supported way to bypass
Resource discovery or the Product gate.

`loushang --discover-local-plugins` is the read-only local inventory route.
Its version 1 JSON form distinguishes installed Plugin Installations from
native Resource candidates, names source completeness and truncation, and
keeps native-only Catalog selection separate from fenced Product selection.
It uses Product-declared local sources and does not inspect unrelated paths or
execute Extension Python.

## Current composition and management

Coding already defines `coding-minimal`, `coding-standard`, and
`coding-architecture` composition sets. Their inert Product requests contain,
respectively, no Plugin, `coding.base` plus optional `coding.lsp.default`, and
those two plus optional `coding.arch.default`. The sets are Product policy;
actual admission and new-Session selection still depend on the exact owner,
Desired State, and Product gate. A new general-purpose profile system is not
implied by these sets. See the
[composition-set code](../../../../../src/loushang/coding/composition_sets.py).

For an ordinary new Coding Session, `loushang --composition-set coding-minimal`
(or `coding-standard`/`coding-architecture`) selects one of these canonical
requests. With no option, a configured `coding.arch` settings key selects
`coding-architecture`; otherwise the CLI selects `coding-standard`. An
explicit choice wins even when the Arch key is present. The Session header pins
the plan fingerprint. Runtime preparation stores a separate startup receipt
with selected Package revision fingerprints, effective Catalog selection, and
owner generation references; `/session` diagnostics reads that evidence when
the Base command pack is selected. A restored Session reuses its
pinned set and refuses an explicit conflicting choice. The option does not
enable a disabled Provider or change an active Session.
When Base is disabled, the receipt still lists independently selected LSP/Arch
Package revisions and the Catalog selection; Base Tools and `/session` are
absent. Product Desired State or selected manifest changes between Session
construction and startup are rechecked before the Session accepts input.
An older persisted Session without the composition header has no verifiable
set choice and cannot be resumed through this route; create a new Session.

The durable [management service](../../../../../src/loushang/harness/plugin_management/service.py)
owns desired-state operations. The fenced Coding Product exposes bounded
CLI, optional Coding RPC, TUI `/plugins`, and local SDK query/command/repair
adapters; the TUI command route currently supports enable, disable, remove,
and own-operation repair. Read-only composition preview reports
`partial_evidence`: it captures the Product-selected Package and contribution
identity alongside a disposable Catalog generation and exact selected
candidate fingerprint. The preview emits an opaque Package revision fingerprint
because the owner's Source identity may contain a local path. This is evidence
for a *new-Session projection*, not proof that an existing Session consumed the
Resource. The version 2 support-status projection joins this receipt with the
management owner's exact Installation, selected Package and Instance revision,
then retains `productUse=not_checked`. It marks policy, authority, settings, or
Desired State drift as stale. See the
[TUI command adapter](../../../../../src/loushang/coding/plugin_management_ui.py),
[preview contract](../../../../../src/loushang/harness/plugin_management/current_preview.py),
and [read SDK](../../../../../src/loushang/coding/plugin_management_read_sdk.py).

The explicit `loushang-worker-windows-candidate` offline inspect and crash
recovery command is implemented behind `--windows-candidate`. The hosted
crash/reopen Product case calls `inspect` and `recover-crash`, verifies refusal
at injected partial-settlement boundaries, then completes recovery through the
command. The exact code head `cd25e160` passed the seven-case native Windows
Session gate with no skipped cases. This candidate
command does not open unflagged Windows Session routing or general third-party
Worker admission.

`loushang-worker-native candidate-status` reads the retained per-install Worker
opt-in decision and observes an exact selected Worker candidate through the
fenced Product's read-only owner. `observed_in_read` is partial selection
evidence, not an execution grant. The status marks changed Desired State or
opt-in revisions as `stale_evidence`. `candidateOptInAlignment` compares the
selected candidate identity with the retained opt-in decision; even
`identity_match_in_read` does not prove that a native release is current or
that any Session used the Worker.
The disposable Worker author smoke proves admission and selected candidate
bytes for its temporary Linux workspace only; its `nativeRelease` and
`productUse` remain `not_checked`.

For Skill and Prompt authors, `loushang-plugin init-coding-skill` or
`init-coding-prompt` creates source and prints a build command. The resulting
Wheel can be checked with `loushang-coding-plugin-smoke`, which runs install, enable, new
Session selection, and persisted model-input use in a disposable offline
fenced Coding workspace. Its `productAdmission`, `productSelection`, and
`productUse` fields report the stage reached. A passing smoke result is evidence
for that exact Wheel in the temporary workspace, not an admission receipt for
another workspace or platform. See the [authoring guide](plugin-authoring-guide.md).

For a fenced POSIX workspace, `loushang-coding-plugin-status --workspace PATH`,
`/plugins status`, and the local read SDK's `support_status()` use the same
read-only Coding projection. It joins the management owner's Desired State and
the Product's current composition preview. `selected` means the exact
Installation, Package revision, Instance revision, contribution, and Catalog
receipt agree; `projected` means only the Product composition identified the
Plugin. Neither stage proves live use. `productUse` remains `not_checked` until
an exact Session or Screen owner receipt proves use. A changed Desired State,
Product policy/authority, or persisted disabled-Skill settings revision reports
`stale_evidence`. Pending A1 operations carry their original actor and exact
operation ID. CLI-origin and TUI-origin operations present only their own repair
commands.

`--explain-plugin-operation`, `/plugins explain`, and the Coding read SDK
classify an observed A2 Package operation separately from an A1-only Desired
State command. A successful A1 enable with no Package operation has no Package
handoff gap. An incomplete, exactly joined A2 handoff can offer
`loushang-package-repair repair-handoff` when the Product-owned Desired commit
has an exact receipt or verified transition. The A2 management actor remains
`product:coding`; the operator repair command does not recast it as a CLI-owned
Desired operation. The status row includes the exact Installation, an opaque Package
revision fingerprint, Instance revision, retirement states, and cleanup debt;
TUI list and status show nonempty debt.

## Product and platform gates

| Route | Current status | Evidence and limit |
| --- | --- | --- |
| Linux fresh workspace | Ordinary first-B cutover, Coding Session and offline Package GC are open | [Coding user guide](../../../../en/user-guide/README.md) and Product regressions; pre-B legacy migration is unsupported and refuses without writes |
| Windows fresh workspace | Explicit `--windows-candidate` first-B cutover and offline GC are open | [PLC9 exact-head native report](plugin-experience-and-plc9-closure-design.md); unflagged ordinary Windows Session/write/GC route remains separately gated |
| macOS | Hosting has native CI evidence | No claim here of an equivalent full Coding Product end-to-end gate |
| Management | Fenced Product-backed CLI, optional Coding RPC, TUI, and local SDK have bounded query/command/repair routes | Exact owner/scope and command gates apply; generic Hosts do not automatically expose Coding routes |

PLC9 historical implementation and acceptance evidence is recorded in the
[closure ledger](plugin-experience-and-plc9-closure-design.md). Its earlier
time-stamped statements may describe a gate before a later native run opened
it; use the latest exact-head evidence and current source for status.

## Exact owners and executable evidence

| Route | Decision and evidence owner | Focused evidence |
| --- | --- | --- |
| Native Skill, Prompt, Theme, Extension | Harness Resource Catalog supplies candidates; Coding Session and Extension runtime decide consumer use | [native discovery](../../../../../tests/coding/test_resource_loader.py), [Extension behavior](../../../../../tests/coding/test_extension_platform.py) |
| Data Wheel | Coding Package Product admits the exact Wheel, Resource Catalog selects it, Coding Session commits model input | [Product admission and prepared-input cases](../../../../../tests/coding/test_package_external_data_wheel.py), [author smoke](../../../../../tests/coding/test_plugin_author_smoke.py) |
| Screen Theme | Coding Package Product and Coding Screen own selection and visual application | [Theme Product cases](../../../../../tests/coding/test_package_external_data_wheel.py) |
| Worker | Coding Product owns explicit candidate selection/receipt; Hosting owns native launch and containment | [PLC9 exact-head native report](plugin-experience-and-plc9-closure-design.md) |
| Method | Coding Method loader owns selection, outside Plugin Wheel lifecycle | [Method loader cases](../../../../../tests/method/test_method_loader.py) |
