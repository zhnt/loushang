# D2-B1 配置构造设计与代码评审

- 对象：[D2-B1](bootstrap-capability-config.md) R1 独立初评，以及 R1.1 澄清的运行视角窄复核，以及接受后的实现与代码评审（分阶段记录）。
- 基线：本地 main/HEAD `2490c9d54f06e9f1d88b23a050dce8b3cf185f83`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 范围：原 B Catalog 父函数内两个同步配置块的局部复用；不改变原 Store/平台/清理/编译或兼容/deferred 路线。
- 视角：职责与复用；运行与失败；数据、兼容与验证。按用户既有要求采用独立 xhigh 评审，各自阅读实际源码，不读其他评审。

## 固定版本与方式

| 版本 | SHA-256 | 作用 |
| --- | --- | --- |
| R1 | `fb468008deac985cf3192e5e853156a233b274da5f90bd50f924d2590fc82c3f` | 三个独立 xhigh 视角的初评 |
| R1.1 | `62582cbbc942b5d0a6cd6a1a0f23d85ebccaa98f0e25a2581bd388b48b1db709` | 失败措辞澄清及源码引用校准，运行视角定向关闭 F1；受审合同快照（状态更新前） |

三个 `gpt-6.1-sol` xhigh agent 各自核对实际源码、适用 AGENTS、方法与原合同；不读取其他 B1 评审、评审索引或作者 AST 探针。三份 R1 初评齐备后才整理修订，再由受影响的运行视角窄复核。职责、数据视角未重做 R1.1 初评，不将这次措辞修订称为三个视角重新评审。

## 结论与发现关闭

| 视角 / 评审者 | R1 结论 | 后续 |
| --- | --- | --- |
| 职责与复用 / `d2_ownership` | 无发现，可交用户评审；单参数与六项原词法来源足够，局部函数有有限维护收益，职责仍归 Coding | R1.1 不改变其接口/职责或复杂度判断 |
| 数据、兼容与验证 / `d2_data` | 无 P0/P1/P2 发现，可交用户评审；原 list、dict 次序、字段/默认 quota、getter/constructor 求值及验收计划成立 | R1.1 未变更数据或验证合同 |
| 运行与失败 / `d2_runtime` | 无机制阻断；F1 为低级别失败措辞歧义 | R1.1 静态窄复核关闭 F1，无新矛盾或剩余本视角阻断 |

F1：R1 “LSP 校验失败时，不准备 Arch 目录”可能掩盖 helper 调用前已创建的 temporary directory。原 bootstrap 1538–1544、1728–1734 会先建立临时目录，因此该句不能被解释为无目录副作用。R1.1 改为“不执行后续 Arch 配置表达式/不调用持久 Arch 私有根 adapter”，明确已有临时目录或已完成的目录操作仍走原清理路径，不新增回滚承诺。同期校准原配置块/try/constructor 的行范围，澄清异常原样传出指保留原表达式向外逸出的异常，原 constructor/adapter 自身转换保持。

综合结论：**R1.1 可提交用户评审；未关闭发现为 0**。一个普通同步局部函数、原两个 if、原两个调用位置可以保持既有边界；尚不能据此断言实现、运行故障轨迹或全平台验证已经通过。

## 综合协同与验证边界

- 原 shared pipeline、Store/目录/平台 owners 和 Current owner map 均保持；没有新增组件或公开合同，按当前范围不必新建 ARD。若需改变职责、准入、持久格式或恢复语义，回到父级设计。
- helper 在调用时读取原 cell，不冻结 Arch 临时状态、不预求 Path、不缓存 cwd/current 事实；目录准备仍有原身份/ACL与部分失败副作用，不将它描述为纯查询。
- helper 不接手临时状态和 cleanup，不改变两处 try 与外层 handler；兼容和 deferred LSP 继续原输入与当前性路径。原部分失败没有被补造为统一 rollback 或“只执行一次”保证。
- 成功字段相等不足以证明失败等价；后续实施须核对原对象、getter/constructor/目录准备次数、异常身份与停止前缀。现有测试仅供定位，不能替代新调用形态的差分。

本轮仅静态核查：15 份源码/测试 SHA 与基线一致，只修改五份文档。轻量文档检查 9 项断言、变更文档相对链接与 `git diff --check` 通过。未 import 产品或运行 pytest/native/异步/模型试验；不改 gate。

冻结件、源码快照/哈希、原始报告和检查记录位于产品树外 `architecture-analysis/plugin-harness-audit-20261104/d2-b1-design-20261105/`：

| 原始报告 | SHA-256 |
| --- | --- |
| `review-ownership.md` | `f615651bb0a29473c336718c5d8558e97a722eb2c225fd86e41fd5ee35dc4d5b` |
| `review-data.md` | `5e13c626c2dadd44e0fbd79afc7c3a683cfbb3678489de61d864e7ddb3c4adb4` |
| `review-runtime.md`（含 R1.1 复核） | `06728b48c49e092c2dc96ae40fb3975903f70fd4f2c62a897107452b227edf57` |

## 设计阶段接受状态（历史）

