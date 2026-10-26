# 模型规划首例：有限 Coding 动作与验收合同 R1.1

- Authority: proposed — GMW-KD-PLAN-01 的候选业务 profile。
- Design status: draft，独立技术复核通过，待用户评审；Implementation status: not-started。
- Owner：Coding Product；继承[专项 R2.1](model-planning-loop.md)和[GP-01…10](../../plans/2026-10-26-goal-model-planning-loop.md)。
- 基线：`f3ee31319`；本文件固定设计输入和验收口径，不声称真实模型已经执行。

## 1. 固定材料与用户目标

用户目标：修复整数减法及闭区间 clamp 的约定行为，使固定全部用例通过；只修改
calculator.py，保留签名、支持的纯函数语法、测试、Method 和其他项目材料。
与既有首例相同的要求为 R-SUB、R-CLAMP、R-FILES，不让规划器自选验收映射。
用户修订到此 profile 无法裁决的要求时明确 needs_user，不由模型生成新验证器。

| 材料 | 原路径 / SHA256 |
| --- | --- |
| 初始源码 | `examples/coding/goal_calculator/calculator.py` / `4d47897f8b404b3b22dd4616658ee9e30aea0719b4617ec48487cd6fad8bccfb` |
| 23 项固定用例 | `examples/coding/goal_calculator/TESTS.json` / `1fd53db853feb6f499777566d4226d102010ffd902d0424569cd4d43a1de12fe` |
| 两步显式 Method | `examples/coding/goal_calculator/methods/task/goal-calculator-repair/SKILL.md` / `2471279d805224df10631955f03c227188cc6b2bc32550ad36cee3e7387da453` |
| 原纯函数验证器 | `coding/adapters/_goal_driver.py` / `4a17c03e938263f58a6f88528388dce8b51ecedcbe9f20fc3b294bc96ae28be8` |

初始规划输入提供完整要求、允许动作/前提、材料摘要及已知证据（起初可以为空）；
没有伪造初始失败报告。源码和测试都是可通过 inspect 获得的真实材料，不隐瞒已经
获取的事实来强迫模型改变路线。传给模型的后续输入包含之前实际结果及有限路线历史。
规划 prompt 要求模型提出下一动作和可修订路线、说明事实依据，不指定一条必走路线。

## 2. 动作合同

| 动作及参数 | 程序可检查前提 | 原执行路径与输出 | 不能推导的结论 |
| --- | --- | --- | --- |
| inspect(targets)；非空且仅 subtraction/clamp | 文件/测试/Method 符合固定项目约束，材料当前 | 原 Work 中的 Coding 只读适配读取所选函数 AST 源段及对应固定测试项，输出有摘要的 Blob 报告；不调用模型、无命令或写操作 | 读过代码不等于测试通过 |
| check(targets)；非空且仅 subtraction/clamp | 同上 | 复用原确定性纯函数验证器和输入快照；完整执行原固定用例，报告完整结果并标明本次请求关注的目标，不隐藏附带发现 | 这是诊断检查；不能直接作为 verify_all 的最终验收角色 |
| repair；targets 固定为整个 calculator 文件 | 存在同当前源码/测试/要求版本的真实 check 或 verify_all 失败报告；方法摘要与支持能力匹配 | 原 Method 编译→inspect/repair 两个 prepared turns→原 SessionTurnExecutor；只允许整个 calculator.py 内容改变；独立验证在后续 Work | 对某函数的关注仅是提示意图，不是函数级写权限或完成证明 |
| verify_all；无 targets | 同项目约束 | 复用原完整固定验证和证据链，报告 23 项结果与项目约束；可供 Goal 独立验收 | 验证失败仍可提供下一规划的实际证据 |
| stop；有 reason，无 targets | 候选结构/来源有效 | 策略返回 PolicyStop，沿原 Goal 暂停记录；不再创建实施 Work | 模型不能提交 completed，也不能冒称用户放弃 |

参数表是候选 schema 的约束来源：targets 对 repair 固定为一个 `calculator` 逻辑标识，
对 verify_all/stop 必须为空；路径由 Product 映射，模型不能指定任意文件、命令或 Method。
check 与 verify_all 复用同一 driver，不复制验证算法；完整结果必须向后续规划公开。
因此选择 check 不保证只发现一个目标的问题，也不能靠隐藏其余失败制造重规划。

每个动作模板规定必需证据 role；模型 expected_evidence 必须覆盖该模板，不得把
必需证据改为可选。requirement_ids 必须包含动作实际涉及的要求：目标检查对应
R-SUB/R-CLAMP，任何 repair 涉及两者和 R-FILES；verify_all 覆盖全部。
这是计划意图/能力的结构核验，最终语义覆盖仍由实际结果决定。

## 3. Method 与权限

保留原 goal-calculator-repair v1，整文件修复契约不拆成模型自创的单函数 Method。
原 inspect 步只启用 read，PolicyEvaluator 同时拒绝写/执行；repair 步只启用原
read/edit/write，并限定写入 calculator.py。两步每次都使用当前失败报告及要求版本。
原 planned_constraint/audit_policy 若需要此执行器不支持的保证，受理前直接停止；
方法摘要不变本身不代表所有声明都可强制执行。

