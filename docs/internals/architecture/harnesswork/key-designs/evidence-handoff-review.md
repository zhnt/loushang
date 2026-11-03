# HW-KD-002 专项评审记录

- Authority: descriptive — review evidence。
- Design status: not-applicable；Implementation status: not-started。
- Owner：HarnessWork 专项设计维护者；重要架构工作件仍由用户评审。
- 对象：[证据交接专项](evidence-handoff.md)；基线 `372cde4ade0fe026076c8fa5e8b4486774b09cc3`。
- 方法：本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

当前候选为 R2.2，外部独立评审后的处置见文末。下列 R1–R2.1 结论保留为其固定
修订的历史证据，不自动覆盖外部新增发现或 R2.2。

## 本轮范围

固定专项修订，三个独立 xhigh 视角分别检查：

1. 成果、职责、复用及与 Goal/Method/Work 架构的协同。
2. 运行、寿命、并发、取消及部分失败。
3. 数据、权限、演进兼容及验证证据。

协同核对[Goal 最小闭环待评审决策](../../goal-method-work/minimum-loop-decisions.md)，
只检查它与本专项有无冲突，不把这份决策提纲当完整 Goal 组件/接口设计。
独立 reviewer 不读取其他 agent 报告；原始报告、快照和哈希留在产品 Git 外。

## 执行与接受边界

维护者已运行产品树外的既有底座组合实验：正常两步、持久重开、临时目录清理、
源变化与缺失/篡改，以及 evidence append 写前/写后故障。它证明所列现有原语可
组合，不证明候选公共 codec/projector 已实现或所有 Product 已装配。

以下登记固定修订、独立发现与处置。用户接受未发生。
本轮无产品源码/测试修改、无新增门禁、不恢复 Goal 主体开发。

## R1 三视角独立评审

R1 SHA256：`2359fe21ce6c5476a807bfbf3bbf437e4e39356f4e69b32c89250b5345f3e361`。
协同 Goal 提纲 SHA256：`d7ca062e0c93cf80031354321d93c4d0373b47b6ee360a8d560ee29e1f042c44`，后续未改。
三位 reviewer 独立读取固定工作件、原始实验与源码，没有读取其他报告或本汇总。

| 独立 xhigh 视角 | R1 结论 | 阻断 / 非阻断 |
| --- | --- | --- |
| A：成果、职责、复用、架构协同 | 可交用户，建议补更窄的 Product 私有选项 | 0 / 1 |
| B：运行、寿命、并发、取消、部分失败 | 可交用户，补 quota 组合断言并限制 busy 承诺 | 0 / 2 |
| C：数据、权限、兼容与验证 | 可交用户，明确缺失键语义和 private metadata 的 consumer 边界 | 0 / 2 |

| Finding | 采纳与处置 | 关闭范围 / 后续触发条件 |
| --- | --- | --- |
| A-N1：底座组合不能证明现在需要公共 core/facade | R2 比较并优先选 Product/SDK 私有编解码/查询；HarnessWork 维护中立引用关联，业务词义归 Product | 设计建议关闭。只有真实多 Product 依据或另行接受边界记录后才考虑提升共享 API |
| B-N1：report 成功后 validation 转存配额耗尽 | R2.1 明列保留 report、原 quota 异常/Work failed、不发伪造 validation，加入 EV5 | 设计/验证计划补齐；新实现的 quota 组合测试尚未执行，不记作运行验收完成 |
| B-N2：原 Blob 锁默认可能阻塞 | R2.1 明确实际抛出 BlockingIOError 才传播；不承诺竞争时立即 busy、固定响应时间或新增 timeout | 设计澄清关闭。有界交互要求出现时，在原 store/Product 边界设计，不新建协调服务 |
| C-N1：可空 reported_step_id 缺失语义不明确 | R2.1 要求 v1 四键齐全、先识别版本；step 显式 null 可，缺键是坏 v1，EV3 分别断言 | 数据口径关闭，实施时仍需真正 decoder/round-trip 测试 |
| C-N2：private 标签不会过滤 Work metadata | R2 明列 listener/query/subscription 原样可见；仅限本地授权 SDK，不把完整 ref 删改后冒充原引用 | 设计说明关闭；首个集成须记录真实 subscriber/reader，跨权限/远程 consumer 是重审触发条件 |

## R2 收窄与 R2.1 精化

R2 SHA256：`080333b8ffe5e81bfe69ea63b01c1248235c57d28e47fa2ae1327ada64841894`。
本轮将“通用能力先建好”收窄为“真实 SDK 任务先集成，确有必要才增加私有函数”，
保留既有 Blob、Work 与 Product owner；不提前增加公共 core API 和 facade。
三个原 reviewer 已分别对该范围变化与组合一致性复核，没有新增阻断。

