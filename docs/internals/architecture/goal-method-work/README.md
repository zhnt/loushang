# Goal、Method、Work 协作架构

## 状态

- Authority: proposed — cross-scope design package。
- Design status: accepted for reviewed local SDK minimum-loop scope；其余扩展为 draft。
- Implementation status: 本地首版已实现并经真实 SDK 与用户手工验证，已集成本地 main；远程发布待完成。
- Owner: Loushang architecture，涉及 Harness、Method、HarnessWork 及 Product composition。
- 设计起始基线：本地 main `372cde4ade0fe026076c8fa5e8b4486774b09cc3`；前置证据切片 `d1f418de53c58040a590683a0c499ff3de50e50d` 与本地首版已随 `e0031f273` 集成本地 main。
- 方法咨询：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 用户要求系统环境图等重要工作件亲自评审；内部评审不能代替用户评审。

用户原话：“系统环境图等重要工作件需要我评审”。因此下面的用户检查点是本次
明确要求，不是从方法文件推断出的额外审批流程。

本目录是协作设计包，不声明新增顶层运行时或 Python 包。旧实现仅作产品树外
历史素材，不作为本设计的结构前提。本地最小闭环已获用户实施授权；其余扩展范围仍仅为设计。

## 概念与职责定位

> Goal 保存目标和完成依据；模型提出实施计划；Method 规定所选工作的契约；Skill 提供局部专业指导；Work 执行并记录实际结果。

这句话记录用户确认采用的协作职责定位，不代表各项能力均已实现。当前本地最小闭环
由固定领域策略选择工作，使用显式 Method 执行修复；模型自主规划仍属于后续扩展。
Method 的契约声明及 Skill 指导不自动构成权限授予或运行时强制保证；实际执行与
约束核验由既有 Product、Policy 和执行路径承担，目标完成还须有当前有效的验收证据。
Method 与 Skill 的详细边界见 [Method 架构说明](../method/README.md)。

下一阶段需求草案：[G-GOAL-PLAN-01：模型自主规划的最小 Goal 闭环 R1](../../plans/2026-10-26-goal-model-planning-loop.md)。
在已交付本地闭环上补模型候选、计划受理、证据驱动的调整与有限推进；当前仅生成
需求和专项设计已形成，三视角技术复核完成，用户评审待提交，未启动产品实现。
候选机制见[模型规划闭环专项](model-planning-loop.md)：规划作为原 Work，保持一次
推进一批；该选择及其环境、组件、交互待用户评审，不改变已接受首版。
配套[场景合同](model-planning-scenario.md)与[独立三视角处置记录](model-planning-review.md)
固定了动作含义、实质修订判据、原始材料及技术阻断关闭依据。

## 需求和工作件

来源为用户附件中的六项要求，以及
[架构设计任务书](../../plans/2026-10-24-goal-architecture-design-brief.md)。
“Goal”在这里指产品能力；原阶段任务为设计和评审；本地最小闭环随后已明确获准实施。

| ID | 要求 | 计划工作件 | 当前状态 |
| --- | --- | --- | --- |
| GMW-R1 | 概念、需求、边界；Method 指导和模型规划共用执行能力 | 概念/需求、领域关系 | 主线事实已核；本地最小闭环的概念及边界见 R3.2 |
| GMW-R2 | 系统环境、入口、既有系统关系和可信边界 | [系统环境图与关系](context.md) | 本地首版按用户反馈调整；全入口扩展仍是候选 |
| GMW-R3 | 功能发现→组件→映射→拆分/合并/保留 | 功能映射和组件模型 | 本地首版组件/三合同见 R3.2；未宣称全入口完成 |
| GMW-R4 | 接口和正常/失败/控制/恢复交互 | 合同、状态和交互时序 | 本地首版见 R3.2 及实现记录；首版之外的入口/恢复承诺仍待设计 |
| GMW-R5 | 关键决策、备选方案和影响 | 共同父级 ARD 和关键设计 | R2 非归属内容已认可；R3.2 明确共享归属及直接合同 |
| GMW-R6 | 固定修订三视角评审、阻断处置、接受证据 | 追溯/验证与评审记录 | 各固定修订三视角结果见评审记录；设计不等于功能验收 |

