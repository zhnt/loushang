# 模型规划 Goal：实施与验证记录

- Authority: descriptive；Implementation status: partial；Owner：Coding Product。
- 实施基线：`3474940c2d7b84d1733af462c736dcfc32ebfbb8`，分支 `feat/goal-model-planning`。
- 授权：2026-10-26 用户接受[专项 R2.1](model-planning-loop.md)及[场景 R1.1](model-planning-scenario.md)，明确“同意，请继续goal”。
- **完整 G-GOAL-PLAN-01 未完成：GP-03 的真实实质重规划证据未达成。**

## 2026-10-27 分阶段交付决定

用户明确要求：“收尾并交付当前‘模型逐批规划’能力，再用真实开发任务验证动态
重规划”。据此交付已实现并验证的逐批规划切片，GP-03 保持待验证，不再作为此次
切片合入的前置条件；完整原 Goal 仍不标为完成，也不降低 GP-03 的判据。

当前范围为本地 Coding SDK、单活动 Goal、显式 advance 和既有有限 calculator
profile；不是接受任意自然语言任务的通用 Coding Goal。模型选择下一动作及路线，
原 Work/Method 执行，当前独立证据裁决完成。默认显式 Method 模式保持兼容。

后续优先从真实待修缺陷或兼容性需求中选任务，固定要求、权限和独立验收，再设计
任务所需的最小领域适配。只有它暴露必要缺口时才补底座；不预建新队列、计划树或
调度器。计算器试验不再追加，[外部协作候选](model-planning-followup-scenario.md)
暂不执行，不当作用户已经接受的 GP-03 替代场景。

入口与使用说明见[示例 README](../../../../examples/coding/README.md)。源码检查点
`307d1fb0b` 已保留；本次收尾同步远程 main `d495fdca6`，交付到本地 main。远程发布
遵守工作日北京时间 18:30 前不推送的规则，Git 推送/PR 状态与功能实现分开报告。

集成验证：合入上述远程 main 后再次执行 Goal/Work 定向回归，218 passed、7 skipped；
文档轻检查 9 项、架构依赖及 diff 检查通过。收尾新增改动仅为文档，未增加 CI gate。
远程 main 尚不包含本地主线原有的 SDK 证据交接、共享 Goal 和 Transcript admission
修复前置提交；发布 PR 必须展示完整依赖范围，不能只描述最后一个规划实现提交。

## 已实现的增量

`CodingGoal.open(model_planning=True)` 显式开启新 profile；缺省仍是原显式 Method。
规划作为原 Work 执行，先落原 intent，再进入原 Session/Agent/标准模型调用；下一次
advance 核验候选并派发最多一个实施 Work。建议路线不等于执行授权。

| 私有模块 | 实际职责 |
| --- | --- |
| `_goal_proposal.py` | 严格单 JSON 候选、有限动作、要求/证据引用与实际效果身份 |
| `_goal_planning.py` | 通过原下一工作与验收合同衔接规划、准入、计数、事实与只读轨迹；沿用 CalculatorPolicy 的原修复/验证准备 |
| `_goal_planning_limits.py` | 标准 stream 注入点的有限逻辑调用委托，保留原 prepared-request 与取消传递 |
| `_goal_planning_work.py` | 原 SessionTurnExecutor 外的阶段工具授权、恢复与 fence；原 Work 中的只读检查和规划报告 |
| `_goal_planning_response.py` | 原提交记录、invocation、完整可重建 ModelInput、可信 prompt 与响应的关联核验 |
| `_goal_planning_history.py` | 原只读 Transcript repository 与 Blob codec 的薄适配，供关闭后复核相同来源 |
| `goal.py` / 示例 27 | 新 profile 装配、冷读结果及 `--model-planning`；没有更改共享 GoalController、WorkRuntime 或默认 Session 行为 |

