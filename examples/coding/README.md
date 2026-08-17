## Coding Examples

`examples/coding/` contains `loushang-coding` 的可执行示例与一个统一入口。

### 一键初始化

执行以下命令可一键生成示例运行所需的本地骨架：

```bash
cd /home/dev/workspace/loushang
uv run python examples/coding/init_examples_env.py
```

会默认创建（并写入说明）：

- `examples/coding/.loushang/`：运行时根目录
- `examples/coding/.loushang/sessions/`：会话落盘目录
- `examples/coding/.loushang/extensions/`：示例扩展文件目录
- `examples/coding/.loushang/models/`：可选自定义模型 catalog 目录

建议将该目录和你的示例会话一起提交为“本地运行环境脚手架”，从其他机器 `git pull` 后再跑一遍初始化即可重建同结构，脚本输出可直接执行的推荐环境变量和命令。

可选参数：

```bash
python examples/coding/init_examples_env.py --help
python examples/coding/init_examples_env.py --dry-run
python examples/coding/init_examples_env.py --copy-model-catalog --overwrite
```

`--copy-model-catalog` 只用于需要本地定制时复制内置 catalog 快照；常规示例直接使用
`src/loushang/ai/model/models.json`，无需复制。

### 统一运行器

从 bash 执行：

```bash
cd /home/dev/workspace/loushang/examples/coding
python run.py list
python run.py list --category sdk
python run.py list --tag toolset --count
python run.py run legacy-001
python run.py run legacy-001 --dry-run
```

参数说明：
- `list`: 列出示例。支持 `--category`/`--tag`/`--query`/`--count`/`--json`
- `run <id|slug>`: 运行指定示例，支持透传参数到原始脚本
- `--json`: 机器友好输出

`run.py` 基于 `example-manifest.toml` 统一管理 232 个示例（包含：
37 个可执行脚本 + 195 个生成示例）。

### 直接运行单个示例

`run.py` 是推荐的统一入口，但不是强制入口。现有脚本都可以直接执行，适合调试单个例子或临时传参：

```bash
cd /home/dev/workspace/loushang
uv run python examples/coding/21_switch_model_route.py
uv run python examples/coding/22_usage_inspect.py --endpoint kimi-code-anthropic --strict
uv run python examples/coding/25_render_tool_events_contract.py
uv run python examples/coding/extensions/01_lifecycle.py
uv run python examples/coding/arch/01_import_graph.py
```

架构分析示例直接使用公共 `loushang.coding.arch` API；更多说明见
[`arch/README.md`](arch/README.md)。仓库自动化使用的 `scripts/arch` 入口不作为用户示例。

如果已经激活本仓库虚拟环境，也可以直接用 `python`：

```bash
cd /home/dev/workspace/loushang
source .venv/bin/activate
python examples/coding/21_switch_model_route.py
```

直接运行时需要注意：

- 建议从仓库根目录执行，保证 `src/loushang` 能被当前环境解析。
- 如果出现 `ModuleNotFoundError: No module named 'loushang'`，优先使用 `uv run python ...` 或激活 `.venv`。
- 需要自定义模型 catalog 时，可通过环境变量传入：`LOUSHANG_EXAMPLES_MODEL_CATALOG=examples/coding/models`。
- 需要会话/产物目录时，可设置：`LOUSHANG_EXAMPLES_ARTIFACT_ROOT=examples/coding/.loushang`。
- `run.py run <id|slug>` 额外提供 manifest 查询、dry-run、统一环境变量透传和脚本参数透传；直接运行则更接近“脚本原生行为”。

### 设计路线（online 优先 + 可复现）

从 `coding` 侧这套路线继续往下走，采用三个锚点：  
- 学习目标：每个例子先定义“验证哪个能力是否成立”。  
- 运行形态：默认走 `online`，能离线验证的例子保留 `offline` fallback。  
- 观测点：每个示例都要能输出 `message/start/end`、`tool.start/end`、`resolved catalog`、会话文件变化、错误码与返回摘要。  

