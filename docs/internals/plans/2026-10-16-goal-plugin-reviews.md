# Goal 插件三视角独立评审

## 状态与评审框架

- Authority: descriptive — independent design review evidence
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: Harness Session / Loushang architecture 协调 agent
- 日期：2026-10-16
- 对象：[Goal 插件设计与实施方案](2026-10-16-goal-plugin-design.md)
- 源码基线：`8f7ce44631ae62ce5335620e6ca93d12e651c132`
- 方法咨询：本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；没有改变项目采用版本或检查远端同步。

用户要求按插件形态重新设计并启动三视角评审。本次为独立 AI 源码/方案评审，没有真实 stakeholder 访谈，不代表实现运行、Target 接受、发布或新增 CI gate 批准。原 2026-10-15 R3 的评审不能覆盖新的归属和插件生命周期。

三位 reviewer 采用新建独立上下文，只获得同一固定输入、各自视角、治理约束及源码访问权；初评不读取其他 reviewer 的输出。设计者综合修订后，三位 reviewer 均重新核对实际 GP-R2 和受影响合同。详细源码分析、固定快照和原始报告保留在产品 Git 外。

| reviewer | 独立任务 | 视角 | 最终状态 |
| --- | --- | --- | --- |
| A | `goal_plugin_arch` | 归属/契约、中立性、完整插件、唯一 owner 与复杂度 | 初评及 GP-R2 独立复核完成 |
| B | `goal_plugin_runtime` | 执行、预算/权限、完成、取消、退役和恢复 | 初评及 GP-R2 独立复核完成 |
| C | `goal_plugin_delivery` | artifact/IR/Session 版本、装配、SDK、兼容与交付验证 | 初评及 GP-R2 独立复核完成 |

覆盖 outcomes/complexity、ownership/contracts、runtime/failure、trust/authority、evolution/operation、verification/scope。物理范围为可用 Linux 受信进程内插件、嵌入式/CLI/hosted 路径；其他平台、第三方 Worker/remote Goal 不据此声明已支持。场景来自用户需求、现有架构和源码，产品偏好仍为方案建议。

## 固定输入

| 修订 | SHA256 | 用途 |
| --- | --- | --- |
| GP-R1 | `95eda2953fb1c7f78f9fc167210e1cb307b6c1e9a62dded34b421c23cd387e7d` | 三路最初独立输入 |
| GP-R2 | `c3c97024401ee58f83dad088e1348290148e208a9b77e93d58db9bd8946de1e0` | 综合初评后实际复核输入 |

## Findings 与复核

三路初评均已完成并读取，共 11 条意见，其中 6 条 High 阻断；以下记录 GP-R2 的具体修改；三路已实际复核确认各自 findings 设计关闭。

| Finding | 阻断初稿 / 依据 | GP-R2 修改与 owner | 后续验证 |
| --- | --- | --- | --- |
| A-01 High | context 注入没有 producer/Session owner/commit/retire 接口，普通 turn、同轮采样、retry/compaction可能丢目标 | §4.2 GoalContextPort；插件提供数据/模板，Session逐请求组合并冻结同一 ModelInput；side_question明确排除；Harness/Plugin | V13/V18 实际输入与退役后资格 |
| A-02 Low | 默认 model assessment 写成 core 提供，与完整插件归属歧义 | §9 明确插件实现assessment；core仅中立引用/结构及原受管执行 | V18 artifact实际逻辑与调用归属 |
| B-GP1 High | control CAS 与输入/lease/usage及异步落盘没有共同排序 | §9 fixed-record final commit ticket，明确谁先admit、durable receipt前pending、unknown查询原owner；Session/transcript | V05/V08/V15 在校验后及write中注入input/revoke/limits |
| B-GP2 High | required disposer 与 revoke不再执行旧插件代码冲突 | §13.1 新host-only no-plugin-code quarantine分流，不伪造正常disposed/GC成功；Session/Plugin/execution | V15 disposer trap、自撤权、rollback/debt和新宿主恢复 |
| B-GP3 Medium | raw active+unavailable下普通prompt归属不明 | §5用effective authority；普通输入明确独立receipt，显式Goal推进拒绝；Session input/read view | V17普通prompt、显式推进与恢复归属 |
| B-GP4 Medium | Busy/stale后unresolved claim可能卡死或重复启动 | §7 claimed/started/released/settled与admission_unknown；精确observe_admission；Goal/execution | V03 consumed input→release→epoch exit→单次续跑，unknown只查原handle |
| B-GP5 Low | 恢复段一律paused与保留limited主停因冲突 | §7统一active转paused、其他停因保留，和§12/13一致；Goal recovery | V05/V07/V17 |
| C-GP-01 High | verified loader只支持单文件，自身模块import没有真实路径 | §4.1/4.3首版完整单文件artifact，factory/disposer同文件，exact ABI，无自身包/ambient实现；Plugin import/Session | V14/V18真实managed revision装载及import负例 |
| C-GP-02 High | 新Session版本不会被max4/exact4 Consumer自动接受 | §4.2明确v4原路/v5新路与兼容矩阵，成套迁移Requirement和typed equality，未知/旧Consumer明确拒绝；Session | V14冻结旧fixtures与真实旧版本 |
| C-GP-03 High | ImportRealm不能因新Session/dispose就装同namespace新digest | §13.2update安装与可用分离；冲突restart_required，旧Session pin，不清realm锁；新宿主验证后装载 | V16同/异依赖、旧Session活跃/退役、宿主重启、数据恢复 |
| C-GP-04 Medium | P2真实pause纵切依赖的finalpermit却列P3 | §10最小许可/context/drain/settle成为P2开放effects前置，P3扩覆盖 | V04 late approval+pause及P2进入条件 |

