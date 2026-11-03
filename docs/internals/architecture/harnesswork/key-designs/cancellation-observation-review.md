# HW-KD-001 专项评审记录

## 状态与范围

- Authority: descriptive — review evidence。
- Design status: not-applicable；Implementation status: complete（观察切片；集成按 PR 记录）。
- Owner：HarnessWork 专项设计维护者；用户保留重要架构工作件接受。
- 对象：[取消观察专项](cancellation-observation.md)；基线 `11b854951125d3437fea9f43f65a9788af620933`。
- 方法版本：干净本地 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

当前实现依据为 **R4.2 观察切片**，新增来源码与实施复核见文末。R1–R3 的控制重构/全 runtime 故障方案仅为未接受
历史候选；R4 的数据阻断已在 R4.1 修正，不沿用先前候选的通过结论。

本轮评审完整的专项候选合同，不能沿用此前能力清单的通过结论。三个独立 xhigh
视角分别检查：职责/复用/架构协同，运行/并发/失败，数据/权限/兼容/恢复。
固定快照、哈希及原始 findings 在产品树外留证；以下登记实际修订与受影响复核。

## R1 三视角结论与 R2 处置

R1 SHA256：`6040814432182c9160cff7ff526f39b3f43b3487cef886273e484a9c9f276adb`。
三位独立 xhigh reviewer 的结论均为 needs_revision：A 1 项阻断，B 2 项，C 3 项，
另 C 1 项非阻断。缺陷主要集中于数据位置/版本、自取消兼容和写入失败责任，
不是要求增加 Goal 实现或第二个执行内核。

| Finding | 阻断 | R2 处置及待复核条件 |
| --- | --- | --- |
| A-R1-001 元数据位置与 opaque/wire 合同不明确 | 是 | 唯一位置改为 journal owner envelope；WorkEvent/domain map 不变，明确 listener 通过 getter 读取。核对日志与旧 Channel 路径 |
| B-R1-01 自取消误驱 domain、改变旧异常分类 | 是 | 无显式认领时不调用 binding，原 CancelledError/Cancelled 保留，观察 unknown/executor_interrupted；已有认领复用一次决定。核对竞态及原分类 |
| B-R1-02 请求/前序 append 失败尚无协调者 | 是 | 新 CO-D5/§6：runtime publication fault、拒新受理、所有旧发布入口 fence、有/无已受理取消分支的 cleanup owner、API 和重开结果。核对三类失败及 wait/dispose |
| C-R1-001 两处版本判定冲突 | 是 | 定义先 lifecycle 校验、再 operation marker、最后支持版 terminal 的优先表；未知 future 不解码，op1/terminal2 报错 |
| C-R1-002 reported_status 与超时及终态组合不完整 | 是 | 完整允许元组表；execution_timeout 保留之前有效报告，不接纳迟到报告覆盖；非法组合报错，单一归约与解码共享 |
| C-R1-003 可变 spec 绕过保留 key | 是 | 改为业务 map 外的 owner envelope，去掉保留 key/冻结要求；serializer 参数由 runtime 单独提供，不能从业务 dict 注入 |
| C-R1-004 元数据自动经过 Channel 的范围误述 | 否 | 同上窄方案使 WorkEvent 不携 owner metadata，现有 Channel payload 维持原形；原始日志查询仍可见，不当作秘密或远程授权 |

## 架构协同与修订影响

Runtime Invariants 的强收尾 Target 不改；unsupported→cancelled 的 Current 差异不关闭。
本专项没有修改 AOD/生命周期枚举/组件依赖，原 migration-ledger 的 opaque 业务载荷
保持。局部新增 journal metadata/查询与一次取消协调，属于 HarnessWork owner 的候选
合同细化。CO-D5 明确提出发布故障的 runtime 级隔离及清理，可能影响同 backend 上
其他 Work；该候选取舍须在本专项中评审和接受，不能冒称纯加字段或零行为影响。

