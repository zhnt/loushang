# Coding Shared-Layer Migration Ledger

This is the rolling implementation ledger for
[the Coding shared-layer migration plan](coding-shared-layer-migration-plan.md).
It is deliberately a ledger, not a second design document: a wave cannot start
until its source regions, final owners, injection points, and deletion condition
are listed here.

[Coding Shared-Layer Owner Rebaseline](coding-shared-layer-owner-rebaseline.md)
is the Wave R evidence for this ledger. It distinguishes shared mechanisms that
are already adopted from actual Coding duplicates; only the latter may support a
future migration LOC claim.

## Ownership Rules

Move an implementation out of `loushang.coding` when it implements a mechanism,
bridge, public contract, or reusable default and every product difference can be
supplied through a port, profile, callback, or plan. The final owner follows the
kind of capability, not the name of the old package.

Neutral Harness core remains independent from Agent and AI. Declared optional
integration packages, including `harness.session` and
`harness.transcript`, may use stable public Agent and AI value contracts;
they must not own provider registration, credentials, or product model policy.

## Wave 1: Leaf Foundations (Complete)

| Source region | Shared owner | Product injection or retained Coding owner | Status |
| --- | --- | --- | --- |
| `coding.diagnostics.problem_bridge` | `harness.diagnostics.observability_bridge` | Products may supply phase/source resolvers. Coding supplies its `config -> model` source override. | Complete: the Coding bridge was deleted. |
| `coding.diagnostics.debug_status` problem-store formatting | `observability.problem_text` | Coding keeps CLI text and default diagnostic export command. | Complete: reusable formatting has no Coding import. |
| removed `coding.diag_export` archive writer and redaction | `harness.diagnostics.export` | Products may replace the shared `DiagnosticBundleProfile`; Loushang products use the standard archive, manifest, README, artifact set, and diagnostic projection. | Complete: Coding imports the shared bundle operation directly. |
| `coding.source_info` descriptor conversion | `harness.resources.source` | Coding only supplies its resource descriptor values. | Complete: production resource consumers import Harness directly. |
| removed `coding.source_info` executable, package, and Git inspection | `observability.runtime_identity` | `coding.diagnostics.profile` supplies package/module aliases, executable name, and display title through `RuntimeIdentityProfile`. | Complete: Coding has no source-info facade, subprocess, package metadata, or PATH logic. |
| `coding.model_selection` normalization and presentation-neutral ordering | `ai.model` | Coding retains preferred models and Coding persistence wording. | Complete: non-policy consumers import `ai.model`. |
| `coding.model_selection` session model application and discovery | `harness.session.model_selection` | Products inject preferred candidate selection and persistence callbacks. | Complete: Coding is the preferred-candidate adapter. |
| removed `coding.observability` configuration lifecycle | `harness.diagnostics.observability_runtime` over `observability.runtime` | Coding supplies only its `config -> model` diagnostic-source policy. Shared defaults own `.loushang` paths and stable session labels. | Complete: CLI and TUI bind the shared contexts directly. |

Wave 1 contract probes:

- The diagnostics archive writer accepts a product-projected manifest and
  diagnostics, redacts both structured values and text artifacts, and rejects
  unsafe archive member names.
- Runtime identity collection works for a non-Coding package/module pair.
- Session model selection works with a fake session and a caller-supplied
  candidate chooser; it has no Coding import.
- Observability lifecycle configuration restores a pre-existing sink after the
  product context exits.

## Top-Level Work, Diagnostics, And Bootstrap Collapse (Complete)

This batch applies the same ownership test to root-level `coding/*.py` files;
placement at the Product package root does not imply Product ownership.

| Removed or reduced Coding region | Canonical owner | Retained Product input |
| --- | --- | --- |
| removed `work_executor.py`, `work_runtime.py`, `work_shell.py`, and `work.coding` | `work.session.SessionWorkRuntime` composed over the existing `work.WorkRuntime` | `coding.domain.work` supplies `domain="coding"`, `SubmitCodingTurn`, and the Agent-event fact projector. |
| `prompt_command.py` and print/channel/CLI Work bindings | existing `harnesstui.conversation` hosts plus `work.session` | Coding retains its renderer, failure wording, Method metadata preparation, and Product binding names. |
| removed `diag_export.py`, `observability.py`, and `source_info.py` | existing Harness diagnostics and Observability packages | `coding.diagnostics.profile` supplies only source aliases and runtime-identity labels. |
| `sdk_surface.py` | `harness.sdk_surface` inspection algorithm | Coding retains the required public entry-name tuple and default module binding. |
| `bootstrap.py` standard activation effects | existing `harness.session.bootstrap` activation graph and `StandardAgentSessionConfigurationRuntime` | Coding supplies Extension construction, source-identity check, prompt/model/tool/session factories, and Product defaults. |

Implementation accounting, excluding tests and documentation:

- Coding Python: 11,969 to 11,010 LOC, a net reduction of 959 LOC.
- root-level `coding/*.py`: 3,473 to 2,358 LOC, a reduction of 1,115 LOC.
- Work/Prompt Coding region: 867 to 392 LOC, a reduction of 475 LOC.
- diagnostics/source/SDK Coding region: 427 to 127 LOC, a reduction of 300 LOC.
- `coding.bootstrap`: 773 to 567 LOC, a reduction of 206 LOC.
- shared mechanisms added or expanded: approximately 1,110 LOC, giving a
  Coding-deletion/shared-addition ratio of approximately 0.86.

The old Coding files are deleted rather than retained as aliases. Architecture
probes require `work.session`, `harness.sdk_surface`, Harness diagnostics, and
the standard session bootstrap runtime to remain free of Coding imports.

## Root Product Plan And Shared Adapters (Complete)

This batch removes the remaining root-level runtime/capability implementations
without introducing a second resolver, transcript lifecycle, resource loader,
selection runtime, or plain-prompt host.

| Removed or reduced Coding region | Existing or extended shared owner | Retained Product input |
| --- | --- | --- |
| removed `coding.runtime_profile` | `harness.transcript.AgentTranscriptProfileRuntime` composed over the existing runtime resolver/binder, transcript stores/profile, and compaction capability | `coding.product_plan` declares Product IDs, metadata key, store/profile implementation identities, and current defaults. |
| removed `coding.capability_plan` | existing `harness.capabilities.composition_runtime` via `standard_capability_composition_plan` | `coding.product_plan` selects the standard composition profile; future Coding deltas remain declared Product data. |
| `coding.session_manager` runtime binding | the shared Agent transcript profile runtime | Coding retains session-root and persistence decisions plus restored-header Product validation. |
| `coding.model_selection_tui` | existing `harness.session.model_selection` and `harnesstui.selection` catalog/runtime | Coding retains preferred-model policy, settings persistence, and its persistence-warning wording. |
| `coding.resource_runtime` | existing `ResourceLoader` through `ResourceLoaderProfile` and `ProfiledResourceLoader` | Coding retains built-in package identity, context-file compatibility names, prompt assembly, package security policy, and default loader choice. |
| duplicated helpers in `coding.prompt_command` and HarnessTUI plain mode | existing `harnesstui.conversation.plain_prompt_host` | Coding retains Work/Method preparation, renderer, Product diagnostics, and final wording. |
| `coding.tool_pack` | existing Harness workspace tool factory/registry plus `WorkspaceToolProfile` | Coding retains Product membership/order, descriptions, prompt snippets, policy, approval, diagnostics, and execution-service inputs. Contribution resolution and registration no longer repeat in Coding. |

Implementation accounting, excluding tests and documentation:

- Coding Python: 11,007 to 10,363 LOC, a net reduction of 644 LOC.
- root-level `coding/*.py`: 2,358 to 1,708 LOC, a reduction of 650 LOC.
- removed runtime/capability implementations: 404 LOC, replaced by the
  38-line declarative `coding.product_plan`.
- `coding.model_selection_tui`: 165 to 38 LOC.
- `coding.resource_runtime`: 154 to 95 LOC.
- `coding.prompt_command`: 324 to 251 LOC.
- shared implementation added or expanded: 761 lines and 69 lines removed,
  including the reusable Agent transcript binding, for a Coding-deletion/shared-
  addition ratio of approximately 0.85.

Product-neutral probes bind `research`/`design` transcript, capability,
resource, model-selection, and plain-prompt adapters without importing Coding.
The old Coding implementations are deleted rather than retained as facades.

## HarnessTUI Conversation Product Binding Collapse (Complete)

This batch removes the remaining Coding-owned copies of the standard
conversation interaction and Agent presentation bindings. It extends existing
HarnessTUI owners rather than introducing a second controller, action host,
history projector, tool projector, surface workflow, or model selector.

| Removed or reduced Coding region | Existing or extended shared owner | Retained Product input |
| --- | --- | --- |
| removed `coding.interaction.intent` | `harnesstui.conversation.intents` | Coding adds no private grammar; future Product intents can be composed at the Product boundary. |
| removed `coding.interaction.controller`, `screen_host`, and `tui_profile` | existing `harnesstui.conversation.controller`, `host`, `action_presentation`, and `info` | `coding.ui.product_binding` injects the command catalog, callbacks, logger, problem prefix, and Product copy. |
| removed `coding.presentation.tui.screen` and `tool_transcript` | optional `harnesstui.conversation.agent_binding` over the existing neutral history, tool, plain, and screen projectors | Coding retains its renderer/glyph profile and attachment-to-AI conversion. |
| reduced `coding.presentation.tui.history` and removed `coding.presentation.session` | `harnesstui.conversation.agent_binding` and `session_view` | Coding retains only persisted SessionManager history loading. |
| standard command/model/settings surface construction | existing `harnesstui.surface` and `harnesstui.selection` profiles/factories | Coding retains settings fields, terminal diagnostics, approval UI, model-application callback, and Product subtitle. |

