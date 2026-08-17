# Session Capabilities Runtime Boundary

## Decision

The former `loushang.harness.session.capabilities` implementation has been
split by semantic owner. A single “session capabilities” concept remains useful
in architecture discussions, but it is not one implementation responsibility:

- `loushang.harness.capabilities.commands` owns Product-neutral dynamic command
  source composition, catalog ordering, and ordered asynchronous dispatch;
- `loushang.harness.session.tool_runtime` owns allowed-name filtering, live
  tool activation, runtime tool admission, and Agent tool rebind mechanics;
- `loushang.harness.session.tool_controller` owns Product/workspace binding,
  default activation profiles, prompt assembly, policy, approval, and tool
  execution-host construction;
- `loushang.harness.session.bash` owns shell parameter construction,
  `bash_operations` binding, incremental stdout/stderr forwarding, abort,
  Bash-result normalization, transcript commit, and context refresh.

This split keeps the existing `ToolActivationCoordinator`,
`CapabilityPackComposer`, command dispatch primitives, workspace execution
types, and `CommandExecutionRecord`. It does not create another tool registry,
command catalog, workspace backend, or transcript repository.

## Command Composition

`CommandRuntimeSource` and `SessionCommandRuntime` are Product-neutral despite
the historical class name. They depend only on capability packs and command
contracts, so their canonical module is `harness.capabilities.commands`.

Descriptor and handler priorities remain separate. A Product can display its
built-in descriptor before an extension descriptor while allowing the
extension handler to receive the invocation first. `dispatch()` returns the
complete `CommandDispatchOutcome`, preserving the distinction between
unhandled and handled-with-`None`; `execute()` remains the compatibility result
surface for callers that only need `ResultT | None`.

## Tool Runtime and Product Binding

`SessionToolRuntime` sees only the mutable Agent `tools` property. It does not
depend on `system_prompt`, resource activation, prompt composition, approval,
policy, or workspace execution. Its registry port contains only operations the
runtime actually consumes.

`SessionToolController` extends that narrow tool surface with the Product Agent
prompt surface. It owns `ToolActivationProfile` and
`create_tool_prompt_rebuilder`, because those operations bind Product defaults,
resources, and prompt assembly to a concrete session. Contribution and tool
execution callbacks use explicit Protocol signatures rather than open-ended
`Callable[..., ...]` contracts.

## Bash Execution

The execution runtime is Bash-specific: its request accepts `cwd`, `env`,
`stdin`, and `timeout_seconds`; it binds `bash_operations`; and it understands
the workspace Bash result schema. `BashCommandExecutionRuntime` therefore lives
in `session/bash.py`. `SessionCommandExecutionRuntime` remains an alias only for
source compatibility.

Execution is single-flight from the start of `before_execute` until transcript
commit or failure cleanup. This makes hook interception observable through
`is_running`, rejects concurrent commands before either can acquire abort
ownership, and lets `abort()` target the one active execution. Ordered final
output is authoritative; stderr metadata is appended only when stderr is not
already present, including when stderr appeared between stdout chunks.

## Product Binding

Products supply callback ports for:

- default and initial tool selection, contribution admission, and tool context;
- prompt construction after the active tool set changes;
- command-source descriptors, priorities, and concrete command handlers;
- current workspace, selected Bash definition, call ID, transcript append, and
  context refresh;
- approval/extension interception and Product diagnostics translation.

Source admission and Product policy happen before values are passed to these
mechanisms.

## Compatibility Surface

`loushang.harness.session.capabilities` is a compatibility re-export module. It
contains no runtime implementation. Existing imports of
`SessionToolRuntime`, `SessionCommandRuntime`,
`SessionCommandExecutionRuntime`, `UserCommandRequest`, and result-normalization
helpers continue to resolve to the canonical owner objects.

New Harness code must import the canonical modules directly. Session internals
must not use the compatibility module, which prevents the former umbrella from
becoming an implementation dependency again.

## Coding Binding

Coding binds `SessionToolController` and `SessionCommandController` as thin
adapters. The standard `BashExecutionRuntime` supplies the default
`["/bin/bash", "-lc", command]` execution, abort, streaming, and transcript
recording path. Coding supplies only the selected tool definition, transcript
callbacks, and its optional `user_bash` extension hook.

Coding keeps its prompt text, default built-in tools, concrete tool context,
tool admission diagnostics, built-in command implementations, resource and
extension command mapping, and TUI/RPC/HTML presentation. No Coding Bash
controller or Bash-specific protocol alias is introduced.

## Dependency Rule

The Product-neutral command module may import only Harness capability and
command primitives. The session tool runtime may import public Agent tool
contracts plus Harness activation and tool-definition contracts. The Product
controllers and Bash runtime may additionally import session-profile resources,
workspace execution types, and portable conversation records.

None of these owners may import Coding, Product prompts, provider/model/auth
resolution, Product stores, or UI/RPC types. Those concerns are supplied through
explicit ports.

## Verification

- Harness tests characterize command priority and handled-`None` dispatch.
- Bash tests characterize single-flight hook execution, abort with streamed
  output, ordered stdout/stderr normalization, and one transcript commit.
- Tool tests verify neutral allowed-name filtering and live rebind.
- Architecture tests require canonical internal imports, a re-export-only
  compatibility module, and Coding-free implementation owners.
- Coding tests preserve active-tool policy, command precedence, extension
  interception, Bash output, and transcript context projection.
