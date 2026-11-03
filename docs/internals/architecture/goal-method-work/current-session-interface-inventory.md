# 当前会话 Goal：Product / Session 接口盘点

- Authority: descriptive；事实盘点与候选接缝，不是新接口合同。
- Status: 本轮盘点完成；跨入口详细设计、接口接受和实现尚未发生。
- 源码基线：main `e1601d0593085120078e3bc468c07756cb89fb8b`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 范围：用户授权的第1项——梳理已有Product/Session控制接口，确定共同归属和复用接缝。只读源码核查，不新增运行组件、不修改产品代码、不运行模型。

## 1. 结论

两种TUI装配应复用Harness负责的通用Goal与Session协同机制：嵌入式路径本地调用；lmux路径经原AppService适配后调用。Coding提供领域策略和装配参数。AppService不是嵌入式调用的必经层。

**修订说明：上一稿把现有代码的位置当作未来职责归属，误将共同业务整体放在Coding Product。按用户纠正重新盘点：通用协同下沉Harness；Goal状态与Work执行仍留HarnessWork；Coding保留领域策略。** 这是本轮确认的职责方向，不是已实现的共同入口；详细接口与迁移方案仍待设计评审。

共同能力不是一个新的执行内核。Harness组合原Session受理、生命周期、模型调用边界及HarnessWork Goal；不能新增平行输入队列、Goal事实账本或Work引擎。当前不存在已核实可直接使用的通用会话Goal接入组件。

当前两条普通对话路径已经有复用基础，但尚未形成对一个既有交互Session随时启用Goal的共同业务入口。已有托管Goal闭环不等于这项接入已经完成。

## 2. 当前路径与证据

| 路径 / 层次 | 已有入口与事实 | 可以复用 / 不可外推 |
| --- | --- | --- |
| 嵌入式Coding TUI | [product_binding.py](../../../../src/loushang/coding/ui/product_binding.py)的build_coding_ui_controller，通过build_coding_session_operation_resolver获得当前操作，命令执行前重新解析当前Session；标准ConversationUiController处理输入意图 | 复用当前Session解析、命令路由及UI结果展示；尚无共同Goal动作合同 |
| TUI会话动作 | [control.py](../../../../src/loushang/harnesstui/conversation/control.py)的ConversationActionHost；[controller.py](../../../../src/loushang/harnesstui/conversation/controller.py)的ConversationUiController | 普通输入/中断展示可复用；该动作接口不能被视为已支持Goal创建/修订/恢复 |
| lmux普通对话 | [conversation_binding.py](../../../../src/loushang/harnesstui/mux/conversation_binding.py)的HostedConversationActionBinding实现共享会话动作，捕获attachment/generation/member，借用AppClient；返回投递状态 | 沿用原绑定和过期结果保护；Ack不是Work完成或Goal成功 |
| AppService Session | [ports.py](../../../../src/loushang/appservice/ports.py)的HostedSessionPortV1含snapshot/subscribe/start_turn/steer/follow_up/interrupt/interaction/close | 托管适配合同；不是嵌入式内核必须伪造的身份或控制对象 |
| 原托管Coding Session | [hosted_session.py](../../../../src/loushang/coding/hosted_session.py)的CodingRealHostedSessionV1.control返回其原AgentSession；claim_execution限制单一执行owner；历史binding无执行控制 | 复用原Session及owner；只读历史Session不可因展示Goal而升级为可执行 |
| 通用Session控制 | [facade.py](../../../../src/loushang/harness/session/facade.py)的SessionControlPort含prompt/steer/follow_up/clear_queue/abort/wait_for_idle等；明确排除Product词汇 | 输入、队列、运行事件复用Harness；不再造Goal队列，不把预算/Method准入塞入通用输入接口 |
| Session生命周期 | [product_runtime.py](../../../../src/loushang/harness/session/product_runtime.py)、[agent_session_runtime.py](../../../../src/loushang/coding/runtime/agent_session_runtime.py)复用原创建/切换/释放装配；Coding runtime已有before_release与子执行清理衔接 | Session创建/替换/释放权不转交给TUI Goal命令；何时停止或挂起关联Goal尚须专项定合同 |
| Goal领域入口 | [goal.py](../../../../src/loushang/coding/adapters/goal.py)的CodingGoal提供create/advance/query及controller；_initialize_borrowed可借用原Session，不负责销毁外部Session | 借用装配是可复用内部接缝；不是面向任意交互Session的公共接入合同 |
| 原托管Goal | [hosted_goal.py](../../../../src/loushang/coding/hosted_goal.py)组合CodingGoal、GoalInvocation与原execution guard；限定真实新binding和固定setup；start_turn拒绝普通对话 | 复用已证明的规划/Work/验收与收尾；不能直接把整个hosted facade套在日常嵌入式Session上 |
| 托管Goal访问 | [goal.py](../../../../src/loushang/appservice/goal.py)的ScopedGoalClientV1借原scope/registry；核对同一Product、instance、绑定及控制权；提供start/find/query/progress/wait/interrupt/retry_settlement | lmux应复用此访问层；interrupt不等于Goal暂停，当前未提供任意目标创建/修订/语义恢复的通用合同 |
| 目标与执行内核 | [controller.py](../../../../src/loushang/harnesswork/goal/controller.py)、[contracts.py](../../../../src/loushang/harnesswork/goal/contracts.py)；Goal状态/修订/策略/验收证明及原Work关联 | 复用GoalController、记录、NextWorkPolicy和GoalAcceptancePolicy；不另建状态机、日志或operation→run映射 |