Closure probes require:

- the neutral conversation modules to remain free of Agent, AI, and Coding
  imports while the optional Agent binding remains free of Coding imports;
- Coding UI construction to use the shared controller, routing profile, local
  action registry, action host, history/tool projectors, and surface factories;
- deleted Coding modules to remain absent rather than returning as compatibility
  re-exports;
- prompt, command, model, queue, retry, compaction, history, tool transcript,
  plain-mode, and screen-mode behavior tests to remain unchanged.

Implementation accounting, excluding tests and documentation:

- Coding Python: 10,363 to 9,520 LOC, a net reduction of 843 LOC.
- Coding source changes delete 1,153 lines and add 310 lines, including the
  96-line Product binding; nine duplicate implementation modules are removed.
- HarnessTUI Python: 15,728 to 16,739 LOC, a net increase of 1,011 LOC.
- Shared source changes add 1,014 lines and remove 3 lines. The additions are
  contracts and compositions over existing owners, not replacement engines.
- Across Coding and HarnessTUI production Python, the batch adds 168 net lines
  while moving the reusable ownership out of Coding.

## Wave 2: Event And Extension Product Adapter Collapse (Complete)

The detailed contract is
[Event And Extension Product Adapter Collapse](event-extension-adapter-collapse-boundary.md).
This is an adapter-collapse Wave, not a mandate to move Coding wire contracts
into Harness.

| Source region | Shared owner | Product injection or retained Coding owner | Deletion condition |
| --- | --- | --- | --- |
| removed `coding.extensions.hooks.HookDispatcher` | `harness.extensions.agent.hooks.ExtensionToolHookDispatcher` | Product supplies context factory and runtime error projection. | Complete: Coding module deleted after focused Agent-hook equivalence tests and a no-Coding-import probe. |
| Agent prompt/context/session-decision reducers formerly in `coding.extensions.runner.ExtensionRunner` | `harness.extensions.agent.hooks` and `harness.extensions.session_runtime` | Coding supplies bound context, CWD, API binding, `before_agent_start` factory/result coercer, and session-decision coercer. | Complete: shared dispatchers own the reducer mechanics; Coding retains provider behavior and Product coercers. |
| removed `harness.session.extension_{hooks,events,input}` modules | `harness.extensions.agent.{hooks,lifecycle,input}` | Session only consumes the profile during Agent-session composition. Input receives normalized typed requests plus queue/delivery ports; lifecycle is an observation-only extension callback adapter with injected clock/correlation values; Coding retains wire parsing/defaults. | Complete: consumers import the profile directly, input has no Session import, and Session no longer re-exports the profile. |
| `coding.extensions.runner.ExtensionRunner` loader/API portions | Coding adapter over `harness.extensions.runner.ExtensionRunner` | `ExtensionAPI`, policy resolver, loader configuration, provider actions, and Coding error dictionary remain Product-owned. | Complete: the Coding runner is a thin loader/policy binding; shared reducer and dispatch mechanics live in Harness with snake_case-only extension events. |
| removed `coding.event` runtime projection, views, serializer, presentation policy, and final import facade | `harness.session.event_types`, `harness.session.event_projection`, `harness.session.runtime_event_views`, `harness.session.event_serialization`, and `harness.events.recording_policy` | Product/Work mapping, rendering, and final wording remain in their existing owners. Session owns runtime-view selection/stream shaping and delivery hints; Events owns transcript-write decisions and cancellation classification. The shared wire schema is snake_case-only; no duplicate neutral event engine exists. | Complete: all consumers and tests import the canonical Harness implementations directly; no Coding event facade or Pi/camelCase alias remains. |

Wave 2 contract probes:

- a fake Product executes context, before/after tool, before-agent-start, and
  session-decision hooks with no Coding import;
- invalid hook results, route ordering, block behavior, and runtime failure
  reporting preserve existing diagnostics;
- Coding extension provider actions remain unchanged; JSON/print/RPC event
  projections use the canonical snake_case fields;
- architecture tests forbid Coding imports from the new shared dispatchers and
  forbid a second event schema or alias layer;
- `harness.extensions.agent` has no `harness.session` import, while neutral
  `harness.extensions` modules do not eagerly import or re-export the Agent
  profile; lifecycle callback order and timestamps are deterministic under an
  injected clock.

## Wave 4, Slice A: Agent Session Adapter Collapse (Complete)

The detailed boundary is
[Session Agent Runtime Boundary](session-agent-session-boundary.md).

| Source region | Shared owner | Product injection or retained Coding owner | Deletion condition |
| --- | --- | --- | --- |
| `coding.session.agent_session` composition and operation coordination | `harness.session.composition`, `harness.session.operations_runtime`, and `harness.session.agent_adapter` | Coding supplies model restoration, resource/package policy, provider/footer behavior, compaction and branch-summary executors, replacement validation, and Product callbacks. | Complete: after an integration merge reintroduced direct assembly, `AgentSession` was restored from 1,732 to 522 lines; the shared modules have no Coding import. |

Wave 4, Slice A closure probes:

- AgentSession, retry, export, and tool regressions pass without changing the
  public session or RPC surface;
- Harness owns resource watching, command/preflight forwarding, extension
  lifecycle, event dispatch, approval lifecycle, transcript export, and
  composed-session initialization;
- a source-level architecture probe rejects `loushang.coding` imports from
  the new session adapter modules;
- the Coding implementation reduction is 70.5% (1,219 of 1,729 lines), with
  the remaining code limited to the product responsibilities listed above;
- the implementation diff deletes 1,399 Coding lines and adds 1,949 shared
  Harness lines (a 0.72 deletion/addition ratio); tests and documentation are
  excluded from this accounting.

## Later Waves

Wave 3's initial command-handler cutover is implemented in
[Standard Session Command Pack Boundary](session-command-pack-boundary.md).
The remaining rows are intentionally broad until their waves are scheduled.
They are not estimates or approval to duplicate an existing Harness owner.

| Wave | Source regions to ledger before implementation | Intended shared owners |
| --- | --- | --- |
| 3 | `coding.session.builtin_commands` admitted subset (`session`, `name`, `export`, `import`, `compact`, `reload`, `new`, `resume`, `fork`, `clone`, `tree`); `coding.session.command_controller` standard-source forwarding; command descriptor and result projection helpers | `harness.session.command_pack`, existing `harness.session.SessionCommandRuntime`, `harness.commands`, and `harness.extensions.commands` |
| 4 | `AgentSession`, runtime composition, bootstrap activation | existing `ProductRuntimePlan`, runtime resolver/binder, `harness.session` |
| 5 | RPC, print, channel host, shared conversation interaction | `channel`, `harness.session`, `harnesstui`, `tui` |
| 6 | Config composition, common defaults, CLI and Work/Method bridges | `harness.config`, `ai`, `work`, `method`, `tui` |

Each later row must be expanded to the same level as Wave 1 before code changes
begin. A product facade is not complete until the old implementation is deleted
or reduced to declared product data and ports.

### Wave 5 Scope Gate: Session RPC Operations

The detailed boundary is [Session RPC Operation Cutover Boundary](session-rpc-operation-boundary.md).

| Source region | Shared owner | Product injection or retained Coding owner | Deletion condition |
| --- | --- | --- | --- |
| JSONL command registry and unknown-command fallback | `channel` | Coding registers its RPC methods and projects its legacy error frame. | Complete: `JsonlCommandRouter` has no Harness/Coding import or wire-schema defaults. |
| Prompt task lifetime and standard session-operation invocation | `channel` task tracking plus existing `harness.session.SessionOperationRuntime` | Coding parses aliases, acknowledges preflight, and projects errors/results. | Pending: admitted handlers delegate through bound ports with no duplicate operation executor. |
| RPC model/auth, package, bash, extension UI, event, state, and transcript handlers | Coding | Product policy and public wire contract. | Retained by design. |

### Wave 3 Scope Gate

| Source region | Shared owner | Product injection or retained Coding owner | Deletion condition |
| --- | --- | --- | --- |
| Shared command descriptor contract and resource/extension projection | `harness.commands` and `harness.extensions.commands` | Coding retains builtin command data, descriptor ordering, and source priority. | Complete: generic descriptor types and resource/extension projections have no Coding import. |
| Descriptor construction for the admitted standard command subset | `harness.session.list_standard_session_command_descriptors` | Coding selects the bound capability ports; standard descriptions and ordering are Harness-owned. | Complete: Coding no longer owns a standard slash-command definition list. |
| Parsing and typed result adaptation for the admitted subset | `harness.session.command_pack` over existing session identity, export/import, operation, lifecycle, and navigation runtimes | Coding supplies ports and wraps the neutral mapping in `CommandExecutionResult`. | Complete: `coding.session.builtin_commands` is deleted. |
| Ordered composition and dispatch | existing `harness.session.SessionCommandRuntime` plus `harness.session.command_sources` | Coding binds extension runner, diagnostics mapping, result projection, and builtin source. | Complete: no second dispatcher or catalog is introduced; extension/resource source adapters have no Coding import. |
| Clipboard, tool/extension rendering, changelog, settings/model/terminal/hotkeys/quit/share | Coding or their already declared future owner | Product wording, rendering, model/auth/provider policy, and UI routes. | Not in Wave 3; no LOC is counted as migrated. |

Wave 3 closure probes:

- a fake Product executes every admitted command through public Harness ports
  with no Coding import;
- invalid invocations and unavailable existing capability groups return typed
  results before a Product port is called;
- standard, extension, and resource sources preserve current priority and
  dispatch order through the existing `SessionCommandRuntime`;
- Coding preserves its catalog and result fixtures after projecting the shared
  result, then deletes the admitted duplicate handlers;
- `harness.session.command_pack` has no Coding, provider/auth, transport, or
  UI import.

