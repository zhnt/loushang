# ARD-006: TUI + Method Integration Constraints and Preconditions

## Status

Accepted

## Context

`loushang code` 当前有两条独立的能力线：

1. **TUI 线**：`loushang.coding.ui` 基于 `loushang.tui` native terminal core，提供交互式终端体验。近期活跃开发集中在 transcript reader/copy、composer selection、playback harness、cursor diagnostics。
2. **Method / Work 线**：`loushang.method` 提供 `MethodDescriptor`/`MethodPlan`/`MethodStep`/`MethodProjection`；`CodingDomainApp` 将方法编译为 `CodingDomainPreparedTurn` 序列；non-interactive CLI path（prompt/print/json）已可按 fixed linear plan 逐步执行，并通过 `loushang.work` 记录 `WorkRun`、`WorkPlan*`、`WorkStep*` lifecycle。

当前 CLI 明确禁止 TUI mode 与 `--method` 共用：

```python
# src/loushang/coding/cli/__main__.py
if args.tui:
    return "--method is not supported in TUI mode"
```

随着 TUI 基础能力趋稳、method/work 基础执行语义成型，出现以下需要明确的问题：

1. TUI + method 是否应该在近期打通？
2. 如果暂不打通，前置条件是什么？
3. 打通后的目标体验是什么？
4. 哪些过渡方案是明确禁止的？

## Decision

### 1. TUI + method 暂不打通，保持互斥

当前 TUI mode 与 `--method` 的互斥是**架构层面的正确选择**，不是临时限制。互斥的原因不是 method 缺少基础 step 语义，而是 TUI 仍围绕单次 `session.prompt()` 生命周期和 session/screen event rendering 工作，尚未具备 method plan projection、step 状态展示、step-level 干预和 replay 对齐。

### 2. 打通需要三个前置阶段

#### Phase 1: TUI 基础稳定（当前进行中）

TUI 必须达到以下稳定状态：

- native terminal core：render loop、resize、input handling、surface overlay 无已知 flicker/corruption
- transcript：reader/copy、composer selection、markdown/thinking/tool rendering 完整
- playback：composer completion、selection、cursor diagnostics 回归覆盖
- lifecycle：startup、resume、abort、queue、steer/follow-up 状态机正确
- 验收标准：单 prompt TUI 会话（无 method）通过 playback/diagnostic 回归；resize、abort、steer/follow-up 不损坏 scrollback、composer state、pending queue；长会话 smoke 可稳定运行 30+ 分钟

#### Phase 2: work-log / method step 语义完成硬化

`loushang.work` 和 `loushang.method` 必须达到以下状态：

- `WorkEvent` 投影层：`AgentEvent -> WorkEvent` 的转换规则稳定，`delivery_hint`（immediate/coalesce/final_only）语义稳定
- method plan / step 事件：`WorkPlanStarted`、`WorkPlanCompleted`、`WorkPlanFailed`、`WorkStepStarted`、`WorkStepCompleted`、`WorkStepFailed` 作为 `WorkEvent.kind` 稳定存在
- step deviation：以 `WorkStepDeviation` 结构化元数据记录在 step payload / projected `WorkStepRun` 中，不定义独立的 `step_deviation` event kind
- work event log：`JsonlEventLogBackend` 可完整记录和回放一次 method plan run
- headless method 可用：`--method` 在 print/json mode 下可运行完整多步骤 plan，work log 可重建运行过程
- failure hardening：assistant-level `stop_reason="error"` / `stop_reason="aborted"` 等失败语义必须投影为 `WorkStepFailed` / `WorkPlanFailed`，不能误记为 completed
- 验收标准：一次 `MethodPlan` run 的 `WorkEvent` 序列可通过 `work-log-inspect` 完整重建，包含每步状态、deviation、artifact 引用

#### Phase 3: TUI + method 打通（目标方向）

在 Phase 1 和 Phase 2 完成后，解除 TUI/method 互斥，实现：

- TUI 的 method status layer 消费 `WorkEvent` / `WorkPlanRun` projection；过渡期 transcript/tool rendering 可继续消费 session/screen events
- TUI 显示 method step 进度：当前步索引、总步数、步骤标题
- TUI 支持 step-level 干预：step cancel/abort、step steer、step retry
- TUI 显示 step deviation 和 approval gate
- TUI 支持 step artifact 预览和导航
- 验收标准：method-driven coding session 在 TUI 中可运行、可观测、可干预，work event log 可完整回放

