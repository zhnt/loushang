# 模型规划专项：三视角独立评审与处置

- Authority: descriptive — 固定设计修订的技术评审证据，不代替用户接受。
- Design status: technical-review-complete，user-accepted（2026-10-26）；Implementation status: in-progress。
- Owner：Loushang 协作架构；实施代理汇总，独立 reviewers 提供发现和复核。
- 方法：干净本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 需求：[G-GOAL-PLAN-01](../../plans/2026-10-26-goal-model-planning-loop.md)。
- 对象：[专项](model-planning-loop.md)与[场景合同](model-planning-scenario.md)。

## 评审框架

三名独立 xhigh agent 分别负责职责与复用、运行与失败、数据与兼容。每人从固定
需求、父架构、方法与本地源码出发，不读取其他 agent 的评审；实施代理负责综合
取舍和修订，再将新固定对象交原 reviewer 复核。首轮对象未包含后续场景文件。
覆盖本地 SDK 部署、信任边界与验证范围；不承诺远程/跨平台，也不启动产品代码。

本记录中的关闭只代表设计合同和静态走查闭合。未运行模型、产品测试或故障实验，
不会把 source 取证、文档检查或 reviewer 同意升级为运行验收。用户要求“系统环境图
等重要工作件需要我评审”，此检查点尚未发生。

| 固定修订 | 对象摘要 |
| --- | --- |
| R1 `58c41e9d56aa8d82c627c820c101fade861d9df9` | 专项 SHA256 `754799add50ee1333d321aec49587387a37d7026175c25c044758a5aa983be61`；源码基线 `f3ee31319902e5677e14eb67ba56c1dd1917bea8` |
| R2 `086bedfec2dd9f9288c3892adaf04a820bb353bb` | 专项 SHA256 `3d5bfd35afc54f2d0299cd5dfa5d0c61d6564830415058bcf7485eeb8905a6ec`；场景 R1 SHA256 `04d06f0a4ead7840019d25c393212f20a0ce9791b2fd3f2f6501ee0bbecbc16a` |
| 最终技术复核 `02b2208b7fe9819baa5058c50ab80bb86345c357` | 专项 R2.1 SHA256 `aa7c4c81a5756401b54e1e95d231757300b9e202da1e2cf1c596697cf4869d70`；场景 R1.1 SHA256 `99a36907cb45fd6c15f16c15eae7cc3b70fc477a6a742357e9bf7012181f8ed1` |

上述为 reviewer 实际核验的对象；之后仅同步技术复核状态和本记录链接，没有修改
机制、判据或场景语义。完整 Git 修订保留每次评审的可复现对象。

## 职责与复用视角

Reviewer：`planning_review_ownership`。R1 认可规划进入原 Work、三合同及 source/Blob
复用；不认为需要新增共享引擎。R1 两项阻断，R2 原项关闭并发现一项新反例：

| ID | 发现、证据与影响 | 处置 / 状态 |
| --- | --- | --- |
| O-01 | R1 只比较路线建议尾部，未要求变化真正执行；改尾部后撤销也可能误关 GP-03 | R2 绑定 next_action 与首项，要求 admitted 且实际执行，明确排除撤销尾部；reviewer 设计关闭 |
| O-02 | R1 repair(targets) 未说明范围是授权还是意图；原 Method 是整文件修复，现有适配也只保护其他文件 | R2 改 repair 为整文件，固定动作前提与 Method inspect 只读；reviewer 设计关闭 |
| O-03 | R2 check(targets) 都执行完整 23 项，仅变关注标签仍可能按 targets 差异关闭 GP-03 | R2.1 将 check 归一 check_all，相同输入仅报告角色变化也排除；补实际执行反例；reviewer 最终设计关闭 |

R2.1 已修正“已受理路线摘要”“目标子集检查”等遗留措辞。委托器限定为
原 stream_fn 的调用前准入，不拥有 provider、调度或账本，职责方向可保留。

## 运行与失败视角

Reviewer：`planning_review_runtime`。R1 三项阻断，一项非阻断：

| ID | 发现、证据与影响 | 修正及 reviewer 结论 |
| --- | --- | --- |
| RP-01 | 空工具集下，agent_loop 对未知工具返回 terminate=False，仍可在一个 Work 内无限采样；批次限额不增长 | 现有 stream_fn 处限制每 planning Work 一次逻辑调用；关闭此 Session 自动 retry/compaction；provider 尝试另有界，不修改 Agent loop；R2 设计关闭 |
| RP-02 | stop_reason=error/aborted 可正常结束 prompt，SessionTurnExecutor 未必抛异常，Work 可 completed；合法 JSON 不足以证明规划成功 | 单 invocation、已提交响应和成功 stop outcome 联合核验；error/aborted/length/toolUse/缺 outcome 拒绝；R2 设计关闭 |
| RP-03 | 原 handle 仅接受 running repair 输入；R1 未选择 planning 输入窗口，队列被消费/清空后无法凭最终 pending=0 排除污染 | 保留 repair-only 输入，规划允许 pause/revise/cancel；原队列不复制，异常插入依原记录拒绝；R2 设计关闭 |
| RP-04 | 无进展 2 次的 reset/交错规划/源码改变语义不清 | 场景加入固定序列，只有新知识或固定失败集合严格缩小重置；R2 主要澄清关闭，报告实际覆盖的后续建议随 R2.1 关闭 |

