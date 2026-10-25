# Goal、Method、Work 协作架构

## 状态

- Authority: proposed — cross-scope design package。
- Design status: draft；Implementation status: not-started。
- Owner: Loushang architecture，涉及 Harness、Method、HarnessWork 及 Product composition。
- Current 基线：本地 main `11b854951125d3437fea9f43f65a9788af620933`。
- 方法咨询：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 用户要求系统环境图等重要工作件亲自评审；内部评审不能代替用户评审。

用户原话：“系统环境图等重要工作件需要我评审”。因此下面的用户检查点是本次
明确要求，不是从方法文件推断出的额外审批流程。

本目录是协作设计包，不声明新增顶层运行时或 Python 包。旧实现仅作产品树外
历史素材，不作为本设计的结构前提。当前只进行设计，不开发 Goal 功能。

## 需求和工作件

来源为用户附件中的六项要求，以及
[架构设计任务书](../../plans/2026-10-24-goal-architecture-design-brief.md)。
“Goal”在这里指产品能力；本线程的工作目标是设计和评审，不包含功能实施。

| ID | 要求 | 计划工作件 | 当前状态 |
| --- | --- | --- | --- |
| GMW-R1 | 概念、需求、边界；Method 指导和模型规划共用执行能力 | 概念/需求、领域关系 | 主线事实已初核；候选概念尚待提交 |
| GMW-R2 | 系统环境、入口、既有系统关系和可信边界 | [系统环境图与关系](context.md) | 第一批草稿，待用户评审 |
| GMW-R3 | 功能发现→组件→映射→拆分/合并/保留 | 功能映射和组件模型 | 未完成；不先固定组件数量 |
| GMW-R4 | 接口和正常/失败/控制/恢复交互 | 合同、状态和交互时序 | 未完成 |
| GMW-R5 | 关键决策、备选方案和影响 | 共同父级 ARD 和关键设计 | 旧候选尚未接受；新决策未定 |
| GMW-R6 | 固定修订三视角评审、阻断处置、接受证据 | 追溯/验证与评审记录 | 未完成；设计不等于功能验收 |

所有要求保持原范围。当前交付环境图供早期确认，不以这批草稿代替完整设计。

补充工作件：[Goal 推进所需支撑能力与复用边界](support-capabilities.md)。
该表区分已有支撑、目标语义缺口、候选责任、关键场景和待决定事项；独立评审
及修订处置见[评审记录](support-capabilities-review.md)。用户评审仍待进行，
本表不替代环境图和完整组件/接口设计。

分阶段候选：[HW-KD-001 取消观察专项](../harnesswork/key-designs/cancellation-observation.md)
承接 SC-06/08 的独立底座增量。其 owner 为 HarnessWork，不引入 Goal 依赖；专项接受
及实施不等于 Goal 整体架构或功能接受，原用户评审检查点继续有效。

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

当前 main 已有 Method、HarnessWork、Harness/Session/Agent/AI 和相关入口；
不存在已核实可用的统一 Goal 协作实现。框图中的 Goal、通用规划与目标验收
关系是本次候选，不声称已组装、已运行或已满足全部入口和兼容需求。

旧 `2de1359c` 基线上的
[Method/Work 协作草稿](../../plans/2026-10-24-goal-method-work-design.md)
和 [ARD-018 候选](../decisions/proposed/ARD-018-goal-reuse-existing-runtime.md)
仅是输入材料；其未核实假设和首轮 findings 不直接升级为本包的现状或决定。