### 3. 打通后的目标 TUI 体验

#### Method Step 进度指示

```
┌─ Method: refactor-extract-service ─────────────────┐
│ Step 2/5: Identify extraction boundaries           │
│ [=====>                    ] 40%                   │
└────────────────────────────────────────────────────┘
```

或更轻量的 footer/status 集成：

```
Status: Running • Step 2/5: Identify extraction boundaries • 3m 12s
```

#### Step 状态转换可视化

TUI transcript 中每步的开始/结束应有可辨识的标记：

- `WorkStepStarted`：在 transcript 或 method status layer 中插入 step divider，显示步骤标题和约束
- `WorkStepCompleted`：标记步骤完成，显示验收结果
- `WorkStepDeviation` metadata：高亮显示偏离信息，提示用户干预
- `WorkStepFailed`：错误标记，提供 retry/skip/abort 选项

#### Step-Level 干预

当前 TUI 的 abort 是整轮 abort（取消当前 `session.prompt()`）。Method 打通后需要：

- **step cancel/abort**：取消当前步骤，记录 step/plan 状态；不隐式回滚 transcript、文件系统或工具副作用
- **step steer**：在当前步骤内发送 steering message
- **step retry**：以新的 step attempt 重新执行当前步骤；如需回到步骤开始前状态，必须依赖单独的 checkpoint/transaction 设计
- **plan abort**：取消整个 method plan

这些操作通过 TUI 的 composer/surface 系统暴露，不直接操作 `AgentSession`。

#### Approval Gate

Method step 可声明 `approval_gates`。TUI 需要：

- 在 step 开始前或特定工具调用前显示 approval 请求
- 提供 confirm/deny/edit 选项
- 记录 approval 结果到 `WorkEvent`

### 4. 明确禁止的过渡方案

以下方案在 Phase 3 之前**明确禁止**，因为它们会制造技术债务和错误用户预期：

#### 禁止 A：每步重启 TUI

```
# 错误方案
for step in prepared_turns:
    run_coding_tui(...)  # 每步启动新 TUI 进程
```

原因：TUI state（transcript history、composer buffer、pending queue）在步骤间丢失，用户体验断裂。

#### 禁止 B：伪方法化（Fake Methodization）

```
# 错误方案
# 把 method guidance 注入 prompt，但 TUI 不感知 step 边界
# 用户看到的是连续对话，没有步骤进度
```

原因：用户无法区分 method 步骤边界，无法干预步骤执行，method 的"可运行、可观测、可验证"价值被消解。

#### 禁止 C：TUI 直接消费 `CodingDomainApp.prepare_turns()`

```
# 错误方案
# TUI 直接遍历 prepared_turns，每步调用 session.prompt()
# 但 TUI 的 running/abort/queue 状态与 method step 没有衔接
```

原因：`ScreenCodingEventProjector` 和 `CodingUiController` 假设一次交互运行对应一个 `session.prompt()` 生命周期。虽然 non-interactive CLI 已能按 step 调用多次 prompt 并写入 work log，但 TUI 的 running flag、active_task、pending queue、composer state、surface overlay 还没有与 plan/step attempt 生命周期对齐；直接遍历 `prepared_turns` 会让 abort/steer/retry 行为不可预测。

#### 禁止 D：通过 CLI 参数绕过互斥

```
# 错误方案
# 修改 _effective_tui() 让 --method 时仍进入 TUI
# 或修改 _method_runtime_error() 解除互斥检查
```

原因：互斥检查不是防御式编程的过度保守，而是当前架构不支持的诚实表达。绕过检查只会把错误推迟到运行时。

### 5. 当前互斥检查的位置与语义

互斥检查位于 `src/loushang/coding/cli/__main__.py`：

```python
def _method_static_error(args: CliArgs) -> str | None:
    ...
    if args.tui:
        return "--method is not supported in TUI mode"
    if args.mode == "rpc":
        return "--method is not supported in RPC mode"
```

和：

```python
def _method_runtime_error(args: CliArgs, *, effective_tui: bool) -> str | None:
    ...
    if effective_tui:
        return "--method is not supported in TUI mode"
```

这些检查在 Phase 3 完成前**不得移除**。Phase 3 完成后的移除条件：