源码依据包含 `agent_loop.py` 的工具 continuation、`SessionTurnExecutor.execute`、
`GoalController.advance`、`CodingGoal._input` 与原 PolicyEvaluatorChain。

## 数据与兼容视角

Reviewer：`planning_review_data`。R1 两项阻断，两项非阻断：

| ID | 发现、证据与影响 | 修正及 reviewer 结论 |
| --- | --- | --- |
| D-B01 | TranscriptRecordCommitted/ModelCallOutcome 本身没有 Work 与响应互相外键；prompt 可含重试/压缩，不能猜 invocation | 限定单调用，agent.message_end.source_record_id、提交路径、input snapshot 祖先、invocation/outcome 联合核验，明示拒绝分支；R2 设计关闭 |
| D-B02 | intent.source 已有提案不代表 Work 已受理；not_submitted 或 accept 后缺 association 时的消费/冷读语义不明 | 增加意图/预约/消费/原 run 受理派生表，自身 intent 二次确认例外；unknown 不释放预约；R2 设计关闭 |
| D-N01 | 连续失败计数和拒绝理由持久来源不完整 | R2 固定清零条件、not_submitted/过期/unknown 分类；精确不可恢复原因显示 unknown，不伪称都已记日志；设计合同关闭 |
| D-N02 | 旧 reader 的 unsupported/unknown 不能抹掉可读 Goal 历史 | 保留原 header/policy 兼容边界，实现阶段验证分层错误显示 |
| D-N03 | check(A) 已公开完整结果，再 check(B) 不应只因请求标签首次出现就算知识增量 | R2.1 按报告实际覆盖去重，补对应序列；最终 reviewer 关闭 |

该视角确认冻结 source、嵌套 WorkEvidenceReported、原 operation 查询和 policy_id
边界可复用；没有证据要求新增共享 record kind 或另一份计划事实日志。

## 综合结论与实施边界

R1 三位 reviewer 均不建议按“阻断已关闭”提交用户接受；方向保留，机制需补齐。
三位 reviewer 对 `02b2208b7` 定点复核后均报告本视角无剩余设计阻断，可提交用户评审。
共同结论：保留原三合同和 Work 执行，Product 私有规划适配足以承载首版；实质调整
必须落在实际执行上，权限、响应成功和消费历史不可由模型自报。
评审结论不替代真实 GP-03 轨迹、调用限额/取消实验和兼容测试；这些仍是完整 Goal
完成的必要证据。用户接受具体重要工作件后，才能按对应范围进入实现。

本轮只修改文档；文档轻检查 9 项及相对链接、diff 检查通过。实现阶段重点回访：
prepared-request/取消透传、第二次规划请求零 provider 调用、错误终态不可消费、工具
配置恢复失败 fence、丢失 Transcript/Work/Blob 的冷读呈现，以及真实模型调整证据。
这些由 Coding 实施 owner 关闭，不能以本轮技术评审代替。

## 用户接受与实施启动

2026-10-26，向用户列出 R2.1 核心观点后，用户明确回复“同意，请继续goal”。
接受范围为专项 R2.1 与场景 R1.1，实施从 `3474940c2` 开始；技术复核记录仍对应
上列固定修订，不将用户授权当作实现验证或真实模型验收的证据。

## 实现三视角复核（2026-10-26）

三位原独立 reviewer 分别检查基线 `3474940c2` 上的实施源码；首次固定输入与产品树外
`implementation-r3-inputs.json` 对应，随后对修正作定点复核。未读取彼此结论、未运行
真实模型；执行验证由主代理完成并单独记录。保留设计评审与实现验收的区别。

| 发现 | 修正与关闭依据 |
| --- | --- |
| IO-01 Method 未知步骤可能在修复之后才失败 | 新 profile 受理前核验完整 inspect→repair 序列，透传原 PolicyStop；未知尾步、倒序、缺步和不支持 constraint/audit 的反例已覆盖 |
| IO-02 / D-I02 只有 live trace，没有原记录冷读 | 新只读 Transcript 适配与 live/cold 共用投影；显示原提案、响应证明、intent 消费和原 run 受理；缺 Transcript/损坏 invocation 列表时 planning unknown，Goal 视图保留 |
| D-I01 snapshot 外壳通过但组件未验证 | 调用原 rebuild_model_input，核验完整组件/root hash/origin；坏来源反例与真实 v1/v2 来源检查，不自建摘要算法 |
| IR-RP01 context 扩展可改写可信输入 | 新 profile 禁 context，且核验重建实际末尾 user 和空 tools；构造拒绝反例 |
| IR-RP02 阈值达到后多一次 advance 才暂停 | Product assessment 在同次 advance 收束；合法最终验收保持优先，不派发额外 Work |
| IR-RP03 包装器取消与恢复失败证据不足 | 6 种确定性组合经过原 Work cancel、Session abort/idle 和包装器恢复；恢复异常或不一致 fence 并拒绝新 advance；不扩张为 live provider 全故障证明 |
| IO-03 GP-03 真实调整未达成 | **未关闭**。三次原场景完整留证；不把 r2 沿原路线成功或 r3 未执行的计划尾部当作重规划成功 |

实现和测试结果见[实施记录](model-planning-implementation.md)。新增分层 JSON profile
候选因未证明优于原场景而撤回，不为验收另建框架。后续协作场景仍为待用户讨论的
候选，内部评审不替代用户对其验收范围的确认。
