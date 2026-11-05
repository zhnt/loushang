# 包物化平台 Adapter 三视角独立评审

## 评审框架

- 日期：2026-11-04。
- 对象：[M1 平台 Adapter 设计](materialization-platform-adapter.md)，初评 R1，修订复核 R2。
- 设计评审阶段用户要求：三个独立 xhigh agent；该阶段负责评审与修订，不启动平台实现。后续用户另行授权开发，实施复核见末节。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。源码基线 main `1120f9b1fe3b8610de76b60c115660dc9d0353d7`；harness lane HEAD `b4b0a03fbd09e06342d18e86c79b0089f4668281` 与其完整 tree 相同。
- R1 SHA256：`5e04ac39aed1c2b6cae483b5eb7b60c85cc192be684b20d6321630092cc73925`。
- R2 冻结评审版本 SHA256：`9bf1f706cbbe784fa92118882d0ea28e5c51e4da52e5c416086b069667ff8624`。三份复核完成后仅更新该设计的 Design status 行，说明复核已完成，接口和合同正文未改变；冻结原文另有归档。
- 范围：M1a 的接口、receipt 共享流程、平台边界、兼容和验证；M1b/c 仅作方向一致性核对，不要求提前设计全部发布/清理接口。
- 独立性：三位 agent 均以空会话上下文启动，独立读取适用规则、方法、文档、源码与相关测试；不读取其他 reviewer 报告作为判断依据。主执行者汇总发现并修订，再由原 reviewer 复核各自相关差异。
- 证据限制：静态核查，没有运行平台回归、pytest 或 native 实验；工作区已有的 M2 实现不属于本次平台设计评审。

## 初评结果

| 视角 / agent | 独立初评结论 | 主要依据与发现 |
| --- | --- | --- |
| 职责与复用 / `platform_adapter_ownership_review` | 无本视角阻断；可实施受约束的 M1a | 两份 receipt 算法确实相同；共享函数与薄 Adapter 足够；建议缩窄 Protocol、复用身份别名、明确 Windows 访问模式 |
| 运行与失败 / `platform_adapter_runtime_review` | R1 有一项实施前消歧阻断 | 操作级 journal 只读与 Windows 构造级原生访问模式不能混合；保留锁/pin 顺序、原关闭与异常限制 |
| 数据与兼容 / `platform_adapter_data_review` | 同一只读歧义阻断 R1 原样冻结 | 数据形状与持久格式可复用；源码库存及原合同断言需随实际移动等价迁移；Windows 必须有对应版本 native 证据 |

两个视角提出的只读问题属于同一合同缺口，不计作两个独立产品缺陷。它是设计歧义，尚未实现，不能称为现有安全漏洞。

## 发现与 R2 处置

| 归并项 | 原报告项 | R2 的最小处置 | 复核状态 |
| --- | --- | --- | --- |
| F1：只读的两个维度 | OWN-N1、runtime D1、data D-01 | `pin_root()` 去参数；Adapter 构造绑定完整祖先链与原访问模式；Windows 保留 `writable=not construction_read_only`；operation 只选原锁和 journal 方法 | 三位原 reviewer 复核关闭 |
| F2：接口与共享实现粒度 | OWN-N2/N3 | 删除未使用的 `validate_visible`、expected-tree/map 输入；复用原 NativeIdentity；M1a 只需共享函数，不建立完整 Store 大类 | 职责视角复核关闭 |
| F3：关闭、异常与观察保证 | runtime N1/N2、data N-01 | 明列锁→pin→核验→关闭→退出顺序；保留原 close 抑制 OSError 和错误覆盖关系；不虚称可重试关闭或整树原子快照 | 运行/数据视角确认设计处置充分 |
| F4：源码库存与兼容验证 | data N-02/N-03 | M1a 移动 pin 时等价迁移两处 path_read 站点；将平台源码字符串要求改为共享实现与两个平台真实委托的等价断言；保留覆盖，不扩 gate | 数据视角确认；实际迁移待实施 |
| F5：平台交付范围 | 三位证据局限 | 复用原 POSIX/Windows 路线；结果绑定变更后源码且 Windows 不跳过；缺 native 结果必须标待验证；不虚称 macOS 已验证 | 验证合同明确；实际运行证据待实施 |

原证据的进一步校正：两平台均在授权与 rename 前关闭 staging descriptor；POSIX flush 与 Windows rename 差异仍须后续单独建模。M1b/c 没有因本次 M1a 评审而被接受。

## 综合结论

原三位评审者均已对同一个冻结 R2 完成定向复核，设计层无未关闭阻断，M1a 可进入实施。不得将其扩大为整个 Store 已统一、Windows native 已通过、M1b/c 已接受或用户已接受本设计。实现符合性、库存等价迁移及对应源码版本的两平台运行证据仍是后续工作。

文档静态检查 9 项及仓库相对链接检查通过，`git diff --check` 通过。没有运行平台测试、修改平台源码或扩大 PR gate。

## 记录位置与权威

完整初评及原 reviewer 的复核结论保存在产品树外审计归档 `architecture-analysis/plugin-harness-audit-20261104/`：

- `platform-adapter-review-ownership.md`
- `platform-adapter-review-runtime.md`
- `platform-adapter-review-data.md`
- R1 原文及 R1/R2 hash 清单。