各项修订关闭设计歧义，不能代替实现或运行证据。协调 agent 已读取全部初评与复核原始报告，以下结论来自固定 GP-R2 实际文本复核。

## GP-R2 独立复核与综合结论

| reviewer | 实际核对 | 结论 |
| --- | --- | --- |
| A | A-01/A-02、context producer→Session组合→真实Model Input、side_question、retire；并核查新装配/提交边界 | 两项设计关闭，本视角无剩余 material blocker |
| B | B-GP1～5，final ticket 两种顺序/unknown、no-plugin-code quarantine、缺插件归属、claim、主停因 | 五项设计关闭，本视角无剩余设计阻断 |
| C | C-GP-01～04，verified单文件、v4/v5矩阵与equality、ImportRealm重启、P2安全前置；检查install→use→update组合 | 四项设计关闭，本视角无剩余设计阻断 |

三路都核对 SHA256 `c3c97024401ee58f83dad088e1348290148e208a9b77e93d58db9bd8946de1e0`；产品交付正文保持与固定 GP-R2 一致，未在复核后修改设计语义。三路初评采用新建独立上下文，复核只读自己历史意见、实际方案与源码，没有读取其他 reviewer 报告。

综合设计路径为：原 Plugin 管理验证/选择真实 artifact → Session v5 的单个 goal.runtime 组件经原 Component Host 装配 → live lease与Catalog barrier开放 → 插件提供逐请求context、续跑、预算/审计 → 原 execution owner执行和收尾 → Session fixed-record ticket 排序后持久complete。停用合作drain，安全撤权走host-only隔离；更新遇原进程digest冲突须新宿主，不能热换或伪造新realm隔离。

本次重新设计、三路独立初评与修订复核已完成。协调 agent 在用户授权内记录“GP-R2 所审范围无剩余设计阻断，可供进入 P0 合同/可行性工作”，未制造用户接受声明。方案仍 proposed/not-implemented，具体跨界 ARD、Target 接受与实现验收分别记录，不由本评审自动替代。

## 必须保留的实施约束与证据

| Owner / 切片 | 待取得证据与边界 |
| --- | --- |
| Harness Session/Agent integration / P0–P2 | context内容形成位置、真实transport/Model Input同源、普通/同轮/retry/compaction/side_question归属；Work多prompt路径不能把单turn idle当整个execution settled |
| Session/execution/transcript / P0–P3 | 原准入/operation owner实现final dispatch与commit ticket、lease/input/navigation/budget共同排序，unknown固定record lookup，不建第二writer/队列；V03/V05/V08/V15 |
| Plugin/Component Host / P0–P3 | 新tuple/feature typedcodec、exact ABI exports实际接线、完整单文件从managedrevision加载；no-plugin-code quarantine与原activation/Instance/GC journals相符，不伪造disposer成功 |
| Session contract/Consumers / P0–P1 | 全部实际v5消费者、typed requirement equality和Provider metadata成套升级；旧v4路线/旧opaque Plugin不承诺直接可用Goal |
| Plugin/host / P3–P4 | 同namespace新digest/依赖冲突、polluted realm给restart_required；关Session或新建realm对象不能清进程事实；新宿主在旧writer释放后恢复 |
| Goal Plugin/recovery / P3 | rawactive+unavailable普通prompt与显式Goal推进分别验证；准确attempt的迟到费用、有限预算unknown、limited/blocked主停因及recovery/debt保持 |
| Neutral应用/Coding/UI/compatibility / P2–P4 | 真正无Coding的受管artifact纵切和同revision Coding使用，package/selection/generation/ModelInput/settle/audit关联；真实CLI/SDK两轮、namespace记录图、旧版本往返 |

18–28 工程日只是待 P0 校准的规划区间；首版完整交付仍为 P0–P4。Linux受信in-process证据不能外推未知平台、热升级、第三方Worker或恶意Python隔离。宿主窄ports/导入约束不构成同进程代码的安全隔离。

若未来重开多模块importer、同宿主双revision、v4/v5策略或热替换，需重评受影响合同；当前无阻断结论不覆盖这些扩展。新增focused验证不等于新增required PR gate，本次未改workflow、trigger、matrix或merge失败条件。

## 本次交付边界

实现计划中的 G01–G13 / V01–V18 为未来验收要求，不是已执行的测试。本次仅重新设计、独立评审、必要修订与文档验证。旧 R3 方案与评审保持原字节，以保留其固定输入证据；plans 入口切换到新方案。

## 本次文档验证

已运行既有 `scripts/ci/check_docs.py`：9 项纯静态文档不变量及本次方案、评审、索引的 repository links 检查通过。GP-R2 正文与三路固定复核输入 SHA256 一致，旧 R3 及其评审保持原字节。最终提交执行 `git diff --check`。本次没有运行插件安装/模型/故障注入、pytest 或功能验收；G/V 矩阵仍是未来实施要求。
