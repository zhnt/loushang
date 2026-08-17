# Reference

English | [中文](../../zh-CN/reference/)

This page collects reference entry points for current users and contributors.

## CLI

```bash
loushang --help
loushang --version
loushang --list-models
loushang --list-commands
loushang --list-sessions
loushang --list-methods
loushang --show-method <method>
loushang --show-method-plan <method>
loushang --list-skills
loushang --list-plugins
loushang --list-packages
```

## Output Formats

Several list and export commands support machine-readable output:

```bash
loushang --list-models --list-models-format json
loushang --list-sessions --list-sessions-format json
loushang --list-commands --list-commands-format json
loushang --list-methods --list-methods-format json
loushang --show-method <method> --show-method-format json
loushang --show-method-plan <method> --show-method-plan-format json
loushang --list-packages --list-packages-format json
loushang --work-log-inspect .loushang/work/events.jsonl --work-log-inspect-format plans-json
loushang --export session.jsonl --export-format jsonl
```

## Methods

```bash
loushang --method <method> -p "Run this coding task."
loushang --no-method -p "Run without the configured default method."
```

`--method` is supported on prompt/print/json paths and rejected in TUI/RPC modes.

## Work Logs

```bash
loushang --work-log .loushang/work/events.jsonl -p "Run this coding task."
loushang --work-log-inspect .loushang/work/events.jsonl
loushang --work-log-inspect .loushang/work/events.jsonl --work-log-run <run-id>
```

Supported inspect formats: `text`, `json`, `plans`, `plans-json`.

## Packages

```bash
loushang --install-package <source>
loushang --uninstall-package <source>
loushang --materialize-package <source>
loushang --update-package <source>
loushang --update-packages
loushang --check-package-updates
```

## Command Execution

```bash
loushang --command <command-name> --command-args "<args>"
loushang --command <command-name> --command-result-format json
```

## Slash Commands

Built-in interactive commands include:

```text
/settings /model /scoped-models /export /import /share /copy /rename
/session /terminal /tools /changelog /hotkeys /fork /clone /tree
/new /compact /resume /delete /reload /quit
```

`/new` starts an empty session in the current context and accepts no arguments.
`/delete` opens a confirmed picker for deleting a previous session; it never deletes the active session.

## Authentication Migration

Coding no longer owns an authentication lifecycle. API key models resolve the
environment variables declared by their model catalog entries when AI requests
are executed. The Coding CLI no longer accepts `--api-key`, and the built-in
command catalog no longer includes `/login` or `/logout`.

SDK callers must remove uses of `loushang.coding.control.AuthManager`,
`AuthResolution`, the `auth_manager=` service/session argument, and the
`oauth_provider_registry=` session argument. Coding does not acquire, refresh,
persist, or select OAuth credentials. Applications that require OAuth must
provide a current request-ready credential through the AI or Agent API rather
than through Coding.

## TUI

- [TUI Runner](tui-runner.md): public lifecycle entry point for terminal apps built with `loushang.tui`.
- [TUI Editing](tui-editing.md): reusable TextInput, Composer, selection-aware editing, keybindings, and playback smoke checks.
- [TUI Widgets](tui-widgets.md): reusable buttons, choices, fields, forms, select lists, and modal dialogs.
