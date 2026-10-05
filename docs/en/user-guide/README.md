# User Guide

English | [中文](../../zh-CN/user-guide/)

The user guide explains the product surfaces that are currently relevant for `loushang code`.

## CLI And TUI

`loushang` is the main CLI entry point. It supports one-shot prompt runs, text/print/json/rpc modes, session controls, model listing, command listing, diagnostics, tools, extensions, skills, methods, packages, export, and work logs.

Use `loushang --tui` to start the terminal UI product surface when you want an interactive coding session. The installed `loushang-tui` command is a convenience entry point for the same TUI mode.

TUI mode has two runtime surfaces. With TTY stdin/stdout, `loushang --tui` and
`loushang-tui` open the screen surface. With piped or redirected stdio under
`--tui`, the same mode uses the plain prompt loop, which is useful for smoke
tests:

```bash
printf "hi\n/quit\n" | loushang --tui
```

There is no separate UI selector flag for plain output. Use `--tui` and let
terminal interactivity choose the surface.

Useful starting commands:

```bash
loushang --help
loushang --list-models
loushang --list-commands
loushang --list-sessions
loushang --tui
loushang-tui
loushang -p "Summarize the current project."
```

For building terminal UI applications with `loushang.tui`, see [Building TUI Apps](tui.md).

In the conversation screen, click **Show Detail** or **Show Less** to expand or
collapse one tool result. Direct SSH sessions request mouse reports by default,
even when the remote host cannot write to your local clipboard. In that case,
copying selected text reports that the clipboard is unavailable. Set
`LOUSHANG_TUI_OSC52=1` only if your terminal accepts OSC 52 clipboard writes,
or set `LOUSHANG_TUI_MOUSE_POLICY=terminal` to keep the terminal's native mouse
selection instead of clickable controls. Inside tmux, turn on its `mouse`
option to forward clicks; with that option off, use F4 and Enter to operate
detail controls from the keyboard. In Apple's Terminal app, enable **View →
Allow Mouse Reporting**; the app cannot receive clicks when that terminal
setting is off. `/terminal` shows `mouse_mode_active` and
`mouse_event_observed` for diagnosis.

For the Linux background named-Mux development preview, see the [lmux guide](lmux.md),
including storage, reconnection, and upgrade limitations.

### Explicit Hosted Application

`loushang-hosted` is an opt-in foreground stdio server for an application
launcher, not another interactive prompt loop. Existing CLI/TUI commands are
unchanged. Start with `loushang-hosted --help`.

Supply `--workspace`, `--application-root`, `--cwd-sessions`, and
`--home-sessions` explicitly. The workspace and application-root parent must
exist; the three storage directories must be separate. The application state
directory must be private (0700 on POSIX); an absent leaf is created privately.
Add `--describe` to inspect path-free scope selectors without starting or
writing anything. Removing that flag starts the framed protocol over pipes,
not newline-delimited text; use a `StdioAppClientV1`-based launcher.

The same application ID (default `coding.default`), workspace and storage roots
restore the saved mux/member/Session state after shutdown. EOF terminates this
foreground application. Active turns, approvals and attachment authority are
not resumed. There is no daemon, network listener or automatic reconnect.
See the [G14 contract and delivery status](../../internals/architecture/appserver/foreground-stdio-hosted-app-g14.md)
for client composition, native-platform validation and integration status.

## Sessions

Sessions preserve the coding conversation and execution record. They are designed for workflows that need resume, fork, export, diagnostics, and later inspection.

Common actions:

```bash
loushang --list-sessions
loushang --resume
loushang --continue
loushang --resume <session-id-or-path>
loushang --export
```

Interactive `loushang --resume` and argument-free `/resume` open the full-screen
searchable continuity picker. By default, Space opens a lazy preview, Tab cycles
available domains when several providers are installed, and Ctrl+S changes the
common sort. `--continue` resumes the newest session in the current project,
while `--resume <session-id-or-path>` and `/resume <session-id-or-path>` restore
a specific session directly. Non-interactive use requires one of those explicit
forms.

Inside the interactive surface, built-in slash commands include `/session`, `/resume`, `/fork`, `/clone`, `/branch`, `/tree`, `/tools`, `/extensions`, `/export`, `/compact`, `/reload`, and `/quit`. `/fork` duplicates the current chat into a new session, `/clone` is a compatibility alias, and `/branch` opens a prompt picker for branching from an earlier user message.

