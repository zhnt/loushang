# ARD-020：托管 Goal 的预算责任与观察层次

## Status

- Authority: normative — cross-scope accepted decision
- Design status: accepted
- Implementation status: implemented — offline verified and independently reviewed; integration follows actual Git/PR state
- Revision: R1，2026-11-02
- Owner: Loushang architecture；参与：Coding、AppService/AppServer、HarnessWork、Harness Session/Agent/AI。
- 基线：`497e386a3bbb8fd40810dd7d1be0db9f21e616eb`。机制与验证由[COD-KD-HG-003](../../coding/key-designs/hosted-goal-budget-observation.md)唯一维护。

## 背景与驱动

现有托管Goal复用原Session和Goal/Work，但真实小任务在120秒业务截止前只完成规划、实施；模型预算投影未包含托管更严限额，频繁进度查询又进入完整业务复核。用户要求先设计预算与观察专项并评审，再讨论实施。

这是Product限额、同进程客户端观察语义与原Work状态消费方式的组合问题，不需要迁移GoalController、增设执行器或复制用量/事实账本。既有[ARD-019](../accepted/ARD-019-work-facts-and-transcript-sharing.md)继续约束Work事实与Transcript内容来源；本决定不选择新的记录粒度。

## 方案比较

| 方案 | 收益 | 代价与判断 |
| --- | --- | --- |
| 所有任务统一把120改成更大常数 | 最少配置 | 无法解释任务、模型及验收差异，预算错配仍在；不选 |
| 共享HarnessWork预算调度/进度缓存服务 | 可集中策略 | 无真实跨Product合同依据，重复现有owner和状态；不选 |
| 把原query改成廉价状态读取 | 原调用方自动变快 | 静默削弱完成有效性与旧wait合同；不选 |
| 先删流式事实或增加历史索引 | 可能减少数据量 | 未核对消费者，已有索引；混入独立数据合同变化；本轮延后 |
| Product配置有效预算、原owner执行；新增显式progress | 保持完成判据、旧API与现有权威，观察用途清楚 | 增加可选方法和能力协商，调用方主动选择；候选推荐 |

## 候选决定

1. Coding Product配置有界任务的有效预算，原PlanningCallAllowance与GoalInvocation分别执行调用约束和时限；静态配置与模型材料通过原Goal/Transcript留证，不新设账本。repository允许显式有限T与收尾R，原calculator缺省/上限保持。
2. AppService新增可选progress，保留原query/wait的完整语义。progress复用原DTO与Goal/Work状态，明确validity=not_checked，不以完成记录等同当前验收。
3. 权限、取消、recording和资源寿命沿原owner；跨await重新核验，截止后沿原settle处理。进度不读外部材料、不回放内容历史、不创建新状态权威。
4. 先验证有限profile的调用边界与复杂度。流式事实选择、跨进程恢复、远程wire、通用预算/性能缓存不进入本决定。

用户于2026-11-02在阅读R1与三项核心决定后回复“同意，继续”，接受上述增量并授权推进。HG-001/HG-002其余合同保持有效。具体字段、竞争结果、兼容和验证见专项，避免两份规范互相漂移。

## 后果、评审与接受

收益是把实时观察和完成依据分清，并让模型看到与实际受理相符的预算。代价是用户或SDK必须显式使用progress；原完整query仍可能昂贵。本轮不保证120秒在线成功、不保证物理硬截止、不消除所有批次切换耗时。

方法与走查记录见[专项评审](../../coding/key-designs/hosted-goal-budget-observation-review.md)。用户接受、作者走查与后来完成的三名独立agent代码评审分别记录。用户已同意评审后收尾交付，实际验证见[实施记录](../../coding/key-designs/hosted-goal-budget-observation-implementation.md)，远程CI和合并状态以PR为准。本次未授权在线试验。
