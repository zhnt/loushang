# E1 Catalog 正式模块专项评审

- 对象：[E1](catalog-adapter-module.md) R1 三视角独立初评，以及 R1.1 的两项定向复核和用户接受后的实现/代码评审；分阶段记录。
- 源码基线：main `9f8c851b5c7cb4a8fce51c140e85bbc135454286`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未验证 upstream。
- 范围：Coding 单一正式实现、旧 import 的窄兼容转发、六生产消费者与原精确源码库存等价迁移；协同 D2 本轮范围结案。
- 当前状态：R1.1 已获用户接受；本地实现与验证、三视角代码评审完成，未关闭代码发现 0；远程交付状态以对应 PR 为准。

## 固定版本与独立性

| 受审件 | SHA-256 | 用途 |
| --- | --- | --- |
| R1 | `dd2a5880ac92634cb5f85d76333ab0fbd80bde0ecca5d2f35d8e7068fe867f8c` | 三位独立 xhigh agent 的初评 |
| R1.1 | `81d6c4a5bdfc7b02a3d57de4c358f23691a2b73e1cd41c99c3d98052fc2a28cb` | 补当前导航及具体验证落点，职责和数据视角定向复核 |

三个 `gpt-6.1-sol` xhigh agent 各自阅读实际源码、适用 AGENTS 与本地方法，以独立上下文核查；初评不读取其他 E1 报告或作者树外 manifest。评审者各自执行文本/AST 分析，不 import 产品、运行 pytest/异步运行时、模型或 native 场景。源码与测试保持原基线。

## 结论与发现处置

| 视角 / reviewer | R1 结论 | 后续处置 |
| --- | --- | --- |
| 职责、收益与复用 / `e1_ownership` | 无阻断；同包正式实现加窄 shim 有维护收益，Product policy 与 Harness 机制保持；D2 未误称全部完成 | O-OWN-1 非阻断：补正式当前导航、保留固定基线历史；R1.1 定向复核在设计层关闭 |
| 导入、运行与失败 / `e1_runtime` | 无实质或阻断发现；六 import、17 名字和单向 shim 能保持原对象/默认值、协作者及失败链；没有发现持久 module 身份连接 | R1.1 没有改变其所评机制，不重复完整初评；实际运行结果仍待实施 |
| 数据、兼容与验证 / `e1_data` | 无阻断；八项 wildcard、14 正式/seam 名字加三别名完整；三处实现库存可等价迁移 | D-E1-01 非阻断：指定真实 Resume node IDs，区分旧 exported prepare 与当前 bootstrap；R1.1 定向复核在设计证据计划层关闭 |

O-OWN-1：当前文件中的历史源码链接多来自固定审计/设计基线。R1.1 要求实施结果补正式实现的当前导航并标注旧 shim；保留历史路径与行号，避免既重写历史、又让当前索引停在转发文件。实际迁移后的导航仍须实施者核对，不把设计要求关闭当作链接已迁移。

D-E1-01：旧 exported prepare 虽在兼容面内，当前无生产/测试直接调用。bootstrap 先 `prepare_catalog_input_receipt` 再调用 build；原集成测试文件通过不能自动证明旧 prepare 的一次 take。R1.1 给出树外计数探针的成功/错误/消费后拒绝观察，并列出能真实持久重开的原 storage compatibility 与 Resume bootstrap 节点；要求记录实际平台、参数及 skip。只确定后续证据计划，没有虚称这些用例或探针已运行。

综合结论：**R1.1 可提交用户评审，设计层未关闭发现 0**。这是 R1 三个独立初评加 R1.1 两项定向复核，不是三位 reviewer 都重新完整评审 R1.1；没有实现或运行验收结论。

## 综合协同与范围

- 单一实现仍归 Coding，同包移动不新增组件/owner；领域 policy/trust/roots 与 Harness admission、Catalog、Graph、Session 寿命边界保持。
- 旧 shim 只转发真实对象，不以 wrapper/subclass、复制 policy、动态 namespace 代理或第二份实现维持兼容。模块自然 `__module__`/traceback 差异已披露，不借仓内零命中宣称任意 pickle/热替换/仓外 namespace 都兼容。
- RCP1、RCP2、type-system 库存对应真正实现位置，保持 exact set 和原禁用断言；无增加或放宽 gate 的授权。Harness 本身真实 shadow 的候选/lease 生命周期不属于命名迁移。
- D2 只关闭本轮已交付和已明确保留的范围；不把 legacy 删除、全部分支统一或 M1 Windows native 缺口写成完成。E1 不隐含启动 E2、M3 或性能项目。
- R1.1 仅补导航和验证计划，§1–§3 核心机制与 R1 逐字相同。实施前若发现实际持久模块身份或支持中的旧 namespace 行为，先重开兼容设计。