## Tools

Tools expose executable capabilities to the agent. The coding product includes built-in tool surfaces and options for enabling, disabling, and narrowing tools:

New interactive sessions enable the built-in `read`, `ls`, `find`, `grep`, `bash`, `edit`, and `write` tools by default. Prefer `ls`, `find`, `grep`, and `read` for file exploration; keep `bash` for shell behavior such as pipelines, redirects, build commands, tests, and Git operations.

```bash
/tools
/tools off bash
/tools only read,ls,find,grep
/tools reset
loushang --tools bash,write -p "Inspect this project."
loushang --no-tools -p "Explain the repository from context only."
```

### Architecture Analysis Tool

`coding.arch` provides the bounded `inspect_import_graph` tool. It defaults to
`on_demand`; activate it for a Coding Session with:

```bash
loushang --capability coding.arch=always \
  -p "Use inspect_import_graph to summarize this repository's dependencies."
```

For deterministic analysis without a model or Session, use the standalone
module CLI:

```bash
uv run python -m loushang.coding.arch src/loushang \
  --package-prefix loushang --query summary --pretty
```

Both surfaces keep roots inside the selected workspace. `--no-tools` and
`coding.arch=disabled` skip the Arch Plugin entirely.

### LSP Semantic Tools

`coding.lsp` is an optional, high-frequency Coding capability that provides
`inspect_symbol` and `document_outline`. It defaults to `on_demand`; make the
tools part of the agent's default tool set for one invocation with:

```bash
loushang --capability coding.lsp=always
loushang lsp status
loushang lsp doctor
```

Servers still start lazily on the first semantic query. `status` and `doctor`
have `scope=catalog`: they only inspect configuration and executable
availability, and never construct a Session, start a Server, or install one.
Loushang probes installed Pyright, TypeScript Language Server, rust-analyzer,
gopls, and clangd defaults.

The TypeScript preset covers `.ts`, `.tsx`, `.js`, `.jsx`, and their standard
module variants. It chooses the nearest `tsconfig.json`, `jsconfig.json`,
`package.json`, or `.git` root. Install both `typescript-language-server` and a
compatible `typescript` package yourself; when either usable server setup is
absent, ordinary Coding tools continue to work and Loushang does not install
packages automatically.

The other defaults choose the nearest language-native project root: Pyright
uses `pyrightconfig.json` or `pyproject.toml`, rust-analyzer uses
`rust-project.json` or `Cargo.toml`, gopls uses `go.work` or `go.mod`, and clangd
uses `.clangd`, `compile_commands.json`, or `compile_flags.txt`. Each also falls
back to the nearest `.git` root.

Inside an interactive Coding Session, use the separate Session-local surface:

```text
/lsp status
/lsp stop <server-id> <root>
```

`/lsp status` reports only Servers known to that Session, including lifecycle,
open-document, request, timeout, replacement, and discarded-publication counts.
It is read-only and does not start a Server. `/lsp stop` gracefully shuts down
the exact Session-owned Server; the next semantic query may start a replacement.
Embedding code can use `session.get_lsp_status()` and
`await session.stop_lsp_server(...)` over the same bounded snapshot. The TUI
executes the same Session command directly. RPC clients can discover it with
`get_commands` and execute it without a model turn:

```json
{"id":"lsp-status","type":"execute_command","command":"lsp","args":"status"}
```

The response carries the command's structured result under `data.result`.

Contributors with `pyright-langserver` already on `PATH` can run the optional
real-server gate with `uv run pytest
tests/integration/coding/test_pyright_lsp_live.py -q`; it skips when Pyright is
absent and never installs it.

The corresponding TypeScript gate is `uv run pytest
tests/integration/coding/test_typescript_lsp_live.py -q`. It looks for
`typescript-language-server` on `PATH` by default, or accepts an executable via
`LOUSHANG_TEST_TYPESCRIPT_LANGSERVER`; it also never installs the Server.

The gopls gate is `uv run pytest
tests/integration/coding/test_gopls_lsp_live.py -q`. It looks for `gopls` on
`PATH` or uses `LOUSHANG_TEST_GOPLS`; installation remains a separate developer
or CI step.