R2 SHA256：`d3d3f3afc99565beb06a4821469a6f91ef2eca2c91bc62a0eb12374e8eb1477a`。
R2 原六项阻断及一项非阻断均在受影响合同层面完成修正。B 给出 ready_for_user_review
并保留两条澄清；A/C 对隔离入口的明列范围采用更严格解释，给出 needs_revision。
维护者采纳明列完整表面的建议，没有以 B 的通过否定另外两路的具体证据。

| R2 finding | R3 处置 | 静态复核要点 |
| --- | --- | --- |
| A-R2-001、C-R2-001/002：写入/公开查询表面遗漏 | 唯一 append 边界纳入 operation/domain fact/全部 lifecycle；完整 API 故障表补解析、活动查询、订阅、诊断、清理 | operation 失败不启新 task/不重试，domain fact 不递归发 Failed，fault 后查询不返回正常快照 |
| B-R2 两项非阻断澄清：同上及 Channel 调用点 | 同上，并指明原 Session/Channel 受理/取消/关闭/相关性职责 | close 不依赖会报错的 active_runs；Session 不误报忙碌；原 ChannelError/None 相关性分支，不增 wire |
| A-R2-002、C-R2-003：示例夹带 source 字段 | 删除 source:{}，只增加 owner envelope | 保持原 operation kind/domain/payload，不扩用户数据落盘范围 |

R3 SHA256：`2ea9118c44f9aa0c813deb11e88343b6f1cf7c750722a2e9b39d88ab8035d68b`。
三位原 reviewer 已独立复核受影响合同及组合一致性，没有读取其他报告或本汇总页。

| 视角 | R3 实际结论 | 当前提交阻断 |
| --- | --- | --- |
| A：职责、复用及架构协同 | ready_for_user_review；envelope/opaque 边界、全入口隔离及必要的原 adapter 协同成立 | 0 |
| B：运行、并发和故障 | ready_for_user_review；原两项阻断与后续澄清已落实，无新增等待环阻断 | 0 |
| C：数据、权限和兼容 | ready_for_user_review；版本/元组及 R2 的 append/API 问题关闭 | 0 |

各修正只建立候选设计的明确合同，不证明实现、异步时序或数据耐久性已通过。
元数据读写、query/fault signal、cleanup、旧 reader 和既有 Channel 行为都须按
CV1–12 在获得实现授权后验证，不以此评审替代运行证据。

B 额外核对一个非阻断的原合同排歧：健康路径 cancel/wait 只控制本实例 _states；
仅在历史投影中存在的 run 不因可被 get_run/get_cancellation 读取就获得取消权，仍依
现有 UnknownWorkRunError 处理。本实例持有的已终态 run 才适用 cancel 原样返回。
publication fault 时则 §6 的 WorkPublicationError 优先，不形成绕过隔离的例外。
这是 R3“运行 owner 内/照旧”的基线含义，不接受新的历史控制能力。

R3 当时可交用户本人评审，但用户未接受。后续用户同意重新比较 CO-D5，并要求
继续隔离实验、R4 收敛及评审，因此不将 R3 的“可提交”扩展为当前方案的接受。
原强收尾/fencing 差异、Goal 完整架构及功能开发暂停仍保留。

## R4：以实验收敛第一阶段

R4 固定快照 SHA256：`1fe392c5c43f19eacf8c715c9a36a6711fe2bb55a5429e540db92235ec72129e`。
R4 缩小为“原终态裁决点的观察记录、查询、回放”；R3 的全 runtime publication fault、
新协调者和 Channel 改造不是第一阶段前置。它们仍是未接受的后续备选，未删除原风险。