两条当前调用链可概括为：

```text
嵌入式：Coding TUI → Coding UI binding / ConversationUiController
                   → 当前Session操作解析 → Coding runtime / AgentSession

lmux：共享会话动作 → HostedConversationActionBinding → AppService
                 → HostedSessionPort / Coding Product binding → 原AgentSession

现有托管Goal：ScopedGoalClient → 原Execution绑定及权限检查
             → CodingHostedGoalSession → GoalInvocation / CodingGoal
             → HarnessWork Goal / Work → 原Session
```

这是当前调用关系摘要，不是已接受的新系统环境图，也不声称嵌入式已接通Goal。

## 3. 按职责重新分类

| 能力 | 归属方向 | 已有实现与复用边界 |
| --- | --- | --- |
| Goal与确切Session实例绑定、当前性核对、启停和生命周期衔接 | **Harness通用协同** | 复用SessionControlPort、ProductSessionRuntime及原生命周期owner；绑定Goal资源不意味着取得Session销毁权 |
| 空闲后推进、用户输入优先、关闭或切换时停止新推进 | **Harness通用协同** | [HostRuntime](../../../../src/loushang/harness/runtime/execution.py)已有run_after_idle/defer_run与原run受理，Session已有队列；还须设计Goal条件与原输入/操作的共同受理，不用一次idle观察冒充完整合同 |
| 期限、取消、推进次数、模型调用额度的执行控制 | **Harness通用机制，调用方配置策略** | 从当前混合代码中提炼；原AI调用入口、prepared committer与Transcript用量继续复用，不新建账本。具体默认值、计量范围及可选性待定 |
| Goal身份、要求修订、状态、批次关联、记录、完成依据的结构约束 | **HarnessWork** | 保留GoalController、GoalRecordStore及原Policy接口；Harness不得再维护一份目标状态或完成结论 |
| Work受理、执行、recording、取消观察、operation→run解析 | **HarnessWork** | 原WorkRuntime及其投影继续权威；Harness只组合查询与驱动 |
| 模型规划的一般驱动、响应来源关联 | **通用候选须进一步拆分** | 已有BatchPlanningPolicy及PlanningWork，但其中含Coding事件、Blob helper和固定proposal/schema；不能把整套实现认定为可直接下沉。若抽出机制，候选是Harness编排、HarnessWork提供工作事实，领域提供动作和准入语义 |
| 动作/约束/验证/评审的机制及具体规则 | **机制可共享；规则由方法/任务包声明，Coding提供编码适配** | Method加载/编译复用现有method；准入/证据/执行复用原内核。具体测试集合、文件范围和完成条件不硬编码在共享层，也不必固定在Coding源码；任务包不能扩大宿主权限或预算 |
| 工具、审批、重试/压缩、模型选项 | **复用Harness/AI既有机制，Coding提供领域限制** | Goal不得静默全局关闭普通会话retry/compaction或替换既有工具。profile限制与共享机制分开，何时生效/撤销待设计 |
| 本地动作访问 | **嵌入式薄适配 → Harness共同能力** | 复用当前Session解析，不伪造托管attachment/generation/member；防止旧结果落到新Session |
| 托管访问与控制权 | **AppService适配 → Harness共同能力** | 保留原scope/registry、撤权及绑定检查；AppService DTO不强迫成为Harness内部类型 |
| TUI命令与展示 | **HarnessTUI通用展示，Coding装配领域内容** | UI不拥有续跑loop、业务账本或验收判定；进度有效性沿原观察含义展示 |

共同合同指业务动作和观察含义一致，不要求两条路径共享全部参数。共同能力接在Harness已有组合接缝上；本轮不决定新增公共类名、目录或一个包办全部功能的大组件。