The rust-analyzer gate is `uv run pytest
tests/integration/coding/test_rust_analyzer_lsp_live.py -q`. It looks for
`rust-analyzer` on `PATH` or uses `LOUSHANG_TEST_RUST_ANALYZER`; contributors
should install a matching stable toolchain, `rust-analyzer`, and `rust-src`
through rustup.

Declare a custom server in `~/.loushang/coding/lsp.json`:

```json
{
  "servers": [
    {
      "id": "python-custom",
      "command": ["my-language-server", "--stdio"],
      "language_extensions": {"python": [".py", ".pyi"]}
    }
  ]
}
```

Project `.loushang/lsp.json` may tune a Product default or a server already
declared by the user. Until the general workspace-trust mechanism exists, a
repository config cannot introduce a new executable or environment override.

## Extensions

Extensions are Python files that can register lifecycle hooks, tools, dynamic resources, commands, and flags. Start with the runnable extension examples in [examples/coding/extensions](../../../examples/coding/extensions/).

An extension may include an adjacent `loushang-extension.toml` manifest to declare identity, permission level, dependencies, and expected runtime surfaces. Use `/extensions` to inspect loaded extensions, surface summaries, and diagnostics; use `/extensions <id>` for one extension. `/tools` includes source information for extension-provided tools when available.

## Packages And Plugins

Packages and plugins can contribute reusable coding assets. Common lifecycle commands:

```bash
loushang --list-plugins
loushang --list-packages
loushang --install-package <source>
loushang --check-package-updates
loushang --update-packages
```

On Linux, a fresh workspace with no prior Plugin state or legacy Plugin/Package settings can be switched offline to the fenced Product store:

```bash
loushang-package-cutover --workspace /absolute/path/to/workspace
```

Stop its Loushang processes first; the command also refuses a live pre-fence writer. The existing Loushang private home must be owned by you and inaccessible to other users; the command does not change its permissions. It installs the checked-in base, LSP, and architecture Plugins through Product transactions and can be retried after interruption. It refuses workspaces that need legacy-state adoption or settings migration. Once fenced, use a fence-aware Loushang version; an older runtime cannot safely write the workspace.

Pre-B workspaces containing old Plugin state, settings, Sources, or Package Store members are unsupported by this Product path. The ordinary cutover command refuses them before creating a B fence or changing the old workspace. Create a fresh workspace for the Product Plugin path; already fenced B workspaces can be reopened by a fence-aware version. The historical legacy review and adoption commands remain in the CLI but are not a supported migration route for this candidate.

On Windows, the fresh-workspace cutover is an explicit candidate command. Stop Loushang processes first, then run:

```powershell
loushang-package-cutover --workspace C:\path\to\workspace --windows-candidate
```

The command refuses old Plugin state and legacy Plugin/Package settings before creating a B fence. The ordinary Windows Session route is still separate from this candidate command; `--windows-candidate` does not change its default selection.

For a POSIX Package operation interrupted during staging, use the exact operation ID to inspect its checkpoint and request the narrow Product recovery:

```sh
loushang-package-repair --workspace /absolute/path/to/workspace inspect-staging <operation-id>
loushang-package-repair --workspace /absolute/path/to/workspace repair-staging <operation-id>
```

Both actions activate Product recovery and open a runtime lease. `inspect-staging` does not select a repair for the requested operation. `repair-staging` selects and executes within one lease, returns a nonzero exit status unless the operation commits, and refuses changed Source, an active old lease, or mismatched staging evidence.

For a `transaction_pinned` operation with no staging effect yet, use `repair-pinned <operation-id>` instead. Product rechecks the retained pin and Source before selecting and executing under one new lease. Do not use it for an operation with a staged receipt; that state uses `repair-staging`.

For an A2 operation still marked `retryable_failure`, the separate `repair-retryable` action uses the Product's cross-runtime Source, cleanup, and lease checks before selecting and executing one retry. It returns a nonzero exit status unless the operation commits:

```sh
loushang-package-repair --workspace /absolute/path/to/workspace repair-retryable <operation-id>
```

For an abandoned active attempt, choose the action matching its Package phase. Each action checks the old lease and Source, settles the exact interrupted attempt through Product, and then selects and executes one retry under the same new runtime lease:

