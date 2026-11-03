# Goal 最小闭环：三项待用户评审的决定

- Authority: proposed — decision brief, not an accepted component/API design。
- Design status: draft；Implementation status: not-started。
- Owner：Loushang architecture / Product composition。
- 基线：`372cde4ade0fe026076c8fa5e8b4486774b09cc3`。
- 方法：本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

这份提纲把[能力清单](support-capabilities.md)的 D1/D2/D4 收敛为三个可讨论的选择，
保留[用户对重要工作件的评审要求](README.md)。现有环境图仍待评审；本页不代替
组件图、完整状态/交互合同或 D3/D5/D6，更不据此开始 Goal 实现。

候选闭环是：创建目标→按照 Method 或模型规划选择下一批工作→既有 Work 执行→
读取运行事实和产物证据→决定继续、等待、暂停或完成。Work 执行与目标完成的
判断分别归属；[HW-KD-002](../harnesswork/key-designs/evidence-handoff.md)只补证据交接。

## 1. 目标身份、状态和寿命（D1）

建议第一轮先限定：Goal 有自己的稳定身份，绑定一个逻辑 Conversation；在同一
会话重开时可读取历史目标。一个会话先只允许一个活动 Goal，保留多个历史目标。
不在第一轮承诺跨 Conversation 转移或多目标并行；这些限制是待评审的产品范围，
不是现有 Work 并发闸门自然提供的能力。

| 必须决定的事项 | 候选处理及含义 |
| --- | --- |
| 状态权威 | Goal 领域记录拥有目标要求、版本、控制状态和完成决定；Work/Transcript 仍拥有各自事实。不复制完整运行和消息日志 |
| 状态与终态 | 候选考虑 active/paused/completed/abandoned/failed/superseded；集合及合法转移待评审。执行失败不自动让 Goal failed，终态必须有领域理由 |
| 修改要求 | 区分追加、修订、撤回；显式记录用户改变了哪些要求。路线调整不得自动改写目标；已有计划/证据是否仍适用需重新判断 |
| 身份与寿命 | Goal id 不等于 session id、method id 或 run id；逻辑会话可跨本地进程重开，跨会话/hosted 连接和控制恢复另明确，不由“可读历史”推导 |
| 存储选择 | 复用现有 journal 基础，但目标记录与 Work/Transcript 的 authority、提交失败和兼容合同尚待设计；不预设同事务或通用第三账本平台 |

验收责任归 Goal/领域要求侧：不能单独按 reported_step_id 或通用投影的
current_step_id 判断覆盖了某一步要求。Product adapter 从当前 WorkExecutionContext
取步骤自报值，但原 publish 不验证它，仍不是 kernel 证明。需要更强步骤归属时，
必须补足证据/合同后再判满足，不能用两个字段相等代替核验。

若需要同会话多活动 Goal 或跨会话目标，必须同步比较调度、输入归属、预算、证据
authority 和恢复成本。当前 Session 的单活动 Work 约束不会自动给出这些答案。

## 2. Method、模型计划与 Work 批次（D2，牵涉 D3）

建议将“下一步如何选”作为 Goal 的策略差异，共用既有执行路径：

- Method 指导方式：保留方法身份及必要步骤/约束，由方法语义指导工作选择。
- 模型规划方式：模型提出或修订计划，Goal 侧组织核验后受理下一批工作。
- 两种方式都提交既有 Work；规划或验收若调用模型/工具，也走现有能力与授权边界。

建议路线可以随证据变化，但每次受理的计划修订和执行批次留下不可改写的历史；
优先通过下一批 Work 表达调整，不在正在执行的 WorkRunSpec 中修改步骤。
MethodPlan 的静态 `plan:{descriptor.id}` 只表示现有方法计划身份，不能单独承担
跨运行的唯一身份；Goal 记录自身计划修订与原 operation 的关联，operation→run
解析仍由 HarnessWork 负责。

计划准入至少要说明：覆盖哪些要求、遵守哪些 Method 要求、具备哪些可用能力，
以及权限/预算能核查到什么范围。还要区分结构错误、证据不足和需要用户决定。
这些判据及失败处理尚未接受；不把提示约束说成通用语义证明器，也不替代真实
工具调用的授权。不能先写自动 planner，再事后补准入 owner。

计划准入还应由 Goal/Method 与领域 owner 在受理本批前明确应提供哪些证据，以及
缺失/可选的处理；不能从 completed 或空报告列表推导“无需证据”。验收消费还须
兼顾既有 WorkStepDeviation.evidence_refs：旧字符串支持材料与新持久报告并存，
显式 Product 绑定可以解析到同一材料，未解析时保留 unresolved；不按引用条数
计算独立证明，不把现有字段误称为已实现的通用 Blob resolver。

## 3. 自动推进、用户输入与唤醒（D4，牵涉 D6）

建议以“一次推进决策→受理一批 Work→取得事实→下一次决策”为粒度，复用既有
Session、Agent loop、输入队列和 Host 执行能力。Goal 不另建输入队列或 Agent loop。

| 情形 | 待接受的交接要求 |
| --- | --- |
| 用户追加/steer/follow-up | 先按原输入路径处理，明确何时影响目标/当前批次/后续批次；不自行抢占或复制输入 |
| Work 结束后续跑 | 事件是可能的唤醒提示；真正受理前重新核对目标状态、输入和当前 Work。Host 的 idle 观察不能独自承担完整合同 |
| 暂停/放弃/恢复 | 分开记录停止派发、执行取消、领域报告和未知效果；新取消观察可提供证据，但不能直接证明全部外部动作已收尾 |
| 重开和 hosted 入口 | 先读历史并核对；需要谁唤醒、谁有控制权限、哪个 profile 真正支持自动推进，应在入口交互图明确。不能仅凭“重开可读”自动重放 |

第一轮应先选一个真实入口做纵向闭环，候选从本地 SDK/现有 Product 装配开始。
具体 Product composition owner 负责选定消费任务、reader/subscriber 和验收判据；
私有适配位置随该 Product 的既有边界确定，HarnessWork owner 核对中立引用合同。
是否需要离线后台或跨连接自动推进另作产品选择，不能默认引入持久调度服务。

## 与本轮证据专项的关系

HW-KD-002 只要求显式会话 authority 和既有 Work，因而可以先独立设计与评审。
它保存快照引用和领域报告，不决定 Goal 状态、计划语义或验收算法；尤其不能从
available、validation 标签或 Work completed 推导目标完成。

本页三个方向仍待用户评审；完整 Goal 开发前，还须结合现有环境图明确组件、
关键接口、失败路径、D3/D5/D6 及需求追溯，并做组合复核。专项内部通过不是这些
事项的自动接受，也不把后续范围偷偷加入独立底座的实施清单。
