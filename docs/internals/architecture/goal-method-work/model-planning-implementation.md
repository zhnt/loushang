# 模型规划 Goal：实施与验证记录

- Authority: descriptive；Implementation status: partial；Owner：Coding Product。
- 实施基线：`3474940c2d7b84d1733af462c736dcfc32ebfbb8`，分支 `feat/goal-model-planning`。
- 授权：2026-10-26 用户接受[专项 R2.1](model-planning-loop.md)及[场景 R1.1](model-planning-scenario.md)，明确“同意，请继续goal”。
- **完整 G-GOAL-PLAN-01 未完成：GP-03 的真实实质重规划证据未达成。**

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
profile，提出协作场景，**待用户确认是否符合本阶段 GP-03 的业务意图**。

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