```sh
loushang-package-repair --workspace /absolute/path/to/workspace repair-unstarted <operation-id>  # classified or acquiring
loushang-package-repair --workspace /absolute/path/to/workspace repair-acquired <operation-id>   # acquired, inspecting, or extracted
loushang-package-repair --workspace /absolute/path/to/workspace repair-resolving <operation-id>  # resolving_closure
loushang-package-repair --workspace /absolute/path/to/workspace repair-verified <operation-id>   # closure_verified
```

These actions refuse a mismatched phase, changed Source, or live prior lease and return nonzero unless Product commits. If a run stops after the old attempt becomes `retryable_failure`, use `repair-retryable` for that exact operation. Pinned and staged states use the separate actions above; later transaction states still need Product recovery. This is not a general Package repair command.

If an update committed but its Package handoff stopped before the terminal receipt, recover that exact operation without activating general Package recovery:

```sh
loushang-package-repair --workspace /absolute/path/to/workspace repair-handoff <operation-id>
```

Product requires a terminal handoff for the requested operation ID. An unknown ID does not recover another pending operation. This action does not repair an earlier A2 transaction phase.

Local Python operators can use `open_coding_package_repair_client(workspace)` from `loushang.coding.package_product_repair` and call `client.perform(action, operation_id)`. The typed result exposes `committed` and a pathless `to_dict()`; `inspect-staging` returns checkpoint evidence without a committed disposition. This is a Coding management API, separate from the Plugin author SDK.

In the Coding Screen or plain TUI, `/plugins repair-package repair-retryable <operation-id>` invokes the same explicit Product repair action without sending a model prompt. Replace `repair-retryable` with one of the other actions above only when its Package phase matches. The current Session keeps its selected resources; start a new Session after a committed repair. This command is separate from `/plugins repair <operation-id>`, which repairs a pending Desired State command.

On Linux, immutable Plugin roots in a fenced workspace have a separate offline GC command. Stop all Loushang Sessions first. `prepare` recovers Product transactions and durably seals GC writers; it is a one-way maintenance step. `list` shows exact candidate and reservation IDs without filesystem paths. Copy an exact candidate ID to delete one root:

```bash
loushang-package-gc --workspace /absolute/path/to/workspace prepare
loushang-package-gc --workspace /absolute/path/to/workspace list
loushang-package-gc --workspace /absolute/path/to/workspace delete --candidate-id <candidate-id> --attempt-key <your-attempt-key>
```

Keep the attempt key to repeat the same request safely. If deletion started but did not settle, use the reservation ID shown in the result or `list` with a new attempt key:

```bash
loushang-package-gc --workspace /absolute/path/to/workspace retry --reservation-id <reservation-id> --attempt-key <new-attempt-key>
```

This command deletes only the exact immutable Plugin root. It leaves Plugin private data untouched and makes no claim that backups have expired.

On Windows, offline GC for an already fenced B workspace requires the explicit candidate flag. Stop Loushang Sessions, then prepare and list candidates before deleting one exact ID:

```powershell
loushang-package-gc --workspace C:\path\to\workspace --windows-candidate prepare
loushang-package-gc --workspace C:\path\to\workspace --windows-candidate list
loushang-package-gc --workspace C:\path\to\workspace --windows-candidate delete --candidate-id <candidate-id> --attempt-key <your-attempt-key>
```

The same `--windows-candidate` flag applies to `retry` with the durable reservation ID. Unflagged Windows GC commands refuse before opening Product state. Retained Worker history must have completed its Product retirement before `prepare` admits Package GC.

On Linux, the separate `loushang-plugin-private-data` command handles the Installation-owned cache of `coding.arch.default`. Stop all Coding Sessions. `backup` copies and verifies that exact cache under an independent Installation backup root; `backup-status` reports `retained` only while the archive still verifies:

```bash
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup > arch-backup-receipt.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup-status
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup-verify --backup-id EXACT_BACKUP_ID_FROM_RECEIPT
```

After the Plugin's Desired State is `absent`, save a deletion preview and enter its exact `fingerprint` value in a separate confirmation command:

```bash
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default preview > arch-plan.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default confirm --plan-file arch-plan.json --accept-fingerprint EXACT_FINGERPRINT_FROM_PLAN > arch-confirmation.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default delete --plan-file arch-plan.json --confirmation-file arch-confirmation.json
```