### Wave 4 First Slice: Product Transcript Lifecycle Store (Complete)

| Source region | Shared owner | Product injection or retained Coding owner | Deletion condition |
| --- | --- | --- | --- |
| removed `coding.runtime.agent_session_runtime._CodingSessionLifecycleStore` | `harness.session.ProductTranscriptSessionLifecycleStore` | Coding supplies transcript create/restore/fork/dispose ports, CWD restore validation, session construction, fork selection, lifecycle hooks, and extension/diagnostic behavior. | Complete: Harness owns the common transcript-to-runtime lifecycle adapter and releases a transcript when Product runtime construction fails. |
| proposed bootstrap transaction | existing `ConfigActivationRuntime` and capability/session runtimes | Coding retains activation callbacks, Product services, prompt/model/resource/tool policy, CWD/session-file acceptance, and final session construction. | Deferred: no second bootstrap engine is admitted while the existing activation runtime owns ordering and rollback. |

Wave 4 first-slice accounting: `coding.runtime.agent_session_runtime` is 1,187
to 1,158 LOC (-29); `harness.session.transcript_lifecycle` is 216 to 371 LOC
(+155). Tests and documentation do not count as migrated implementation.

Wave 4 first-slice probes:

- a fake Product creates and forks a runtime session through the shared store
  without importing Coding;
- failed Product runtime construction disposes the opened transcript;
- Coding lifecycle, bootstrap, and import-boundary regressions preserve CWD,
  fork, extension, and diagnostic behavior.

### Session Adapter Cull And RPC Lifecycle Port (Complete)

The requested public-facade and RPC audit confirms that most of the proposed
cutover already landed in earlier waves. Prompt, queue, abort, compaction, and
retry handlers already use `SessionOperationRuntime`; moving them again would
create a duplicate engine. The remaining lifecycle handlers now use explicit
Harness `SessionLifecycleOperationPorts`, while Channel continues to own JSONL
framing and Coding retains validation, error wording, compatibility fields, and
response projection.

| Source region | Actual change | Ownership result |
| --- | ---: | --- |
| `coding.session.agent_session` | 1,890 to 1,874 LOC (-16) | Removed only `abort`, `compact_session`, and bash state aliases that forwarded Harness methods. Coding compaction, bash, diagnostics, package, model, extension, and event behavior remains Product-owned. |
| `coding.mode.rpc_mode` | 2,739 to 2,758 LOC (+19) | Added explicit lifecycle port binding; no RPC capability was deleted. The increase is intentional wiring, not a migration reduction. |
| `harness.session.operations` | shared port/runtime contract | Owns neutral lifecycle callback dispatch for Product hosts. |

This wave's net Coding reduction is 0 after the explicit RPC binding is
included. The earlier 800--1,200 LOC projection is superseded by this audit;
future reduction must come from a separately proven handler or Product adapter
removal, not from reclassifying existing Harness calls.

The lifecycle port now also exposes `clone_session` explicitly. RPC hosts use
that capability when available; the Coding adapter keeps a fallback to the
existing fork-at-current-position operation for older runtime implementations.
This makes clone part of the neutral operation grammar without changing the
Coding wire contract.

### Session Tool, Bash, And Provider Collapse (Complete)

The standard command pack now owns `tools`, `extensions`, `copy`, and
`changelog` parsing/execution. Coding supplies tool/extension data, clipboard
implementation, changelog content, and the final Product result projection.

`ToolActivationProfile` owns default tool selection and new-tool activation.
`SessionToolRuntime` remains the live rebinding mechanism; Coding only supplies
its preferred order, builtin set, and activation policy.

`BashExecutionRuntime` now owns the native Harness command-execution surface.
The Coding `BashController` and its Pi-style `execute_pi_style` and
`record_pi_style_result` entry points were removed. Native extension `user_bash`
interception remains an injected Coding extension policy callback and receives
only the typed native result shape.

`ExtensionProviderRuntime` owns provider register/unregister/query lifecycle in
Harness. Coding retains only the AI-native provider configuration conversion;
provider registration, API source cleanup, and runtime lookup are shared.

### Session Composition, Bootstrap, Settings, And CLI Lifecycle (Complete)

The following implementation-only surfaces now have shared owners without
moving Coding content or command syntax:

| Source region | Shared owner | Coding retained |
| --- | --- | --- |
| `coding.runtime.agent_session_runtime` lifecycle forwarding | `harness.session.SessionLifecycleOperationAdapter` | CWD/session-file acceptance, fork policy, Coding hooks, diagnostics, and resource policy |
| `coding.bootstrap` resource activation ordering and contained diagnostics | `harness.bootstrap.ResourceBootstrapRuntime` and `BootstrapActivationRuntime` | Resource loader, extension factory, flags, prompt/tool rebuild, and Product diagnostics callbacks |
| removed `coding.control.settings_manager` and `coding.control.types` | `harness.config.agent.SettingsManager` and standard Agent settings records over the existing `SettingsRuntime` / `ScopedConfigRuntime` / `LayeredConfig` chain | Coding settings paths, command-backed value execution, `ModelRegistry`, and Product-only policy/presentation |
| `coding.cli.__main__` stream binding, output guard, and disposal fallback | `harness.host.product_host.ProductHostLifecycle` | Argument grammar, mode selection, Product startup policy, output format, and command handlers |

These are adapter collapses rather than new protocol layers. Harness and Channel
do not import Coding, and no RPC/CLI wire fields changed in this wave. The
lifecycle contract is verified with independent Harness/Channel fakes plus the
existing Coding settings and CLI regressions.

### Wave 6, Slice B: Generic Product CLI Surfaces (In Progress)

The detailed boundary is [Product CLI Lifecycle Boundary](product-cli-lifecycle-boundary.md).
This slice extracts only object-shape and lifecycle mechanisms. It does not move
Coding argument grammar, mode selection, package/work/method handlers, product
wording, or RPC schemas.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| repeated prompt/print/mode turn loops and TTY probing | `harness.host.product_host.ProductHostLifecycle` | Turn values, runner selection, output, and disposal candidates | Complete |
| prompt/stdin/file/image input resolution | `harness.host.prompt_input` | CLI argument grammar and product prompt policy | Complete |
| model listing normalization and metadata formatting | `harness.session.model_selection` | Preferred model candidates and persistence wording | Complete |
| command descriptor listing projection | `harness.commands.project_command_descriptor` | Descriptor source selection and JSON/TSV output | Complete |
| skill/plugin/session catalog listing projections | `harness.resources.*`, `harness.transcript.catalog` | Discovery, settings, query grammar, and output format | Complete |
| diagnostic record/error/summary serialization | `harness.diagnostics.serialization` | Existing call sites only; camelCase output retained | Complete |
| package catalog and materialization record projection | `harness.resources.packages.projection` | Coding retains resource discovery, materializer policy, and command selection | Complete |

Slice B accounting (implementation only): `coding.cli.__main__` is 3,358 to
2,941 LOC (-417); the former Coding diagnostics serializer is deleted (83 LOC);
the shared mechanisms add approximately 890 LOC across Channel/Harness. The
deletion/addition ratio is approximately 0.71. Tests and documentation are not
counted. The lower ratio is intentional: this slice establishes reusable
contracts and does not delete product handlers or CLI grammar.

### Slice B implementation follow-up: standard operation leaves

The following additional leaves are now shared without changing Coding's
argument grammar, operation order, security policy, or output fields:

| Coding source mechanism | Shared owner | Product injection or retained Coding owner | Status |
| --- | --- | --- | --- |
| resource enable/disable and plugin-source toggle mutation | `harness.cli.resource_toggles` | Coding supplies `PackageSecurityPolicy`, remote-source labeling, and diagnostic capture | Complete |
| asynchronous package install/materialize/update/remove/uninstall orchestration | `harness.cli.package_lifecycle` | Coding supplies install-source policy and JSONL serialization | Complete |
| session command invocation, slash normalization, result extraction, and raw/JSON formatting | `harness.cli.command_execution` | Coding supplies CLI argument values and stream/error projection | Complete |
| new/restore/continue/fork session selection | `harness.cli.session_resolution` over `harness.session` lifecycle ports | Coding supplies parsed CLI values and product runtime | Complete |
| `provider/model`, `provider:endpoint:model`, and explicit provider+model parsing | `loushang.ai.model.parse_model_selection_reference` | Coding retains preferred model candidates and persistence wording | Complete |
| extension flag discovery and application | `harness.cli.extension_flags` | Coding retains second-pass argparse typing and help text | Complete |
| Method catalog normalization, lookup, plan projection, and text/JSON formatting | `harness.cli.method_listing` | Coding supplies discovery and `MethodCompiler(domain="coding")` callbacks | Complete |
| Work event-log inspection, tailing, plan projection, and text/JSON formatting | `loushang.work.cli` | Coding retains CLI flag grammar and Work runtime binding | Complete |

After these leaves, the implementation-only `coding.cli.__main__` count is
1,994 lines (2,941 at the start of this follow-up). The remaining CLI code is
deliberately not counted as shared yet: Method/Work preparation, Coding
resource discovery and package materialization policy, mode selection, prompt
policy, approval/tool setup, and final product/TUI/RPC projection still carry
product semantics or require an explicit owner decision.

The shared operation modules have independent fake-capability probes under
`tests/harness/cli`. They return typed results and leave wire formatting to the
Product host; no second session, package, or transport engine is introduced.

Closure probes:

- CLI/model/prompt/channel regressions preserve existing output and lifecycle
  behavior;
- Harness/Channel modules have no Coding import;
- malformed resource and command objects remain best-effort and are skipped as
  before;
- diagnostic JSON retains the existing field names; any snake_case protocol
  change requires explicit approval in a later contract migration.

### Wave 6, Slice C: Shared Workspace Policy Engine (Complete)

