# Standard Session Command Pack Boundary

## Status

Status: the standard-handler cutover, descriptor canonicalization, neutral
result projection, shared local-command profile, session diagnostics, and
resource/extension source adapters are implemented for the initial Wave 3
subset. `coding.session.builtin_commands` and the duplicate Coding command
definition modules have been removed.

This Wave makes standard typed session commands a Harness capability pack. It
does not make every current Coding slash command standard and it does not
replace the existing command catalog or command dispatch runtime.

## Decision

The existing owners remain canonical:

| Concern | Canonical owner | Product responsibility |
| --- | --- | --- |
| Command descriptors, catalog lookup, parsing, and dispatch | `harness.commands` | Select commands, add Product commands, and project to a local UI/transport. |
| Ordered dynamic command-source composition | `harness.session.SessionCommandRuntime` | Admit Product, extension, and resource sources with priorities. |
| Typed prompt, maintenance, identity, retry, queue, and abort operations | `harness.session.SessionOperationRuntime` | Choose the admitted capability groups and project results. |
| Session creation, restore, fork, replacement, and disposal transactions | `harness.session.SessionLifecycleRuntime` | Bind store/CWD policy, Product session construction, and transition projection. |
| Transcript branch navigation and optional branch summaries | `harness.transcript.AgentTranscriptNavigationRuntime` | Bind Product summary runner, hook policy, and event projection. |
| Workspace command-tool execution, cancellation, transcript result commit, and context refresh | `harness.session.SessionCommandExecutionRuntime` | Bind tool, workspace, approval, prompt, and result-presentation ports. |
| Standard session command descriptors, argument parsing, and typed result adaptation | `harness.session.command_pack` | Bind existing session/lifecycle/navigation/runtime ports and Product presentation ports. |
| Extension/resource command source projection and dispatch | `harness.session.command_sources` | Bind extension runtime, resource bundle, Coding diagnostics, and Product result projection. |
| JSONL/RPC framing and response delivery | `channel` | Supply a Product RPC schema and result projection. |
| Local command routes, text, clipboard, HTML, and screen behavior | Product and `harnesstui`/`tui` | Select routes, wording, renderer, and terminal integration. |

`harness.session.command_pack` is an optional Agent/session integration
package. It may use stable public Agent and AI value contracts where the
existing session profile already does so. It must not import Coding, resolve a
provider or credential, select a model, own a Product storage policy, or emit
Product RPC/TUI dictionaries.

The target composition is:

```text
STANDARD_SESSION_COMMAND_PACK
  + StandardSessionCommandProfile.select()/without()
  + a Product's existing builtin `CommandRuntimeSource`
  + callbacks bound to session/lifecycle/navigation runtimes
  + unchanged extension and resource command sources
  -> SessionCommandRuntime
  -> Product command-result projection
```

There is one command catalog and one ordered dispatcher: the existing
`harness.commands.CommandCatalog` and `SessionCommandRuntime`. The Product's
existing builtin source delegates only the admitted invocations to the
standard pack, preserving its descriptor order. The pack must not introduce a
second catalog, command registry, source ordering, or fallback dispatch loop.

`harness.session.command_sources` supplies the extension and resource source
adapters. It projects shared descriptors and dispatches only through
Product-bound extension, resource, diagnostic, and result ports; it neither
owns Product errors nor creates a second source-ordering policy.

## Source Classification

The former implementation was concentrated in
`coding.session.builtin_commands` and `coding.session.command_controller`.
Standard session metadata, parsing, typed execution, and neutral result
projection remain exposed through `harness.session.command_pack`. The physical
implementation is split by responsibility under `harness.session.commands`:
`catalog.py` owns identifiers, descriptors, and immutable profiles;
`execution.py` owns typed ports, argument parsing, and dispatch; and
`projection.py` owns neutral result shaping. The compatibility module contains
only explicit re-exports. Generic local command definitions live in
`harness.commands.DEFAULT_LOCAL_COMMANDS_PROFILE`. Coding retains only the
catalog adapter and Product-specific command overlays.

| Current command capability | Wave 3 owner | Product injection or retained owner |
| --- | --- | --- |
| Session snapshot, manual compaction, resource reload | Standard Harness command mechanism | Product supplies snapshot, compaction, and reload ports plus display wording. |
| New, resume, fork, clone, and tree navigation | Standard Harness session-operation adapter | Product supplies lifecycle/navigation ports, accepted arguments, fork interpretation, and result projection. |
| Tool selection and extension inventory | Harness command mechanics only if backed by existing neutral tool/extension ports | Product supplies descriptors, admission policy, display entries, and wording. Do not move Coding renderers. |
| Session name mutation | Standard Harness command mechanism | Product binds session metadata mutation and projects the completed value. |
| Transcript export and import | Standard Harness command mechanism | Product binds HTML/JSONL export and import ports, selects files/storage policy, and projects results. |
| Clipboard copy | Product/TUI boundary | Clipboard backend and assistant-text selection are presentation concerns. |
| Changelog, model, settings, terminal, hotkeys, quit, share | Product local commands | They describe a Product, client, provider, or process policy rather than a reusable session operation. |
| Coding command descriptions, aliases, and legacy output dictionaries | Coding | Harness descriptors use neutral identifiers and availability only. |