## 静态验证及局限

作者复核确认：22 份命中源码/测试快照 SHA 不变；六生产直接导入文件、五测试直接导入文件；全部仓内显式导入、原八项 `__all__` 和三个旧 alias 的并集为 17 项。仅修改六份文档，产品、测试、打包和 gate 零变更。

轻量文档检查的九项静态断言、六份文档仓库相对链接和 `git diff --check` 通过。没有运行产品测试、冷导入/identity 探针、wheel 安装、模型或 native 试验；故不声称实际迁移、恢复或全平台行为已通过验证。持久身份判断仅对应已查的 receipt/Catalog JSON/Plugin manifest/Resume 路径，不能证明不存在仓外消费者。

树外 `architecture-analysis/plugin-harness-audit-20261104/e1-catalog-module-20261105/` 保存两版冻结设计、源码快照与 manifest、版本差异、静态检查和原始报告：

| 原始报告 | SHA-256 |
| --- | --- |
| `review-ownership.md`（含 R1.1 O-OWN-1 复核） | `4e59802cc09faed3c694f379ac04894eeaa187a2324a410021e8f08f642257a9` |
| `review-runtime.md` | `4587609903f309c2b71b7fc6ffca2c31de70c2fab6b520ee5ff16fa9308a4fd0` |
| `review-data.md`（含 R1.1 D-E1-01 复核） | `43556306b403b7fea03aafa5f8b3d6da5b4235b725661e840a13eeb932895aec` |

## 设计阶段用户评审状态（历史）

用户已同意完成 D2 结案并推进 E1 专项设计及三视角评审；本记录不把该授权写成尚未呈交的 R1.1 合同已接受。按用户此前“系统环境图等重要工作件需要我评审”的明确要求，提交 E1 §2 关系图、§3 兼容范围及 §4–§5 迁移/验收边界供用户评审。产品实现保持未开始，不删除旧路径或别名；本轮文档也未 commit/push。


## 用户接受后的实施与代码评审

用户在收到 R1.1 关系图、兼容范围和设计评审结论后，明确“同意，请实施开发”。本次接受限于该窄迁移及验收，不自动接受兼容路径删除、Harness shadow 改名或 D2 余项合并。Design status 为 accepted，Implementation status 为 implemented；远程交付状态以对应 PR 为准。

唯一实现现为 [Coding Catalog adapter](../../../../../src/loushang/coding/_resource_catalog_adapter.py)，原 [shadow 模块](../../../../../src/loushang/coding/_resource_catalog_shadow.py)仅保留兼容转发。新实现逐字等于基线删除尾部三个旧别名及其说明块；类体、函数体、import 顺序、默认值、policy/revision 字符串、八项 `__all__` 保持。六生产文件只改 import 路径；三架构库存文件各只改一次实现路径字面量，原全部断言、扫描和 exact set 比较保持。

### 三视角独立代码评审

三位原独立 xhigh reviewer 按接受的 R1.1、实际 diff 和基线 `git show` 评审同一份 11 文件候选。只读取固定文件清单，不读取作者证明、探针/测试结果或其他代码报告；各自重新计算候选哈希。三份评审均为静态检查，不将下面作者运行结果写成 reviewer 已执行。

| 视角 | 结论 |
| --- | --- |
| 职责、收益与复用 / `e1_ownership` | 无发现；唯一实现、Product/Harness 责任和单向 shim 依赖保持，生产路径已切换；原库存控制仍指向真实实现 |
| 导入、运行与失败 / `e1_runtime` | 无实质或阻断问题；原 globals/协作者、policy/default/exception 绑定、receipt/编译/cleanup 流程保持 |
| 数据、兼容与验证 / `e1_data` | 无阻断或非阻断发现；17 项兼容绑定、八项 wildcard、持久字段/版本及三处库存迁移符合 R1.1，无 gate 放宽或扩张 |

综合代码结论：**未关闭发现 0**。

### 实际验证

