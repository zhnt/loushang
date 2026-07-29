# CLI Product Host Collapse

## Boundary

Product CLI additions, Product startup policy, Method/Work bindings, and
product wording remain product-owned. Harness owns the standard Agent CLI
grammar/value projection, two-pass application lifecycle, and reusable
operations over injected session and settings capabilities. Channel continues
to own stream binding, stdout protection, turn ordering, and disposal through
`ProductHostLifecycle`.

This slice extends the existing `loushang.harness.cli` runtime. It does not add
a second CLI parser, transport, session runtime, or product host.

## Shared Contracts

- `CliOperationSequence` executes product-selected operations in declared order
  and returns on the first handled exit code.
- `StandardCliOperationRequest` binds the standard Agent operation pack;
  `CliOperationInsertion` places Product operations at explicit points without
  rebuilding that pack.
- `CliOperationStage` binds a stable operation id to a synchronous or
  asynchronous handler. Products can add, remove, or reorder stages without
  changing Harness.
- `AgentCliArgs` and `agent_cli_argument_values()` project
  `STANDARD_CLI_PROFILE` once. Products subclass the value object with additive
  fields instead of copying the standard dataclass and namespace projection.
- `CliApplicationRuntime` owns bootstrap parse, static validation, guarded
  runtime construction, session resolution, extension-aware final parse,
  configuration, operation, and host phase ordering over injected ports.
- `AgentCliStatePreparationPorts` and
  `prepare_agent_cli_application_state()` own service selection, session-path
  resolution, pre-runtime operations, resource toggles, tool-registry
  construction, and approval binding. Extension-aware help discovery reuses
  these same ports rather than constructing a parallel bootstrap path.
- `AgentCliEarlyOperationPorts` binds Product version/source identity and help
  formatting to the shared help, version, and source-info exit behavior.
- `invoke_agent_cli_runtime_builder()`,
  `resolve_agent_cli_session()`, and `run_agent_cli_session_listing()` bind the
  standard runtime inputs, session-resolution grammar, and listing request
  directly to their existing shared owners.
- `run_keyword_cli_turns()` owns first/last image, follow-up, and disposal
  semantics for Product-prepared turn batches.
- `prepare_agent_cli_host_input()` and `project_domain_turns_to_cli()` own the
  standard prompt-input error boundary and prepared-domain-turn projection.
  Products inject domain preparation and error wording.
- `run_agent_cli_host()` composes the existing TUI, RPC, Channel, workflow,
  prompt, and plain hosts after Product input preparation. It owns mode
  precedence and planned-turn selection without importing Work, Method, TUI,
  or a Product argument type.
- `AgentCliSessionHostBinding` and `run_agent_cli_session_host()` bind one
  resolved Product session to that existing host. Product callbacks supply
  Work construction, observability context, and runner selection; Harness
  retains the standard TTY, mode, lifecycle, and failure semantics.
- `CliLaunchPlan` normalizes TTY selection, structured-output protection,
  session-restore conflicts, Work/Method/Channel compatibility, and
  observability mode without receiving a Product argument object.
- `harness.cli.host_operations` owns common request execution, output writing,
  and stable error-to-exit-code behavior for standard session, resource,
  package, and catalog operations.
- Standard Agent arguments project resource toggles, session listing and
  resolution, catalog operations, ephemeral bootstrap policy, resource-loader
  options, session paths, and image policy through their existing capability
  modules. Products no longer rebuild those requests.
- `configure_agent_cli_session()` owns extension flags, session naming,
  model-selection error containment, and thinking selection while Product
  callbacks retain persistence policy and warning wording.
- `workspace_tool_runtime_settings()` projects shared tool settings into an
  injected policy factory and standard headless approval resolver.
- `run_fake_workflow_cli()` lets fake scenario workflows exit before Product
  runtime construction without moving scenario execution into the CLI layer.
- `harnesstui.conversation.agent_binding` binds standard Agent event
  projection, failure detection, prompt sequencing, and disposal to the
  existing plain prompt host.
- `work.SessionWorkHostPort` maps host metadata onto
  `SessionWorkRuntime`; `channel.adapters.session_work.SessionWorkChannelPort`
  maps that runtime
  onto the Channel protocol. Neither creates another Work or Channel engine.
- `work.project_prepared_session_work_turns()` maps generic prepared turns into
  the existing Work turn shape; `method.MethodDomainRuntime` composes existing
  Method discovery, selection, compilation, and projection.
- `harness.host.AgentRuntimeChannelProjection` is the optional standard Agent
  event-to-Channel projection. Channel remains unaware of Harness and Work.

Harness receives already parsed request values and explicit callbacks. It does
not inspect a Coding argument object and does not import Coding, Method, Work,
TUI, or a product wire schema.

## Coding Binding

Coding subclasses `AgentCliArgs` with Method/Work fields, inserts its Method and
package-catalog stages into the standard operation pack, supplies its policy
factory and model-persistence warning, and binds Product callbacks to
`CliApplicationRuntime`, `AgentCliStatePreparationPorts`, and
`AgentCliSessionHostBinding`. It retains:

- additive Method/Work argument grammar;
- Coding bootstrap and tool/resource policy selection;
- package source security and diagnostics callbacks;
- Method discovery/compilation and Work event-log bindings;
- Coding Work vocabulary (`domain="coding"` and `SubmitCodingTurn`);
- the plain renderer, model preference preparation, and final Product runner
  callbacks.

Mode precedence, prompt/plan lifecycle, Channel cancellation/delivery, and
standard Agent event projection are no longer implemented in Coding. Service
and session-path preparation, extension-aware help bootstrap, informational
early exits, runtime-builder invocation, standard session resolution/listing,
prompt input decoding, diagnostic archive execution, and Work log path
handling are also shared.

The old Coding helpers are deleted once the equivalent Harness operations are
used directly. Compatibility facades are not retained.

## Behavior Contract

The migration preserves operation precedence, two-pass extension flag parsing,
output formats, error text, and exit codes. Multiple command-style flags
continue to execute only the first operation in the existing order. No
external CLI or RPC field is renamed in this slice.

## Dependency Rule

`loushang.harness.cli` may depend on public Harness, Agent, and AI value/codec
APIs needed by standard Agent-product CLI operations. It must not import
`loushang.coding`, `loushang.method`, `loushang.work`, or terminal UI packages.
`loushang.channel` remains independent of Harness and Product packages.