### 3.1 现有Coding代码的拆分候选

| 当前代码 | 可复用/提炼的机制 | 留在Coding或适配层的内容 | 结论 |
| --- | --- | --- | --- |
| [GoalInvocation](../../../../src/loushang/coding/_hosted_goal_work.py) | deadline/checkpoint、在途任务取消与settlement、保留首个停止原因 | calculator名称、repository分支、profile/setup访问；ExecutionOutcomeV1映射属于托管边界 | 拆机制与领域驱动及托管结果映射，不整类搬到Harness |
| [PlanningCallAllowance](../../../../src/loushang/coding/adapters/_goal_planning_limits.py) | await前计数、当前operation归属、限额快照、原stream委托与prepared一致性 | planning/repair阶段集合、proposal.LIMITS、固定provider尝试与hosted字段 | 通用额度机制候选下沉Harness组合层；保留领域限额配置，不复制AI账本或传输层 |
| [CodingGoal](../../../../src/loushang/coding/adapters/goal.py) | borrowed owner、Goal/Work/reader装配和清理的组合经验 | calculator校验、固定文件工具、替换hook限制、规划profile、Coding SDK构造 | 明确借用与拥有差异后提炼通用Session协同；不能将open或_initialize_borrowed直接当公共接口 |
| [hosted_goal.py](../../../../src/loushang/coding/hosted_goal.py) | 原Goal/Work观察组合的输入事实与校验规则 | AppServer DTO、绑定ID、execution claim/guard适配、AppService错误映射 | 通用事实优先复用原HarnessWork查询；托管包装留原边界，不把AppService依赖倒灌Harness |
| [_hosted_repository_work.py](../../../../src/loushang/coding/_hosted_repository_work.py) | checkpoint/阶段驱动调用的组合经验 | verify_current/review_material、仓库快照与冻结机械评审顺序 | 保留仓库业务驱动与策略，通过后续明确合同交给通用协同调用 |
| [SessionExecutionPolicy](../../../../src/loushang/coding/adapters/_goal_execution_context.py) | 复用Harness已有子Session factory/ForkTier/容量/清理 | Coding历史映射、文件工具限制与领域选择理由 | 已有下沉部分继续复用，不能为Goal再实现子Session创建/驱动/清理 |

这些是按源码职责识别的提炼候选，不表示已完成迁移、已经证明独立可用或必须新增上述数量的组件。

### 3.2 两条路径的候选汇合位置

```text
嵌入式 TUI → 本地会话动作适配 ─────────────┐
                                           ├→ Harness Goal/Session通用协同
lmux TUI → 原AppService/托管绑定适配 ───────┘        │
                                                    ├→ 原Session受理/队列/生命周期
Coding profile ──提供动作、Method、验收与配置────────→│
                                                    └→ HarnessWork Goal / Work
```

此图仅说明职责方向，尚非完整系统环境图或已接受接口设计。原会话owner、托管owner及HarnessWork事实权威保持各自职责；通用协同只拥有自己创建的绑定资源和推进任务。

## 4. 已证实的接入缺口

1. **已用Session的安全装配。** CodingGoal.open的模型规划路径要求fresh Session；_initialize_borrowed要求原构造注入相同allowance/tool policy。现有托管应用还在Session构造时安装规划system prompt、模型调用wrapper和工具策略，见[hosted_goal_application.py](../../../../src/loushang/coding/hosted_goal_application.py)。因此“从普通会话启用Goal”不只是增加菜单；须决定既有历史如何使用、模型调用如何纳入预算、工具策略何时生效及退出后如何处理。当前_validate_goal_session还要求原文件工具、拒绝若干替换hook，并在模型规划模式关闭自动retry/compaction；这些profile限制不能直接套用到普通对话，须分别决定保留、隔离或演进，不能静默改变会话行为。
2. **日常输入与Goal的共存。** 现有hosted execution claim排除第二个输入owner，hosted Goal的start_turn拒绝普通输入。需要明确哪些用户输入是steer/follow，哪些是修改要求或暂停，不能直接同时启动两个driver。
3. **控制语义的覆盖。** core已有revise/control等原语，ScopedGoalClient的interrupt是执行中断；pause/resume/edit/clear还未形成两种入口共同的业务合同。不得用名字相似的动作替代它们。
4. **Session切换与关闭。** 原runtime拥有创建/切换/释放；后续应核对现有before_release和清理重试接缝，规定Goal停止推进、在途Work收敛、来源reader释放的顺序。普通关闭失败不能丢掉清理owner。
5. **自动唤醒的受理。** 当前托管Invocation是有限驱动，不能直接外推成普通交互Session的空闲事件续跑。需与当前操作、待处理输入、关闭、控制权和预算共同受理；沿原事件与受理入口设计，不新建Goal输入队列。
6. **观察身份。** 本地current Session引用与托管attachment身份机制不同；要分别阻止旧结果写到新会话。复用现有完整query与轻量progress，后者not_checked不得展示成已验收current。

