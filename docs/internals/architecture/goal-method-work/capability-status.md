# Goal 能力、验证范围与剩余差异

- Authority: descriptive — 固定切点事实与后续交付索引；不是新的架构决定或实施授权。
- 原盘点日期：2026-11-01；源码基线：main `914cf3ac84935c8bbd2855e660505b3b31eba2ef`。第 1—5 节保留该切点的结论、试验和当时待办，不作为今天的完整 Current。
- 后续交付核对：2026-11-04，main `1909dd1adc5319e79baa3abe09ea8b6969903601`；当前增量见第 0 节。
- 方法咨询：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，区分 Current、历史证据、已接受差异和候选扩展。
- 范围：原盘点的源码、测试、交付记录和保存的真实试验结果，以及第 0 节的后续 main 提交和已存在的实现记录。本次仅静态核对，没有重新运行产品测试、付费模型或三视角评审；没有接受新系统环境、接口或组件设计。

## 0. 后续已交付增量与当前边界

下列 PR 均已由本地 main 的 first-parent 合并历史确认，源码和实现记录用于限定实际能力；不将未重新执行的历史测试计作本次验证。

| 后续能力 | 已交付依据 | 当前仍须区分的边界 |
| --- | --- | --- |
| 托管 Method → Work 执行与查询，以及 calculator Goal 最小闭环 | PR [#841](https://github.com/zhnt/loushang/pull/841)、[#842](https://github.com/zhnt/loushang/pull/842)；[托管 Goal 设计](../coding/key-designs/hosted-goal-loop.md) | 复用 AppHost canonical Session 与既有 AppService scope；不表示所有远程 wire/TUI 路由已经接入 |
| 托管有限仓库 Goal、可信评审、有效预算与轻量进度观察 | PR [#843](https://github.com/zhnt/loushang/pull/843)、[#844](https://github.com/zhnt/loushang/pull/844)、[#848](https://github.com/zhnt/loushang/pull/848)；[仓库实现](../coding/key-designs/hosted-repository-goal-implementation.md)、[预算/观察记录](../coding/key-designs/hosted-goal-budget-observation-implementation.md) | 服务器显式配置的有限 profile；进度不等于当前验收，离线与在线结果分别报告 |
| Session 联合受理、配置/限额/取消与关闭边界，共同批次规划和回复交接 | PR [#852](https://github.com/zhnt/loushang/pull/852)；[共享重构交付](refactoring-delivery.md)、[批次规划](../../../../src/loushang/harnesswork/goal/batch_planning.py) | Harness / HarnessWork / Method / Coding 各守原权威；冷读不自动重放副作用 |
| 在已有持久 Session 显式 attach 有限 Goal profile | [CodingGoal.attach](../../../../src/loushang/coding/adapters/goal.py)、上述共享交付记录 | open 与 attach 是不同装配方式；不能再把“模型规划一律新建 Session”列为共同限制 |
| 嵌入式 TUI 输入日常开发目标，有限推进、显式 Method、默认人工验收 | PR [#853](https://github.com/zhnt/loushang/pull/853)；[专项](interactive-development-goal.md)、[评审与实施](interactive-development-goal-review.md)、[任务适配](../../../../src/loushang/coding/adapters/interactive_goal.py)、[命令入口](../../../../src/loushang/coding/interaction/goal.py) | 复用原 Session/Goal/Work；不保证任意配置或预算内必成功，不包含 lmux Goal wire、自动选配任意 Method、后台或跨进程自动续跑 |

因此，下文 G01 的“托管闭环尚无”、G04 的“仅固定 calculator/私有仓库”、G05 的“规划必须 fresh Session”，以及第 5 节“下一项先做 G01 设计”，都只属于 11 月 1 日的历史切点，不能据此安排重复开发。G04 中自动选配任意 Method/跨领域通用验收等扩展并未因此交付；G02 的记录留存差异及 G03 的历史试验证据边界，也不能因新增入口自动认定关闭。需要新开发时应先核对对应最新专项与具体消费者，不把旧行整体打包重做。

## 1. 原基线结论

**本地 Coding SDK 的 Goal 已具有模型逐批规划、证据驱动的实质重规划、Method 执行、独立验证/可信评审及冷读闭环。** 实质重规划 GP-03 已于 2026-10-28 在有界真实仓库任务中证明，不是待重新证明的基本能力。

随后交付了通用子 Session 机制、按批 reuse/fresh/inherit、Work 记录和 Transcript 来源、宿主零模型收尾，以及私有有界收尾预算。11 月 1 日的文件名修复试验补充了新任务在冻结预算内完整交付的证据；它没有发生重规划，不会撤销此前 GP-03 的成功证据。

这仍不是所有入口、任意自然语言任务或跨进程自动续跑都已完成。不得将局部试验成功外推为这些保证，也不得将未承诺的扩展全部算作已接受需求的开发欠账。没有统一冻结的“全部 Goal”范围，本文不计算总体完成百分比。

## 2. 原基线已交付能力与复用位置

下表“已交付”表示源码已在本基线 main 中；具体运行证明按第三节区分，不表示每项都有在线、跨平台或故障实验。

| ID | 能力与当前范围 | 实现 / 合同依据 | 后续应复用什么 |
| --- | --- | --- | --- |
| C01 | 目标身份、要求修订、状态与批次关联；显式推进、控制、当前完成依据 | [GoalController](../../../../src/loushang/harnesswork/goal/controller.py)、[Records](../../../../src/loushang/harnesswork/goal/records.py)、[三合同](../../../../src/loushang/harnesswork/goal/contracts.py)、[首版验证](../harnesswork/goal/implementation.md) | Controller 和记录组件；不建立第二个执行器、队列或 operation→run 映射 |
| C02 | 显式 Method 准备及顺序 Work 执行；模型计划不自动改变 Method/权限 | [Method runtime](../../../../src/loushang/method/runtime.py)、[Session Work](../../../../src/loushang/harnesswork/integrations/session.py) | 原 compiler、MethodDomainRuntime、SessionTurnExecutor、WorkRuntime；MethodPolicy 仍为 off/explicit，不等于模型自动选任意方法 |
| C03 | 模型逐批提出下一动作和可修订路线，校验受理、来源证明及有限推进 | [规划实现记录](model-planning-implementation.md)、[Planning](../../../../src/loushang/coding/adapters/_goal_planning.py)、[Proposal](../../../../src/loushang/coding/adapters/_goal_proposal.py) | 原规划 Work、提案解析和候选确认；不是一次生成后永不修改的静态总计划 |
| C04 | 测试事实、可信评审意见可成为后续规划依据；通过意见与当前候选绑定 | [反馈专项](../coding/key-designs/goal-review-feedback.md)、[真实证据](../../plans/2026-10-28-goal-review-replanning.md)、[仓库适配](../../../../src/loushang/coding/adapters/_goal_repository.py) | 原 Work/Blob 交接；模型没有 submit_review 权限，测试通过不能替代独立评审 |
| C05 | 取消观察、证据交接、未知结果保守处理及冷读；失败清理保留 owner 重试 | [取消专项](../harnesswork/key-designs/cancellation-observation.md)、[证据专项](../harnesswork/key-designs/evidence-handoff.md)、[实现记录](../harnesswork/goal/implementation.md) | 原 cancellation projection、Artifact/Blob、GoalJournal；冷读重建事实，不自动重放副作用 |
| C06 | Work 默认 recording v1、持久要求、ACK/loaded 确认查询；来源声明与共享 reader | [记录切片](../../plans/2026-10-29-work-recording-defaults.md)、[引用切片](../../plans/2026-10-29-work-transcript-references.md)、[recording](../../../../src/loushang/harnesswork/recording.py) | HarnessWork 默认机制、Product 策略及资源配置；不用每个 Product 自写一套记录机制 |
| C07 | 同 Session 多批执行及受控 Transcript 来源查询；保留期限由 Product 承诺 | [接入记录](../../plans/2026-10-30-goal-session-recording.md)、[来源读取](../../../../src/loushang/coding/adapters/_goal_work_sources.py) | 原 prepare_session_work_source 和 TranscriptSourceReader；未声明来源不等于来源完整 |
| C08 | 通用子 Session 创建、历史安装、驱动与清理已下沉 Harness | [共享专项](../harness/multiagent/child-session-composition.md)、[工厂](../../../../src/loushang/harness/session/subagent.py) | AgentSessionSubagentFactory、原 Multiagent 控制树/容量/轮次；Coding 保留产品配置 builder |
| C09 | 私有仓库 Goal 按批选择 reuse/fresh/inherit，可混用多个 child；默认同 Session 不变 | [R3](delegated-session-execution.md)、[执行选择](../../../../src/loushang/coding/adapters/_goal_execution_context.py)、[委派](../../../../src/loushang/coding/adapters/_goal_delegation.py) | 原 Harness factory、ForkTier 和固定父历史截点；不要求所有 Work 必须复用一个 child |
| C10 | 可信宿主直接 verify_current，再 submit_review，收尾无需模型规划 | [收尾专项与验证](../coding/key-designs/goal-low-token-closeout.md)、[仓库合同测试](../../../../tests/coding/test_repository_goal.py) | 原 Controller.advance、verifier、review Work；不增调度器，不重置旧预算或伪造模型提案 |
| C11 | 私有 closeout_budget v1 把阶段额度和可行收尾路线交给原规划/准入 | [预算专项](../coding/key-designs/goal-closeout-budget.md)、[冻结任务](../../../../src/loushang/coding/adapters/_goal_repository_task.py) | 单次实施 profile 的 1—6 Work / 1—2 planning；无此字段保留旧默认；不是通用复杂重规划预算 API |
| C12 | 原模型用量记录及按已受理 Work 限制逻辑调用，支持报告真实花费 | [用量投影](../../../../src/loushang/harness/transcript/model_usage.py)、[调用 allowance](../../../../src/loushang/coding/adapters/_goal_planning_limits.py) | 原 Transcript 账本和 AI 请求选项；Work 数不等于调用数，调用数不等于总计费 token 硬上限 |

这些实现提交已核实为 main 祖先：首版 `e0031f273`、逐批规划 `307d1fb0b`、仓库反馈 `f024cb734`、共享子 Session `3aac81d8e`、委派修正 `2a046fa3b`、同 Session 来源 `2f257ca2e`、预算修正 `3614c1e0a`。后续汇总交付见 PR [#832](https://github.com/zhnt/loushang/pull/832)、[#833](https://github.com/zhnt/loushang/pull/833)、[#834](https://github.com/zhnt/loushang/pull/834)、[#836](https://github.com/zhnt/loushang/pull/836)、[#838](https://github.com/zhnt/loushang/pull/838)。历史文档的“尚未发布”仅描述当时切点。

## 3. 各次验证证明了什么

| 证据 | 实际结果 | 可复用的结论 / 不能外推的内容 |
| --- | --- | --- |
| 初期 calculator 三次模型试验 | 一次完成但沿旧路线，一次装配失败，一次无进展暂停 | 保留原 [r1/r2/r3](model-planning-implementation.md) 结论；它们当时未证明 GP-03，不代表后来仍未证明 |
| 2026-10-28 真实 #125 | 7 planning、15 Work；测试失败使旧剩余检查路线前新增修复，实际执行，完整验证/宿主批准/冷读 completed/current | **GP-03 已证明**。触发是测试失败；该次在线运行只有通过评审，不能冒称由评审拒绝触发。见[完整事实链](../../plans/2026-10-28-goal-review-replanning.md#真实运行结果2026-10-28) |
| 2026-10-31 R3 真实委派试验 | A→A→B；测试失败及真实评审拒绝均驱动后续修改；8 planning 用尽，冷读 paused/not_satisfied | 证明多 child 执行及真实反馈后调整；该旧 Goal 未完成。在线 inherit 未运行，不能把离线证据标为在线。见[原结果](../../plans/2026-10-31-goal-child-session.md#本轮真实-kimi-coding-验证) |
| R3 离线 SDK 合同 | reuse/fresh/inherit、固定历史、附件、错绑/损坏、取消、容量及清理重试已有测试 | 三种模式已实现，不是待重建；离线覆盖与在线表现分别报告。见[原测试](../../../../tests/coding/test_repository_goal.py) |
| 2026-11-01 固定候选零模型收尾 | 新 Goal 恰好 2 Work、0 新模型调用，完整验证及评审后 completed/current | 已证明宿主确定性收尾；不把旧暂停 Goal 改写为成功。见[结果](../coding/key-designs/goal-low-token-closeout.md#固定候选的真实收尾结果) |
| 同一 Goal 离线连续闭环 | 原规划、真实文件工具实施、宿主验证/评审、冷读；成功及拒绝/失败分支 | 已证明接口在同一 Goal 内衔接，不需为这一接缝再建平行驱动。见[记录](../coding/key-designs/goal-low-token-closeout.md#8-同一-goal-的离线连续闭环验证) |
| 2026-11-01 有界首次 read-hint 试验 | 模型选 inspect，旧试验驱动未留名额，停在规划后；未实施 | 历史设置缺口，后来由预算专项处理；不是“模型不会规划”。见[原记录](../coding/key-designs/goal-low-token-closeout.md#9-有界真实任务试验未进入实施) |
| 2026-11-01 冻结预算 read-hint 试验 | 4 Work、9 调用；17 合同与 163 回归通过，独立批准、冷读 completed/current；修复随 #838 合并 | 新任务有界完整闭环已证明；直接实施无实质重规划，不抵消旧 GP-03。累计 token 167,196，其中缓存读取 133,120、输出 3,233；金额未知，不声称这是低总 token 基准 |

最后一次试验的宿主评审、冻结包摘要、候选补丁、用量和冷读原件保存在产品树外 `architecture-analysis/goal-read-hint-budget-20261101/`；其交付 PR 与 main CI 均通过。原始记录不搬入源码仓库，后续不依赖已删除的试验工作树来寻找证据。

## 4. 原基线剩余事项：实现差异、证据边界和候选扩展（历史）

| ID / 类别 | 当前缺口或边界 | 既有依据 / 责任 | 推进条件及最小增量 |
| --- | --- | --- | --- |
| G01 已登记的候选接入 | AppHost/AppService 尚无已核实的 Goal/Method/HarnessWork 完整托管闭环 | [#824](https://github.com/zhnt/loushang/issues/824) 仍 open；[CodingExecutionWorkV1](../../../../src/loushang/coding/_hosted_execution_work.py) 当前驱动 execute_prompt，其名称不等于 HarnessWork Work；[CodingGoal.open](../../../../src/loushang/coding/adapters/goal.py) 仍拥有自己的 SDK/Session | 若选择此方向，先设计已有 Product/Session 上的 Method→Work 装配及身份/关闭责任，再接 Goal；复用 AppHost 所有权和 AppService 原端口，不按请求另建 Session。重要环境图/交互仍需用户评审 |
| G02 已接受设计的部分差异 | Work 来源引用已接通，但仍保留原正文；完整审计、正文裁剪和入口迁移未完成 | [HW-KD-003 §11](../harnesswork/key-designs/fact-retention-replay.md#11-已接受-target-与-current-的差异)、[ARD-019](../decisions/accepted/ARD-019-work-facts-and-transcript-sharing.md)；HarnessWork/Harness/Product 共同负责 | 先选一个确实需要该行为的消费者，核对订阅/重连/旧 reader/保留期后补窄切片；不再建设来源读取器，不先上缓存或索引 |
| G03 已实现能力的证据边界 | 在线 inherit 尚未验证；R3 在线 A→A→B 的原 Goal 未完成 | R3 原结果；后来零模型收尾属于新 Goal | 不阻止复用已通过离线合同的实现。实际产品需要在线继承或该组合验收时，再冻结专门试验；不是现在再重跑 GP-03 的理由 |
| G04 候选业务扩展 | 任意自然语言 Goal、模型自动选择/组合任意 Method、通用业务验收尚未交付 | 当前公开示例是有限 calculator，仓库 profile 为私有固定任务合同；MethodPolicy 是 off/explicit | 由具体领域先提供要求/动作/Method 准入/验收合同。不要把现有有限 planner 改名为通用 planner，也不另造 Work 引擎 |
| G05 未承诺的运行扩展 | 后台自动唤醒、跨进程自动续跑、多 Work 并发、跨 Goal 共享 child、持久 child Transcript 未在现范围交付 | [最小架构](minimum-loop-architecture.md)、[R3 范围](delegated-session-execution.md)；child persist=False，模型规划 open 要求 fresh Session | 冷读、原 Session 恢复与业务执行恢复分开；有明确需求再设计，不能从日志可读自动推导可重放 |
| G06 候选计量/预算扩展 | 已有原始用量账本与有限调用/批次限制，但没有跨全部子执行的完整归属及总计费 token 硬限 | [用量事实](../../../../src/loushang/harness/transcript/model_usage_types.py)、预算专项、R3 子原文边界 | 如果产品确实要求全 Goal 成本核验，先补原 invocation/Work/child 的关联与不可知范围；不复制账本。当前 6/2 单实施收尾配置不能冒充多次修复预算 |
| G07 用户暂缓的优化 | 旧真实任务暴露历史读取成本；已有记录/来源架构增量，但未有独立性能归因或优化收益证明 | [旧任务限制](../../plans/2026-10-28-goal-review-replanning.md#适用范围与后续事项)，用户要求先架构分析 | 不作为当前交付阻断，不因 9 次模型调用直接启动历史缓存工程；未来有实际性能目标时先测量 |

G01、G04—G07 中的候选方向不是本盘点新接受的 Target。G03 是验证范围差异，不是重新实现三种模式的工作单。G02 保留其已接受差异身份，但不因存在差异自动取得所有入口默认切换或 PR gate 扩大的授权。

## 5. 原基线的后续工作顺序与避免重复的规则（历史）

1. 本轮关闭文档状态不一致：总览、旧支撑表和关键实施入口指向本盘点；历史基线与失败结论保留，不覆盖成成功。
2. 建议下一项是 **G01 的专项设计**，先选一个托管入口，明确借用现有 Session、Method/Work 身份与关闭责任，再讨论 Goal 控制及证据读取。#824 原先“先证明 GP-03”的前置事项已经满足；本轮只读取 issue，未修改远程内容，也未开始实现。
3. G02 随真实消费者按需补齐；G03 不立即安排付费补测；其余候选不作为必须完成的基础设施清单。
4. 再次验证必须说明新问题：代码/合同变化、入口组合变化、具体历史缺口或回归。没有新问题就引用既有证据；不重复修复 #125，不重造 Session/队列/日志，不以同类样例不断证明同一能力。
5. 一次试验的结果只作用于其版本、任务和组合。旧失败、后来的修复验证、已合并实现分别记账；测试失败后确有新路线执行和完整验收才算 GP-03。实质重规划已证明，无需每个交付都再次展示。

本盘点没有改变既有用户评审要求。新的系统环境、重要组件交互或托管合同仍需形成可审查工作件，经用户评审后实施。