所有要求保持原范围。当前以本地 SDK 最小闭环收束设计；全入口协作仍按后续实际范围补齐。

补充工作件：[Goal 推进所需支撑能力与复用边界](support-capabilities.md)。
该表区分已有支撑、目标语义缺口、候选责任、关键场景和待决定事项；独立评审
及修订处置见[评审记录](support-capabilities-review.md)。用户评审仍待进行，
本表不替代环境图和完整组件/接口设计。

下一批讨论提纲：[Goal 最小闭环的三项待评审决定](minimum-loop-decisions.md)，
覆盖目标身份/寿命、计划与工作批次、推进与用户输入交接；仍为候选。

第三阶段候选设计：[Goal 最小业务闭环](minimum-loop-architecture.md)，对照
[G-GOAL-MIN-01](../../plans/2026-10-25-goal-minimum-business-loop.md) 补齐本地 SDK
范围、组件、状态、受测版本绑定及关键交互。R2 非归属部分已获用户认可，R3.2 按
用户反馈明确 Controller 与记录组件两个子组件、内部 Codec/Reducer 及真实适配边界。
新增子系统工作件：[harnesswork.goal 环境与子组件](../harnesswork/goal/README.md)，
作为独立固定对象评审其图、内部拆分及外围适配。
本地首版的设计再审已完成，用户已要求开始开发；当前实施记录见
[Goal 实现与验证](../harnesswork/goal/implementation.md)。
固定修订三视角发现及关闭证据见[最小闭环设计评审](minimum-loop-review.md)。
独立于实现的首个缺陷项目、原始测试及 Method 准备证据见
[最小闭环场景与验收输入](minimum-loop-scenario.md)；不构成设计接受或 Goal 运行通过。

分阶段候选：[HW-KD-001 取消观察专项](../harnesswork/key-designs/cancellation-observation.md)
承接 SC-06/08 的独立底座增量。其 owner 为 HarnessWork，不引入 Goal 依赖；专项接受
及实施不等于 Goal 整体架构或功能接受，原用户评审检查点继续有效。

第二阶段专项候选：[HW-KD-002 产物证据交接](../harnesswork/key-designs/evidence-handoff.md)，
复用已有 Artifact promotion、Session Blob 与 Work 领域事实；首个本地 Coding SDK
消费切片已获用户授权，见[限定目标与实施记录](../../plans/2026-10-25-coding-sdk-evidence-loop.md)。
此授权不等于接受或恢复完整 Goal 运行时开发。

## 用户评审检查点

| 批次 | 交用户评审的重要工作件 | 对后续工作的约束 |
| --- | --- | --- |
| 1 | 系统环境图、范围、外部关系和待确认事项 | 未确认的边界不作为已接受前提；可继续独立核查源码事实 |
| 2 | 概念/事实权威、功能映射、组件划分与已有组件关系 | 用户评审后再固定这些结构决定；内部建议均保留候选标签 |
| 3 | 关键接口、交互、状态/恢复及重要 ARD | 先提供完整可审查内容，再请求评审；不把框图认可扩大为机制接受 |
| 4 | 综合设计、需求追溯、三视角 findings 关闭和实际接受范围 | 设计结论留证后汇报；仍须用户明确恢复功能开发 |

批次可按讨论合并，但不得省略用户对重要件的评审。用户未回复不视为认可，
内部三视角通过也不自动把用户待评审内容改为 accepted。

## Current 与候选的区分

本包启动时的 main 基线已有 Method、HarnessWork、Harness/Session/Agent/AI 和相关
入口。当前本地 main 已实现并验证本地 SDK 最小闭环，详见实现记录；通用模型规划、
全入口协作和跨进程自动续跑仍属扩展，历史框图不表示这些能力已经实现。

旧 `2de1359c` 基线上的
[Method/Work 协作草稿](../../plans/2026-10-24-goal-method-work-design.md)
和 [ARD-018 候选](../decisions/proposed/ARD-018-goal-reuse-existing-runtime.md)
仅是输入材料；其未核实假设和首轮 findings 不直接升级为本包的现状或决定。