- [ ] `WorkEvent` 投影层和 `work-log-inspect` plan replay 已完成 failure hardening
- [ ] TUI method status layer 已消费 `WorkEvent` / `WorkPlanRun` projection
- [ ] transcript/tool rendering 与 method status layer 的 event 边界已明确，过渡期允许 session/screen events 与 WorkEvent projection 并存
- [ ] TUI 的 abort/queue/steer 状态机已支持 step-level 语义
- [ ] method step 的 `WorkStepStarted` / `WorkStepCompleted` / `WorkStepFailed` 以及 deviation metadata 在 TUI 中正确渲染
- [ ] 回归测试覆盖：method plan 在 TUI 中完整运行、abort、steer、replay

## Rationale

1. **TUI 当前假设单 prompt 生命周期**：`ScreenCodingEventProjector`、`CodingUiController`、`ScreenCodingTuiState` 都围绕一次 `session.prompt()` 设计。method 的多步骤 `prepared_turns` 打破这个假设。

2. **Method 在 non-interactive path 已有窄 run protocol，但 TUI 尚未接入**：`CodingDomainApp.prepare_turns()` 可返回带 `method_id`、`plan_id`、`step_id`、step policy metadata 的 prepared turns；CLI 通过 work shell 逐步执行并记录 lifecycle。TUI 目前仍只能看到用户 prompt 与 session/screen events，不能可靠呈现 plan/step attempt 边界。

3. **WorkEvent / WorkPlanRun projection 是 method UI 的正确中介层**：TUI 的 method status layer 不应直接消费 `MethodPlan` 或裸 `prepared_turns`，而应消费 `WorkEvent` / `WorkPlanRun` projection。底层 transcript/tool rendering 可在迁移期继续使用 screen/session events，直到 channel/work 边界进一步稳定。

4. **禁止过渡方案比允许更关键**：每步重启 TUI、伪方法化、直接消费 prepared_turns 等方案看似能快速 demo，但会制造深层债务。用户一旦形成"TUI 支持 method"的预期，后续修正成本极高。

## Consequences

### Positive

- 保护 TUI 和 method 两条线的独立演进空间
- 防止技术债务：不会有"半吊子 method TUI"需要后续重写
- 明确 Phase 2 的验收标准：work event log 可重建 method run，并正确区分 completed / failed / aborted
- 为 Phase 3 的 TUI + method 体验提供清晰的设计目标

### Negative

- 短期内用户无法在 TUI 中使用 method
- 需要额外工作量完成 Phase 2 硬化（assistant-level failure projection、replay/schema 稳定性）
- 竞品可能有"TUI 方法引导"的演示功能，产生市场感知差距

## Impacted Documents

- `docs/internals/architecture/coding/ARD-001-coding-product-boundaries.md`（method 定位）
- `docs/internals/architecture/coding/ARD-005-rpc-mode-transitional-channel-positioning.md`（RPC 与 method 互斥）
- `docs/internals/architecture/drafts/loushang-work-method-channel-harness-architecture.md`（WorkEvent 语义）
- `docs/internals/architecture/tui/native-terminal-core/README.md`（TUI 事件消费边界）

## Impacted Code

- `src/loushang/coding/cli/__main__.py`（互斥检查保留）
- `src/loushang/coding/presentation/tui/screen.py`（未来需与 method status projection 明确边界）
- `src/loushang/coding/interaction/controller.py`（未来需支持 step-level 干预）
- `src/loushang/coding/ui/screen_app.py`（未来需支持 method step 状态显示）
- `src/loushang/coding/domain/app.py`（未来需暴露 method step 运行时状态）
- `src/loushang/work/types.py`（需保持 WorkStep/WorkPlan lifecycle 与 deviation metadata schema 稳定）

## Follow-up

- [ ] Phase 1 验收：定义 TUI 稳定性测试套件（30+ 分钟运行、resize、abort、steer）
- [ ] Phase 2 设计：补齐 `AgentEvent -> WorkEvent` failure projection 规则文档
- [ ] Phase 2 设计：固化 `WorkStepStarted`、`WorkStepCompleted`、`WorkStepFailed` 与 `WorkStepDeviation` metadata schema
- [ ] Phase 2 验收：headless method run 的 work event log 可完整重建
- [ ] Phase 3 设计：TUI method step 进度 UI 草案（footer vs overlay vs transcript divider）
- [ ] Phase 3 设计：step-level cancel/abort、steer、retry 的 TUI 交互方案；明确不提供隐式 rollback
- [ ] 在 `loushang.work` 或 `loushang.method` 的 TODO 中记录：method step 的 approval gate 需与 TUI approval presenter 对接
