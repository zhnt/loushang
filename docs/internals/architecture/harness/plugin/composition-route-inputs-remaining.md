# D2 剩余范围盘点

## 范围与结论

- Authority: observed — 固定源码事实与候选处置，不增加架构权威。
- Design status: 本轮 D2 收敛范围已结案；B1 R1.1 已经用户接受，保留项按下述结案记录处置。
- Implementation status: 本轮限定切片已交付；[第一切片](composition-route-inputs.md)为 PR #869，B1 为 PR #871；其余项明确保留，不计为待实施切片。
- 原盘点固定基线：本地 main `2490c9d54f06e9f1d88b23a050dce8b3cf185f83`，2026-11-05；当前结案切点见文末，不改写原行号。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。按既有 scope 的证据盘点裁剪工作，复用 R2 环境图、[职责图](../current-owner-map.md)和[审计 D2](convergence-audit.md)，不新增组件或 ARD。

本盘点选出的后续范围是 **B1：B 同步 bootstrap 的配置值构造局部复用**，现已按接受的专项在本地实施。路线选择已有唯一 owner，三个准备入口已有共同编译链；整合 seed builder 或统一 owner 寿命没有足够依据。B1 属于维护性候选，不是已证实的功能缺口或完成 D2 的强制条件。

后续 [B1 专项设计](bootstrap-capability-config.md) R1.1 已经用户接受并实施：只在原 B 父函数内局部复用，保持求值顺序和副作用归属；评审、实施与验证状态以该专项及其评审记录为准，接受不由本盘点推导。

## 剩余项—源码证据—处置建议

路径与行号均固定于上述基线；AST 相同只证明相应表达式，不能证明完整路径或执行时机等价。