本文件是产品内的独立表达与处置索引，不复制外部方法文本。设计评审当时保持 draft / not-started；其结果不能冒充后续实现或跨平台验证完成。

## M1a 实施后的独立代码复核

用户在上述 R2 复核之后明确要求实施开发，授权范围为 M1a。原三位 reviewer 分别检查实际三源文件、相关调用及等价库存迁移，仍保留原视角独立性；没有以设计通过替代码背书。

| 视角 | 实际代码结论 | 剩余边界 |
| --- | --- | --- |
| 职责与复用 | 未发现阻断或待整改代码项；共享算法、两个 Protocol 实际使用，原八个公开 Store 类和两模块导出不变 | M1b/c 未实施 |
| 运行与失败 | 未发现阻断；锁/关闭顺序、原异常映射、根身份和 Windows 构造访问模式、journal 只读分支保留 | 不声明 Windows native 已验证 |
| 数据与兼容 | 未发现产品代码缺陷；原 reviewer 已确认 G-01 关闭，无未关闭评审问题 | Windows native 证据仍待取得 |

治理发现与处置：六个新增案例若留在原 Harness 测试树，会被原 gate 自动收集，形成新增失败条件。没有另行扩门禁批准，因此将案例保留到产品树外本地验收归档，恢复原 POSIX 测试文件，产品内只保留两份已有架构断言的等价迁移。不以弱化断言、改 workflow 或声明一般开发授权为 gate 批准来处理。

既有相关回归 **87 passed / 27 Windows-native skipped**；其余统一插件架构检查 **54 passed / 1 已通过案例 deselected**；六个产品树外本地验收通过。Ruff、三源文件聚焦 mypy 和文档检查通过。此处记录实施切点的本地证据；Windows 对应版本的 native 结果待取得。

实际代码报告分别归档为 `platform-adapter-code-review-ownership.md`、`platform-adapter-code-review-runtime.md`、`platform-adapter-code-review-data.md`，各自固定 M1a 三源 SHA256。代码结论只针对这些源码，设计文档的状态/实施记录更新不改变原冻结 R2 合同的评审证据。

综合实施结论：三视角无未关闭代码评审问题；本地实现责任人接受本切片的实现结果与本地证据范围。该接受不关闭 Windows native 待验证项，不接受 M1b/c，也不代表已经提交、合并或完成跨平台发布。

## M1b 后续实施评审

在 M1a 本地结果说明后，用户再次要求开发，主执行者说明继续 M1b，并在原专项 §8 补齐四方法端口、授权前后状态与失败边界。三个原 xhigh reviewer 对该窄设计分别核查，均无设计阻断；这次继续授权与接受只涵盖 M1b，不把前一次 M1a 审核扩大为 M1b 自动接受。

实际代码评审以产品树外 `m1b/before-*` 中的 M1a 三源快照为对照，避免把先前 M1a 或 M2 变化重复计作本轮开发。

| 视角 | 窄设计结论 | 实际代码结论 |
| --- | --- | --- |
| 职责与复用 | 四方法结构类型端口足够，无新 owner/state；可实施 | 已确认共享流程实际使用、原 sink 独占状态及公开兼容；无阻断或待整改项 |
| 运行与失败 | 必须保留原 probe 与 FileExistsError 作用范围；无阻断 | 已确认参数、图对象、标志/授权时点及原异常范围保留，无阻断 |
| 数据与兼容 | 保留原 receipt/图/flags，等价迁移授权字面断言；无阻断 | 未发现数据、兼容或库存问题；未新增 gate |

本轮原有相关检查 **141 passed / 27 Windows-native skipped**；产品树外故障合作验收 **10 passed**，无新增产品测试门禁。原生 prepare/publish 语句与 abort 的 AST 对照通过；不以 AST 或 fake 平台端口替代 Windows native 实验。源文件 Ruff、聚焦 mypy 与文档验证另按实际结果记录。

独立报告存放产品树外 `m1b/design-{ownership,runtime,data}.md`、`m1b/code-{ownership,runtime,data}.md`；每份代码报告固定本轮源码 SHA。Windows native 仍待验证，M1c 仍未授权实施；提交与远程交付状态以承载此变更的 PR/Git 记录为准。

综合结论：原三个 reviewer 的 M1b 设计核查与实际代码复核均无未关闭问题。实施 scope owner 接受本切片的本地实现及上述证据范围，保留 Windows native 待验证；不把原生平台证据未齐写成跨平台发布已完成。文档 9 项静态断言、相对链接及 diff whitespace 检查通过。


## 后续 Windows 原生证据（2026-11-05）

上述各实施切点的 Windows pending/skip 是历史结果，保留原文。后续对与 #863/#872/当前 main 逐字相同的五个 M1 模块及三份测试做了一次实际原生 suite：既有 Windows 27 项加一个树外真实部分删除重试场景，28 passed、零跳过/失败，Windows Server 2022 x64、项目 Python 3.11.15。首个启动器准备失败未执行用例，修正后运行及两份日志均保留；不虚称单次 dispatch 成功。

实际版本绑定、节点、局限及临时 ref 删除事实以[统一证据记录](materialization-platform-evidence.md#7-一次性-actions-执行验收与入口退出2026-11-05)为准；产品实现和原评审结论没有因此重写。限定 native 待验证项已取得对应证据，其余排除范围保持；未恢复或新增门禁。