## 5. 后续专项的输入和决策项

本轮不选择新公共接口名称或模块迁移方式。下一份专项只需围绕上述接缝回答：

- Goal在一个已交互Session中的寿命、基数，以及/new、切换、关闭、恢复的关系。
- 如何复用原模型调用、工具策略和审批边界；Harness现有机制如何承载Goal执行范围，领域配置是否需要可撤销的作用域，或已有装配是否提供其他路径。不得修改已提交的Model Input或重置旧计数。
- 哪些业务动作及只读观察需要共同表达，哪些参数只属于托管适配；如何兼容原冻结profile及旧调用方。
- 空闲唤醒的责任、用户输入优先顺序和并发受理；无法安全受理时应给出什么可解释结果。
- 预算耗尽、中断、暂停、断连和关闭分别如何作用于Goal与原Work；不能把清理完成当业务完成。

建议形成Harness主责、HarnessWork/Coding/AppService/HarnessTUI协同的专项。先确认现有组件复用和源码拆分，再形成完整环境关系、关键交互与失败合同，提交用户评审后实施；具体新合同尚未接受。

## 6. 核查与局限

本轮沿职责/复用、运行/失败、数据/兼容三个方面自查了盘点：通用协同归Harness、领域策略留Coding、状态与执行留HarnessWork；单owner与清理不被绕过；本地身份与托管身份不混用；历史readonly不升级执行。此为作者静态自查，不是三名独立agent评审，也不构成重要架构工作件的用户接受。

未运行测试、并发试验或模型；没有验证新方案的运行行为。当前源码与链接支持事实表；候选接缝是后续设计输入，不将缺失机制写成既有保证。现有271项回归与在线成功证据只适用于原profile，不证明本轮列出的普通会话接入已经实现。

## 7. Method边界与Goal职责质量复核

### 7.1 是否需要harnessmethod

当前已有独立的产品中立[loushang.method](../../../../src/loushang/method/__init__.py)，并非Coding私有方法论：

- [runtime.py](../../../../src/loushang/method/runtime.py)的MethodDomainRuntime接收领域profile，组合发现、显式选择、编译与提示准备。当前mode仅off/explicit，不是自动方法组合器。
- [compiler.py](../../../../src/loushang/method/compiler.py)支持single_turn/fixed计划；[types.py](../../../../src/loushang/method/types.py)提供描述、步骤与计划类型。约束/audit元数据的存在不等于通用约束执行器，expected_artifacts/approval_gates字段也不能推导已具备通用验收。
- [CodingDomainApp](../../../../src/loushang/coding/domain/app.py)已经是MethodDomainRuntime的领域薄适配；Goal中的仓库实施也调用此运行时。
- method的loader/resources依赖Harness frontmatter资源基础；未来Harness组合Method时须核查包依赖方向，不能只按新名称搬文件并形成隐式循环。

| 选项 | 价值与成本 | 本轮建议 |
| --- | --- | --- |
| 保留loushang.method，收敛职责；Harness组合，HarnessWork执行 | 复用现有公共合同，迁移面最小；需补明确的组合接缝 | **优先** |
| 将method整体更名为harnessmethod，旧路径兼容 | 可以统一命名，但不自动增加能力；涉及导入、包边界、文档和下游兼容 | 当前无必要，不能以更名代替职责整改 |
| 保留method并新增独立harnessmethod | 仅当出现独立且稳定的Session方法装配责任时才有意义；容易复制加载/编译和执行内核 | 暂不新增；先用Harness现有组合模块承载适配，证明确有独立职责再评估 |

结论：需要通用Method能力，不需要先增加一个同义组件。Method资源解释归现有method；方法到原Session/Work的绑定属于组合与集成；Work生命周期仍由HarnessWork拥有。

### 7.2 机制、内容、适配的四分法

1. **共享机制：** 方法资源解释、动作注册/准入框架、约束检查接缝、验证/评审调用、证据归属和当前性核对。分别复用method、Harness组合与HarnessWork合同，不要求集中放入一个包。
2. **方法内容：** 所选工作的步骤、专业指导、可声明的约束及检查要求。
3. **任务内容与授权：** 本次目标要求、文件范围、固定测试集合和完成条件由任务合同表达；权限/预算来自用户或可信宿主，方法/模型不得自行扩大。
4. **领域适配：** Coding提供仓库读取、编码工具、测试命令执行和领域结果解释。其他领域提供自己的适配；规则数据化不代表领域语义可以完全消失。