建议执行时按 `pi-mono` 风格阅读映射：
- `sdk-*`：SDK 与模型通路（会话构建、鉴权、路由、重试、降级）
- `ext-*`：扩展生命周期与 hook
- `skill-*`（新增）：Skill 注册、发现、调用与回退
- `model-*`（新增）：provider/endpoint/模型参数一致性与健康检查
- `provider-*`（新增）：自定义 provider、OAuth、payload、streaming 与降级
- `config-*`（新增）：settings/env/catalog/session 的配置一致性
- `run-*`：运行器语义、会话恢复与落盘
- `rpc-*`：RPC mode、命令与会话查询面
- `cmd-*`（新增）：slash/prompt/skill/extension 命令发现、解析、路由与执行
- `interaction-*`：简单交互
- `prompt-*`：系统提示词
- `compaction-*`：compaction 策略
- `ui-*`（新增）：UI/render/status/editor/overlay 的文本与事件投影适配
- `git-*`（新增）：checkpoint、auto-commit、dirty repo guard
- `tools-*`：工具链（bash/write/tool list）
- `stepwise-*`：无渲染分步编码

说明：当前生成型入口新增了 `model/skill/config`，用于补齐 pi-mono 组件齐全性；实际脚本先对齐现有 25 个（`legacy-*`）后再逐步迁移 id 命名。

更完整的路线说明见 [EXAMPLE_DESIGN_ROADMAP_2026-05.md](/home/dev/workspace/loushang/examples/coding/EXAMPLE_DESIGN_ROADMAP_2026-05.md)。

主题前缀（按生成+既有脚本）：
- `sdk-*`：SDK 相关
- `ext-*`：extensions 相关
- `model-*`：模型通路（provider/endpoint/catalog）
- `provider-*`：自定义 provider 与鉴权/streaming 适配
- `skill-*`：skill 生命周期与调用
- `config-*`：配置、环境变量与会话路径
- `run-*`：run 体系
- `rpc-*`：RPC mode 与命令查询面
- `cmd-*`：用户命令面（slash/prompt/skill/extension）
- `interaction-*`：简单交互（simple_interaction）
- `prompt-*`：系统提示词
- `compaction-*`：短窗口 compaction
- `ui-*`：UI/render/status/editor/overlay 适配
- `git-*`：Git 集成与安全守卫
- `tools-*`：toolsets
- `stepwise-*`：step_by_step_coding（无渲染）

pi-mono 覆盖跟踪见 [PI_MONO_COVERAGE.toml](/home/dev/workspace/loushang/examples/coding/PI_MONO_COVERAGE.toml)。覆盖状态含义：

- `covered`：已有可运行 loushang example 验证同一学习目标。
- `partial`：已有能力域覆盖，但缺少专门脚本或关键观测点。
- `planned`：已进入 manifest/coverage，尚未实现具体脚本。
- `deferred`：依赖 loushang 核心能力或 UI 形态，暂缓。
- `not_applicable`：pi-mono TUI/平台细节，不迁移为 coding 主线示例。

### 可复现流程

建议流程（任何机器上可复现）：

```bash
cd /home/dev/workspace/loushang
uv run python examples/coding/init_examples_env.py
export LOUSHANG_EXAMPLES_ARTIFACT_ROOT=examples/coding/.loushang
uv run python examples/coding/run.py list --count
```
默认模型 profile 已调整为：

- `coding_primary` => `provider=kimi-code`, `endpoint=kimi-code-anthropic`, `model=kimi-for-coding`

**3 秒判断：默认/显式**
- 默认走 `kimi-code/kimi-code-anthropic`（Anthropic 兼容协议）。
- 显式指定 `kimi-code-openai` 时走 OpenAI 兼容协议。
- Kimi Code 两条协议都支持 `k3`（当前旗舰）和 `kimi-for-coding`（K2.7）；示例 profile 暂时固定 `kimi-for-coding` 以保持可复现。
- `KIMI_MODEL_NAME` 仅作为模型名提示变量；在示例缺省路径里不会强制切换 endpoint。

说明：`provider:endpoint:model` 中的 `endpoint` 只接受 registry 中的 endpoint id。
Kimi Code 在内置 catalog 中提供 `kimi-code-openai` 与 `kimi-code-anthropic` 两条路由。

未指定 `--model-catalog` 时，示例只读取内置 catalog。仓库不再提供会遮蔽内置配置的
Kimi Code 示例 catalog。

补充：Kimi Code 使用自己的模型 ID：当前旗舰写 `k3`，K2.7 coding 路线写 `kimi-for-coding`，不要写 Moonshot 平台的 `kimi-k3` 或旧的 `kimi-k2.5`。

### Kimi 环境变量模板（按你这个模型名）

如果你要用 Kimi 官方建议的模型名：

