# Coding 仓库 Goal：有界收尾预算候选

- Authority: proposed；Design status: draft；Implementation status: prototype。
- Owner：Coding；基线 `a77595735`；2026-11-01。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 范围：用户“继续”授权的最小方案与离线验证。延续[已有收尾设计](goal-low-token-closeout.md)，本轮不开展在线试验；此私有任务合同增量保留[用户评审检查点](../../goal-method-work/README.md#用户评审检查点)，离线原型不等于接受为共享或公开接口。

## 问题与选择

上次驱动只接受直接实施；模型看到原 profile 的 20 Work / 8 planning，且首次规划无源码正文，先选择 inspect 是合理的。仅把脚本循环从 5 调到 6 或追加提示，仍不能使实际准入与模型额度一致。

候选方案：在已冻结、带摘要的 RepositoryTask 中显式选择 `closeout_budget`；原 Coding profile 将它编译为更小的限制，原 GoalController 记录总额度，原 RepositoryPolicy 同时负责规划输入和准入。没有新运行组件、队列、调度器、用量账本或 Goal/Work 记录 schema。已有私有批次策略仅提取剩余额度投影方法，默认计算不变。

## 私有配置及责任

```json
{"closeout_budget":{"version":1,"work_intents":6,"planning_intents":2}}
```

只接受这三个键，严格整数，拒绝 bool；version=1，总 Work 为 1—6、planning 为 1—2。允许配置小于可完成路径的额度，用于提前停止，而不是自动增加预算。没有该字段的旧任务保留原 20/8 和原验收语义。

该限定模式至多 inspect、repair、verification、review 各一次，check 为零。每次模型调用及 provider 重试上限沿用原规则；Work 数不等于模型调用数，也不是 token 硬限。宿主在一次实施后显式请求原 verify_current 与独立评审；模型不能提供评审决定，也不能将 check 冒充完整验证。输入将 model_actions（inspect/implement/stop）和 work_routes 分开，明确阶段名不能作为模型计划动作照抄。

| 路径 | Work | 规划次数 |
| --- | --- | --- |
| 直接实施 | planning → repair → verification → review | 1 |
| 先读源码再实施 | planning → inspect → planning → repair → verification → review | 2 |

总额度进入原 GoalState.limit 和原 metadata.planning_limits；输入的 limits、remaining 由同一策略及原历史生成。第二条路径检查后，下一次规划看到剩 4 Work / 1 planning、inspect 剩 0。不会一边显示 20/8，一边由宿主偷偷限制为 6/2。

## 准入、失败与事实

- 原按 Goal 的 batch intent 计数，不按进程或 epoch 清零，不增加计数日志；未提交和失败的 intent 仍消耗名额。
- 准备 planning 至少保留本次规划、实施、验证、评审的 4 个位置；inspect 至少需要检查及后续四步的 5 个位置，并有下一次规划余额。repair 需 3，verification 需 2，review 需 1。
- 这是该单次实施模式的可行路线检查，不是跨进程的资源预留。先检查后仅剩不足额度时，通过原 PolicyStop 暂停，不执行检查或额外模型调用，不重写目标。
- 原受理前两次确认重查额度；只排除与本候选 operation、basis、phase、intent sequence 完全匹配的暂定 intent，避免最后一个合法名额被重复扣减。
- 同 command 重读回执继续沿原幂等路径；不因缓存查询追加 Work。其他入口、并发、取消、日志追加不明沿原合同。验证失败或评审拒绝不会使 Goal 完成。
- 冷读使用同一个冻结任务，核对 Goal 元数据及各阶段计数。仅有预算不表示目标满足；证据仍须通过原完整验证和独立批准。

## 兼容与比较

默认任务不启用新模式，原 calculator profile 仍为 20 Work；既有调用方不能临时传更大 limit 来覆盖任务上限。新模式通过不同的 planning_limits 元数据显式留下限制。旧 reader 的固定 20/8 校验会将其视为不匹配，不承诺旧版可执行或给出 current；原记录不迁移、不补写。新模式仍是 Product 私有任务合同，不提升为 HarnessWork 通用预算 API。

未选择：另一套 Goal controller、外部第二份预算账本、只靠模型自觉遵守文本，或在失败后自动重开 Goal。是否需要通用配置以及多次实施/复杂重规划，仍是后续独立问题。

## 离线验证与审查记录

本轮测试直接检查原模型适配器收到的准备请求，实际运行原 inspect、Method/write、完整验证和评审，再关闭 owner 冷读。要求覆盖：直接实施、检查后实施、总额不足、规划额不足、非法/扩大配置，以及旧默认路径。首轮新配置与闭环测试 16 passed（91.46 秒）；不足四步时零模型暂停与幂等查询 1 passed（20.46 秒）。计算器 Goal 兼容回归 73 passed、5 skipped（190.18 秒）；仓库其余回归 39 passed（406.73 秒）。最终输入区分 model_actions 与 work_routes 后，受影响四条路径复验 4 passed（41.25 秒）。合计 129 项不同用例通过、5 项跳过，另通过 Ruff、架构依赖及 9 项文档检查；未将重复复验计入不同用例总数。

职责与复用、运行与失败、数据与兼容三个视角由本轮实现者自查，不冒称三个独立 agent 已评审。设计与原型等待用户对重要私有合同增量的评审；不据离线通过启动付费模型。


| 自查视角 | 结论与证据 |
| --- | --- |
| 职责与复用 | 冻结任务只配置更小的 Coding 策略；总量仍由原 GoalController/records 校验，阶段数量从原 batch intent 推导，没有第二份账本或执行循环 |
| 运行与失败 | SDK 实测 4/6 Work 两路径恰好在预算内完成，覆盖 intent 后二次确认；不足总额/规划额在 inspect 前暂停，最短路径不足时在首次模型调用前暂停；幂等回执不扣新名额 |
| 数据与兼容 | 小额度进入原 Goal 元数据及实际模型请求；各阶段数量也入 planning_limits，避免旧 reader 将新任务当默认合同；默认仓库与计算器回归验证默认值未放宽 |

外部下一轮驱动模板已移除“首步必须 implement”的判断，只调用原 advance 至 repair 或原策略停止，再请求宿主验证/评审。该模板仅语法检查，未创建在线任务包或运行根，未使用 Kimi 凭据；不能把模板存在计作真实验证完成。
