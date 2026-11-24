# Embedded and Hosted TUI session commands

## Ownership and execution

Phase two builds on the command implementation merged at `6740f9c55`. Embedded Coding TUI uses
`ConversationCommandCatalog` and `MixedCommandCatalog` for local and Session
effects. The Coding dispatcher delegates a Session command to its
`SessionCommandController`. `SessionCommandRuntime` and
`CapabilityPackComposer` assemble the current command generations,
extension sources, and Prompt and Skill resources. `CommandCatalog` resolves
names and aliases. `StandardSessionCommandPorts` bind the operation to its
existing Session owner. The Hosted adapter reads this same catalog on demand,
including new descriptors after resource refresh.

`ToolDefinition` describes a model-callable operation. The existing
`ToolRegistry` supplies registered definitions, and
`ToolActivationCoordinator` resolves the available, allowed and active tool
sets. The `/tools` slash command queries these sets or changes the Session's
selection through its existing operation. Its result reads back the effective
selection after refresh. Runtime Tool Policy and Approval still govern each
tool invocation. An allowed tool in this inventory has passed the Session
selection allowlist. Approval and policy for individual calls are evaluated
when those calls are made.

### Command inventory

The Hosted column describes this implementation. The final column identifies
existing reusable routes and the next step where the slash entry is absent.

| Commands | Declaration and owner | Embedded route and handler | Hosted route and follow-up |
| --- | --- | --- | --- |
| `/session` | `harness.session.commands.catalog`, standard Session pack | `execute_standard_session_command_async` reads Session statistics, context and maintenance state | Shared read route for active Sessions, including without a model or while an Execution runs |
| `/tools [on\|off\|only\|reset]` | Standard Session pack, Session tools | Standard tools handler uses the Session ToolController and refreshes activation through existing Session operations | Shared read for the inventory, guarded submission for selection changes, and argument completion from allowed tools |
| `/compact [instructions]` | Standard Session pack, transcript maintenance | Standard handler calls Session compaction with optional instructions | Guarded shared route using the original checkpoint and context refresh |
| `/rename [name]` | Standard pack and Embedded rename surface | Session metadata update or interactive rename | Guarded standard command. The empty form prepares a name input. Metadata events refresh authoritative Mux titles |
| `/new`, `/resume`, `/delete` | Standard pack and Embedded lifecycle surfaces | Session creation, replacement or deletion through lifecycle ports | `/new <scope>` opens a member. `/sessions` and `/resume` use discovery and admitted member open. Hosted `/close --yes` uses member close. Session deletion needs its own lifecycle action |
| `/fork`, `/clone`, `/branch`, `/tree` | Standard pack, transcript navigation and lifecycle | Fork and its clone alias, branch picker or explicit branch point, tree navigation | Discoverable as requiring another route. Extend the existing member/session lifecycle and navigation contracts |
| `/export`, `/import` | Standard pack, Session import/export | HTML, JSONL or bundle export and controlled Session import | Requires an explicit resource transfer and lifecycle route |
| `/extensions [name or ID]` | Standard pack and current Extension Runtime | Loaded extension inventory and details | Shared read route exposing identities, enabled state, permission level and diagnostic codes |
| `/reload` | Standard pack and resource owners | Existing resource refresh graph | Discoverable as requiring another route |
| `/copy`, `/changelog` | Standard pack with client or Product ports | Embedded clipboard and changelog handlers | Clipboard and display remain client actions when added |
| `/model`, `/models` | `DEFAULT_LOCAL_COMMANDS_PROFILE` and model selection surface | Embedded model chooser and listing with model argument completion | Hosted local actions use the existing AppClient model catalog and selection operations. `/model --thinking <level>` uses levels returned for the current model |
| `/command`, `/commands` | Local catalog/surface grammar | Embedded selection palette and filtered listing | Slash completion and local `/commands` display the live Hosted response |
| `/settings`, `/config`, `/hotkeys`, `/terminal` | Local catalog/surface grammar | Embedded settings, keybindings and terminal diagnostics | Host and terminal settings belong to the applicable client or settings port |
| `/permissions`, `/agents`, `/btw` | Local catalog/surface grammar | Embedded approval and grant surface, agent tree, side question | Existing `/question`, `/approve`, `/deny` preserve the Hosted approval path. Broader local surfaces are future work |
| `/quit`, `/exit` | Embedded conversation host | Local teardown | Hosted `/exit` and `/detach` preserve the original attachment and foreground lifecycle rules |
| `/goal` | Coding Goal overlay in `coding.ui.completion` and `product_binding` | Product Goal commands and status | Use existing interactive Goal operations for a future shortcut |
| `/plugins` | Coding plugin overlay in `coding.ui._plugin_completion` and `product_binding` | Product Plugin status, list and management operations | Requires a scoped Plugin route. Package management remains in its owning subsystem |
| `/lsp` | `coding.lsp.commands`, exposed by Coding AgentSession | Coding LSP access and command parser | `/lsp` and `/lsp status` use the read route. `/lsp stop <server-id> <root>` uses guarded submission and the Session-owned supervisor |
| Extension commands, Prompt names and `/skill:<name>` | `harness.session.command_sources`, resource descriptors and extension runtime | Registered extension handler, or Prompt/Skill preflight inside the ordinary turn | Current effective declarations appear in the catalog. A future route needs explicit extension execution or Prompt/Skill submission semantics |
| `/help`, `/question`, `/refresh`, `/steer`, `/followup`, `/approve`, `/deny`, `/interrupt`, `/detach`, `/command-result` | Hosted shell commands | Embedded has separate controls and keybindings | Hosted reserves these names. `/command-result <submission ID>` reads an existing execution. `/interrupt` can target an acknowledged Session command |

