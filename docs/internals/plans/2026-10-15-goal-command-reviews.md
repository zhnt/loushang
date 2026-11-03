# `/goal` 方案三视角独立评审

## 评审框架与证据范围

- Authority: descriptive — independent design review evidence
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: Loushang architecture / 本次方案协调 agent
- 日期：2026-10-15
- 主题：[Loushang `/goal` 命令设计与实施方案](2026-10-15-goal-command-plan.md)
- 源码基线：`f2797520f3c6596aef58936ddb1a4400f546172c`。
- 方法咨询：本地干净 archmethod `master`，`0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；不是远端同步证明或项目采用版本变更。

用户要求完成调研、制定实施方案并做三视角独立评审。本次是三个独立 AI reviewer 的源码与方案走查，不是真实客户/运维访谈、实现测试、Target 接受或发布授权。没有运行 Codex 测试、Loushang 功能测试或真实 provider 调用。候选方案的设计可实施性与未来实现符合性分别判断。

三位 reviewer 使用独立上下文，最初只获得同一方案、评审视角、治理约束与可访问源码，不读取其他 reviewer 输出；设计者汇总修订后，各自复核实际 R2。完整参考分析、固定输入和原始报告留在产品 Git 外；这里记录独立表达的产品问题、处置与证据范围。

| reviewer | 独立任务 | 视角 | R1 结论 |
| --- | --- | --- | --- |
| A | `goal_architecture_review` | 产品价值、复杂度、职责/依赖、Goal/Work/Method | 需修订，2 项阻断、2 项实施跟进 |
| B | `goal_runtime_review` | 并发、权限、派发、取消/收尾、恢复、用量 | 需修订，3 项阻断、3 项实施跟进 |
| C | `goal_delivery_review` | API/UX、headless、分支/迁移、切片与验证 | 需修订，3 项阻断、2 项实施跟进 |

评审覆盖 outcomes/complexity、ownership/contracts、runtime/failure、trust/authority、evolution/operation、verification/scope。物理场景限本地嵌入式、单次 CLI 和现有 hosted 宿主，不宣称覆盖跨设备、集群或无人值守部署。场景来源为用户需求和当前源码；没有额外 stakeholder 输入，相关产品取舍仍是方案建议。

## 固定输入与复核规则

| 修订 | SHA256 | 含义 |
| --- | --- | --- |
| R1 | `00341681b9199fb24ce272f8bff96aa4e7218c0929f46a8d9f9e62be4a8aef56` | 三位 reviewer 最初独立检查的相同输入 |
| R2 | `5b6d99ebe5972c09050c8790d02a79c3d2b95226aff45905b6a169b580355113` | 设计者综合 R1 意见后的实际复核输入 |
| R3 | `7a29c08e1c080e8fa386d18af71c96c77c704a5ab290fea1c216cea7cf37a98e` | 三路最终复核的方案；产品交付正文与此 hash 完全相同 |

评审 hash 固定输入正文；R3 后没有再改方案正文。若存在语义修改则重新固定输入并复核受影响合同。文档修订只关闭设计歧义，不能用它证明运行行为。

## R1 Findings 与修订

同一问题由多位 reviewer 独立提出时保留各自 ID，避免将重复意见包装成额外缺陷。15 条评审记录中，8 条阻断意见对应 5 类核心合同问题：完成时序、分支终态/副本、派发许可、用户执行归属、headless 寿命。

| Finding / 严重性 | 设计场景与影响 | 阻断 R1? | R2 修改 / Owner | 关闭条件与实施证据 |
| --- | --- | --- | --- | --- |
| A1 / High | complete 工具属于尚未 settle 的调用，立即校验永远失败，等待自己会死锁 | 是 | §9：持久 completion candidate → 工具返回 → 原 owner graceful end → settled → CAS；Coding/execution | 正常路径及取消/后代失败/崩溃组合可由文本走查；V05/V08 尚待实现 |
| A2 / Medium | complete 不可逆与换 branch 无条件 paused 冲突 | 是 | §6/6.1：未终结按状态停止续跑，complete 保留历史终态，重验新建 ID；Coding | active/limited/complete/cleared 分支矩阵；V02/V08/V12 待实现 |
| A3 / Medium | 内层空闲不等于外层 hosted 已收尾；多实例订阅可能重复启动 | 否 | §4/7：单 Session/generation 单服务，外层 guard 不被绕过，P0 定位共同 owner；Coding/Harness | 实施前置：入口调用链、唯一 owner、卸载重载；V03/V04/V10 |
| A4 / Medium | Method enactment 若只注入文字会另造 plan/run 权威 | 否 | §4/V11：原 Coding binding + HarnessWork 拥有冻结 plan/run/step；Goal 只引用；Coding/Method/HarnessWork | Method-backed 场景及历史 Work 不变；V11 待实现 |
| B01 / High | complete 与 whole-call settle 组合自等待 | 是 | 同 A1；候选为 singleton batch，后续不再采样，固定本地呈现 | 复核候选不先宣称 complete；V05/V08 待实现 |
| B02 / High | 进入审批前查 fence，迟到 allow/commit 后仍可能产生新效果 | 是 | §7.1：approval/commit await 后 final admission；登记为在途与 fence 可排序；Harness execution/model/tool | 只承诺 fence 后无新 admission，已准入效果仍收尾；V04/V07 待实现 |
| B03 / High | 用户 turn 受 Goal 计费，却同时被描述为暂停后继续，预算许可矛盾 | 是 | §5：全部 Goal-bound 用户/自动执行同样 fence/cancel/settle；独立 side question 不混入；Coding | 用户 turn→pause→下一派发、旧回执和预算竞争；V04/V07 待实现 |
| B04 / Medium | 输入被消费而未创建 execution，Busy 后可能永无唤醒 | 否 | §7：admission_epoch 覆盖全部输入/维护退出，订阅后复查，P0 列 owner；Harness | consumed command/preflight、输入失败、maintenance 退出；V03 |
| B05 / Medium | Resource/Skill evidence 不等于原始用户 Goal 授权 | 否 | §5.2：独立 GoalIntent，原始输入在 transform 前锚定，凭证缺失不开放模型 create；Coding/input | transform/application/历史/重放不可铸造凭证；V08 |
| B06 / Medium | 完全没有 usage callback 的 attempt 可能被漏作零费用 | 否 | §8：expected-attempt 集合与 dispatch/outcome/usage debt；不能用 latest 猜 attempt；Coding/usage | 无 callback、usage 写失败、旧 attempt 迟到；V06 |
| C01 / High | complete 的成功路径与宿主实际 run/settle 顺序不相容 | 是 | 同 A1/B01；限定候选 receipt、预算竞争、后代及恢复行为 | 工具正常返回后 settled 才 complete；V05/V08 待实现 |
| C02 / High | 全 Session 控制 replay 沿 branch-only export/fork 丢 tombstone，或复活旧目标；complete branch 规则冲突 | 是 | §6.1：副本默认无 Goal；显式 copy-goal 新 paused ID；export 剥离 namespace、import 隔离；Coding/compatibility | clear 位于未导出路径、fork 到 create 前、JSONL/bundle/旧版往返；V02/V12 |
| C03 / Medium | headless 第一轮结束后可能 dispose，或等待无退出合同 | 是 | §5.1：CLI create/resume 等待目标停点、确定退出码；SDK/hosted receipt 与宿主寿命分开；Coding CLI/hosted | CLI 两轮、Ctrl-C、非交互 approval、unsupported；V01/V10 |
| C04 / Medium | Goal 预算算法与共享 ledger 不同，可能出现两份“事实” | 否 | §8：同一 durable raw usage，Goal 只作派生 budget quality，ledger 不变；Coding/transcript | total-only、组件大于 total、终结冲突、旧样本；V06 |
| C05 / Medium | P2 audit complete 依赖 P3 才有的 audit/progress，工具协议缺口 | 否 | §5.2/P1–P3：先最小 schema，P2 真实最小闭环，P3 扩覆盖；P3 前拒绝有限预算；Coding | 无 fake audit 冒充；progress producer、要求锚点/版本和 receipt；V08/V09 |

表中“待实现”是后续功能交付的明确工作，并非本次设计评审失败的别名；本次不将这些尚未接受为 Target 的候选合同计作既定实现债务。

## R2 / R3 独立复核

| reviewer | 实际 R2 复核 | R3 局部复核 | 最终结论 |
| --- | --- | --- | --- |
| A | A1–A4 设计关闭；新增 A5 Medium 窄阻断：不能把正常追加推进 cursor 当成用户导航 | 核对固定 R3 与 diff，确认 §6/9 和 V08 区分 navigation_epoch 与 source_cursor；A5 设计关闭 | 所审范围无剩余设计阻断，可作为进入实施的方案 |
| B | B01–B06 设计关闭；新增 B-R2-01 Medium 同类导航歧义；恢复停因 Low 建议 | 核对实际 R3，正常候选/工具结果/usage 链不自失效，input epoch 和证据新鲜度仍约束完成 | 所审范围无剩余设计阻断，可供实施；恢复主停因保留非阻断跟进 |
| C | C01–C05 设计关闭，无新增阻断；列导航、记录图、receipt 消费实施检查 | 确认导航歧义关闭，未放宽真实上下文变化的复核，未变合同沿用 R2 | 未发现新增阻断，可作为可供实施方案参与综合决定 |

R2 新问题来自组合走查：candidate 和工具结果持久化自身也推进 transcript leaf。若把这种自然追加等同历史切换，正常完成就会自行暂停。R3 只在用户显式历史导航时推进 navigation_epoch，source_cursor 保留为证据锚点；candidate、工具结果、usage、本地总结和只读审计的预期追加不改变导航 epoch。用户新输入、控制变更、证据变化仍独立触发复核。三路均核对实际文本及 R2→R3 diff，未以修订意图替代证据。

正常完成路径的综合设计分析现为：singleton 工具保存候选并返回 pending → 工具结果正常追加 → 原 owner graceful end → 全部 execution/后代/usage/事件 settle → 唯一 GoalService 核对控制/input/navigation 版本、预算及证据 → CAS complete。审批等待与 pause 交错则在最终 admission 核验 fence；已准入效果仍属于在途责任。分支副本默认隔离 Goal authority，CLI 持有 Session 跨轮等待。这些合同可以同时成立，不新增第二个执行 runtime。

### 明确保留的非阻断实施事项

| 事项 | Owner / 切片 | 关闭证据 |
| --- | --- | --- |
| hosted 外层与 Harness 内层的实际共同准入、settle、dispatch ticket、导航/input epoch、无 execution 的唤醒 | Coding/Harness / P0–P2 | 真实调用链、唯一 owner；V03/V04/V08/V10，证明没有丢失唤醒和重复执行 |
| GoalIntent 原始用户授权、expected-attempt 和全部 provider 路径覆盖 | Coding/input/usage / P0–P3 | 无授权来源不能 mutation；无 callback/写失败保留 debt；V06/V07/V08 |
| Method-backed Goal 不改写既有 Work 权威 | Coding/Method/HarnessWork / P0–P4 | V11 的冻结 binding、暂停及历史终态证据 |
| namespace 剥离/隔离后记录图仍有效，正常历史可读 | Coding compatibility / P0/P4 | 转换 hook 和合法 parent/ref；JSONL/bundle/旧版往返真实样本，V02/V12 |
| 客户端消费 pending/final receipt，不等待不存在的下一次模型 final | Coding UI/CLI/hosted / P2/P4 | V08/V10 的完成、退出与断线重连 |
| 恢复同时存在 budget/usage limit 和 cleanup debt 时保留主停因，叠加 recovery_required | Coding recovery / P0/P3 | V05/V07 的 limited→crash→restore；不能靠普通 resume 隐藏限额 |

最后一项是 B-R2-02 Low 建议；本次明确交给实施合同细化，不将它写成已实现或已测试。若 P0 证明实际 owner 无法兑现设计，应修订受影响合同并复评，不能用产品自建队列绕过原 owner。

## 综合结论与后续责任

协调 agent 已读取三路 R1、R2、R3 原始报告并核对方案修订。最终 R3 完成三视角独立评审与受影响合同复核，所审范围内无剩余设计阻断；作为本次“调研 + 实施方案 + 独立评审”的交付已经就绪。负责协调的 agent 在用户授权范围内记录该结论，没有替用户做接受声明。方案仍为 proposed、implementation not-implemented，P0 的共同父级 ARD 和 Target 接受另行记录，未被本评审自动替代。实施仍须 P0 验证实际 owner/hook、P1–P4 打通完整链路并执行 G01–G10 / V01–V12 验收。自然语言完成判定的语义真实性、provider 用量缺失和已在途外部效果的可确认性保留为明确限制。

本次没有修改 PR gate、CI workflow、required checks 或触发器。内部方案审阅不要求额外用户确认；本记录不制造用户接受声明，也不批准超出任务范围的发布或外部动作。

## 本次交付验证

已执行既有 `scripts/ci/check_docs.py`，通过 9 项纯静态文档不变量，并对本次方案、评审记录和 plans 索引执行 repository link 检查。方案正文 SHA256 与三位 reviewer 的 R3 输入一致。该检查不执行 pytest，不导入产品运行时，不覆盖 V01–V12 的未来功能验收。最终提交另执行 `git diff --check`；详细参考研究和原始评审未写入产品 Git。