```bash
source examples/coding/kimicode.env.example
```

模板内容（可按需改）：

```bash
export KIMI_CODE_API_KEY="sk-xxx"
export KIMI_MODEL_NAME="kimi-for-coding"  # 缺省路径下仅作兼容变量，不影响 endpoint 选择
```

注意：`KIMI_CODE_API_KEY` 与 Moonshot 开放平台的 `MOONSHOT_API_KEY` 分属不同
provider 配置，示例不再交叉回退到 Anthropic、OpenAI 或 Moonshot 平台 key。

如果你不想每次都手工设置环境变量，也可以在运行时直接指定参数：

```bash
python examples/coding/run.py --artifacts-root examples/coding/.loushang \
  --session-dir examples/coding/.loushang/sessions \
  --extensions-dir examples/coding/.loushang/extensions \
  list --count
```

若只想跑单个脚本，不依赖仓库根目录约定，可直接进入目录：

```bash
cd /home/dev/workspace/loushang/examples/coding
python run.py run legacy-001
```

为避免 `import loushang` 解析失败，`run.py` 在执行子示例时会自动注入仓库 `src` 到 `PYTHONPATH`。
你在仓库其他机器上 `git pull` 后，只要按同样路径运行就能直接启动：

```bash
cd /home/dev/workspace/loushang
python examples/coding/run.py run legacy-001
```

建议采用固定目录约定（都放在仓库内，便于 pull 后复用）：

- `~/<repo>/examples/coding/.loushang/`：示例运行时总目录（本仓库默认）。
- `~/<repo>/examples/coding/.loushang/sessions/`：会话落盘目录（默认值，对应 `persist=True` 的示例）。
- `~/<repo>/examples/coding/.loushang/extensions/`：示例扩展文件可存放目录（供需要读取本地扩展时使用）。
- `~/<repo>/examples/coding/.loushang/models/`：可选模型清单目录；只有显式选择该目录时才作为覆盖 catalog。
- `~/<repo>/examples/coding/models/`：自定义 catalog 示例位置；仓库不在这里提供默认 provider 数据。
- `~/<repo>/.loushang/settings.json`：可选本地配置（如需覆盖模型/提示词/会话目录时）。

`run.py` 的运行时约定会透传如下环境变量给子进程：

- `LOUSHANG_EXAMPLES_ARTIFACT_ROOT`
- `LOUSHANG_EXAMPLES_EXTENSIONS_DIR`
- `LOUSHANG_EXAMPLES_SESSION_DIR`
- `LOUSHANG_EXAMPLES_MODEL_CATALOG`（当前支持 json 文件或目录）

你可以把自定义目录固定到仓库内，跨机器 pull 后重用：

```bash
cd /home/dev/workspace/loushang
export LOUSHANG_EXAMPLES_ARTIFACT_ROOT=examples/coding/.loushang
export LOUSHANG_EXAMPLES_MODEL_CATALOG=examples/coding/models
python examples/coding/run.py list --count
python examples/coding/run.py run legacy-001
```

`LOUSHANG_EXAMPLES_MODEL_CATALOG` 不设时，示例 helper 会优先读取：
`<artifacts-root>/models/`（目录）；
`<artifacts-root>/models.json`（文件）；
找不到再回退到内置 `src/loushang/ai/model/models.json`。

`models.xx.json` 这类模型清单建议放在示例目录的 `models/` 下（例如 `examples/coding/models/`），
并在需要时通过：

```bash
python examples/coding/run.py run legacy-014 --model-catalog examples/coding/models
```

来使用；默认仍为 `src/loushang/ai/model/models.json`。

Kimi Code 的 provider、两条兼容协议路由以及 `k3`、`kimi-for-coding` 模型都由内置
catalog 维护。`init_examples_env.py --copy-model-catalog` 仅复制该内置文件作为用户
定制快照，不会再叠加示例目录中的 provider 模板。

若你习惯在 `examples/coding` 目录直接运行，也可直接执行：

```bash
cd /home/dev/workspace/loushang/examples/coding
python run.py list --count
python run.py run legacy-007
```

会话与模型目录的执行优先级为：
1) CLI 参数（`--session-dir`/`--artifacts-root`/`--model-catalog`）
2) 对应环境变量（`LOUSHANG_EXAMPLES_SESSION_DIR` 等）
3) 默认路径（`~/<repo>/examples/coding/.loushang`）

