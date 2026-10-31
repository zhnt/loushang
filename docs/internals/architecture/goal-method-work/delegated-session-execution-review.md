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

## R3 新一轮评审

用户明确要求解除固定单 child 约束，支持按需复用、新鲜 Session 和继承上下文。R3 更新了环境、组件责任、逐批选择冻结、多 child 生命周期、继承来源与记录/验收。R2 的技术通过不覆盖这些语义变化；本轮另以固定 R3 提交开启职责与复用、运行与失败、数据与兼容三视角独立评审，结果待登记。源码基线 a19e5173f，仓库 profile 对照 f024cb734；设计 proposed，实现 not-started。