用户此前明确要求“系统环境图等重要工作件需要我评审”。本轮将 R1.1 §2 调用关系、§3 求值/失败合同及 §5 验收计划作为用户评审对象；内部结论不替代该接受。Design status 保持 proposed，Implementation status 保持 not-started；没有修改产品实现，也不把 D2 整体标记完成。


## 实施与代码评审

用户在听取 R1.1 关键机制及 LSP/Arch 可独立启用说明后，以“同意，请继续”接受并授权实施 B1。当前 Design status 为 accepted，Implementation status 为 implemented；远程交付状态以对应 PR 为准。未扩大接受范围，不将 D2 整体标记完成。

实现仅在原 B 父函数提取一个同步局部函数，两个原配置位置调用；原两个 if、六项调用时词法来源、配置对象/顺序、私有目录与 cleanup owner、两个 composer try 的边界均保持。反向内联新函数后，完整 bootstrap 模块 AST 与原基线相等。兼容与 deferred 路径保持原实现。

### 三视角独立代码评审

三个原独立 xhigh agent 各自检查候选源码与接受的合同，初评不读取其他报告或作者差分结果。初评后因下述测试配置修正，运行与数据视角再作定向复核；职责视角没有重评该测试修改。

| 视角 / 评审者 | 代码结论 | 测试配置修正复核 |
| --- | --- | --- |
| 职责与复用 / `d2_ownership` | 无发现；保留 Product 输入适配与原资源 owner，无新增通用组件 | 未重复评审 |
| 运行与失败 / `d2_runtime` | 无发现；原求值、异常及两分支清理合同保持 | 无发现；只显式配置联合激活前提 |
| 数据、兼容与验证 / `d2_data` | 无 P0/P1/P2 发现；原对象、字段与格式保持 | 无发现；原断言、其他用例和 gate 范围保持 |

综合代码结论：未关闭发现为 **0**。评审为静态检查，下面的运行验证由实施者另行执行，不将其归为 agent 已运行的测试。

### 实际验证与既有测试修正

| 检查 | 结果及范围 |
| --- | --- |
| 树外完整内层 B 函数/外层 wrapper 的受控差分 | **38 passed**；两分支、代表性插件组合、temporary/持久配置、原对象/字段/调用顺序、live cell 与不同 cwd，以及 getter/LSP/layout/private-root/Arch/composer 的失败、取消与清理轨迹。使用受控 collaborators，不调用模型或 native host |
| 相关仓库测试 | **41 个不同用例通过**：首次聚焦运行中不受后述既有失败影响的 29 个配置/bootstrap 用例，加测试配置修正后 `tests/coding/arch/test_activation.py` 全文件的 12 个通过用例；不是一次重新执行的 41 项套件 |
| 静态等价与范围 | 完整模块反向内联 AST 相等；一个 helper、两个调用、无默认参数冻结；原父函数自由变量集合保持，helper 恰好捕获六项来源；15 份基线文件中其余 14 份 SHA 不变 |
| 静态质量 | 修改的源码与测试 Ruff 通过；bootstrap 的 mypy `--follow-imports=silent` 通过；现有 package dependency facts 检查通过 |

首次聚焦运行是 30 passed / 1 failed。失败用例 `test_arch_and_lsp_share_one_product_composition_and_session_graph` 在未改动的 main 基线也单独复现：fixture 只显式将 Arch 配为 always，而 LSP 生产缺省是 on_demand，用例却断言两者均即时挂载。修正仅为该联合用例显式传 `lsp_mode="always"`；helper 的可选参数默认 None，其他调用及生产缺省均保持。测试文件原有全部 41 个 assert AST 和测试名称不变，随后全文件 12 项通过。没有新增测试路由、矩阵或 merge gate。

本地运行遵守既有非 live、非 host-runtime 选择和 sandbox 外执行要求。不据此声称全仓、所有平台、native/hosted 全支持面或全部 B 组合已验证；没有重复付费 Goal 试验。产品调用次数未减少，不主张性能提升。

### 冻结实现与原始证据

树外前述归档的 `implementation/` 保存源代码前后快照、JUnit、主线失败复现、静态证明及原始代码报告：

| 对象 | SHA-256 |
| --- | --- |
| 最终 `src/loushang/coding/bootstrap.py` | `6d39bc6952af4cab62350c06588d137554c28e46f9057b1f1448159fd526565c` |
| 最终 `tests/coding/arch/test_activation.py` | `c0b81bb5909ad8079c8ac30326c81ba7494bd8644f7907f8719cb443b17682a2` |
| `code-review-ownership.md` | `01b721782e6efbbd992465302155bc4906fff1379ed13b670ac123e32ee6263c` |
| `code-review-runtime.md`（含测试修正复核） | `279604156d1873238b2219c9d83b8f37cb6c54128b6202424c8d060c4adc099c` |
| `code-review-data.md`（含测试修正复核） | `e9731c5e5768ecf15e6540e66d9d280d3f1b3807f5d14002f43d773703c49527` |

`differential.xml` 记录 38 项差分；`focused.xml` 保留首次 30/1 结果；`main-joint-activation.xml` 保留主线单项失败；`activation-fixed.xml` 记录 12 项通过；`combined-checks.json` 说明 41 个不同通过用例的统计来源。最终文档、链接、哈希和范围校验另记于 `implementation/validation.json`。
