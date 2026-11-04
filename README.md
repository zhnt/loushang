# Loushang

English | [中文](./README.zh-CN.md)

Loushang is a method-native AI work system for running complex work from intent to verified delivery.

Current focus: `loushang code`, a CLI and terminal workbench for software development with model routing, persistent sessions, tools, extensions, and method-guided delivery.

## Why Loushang

Modern AI agents can plan and act, but complex work still breaks down when context is lost, execution cannot be resumed, tools are hard to govern, and results are not verified.

Loushang treats methods, stages, roles, tools, sessions, and work products as runtime objects. The goal is not just to make agents smarter, but to make complex work more reliable, recoverable, auditable, and deliverable.

Method is the work contract, work is the runtime fact, agent is the execution kernel, ai is the model access layer, harness is the cross-product substrate, coding is the V1 product surface, tui is the terminal presentation, and channel is the boundary protocol—together organizing complex knowledge work into a runnable, recoverable, verifiable, and evolvable system.

## What You Can Use Today

- `loushang code`: a coding-focused CLI and terminal workbench.
- `loushang.ai`: a provider-aware AI SDK with model registry, streaming, tool calls, and cost helpers.
- Sessions: persistent coding sessions with resume, fork, export, and diagnostics.
- Tools: built-in coding tools and configurable tool surfaces.
- Extensions: project-level extension hooks, custom tools, dynamic resources, and commands.
- Methods and skills: method-guided coding turns and reusable workflow assets.

## Quick Start

Loushang is in early development. The recommended path is to run it from source.

```bash
git clone https://github.com/zhnt/loushang.git
cd loushang

uv venv .venv
source .venv/bin/activate
uv pip install -e ".[dev]"

loushang --help
loushang --list-models
loushang --list-commands
loushang -p "Inspect this repository and summarize what it does."
```

You can also run `make bootstrap`, which creates `.venv/` with `uv` and installs the project in editable development mode. The Makefile does not currently provide a `make install` target; use `make bootstrap` for local development or `make install-binary` for a local binary install.

Before the first online run, set a provider API key in the environment; [Getting Started](./docs/en/getting-started/#configure-a-provider-credential) lists the variable for each built-in provider.

For local development in this repository, use the project virtual environment in `.venv/`.

## Core Concepts

- Method: a structured work contract that defines roles, phases, workflow, constraints, artifacts, and acceptance expectations for a class of work.
- Session: a durable coding conversation and execution record that can be resumed, forked, exported, and inspected.
- Tool: an executable capability made available to the agent under policy.
- Extension: project-level Python code that can contribute hooks, tools, resources, commands, and flags.
- Model provider: a concrete AI provider endpoint and model resolved through the model catalog.

## Documentation

- [Documentation Home](./docs/en/)
- [Getting Started](./docs/en/getting-started/)
- [User Guide](./docs/en/user-guide/)
- [Concepts](./docs/en/concepts/)
- [AI SDK](./docs/en/sdk/)
- [Examples](./docs/en/examples/)
- [Reference](./docs/en/reference/)

## Examples

- [Coding examples](./examples/coding/) show CLI/session/tool/extension scenarios.
- [AI SDK examples](./examples/ai/) show model lookup, complete, stream, tools, and typed contexts.

## Roadmap

- V1: `loushang code` as the primary product surface for software development work.
- V2: `loushang work` as a personal complex-work workbench, with `code`, `research`, and `ppt` as specialized flows.
- V3: daemon, method market, and model gateway foundations.
- V4: team workflows, shared runs, approvals, budgets, and audit.
- V5: managed runtime for method-bound complex work.

## Project Status

Loushang is in active early development.

The current stable focus is `loushang code` and the underlying `loushang.ai` SDK. Broader work surfaces such as `loushang work`, `loushang research`, and `loushang ppt` are part of the roadmap and should be treated as evolving product directions.

## Contact

Loushang was initiated by Heng Zhou. He has long worked across low-code systems, workflows, databases, model-driven engineering, DSLs, architecture methods, systems engineering, and artificial intelligence, with a focus on operationalizing ontology and methodology into infrastructure for complex-work delivery.

For questions, feedback, collaboration, or a community group invitation, contact: zhnt@foxmail.com.

## Acknowledgements

Loushang learns from public design and engineering patterns in projects such as OpenAI Codex, pi, python-prompt-toolkit, browser-use, Kimi CLI, superpowers, gstack, openclaw, and hermes-agent. These projects are references and inspiration; unless listed in `THIRD_PARTY_NOTICES.md`, this repository does not include or redistribute their code.

## License

Loushang is licensed under the Apache License 2.0 unless a file states otherwise.

When redistributing source code, binaries, documents, or modified versions, keep `LICENSE` and `NOTICE`, and retain attribution in product documentation, About/Credits pages, or equivalent third-party notices.

Third-party dependency information is available in [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).