最终 R2.1 SHA256：`56b67f93a5fbe9db318109eb45840e14bb12ff73d8106e5836a2aa3da98f9bcd`。
相对 R2 只精化必需字段、默认阻塞锁的限制及 quota 部分失败/验证断言，没有新增
存储、运行控制、公共 API 或 Goal 语义。固定快照与各路受影响复核独立留存，未受
影响的 R1/R2 证据复用，不重写历史结论。

| 独立 xhigh 视角 | 最终 R2.1 结论 | 未关闭阻断 |
| --- | --- | --- |
| A：成果、职责、复用、架构协同 | ready-for-user-review；私有优先及词义 owner 建议关闭，组合边界保持 | 0 |
| B：运行、寿命、并发、取消、部分失败 | ready-for-user-design-review；两项设计意见关闭，新实施断言仍待执行 | 0 |
| C：数据、权限、兼容与验证 | ready-for-user-design-review；字段口径与 consumer 边界说明关闭，无新设计发现 | 0 |

配额表述按没有同时取消/日志失败的普通 quota 单故障理解；组合竞态继续沿用原
Work 取消与错误优先级，不能把本专项解释为新异常裁决。对应实现组合测试仍待执行。

## 已执行验证与局限

原始 `probe_existing_handoff.py` SHA256：
`ee24f36c932b05e019f54791c08263d7f38bdc3b6a5fb8ddcdc7a894a81caa96`。
维护者按工作区规则在沙箱外执行，全部对象在产品 Git 外的隔离目录。源码基线、
12 个相关源文件哈希、固定工作件、实验 JSON 和各路原始报告留证，没有导入参考
仓库分析或源码到产品树。

| 实测 | 结论与限制 |
| --- | --- |
| 两步 Work 生成报告及验证结果，使用现有快照/转存/JSONL/Blob | 两份引用重开可读；临时 run 清理后仍在。验证内容绑定报告摘要；不是 Goal 验收器 |
| 修改工作区源、篡改 Blob、删除 Blob、外 Session 引用 | 源改变不影响已保存快照；篡改 corrupt、丢失 missing、外引用非 available；不证明适用于最新代码 |
| evidence append 写前/写后抛错 | 原 OSError 身份保留，冷读分别 0/1 条报告，Blob 保留、无自动重试；没有证明任意 I/O 异常可自动对账 |
| 既有文档检查 | 当前 change-aware 计划只选 docs；9 项检查通过，5 份改动文档的相对链接/围栏核验通过；无新增门禁 |

三位 reviewer 均为静态核查，未自行运行产品或测试。候选私有 codec/projector 尚未
实现，EV1–EV6 是未来实施断言；未跑新增产品 pytest，也未验证所有生产 Product、
hosted、断电、多 writer、完整 quota 组合和锁竞争时延。Mermaid 只核对代码围栏，
未用渲染器验证。不能把组合实验写成候选实现或全局一致性保证。

## 提交用户评审的范围

本轮可审查的是：本地 SDK 私有交接、持久 Blob 引用的内容/寿命与 Work 关联边界，
以及单独的三项 Goal 决策提纲。用户接受前不把这些候选改为 accepted；Goal 系统
环境图和完整组件/接口仍须按原安排评审。后续代码应由真实消费任务驱动，不因为
设计有函数签名就必须新建公共服务。

## 外部独立 R2.1 评审与 R2.2 处置

用户另提供一份未读既有报告的独立评审，指出三项阻断及四项非阻断。维护者重新
核对源码并作隔离复现，没有以原三路通过否定新证据，也没有照收全部推论。
前述 R2.1 的可提交判断据此重新评估，相关缺口已进入 R2.2。