| 实验组 | 执行结果与限制 |
| --- | --- |
| 4 组存储故障注入 | 真实基线 JSONL backend/journal；写前、半行、完整关闭后抛错、索引更新前抛错均按预期复现。后两种内存 1 条/冷读 2 条，盲重试为 3 条并被 strict Work replay 拒绝 |
| 显式尾行修复 | 只在副本启用既有 partial_tail=repair，恢复完整前缀后显式追加可合法回放；原 Work 默认严格策略未变 |
| 4 组取消流程 | settled/unsupported/failed 各并发两次 cancel，已有流程单 terminal、有 binding 时一次驱动；自取消不调用配置的失败 binding，并保留原异常 |

脚本 `probe_r4.py` 和结果 `probe-r4-results/results.json` 在产品 Git 外留证，脚本
SHA256 为 `64faa19d2397ede0267c3f99c587365fc46e361f1fa95c2ec0e54ecc5cfe97eb`。
实验在沙箱外运行，仅使用隔离文件和故障替身，未改产品代码、未调用模型/网络。
5 秒只是单例实验失控保护，不是产品 timeout；没有断电、真实磁盘满、多 writer 或
所有取消竞态验证。控制示例能取到数据不证明永远不需要协调增强。

R4 的新增边界是：append 失败只使**新观察查询**不可确认，不把它冒充停写/停止执行，
不改变旧控制 API；真实恢复需停止 writer、由日志 owner 核对，并另行接受。元数据
仍在 owner envelope，不进业务 payload/Channel。settled 的候选含义收敛为“终态裁决前
binding 报告”，不再承诺 R3 的新 coordinator join 语义；R3 未落地，不存在实际新日志
被静默改义。本次评审须核验这个取舍和剩余风险，不能复用旧 R3 结论当作通过。

R4 的 A 视角 ready_for_user_review/0 阻断；B/C 独立指出一个相同的 domain_timeout
报告元组问题，C 另指出非终态 unknown 的依据字段缺失，因此 R4 当时 needs_revision。

## R4.1 数据修订与三视角复核

R4.1 SHA256：`7b59433730f6cdf708fcc3bbfb5a28ed07ee0bf9c5e2ecf0174a0d4fd19c4693`。

| Finding | 处置与关闭范围 |
| --- | --- |
| B-R4-01 / C-R4-001：超时与真实迟到报告不可同时表达 | 扩 domain_timeout 元组，保留冻结点前实际三种报告或 null，不覆盖原 Failed/超时异常；原因/outcome 来源绑定获选归约，不添 timing 字段或控制机制 |
| C-R4-002：非终态 unknown 必含依据字段未定义 | 新逐 run 依据表：各 unknown 的 journal basis、该 run 末 entry sequence/event_id；operation-only 0/null；live 截点取成功 ACK 而非预增 sequence；与离线额外事实区别明确 |

补充实验 `probe_r4_timeout.py` 在沙箱外执行，实际证明原 domain_timeout 可与 terminal
前真实 settled 报告共存；原 WorkRunFailed/WorkCancellationTimeoutError 不变。脚本
SHA256 `273f45aa196bd4da1404c317215f7dcde5ca1531e2f753d475cfa07af4c9f0ee`。
这不是候选观察实现测试；实验只实证 late settled，late unsupported/failed 等仍须 V2。

| 独立 xhigh 视角 | R4.1 结论 | 当前提交阻断 |
| --- | --- | --- |
| A：职责、复用、架构协同 | ready_for_user_review；数据修订保持观察切片，不加恢复/控制前提 | 0 |
| B：运行、并发、失败 | ready_for_user_review；原超时归约与真实报告可同时忠实表达，不需新精确时钟字段 | 0 |
| C：数据、权限、兼容 | ready_for_user_review；两项数据阻断关闭，覆盖已列各历史/活体例子 | 0 |

三位均独立核查固定修订及源码，仅读取实验材料，没有自行执行实验或读取其他报告。
维护者执行实验并汇总处置，原始 JSON/快照在产品树外保留。结论仅为可提交用户，
不是 accepted Target、候选新功能已通过或所有取消/存储风险已解决。