`coding.policy.engine` was an implementation duplicate over the existing
Harness policy subjects, matchers, command normalization, and rule evaluator.
The evaluator now lives in `harness.policy_engine.PolicyEngine` and accepts a
product rule-id namespace plus product-supplied rule values. The later
Policy/Approval extinction slice removed the temporary Coding binding; Coding
now imports the Harness evaluator directly.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| removed `coding.policy.engine` rule assembly and action/tool evaluation | `harness.policy_engine.PolicyEngine` | Policy settings only | Complete |

Slice C accounting: the Coding implementation shrank from 298 to 17 LOC
(-281); Harness gained the shared implementation at 300 LOC. The shared module
has no Product imports. Coding policy and workspace-tool regressions remain
covered by the existing tests, with independent Harness probes for non-Coding
rule namespaces.

The same slice also collapsed the callback-backed approval lifecycle. The
`ApprovalBroker` wrapper, presenter lifecycle, timeout/cancellation behavior,
and result correlation now live in `harness.approval.InteractiveApprovalResolver`.
The later extinction slice also moved the `action`/`risk` projection and
standard project/user rule-store binding into Harness, then deleted the thin
Coding subclass:

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| removed `coding.policy.approval.InteractiveApprovalResolver` | `harness.approval.InteractiveApprovalResolver` | Presenter binding only | Complete |

Approval accounting: Coding shrank from 135 to 56 LOC (-79); Harness gained
104 LOC of parameterized lifecycle and presenter code. Existing Coding approval
tests and independent Harness policy probes pass; the shared approval module has
no Product imports.

Package source trust evaluation is also now a shared resource capability. The
`PackageSecurityPolicy` and `PackageSourceSecurityReport` types moved to
`harness.resources.packages.security`; Coding imports them directly while it
continues to choose when a package operation asks for a security decision.
This keeps trusted-host/source configuration injectable for Design, PPT, and
other Products without changing the existing package wire shape.

### Wave 6, Slice D: Session Observability Binding (Complete)

The repeated CLI/session observability binding now lives in
`harness.diagnostics.observability_runtime`. It owns scope parsing, explicit or
environment-derived output paths, startup/session labels, sink binding, and
debug enable/disable lifecycle. Coding keeps only its source classification
(`config` problems are presented as `model`); the historic wrapper module has
now been deleted.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| removed `coding.observability` session/startup context and debug file lifecycle | `harness.diagnostics.observability_runtime` | Coding diagnostic source mapping | Complete |

Slice D initially reduced the adapter from 157 to 109 LOC; the top-level
collapse later deleted the remaining 109 LOC and bound CLI/TUI directly to the
shared context. No debug/trace environment variables or file naming behavior
changed.

### Wave 6, Slice E: Top-Level Session Bootstrap Leaves (Complete)

Several top-level Coding helpers were implementation-only session mechanics,
despite being located beside the Product bootstrap entry point. They now live
under the Harness session package and accept only neutral values or existing
Harness ports:

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| preferred model detail/selection matching and candidate ordering | `harness.session.model_preferences` | `PREFERRED_CODING_MODELS` and the settings persistence binding | Complete |
| cwd/project/resource consistency audit | `harness.session.cwd_audit` | Coding settings/resource object extraction and diagnostic capture | Complete |
| no-tools normalization and initial tool activation selection | `harness.session.bootstrap_utils` | Product bootstrap argument wiring | Complete |
| resource prompt override lookup and fragment assembly | `harness.session.bootstrap_utils` | Product default prompt and resource content | Complete |
| scoped model/thinking suffix parsing | `harness.session.bootstrap_utils` | Product model registry lookup and payload assembly | Complete |

This is a leaf extraction, not a second bootstrap runtime. Harness does not
construct Coding services or sessions; it only exposes reusable value-level
operations. Coding's public import names remain available while their
implementation ownership moves to Harness.

Slice E accounting: Coding shrank by approximately 178 implementation lines
(`bootstrap.py` 1,381→1,315 and `model_selection.py` 137→67 in this slice),
while Harness gained approximately 312 lines plus focused Harness probes.
Existing Coding model/bootstrap behavior is unchanged; the new Harness tests
exercise the same operations without importing Coding.

### Wave 7, Slice A: Agent Bootstrap Construction Collapse (Complete)

The Agent construction boundary is now explicit in `harness.session.bootstrap`.
Harness owns the neutral construction request/result contracts and the shared
pipeline that:

1. builds the initial Agent state and constructor kwargs;
2. creates a workspace registry when requested;
3. registers Product-provided extension tools;
4. records extension diagnostics through a Product callback;
5. resolves initial active tools; and
6. invokes the Product session factory.

Coding retains the service factories, resource/extension policies, model
resolution, prompt defaults, image policy, approval binding, and the concrete
`AgentSession` constructor. No Coding type is imported by the Harness module,
and no second session runtime was introduced.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| bootstrap service/result data contracts | `harness.session.bootstrap` | Product-specific service types supplied as generic values | Complete |
| Agent initial state and constructor kwargs | `AgentBootstrapRuntime` | Agent factory selection and Product session factory | Complete |
| tool registry/extension contribution/active-tool pipeline | `AgentSessionConstructionRuntime` | Extension pack IDs, diagnostics normalization, and tool policy | Complete |

Slice A accounting: `coding/bootstrap.py` is approximately 1,315→1,277 LOC;
the shared construction contracts/runtime add approximately 240 LOC. The
reduction is intentionally limited to the construction boundary: the
remaining bootstrap code is activation policy and Product service wiring,
which cannot move without changing ownership or duplicating the existing
resource activation runtime. Independent Harness construction probes and the
Coding bootstrap/session regression suite pass.

### Wave 7, Slice B: Model and Provider Resolution Collapse (Complete)

Model catalog mechanics are now owned by `harness.model_catalog`. The shared
catalog wraps the existing AI registry types without changing `loushang.ai`:
layered builtin/user/project loading, provider/model registration, reference
resolution, endpoint selection, and model construction are all reusable by
other Products. Coding keeps only the historical import name as a zero-logic
alias and continues to provide its preferred model list and Product defaults.

Session bootstrap resolution also moved to explicit Harness operations in
`harness.session.model_resolution`. It provides default-model fallback,
stable failure classification, startup diagnostic recording, and scoped
model/thinking pattern projection through typed callbacks. No runtime
capability is discovered through `getattr`; Products bind the catalog and
diagnostics ports explicitly.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| removed `coding.control.model_registry` registry/reload/resolve/build implementation and import alias | `harness.model_catalog` | no Coding implementation or submodule facade | Complete |
| bootstrap default-model fallback and failure diagnostics | `harness.session.model_resolution` | model preference/default selection | Complete |
| enabled model/thinking pattern parsing and scoped payload assembly | `harness.session.model_resolution` | Product settings wiring | Complete |

Slice B originally reduced `coding/control/model_registry.py` from 176 to 5
LOC; Wave 7 Slice W removes the remaining alias. `coding/bootstrap.py` moved
from approximately 1,277 to 1,178 LOC during this slice. Harness gained the
shared catalog and resolution helpers, with no changes to `loushang.ai.model`
and no external wire behavior changes. Focused Coding regressions and
independent Harness model-resolution probes pass.

### Wave 7, Slice C: Session Public Adapter Audit (Already Complete)

This requested slice is already present in the integration baseline and must
not be repeated as a second migration. Commits `7c8fb1e1` and `808767a0` moved
the common session facade, inspection, retry, transcript export, tool,
extension, lifecycle, and maintenance coordination to Harness. The current
`coding.session.AgentSession` is 522 LOC, down from approximately 1,732 LOC;
its remaining code is composition wiring and Product behavior.

| Remaining AgentSession region | Owner | Classification |
| --- | --- | --- |
| model/provider binding and preferred selection | Coding + Harness/AI ports | Product policy binding |
| resource/package/tool contribution wiring | Coding resource policy + Harness runtimes | Product adapter |
| compaction and branch-summary callbacks | Coding | Product prompt/executor semantics |
| extension provider/footer/replacement callbacks | Coding + Harness extension ports | Product API and presentation |
| context-usage camelCase projection | Coding public projection | Transform, not a pure forwarder |

The audit found no remaining 600–900 LOC block that is both pure forwarding and
safe to delete. Removing these methods would either change the public Coding
projection or move Coding-specific prompt, provider, footer, cwd, package, or
extension semantics into Harness. Therefore this slice has **0 additional
LOC** and is accepted by existing session architecture gates rather than being
artificially expanded. The next large reduction should target Settings
Composition or CLI Product Host, where shared mechanisms still have separate
owners.

### Wave 7, Slice D: Model Selection TUI Runtime (Complete)

The model-selection UI flow was a second copy of generic terminal interaction:
filtering, completion projection, palette resolution, cancellation, ambiguity
presentation, and the final apply-result message. Those operations now live in
`harnesstui.selection.runtime` behind the explicit
`ModelSelectionViewPort` contract. The port supplies normalized
`ModelChoice` values, the current value, and an apply callback; it does not
expose a Coding session or discover capabilities dynamically.

Harness owns the AI/model-value projection and standard session acquisition;
HarnessTUI owns endpoint/detail view projection over its existing selection
catalog and interaction runtime. Coding retains preferred-model policy,
settings persistence, and persistence-warning wording. Its module contains
only those Product bindings; no generic interaction, acquisition, or selection
runtime is duplicated there.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| model list filtering, completion, palette resolution and result presentation | `harnesstui.selection.runtime` | Product persistence warning | Complete |
| model-selection apply/persistence boundary | `ModelSelectionViewPort` | `apply_model_selection` and warning policy | Complete |
| model details, endpoint identity and current-session projection | `harness.session.model_selection` and `harnesstui.selection.binding` | preferred-model policy | Complete |