没有增加执行队列、模型循环、原始用量账本或共享计划存储。限额是 Work/逻辑调用/
provider 尝试次数，不是金额、token 或墙钟时间的硬保证。新 profile 禁止恢复旧 Session
控制；`--reopen` 从原记录冷读，不启动模型或重放。`CodingGoalView.planning` 的健康与
最终验收 validity 分开，缺规划来源不会抹掉独立可读的历史完成决定。

## 三次真实试验：全部保留

模型配置均为 `kimi-code / kimi-for-coding`，使用原标准调用链；没有保存凭据。材料
使用原固定源码、23 项测试、Method 与 driver，摘要见原场景。实现修订摘要和完整日志
在产品 Git 外的 `architecture-analysis/goal-model-planning-implementation-20261026/`。

| 试验 | 观察结果 | 可以和不可以证明什么 |
| --- | --- | --- |
| r1 | 模型提出合法计划；工具策略误拒绝可信固定验证器命令，因缺证据暂停 | 暴露装配缺陷；已以精确命令/输入作用域修复，并通过真实本地验证器回归；不是成功场景 |
| r2 | inspect→check→repair→verify_all；23 项从 13 失败到 0 失败，Goal completed/current | 证明真实路线选择、模型代码修改及独立完成；实际只沿原剩余路线，**不满足 GP-03** |
| r3 | 修复 Work completed，但源码未改，验证仍有 13 失败；无进展计数 2 后暂停 | 证明 Work completed 不等于 Goal 完成；新增 repair 只在未执行尾部，**不满足 GP-03** |

r3 模型声称没有编辑工具；原 ModelInput 实际显示 inspect 有 read、repair 有
read/edit/write，因此不能把该说法当作权限切换缺陷。第二、三轮关闭后的规划冷读
各重建四份原提案及其来源/实施关联，前后文件清单和全部文件 SHA256 相同。

三次试验额度已用完，不再重复 calculator 碰运气。新增业务 profile 的 JSON 配置
建议经评审后撤回；[R2 后续验证建议](model-planning-followup-scenario.md)保留现有
profile，提出协作场景。2026-10-27 用户选择先交付当前能力、再用真实开发任务验证；
该协作候选暂不执行，不视为用户接受。

## 实现复核与本地检查

三位独立 reviewer 继续按职责复用、运行失败、数据兼容复核，来源见
[评审记录](model-planning-review.md)。已处理 Method 步骤必须受理前核验、context
输入改写拒绝、完整输入重建、冷读原来源和调用投影损坏分类，以及同轮达到阈值暂停。

- Goal/Work 定向回归：218 passed，7 skipped（既有 host 选择器）；后续窄修复另有
  3 passed，覆盖标准管线冷读损坏 outcome 和固定验证器真实本地子进程。
- 输入组件/hash/origin 损坏及 planning/repair 取消×恢复正常/异常/不一致：10 passed，
  已包含在上述定向覆盖中，不重复累计。
- Coding 原宽回归先有 3369 passed、560 failed、20 skipped、62 deselected；首个失败
  是 `/run/user/1001` 的 164 MB 临时盘耗尽。只复跑失败项：533 passed；剩余资源发现
  用例因暂存目录位于工作区祖先而受配置影响，移至 `/var/tmp` 后 23 passed。其余四个
  Goal 用例由当前定向回归重新覆盖。未通过修改产品代码或测试断言掩盖环境问题。
- 修改源码的 Ruff、mypy、架构依赖和文档轻检查分别执行；不扩大 PR gate，不把既有
  基线文件的独立静态错误归入本次新增能力。

取消测试使用原 WorkRuntime/SessionTurnExecutor 与可控 Session port；不声称已覆盖
真实 provider 取消或所有 unknown/close 故障组合。原宽回归在多个修订期间运行，以上
是明确分段证据，不冒称同一次全量零失败。真实试验没有验证远程入口、跨进程续跑
或强断电耐久。当前分支保留交付检查点，不因局部测试通过就宣布完整 Goal 完成。
