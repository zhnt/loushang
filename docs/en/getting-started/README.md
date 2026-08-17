# Getting Started

English | [中文](../../zh-CN/getting-started/)

This guide gets you from a fresh clone to a first `loushang code` run.

## Requirements

- Python 3.11 or newer.
- A model provider credential for online runs.
- A terminal environment that can run Python virtual environments.

## Install From Source

```bash
git clone https://github.com/zhnt/loushang.git
cd loushang

uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Equivalent Makefile shortcut:

```bash
make bootstrap
source .venv/bin/activate
```

`make bootstrap` creates `.venv/` with `uv` and installs the project in editable development mode. There is no `make install` target today; `make install-binary` is reserved for building and installing a local binary.

## Check The CLI

```bash
loushang --help
loushang --list-models
loushang --list-commands
```

## Run A First Prompt

```bash
loushang -p "Inspect this repository and summarize what it does."
```

Use `--model` or provider-specific environment variables when you need to select a concrete model route. `--model provider:model` is a short form (`provider/model` is also accepted): it works only when that provider/model pair matches exactly one endpoint. If the same provider/model exists under multiple endpoints, the CLI reports an ambiguity and lists explicit `provider:endpoint:model` alternatives. Use `--model provider:endpoint:model` when you need to choose a specific endpoint, region, lane, or protocol. In catalog keys, `provider` and `model` ids cannot contain `:`, while endpoint ids may contain `:`. Project and example model catalog files can be placed under `.loushang/models/` or passed explicitly where supported.

## Next Steps

- Read the [User Guide](../user-guide/) for sessions, commands, tools, extensions, methods, and diagnostics.
- Read the [Examples](../examples/) page for runnable coding and AI SDK scenarios.
- Read the [Reference](../reference/) page when you need exact CLI and configuration surfaces.
