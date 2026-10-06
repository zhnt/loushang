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
| Native Worker Wheel | `build-coding-worker-candidate`; Linux disposable `loushang-coding-plugin-smoke --kind worker` checks admission and selection only | Linux operator `candidate-capture`, `candidate-install`, `candidate-enable`, `candidate-disable`, and `candidate-remove` stage exact capture, Product installation, and Desired State; native release and per-install opt-in remain separate | Explicit Linux Python SDK Session query can use the selected Worker; default Coding Session remains Current | Linux x86-64; explicit Windows AMD64 Direct, Hosted, and crash/reopen candidate Sessions passed a native 4/4 report on `acd038cb`; the current head still needs its native run, and unflagged Windows routing remains closed | No general third-party self-service, physical GC proof from CLI removal, or default route |
| Other declared Resource kinds | Declaration/IR may exist | No corresponding public Coding Wheel profile for Method, Asset, or Source | No Product consumer proof from declaration alone | None claimed | Open each kind only with its Product owner and evidence |

The local Extension row is the simple file-based author path comparable in
shape to pi extensions. It runs trusted Python in-process. A Wheel is the
versioned Package path with installation, enablement, Product admission, and
retirement; the two paths have different authority and lifecycle guarantees.
The removed `--extension`/`-e` raw CLI flags are not a supported way to bypass
Resource discovery or the Product gate.

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
the Product's current composition preview. `observed_in_preview` admission
and `projected` selection are partial evidence; `productUse` remains
`not_checked` until an actual Session or Screen consumer proves use. A changed
Desired State revision reports `stale_evidence` rather than a current selection.

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
