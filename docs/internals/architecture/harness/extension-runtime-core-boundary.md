# Harness Extension Runtime Core Boundary

## Status

Status: implementation complete, including the follow-on control-plane routing
closure, for integration into `lane/harness`.

This boundary moves the product-neutral extension runtime core into
`loushang.harness.extensions`. Coding remains Product composition; the
zero-compatibility cutover preserves Product behavior without retaining Coding
Extension import paths or a second implementation.

Canonical Package, Plugin, and Extension terms are defined by the
[Product And OEM Glossary](../../glossary/loushang-product.md). This runtime
owns Extension loading and composition after discovery and Product/OEM
admission. It does not own Resource Package distribution or Plugin identity,
source registration, enablement, and package-root resolution; those mechanics
belong to the
[Platform Resource Layout Boundary](platform-resource-layout-boundary.md).

## Harness Ownership

Harness owns these mechanisms:

- extension event vocabulary and manifest declaration parsing;
- `LoadedExtension`, contribution registration records, input results, and
  neutral activation-decision records;
- `ExtensionContributionAPI` for hooks, tools, commands, flags, shortcuts, and
  message renderer registration;
- descriptor-driven Python module loading, legacy-object adaptation, manifest
  attachment, and contribution projection;
- deterministic command naming, first-wins flag/shortcut/tool resolution,
  source provenance, and duplicate diagnostics;
- stable dependency-aware route planning, failure-contained observer dispatch,
  opaque-state reducers/interceptors, and sequential input transformation;
- resource contribution execution and `promptPaths`, `skillPaths`, and
  `themePaths` normalization;
- registered-tool execution wrapping with an injected context factory.
- `ExtensionRuntime`, which composes already-loaded extensions into the common
  registry, route plan, dispatcher, resource discovery, command/flag/shortcut,
  tool, renderer, diagnostic, and extension-visibility surface.
- `ExtensionSessionRuntime`, which applies the existing lifecycle coordinator
  to a bound Product session's runtime bindings, start/refresh events, reload
  resource refresh, diagnostics, and context invalidation.

The implementation is split across focused modules under
`loushang.harness.extensions`: `manifest`, `types`, `api`, `loader`, `registry`,
`dispatch`, `resources`, `contributions`, and `wrapper`. These modules are not
exported from top-level `loushang.harness`.

Harness consumes already-discovered `ExtensionDescriptor` values. It does not
choose search roots, trust an extension, enable a product capability, or decide
whether a descriptor should be passed to the loader. A product must apply its
trust, approval, and activation policy before executable extension code is
loaded.

## Coding Adapter

The optional Agent profile owns:

- `ExtensionAPI` additions for session entries, messages, model selection,
  thinking level, labels, and provider-registration callbacks;
- the standard Agent permission-level defaults and capability mapping in
  `policy_from_manifest`;
- the loader and runner profiles that bind those additions to the neutral
  Harness extension loader and runtime.

Products keep:

- callback injection for the Harness-owned runtime binding/context mechanisms
  defined by the [Product Runtime Core Boundary](product-runtime-core-boundary.md);
- session switch/fork/compact/tree decisions and Coding event projection;
- system-prompt augmentation, model/provider behavior, Agent tool-call result
  adaptation, compaction behavior, and UI integration;
- Product-specific provider factories, credentials, default activation,
  diagnostics wording, and transport/UI projection.

The complete `loushang.coding.extensions` package is removed. Agent products
import `ExtensionAPI`, `ExtensionLoader`, and `ExtensionRunner` from
`loushang.harness.extensions.agent`; neutral records remain owned by focused
modules directly under `loushang.harness.extensions`.

## Runtime Composition

`ExtensionRuntime` starts after a Product has loaded, trusted, and selected
extensions. It owns the mechanical composition of the standard extension
surfaces: registration resolution, dispatch routing, resource contribution
execution, context-factory based tool wrapping, and diagnostic/visibility
projection. Its two context factories are explicit injection points: the
per-extension factory supports dispatched hooks and tools, while the optional
resource factory preserves a Product's resource-refresh context semantics.