Embedded screen routes take eligible local actions before prompt submission.
The mixed Embedded catalog retains its existing Session-first display order.
An entry that shares a local route can still delegate to that local route
when its raw input matches the local grammar. In the Session runtime, extension handlers already
ran before builtins. The catalog now gives the extension priority for
colliding canonical names, so it does not advertise the shadowed builtin
as executable. Hosted keeps its local names reserved and does not offer
shadowed aliases. Hosted reads and executions bind the admitted owner after checking the
current catalog and extension conflicts. Coding contributes LSP through its
existing descriptor and parser.

## AppClient capability

The optional `SessionCommandClientV1` methods use the existing Execution
connection, attachment generation, member identity and Host instance. The
connection still carries its original Execution snapshots and records. A
client can request the extra operations below when connected to this Host
revision.

| Operation | Meaning |
| --- | --- |
| `session/command_catalog` | Current descriptors, aliases, argument hints, source, availability, access mode and prefix completions |
| `session/command_read` | Structured read result for an admitted read-only command. AppService checks the same current Session before and after the read |
| `session/command_submit` | Explicit name and arguments with a caller-owned submission ID. Returns the existing Execution record |
| `session/command_result` | Bounded structured result for an authorized Execution ID. Work status continues to use the existing execution record |

Mutations run through the same registry, Product guard, admission and
settlement owners as ordinary executions. The digest distinguishes a
command submission from a chat submission. Results stay scoped to the current
Session and are retained within the existing instance ledger budget. The
client can use `execution/find_submission`, `execution/get` and
`execution/interrupt` for reconciliation and cancellation. Closing an
attachment stops local waits, and a new attachment can query the accepted
submission in the same Host instance. Restart recovery across Host instances
remains subject to the existing execution contract. The client never
replays an uncertain mutation automatically.

A detached historical preview has no active command runtime. The existing
Resume/R6 activation rules still apply before using commands on a writable
Session. A model must be selected for manual compaction. The reply preserves
the operation outcome if a Product result exceeds the wire budget and marks
the data as truncated.

## Phase two behavior and review

The Hosted model chooser uses the Embedded matching and picker code with the
current AppHost model catalog. The Python client opts in to the existing
thinking hello. The existing selection lock, title settlement and execution
checks remain on the server. A rejected model or reasoning selection retains
the current selection. If default preference persistence fails after the
Session commits its model, the result still reflects the committed model and
the Host logs the preference failure.

Rename calls the standard metadata writer. Its metadata event prompts Hosted
TUI to read the authoritative Mux title. Reattachment and the session directory
use the stored name. A provisional transcript follows its existing first-message
materialization policy. The rename result indicates whether the transcript has
been persisted. An entered rename or LSP stop settles before the execution
slot is released, including after an interrupt request.

Extensions and LSP status use the read route. The Extensions projection
exposes diagnostic codes and omits raw diagnostics, configuration, and source
or manifest locations. The LSP adapter uses Coding's original parser to
classify a stop as a mutation. The catalog projects `readOnly` for the
invocation in `commandPrefix`, which can include arguments. The server checks
the route again before invocation. The existing runtime validates each root
against the Session workspace and only stops its own server. LSP status
retains authorized workspace roots for selecting a stop target.

Codex reviewed and accepted the phase two increment on
`feature/gui-hosted-command-phase-two` from `6740f9c55`. The review covered
command ownership, guarded writes, attachment identity, safe projections and
the existing wire paths. Framed AppClient tests exercised the five commands
with real Session state and a synthetic LSP process transport. The consolidated
offline run passed 2,296 cases and skipped 12. The legacy AppProtocol schema
error vocabulary mismatch and the existing LSP on-demand active-tool
assertion both failed on the unchanged base as well.

Clients can use these operations on the updated Host. Older Host decoders may
close the connection on the command operations introduced in phase one.

## Follow-up

Use the existing lifecycle operations for history selection and deletion next.
Add guarded reload and resource refresh, followed by fork, branch, tree and
import or export. Goal and Plugin shortcuts can follow their existing Product
routes. Extensions that execute work and Prompt or Skill submissions need
their own policy-aware entry points. GUI can use the existing model operations
and the four command operations with the same authority and result handling.

See [GUI Session capabilities](gui-session-capabilities.md) for graphical entries and shared ownership.
