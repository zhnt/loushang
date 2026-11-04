# D1 管理账本装配：三视角设计与代码评审

## 对象与方法

- 日期：2026-11-04；对象：[首切片设计](management-ledger-assembly.md) R1 → R2。
- 设计阶段授权：源码盘点、专项设计、三视角评审；随后用户以“请开始实现和开发”授权按 R2 实施。
- 基线：main `00d9424826b349241341168e30a864a63bb38f11`。设计阶段产品源码、测试、工作流与门禁未修改；随后实施变化另列于下文。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核验方法远端。
- R1 SHA256：`6ddc540367786e4bff53ef44af3b2866b347e5fdcb5da01991fb9aed0b1d4100`。
- R2 SHA256：`92d554403b8c183bd521e6b73b0ff4a6a6e538371bf98cf73ec28e2dd6071b1e`。

三位 xhigh reviewer 以空上下文独立读取规则、方法、源码和合同，各自形成初评，不阅读其他报告、不修改产品或设计、不运行 pytest/native/异步。R2 只由原 reviewer 按变化路径复核，不称为又一轮全新隔离审核。用户要求来自审计 D1 及其后本轮确认，未把 AI 角色模拟当作新的 stakeholder 确认。

评审问题：能否用两段 Harness 内部构造复用现有对象图，保留中间兼容/恢复屏障、Product 政策、只读与租约边界，并正确维护既有精确库存。部署只检查原进程及 Product namespace，不涉及新增部署节点或网络协议。

## 初评与修订

| 视角 / reviewer | R1 结论 | 证据与处置 | R2 状态 |
| --- | --- | --- | --- |
| 职责与复用 / ledger_ownership | 无阻断、无非阻断技术发现 | 现有 application ports 不构造账本，Service 默认 retirement 路径不能代替原显式路径，fenced GC 装配不是等价候选；两个引用组不拥有状态、租约或恢复 | R2 定向复核通过，无新增问题 |
| 运行与失败 / ledger_runtime | 无阻断、无实质非阻断发现 | compat→recover→coordinator→security/instance/package 顺序可保持；hold/prepare 平台条件、BaseException owned/borrowed 释放、strict policy 与只读边界吻合源码 | R2 定向复核通过，无新增阻断 |
| 数据、兼容、库存与验证 / ledger_data | 无技术阻断，1 个非阻断事实勘误 | D-DATA-01：application builder 范围应为 1117–1212，R2 已改；构造库存 7→6，其他 5 个位置与两个 mutation 调用保留 | R2 确认勘误关闭，无未关闭发现 |

主执行者 AST 自查同样发现上述行号勘误，不重复计为第二个问题。综合修订还澄清图中准备按原模式/平台选择，并明确后段直接使用原 management.operation_journal_path；这是原 service 已有属性，不新增路径推导或 authority。

完整报告、冻结设计、源码范围和 SHA 在产品树外 `architecture-analysis/plugin-harness-audit-20261104/d1-ledger-assembly/`：`review-ownership.md`、`review-runtime.md`、`review-data.md`、`source-evidence.json`。产品内保留本索引及独立表达的决定，不复制方法文本。

## 综合决定与实现后条件

建议的首切片只共享共同构造关系：一个内部 assembly 模块、两个函数及两个短期引用组。Coding 原入口保留 layout/版本/平台政策、原 startup 租约、prepare、compatibility、recover 的发起点和返回类型。fenced B、Continuity 特定政策、owner evidence、退役交接及 D2 路线选择不随之搬迁。

实现后应以实际参数/对象身份/原失败顺序证明委托等价，尤其是 strict policy、缺 namespace/锁无创建、compat 拒绝先于恢复/后段、原 security 覆盖、同图 GC gate 与仅释放本次取得的租约。引用组不证明 ready；strict load policy 不是命令授权；部分恢复不作事务回滚。

原精确库存只等价迁移两个直接构造点为一个共同位置，不改 scanner、不扩大允许目录、不删除 mutation 断言或引入新 gate。额外失败轨迹在树外验收，不恢复暂停路线；本轮查阅现有测试不等于运行通过，更不代表全平台或整项 D1 已完成。

## 设计阶段结论与用户接受

R1 独立初评无技术阻断；事实勘误在 R2 修正并由原数据 reviewer 确认关闭。三位原 reviewer 对同一固定 R2 完成定向复核，均无新增实质问题。

9 项静态文档断言、三份变更文档的仓库相对链接及 `git diff --check` 通过；冻结 R2 与基线源码 SHA 核对一致。未运行产品测试、原生平台或性能实验，未修改产品源码、测试、工作流或门禁。

