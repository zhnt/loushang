# Goal 批次执行 Session：独立三视角评审

- Authority: descriptive；日期：2026-10-31；Owner：Coding / Loushang architecture。
- 对象：[GMW-KD-SESSION-02](delegated-session-execution.md)；初审 R1 `267708ef1`，关闭复核 R2 `ee2a1f221ecc39508e5ccb1417488d60450abd54`。
- 方法：干净本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 源码对照：main `64d035620`、Harness 子 Session `3aac81d8e`、原仓库 Goal profile `f024cb734`。这些分支尚未作为一个版本集成验证。
- 三位独立 xhigh reviewer 分别检查职责与复用、运行与失败、数据与兼容；不互读评审结果。此轮只有静态源码/合同核对，没有实现、测试或模型调用。

## R1/R2 历史评审：发现与关闭

| ID | 视角 / R1 发现 | R2 关闭依据 |
| --- | --- | --- |
| DS-O1 阻断 | owner 可以顺序创建多个 Goal，只有“每 owner 一个 child”不能保证每 Goal 新鲜上下文 | 此 Coding 委派 profile 终身绑定一个 Goal ID，终态后新 Goal 仍须新 owner；共享 GoalController 不变，DS-02 覆盖 |
| DS-O2 阻断 | 常规 bind helper 会把子完成通知加入父 mailbox，既绕过 Work 报告又破坏父规划响应证明 | 私有装配原 SessionMultiAgentRuntime，root_input=None、discard；不安装第二个父 runtime。原 control 保留结果，DS-03 覆盖 |
| DS-R1 阻断 | 原 deliver 先入队再返回 triggered_new_round，不能用返回值实现投递前拒绝 | 短投递/取消临界区在投递前核验 exact ref、上轮收敛、残留输入与取消；返回值只复核，一致性失败后停止并收敛已受理动作 |
| DS-C1 阻断 | main 来源读取不支持仓库 policy，不能直接承诺返回 not_declared | 指定原 read_goal_work_sources 的受支持仓库身份窄分支、真实父 reader 与原关联检查；未知 policy/损坏/错绑仍报错 |
| DS-C2 阻断 | 新 role 未接读取路径，报告基数、失败缺项与 current 关系不明 | 沿原单 repair Method，每成功 run 两种 role 各一份；共享 Product decoder 接 live/detached，新旧 operation 分流；区分失败局部轨迹、历史终态与当前证明 |
| DS-O3 建议 | 现有直接输入 API 会把委派实施期间的输入误投父 Session | 本 profile 显式拒绝 steer/follow_up/clear_queue，目标控制保留原合同 |
| DS-R2 建议 | 取消与创建返回竞争时，创建调用结束不表示子轮次已停止 | 接回实际 ref/round 后 interrupt/join，交接收敛后释放 allowance/权限，DS-06 验证 |

三位原 reviewer 在固定 R2 上均确认各自阻断关闭、未发现新增阻断，可以提交用户评审。运行 reviewer 另确认临界区不跨模型执行；兼容 reviewer 确认子 Transcript 未声明与必需委派报告缺失没有混同。

实施提醒：原 RepositoryReport 在 delegate 失败时也不会交接 repository_report，旧 observations 却无条件读取它。新委派失败批分支必须同时处理两种成功报告的缺失，不能只豁免 delegated_method_report 而被旧读取分支阻断。这属于 R2 已规定的失败轨迹合同，须在实施回归中验证。

## R2 历史接受范围与检查点

执行 agent 作为本次授权内 Coding 架构责任承担者，接受“技术阻断已关闭、可提交用户评审”的结论；不记录用户尚未作出的接受。设计继续 proposed，Implementation status 为 not-started。

用户评审对象为系统环境、父 Goal/Work 与 child 的身份关系、投递/取消交接、首版证据范围及真实任务验收方案。遵循 [README 的用户检查点](README.md#用户评审检查点)，独立评审不能代替用户接受；此前真实任务、底座或同 Session 验证也不能替代新模式的集成与实际运行证据。

评审后仅更新底座 caaff3945 已本地合入的状态和一个措辞（子 Session 的原队列）；上述 R2 身份、交互、证据和验收合同未变，不据此记录新模式实施或用户接受。

## R3 新一轮独立评审

用户明确要求解除固定单 child 约束，支持按需复用、新鲜 Session 和继承上下文。R3 更新了环境、组件责任、逐批选择冻结、多 child 生命周期、继承来源与记录/验收。R2 的技术通过不覆盖这些语义变化。

- 固定设计修订：`7e56befce75740633890edcd4d5f915a832654ab`，R3；源码基线 `a19e5173f`，仓库 profile 仅对照独立分支 `f024cb734`。
- 方法：三位 reviewer 均核实干净本地 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，读取方法入口及 architecture-review。
- 三个全新、独立 xhigh agent 分别只读固定文档和源码；未读取本文件中的 R1/R2 结论或其他 agent 评审，没有补造缺失机制，也没有运行测试/模型或修改产品代码。

| Reviewer / 视角 | 关键核查与结论 |
| --- | --- |
| goal_context_ownership_r3 / 职责与复用 | AgentRef、Session、历史来源分开；Goal 可关联多个 child，Product 冻结选择，Harness 保持创建/历史/轮次/清理权威。A→A→B 与固定父截点继承的职责路径完整；原仓库分支、同 Session 接缝及未实现范围标注准确。没有重复建设树、队列、生命周期或执行内核；无阻断，可提交用户评审 |
| goal_context_runtime_r3 / 运行与失败 | 对照 GoalController.advance 的两次确认、RunHandle.deliver 先入队事实、共享 factory 的先持有后 await、control 容量与关闭失败保留行为。投递前核验、创建回执/取消交接、多 child 清理、额度与兼容性合同能够组合，未发现等待环或新增调度权威；无阻断，可提交用户评审 |
| goal_context_data_r3 / 数据与兼容 | intent/operation/report 的 execution_context 一致性、多 child 创建与 reuse 关联、固定来源 Session/库/watermark、requested/effective tier 及附件/model 限制明确；live/detached 共用读投影，失败报告缺失与成功坏损分别处理，旧 kind 不回写。子原文未持久化与父来源核验没有混同；无阻断，可提交用户评审 |

评审的源码依据包括：共享 subagent.py 的创建/历史安装与失败保留；multiagent/context.py 的 source/mapper、all/last、空集降级和模型限制；session/multiagent.py 的首次与后续投递、关闭保守次序；control.py 的原容量约束；transcript/profile.py 的持久图片 hydration 要求；独立仓库 profile 的 Method binding、allowance、RepositoryReport 与 observations。静态核查不等于这些分支已集成或新接入已运行。

综合复核：三视角均无技术阻断，职责、运行和证据合同未发现相互冲突。执行 agent 作为本轮授权内 Coding 架构责任承担者，接受“R3 已具备提交用户评审条件”的技术结论。R3 继续 proposed / not-started，未记录用户尚未作出的工作件接受，不据此启动实现。

实施验证保留 DS-01—10：尤其 DS-03/06 的跨 child 权限和额度、创建/投递取消竞争及多 child 关闭重试，DS-05/07 的错绑/缺失/旧 kind 混读，以及 DS-09/10 的固定历史、附件/工具消息、空集降级和未支持模式拒绝。第一切片接 reuse/fresh，inherit 完成对应验证后才开放。三位 reviewer 都将这些明确标为实施证据要求，而不是宣称设计通过即实现通过。

本轮文档变更通过既有文档检查，未触发产品回归路由，未新增门禁。重要工作件仍按 README 的用户检查点办理。