Slice D final accounting: `coding/model_selection_tui.py` shrank from 279 to
38 LOC (-241), including 127 LOC in this follow-on. Harness owns the AI-aware
session data contract; HarnessTUI converts those records into view models by
extending the existing selection binding rather than creating another runtime.
HarnessTUI has no direct AI import, no shared module imports Coding, and
independent fake-Product probes cover acquisition, endpoint identity,
completion, and application.

### Wave 7, Slice E: CLI Standard Operation Host (Complete)

Coding previously repeated the same capability call, error projection, output
write, and early-return loop around shared CLI leaf operations. The reusable
host behavior now lives in `harness.cli.host_operations`, while
`CliOperationSequence` owns ordered sync/async early-exit dispatch.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| session catalog query validation, projection and output | `harness.cli.host_operations` | query values and selected format | Complete |
| export, model/command/diagnostic/skill/plugin list execution | `harness.cli.host_operations` | operation enablement and declared order | Complete |
| resource toggle and package lifecycle CLI result/error writing | `harness.cli.host_operations` | package security and diagnostic callbacks | Complete |
| command invocation CLI result/error writing | `harness.cli.host_operations` | command arguments and result-format choice | Complete |
| first-handled standard operation dispatch | `harness.cli.CliOperationSequence` | Product stage selection, insertion and order | Complete |
| TTY selection, output guard, launch conflicts and runtime-mode projection | `harness.cli.CliLaunchPlan` | `CliArgs` to plan projection | Complete |

Coding still owns Method visibility, package catalog fallback, diagnostics
archive export, argument grammar, bootstrap policy, Work binding, and final
mode selection. These are not hidden behind a compatibility facade.

Slice E accounting (production implementation only):
`coding/cli/__main__.py` changed from 1,994 to 1,725 LOC. The diff removes 575
Coding lines and adds 306 lines of request/stage/plan declaration, for a net
Coding reduction of 269 LOC. Harness adds approximately 601 production lines
across the operation host, launch plan, sequence runtime, and public exports,
giving a gross deleted/shared-added ratio of approximately 0.96. Tests and documentation are
excluded from the ratio. The detailed boundary is documented in
`cli-product-host-collapse.md`; the complete Coding CLI and independent Harness
CLI suites remain green with unchanged operation precedence, output, and exit
codes.

### Wave 7, Slice F: Standard Agent Settings Profile (Complete)

The former Coding settings manager already delegated its storage and
transaction mechanics to `SettingsRuntime`, `ScopedConfigRuntime`, and
`LayeredConfig`, but Coding still owned every standard Agent setting record,
field codec, getter, setter, and collection mutation. These reusable surfaces
now live in the optional `harness.config.agent` profile. The profile composes
the existing config stack and does not introduce another settings engine.

| Source region | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| standard Agent settings records and defaults | `harness.config.agent.types` | Product-only additions and overlays | Complete |
| standard field codecs, validation, getters, setters, and mutations | `harness.config.agent.SettingsManager` | none | Complete |
| layered load/merge/persist/reload, snapshots, listeners, issue drain | existing `harness.config` runtimes | none | Reused, not duplicated |
| settings paths and command-backed value execution | Coding | `.loushang/coding` path and shell-runner policy | Retained |
| model catalog policy | Coding/AI | preferred models and Product selection policy | Retained |

The neutral config core remains free of Agent and AI imports. Only the explicit
`config.agent` profile admits stable Agent/AI value types, and the entire config
package remains free of Coding imports. Production Coding consumers now import
the shared settings owner directly; `coding.control` retains only its public
export identity alongside Product-owned control services.

Slice F accounting (production implementation only): the deleted Coding
implementation was 1,580 LOC (`settings_manager.py` 1,403 plus `types.py` 177).
The shared profile contains 1,640 LOC including its 59-line public export, a
gross deleted/shared-added ratio of 0.96. Coding Python fell from 15,737 to
14,157 LOC. The behavior suite moved to the shared owner and the broader config,
Coding control/package, and architecture regression completed with 211 passing
tests.

### Wave 7, Slice G: Agent Session Lifecycle Binding Collapse (Complete)

The remaining Coding runtime still repeated standard Agent Product effects
around the already shared `ProductSessionRuntime`. Those effects now extend
their existing owners; no `AgentProductSessionRuntime` or second lifecycle
engine was introduced.

| Source region | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| after-commit index/replacement callbacks and restore/import failure routing | `ProductSessionRuntime` | none | Complete |
| standard transcript create/open/fork/dispose/rename/delete binding | `ProductTranscriptSessionBinding` | `SessionManager` selection | Complete |
| approval, runtime-host, extension switch/fork/start/shutdown, and disposal hooks | `AgentSessionAdapterMixin` lifecycle-hook builder | none | Complete |
| session diagnostic capture with structured details | `SessionDiagnosticsRuntime` | diagnostic service injection | Complete |
| Agent message `at`/`before` fork target and selected-text projection | `ProductSessionRuntime` Agent transcript helper | Coding default position | Complete |
| missing cwd public exception | Harness validation plus Coding translator | Coding public error type | Retained |

Slice G accounting (production implementation only):
`coding/runtime/agent_session_runtime.py` shrank from 639 to 229 LOC (-410,
64% source compression). Total Coding Python fell from 14,156 to 13,746 LOC.
The shared changes extend existing session, transcript, diagnostics, and Agent
adapter modules rather than adding a synonymous runtime. Independent Harness
bindings and the complete Coding Agent-session characterization suite preserve
fork, cwd, import, extension ordering, replacement, index, and diagnostic
behavior.

### Wave 7, Slice H: Bootstrap Activation Collapse (Complete)

The remaining Coding bootstrap repeated the standard Agent activation graph
and several leaf bindings. The graph now composes the existing Harness
activation, resource, package, diagnostics, transcript, and model-catalog
owners. No second bootstrap, session, resource, or lifecycle engine was added.
The detailed boundary is
[Bootstrap Activation Collapse Boundary](bootstrap-activation-collapse-boundary.md).

| Source region | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| seven-stage Agent startup ordering and first-failure propagation | `BootstrapActivationRuntime` plus `standard_agent_session_activation_plan` | seven Product effect callbacks | Complete |
| standard resource/extension/diagnostic port binding | `create_standard_resource_bootstrap_runtime` over `ResourceBootstrapRuntime` | Coding extension runtime factory | Complete |
| extension flag application and tool registration | `harness.extensions.ExtensionRuntime` and `harness.bootstrap` | Coding loader/policy and legacy pack identifiers | Complete |
| package sources, roots, install root, lock diagnostics | existing `harness.resources.packages` components | Coding package security policy | Complete |
| startup checks and cwd audit recording | existing `harness.diagnostics` and `harness.session.cwd_audit` | Coding executable identity check | Complete |
| prompt/model/context bootstrap leaves | existing `harness.session` and `harness.transcript` | Coding default prompt, model preference, image message | Complete |
| project model-catalog reload | `ModelCatalog.reload_if_project_layer` | `.loushang/models` path convention | Complete |

Slice H accounting (production implementation only):
`coding/bootstrap.py` shrank from 1,178 to 773 LOC and
`coding/session/package_controller.py` from 232 to 205 LOC, a total Coding
reduction of 432 LOC. The remaining bootstrap code is the public Product
factory surface, Coding service/default construction, seven injected effects,
and concrete `AgentSession`/runtime binding. Private helper tests were moved to
the canonical Harness owner rather than preserving a Coding facade.

### Wave 7, Slice I: CLI Application Composition (Complete)

The remaining Coding CLI still copied the standard Agent argument value object,
extension bootstrap parser, two-pass application phase order, standard
operation queue, and repeated prepared-turn lifecycle arguments. These
mechanisms now extend the existing `harness.cli` package; no parser, session
runtime, or transport was duplicated.

| Source mechanism | Shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| standard Agent CLI dataclass and argparse namespace projection | `harness.cli.AgentCliArgs` | Method/Work additive fields | Complete |
| standard package/diagnostics/observability argv normalization and extension flag bootstrap parsing | `harness.cli.agent_args` and `harness.cli.extension_flags` | Method subcommand aliases | Complete |
| bootstrap parse, validation, guarded runtime/session creation, final parse, operations, and host phase order | `harness.cli.CliApplicationRuntime` | Product services, tool policy, observability context, and runner bindings | Complete |
| standard export/catalog/package/command/model precedence | `harness.cli.run_standard_cli_operations` | Method and package-catalog stage insertions | Complete |
| first/last prepared-turn images, follow-ups, and disposal flags | `harness.cli.run_keyword_cli_turns` | Method/Work prepared-turn metadata and Product runners | Complete |
| standard launch intent projection | `harness.cli.agent_cli_launch_plan` | Method/Work launch overlay | Complete |
| standard resource/session/catalog request projection and ephemeral bootstrap policy | existing `harness.cli` capability modules | Method catalog insertion and package security callbacks | Complete |
| resource-loader flags, session path, image policy, and offline activation | `harness.cli.agent_args` | Coding service factory and resource package content | Complete |
| tool settings to policy/approval projection | `harness.tools.workspace.factory` | Coding rule-id policy factory and interactive approval presentation | Complete |
| post-resolution extension/name/model/thinking configuration | `harness.cli.session_configuration` | model persistence policy and warning wording | Complete |
| fake workflow pre-runtime exit | `harness.scenario.cli` | Coding workflow runner and CLI flag | Complete |

Production accounting: `coding/cli` changed from 2,441 to 1,602 physical
Python LOC (-839 net). The cumulative patch deletes 1,525 Coding
implementation lines and adds 686 Coding binding lines. Shared production
additions are approximately 1,779 lines, for a gross
deletion/shared-addition ratio of 0.86. The larger shared addition establishes
typed, independently tested contracts rather than moving the old function
intact. Channel remains the owner of streams, output protection, turn ordering,
and disposal.