后续 owner/触发条件：HarnessWork 在获准实施时按 V1–7 验证真实来源标签、逐 run
ACK 截点、不可变观察、listener 次序及新 getter 不可用标记；日志 owner/Product 对
候选 B/C 或任何恢复动作另作场景驱动的设计。现有 binding 报告范围仍须核实。
不将这些后续工作偷偷作为第一阶段的新协调/全局隔离实现前置。

## 验证与接受边界

R1–R3 均通过 9 项现有静态文档检查及相关相对链接/围栏检查。R1–R3 为静态评审，
未运行 runtime/pytest；R4 已运行上述隔离的 Current 实验，仍未实施候选观察功能。
R4.1 亦通过 9 项既有静态文档检查及相关相对链接/围栏检查；产品 src/tests 无修改。
Mermaid 未经渲染器验证。R3 CV1–12 和 R4.1 V1–7 分别是各候选的实施验证计划，
不能把本轮基线实验当成新功能验证，也没有新增 CI 门禁。

以上是截至 R4.1 设计轮的执行状态，不覆盖后续用户“继续”后的第一阶段实施。

## R4.2 实施与受影响复核

用户在第一阶段开发建议后要求“继续”，本轮按其范围实施取消观察。没有将该授权
扩大为完整 Goal 架构接受、恢复其他 Goal 开发或 R3 控制改造。重要架构件的用户
评审安排仍保留；截至实施评审时代码处于本地分支，后续集成授权见实施记录。

R4.2 合同 SHA256：`9fa0cf2a983edc62a6ccdd09ae4fc15ef330b0e2a2ecb6741a8530f368256ff2`。
最终 runtime SHA256：`79969aa84296391d634fcabae0c3546ced7ce062488df68e6f1c13c9e902c128`；
projector SHA256：`3cefec21218f1c569c7e754c9580a2264e99a2239698b8a95366175ebca983f6`。

| 实施发现 | 处置与复核范围 |
| --- | --- |
| 三路独立发现 operation-only 同名误判 | 识别 terminal 必须 entry_type=event；补三种同名操作回归 |
| C 发现请求 append 写后失败，binding 存在但未调用 | R4.2 增补 unknown/cancellation_not_driven/null，限 Cancelling+Cancelled；不改变原 unsupported 归约。补写前/写后原异常身份、调用数、warm unavailable 与 cold replay 差异 |
| A 提出来源侧车的资源建议 | 终态确认后清理，迟到来源不再加入；原终态先行判断保护后到 waiter |
| C 提出故障测试宽泛吞异常 | 所有 15 种 append 点的写前/写后测试增加原 append_error 对象身份传播断言 |

三位原独立 xhigh reviewer 分别重新评审实现，未读取其他 agent 结果。它们核对最终
源码和 R4.2 固定合同，不把 R4.1 通过当作实现通过；实际 pytest 由主代理执行。
原始 `implementation-review-a/b/c.json`、固定快照和源哈希保存在产品 Git 外。

| 独立 xhigh 视角 | 最终实现结论 | 未关闭阻断 |
| --- | --- | --- |
| A：职责、复用、架构一致性 | no_blocking_architecture_findings；同名 operation 与资源建议关闭 | 0 |
| B：运行、并发、故障 | ready_for_final_verification；多 waiter 差异 deadline 等组合保留为验证局限 | 0 |
| C：数据、可验证性、兼容演进 | ready_for_user_review；两处数据缺陷及异常传播断言盲点关闭，保留非阻断覆盖建议 | 0 |

最终执行范围、剩余验证局限和下一步边界见[实施记录](cancellation-observation-implementation.md)。
全包 mypy 的 20 项错误已与固定基线比较，错误诊断相同，仅扫描文件数因新模块
从 23 变成 25；不是本次新增，亦未在本轮顺手修改。未新增 CI 门禁。