| 外部 finding | 采纳判断与 R2.2 处置 |
| --- | --- |
| F1：遗漏 WorkStepDeviation.evidence_refs | 采纳盘点/关系缺口。该字段已有字符串反序列化与步骤投影，不能当作不存在；也不是已具备持久 Blob 解析的机制。补 Current 行、并存关系、Product 显式解析/未解析材料保留、避免重复登记或重复计独立证明，以及 EV7 |
| F2：顶层键污染 run/plan 投影 | 采纳实际风险并补完整 11 键影响面；v1 事实 payload 精确 `{evidence}`，标准 adapter 发布前拒额外键，新查询也报错。不采纳扩大全局保留键/修改 kernel 的方向，也不把步骤元数据污染说成 envelope 的 run/operation 身份已被改写 |
| F3：步骤自报的使用责任不完整 | 采纳。Product adapter 直接读发布时 context；Goal 禁止单独按 reported_step_id 或通用 current_step_id 判要求满足。要求侧负责批次覆盖与验收；确需强步骤证明时另补证据/合同，Goal 提纲同步 |
| F4：single writer 不是 backend 保证 | 采纳澄清。明确为 Product 装配/使用前提；无 lease、无跨进程拒写或完整检测保证，多 writer 不受支持。没有因此新增锁/协调服务 |
| F5：完整 ref 比较与一 ULP 推论 | 采纳全字段值比较说明；不采纳“真实一 ULP 改变仍被接受，因此 created_at 不参与归属”的推论。原 store 的受控实测拒绝了真正相邻的浮点值和 source 变更；manifest round-trip 仍可读 |
| F6：首个消费任务与私有位置 owner | 采纳。Product composition owner 明确任务、caller/reader/subscriber 和成功/失败判据；私有适配遵守该 Product 的集成边界，具体位置随真实任务确定，不放入 core |
| F7：应否期待证据的来源 | 采纳要求侧责任。Goal/Method/领域 owner 在本批受理前说明期待材料、可选/缺失处理；不从 completed 或空 tuple 推导无需证据，不声称预留字段已有强制机制 |

这里没有把旧字符串改成新全局 URI，也没有添加 resolver/登记服务。若偏离和新报告
指向同一材料，保留来源/用途，但验收不按引用条数计分；旧引用无法解析时保留
unresolved，不把材料静默丢弃。引用的字节归属仍按原 SessionBlobStore 核实。

发布前 guard 失败是 adapter 的本地校验错误，不等同 backend 已进入未知 append；
已经转存的字节仍按原 Session 配额/寿命处理，不据此回滚删除共享对象。新查询按
原 lifecycle 校验优先；绕过标准 adapter 的原通用投影风险仍在，不冒称已修复。

### 补充实测与判断限制

产品树外 `probe_external_review.py` 使用未修改的 `372cde4`：

- 仅嵌套 evidence 时投影步骤保持 step-real；额外顶层 step_id 时可变为 GHOST，
  再加 plan_id 时还可增加投影的 GHOST 步骤；各组 run_id/operation_id 均保持原值。
- 旧 deviation 的 `legacy-note` 字符串按原投影到达步骤 deviation 和 metadata，
  新报告仍在同一历史；该实验没有实现或证明旧字符串到 Blob 的解析器。
- 原时间 3.0 的浮点十六进制为 `0x1.8000000000000p+1`，math.nextafter 得到
  `0x1.8000000000001p+1`；修改后的 ref 与原 ref 不等，原 store 拒绝读取。
  修改 source 同样被拒绝，原 manifest 编解码往返相等且能读取原字节。

没有外部 agent 的原实验脚本，不能断定其一 ULP 结论的具体成因；不据此补造解释。
本实测只反驳“真正改变相邻浮点值仍属原引用”这一推论，不要求更改原比较机制。
这些都是纯投影及隔离同步 Blob 调用，首次在沙箱外执行，无网络或产品源码变动；
不是候选 adapter guard、Goal 验收或 EV1–EV7 的实现通过证据。

R2.2 专项 SHA256：`113bcaa4f1dba890477177e12a199f55f6a55284eb12431f4aec6547111c5fa0`。
协同 Goal 提纲 SHA256：`14c0f74317fb190e6a82381125ae3b8a7e1c5b8a1c0706f4471a76b0c2c21c84`。
原三位独立 xhigh reviewer 对固定双文档受影响条款及组合关系重新核查，复用未变
证据；不将 R2.1 的通过自动外推。用户接受仍待进行。

| 独立 xhigh 视角 | R2.2 实际结论 | 未关闭阻断 |
| --- | --- | --- |
| A：职责、复用、架构组合 | ready-for-user-review；旧引用、局部 payload 约束和要求侧责任不引入重复底座 | 0 |
| B：运行、寿命和部分失败 | ready-for-user-design-review；guard 是发布前局部校验，字节寿命、原控制及单 writer 前提一致 | 0 |
| C：数据、权限和兼容 | ready-for-user-design-review；并存、不双计、步骤证据等级及完整 ref 比较一致 | 0 |

三份 `review-a/b/c-r2_2.json` 分别核实最终双文档和证据哈希，未读取其他 agent 报告；
均为静态复核，未把维护者的隔离实验冒充其自行运行的测试。新增的 EV7 与细化后的
EV2–EV4 仍是实施计划，不是产品测试已通过；没有新增产品实现、门禁或架构接受。