The runtime has no Product session state and does not interpret model choices,
approval outcomes, UI state, or Agent-specific hook results. The optional
Agent `ExtensionRunner` profile only selects the Agent API, policy, and loader;
Products inject live runtime bindings and any Product error projection. It
must not reimplement
registry snapshots, resource discovery, generic input/event dispatch, command
completion, flag state, or extension visibility serialization.

The optional Agent extension profile owns `ExtensionInputRuntime`,
`ExtensionAgentHookRuntime`, and `ExtensionAgentEventRuntime`. Its target
package is `harness.extensions.agent`, split into `input.py`, `hooks.py`, and
`api.py`, `loader.py`, `policy.py`, `runner.py`, `input.py`, `hooks.py`, and
`lifecycle.py`; the former session-owned and Coding-owned module locations are
deleted. It delivers standard extension-originated input, composes typed Agent
context/tool hooks, and observes Agent lifecycle facts without importing a
Product.

The profile is an in-process integration boundary, not an event bus or a
plugin container. Hook results are the only documented control path. Lifecycle
callbacks are observation-only and do not create a second `RuntimeEvent`,
transport, or external-process JSON protocol. The profile receives an injected
clock and available session/run/turn/tool-call correlation values so lifecycle
callbacks are deterministic and attributable. A Product still supplies its
runtime binding factory, session replacement/fork semantics, provider
implementation, diagnostics wording, and transport/UI projection.

These Agent-extension profile modules may depend on stable Agent/AI message and
tool value contracts because they operate a live Agent session. They are
separate from the neutral extension core: they must not import Coding, a
Product, provider execution, authentication, model resolution, or UI
implementation. They also do not import `harness.session`; session assembly
passes delivery, prepared-input, and lifecycle capabilities into the profile
through typed ports.

## Policy Injection

Harness supplies a neutral `ExtensionPolicyDecision` and a conservative
descriptor-enabled default. The optional Agent profile supplies the standard
Agent permission-level mapping. Other profiles may inject their own
`ExtensionPolicyResolver` into the neutral loader.

Harness also leaves runtime state opaque. `ExtensionContributionAPI` only uses
capability-shaped callbacks when a product binds them. Coding's binding record
may contain additional session/model/UI callbacks without pulling those fields
into the shared contract.

## Extension Injection Categories

Extensions fall into three categories with different execution semantics:

| Category | Behaviour | Failure strategy | Examples |
| --- | --- | --- | --- |
| **Contribution** | All declarations are aggregated; each runs independently | One failure produces a diagnostic; others continue | tool, command, skill, method, prompt, resource_root |
| **Interceptor** | Handlers form a pipeline; each sees the output of the previous | Step failure is governed by `on_error` (skip / fail_chain) | hook, policy |
| **Replacement** | Only one active provider per slot; the first active provider in resolved order wins and conflicts are diagnosed | Failure propagates to the Product-selected fallback; there is no chain to skip | approval, model_provider, channel adapter, storage backend |

Harness owns the scheduling categories. Product adapters and OEMs decide
which extensions are active in each category and inject policy for each slot.

## Extension Routing And Ordering

Extension execution is compiled into an event-scoped route plan. The descriptor
and registered-handler records carry explicit ordering and error-policy fields:

```python
@dataclass(frozen=True)
class ExtensionSurfaceDescriptor:
    type: ExtensionSurfaceType
    name: str
    extension_id: str
    source_path: Path
    active: bool = True
    priority: int = 0
    permission_requirements: tuple[str, ...] = ()
    diagnostics: tuple[DiagnosticDraft, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    # Appended to preserve the legacy positional constructor contract.
    after: tuple[str, ...] = ()       # canonical route/extension references
    before: tuple[str, ...] = ()
    on_error: Literal["skip", "fail_chain"] = "skip"
```

Routes use stable topological ordering with priority and registration order as
tie-breakers. When `after` or `before` constraints create a cycle, Harness
preserves edges outside the strongly connected component, emits a diagnostic,
and uses priority plus registration order inside the conflicting component.
Legacy `LoadedExtension.hooks` values synthesize registrations in existing
extension and handler order.

