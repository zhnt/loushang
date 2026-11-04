# Harness 可选 Goal 组件三视角独立评审

## 状态与固定输入

- Authority: descriptive — independent design review evidence
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: Harness Session / Loushang architecture 协调 agent
- 日期：2026-10-17
- 对象：[Harness 可选 Goal 组件设计](2026-10-17-goal-component-design.md)
- 源码基线：`df4324d1ddb9db2b3b6666a00b55240353934d9d`
- 方法咨询：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，不声明远端同步或变更项目方法版本。

用户指定组件交付方向并要求三视角独立评审。三位 AI reviewer 使用分别创建的独立上下文、同一固定输入和只读源码；初评不读取其他 reviewer 报告。场景来自明确用户需求、当前架构和源码，不冒充真实 stakeholder 访谈。旧插件方案评审不能覆盖本次设计。

| 修订 | SHA256 | 状态 |
| --- | --- | --- |
| GC-R1 | `7c7ab612e295dd080eb532340b654eafd51131cfc54b5c8145d103b070703072` | 三路初评输入 |
| GC-R2 | `f0c90a3c130f022e3f90f179240c7053a94c2deb076550c27221302c15e73168` | 初评后综合修订的固定复核输入 |

| reviewer | 独立任务 | 范围 | 状态 |
| --- | --- | --- | --- |
| A | goal_component_arch | 归属/契约/中立性/复杂度 | 初评及 GC-R2 独立复核完成 |
| B | goal_component_runtime | 执行/权限/预算/完成/恢复/停止 | 初评及 GC-R2 独立复核完成 |
| C | goal_component_delivery | 装配/版本/入口/兼容/交付 | 初评及 GC-R2 独立复核完成 |

原始报告、固定快照和详细源码分析保存在产品 Git 外。G01–G13/V01–V18 是未来实施义务，本轮没有执行这些功能测试。物理范围为当前 Linux 本地可信内置实现和拟议 CLI/TUI/SDK/hosted 路线；静态走查不能证明其他平台、性能或工程日估算。

## 初评 findings、修订与复核

初评共 5 条意见，其中 A-GC-01 与 GC-C-01 是两个独立视角发现的同一只读合同缺口；分别为 Medium/High 阻断，合并根因但保留独立报告。B 的两条 P2 属非阻断澄清项，GC-C-02 是 Medium、首版开放入口前须关闭；不把这些意见夸大为已复现的运行故障。

| Finding | 初评依据与影响 | GC-R2 选定修改 | 实际复核 / 后续验证 |
| --- | --- | --- | --- |
| A-GC-01 Medium / 阻断 | disabled/构造失败且无缓存时，没有明确最后状态来源；宿主复制 reducer 会违背唯一语义归属 | §6.2 同一份纯 replay/projection，live runtime 与只读 host 共用；不构造行为实例、不写状态/订阅/执行；全 Session 已提交全序和同截点原 usage view | A 已确认设计关闭；V02/V16/V17 无缓存、失败、progress/usage、跨 branch clear/replace |
| GC-C-01 High / 阻断 | unavailable/unknown schema 读取承诺与事件 envelope/cache 无法衔接 | 同上；supported schema 返回精确 data-only view，unsupported/corrupt/unverified/read_unknown 不猜当前业务状态；宿主 debt/suspension 独立 overlay | C 已确认设计关闭；不是新增持久 read-envelope 或第二日志 |
| B-GC-01 P2 / 非阻断 | 完成候选不能拿 handler 最新 epoch 冒充模型实际审计过的输入，graceful end 可能先于队列消费 | §5.2/§9 assessed_input_watermark 由实际 Model Input 冻结；final ticket 拒绝未覆盖的 admitting/pending 输入；保留并优先处理 E+1 后重审 | B 已确认设计关闭；V08 注入模型冻结后、候选前的 steering/follow-up/mailbox/application 输入 |
| B-GC-02 P2 / 非阻断 | Current 回调只带 invocation/latest-attempt，UoW 又拒绝 outcome/terminal/非 active-path raw usage；只加 Goal 投影不够 | §8 原 usage owner 捕获 exact binding、原 writer append-only 补充事实/幂等 lookup、版本化原账 query；不改写旧 terminal，不建 Goal raw 账，不静默放宽旧校验 | B 已确认设计关闭；V06/V12 outcome/导航/跨 attempt/重复 terminal/写失败与旧版本保留 |
| GC-C-02 Medium / 非阻断方向 | 默认 false 但缺用户可执行选配入口，GoalCommand 是否隐式启用未定 | §4.5 启动级 --enable-goal/--disable-goal、默认 false、无新增持久设置；command 不隐式启用，SDK 显式构造，hosted server-only；禁用选择与 drain receipt 分开 | C 已确认设计关闭；V10/V14/V15 默认值、拒绝/只读、server/client 权限和重开恢复 |

