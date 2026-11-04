# M1c 文件树核验：三视角独立设计评审

## 对象与范围

- 日期：2026-11-04；对象：[M1c 设计](materialization-tree-validation.md) R1 → R2。
- 初评时用户同意继续差异清单、接口与失败路径设计；设计复核后，用户明确要求“请你按照R2开发实施”。下文保留设计审查历史，并追加实际实施与代码审查记录。
- 复用同专项的三视角 xhigh 独立审核安排：`m1c_ownership`、`m1c_runtime`、`m1c_data` 均以空上下文启动，独立读取适用规则、方法、源码与测试，不以其他评审报告代替判断。
- 原评审者对 R2 做定向复核；不把已有发现上下文的定向复核称为又一次全新隔离审核。
- 源码基线：main `f8e46275565cf33f6ca945cb1b60200767162847`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核验方法远端。
- R1 SHA256：`9c0f4c5aa8e017a65de814601e8b540bad06253ae0cba476813ab6d76fe0e266`。
- R2 冻结审核版本 SHA256：`ab6418babf2774650eca699b1d35bc5d10ba4f79fc164a1b635cffc01ae93ac0`。
- 设计审查深度：静态调用链/AST/合同与失败走查。设计阶段未运行 pytest、平台实验、Product 异步运行时、付费模型或性能测量；实施验证另见下文。

本次只评“唯一共享树 scanner＋完整核验＋窄平台读取端口”。写入/file sink、reuse sink、abort 删除仅盘点边界，没有提前冻结其未来接口。GC 的 partial 扫描是实际受影响消费者，纳入本切片核查；不改变 tombstone 或删除授权。

## 初评与处置

| 视角 | 初评结论 | 发现与 R2 处置 | 复核状态 |
| --- | --- | --- | --- |
| 职责与复用 | 无阻断；原 tree_transfer 是写入/传输合同，不是可直接替代的实际树 scanner；两个窄读取端口与一个临时观察值足够 | O-N1：Windows writable=False 仅指新开 scanner 子目录；借入 GC/owned 根保持原 mode，不重开/dup 根 | 原 reviewer 复核关闭，无剩余设计发现 |
| 运行与失败 | 无实质阻断；原锁、根 owner、包装错误与观察图归属可以保留 | N1：未知成员不进入内容读取/递归，但 Windows 属性 stat 仍有 native handle；N2：Windows names tuple 捕获时 eager component 检查，metadata 才是逐项 lazy | 原 reviewer 确认 N1/N2 关闭，无新增阻断 |
| 数据与兼容 | 一个局部设计阻断，非现有产品缺陷 | B1：`.open_file` 会被无接收者类型区分的库存误记为新增 verified writer。R2 改为语义明确的 `file_reader`，不改识别器、不放宽 token/owner/count；实际 OS 访问仍等价核对 | 原 reviewer 确认 B1 关闭 |
| 数据与验证 | 两个非阻断范围澄清 | N1：现有 POSIX partial retry 直接证据不能替 Windows 成功 GC/absence replay 证明 Windows 重试；R2 明列待 native 验收。N2：属性句柄与内容读取区分，同运行视角处置 | 设计说明已闭合，native 证据继续作为实施验收条件 |

改名的目的不是隐藏 OS 访问：现有 `tree_transfer.open_file` 是 verified writer，新的端口提供只读文件 reader，语义不同。原 native helper 与安全边界必须继续保留，不能通过通用 getattr、换个裸路径访问或删除 guard 逃避库存。真实 OS 站点若移动，仍按原角色和授权等价迁移。

## 已核实的主要合同

1. `_validate_tree_contents` 两平台各 24 行 AST 相同；`_collect_tree` 为 112/103 行的同类算法，夹杂不同 OS 原语。共享的是 DFS、成员/身份、计数摘要和 full/partial 规则，不只是再加一层调用包装。
2. 当前 collector 两类直接消费者是完整内容核验与 GC partial；GC 先写 tombstone、扫描、核对在场内容，再逐项重检身份删除，失败不应以半成品图继续删除或撤回 tombstone。
3. root Adapter 只借用已打开 tree fd；父枚举器、子目录、文件各有原作用域，晚期身份检查与原 close 覆盖关系保留。公共层不接收 fd/HANDLE，不授予访问权限，不新增一致性快照保证。
4. observed 三张图、原 manifest/receipt/journal 及外层构造/错误接口不改；缺失项只在 partial 中允许，不补造 observed，也不能让完整入口自动降级。
5. `read(64KiB)`、超长检查和 late identity/link/reparse 时点保持原语义；性能仅声明不额外整树复制或重复扫描，没有已测耗时收益。

## 证据、未验证项与接受边界

完整独立报告、R1/R2 冻结原文、原源码及 AST/SHA 清单在产品树外 `architecture-analysis/plugin-harness-audit-20261104/m1c/`，报告名为 `review-ownership.md`、`review-runtime.md`、`review-data.md`。产品内保存本索引和独立表达的处置，不复制方法文本。

实施后仍需证明实际 primitive 轨迹、close 顺序、原生访问模式和所有真实调用者符合设计；原 Windows native 暂停安排保留，partial retry 必须有对应版本真实证据才能报告完成。mock、静态评审和 Linux 通过不能代替该证据。

新增本地验证若会增加原 PR 门禁失败条件，需遵守已有变更控制或留在产品树外，不因设计获认可就取得扩门禁授权。设计评审本身不声明用户接受或实施验收，也不将整个 materialization Store 的收敛视为完成；后续实施授权与实际验收边界见下文。

