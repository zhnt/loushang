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

## Configure A Provider Credential

Online runs need an API key. Loushang reads it from the environment variable declared by the model catalog entry it resolves, and does not load a `.env` file for you: export the variable in the shell that runs `loushang`.

| Provider | Environment variable |
| --- | --- |
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` (the `coding-responses` endpoint uses OAuth instead) |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Alibaba Cloud DashScope | `DASHSCOPE_API_KEY` |
| Moonshot AI | `MOONSHOT_API_KEY` |
| Kimi Code | `KIMI_CODE_API_KEY` |
| MiniMax | `MINIMAX_API_KEY` |
| Z.AI | `ZAI_API_KEY` |
| Volcano Ark | `ARK_API_KEY` |
| Tencent Hunyuan | `HUNYUAN_API_KEY` |
| Baidu Qianfan | `QIANFAN_API_KEY` or `BAIDU_QIANFAN_API_KEY` |
| StepFun | `STEP_API_KEY` or `STEPFUN_API_KEY` |

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
loushang -p "Reply with the single word: ready"
```

Windows PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

`loushang --list-models` prints the catalog with the provider and endpoint each model resolves through, and `loushang --list-models --list-models-format json` prints the same data as JSON for scripts. When a model needs a credential and none of its variables is set, the error names the variables it looked for (`expected_env`).

Project and example catalogs under `.loushang/models/` may declare their own `apiKeyEnv` / `apiKeyEnvs`; those names replace the built-in ones for that catalog entry.

## Run A First Prompt

```bash
loushang -p "Inspect this repository and summarize what it does."
```

Use `--model` or provider-specific environment variables when you need to select a concrete model route. `--model provider:model` is a short form (`provider/model` is also accepted): it works only when that provider/model pair matches exactly one endpoint. If the same provider/model exists under multiple endpoints, the CLI reports an ambiguity and lists explicit `provider:endpoint:model` alternatives. Use `--model provider:endpoint:model` when you need to choose a specific endpoint, region, lane, or protocol. In catalog keys, `provider` and `model` ids cannot contain `:`, while endpoint ids may contain `:`. Project and example model catalog files can be placed under `.loushang/models/` or passed explicitly where supported.

## Next Steps

- Read the [User Guide](../user-guide/) for sessions, commands, tools, extensions, methods, and diagnostics.
- Read the [Examples](../examples/) page for runnable coding and AI SDK scenarios.
- Read the [Reference](../reference/) page when you need exact CLI and configuration surfaces.