上述为冻结 R2 的设计阶段结果，当时保持 proposed/draft、not-started 并提交用户评审。用户随后授权实施；当前设计 accepted、首切片 locally-implemented。冻结 R2 指纹用于追溯当时受审内容，不表示实施状态更新后的文档仍具有相同指纹，也不宣告整项 D1 完成。

## 实际实现的三视角代码评审

原三位 xhigh reviewer 分别重新审查实际实现，未读取其他代码评审报告，未修改产品，未运行产品测试。此为设计后针对代码的独立审查，不把原设计通过直接视作代码通过。受审分支 `design/plugin-ledger-assembly`，HEAD 仍为上述基线，审查对象为本地未提交实现。

| 固定输入 | SHA256 |
| --- | --- |
| `src/loushang/harness/plugin_management/assembly.py` | `5c41cb4a0b98870391f382a36c06ccaa34e30cec174b55f28dc238e50f648060` |
| `src/loushang/coding/_plugin_lifecycle.py` | `a0686e4bba99fc4f200421fb8f2d146eaae6b12f37a8bb168d090bbdb5ce4520` |
| `tests/architecture/test_plugin_lifecycle_plc9_baseline.py` | `7194d701cdf1d0c9baad967a36a25a170d9ebebf96643ff1f3f89f6738e5f11e` |

| 视角 | 结论与关键证据 | 树外报告及 SHA256 |
| --- | --- | --- |
| 职责与复用 / ledger_ownership | 无实质性发现；共同构造归 Harness，引用组不新增 owner，Product/Continuity/fenced 职责保持 | `code-ownership.md`；`819b51f32b808a6be91a6542aeb3c0bff1e56afa1f75f5f02a658da9e1d7c17f` |
| 运行与失败 / ledger_runtime | 无实质性发现；原 constructor、compat/recover/coordinator 与 version 顺序、strict policy、owned/borrowed lease 边界保持 | `code-runtime.md`；`733a2979164a6fb553489513e8e564a9bcb615362a3c462f5acc815f83f76db9` |
| 数据、兼容与库存 / ledger_data | 无实质性发现；实际构造位置为 6 个，另 5 点及 2 mutation 保持；反向迁移位置字面量后整份库存测试 AST 与基线相同 | `code-data.md`；`0fd3dbc7b1e655974511bcbe4594157e4b01222f92dd2568573d5c741ac0b11d` |

报告位于前述树外目录。源码、库存与评审输入的指纹一致；其他原 Harness 账本、Service、application、CLI、Continuity 与 fenced owner 均未改。

## 实施验证与关闭边界

| 验证 | 实际结果 |
| --- | --- |
| lifecycle、management CLI、enablement migration、Continuity、Harness application/service/instance/package 与 PLC9/PLC9A1 集中离线回归 | 首次 229 passed、5 skipped、1 failed，耗时 494.78 秒；该失败为下面的测试根环境问题 |
| 单独诊断与复核 Continuity 失败 | 树外诊断包装显示 `Coding continuity temporary path has a writable ancestor`；测试根位于组可写 `/home/dev/lsspace` 下。仅换私有 `/tmp` 根后原用例 1 passed，4.47 秒；未改产品、原断言或安全检查 |
| 树外基线/当前装配等价性 | 82 passed，2.72 秒；20 个正常/平台条件/security 覆盖场景，62 个分阶段失败及 lease 清理场景。参数表编写错误在收集阶段修正，随后完整运行，未弱化断言 |
| Ruff / mypy / 包依赖图 | Ruff 通过；两份实现 mypy 通过；`render_current_package_dependencies.py --check` 通过 |
| 静态与加载来源证据 | `implementation-proof.json` 记录两目标函数及库存 AST 比较；`loaded-source-proof.json` 确认产品导入来自 Harness lane，SHA 与受审输入相同。测试命令显式设该 lane 的 `PYTHONPATH`，避免 runner 提前加载 control lane |

原生离线场景在本机 Linux 运行。树外平台条件模拟不证明 Windows/macOS 原生行为；代码审查也不代替并发、断电、性能或全仓回归。`make plan-checks` 另列出广泛 Coding/Harness 路线，本轮按变更边界只运行上述受影响范围，未宣称整个计划全绿。暂停路线和既有 PR gate 未恢复或扩张。

实施者将首切片本地实现与受影响验证关闭，三视角代码审查无未关闭问题。上述验收发生于提交前，后续远程交付由对应 PR 记录。后续 fenced B 与退役协调仍是独立候选，不因本次装配共享自动接受或完成。