## 综合结论

三位原 reviewer 对同一个冻结 R2 完成定向复核，均确认设计层无未关闭阻断，可以进入该窄读取切片的实施。此为实施前结论，不代替用户评审或 native Windows、性能验收；当时保持 proposed/draft 与 not-started。

设计阶段交付是差异清单、接口、调用者及失败路径设计和三视角处置记录；当时源码、测试、工作流、门禁均未修改，9 项静态文档断言、变更相对链接与 `git diff --check` 通过。原六份 Goal 文档和先前 M1a/M1b 已交付状态未改变。

## R2 实施与三视角代码审查

用户在冻结 R2 设计审查后明确要求按 R2 开发实施。主代理据此接受本切片内部职责调整并落实源码；授权不扩及后续写入/删除收敛、恢复暂停的 Windows 路线或新增 PR 门禁。上文 R2 SHA 指实施前冻结原文，后续状态更新不改写该历史对象。

实际改动为一个共享内部模块及两个平台模块：`_tree_validation.py` 唯一拥有 full/partial DFS 与完整核验；两个平台的原入口薄委托，通过目录与文件读取端口调用原安全原语。AST 对照源码基线：POSIX 原 26 个、Windows 原 23 个其余顶层定义保持相同；GC 授权、tombstone、实际删除、root pin、写入/reuse sink、abort 和持久格式未改。

三位原 xhigh reviewer 分别独立检查实际源码、完整 diff 与调用者，没有用其他报告代替判断；它们仍持有前期设计背景，因此不称为三次全新空上下文评审。

| 代码审查视角 | 结论 | 固定范围 |
| --- | --- | --- |
| 职责与复用 | 无阻断、无需修复问题 | 真正共享规则；平台仅 native 读取；不新建 root owner 或重复 transfer 合同 |
| 运行、失败与平台安全 | 无阻断、无需修复问题 | 惰性观察、Windows 名称检查、借根 mode、64KiB、late identity/reparse、close、GC partial 保留 |
| 数据、兼容与库存 | 无阻断、无需修复问题 | observed 三张表、full 默认、partial 不补记录、持久/公开合同与 OS 库存保持 |

三个报告固定于相同源码 SHA256：

| 文件 | SHA256 |
| --- | --- |
| `_tree_validation.py` | `53fdc378fb7eccde34b28be298105a22a40a51368a27be228898792075030e4b` |
| `posix_materialization.py` | `99b3bf7236a62b1b0a21303463553b6a436c2ccbc7a63952b22b41a4b1d03ca4` |
| `windows_materialization.py` | `db539f95e07875d7fe1a7adec91d253369ead1113f1cec530a96ac3291fde3f7` |

完整代码审查与 AST/SHA 证明仍保存在前述产品树外目录，文件为 `code-ownership.md`、`code-runtime.md`、`code-data.md`、`implementation-proof.json`。

实施者本地验证：

- 三份改动源码 Ruff 与 mypy 通过。
- 既有 POSIX/Windows materialization 与 PLC9B/统一 Plugin 架构合同回归：141 passed，27 skipped（Windows native），127.62 秒；保持 `not live`、`--skip-host-runtime`，首次即在沙箱外执行。
- 产品树外本地补充验收：17 passed，1.90 秒。覆盖调用先后、未知成员、full/partial、句柄关闭、Windows 模拟观察及四种树状态与旧 POSIX scanner 的输出/错误对照；未加入 Product 测试或 PR gate。这些结果不能代替 Windows 原生访问证据。
- 变更计划中的文档 9 项断言、包依赖事实检查、Harness 全量 Ruff/mypy（786 个源码文件）与 Hosting Ruff/mypy（35 个源码文件）通过。
- Harness 扩展离线回归：6413 passed、121 skipped、3 deselected、1 failed，976.20 秒。唯一失败为既有 `test_direct_ai_model_entrypoint_imports_remain_inventoried`：库存未列出 Coding `goal.py` 的 `stream` 导入。已在干净控制工作树 main `f8e46275565cf33f6ca945cb1b60200767162847` 独立复现同一失败（32.83 秒），相关产品文件及库存断言本切片未改。不得把这轮检查报告为全绿，也未通过扩允许集合掩盖失败。
- `unit_harness` 相对完整 Harness 路线独有的两个示例文件：3 passed，3.71 秒。计划中重复的 full/unit 文件范围按已执行覆盖去重，没有更改检查选择器或仓库门禁。
- Hosting 与独有示例曾被运行目录容量保护在测试执行前拒绝。后续使用既有 `LOUSHANG_RUNTIME_DIR` 配置，将补跑的运行目录放到产品树外本任务磁盘目录；保留 64MiB 容量检查、原非 live/host-runtime 选择，没有删除用户状态或降低保护阈值。
- Hosting 补跑：512 passed、53 skipped、4 deselected、1 failed，115.71 秒。唯一失败为 `test_hosting_apphost_and_appserver_optional_modules_are_exact`，appserver 精确模块库存未列既有 `goal.py` / `method_work.py`；在同一干净 main 基线单条复现相同失败。相关模块与断言均未修改。扩展检查共有这两项已复现的主线既有库存失败，不宣称 `make check-changed` 通过；日志与基线复现保存在产品树外归档。

本地实现和三视角代码审查完成；Windows native 与 Windows 部分删除重试、性能测量仍未验收。本结论不意味着整个 Store 收敛完成，也不触发后续写入/删除切片的实施。