The initial shared subset is intentionally conservative:

```text
session, name, export, import, compact, reload, new, resume, fork, clone, tree
```

`tools` and `extensions` may join only when their existing neutral result
contracts can carry structured inventory data without importing Coding. They
must not be admitted merely because other products could display a similarly
named command.

## Shared Contract

The exact names may be refined during implementation, but the contract shape
is fixed.

```text
SessionCommandId
  = session | name | export | import | compact | reload | new | resume | fork | clone | tree

StandardSessionCommandResult
  command_id: SessionCommandId
  disposition: completed | unavailable | invalid_arguments
  value: object | None             # opaque to Harness
  error_code: str | None

StandardSessionCommandPorts
  get_session_info()
  set_session_name(name)
  export_html(path)
  export_jsonl(path)
  import_session(path, cwd)
  compact(instructions)
  reload()
  new_session(options)
  resume_session(reference, options)
  fork_session(record_id, options)
  clone_session()
  navigate_tree(record_id, options)
```

The command pack must treat returned values as opaque and must never serialize them,
inspect dataclass fields, call `repr()`, or assume a Coding result type. A
Product adapter projects that typed value to a transport or TUI representation
after the operation completes. Each callback binds an already-composed
`SessionOperationRuntime`, `SessionLifecycleRuntime`,
`AgentTranscriptNavigationRuntime`, or equivalent Product adapter. The pack
does not recreate their transactional behavior.

Argument handling is a shared mechanical contract:

| Command | Normalized arguments | Validation owned by Harness |
| --- | --- | --- |
| `session`, `reload`, `clone` | none | legacy extra arguments are ignored |
| `name` | optional display name | an empty request clears the name |
| `export` | optional target path | `.jsonl` selects the JSONL export port; otherwise selects HTML |
| `import` | required path, optional CWD | requires a first positional path |
| `compact` | optional `instructions` | preserve an empty request as absent |
| `new` | optional `cwd` | first positional value is the CWD |
| `resume` | required `reference` | requires a first positional value |
| `fork` | required `record_id`, optional `position` | `position` is `before` or `at` |
| `tree` | required `record_id`, optional summary/label/instruction options | preserves current recognized-option parsing |

The parsed values are still subject to Product acceptance. For example, the
Product decides whether a supplied CWD is usable and whether a record ID is a
valid fork location. Harness only parses and routes the neutral operation.

A selected command whose callback was not bound returns
`disposition="unavailable"` without calling a Product operation. Products
normally select only the command IDs backed by their existing operation,
lifecycle, and navigation capabilities. The result is an explicit adapter
outcome, not a replacement for `SessionOperationAvailability`.

## Profile And Composition

`harness.session.command_pack` exposes an immutable command-ID profile rather
than a global mutable command list:

```text
StandardSessionCommandProfile
  enabled_command_ids: frozenset[SessionCommandId]
  select(ids)
  without(ids)
```

Its methods return immutable copies. Product descriptor metadata remains in
the existing descriptor source for this cutover so the public command list
keeps its current ordering. Extension and resource commands remain separate
runtime sources; the standard pack never mutates a selected Product profile at
runtime.

A Product binds the pack through a small adapter:

```text
CODING_SESSION_COMMAND_PROFILE
  = STANDARD_SESSION_COMMAND_PROFILE
      .select({session, name, export, import, compact, reload, new, resume, fork, clone, tree})

SessionCommandRuntime(
  sources=(
    coding_builtin_source(delegate_standard_commands(profile, ports)),
    coding_extension_command_source(...),
    coding_resource_command_source(...),
  )
)
```

Coding continues to choose names, descriptions, compatibility aliases, source
labels, and handler priorities where those are part of its public surface. A
future Research, Design, or PPT product can bind the same standard pack with
different capabilities and no Coding import.

## Coding Cutover

The final Coding adapter may contain only:

- a `StandardSessionCommandPorts` binding to its identity, export/import,
  lifecycle, compaction, and transcript navigation facades;
- the Product profile and any Coding-only command descriptors;
- extension/resource command adaptation, including Product diagnostics;
- conversion from the neutral standard result mapping to
  `CommandExecutionResult`.