### Wave 7, Slice J: HarnessTUI Conversation Adapter Extinction (Complete)

Reusable conversation presentation and routing mechanics no longer have a
second implementation under Coding. This slice extends four existing
HarnessTUI owners and deletes the Coding event facade; it does not add a new
projector, controller, runtime, application, queue adapter, or package.
The detailed boundary is
[Coding Conversation Adapter Extinction](coding-conversation-adapter-extinction.md).

| Source mechanism | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| normalized Session event routing and message/tool lifecycle | `harnesstui.conversation.projection` | visibility flags and Agent tool-result binding | Complete |
| queue-source normalization | `harnesstui.conversation.runtime_view` | explicit Session queue sources | Reused |
| mapping-shaped tool event/result projection and standard workspace presentation policy | `harnesstui.conversation.tool_transcript` | `AgentToolResult` conversion, optional Product renderer and final command-label policy | Complete |
| structural Agent message and command-history projection | `harnesstui.conversation.history` | persisted-session acquisition, kind dispositions and tool binding | Complete |
| abort-settling/follow-up/steer/local/dispatch decision order | `harnesstui.conversation.host` | Coding intents, local-action declarations, command catalog and copy | Complete |
| Plain/Screen effects and rendering | existing `plain_target`, `screen_target`, `screen_app` and TUI transcript engine | Product title, glyphs, status copy and theme | Reused |

Production accounting: Coding Python changed from 12,475 to 11,969 physical
LOC (-506 net). The affected Coding implementation changed from 1,369 to 863
LOC. The four existing HarnessTUI owner files changed from 1,106 to 1,715 LOC
(+609), giving a net Coding-reduction/shared-addition ratio of 0.83. No
compatibility facade replaces `coding.presentation.tui.events`, and
`CodingTuiProfile` is removed rather than re-exported. Independent HarnessTUI
tests cover structural event, history, tool and routing behavior; architecture
gates keep HarnessTUI free of Coding, Agent and AI imports.

### Wave 7, Slice K: Agent Product Host Binding Collapse (Complete)

The remaining Coding host layer still coordinated standard TUI/RPC/Channel/
workflow precedence, repeated Agent prompt failure/disposal logic, translated
plain-host metadata into `SessionWorkTurn`, and owned the Work-to-Channel
operation loop. This slice extends the existing CLI, HarnessTUI, Work, and
Channel-facing owners; it does not add another host, Work runtime, event
projector, or transport.

| Source mechanism | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| Agent CLI mode precedence and prepared-turn lifecycle | `harness.cli.run_agent_cli_host` plus `CliApplicationRuntime` and `run_keyword_cli_turns` | input/Method preparation and runner binding | Complete |
| standard Agent plain JSON event projection | `harnesstui.conversation.agent_binding` plus existing `PlainHost` | plain renderer selection | Complete |
| prompt and fixed-plan subscribe/failure/worked/dispose lifecycle | existing `plain_prompt_host` with Agent binding helpers | model preparation and Coding Work factory | Complete |
| host metadata to session Work turns | `work.session.SessionWorkHostPort` over `SessionWorkRuntime` | Coding Work profile | Complete |
| Work operation acceptance, cancellation and Channel delivery | `channel.adapters.session_work.SessionWorkChannelPort` over `ChannelHost` | `coding` domain and `SubmitCodingTurn` vocabulary | Complete |
| standard Agent runtime views to Channel envelopes | `harness.host.AgentRuntimeChannelProjection` | event-view selection | Complete |

Production accounting: `src/loushang/coding` changed from 9,519 to 9,071
physical Python LOC (-448). The affected files changed as follows:

- `coding/cli/__main__.py`: 1,332 to 1,239 LOC (-93);
- `coding/mode/channel_mode.py`: 310 to 105 LOC (-205);
- `coding/mode/print_mode.py`: 254 to 172 LOC (-82);
- `coding/prompt_command.py`: 251 to 183 LOC (-68).

The patch deletes 617 Coding implementation lines and adds 165 Product binding
lines. Shared additions are independently usable: contract probes bind a
Research Work/Channel profile and a Product-neutral CLI host without importing
Coding. Existing Coding CLI, prompt, print, RPC, and Channel snapshots remain
unchanged.

### Wave 7, Slice L: Agent Product Construction Final Collapse (Complete)

This slice completes five related owner switches without introducing a second
session, package, Method, Work, CLI, or presentation engine:

| Source mechanism | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| standard Agent Product session construction | `harness.session.AgentProductSession` over `SessionComposition`, `SessionFacade`, transcript, retry, compaction, diagnostics, commands, packages, and extensions | capability profile, summary executors, prompt/content, changelog, clipboard, footer, and package summary | Complete |
| session package operations and projected catalog fallback | `harness.resources.packages.session`, `catalog`, and `projection` | built-in package/content profile and package security policy | Complete |
| standard session command source composition | `harness.session.StandardSessionCommandController` | no duplicate Coding controller | Complete |
| plain conversation app, resume hint, and Agent session history | existing `harnesstui.conversation` app/binding/resume/history components | title/copy, command prefix, Product session loader, and renderer | Complete |
| Method domain discovery/select/compile/project/prompt preparation | `method.MethodDomainRuntime` over the existing Method components | `domain="coding"` and guidance template | Complete |
| Agent RuntimeEvent to Work facts and session Work factory | `work.agent_projection` plus existing `SessionWorkRuntime` | `CODING_WORK_PROFILE` | Complete |
| prepared domain turn to CLI/Work turn projection, prompt error boundary, package listing, Work-log inspection | existing `harness.cli` and `work` CLI/session components | argument mapping, Product callbacks, and wording | Complete |

Deleted canonical Coding modules:

- `coding.session.command_controller`;
- `coding.session.package_controller`;
- `coding.package_projection`;
- `coding.presentation.resume`;
- `coding.domain.types`.

Production accounting: `src/loushang/coding` changed from 9,071 to 7,755
physical Python LOC (-1,316) in Slice L. From the Slice K pre-change baseline
of 9,519 LOC, the combined Agent Product host/construction work reduced Coding
by 1,764 LOC. Notable final sizes are:

- `coding.session.agent_session`: 140 LOC, a Product binding over
  `AgentProductSession`;
- `coding.cli.__main__`: 1,145 LOC, with standard application/host/input/listing
  mechanics delegated to shared owners;
- `coding.ui.plain_app`: 103 LOC, a Product binding over the HarnessTUI plain
  app;
- `coding.domain.app` plus `coding.domain.work`: 94 LOC, containing only
  Product profiles and thin bindings.

Independent Research/Design-style contract probes exercise the Method runtime,
prepared-turn CLI projection, package listing, Work turn projection, and Work/
Channel profiles without importing Coding. Architecture gates allow the
optional Agent Product session profile to depend on public Agent/AI contracts
while continuing to prohibit all shared owners from importing Coding.

### Wave 7, Slice M: CLI Product Binding Final Collapse (Complete)

This slice removes the remaining standard Agent CLI bootstrap and session-host
mechanics from Coding while extending the existing `harness.cli` application,
operation, prompt-input, and host components. It does not add another parser,
session runtime, transport, Work runtime, or presentation engine.

| Source mechanism | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| service/session-path preparation, resource toggles, tool and approval binding | `AgentCliStatePreparationPorts` plus existing resource/session/tool owners | Product service, tool-pack, and policy factories | Complete |
| extension-aware help bootstrap | the same state ports plus `collect_agent_cli_help_extension_flags` | Product parser and help formatter | Complete |
| help, version, and source-info early exits | `AgentCliEarlyOperationPorts` and `run_agent_cli_early_operation` | Product source identity and wording | Complete |
| runtime-builder invocation | `invoke_agent_cli_runtime_builder` over `invoke_cli_builder` | Product runtime factory | Complete |
| standard session listing and resolution | `run_agent_cli_session_listing` and `resolve_agent_cli_session` over the existing request/runtime functions | no duplicate Coding wrappers | Complete |
| prompt input and tool selection | `resolve_agent_prompt_input` and `agent_tool_selection` | Product domain-turn preparation | Complete |
| TTY/mode/Work/observability host binding | `AgentCliSessionHostBinding` over `run_agent_cli_host` | Coding Work profile and final runner callbacks | Complete |
| diagnostic archive and Work log leaf operations | existing Harness diagnostics and Work engines with shared CLI bindings | Product paths, diagnostics source, and error wording | Complete |

Production accounting: `src/loushang/coding/cli/__main__.py` changed from 1,145
to 810 physical Python LOC (-335, 29.3%). Because this was the only Coding
production file changed by Slice M, total `src/loushang/coding` changed from
7,755 to 7,420 LOC (-335). The deleted code consisted of private state,
bootstrap, help, early-operation, runtime-builder, prompt-input, session,
diagnostic, and Work-log wrappers; Product arguments, operation ordering,
runner selection, output contracts, and error wording remain intact.

Shared contract tests bind Research-style state preparation and session hosts
without Coding imports. Coding CLI regression tests preserve two-pass extension
flags, session resolution, model/thinking configuration, output selection,
diagnostic export, Work logs, and exit behavior. Architecture gates verify
that Harness CLI continues to avoid Coding, Method, Work, and TUI imports.

### Wave 7, Slice N: Product Host And Leaf Extinction (Complete)

This slice completes the owner switch after the CLI binding collapse. It
removes the Coding mode namespace, reuses the existing Agent Product
construction/session ports, adds a HarnessTUI application binding over the
existing screen/plain runners, and moves reusable leaf services to their
canonical owners. It does not add a second host, session runtime, transcript,
scenario engine, footer model, or transport.