The delete command rechecks the exact data target, separate confirmation, removed Desired State, and absence of active Product Sessions. Repeating the same command returns its durable receipt. Backup retention is projected separately and remains `retained` after source deletion. `backup-verify` reopens the exact archive named by the receipt, even after source deletion, and refuses tampered bytes.

After the Installation is removed and its data deletion has a completed receipt, preview the exact backup restore and accept its fingerprint to restore into an empty data root. The command refuses changed existing data and can replay the same plan after an interrupted restore:

```bash
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default restore-preview --backup-id EXACT_BACKUP_ID_FROM_RECEIPT > arch-restore-plan.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default restore --plan-file arch-restore-plan.json --accept-fingerprint EXACT_FINGERPRINT_FROM_RESTORE_PLAN
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default restore-confirm --backup-id EXACT_BACKUP_ID_FROM_RECEIPT > arch-restore-confirmation.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default restore-confirm-verify --backup-id EXACT_BACKUP_ID_FROM_RECEIPT --confirmation-id EXACT_CONFIRMATION_ID
```

Run `restore-confirm` after restoration. It rechecks the archive, completed deletion and restore records, and the restored bytes before writing a separate durable confirmation. Verification refuses a changed restored tree. This Arch Installation confirmation is not a migration restore-test receipt.

After confirmation, preview the exact archive and restored-data evidence. Save the plan, separately accept its fingerprint, then expire only that backup:

```bash
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup-expiry-preview --backup-id EXACT_BACKUP_ID_FROM_RECEIPT --confirmation-id EXACT_CONFIRMATION_ID > arch-backup-expiry-plan.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup-expiry-confirm --plan-file arch-backup-expiry-plan.json --accept-fingerprint EXACT_FINGERPRINT_FROM_EXPIRY_PLAN > arch-backup-expiry-confirmation.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup-expire --plan-file arch-backup-expiry-plan.json --confirmation-file arch-backup-expiry-confirmation.json
loushang-plugin-private-data --workspace /absolute/path/to/workspace --plugin-id coding.arch.default backup-status
```

`backup-expire` permanently deletes the verified archive. It requires the Installation to remain removed, the confirmed restored data to remain unchanged, and no active Product Sessions. An interruption leaves `expiry_pending`; repeat the same command to recover. A completed expiry reports `expired` with an independent receipt ID. The restored Installation data remains in place. Other Plugin data types and Windows are not admitted.

For a Product that has already admitted a dependency-bearing Wheel, `list` also shows `dependencyRetention`. After every holder root has a verified deletion, an `exact_target` row gives the dependency ref and settlement IDs. Use those exact IDs to delete the orphan; if deletion started without a result, retry its durable start ID:

```bash
loushang-package-gc --workspace /absolute/path/to/workspace delete-dependency --dependency-ref-id <dependency-ref-id> --settlement-id <settlement-id> --attempt-key <your-attempt-key>
loushang-package-gc --workspace /absolute/path/to/workspace retry-dependency --start-id <start-id> --attempt-key <new-attempt-key>
```

Coding's current local-data Wheel policy does not admit dependency-bearing Wheels. These commands do not expand that admission policy.

## Methods And Skills

Methods and skills turn reusable working practices into runtime assets. In the CLI, use:

```bash
loushang --list-methods
loushang --show-method <method>
loushang --show-method-plan <method>
loushang --method <method> -p "Run this coding task."
loushang --no-method -p "Run without the configured default method."
loushang --list-skills
```

`--method` is supported for non-interactive prompt/print/json paths. It is intentionally rejected in TUI and RPC modes until the method step UI and work-event projection path are ready.

## Work Logs

Work logs record `WorkOperation` and `WorkEvent` entries for one-shot prompt/print/json runs:

```bash
loushang --work-log .loushang/work/events.jsonl -p "Run this coding task."
loushang --work-log-inspect .loushang/work/events.jsonl
loushang --work-log-inspect .loushang/work/events.jsonl --work-log-inspect-format plans
```

`--work-log` is not supported in TUI or RPC modes.

## Diagnostics And Export

Diagnostics and exports help inspect what happened in a session:

```bash
loushang --list-diagnostics
loushang --diag-export --diag-output diagnostics.json
loushang --export session.html
```
