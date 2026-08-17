# Session Agent Runtime Boundary

This document defines Slice A of the Coding shared-layer migration.  It is an
implementation boundary, not a compatibility promise for the old module
layout.

## Baseline

`src/loushang/coding/session/agent_session.py` was restored to the composed
adapter after an integration merge reintroduced direct runtime assembly. It is
now 522 lines, down from 1,732 lines in the merged baseline.
Most of its constructor assembles already shared Harness runtimes: transcript
context, queue and turn policy, retry, compaction/navigation, resource
refresh, tool activation, extension lifecycle, and session disposal.

## Target ownership

`loushang.harness.session.composition`,
`loushang.harness.session.operations_runtime`, and
`loushang.harness.session.agent_adapter` own reusable session composition and
operation coordination. `loushang.harness.session.agent_product_runtime` owns
the standard lifecycle hooks, transcript runtime ports, and concrete Product
session runtime. `loushang.harness.session.extension_composition` owns the
extension input adapter, provider/replacement controllers, runtime binding
factory, and public extension lifecycle binding. They accept explicit Product
ports for:

- transcript/session storage and context application;
- model/thinking selection and persisted settings;
- resource and package policy;
- extension bindings and provider actions;
- compaction and branch-summary executors;
- diagnostics, approval, command, and presentation callbacks.

The Harness runtime must not import Coding, Method, Work, or product resource
content.  It may use the stable Agent/AI value contracts already admitted by
`harness.session`.

The shared Harness composition already exists; this re-application deletes
1,210 Coding lines without adding another runtime engine. Tests and
documentation are excluded from the LOC accounting.

Coding keeps only its product plan and adapters: preferred model policy,
resource roots, command wording, Coding compaction/branch-summary prompts,
provider conversion, footer/diagnostic presentation, and Coding extension API
behavior.

The physical boundary is intentional: `agent_adapter` contains the composed
session facade and installation plumbing, while `agent_product_runtime`
contains replacement lifecycle policy. The runtime module must not import the
adapter, and the package root exports runtime symbols from their real owner.
The former direct `agent_adapter` imports remain compatibility aliases only.

Extension assembly receives its own explicit capability record; it does not
receive `SessionCompositionPorts` and must not import `composition`. This keeps
the extension-facing dependency surface visible without creating a second
session composition root.

Composition ports contain Product policy or unavailable pre-assembly state,
not aliases for already assembled runtimes. Context refresh, resource refresh,
event projection, and serialization must use their existing runtime owners
instead of adding pass-through callbacks to `SessionCompositionPorts`.

The composition root is staged internally without expanding that port surface:
foundation runtimes assemble diagnostics, tools, resources, navigation, and
bash; maintenance runtimes assemble the selected compaction capability plus
compaction and retry runtimes; Product bindings assemble model, identity,
maintenance, inspection, and extension bindings after the core `SessionRuntime`
exists. The private stage results are frozen containers of existing runtimes,
not new bridges, coordinators, or callback owners.

`SessionComposition` is also a frozen assembly result. After installation, the
Agent Product adapter keeps that result as its single source for assembled
runtimes and bindings instead of copying each component into another private
attribute. Product objects that must exist before composition, such as package
and extension controllers, may retain their construction-time references; the
adapter must not create post-assembly runtime mirrors for convenience.

## Deletion condition

The old `AgentSession` implementation is reduced to a thin Product adapter.
No generic queue, retry, compaction/navigation, extension lifecycle,
tool/resource controller, transcript export, or disposal implementation may
remain duplicated in Coding.  The remaining 522 lines are limited to
composition inputs, model restoration, resource/package policy, provider and
footer behavior, replacement validation, and Product compaction/branch hooks.

## Compatibility and validation

The public Coding session surface and RPC wire shape remain unchanged.  The
slice is accepted only when focused session tests, AgentSession regressions,
architecture import-boundary tests, Ruff, and `git diff --check` pass.  A
Harness fake-product probe must construct two independently configured Product
sessions, exercise their compaction strategies and hooks, and dispose them
without cross-session state or any import of `loushang.coding`.