| Source mechanism | Existing shared owner | Coding retained | Status |
| --- | --- | --- | --- |
| RPC/plain/Channel mode facades | `harness.host.rpc`, `harnesstui.conversation`, and `channel.adapters` | Product runner callbacks, Work profile, renderer, and diagnostics | Removed |
| standard Agent Product configuration and construction | `harness.session.AgentProductConstructionRuntime` over existing configuration, prompt, model, tool, capability, and session construction runtimes | Coding prompt, pack IDs, image policy, and concrete session factory | Complete |
| Agent Product session runtime port assembly | `harness.session.build_agent_product_session_runtime_ports` over existing lifecycle, transcript, fork, and Product session runtimes | Coding store/profile binding and diagnostic mapping | Complete |
| screen/plain Agent application binding | `harnesstui.conversation.AgentScreenConversationApplicationBinding` and `AgentPlainConversationApplicationBinding` | screen app, surfaces, Product controller/action host, renderer, completion, copy, theme, and policy | Complete |
| session footer state and Git watcher | `harness.session.footer` | no Coding facade | Complete |
| version-check engine | `harness.cli.version_check` | Loushang endpoint, user agent, offline variables, and named Product entrypoint | Complete |
| scenario discovery/report/CLI lifecycle | existing `harness.scenario` | model readiness and injected `ExecService` shell policy | Complete |

Production accounting: `src/loushang/coding` changed from 7,420 to 5,986
physical Python LOC (-1,434, 19.3%). Notable reductions are:

- the complete `coding.mode` namespace is deleted;
- `coding.bootstrap` is 505 LOC and delegates construction to the shared
  runtime;
- `coding.runtime.agent_session_runtime` is 148 LOC and delegates standard
  port construction;
- `coding.ui.mode` is 220 LOC and contains Product UI composition rather than
  Agent history/status/queue wiring;
- the 231-line Coding footer implementation is removed;
- `coding.platform.version_check` is a 45-line Product profile;
- `coding.workflow` is a 69-line Product adapter and no longer owns discovery,
  reporting, or scenario lifecycle.

Independent Harness, HarnessTUI, Work, Method, and scenario contract tests bind
non-Coding products to each shared owner. Architecture gates prohibit shared
owners from importing Coding and prohibit Harness scenario code from starting
a shell process.

### Wave 7, Slice O: Agent Extension Profile Extinction (Complete)

This slice moves the remaining standard Agent extension API, permission
profile, loader selection, and runner selection into the existing
`harness.extensions.agent` profile. It reuses the neutral
`harness.extensions.loader`, `harness.extensions.runner`, runtime binding
records, routing, lifecycle, and hook components; no second extension engine,
event bus, or Product session runtime is introduced.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| Agent session/model/message Extension API | `harness.extensions.agent.api` over `ExtensionContributionAPI` and injected runtime bindings | provider implementation, credentials, preferred-model defaults | Complete |
| Agent permission defaults | `harness.extensions.agent.policy` | optional Product/OEM resolver replacement | Complete |
| Agent loader/runner selection | `harness.extensions.agent.loader` and `.runner` over the existing neutral core | live Product binding callbacks and final UI/transport projection | Complete |
| `coding.extensions` facade and implementation | no replacement facade | none | Removed |

Production accounting: `src/loushang/coding` changed from 5,986 to 5,640
physical Python LOC (-346, 5.8%). The deleted 346 lines are the complete former
Coding extension package; all behavior is now exercised through the canonical
Agent profile. A non-Coding contract probe loads a Research-style extension
through that profile, and architecture gates prohibit the profile from
importing Coding, Channel, Work, Method, TUI, or Harness Session.

### Wave 7, Slice P: Shared Leaf Convergence (Complete)

This slice removes small but canonical Coding owners only where an existing
shared component can absorb the behavior or a reusable binding is missing. It
does not introduce another transcript, command, config, event, package, or TUI
engine.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| Agent tool-call resource evidence attached to compaction and branch summaries | `harness.transcript.summarization` over the existing `SummaryResourceOperations` model | tool-name, operation, detail-key, tag, and exclusion profile | Complete |
| local plus session command catalog binding for conversation hosts | `harnesstui.commands.catalog` over the existing `harness.commands.MixedCommandCatalog` | session command provider and local action handlers | Complete |
| changelog discovery, parsing, formatting, and standard session-command payload | `harness.session.changelog` | optional filename and entry-limit profile | Complete |
| command-backed config values | neutral injected runner in `harness.config.values`, with explicit local-shell adapter in `harness.config.subprocess_values` | optional Product/OEM runner selection | Complete |
| transcript recording/cancellation policy | existing `harness.events.recording_policy` | no Coding facade | Complete |
| package-source security policy | existing `harness.resources.packages.security` | policy construction and Product trust inputs | Complete |

Deleted canonical Coding modules:

- `coding.commands` and its 127-line catalog;
- `coding.control.config_value`;
- `coding.event.presentation_policy`;
- `coding.platform.changelog`;
- `coding.policy.package_security`.

Production accounting: `src/loushang/coding` changed from 5,641 to 5,272
physical Python LOC (-369, 6.5%). The patch deletes 436 Coding lines and adds
67 direct Product bindings, so 84.6% of the gross deletion remains as net
reduction.
Shared production code grows by 589 lines, including independent Design-style
summary-resource and conversation-command contracts. The higher shared cost is
intentional public capability rather than a relocated Coding implementation:
the new profiles cover arbitrary resource operations, command sources,
changelog names, and config runners without importing Coding.

Architecture gates require the removed Coding modules to remain absent, keep
the neutral config resolver free of subprocess ownership, and keep lightweight
HarnessTUI interaction imports free of Harness, Agent, AI, and Coding package
side effects. Coding compaction, command completion, changelog, event,
package-security, AgentSession, and TUI behavior remain covered by their
existing regressions.

### Wave 7, Slice Q: Reusable Product Binding Cleanup (Complete)

This slice revisits small Product bindings only where the implementation was a
reusable mechanism. Existing factories, registries, loaders, application
bindings, and lifecycle runtimes remain the execution owners; no parallel tool,
resource, approval, retry, or session runtime was added.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| workspace tool selection, decoration, contribution resolution, and registration | existing `harness.tools.workspace` factory and registry, extended with `WorkspaceToolProfile` and `register_profile()` | tool membership/order, descriptions, prompt snippets, policy and service inputs | Complete |
| package-root resource summary discovery | existing `ResourceLoaderProfile`, `ProfiledResourceLoader`, and package catalog | built-in package, context-file conventions, prompt assembly, and security defaults | Complete |
| Agent screen approval presenter and session-transition cleanup | existing `harnesstui.conversation.agent_application` binding | approval policy, surface rendering, fallback copy, and Product composition | Complete |
| abort-aware retry sleep | existing `harness.session.composition` | no Product implementation | Complete |
| missing-session-cwd issue and error translation | existing `harness.session.lifecycle` contract and Product session runtime | no Coding compatibility exception | Complete |

The three Coding resource classes remain intentionally thin profile/default
bindings; deleting them would only obscure Product choices. Production
accounting: `src/loushang/coding` changed from 5,272 to 5,085 physical Python
LOC (-187). Shared production additions total 325 LOC and are independently
exercised with Design/Research-style profiles and structural ports. The former
108-line `coding.policy.tui` mechanism and the 51-line Coding cwd compatibility
layer are deleted rather than retained as facades.

### Wave 7, Slice R: Agent Product Runtime Factory Collapse (Complete)

This slice moves the final standard Agent lifecycle-runtime adapter out of
Coding and into the existing Harness session stack. It extends
`build_agent_product_session_runtime_ports`, `ProductSessionRuntime`, and the
existing bootstrap contracts; it does not introduce another session,
transcript, lifecycle, diagnostics, or bootstrap engine.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| standard Agent transcript/lifecycle runtime construction | `harness.session.AgentProductSessionRuntime` over `ProductSessionRuntime` and `build_agent_product_session_runtime_ports` | transcript session type and Product session factory | Complete |
| session diagnostic scope and shutdown-failure recording | the same shared Agent runtime adapter over `SessionDiagnosticsRuntime` | optional diagnostics service | Complete |
| current-session approval/runtime-host activation | existing `prepare_current_agent_session` | no Product implementation | Complete |
| cwd-aware service selection and non-persistent session finalization | `harness.session.build_agent_product_session_runtime` | Product service factory, session builder, and finalizer callbacks | Complete |
| import-copy race test seam | shared runtime `copy_file` port | Coding injects its named test seam | Complete |

`coding.runtime.AgentSessionRuntime` is now a 47-line type binding that fixes
`SessionManager` and preserves the public constructor. Coding prompt,
capability, model, tool, resource, and session-facade selection remain in
Coding. Production accounting for this slice changes `src/loushang/coding`
from 4,948 to 4,893 physical Python LOC (-55). Independent Harness tests bind a
Research-style current session and cwd service factory without importing
Coding; the Coding runtime/bootstrap, SDK signature, file-import race, and
architecture suites preserve existing behavior.

### Wave 7, Slice S: CLI Application Binding Convergence (Complete)

This slice removes the remaining manual application-phase assembly from the
Coding CLI. It extends the existing `CliApplicationRuntime`,
`AgentCliSessionHostBinding`, state preparation, early-operation, session
listing, and session-resolution components; it does not add another parser,
host, operation runtime, session runtime, transport, or presentation engine.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| two-pass parse and application phase composition | `harness.cli.AgentCliApplicationBinding` compiled onto `CliApplicationRuntime` | Product parser, launch plan, validated operation, and final error wording | Complete |
| extension-aware help session and runtime construction | the same application binding over existing state ports and runtime builder invocation | Product help text, runtime identity, services, and runtime factory | Complete |
| offline initialization and cwd selection | existing `AgentCliArgs` contract and application runtime | no repeated Product callbacks | Complete |
| standard session listing, resolution, and extension-flag collection | existing CLI operations and session lifecycle functions selected by the application binding | Product session configuration and operation insertions | Complete |
| session host callback binding | existing `AgentCliSessionHostBinding.bind()` over `run_agent_cli_session_host` | Work/Method preparation, observability source, and Product runners | Complete |