The following are deleted or reduced in this cutover:

- duplicated parsing, dispatch, descriptors, and result projection in
  `coding.session.builtin_commands`;

`SessionCommandDescriptor`, `CommandSourceInfo`, and `SlashCommandInfo` are
canonical `harness.commands` contracts. Coding's `commands` package now owns
only its catalog adapter and future Product overlays. The prompt/skill resource descriptor projection
also lives in `harness.commands.resources`; Coding retains diagnostics and
result presentation. Resolved extension commands are projected by
`harness.extensions.commands`; Coding retains extension error diagnostics and
result presentation. `harness.session.command_sources` now owns the extension
and resource source adapters. Coding's controller binds its extension runner,
shared diagnostics runtime, result projection, and builtin source. Product builtin
descriptor reduction is complete for the standard session subset; local UI
commands come from `DEFAULT_LOCAL_COMMANDS_PROFILE` and Product overlays.

The following remain outside this Wave:

- Coding model/auth/settings/provider commands and policy;
- clipboard, terminal diagnostics, hotkeys, quit, changelog,
  sharing, and Coding-specific command text;
- transcript import/export format, storage policy, file selection, and archive
  policy;
- session-file/CWD acceptance, fork product semantics, and Coding result
  wording;
- Pi/RPC/camelCase result dictionaries and TUI route handling.

## Delivery Sequence

The Wave has three reviewable commits. Each remains runnable and contains no
new long-term compatibility facade.

1. **Contracts, profile, and fake Product probe**
   - Complete: add typed IDs, results, ports, immutable profile,
     and command-argument parser under `harness.session.command_pack`.
   - Complete: bind a fake Product with no Coding imports and lock invalid arguments,
     unavailable commands, descriptor precedence, and async port behavior.
   - Complete: add a narrow no-Coding-import probe before moving Coding handlers.

2. **Standard handler implementation**
   - Complete: implement and test the initial subset through injected ports.
   - Complete: keep `SessionCommandRuntime` as the sole dispatcher by
     delegating from the existing builtin source, preserving descriptor order.
   - Test cancellation/error propagation, fork/tree option parsing, and no
     call to a port when availability rejects a request.

3. **Coding adapter cutover and deletion**
   - Complete: bind Coding's existing lifecycle and compaction facades to the shared
     ports; preserve Coding result projections with golden tests.
   - Complete: delete the moved handler logic rather than re-exporting it
     through a legacy Coding module.
   - Complete: canonicalize the shared command descriptor contract under
     `harness.commands`, and route Coding consumers directly to it.
   - Complete: move extension/resource source adapters into
     `harness.session.command_sources`, retaining Coding diagnostics and result
     projection as injected callbacks.
   - Leave Product builtin descriptor reduction explicitly pending; do not
     count its LOC until the old code is deleted.

## Verification

Focused tests must cover:

- `SessionCommandRuntime` source precedence remains unchanged when the
  standard pack, extension commands, and resource commands all claim names;
- each standard command validates input before calling its port and returns a
  typed invalid/unavailable/completed result;
- fake-Product ports can implement the full initial subset without a Coding
  import;
- failed, cancelled, and concurrent lifecycle operations preserve the existing
  session operation ownership and do not double-commit a transcript record;
- `fork` and `tree` preserve `before`/`at`, summarize, and label semantics
  without Harness inventing a record-selection policy;
- Coding's current command catalog, extension command precedence, and RPC/TUI
  result fixtures remain equivalent after its adapter projects the shared
  result;
- `harness.session.command_pack` has no Coding import and does not import
  provider registration, credentials, transport, or UI modules.

Run targeted Harness command/session tests, Coding command-controller tests,
architecture-import tests, and then the affected non-live suite.

## Non-Goals

This Wave does not:

- add a universal command language, command persistence, remote-command
  protocol, or a second command registry;
- make Product local UI commands automatically shared because they have common
  names;
- move HTML, clipboard, terminal, changelog, settings, model, authentication,
  provider, or share behavior into Harness;
- change the transcript file format, fork policy, storage backend, or command
  transport schema;
- turn command descriptors into a Product service locator.

## Measurement

The Wave begins with 1,123 lines across the two main Coding command modules.
It is not correct to count all of them as shared: extension/resource adaptation,
Coding command descriptions, tool/extension presentation, clipboard/export,
and compatibility projections remain Product code. The implemented handler
cutover moves eleven command implementations but retains a Coding binding and
result projector, so it is not yet a meaningful net-LOC reduction. A
220--350 line reduction requires the separately scoped descriptor and command
source-adapter collapse; any larger figure requires separate
tool/package/transcript ledger entries. Harness additions are never counted as
a reduction merely because a file changed owner.
