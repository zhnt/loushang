# Examples Design Roadmap（online 优先）

本次重设计目标：在 `examples/coding` 上建立一条“可复现 + 可观察 + 组件覆盖全”的示例路线。  
约束：以 online 为主（脚本默认可联网可观测），离线能力保留为 fallback 验证层；组件覆盖对齐 pi-mono 的 SDK/Extension/Skill/Config 语义。

## 1. 设计三件事（每个例子都必须先给出）

1. **学习目标（Goal）**  
   - 该例子验证什么：会话、路由、工具、扩展、配置、RPC、compaction 或会话生命周期中的哪一个能力。

2. **运行形态（Mode）**  
   - `online` 为默认。  
   - 纯本地能力保持 `offline` fallback（例如本地 session 落盘、extensions 离线脚本、RPC 查询）。

3. **观测点（Signals）**  
   - 输入：`resolved catalog`、模型元信息（provider/endpoint/base_url/model）  
   - 调用：`message.start/end`、`model.start`、`tool.start/end`  
   - 持久化：`.loushang` 会话落盘与恢复、生成文件  
   - 异常：错误码、返回码、错误文本  
   - 指标：usage / cost / 账本或命令日志

## 2. 组件覆盖现状与规划

- `sdk-*`：会话、model、路由、重试、鉴权（现有 1-23 覆盖核心）
- `ext-*`：生命周期与 hook（现有离线+在线扩展样例）
- `skill-*`：新增生成式序列（补齐 pi-mono 的 skill 语义）
- `model-*`：新增生成式序列（补齐 provider/endpoint/兼容协议）
- `provider-*`：新增生成式序列（补齐自定义 provider、OAuth、streaming、payload）
- `config-*`：新增生成式序列（补齐 settings/env/model catalog/session）
- `run-*`：会话管理、会话落盘、恢复、导出链路（离线核验）
- `rpc-*`：RPC mode、命令与会话状态查询能力
- `cmd-*`：用户命令面（slash/prompt/skill/extension 的发现、解析、路由与执行）
- `interaction-*`：简单交互与对话策略
- `prompt-*`：系统提示词策略
- `tools-*`：工具链（bash/write/tool list）
- `ui-*`：UI/render/status/editor/overlay 的文本与事件投影适配
- `git-*`：checkpoint、auto-commit、dirty repo guard
- `compaction-*`：compaction 策略
- `stepwise-*`：step-by-step 编码链路（无渲染）

具体 pi-mono 示例逐条映射见 `PI_MONO_COVERAGE.toml`，该文件是后续补脚本的任务源。

## 3. 当前执行路径（推荐）

1. `uv run python examples/coding/init_examples_env.py`
2. `run.py list --category sdk --tag generated`

## 4. 后续生成执行约束

这份路线可以交给较弱模型或批量生成工具继续展开，但需要固定边界：

- 每个示例先写“学习目标、运行形态、观测点”，再写脚本逻辑。
- 默认优先 `online`，但必须保留可解释的 `offline expected sample`。
- 所有示例统一打印 `resolved catalog`、模型路由、关键事件、成功标准。
- `rpc-*` 只覆盖 RPC mode 与机器接口，不承载用户命令语义。
- `cmd-*` 只覆盖 slash/prompt/skill/extension 命令发现、解析、路由与执行。
- `tools-*` 只覆盖工具注册、工具调用、工具权限、工具结果与工具观测。
- `prompt-*` 只覆盖系统提示词、提示词继承、注入顺序与格式约束。
- `skill-*` 需要覆盖注册、发现、匹配、调用、失败回退和与 command 的关系。
- `provider-*` 只覆盖自定义 provider 与鉴权/streaming/payload，不替代 `model-*` 的 catalog/route 例子。
- `ui-*` 默认做文本/事件投影适配；不能迁移的 TUI overlay/game/editor 细节标记为 `deferred` 或 `not_applicable`。
- `git-*` 必须离线优先，避免默认执行 destructive git 操作。
- 新脚本不要直接堆长流程，先实现最小可复现路径，再补可观测输出。
3. `run.py run <id>` 按目标能力线性推进
4. 每个例子记录三件事：目标、关键事件、是否在线/离线通过

## 4. 下一步动作（建议顺序）

1. **先补齐文档化规范**
   - 用本文件作为统一验收模板，每个新样例需有明确目标与观测点。
2. **把 `legacy-*` 统一迁移到目标命名**
   - 先保留兼容路径（不影响现有运行）。
   - 再通过 manifest 增加新 id 方案（例如 `sdk-legacy-001` / `ext-legacy-001`）。
3. **把 online 入口统一到 pi-mono 对齐路径**
   - 通过 `model-*`, `skill-*`, `config-*` 系列覆盖组件短板。
4. **阶段性验证**
   - 每加一个系列，先跑 3 个 smoke（成功路径/失败路径/离线 fallback）。