所有运行验证使用本地 Python 3.11、Linux，在 sandbox 外首次执行；仓库 pytest 保留 `-m 'not live and not requires_host_runtime' --skip-host-runtime --strict-markers`。没有模型、网络或付费 Goal 试验。

| 原测试范围 | 实际结果 |
| --- | --- |
| `tests/architecture/test_plugin_contribution_type_system.py` | 3 passed |
| `tests/architecture/test_resource_catalog_rcp1_shadow.py` | 3 passed |
| `tests/architecture/test_resource_catalog_rcp2_components.py` | 10 passed |
| `tests/coding/test_resource_catalog_shadow.py`（原兼容 import 与全部场景） | 34 passed |
| `tests/coding/test_workspace_storage_compatibility.py::test_ordinary_upgrade_reopens_legacy_workspace_and_transcript` | 原 `[settings]`、`[package_v4]` 两项 passed |
| `tests/coding/test_resume_bootstrap.py::test_resume_bootstrap_uses_current_plan_without_rewriting_original_header` | 原 `[legacy]`、`[changed]` 两项 passed，Linux 条件实际满足 |

单次聚焦运行合计 **54 passed / 0 failed / 0 skipped**，183.26 秒。结果由 `focused.xml` 和逐项 `focused-summary.json` 固定，不以纯构造 history 的比较替代持久重开。

另外三个树外受控进程通过：旧路径先导入、正式路径先导入，以及六生产模块导入。前两项逐一核对 14 个正式/seam 名字与三旧别名的 `is`、原八项 wildcard 及顺序、默认 standard policy 单例和函数 globals；用计数 receipt source 与受控 build 协作者实际调用旧 prepare 别名，验证成功一次 take、AttributeError/RuntimeError 原因转换、build 拒绝后不重新领取。受控协作者在 finally 恢复，不将其当作真实 Catalog 编译证据；真实 build/编译由上述原 Catalog 场景覆盖。生产进程确认六模块全部导入正式模块，旧 shim 未加载。

静态核对与质量检查：

- 完整模块 AST 除三旧 alias 外与基线相等；六消费者只改 import；三库存只改完整实现路径字面量，原禁止 flag 未改。
- Ruff 覆盖八个修改/新增源文件与三库存测试，通过；八个源文件 mypy `--follow-imports=silent` 通过，不代表完整依赖树类型检查。
- 原 package dependency facts `--check` 通过，无需改生成事实。
- 当前实现导航已补入专项 §6，旧 shim 角色明确；原固定基线证据的历史路径/行号保留。
- 最终九项文档静态断言、六份变更文档的相对链接与 `git diff --check` 通过。未扩展或恢复任何 PR gate。

这些证据完成 R1.1 本地实施验收；不据此声称全仓、全部托管/平台入口、Windows native、任意 pickle 或仓外 namespace 行为均已验证。没有性能提升或删除 legacy 的结论。

### 冻结实现及报告

树外前述归档的 `implementation/` 保存 before/candidate 源码、`candidate-manifest.json`、AST 证明、JUnit、三份探针输出、质量检查及原始代码报告。

| 对象 | SHA-256 |
| --- | --- |
| `src/loushang/coding/_resource_catalog_adapter.py` | `2b8769dc3b2636ca3821db6bda5e8647bc99bbb0ba8bc70eec1a7260776c70d1` |
| `src/loushang/coding/_resource_catalog_shadow.py` | `e859f501846e1997056b73f771a53a18d1df7fb085b99f654d04ac94d3f520a7` |
| 11 文件 `candidate-manifest.json` | `fde3cb3e1df3fb8be93ed0e436b3431dcffbdfeeec37150558b8986e40baf700` |
| `code-review-ownership.md` | `898bce37e8184b569fe04fada4c183c4d4de7527785bd213dcb5805d3e3e4652` |
| `code-review-runtime.md` | `4bc86b6f12f849c643cfdaca9d34656e331e37ed8c4153bb278601fd659e20d7` |
| `code-review-data.md` | `a45671700c905822ba3cd7841fb1533cd5bdc2867c5f660566d678f476dd9a11` |

冻结 R1.1 是设计元数据更新前的合同快照；当前设计文件已同步接受、实施状态和当前源码导航，不以其新字节哈希覆盖受审原件。最终校验与本地完成记录分别位于 `implementation/validation.json`、`implementation/completion.json`。