验证器或评审器也不必是纯文本配置；可以通过已注册、受信任的可调用实现提供。加载方法不授权执行任意命令或插件代码。动作集合的声明与运行能力的注册/授权需区分。

### 7.3 当前Goal是否为最佳职责划分

判断：**核心状态与执行分离值得保留；应用装配和有限profile实现尚不是通用Goal的理想职责划分。** 以下是静态架构发现，不推翻已通过的业务验收，也不自动授权代码迁移。

| 发现 | 源码事实 | 影响与整改方向 |
| --- | --- | --- |
| CodingGoal承担过多组合责任 | [goal.py](../../../../src/loushang/coding/adapters/goal.py)同一owner覆盖自建SDK、借用Session、Goal/Work/Blob/reader装配、输入转发及清理 | 先区分owned/borrowed和领域profile，再提炼Harness组合；保留清理失败owner与旧API兼容 |
| 托管执行控制混入领域和传输结果 | [_hosted_goal_work.py](../../../../src/loushang/coding/_hosted_goal_work.py)同时包含期限/取消/收敛、calculator名称/repository分支及AppService outcome | 通用控制候选归Harness；领域步骤由profile提供；结果映射留托管适配；避免整类下沉 |
| 规划“shared”尚非产品中立 | [_goal_planning_shared.py](../../../../src/loushang/coding/adapters/_goal_planning_shared.py)导入Coding事件profile、calculator Blob helper及_proposal的固定LIMITS/schema | 分离响应来源核对、批次准备与领域动作合同；先明确实际依赖，不能靠shared命名推广公共API |
| 示例内容被其他profile复用为基础 | [_goal_proposal.py](../../../../src/loushang/coding/adapters/_goal_proposal.py)包含subtraction/clamp、R-SUB/R-CLAMP等固定动作和要求；repository复用其结构再替换动作 | 结构校验与动作/要求定义解耦；把任务内容从共享机制中移出，保持旧profile解释不变 |
| 仓库策略聚合多个职责 | [_goal_repository.py](../../../../src/loushang/coding/adapters/_goal_repository.py)同时含动作、提示、快照、规划观察、准入、验收、Work适配与SDK入口 | 以稳定合同拆分，不按文件行数机械拆类；领域事实与通用来源/准入骨架分开 |
| 调用预算带profile耦合 | [_goal_planning_limits.py](../../../../src/loushang/coding/adapters/_goal_planning_limits.py)通用计数与固定phase/LIMITS/hosted快照混合 | 共享计数及调用边界；限额及阶段策略注入；不复制原AI账本 |
| 普通Session被有限profile假设约束 | 原Goal验证要求固定工具、限制hook，并关闭retry/compaction；借用装配要求原构造注入wrapper | 设计明确的执行作用域和兼容策略，保留普通会话原有能力，不默默扩大权限或更改已提交模型输入 |
| 核心边界已经正确 | HarnessWork Goal通过NextWorkPolicy/GoalAcceptancePolicy接收策略；Method独立；Session/Work各有原owner | 继续复用，不因上层混杂重写状态机、执行器、队列或事实存储 |

### 7.4 建议顺序

先冻结上述职责与允许的依赖方向；再设计Harness的Session/Goal协同合同及method→Work集成接缝；随后逐个抽离调用控制、owner装配与规划机制，同时让原Coding profile通过适配继续运行。方法/任务内容配置化与通用自然语言Goal是后续范围，不能仅搬包就宣布实现。

本轮推荐保持method包名。若后续独立职责和多个消费者证明确实需要harnessmethod，再作单独决策和兼容迁移。重要环境图/组件交互和新增接口仍待评审，当前没有实施迁移。

## 8. 与重构计划R2协同的边界修正

[重构计划](refactoring-plan.md)的独立评审进一步确认：Harness不得直接导入HarnessWork，本文“组合”指调用中立注入端口；Goal-specific候选、证据发布、状态和策略仍由原上层合同/集成持有。运行关系图不能视为包依赖许可。

普通Session已有SessionWorkRuntime/SessionWorkHostPort，必须复用或明确不兼容拒绝，不能再构造互不知晓active_runs的两个runtime。application-local ScopedGoalClient也不等于真实lmux wire已支持Goal；真实连接/客户端/外壳的Goal能力接入须另行形成可评审合同，详见计划RF-02a/02b和S4a/S4b。本文此前表中lmux已有的是普通会话调用路径，不能外推为Goal入口已可达。