| 项 | 源码证据 | 结论与建议 |
| --- | --- | --- |
| R1 workspace 路线选择与 direct/app 包装 | [原 selector](../../../../../src/loushang/coding/package_product_runtime.py#L453) 453–593 在锁内选择、初始化/恢复及留存 owner；[direct 包装](../../../../../src/loushang/coding/bootstrap.py#L2832) 2832–2857 与 app 包装 3253–3297 均调用原 selector | **保留**。direct 转交 owner，app 借用 owner；显式 factory 在 2996–3005 绕过自动选择。未发现第二套存储选择器，不再建立 RouteResult。 |
| R2 bootstrap 的 factory/None 条件 | [bootstrap](../../../../../src/loushang/coding/bootstrap.py#L735) 735–840 处理 minimal、Worker、互斥和旧设置；982–1018 决定 materializer/lifecycle；1315–1390 处理内部 assembly/Catalog | **保留原分支**。这些是不同装配条件与失败时点；None 也可配合内部初始 assembly/minimal，不足以表示统一 legacy 路线。 |
| R3 两 composer 的共同准备链 | [兼容入口](../../../../../src/loushang/coding/_capability_plugin_composition.py#L1414) 1414–1469；[B combined](../../../../../src/loushang/coding/_product_capability_plugin_composition.py#L274) 274–335、B capability-only 415–468 均使用 `_finalize_selection`、原 completion、`_assembly_request` 和 Harness `prepare_product_plugin_composition` | **已有共享**。原 `_assembly_request` 1912–1964 含 Coding Definitions、Provider 选择和 roots；再包装进 Harness 不能增加通用职责。 |
| R4 三种 seed builder | [兼容 builder](../../../../../src/loushang/coding/_capability_plugin_composition.py#L1762) 1762–1909 合并已有 seed，取管理 lease 身份或合成实例，并为新增项构造 `host-equivalent-local` trust；[B capability-only](../../../../../src/loushang/coding/_product_capability_plugin_composition.py#L503) 503–567 使用选中 Store 快照；B combined 570–724 还保留 base contribution/config 与外部数据 owner/trust | **保留三个策略适配**。它们产生同一 PlanSeed 类型，但身份、信任、合并选择不同；共同的数据类型和排序形式不能证明整个 builder 等价。 |
| **B1 同步 bootstrap 配置构造** | [bootstrap](../../../../../src/loushang/coding/bootstrap.py#L1259) 的 LSP constructor 调用在 1266–1270、1558–1562、1749–1753 AST 完全相同；Arch constructor 在 1566–1579 与 1757–1770 两处 B 分支 AST 完全相同，兼容分支 1274–1281 的私有根策略不同 | **后续已按 B1 专项实施**：收敛两个 B 分支的配置值构造，原临时状态、准入及清理 owner 保持；兼容分支只复用已证实等价的叶子操作。留在原 Coding 适配层，不新建 Harness 配置组件。 |
| R5 重复配置 entry 表达式 | 三 builder 的 `PluginEffectiveConfigurationEntry(...)` 分别在[兼容路径](../../../../../src/loushang/coding/_capability_plugin_composition.py#L1859) 1859–1867、[B 路径](../../../../../src/loushang/coding/_product_capability_plugin_composition.py#L544) 544–552、695–703；这三个 constructor 表达式 AST 相同 | **低优先，先保留局部**。外围的包筛选、base entries 合并与排序范围不同；单独提取很短的 constructor 还需传 Coding 配置转换。没有扩成通用 plan builder 的依据。 |
| R6 两个 B revision recheck | [B composer](../../../../../src/loushang/coding/_product_capability_plugin_composition.py#L320) 320–322 与 455–457 的局部函数 AST 相同，均在原 preparation 的 `selection_recheck` 中使用 | **先保留**。只是原 runtime 的逐包 verify，提取不能减少核验次数；不要顺带缓存结果或移动 current check。 |
| R7 两种失败清理 | [兼容入口](../../../../../src/loushang/coding/_capability_plugin_composition.py#L1466) 1466–1481 保留 leases/callbacks 和失败 custodian；[B 入口](../../../../../src/loushang/coding/_product_capability_plugin_composition.py#L358) 358–361、471–473 调原 runtime.close。bootstrap 两 B 分支也分别保留原直接 cleanup 和 `run_cleanup_steps` | **保留边界**。资源持有与失败凭据不同；将清理合成一个总入口会改变原异常、重试或依赖释放合同。不是配置值复用的附带内容。 |
| R8 deferred LSP 与同步输入 | [bootstrap](../../../../../src/loushang/coding/bootstrap.py#L2450) 2450–2556 到激活时才 discovery、构造 config、捕获/核对当前 Store selection，随后调用原 composer；2469 的 definitions 输入与前三个同步 constructor 不同 | **保留惰性路径**。不同唤醒时机和当前性证据不能因同一配置类型而合并成 eager snapshot；本次 B1 候选不涉及它。 |

## B1 专项设计的输入要求（盘点时记录）

两处 B 配置调用相同，仍不等于其整段准备过程是纯函数：

1. 保留“已由原分支选定的能力 → 配置值”的职责；desired enabled/disabled、base/external-data 选择及 snapshot 捕获仍由原 owner 决定。
2. 保留原 LSP → Arch 求值顺序，只有选中 Arch 时才准备它的私有根。`prepare_coding_product_arch_private_data_root` [109–173 行](../../../../../src/loushang/coding/package_installation_private_data.py#L109) 会检查安装/Session 身份、捕获当前选择并创建目录；Windows 还绑定目录身份、设置 ACL 后重新捕获，不是纯 Path 拼接。
3. 临时目录和 cleanup 凭据仍由原调用分支持有；不把目录准备提前到 LSP 配置校验之前，不改变失败前缀或关闭责任。
4. 选一个原 bootstrap 内的私有函数或原 Coding 适配模块即可；不提升为公共 facade、配置注册表或 Harness policy engine。若必须增加一组新回调、方案开关或跨调用缓存才能复用，应重新评估收益。
5. 后续验收先复用现有 bootstrap、hosted/Store 和 LSP/Arch 配置用例，再仅补必要的构造顺序、路径准备次数、字段与异常轨迹差分；不重跑已交付 Goal 试验，不扩大 PR gate。具体接口与验收包属于后续专项设计，本轮不预定。

这段代码认识 `coding.lsp.default`、`coding.arch.default`、两种 Coding 配置类型和 Arch 的安装私有根策略，是 Product 输入适配。底层配置类型、原装配协议、Store/目录与平台机制已各有 owner；其重复调用不产生新的 Harness 共用机制需求。若后续出现另一 Product 的真实共同输入，再按 owner map 重新判断机制下沉。

## 盘点阶段的复核与范围限制（历史）

本轮由实施者按三个视角静态自查，不称三位独立 agent 评审，也不替代重要架构工作件的用户评审：

| 视角 | 核对结果 | 尚未证明 |
| --- | --- | --- |
| 职责与复用 | 原 shared pipeline 与明确重复叶子均已定位；B1 归 Product 输入适配，未增 shared owner | B1 的具体函数边界和复杂度收益需专项设计 |
| 运行与失败 | direct/app、临时状态、Store witness、Arch 目录和 deferred LSP 具有不同副作用与寿命 | 未运行并发、故障、native 或构造差分，不能声称 B1 等价实现已可直接落地 |
| 数据与兼容 | 三 builder 的实例/信任来源及 base/external-data 合并差异明确；同一 entry 表达式不等于同一输入集合 | 未证明这些候选存在性能瓶颈，也没有可删除 legacy 路线的存量证据 |

树外 `architecture-analysis/plugin-harness-audit-20261104/d2-remaining-20261105/` 保存 13 份源码/测试的 SHA、AST 范围、相同 constructor/recheck 的指纹及静态探针。现有 `test_bootstrap.py` 的 minimal/fenced/on-demand 场景、`test_resource_catalog_shadow.py` 的单次编译及 base 缺席场景、`test_plc9b_adversarial.py` 中的 B composer 调用为后续定位依据；本轮仅查阅，不将其视为已执行或覆盖全部 B1 分支。

本轮仅修改文档，不修改实现、测试、CI、格式或权限，不调用模型或运行 pytest。**盘点时 D2 为第一切片已交付、后续候选待决**：路线权威和共同编译链已确认复用；B1 可单独设计，也可明确暂缓后结束本轮 D2 收敛。没有把候选数量变成必须开发的工作量或完成比例。

B1 实施时状态（历史）：B1 已完成用户接受、局部实现、定向验证与三视角代码评审，详见[专项记录](bootstrap-capability-config-review.md#实施与代码评审)。上述盘点阶段未执行测试的限制是历史记录；其余保留项没有被变更为必做任务，也未因 B1 实施而将 D2 整体标为完成。


## 本轮范围结案（2026-11-05）

用户接受“先收尾 D2，再推进 E1”的建议后，本轮 D2 收敛按以下范围结案。代码基线为 main `9f8c851b5c7cb4a8fce51c140e85bbc135454286`；源码与上表原盘点切点相比，仅 B1 提取及既有联合激活测试前提修正影响本轮范围。

| 项 | 处置与结案依据 | 重新开启条件 |
| --- | --- | --- |
| 共同 owner 输入准备 | PR #869 已交付；同一 Harness 准备机制承接 Product 窄政策 | 出现可证明的重复协调或合同缺口 |
| B1 配置构造 | PR #871 已交付；原两个位置复用一个局部函数；三视角代码评审无未关闭发现 | 原配置语义或真实复用需求变化 |
| R1/R2 路线与 factory 条件、R3 共同准备链 | 已有唯一 selector/共享机制；保留既有选择、绑定和失败边界 | 证实另一条竞争权威或同语义重复机制 |
| R4 三种 seed 策略、R7 清理边界、R8 deferred LSP | 明确保留；身份/信任、资源凭据或当前性时点有差异 | 原职责发生变化且能给出新的等价与兼容证据 |
| R5 配置 entry、R6 revision recheck 短表达式 | 本轮不抽取；没有足够维护收益，不设为积压开发承诺 | 出现实际规则漂移或新增真实共同消费者 |

这表示本轮选定问题已完成处置，不表示所有 bootstrap 分支已合并、legacy 可删除、全平台均已验证或整体 Plugin 架构审计已完成。沿用已有差分、聚焦测试与 PR 证据，不为结案重跑 Goal 或模块回归。PR #871 的既有检查结果为 12 success / 12 skipped；跳过不等于取得 Windows native 证据。

E1 是审计中独立的命名与兼容入口候选，详见[专项设计](catalog-adapter-module.md)；它不重新打开 seed/清理/路线政策，也不承担 M1 的 Windows native 验证缺口。