`src/loushang/coding/cli/__main__.py` changes from 815 to 722 physical Python
LOC (-93, 11.4%). The file deletes 132 lines and adds 39 lines of Product
binding, so 70.5% of the gross deletion remains as net reduction. Total
`src/loushang/coding` changes from 4,893 to 4,800 physical Python LOC.

The shared binding compiles existing ports rather than reimplementing their
phase behavior. A Research-style contract probe exercises state preparation,
runtime/session construction, the second parse, and host dispatch without
Coding imports. Architecture gates require Coding to use the binding and
forbid it from directly assembling `CliApplicationRuntime`, help-session,
session-listing, or session-resolution internals.

### Wave 7, Slice T: Agent Product Construction Binding Convergence (Complete)

This slice removes the final direct construction-request assembly from Coding.
It extends the existing `AgentProductConstructionRuntime` owner with a
declarative `AgentProductConstructionBinding`; it does not introduce another
bootstrap, configuration, prompt, model, tool, Agent, session, or capability
runtime.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| Product capability runtime acquisition | existing `bind_capability_composition_runtime`, selected through `AgentProductConstructionBinding` | Product capability profile | Complete |
| standard services to configuration-request mapping | existing `StandardAgentSessionConfigurationRequest` and configuration runtime | source-identity check, package materializer, and extension flags | Complete |
| capability runtime to construction ports | existing `AgentProductConstructionPorts` | extension tool discovery callbacks and Product pack IDs | Complete |
| default thinking selection and Product construction request assembly | existing `AgentProductConstructionRuntime` request contract | default prompt, explicit/append prompt inputs, model/tool selections, and Agent factory | Complete |
| configured Agent to Product session binding | existing construction runtime callback | Coding `AgentSession` policy constructor, session manager, approval resolver, and Product event inputs | Complete |

`src/loushang/coding/bootstrap.py` changes from 496 to 482 physical Python LOC
(-14), and total `src/loushang/coding` changes from 4,800 to 4,786 LOC. The
small LOC delta is intentional: the former request assembly was already using
the correct shared engines. The responsibility change prevents Coding and
future Research, Design, or PPT products from repeating the nested
configuration/port wiring while preserving Product-owned policies.

A Research-style contract probe verifies that the binding compiles Product
choices into the canonical request, resolves the standard thinking default,
and passes the same capability runtime to the Product session factory.
Architecture gates require Coding to import the binding and prohibit direct
imports of the construction runtime, request, ports, and standard
configuration request.

### Wave 7, Slice U: HarnessTUI Agent Surface Binding Finalization (Complete)

This slice removes the last repeated Agent-session reads from Coding startup,
completion, and settings adapters. It extends the existing HarnessTUI startup
view, Agent application binding, prepared completion host, model-selection
binding, and settings workflow; it does not introduce another TUI
application, runtime, controller, catalog, selection engine, or settings page.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| prepared Agent session to startup view | `harnesstui.conversation.agent_application` over the existing neutral startup view and session-view facts | usable-model preparation and Product startup entry point | Complete |
| live session command/model completion sources | `harnesstui.completion.host` over the existing command catalog and model-selection binding | completion command, argument-group, alias, and wording profile | Complete |
| session model settings snapshot and workflow ports | `harnesstui.settings.workflow` over the existing selection binding and settings dashboard | boolean setting bindings/copy and model persistence action | Complete |
| plain Agent conversation application | existing `build_agent_plain_conversation_ports` and `build_agent_plain_conversation_app` | renderer, controller, hotkeys, debug behavior, and Product copy | Already canonical |
| interactive model selection | existing `select_session_model` with an injected apply callback | preferred models, persistence scope, and warning copy | Already canonical |

The neutral `conversation.startup` module remains free of Agent model access;
the structural Agent session binding lives in the existing
`conversation.agent_application` owner. This preserves the selected-session
model semantics at restore/switch boundaries rather than silently preferring
a possibly stale live Agent model.

Production accounting: `src/loushang/coding` changes from 4,786 to 4,745
physical Python LOC (-41). The three Coding adapters delete 57 lines and add
16 lines of Product profile/callback binding, so 71.9% of the gross deletion
remains as net reduction. HarnessTUI production additions total 102 lines and
are independently exercised by Research-style structural sessions without
Coding imports. Architecture gates keep the neutral startup view free of
Agent policy and require the Agent application owner, rather than Coding, to
load standard session model facts.

### Wave 7, Slice V: Agent Product Service Bundle Finalization (Complete)

This slice moves only the remaining standard Agent service-bundle construction
and bootstrap-result collection into the existing
`harness.session.bootstrap` owner. It reuses `BootstrapServices`,
`DiagnosticsService`, `ModelCatalog`, `SettingsManager`, `ExecService`,
`prepare_agent_session_services`, `AgentProductConstructionBinding`, and
`build_agent_product_session_runtime`; it does not add another service
container, bootstrap runtime, configuration runtime, or session factory.

| Source mechanism | Existing shared owner | Product retained | Status |
| --- | --- | --- | --- |
| standard settings/model/diagnostics/exec service construction | `create_standard_agent_bootstrap_services` in the existing session bootstrap owner | Product resource-loader factory and optional injected service instances | Complete |
| Product session plus resource/diagnostics/audit result projection | `build_standard_agent_session_result` beside the existing `CreateAgentSessionResult` contract | Product session creation and selection of session/resource/audit values | Complete |
| cwd-bound resource and extension service preparation | existing `prepare_agent_session_services` | Coding settings paths, loader options, and extension runtime factory | Already canonical |
| Agent and Product session construction | existing `AgentProductConstructionBinding` with Coding session factory callbacks | Coding `AgentSession`, prompt/image wording, tool activation, package materializer, diagnostics identity, and approval policy | Intentionally retained |

Production accounting: `src/loushang/coding` changes from 4,745 to 4,737
physical Python LOC (-8), while `coding.bootstrap` changes from 482 to 474
lines. The small reduction is intentional: public Coding signatures remain
stable and continue to expose Product choices, while the reusable construction
logic has a single shared owner. Harness production grows by 66 lines,
including exports. Research-style contract tests bind a custom resource loader,
model registry, diagnostics service, execution service, model default, prompt,
and session result without importing Coding.

The slice stops at this boundary. Moving the remaining Coding session factory
would only turn Product-specific `AgentSession`, resource, prompt, tool,
package, approval, and diagnostic choices into a long callback list. An
architecture gate requires Coding to use the shared service/result helpers and
forbids it from directly constructing `ControlConfig`, `DiagnosticsService`, or
`ModelCatalog`.

### Wave 7, Slice W: Coding Public Facade Cull (Complete)

This slice removes only zero-logic Coding import facades after checking their
production, test, example, and SDK consumers. It adds no shared implementation
and changes no runtime behavior.

| Removed facade | Canonical owner | Product surface retained |
| --- | --- | --- |
| `coding.event` | `harness.events` | Product/Work projections and final presentation remain in their existing owners |
| `coding.control.model_registry` | `harness.model_catalog.ModelCatalog` | Coding model preferences and selection persistence remain in `coding.model_selection` |
| `coding.prompt.types` | `harness.capabilities.prompt` and `prompt_assembly` | Coding prompt default and assembler remain in `coding.prompt` |
| `coding.prompt.preflight` and package-level preflight/template re-exports | `harness.capabilities.prompt_preflight` and `prompt` | no duplicate Product preflight mechanism |

The top-level Coding SDK retains its Product constructors, sessions, resource
bindings, workspace-tool profile helpers, policy defaults, and prompt
assembler. Shared event and model-catalog symbols that were not part of the
declared SDK entry contract are no longer re-exported. Event and model-catalog
tests move to the Harness suite, while Coding prompt tests import canonical
preflight/template owners for the shared portions.

Production accounting: `src/loushang/coding` changes from 4,737 to 4,641
physical Python LOC (-96). Harness production adds zero lines. Architecture
gates require all four retired prefixes to remain unimportable and reject
imports from source, tests, and examples.

### Wave 7, Slice X: CLI Leaf Binding Convergence (Complete)

This slice removes two repeated CLI leaf mechanisms by extending their existing
owners. It adds no CLI runtime, tool registry, policy engine, approval resolver,
or diagnostics service.

| Repeated leaf | Existing owner reused | Product retained |
| --- | --- | --- |
| tool settings parsed once by Harness and then parsed again while Coding built its registry | `harness.cli.AgentCliStatePreparationPorts` now passes the existing `WorkspaceToolRuntimeSettings` value produced by `workspace_tool_runtime_settings` | Coding workspace-tool profile, membership, descriptions, and service injection |
| package-source policy rejection mapped to a diagnostic in Coding | existing `harness.resources.packages.catalog_diagnostics` exports `record_package_source_policy_denial` | Coding security policy selection, allow/deny decision, CLI command selection, and final error text |

Normal application preparation and extension-aware help discovery both resolve
tool runtime settings once per path and pass the same policy/resolver facts to
the Product registry builder. The help path does not create an interactive
resolver, preserving its non-interactive behavior. Coding's model persistence
warning, Method/Work operations, help copy, and completion failure wording stay
Product-owned.

Production accounting: `src/loushang/coding` changes from 4,641 to 4,632
physical Python LOC (-9), all in `coding.cli.__main__`. Shared production
owners grow by 43 net lines including exports. The small LOC delta is intentional:
the change removes duplicate settings interpretation and centralizes one
standard diagnostic contract without relocating Product callbacks.