综合修订同时澄清：关闭 slot 时从 selection Definition 集合排除；first_party binding 不进入 artifact host；Goal commands 由独立 owner contribution 提供，不改变 coding.base 固定 admitted identities，也不误把该 pack 当作 Session exact4 消费证据。ExtensionData 名字本身不授予权威，原 append owner 拟增加 reserved namespace gate，普通扩展/工具伪造同名 payload/receipt 拒绝，导入/fork 历史隔离。

这些修订解决合同表达，不能证明当前实现已经具备 projection、namespace gate、late usage 或 final ticket。

## GC-R2 组合复核

| reviewer | 实际检查及结论 | 剩余设计阻断 |
| --- | --- | --- |
| A | 固定 R2/产品同字节；纯投影/全序/同截点 usage/unknown、启动选择、namespace/命令 owner 组合；A-GC-01 关闭，无新增 material finding | 0 |
| B | 固定 R2/产品同字节；B-01/02 关闭，重走未消费输入、normal/supplement terminal 竞逐、fact version/ticket、禁用后的原 owner 收尾及只读；无新增 finding | 0 |
| C | 固定 R2/产品同字节；C-01/02 关闭，重走 unavailable+clear/replace/schema/import/选配/命令贡献/v4-v5 组合，无新增 material finding | 0 |

三路复核都只使用实际固定设计、自己的历史 findings 与只读源码，不读取彼此报告。协调 agent 已读取三份初评与三份复核全文。三路均核对 SHA256 `f0c90a3c130f022e3f90f179240c7053a94c2deb076550c27221302c15e73168`；产品方案保持与固定 GC-R2 同字节，未在复核后修改设计语义。

综合结论：**5 条意见均已在设计层关闭，GC-R2 所审范围无剩余设计阻断，可供进入 C0 合同与可行性工作。** 协调 agent 在用户授权内记录该内部评审结论；首版采用 Harness 可选组件、插件化由独立交付需求触发的方向与用户指定一致。方案具体新增接口仍 proposed，不将三路复核冒充用户对所有细节的接受、accepted Target 或功能实现证据。

## 保留的实施义务与决策触发

| Owner / 切片 | 待取得的证据 |
| --- | --- |
| Session/component / C0–C1 | 真实 first_party admission/selection/binding、单实例、partial publication、typed Consumer/live guard；disabled 无行为实例；不把现有 generation lease 当执行许可 |
| Session contracts / C0–C3 | 成套 v4/v5 Definition/Provider/Requirement/typed equality 选择与现有默认/第三方 Plugin 兼容；旧 v4 路线保留，未知 v4-only 不强扩范围 |
| Input/context/execution / C0–C2 | 外层/内层原 owner 共同 admission、所有忙状态进入退出通知、逐 sampling/retry/compaction 同源 Model Input、side-question、审计输入水位、late approval 后 final permit |
| Goal schema/transcript / C0–C2 | 单一纯 projection、全部 branch 全序及同 committed 截点、reserved gate 全入口/provenance stamp、fixed-record ticket 与原 writer 的排序/unknown lookup，不造第二 reducer/writer |
| Usage / C0–C2 | exact attempt/dispatch callback、outcome/导航后原 owner 补充事实、terminal 冲突/重复、同一原账查询和真实旧版本保留；未兑现不得声称有限预算首版完成 |
| Product/Session / C1–C3 | CLI 运行到目标停止、SDK/hosted lifetime 与权限、disable/self-drain/close 无自等待、fallback/unavailable 明示归属；重启恢复不重放未知效果 |
| Transcript/Product / C0–C3 | 所有公开 import/fork/export 入口的控制隔离与合法记录图，完整原始 Session/blob 备份集合、真实旧版本样本、schema/回退失败保留原数据 |
| 中立应用/Coding / C1–C3 | 同一发布构建经实际 Session owner 组装运行完整 G/V 纵切，不能用直接 new GoalRuntime 或静态检查冒充功能交付 |

12–18 个有效工程日是 C0 前的规划区间，未由本次评审验证。原 usage、准入、schema 或 compatibility 工作扩大时重新估算并复评，不能删不变量以维持工期。

后续仅在独立发布/回退、不同实现选择、按制品安装/撤权/卸载等具体需求出现时重新评估 Plugin 交付；复用同一组件的第二产品不自动触发插件化。未来 arbitrary Python factory、热替换、第三方代码或独立 ABI 不在本轮无阻断结论范围内。

## 本次交付与验证边界

本次不修改实现、运行时、Plugin IR/loader、CI 或 PR gate，不安装插件、不调用模型、不发布远端。旧 Coding R3 和插件 GP-R2 及其评审保留原字节，plans 入口转向组件方案。具体新增接口仍 proposed/not-implemented，用户指定的组件交付方向不自动接受所有候选跨界合同。

已运行既有 `scripts/ci/check_docs.py`：9 项纯静态文档不变量与本次设计、评审及索引的链接检查通过；`git diff --check` 通过。GC-R2 与三路固定复核输入 hash 一致，旧四份 Goal 方案/评审保持原字节。本次没有运行 pytest、模型或 G/V 功能验收；检查通过只证明本次文档有效性。