## ExtensionSurfaceType Gaps

The control-plane closure adds executable `policy` and `approval` contribution
paths. Method and Channel surfaces remain owned by their respective layers and
are not added as unprocessed Harness vocabulary:

```python
ExtensionSurfaceType = Literal[
    # existing
    "command",
    "tool",
    "prompt",
    "skill",
    "hook",
    "model_provider",
    "ui",
    "autocomplete",
    "resource_root",
    # implemented control-plane contributions
    "policy",          # inject a PolicyEvaluator chain member
    "approval",        # select an ApprovalResolver replacement
]
```

Runtime values use focused control-contribution records rather than mutable
descriptor metadata. Policy contributions compose in resolved route order;
approval is an exclusive replacement slot with deterministic conflict
diagnostics. Policy contributions fail the chain by default; advisory skip
semantics must be explicit. The selected approval replacement validates its
result and reports route/source diagnostics before propagating failures, while
cancellation remains undiagnosed. Product/OEM code supplies activation and
trust decisions before composition; Harness applies inactive filtering
consistently across executable surfaces. See the
[Control Plane Runtime Boundary](control-plane-runtime-boundary.md) for the
runtime contracts and compatibility matrix.

## Failure And Ordering Contract

Extension order and handler registration order are stable. One failing handler
adds a provenance-bearing diagnostic, invokes the optional runtime-error
callback, and does not stop later handlers.

Commands with duplicate names receive deterministic numeric invocation
suffixes while avoiding literal-name collisions. Duplicate tools, flags, and
shortcuts are first-wins and produce diagnostics for rejected contributions.
Products may replace this policy later by supplying a different registry layer;
the core does not infer user intent.

## Canonical Imports

Agent products use the canonical Agent profile; neutral extension contracts
continue to use their focused Harness owners directly:

```python
from loushang.harness.extensions.agent import ExtensionLoader, ExtensionRunner
from loushang.harness.extensions.manifest import parse_extension_manifest
from loushang.harness.extensions.types import ExtensionPolicyDecision
```

The complete legacy `coding.extensions` package is removed. New cross-product
code imports either the optional Agent profile or the focused neutral Harness
owner directly; no Product compatibility path is retained.

## Dependency Direction

The target direction is:

```text
loushang.coding                               # Product composition only
  -> loushang.harness.session
  -> loushang.harness.extensions.agent        # optional typed Agent profile
  -> loushang.harness.extensions               # neutral routing/runtime
  -> loushang.harness.resources / tools / contributions

loushang.harness.extensions.agent
  -> stable public Agent/AI values + injected Harness ports
```

The neutral modules directly under `loushang.harness.extensions` must not
import Coding, Method, Work, TUI, AI, provider, UI, Session, or another Product
package. The optional `loushang.harness.extensions.agent` profile is the sole
exception: it may import narrow public Agent/AI value contracts and Harness
Agent-transcript/host values, but never `harness.session`, Coding, Channel,
Work, Method, TUI, provider execution, authentication, model registry, or a
Product package. The `harness.extensions` package root must not eagerly import
or re-export the optional Agent profile.

Trust, approval, and activation remain before this graph: a Product or OEM
selects eligible extensions before `ExtensionRuntime` composes them, and the
Agent profile never bypasses that decision. A future process-hook adapter, if
needed for OEM integration, is separate from this typed in-process profile.

Coding must not reintroduce parallel implementations of Harness-owned
manifest, loader, registry, dispatcher, resource contribution, runtime
composition, or tool-wrapper behavior.

## Validation

The migration must prove:

- a product-neutral extension can register, load, resolve, dispatch, and
  contribute resources without Coding runtime objects or Coding vocabulary;
- failure containment, ordering, conflicts, source provenance, and input
  reduction remain deterministic;
- accepted Coding paths share Harness-owned object identity;
- Coding loader, API, runner, resource, and hook behavior remains compatible;
- Harness import boundaries and top-level export discipline remain intact;
- startup and the non-live test suite remain green.
