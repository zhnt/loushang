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

Inside the interactive surface, built-in slash commands include `/session`, `/resume`, `/fork`, `/clone`, `/tree`, `/tools`, `/extensions`, `/export`, `/compact`, `/reload`, and `/quit`.

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