可程序保证的事项：原 Method 身份/步骤、工具选择、解析路径及效果、固定材料完整性、
纯函数语言、最终固定测试。建议“最小修改”“解释思路”等仍是指导，不包装成强制保证。
Skill 首例可不配置；若用户显式配置，记录固定来源/摘要并作为指导输入，不准它改方法、
动作表、额度或验收规则。自动选择/生成 Skill 不在首版范围。

必要反例：模型提案 repair(subtraction) 不符合 schema，拒绝；合法 repair 同时修好
clamp 是整文件合同允许的结果，不能拿它证明函数级调度。没有当前失败报告的 repair
被拒绝，可在下一次规划选择 check/verify_all。方法要求未支持的审计语义时停止。

## 4. 真实规划与实质修订的判据

路线第一项必须与 next_action 相同；尾部不是执行授权，也不要求当前已满足其前提。
对比时以实际执行语义为身份：check 的 targets 仅为关注标签，全部归一为 check_all；
同输入的 check/verify_all 仅报告角色改变不能单独计作调整。inspect 的不同 targets
对应真实不同源段/用例，保留其读取范围身份。忽略理由文案和 operation id，扣除已执行
前缀后判断是否改变。必须有以下完整链才能关闭 GP-03：

1. 原候选路线留存，第一动作经原 Work 受理并产生实际检查/执行事实。
2. 后续真实模型候选引用该新增事实，提出与原剩余路线不同的下一实际行动。
3. 该变化通过准入，并有 Work 已开始/结果及对应证据；不是只改未采用的建议尾部。
4. 独立复核能把“新事实→改变的实际选择”对上，不能仅凭 change_reason 宣称成立。

正向设计走查（**不是实际模型结果或给模型的固定脚本**）：原路线为 inspect(subtraction)
→check(subtraction)→inspect(clamp)→check(clamp)→repair→verify_all。
check 的完整真实报告暴露两类失败后，模型改变原剩余路线，直接选择整文件 repair；
该 repair 实际执行并随后验收通过。这可以证明减少重复检查并改变真正采用的路线。
若模型始终沿原路线正确完成，只关闭执行/验收要求，不关闭 GP-03。

反向走查：模型交换两个尾部建议，后续在执行它们前又恢复原顺序，实际行动未变；
或仅计划列表去掉已完成第一项；或新候选改变路线却被拒绝/not_submitted。这些都
不计作已交付的实质修订。不得强迫错误补丁、运行中改测试或裁剪报告来制造正例。
另一反例：inspect 后模型把 check(subtraction) 改成 check(clamp)，且新 check 已执行；
两者实际都执行完整 23 项并公开相同结果，只变关注标签，仍不计作 GP-03。

真实运行前固定模型/provider 配置标识和本文件材料清单；不保存凭据。本阶段真实
验收最多先尝试三次独立、可还原的场景运行并保留全部结果，不能只选成功片段。
若都未出现实质修订，报告 GP-03 未达成，重新设计更有信息增量的小场景并评审，
不降低判据或无限调用模型。此限制是验证工作量约束，不是产品内部自动重试。

## 5. 有限推进的具体序列

总 Work 20、planning intent 10、每 planning Work 一次逻辑调用、每 repair Work 最多
12 次逻辑调用、每次 provider 尝试最多 3；规划和实施已知失败均继续消耗原额度。
Session 自动 retry/compaction 在此新 profile 关闭；不会改用户全局设置。

| 序列 | 预期结果 |
| --- | --- |
| planning invalid 连续 3 次 | 第三次事实可知后暂停，第四次不派发；合法但未实施的提案不清零 |
| planning→首次 inspect(subtraction)→planning→重复 inspect(subtraction)→planning→再次重复 | 首次知识增量清零，重复累计 1/2，达到 2 停止 |
| 已 inspect A/B 后交替重复 A/B | 不因目标交替或新 op id 清零，两个无新增信息的实施结果后停止 |
| check(subtraction)→planning→check(clamp)，源码和结果相同 | 第一次完整报告已建立两目标检查知识；第二次无新知识，不能因为首次请求 clamp 清零 |
| failed check→repair（源码变了）→verify_all 失败集合未缩小 | repair 暂记一个未证明进展的实施尝试；验证未改善再加一，到 2 停止；只改字节不清零 |
| failed check→repair→verify_all 失败集合严格缩小 | 验证产生实际改善时清零；仍未全部满足则可再规划 |
| not_submitted / pause→resume | 不释放已预约候选，不清空规划失败或无进展计数；重新规划仍受累计额度约束 |

首次知识按报告实际公开的事实覆盖去重，不按请求标签计数；完整 check 一次就标记
两目标结果已知。相同材料的 verify_all 也不会因证据角色不同重新获得知识增量。
源码变化不把相同 inspect
变成新的“首次”。验证进展按固定全部用例的失败集合比较：严格子集才算改善，失败
交换或总数相同不算。缺完整可比报告则 unknown/停止，不推断改善。revision 改变后
不能直接比较旧要求的失败集；首版 profile 不支持新验收映射时 needs_user。

## 6. 输出与验收留证

按一次显式 advance 展示 planning/implementation、原 operation/run、候选检查结果、
要求版本、剩余额度和停止理由；冷读只解析历史和核验材料。最终证据含原输入/响应
引用、调用身份、候选提案、实际受理/执行链、实质调整对照和独立全量验收结果。
不把 query 展示做成第二份状态权威。实现和真实验证都未开始，本文件只有合同与走查。