### 现有脚本总览

### Main Path

- `01_minimal.py`: smallest online session with a custom calculator tool
- `02_custom_model.py`: use a manually selected model
- `03_custom_prompt.py`: customize the system prompt
- `04_builtin_bash_tool.py`: enable the built-in bash tool
- `05_model_with_builtin_bash.py`: combine a custom model with built-in tools
- `06_nl_with_builtin_bash.py`: natural-language tool usage with bash
- `07_offline_session_restore.py`: offline runtime, persist, and restore a session
- `08_online_resume_repo_session.py`: resume a repo session against a real model
  - use `--timeout <seconds>` to avoid long hangs when the model endpoint is slow/unreachable
- `09_print_mode_text.py`: run `PrintMode` in text projection
- `10_print_mode_json.py`: run `PrintMode` in JSON projection, optionally with rendered tool events
- `11_cli_commands.py`: exercise CLI command list/execute flow
- `12_cli_session_surface.py`: exercise CLI session naming/listing/export flow
- `13_rpc_mode_probe.py`: exercise RPC mode discovery and lightweight state mutation flow
- `14_simple_code_writer.py`: simple natural-language coding request that writes files through bash
- `15_simple_write_tool.py`: minimal natural-language coding request that writes files with the write tool only
- `16_write_tool_trace.py`: readable assistant/tool trace for a coding request
- `18_kimi_runtime_matrix.py`: offline matrix of endpoint -> base_url -> api -> model
- `19_session_store_check.py`: verify session persistence and list/index consistency
- `21_switch_model_route.py`: validate route switch across candidate endpoints
- `22_usage_inspect.py`: model usage/cost extraction and unified print format
- `23_kimi_weekly_usage_ledger.py`: local weekly ledger based on response usage, with rolling aggregation and an optional local budget
- `24_git_checkpoint.py`: git stash checkpoint as an AgentTool with offline mock + optional live path
- `25_render_tool_events_contract.py`: offline JSONL example for renderedToolCall/renderedToolResult
- `26_compaction_summary_evaluation.py`: offline summary quality evaluation for compaction output, with optional `--real` model run
- `skill_01_discovery.py`: skill discovery, filtering, and replacement with source ordering
- `skill_02_advanced.py`: disable-model-invocation filtering and system prompt `<available_skills>` XML injection
- `skill_03_precedence.py`: source precedence (project_local > external_package) and same-precedence collision handling
- `skill_04_reload.py`: hot reload skills at runtime without process restart
- `config_01_resource_layers.py`: flat resource architecture four-layer precedence (project > user > external > built-in)

`06_nl_with_builtin_bash.py`, `08_online_resume_repo_session.py`, `09_print_mode_text.py`, and `10_print_mode_json.py` require an explicit `request` argument. Running them without a request prints usage and exits.

### Extension Path

Extension-focused examples live in [extensions/README.md](/home/dev/workspace/loushang/examples/coding/extensions/README.md).

They are intentionally offline and self-contained:

- they create a temporary project directory
- they write an `extensions/*.py` file using the current `register(api)` protocol
- they run a local offline session/runtime to demonstrate the hook or tool behavior

Start there if you want to learn the current `ExtensionAPI v1` surface.

### Commands Status

The command descriptor surface is now test-backed in the core `coding` package and has a dedicated example. It follows the pi-style session aggregation model rather than a standalone command registry class.

Current stabilized pieces:

- RPC `get_commands` delegates to `AgentSession.list_commands()` and can return `extension`, `prompt`, and `skill` entries
- slash-prefixed extension commands are consumed before prompt/skill expansion reaches the model
- queued `steer` / `follow_up` inputs reject extension slash commands instead of executing them later
- extension `input` hooks can `handled` or `transform` user input before prompt/skill expansion
- extension command argument completions are available through the session/runner query surface
- CLI supports extension-registered flags through a two-pass startup parse
- CLI `--session-name` writes session metadata for later introspection and listing
- CLI model listing keeps the default text output and supports `--list-models-format json` for structured consumers
- CLI session listing supports `--list-sessions` with TSV output by default and `--list-sessions-format json`
- CLI command listing keeps the default TSV output and supports `--list-commands-format json` for structured consumers
- CLI command execution keeps raw result output by default and supports `--command-result-format json`
- CLI session export supports bare `--export`, `--export-format html|jsonl`, and `--export-result-format json`
