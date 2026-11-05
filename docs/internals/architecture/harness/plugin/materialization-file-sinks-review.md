# M1c 文件写入与复用：三视角独立设计评审

## 对象与证据

- 日期：2026-11-04；对象：[专项设计](materialization-file-sinks.md) R1 → R2。
- 用户同意先做文件写入/复用专项设计、三视角评审；重要系统环境图等工作件先提交用户。随后用户对 R2 回复“同意，继续”，授权实施；设计与代码审查分别记录。
- 源码基线：main `8b7e0358cbe79425757544154d5b36766771a410`；设计阶段未改产品源码。后续三份实现源码见下文，测试、工作流与门禁未修改。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核验远端。
- R1 SHA256：`fce8b2226dd0ce16928a0fb5ac8cab2ab63fbdfae6ba6a7d80d095ceb924c85a`。
- R2 冻结评审/接受版本 SHA256：`afac0bcba800be5f4b308735f72dd37cfd55d8551c99c02062d9472318070f2f`；其后状态与实施结果更新不改写该历史对象。

三位 reviewer 以独立空上下文、xhigh 推理启动；各自读取适用规则、方法、源码及现有合同，不阅读其他评审报告，不改产品或设计，不运行 pytest、产品异步代码或原生实验。原三位对 R2 仅按变化路径复核，不把这次定向复核称为另一轮全新隔离审核。

本轮问题：两个共享 sink 和一个窄原生写端口能否消除共同决策的复制，同时保留原 Transfer、tree owner、平台句柄及发布授权边界。关注职责复用、运行失败、数据兼容三个视角；部署只核对同进程、原 Store 锁/pin 和原生 fd 的物理路径，没有新增部署节点或远程通道。场景来自用户的复用/优雅/平台下沉要求与真实调用者代码，AI 审核不冒充额外用户或运营方确认。

## 独立评审结论

| 视角 / reviewer | R1 结论 | 主要依据 | R2 状态 |
| --- | --- | --- | --- |
| 职责与复用 / file_sink_ownership | 0 阻断、0 需修正缺陷 | 共享 sink 拥有公共规则；Writer 只管已开句柄；原 tree owner 保留 active/next；完成回调必须收到实际返回对象 | R2 定向复核通过，无新增实质问题 |
| 运行与失败 / file_sink_runtime | 0 阻断、0 需修正缺陷 | 计数、短写、摘要、fstat 与 OSError 边界、flush→close→callback 均可保留原语义；原 close/构造失败弱点没有被冒称修复 | R2 定向复核通过，无新增阻断 |
| 数据、兼容、库存与验证 / file_sink_data | 0 阻断、0 需修正缺陷 | 私有构造只由原平台消费；公开与持久合同不变；按此方案无需放宽现有精确库存；模拟轨迹与 native 证据区分 | R2 定向复核通过，无新增缺陷 |

独立报告与 R1/R2 冻结原文、原源码 SHA 和 AST 证据保存在产品树外 `architecture-analysis/plugin-harness-audit-20261104/m1c-file-sinks/`：`review-ownership.md`、`review-runtime.md`、`review-data.md`、`source-evidence.json`。规范化唯一的 owner 类型注解后，两份原 ReuseFileSink 的完整类 AST 一致；这只证明该源码差异，不证明未来组合代码已经通过运行验收。

## 综合修订与关键决定

主执行者对 R1 补两项非阻断澄清：

- S1：原图把 Transfer 对 tree 和 file 的调用合并标注。R2 分别画出 tree.open_file、返回的 file.write/finish 和最终 tree.finish；file_finished 只推进原 active/next，不自动发布整树。
- S2：R2 明确普通 sink 多一个短寿命 Writer 和完成回调，额外空间每活动文件 O(1)，不宣称性能零成本或已测提速。

R2 没有修改接口、原生观察或错误顺序。建议接受的范围仍是两个共享 sink、一个窄写端口、两个原平台 Writer：不建立第二 owner/stream 框架，不合并源/目标两次独立内容校验，也不移动 tree abort、GC 或发布授权。

## 未验收项与实施条件

1. 设计可相容不代表代码已相容。实施后必须核对实际 callback 类型/对象、原生调用点、计数和摘要状态及完整 Transfer/tree owner 的组合链。
2. 已有端到端 reuse/abort 用例不能代替短写、不前进、fstat/flush/close/callback 分别失败的精确状态轨迹；新增本地轨迹留在产品树外，不自动扩 PR 门禁。
3. 文件 close 抛错后的原句柄不确定性、构造失败窗口属于原机制边界，本次不宣称必定关闭或安全重试。若新增此保证，须另行设计与故障证据。
4. Windows native 与对应版本的失败/关闭行为仍待实际证据；Linux、mock、静态审核和其他三平台续跑 CI 都不能代替。暂停路线保持，不借本设计恢复门禁。
5. 公开接口、error code/消息、原 manifest/receipt/journal 路径与格式、root pin、锁及授权保持；不要求清空用户状态或新 workspace。

## 当前结论

R1 三视角独立审核无阻断；三位原 reviewer 对同一固定 R2 的图示/成本澄清定向复核，均无新增实质问题。职责和数据 reviewer 在复核时指出评审记录链接尚未创建；该导航整合待办已由主执行者生成本文件并核对链接后关闭，不涉及接口修订。

设计阶段的 9 项静态文档断言、四份变更文档的仓库相对链接与 `git diff --check` 通过。当时 R2 hash 与原四份源码 hash 均复核一致，尚未执行产品测试、原生平台或性能实验；没有测试/工作流/门禁变更。

以上为实施前结论：专项设计与内部评审完成后提交用户评审环境图和关键合同，当时保持 proposed/draft、not-started。用户后续接受 R2 并授权实现，结果如下；不宣告整个 M1c 或跨平台交付完成。

## R2 实施与代码审查

实际实现为一个内部 `_file_sinks.py` 与两平台 FileWriter。原私有 FileSink 名称保留为 import alias，callback 仍把实际 sink 传给原 tree owner；平台 Writer 只有 descriptor/初始 identity。两平台原 tree owner 仅 open_file/_create_file_sink 接线改动，其他 16 个方法和其他保留定义 AST 不变。Transfer 源端校验、读取核验、GC、journal、原 root mode、授权及删除没有变更。

原三位 xhigh reviewer 各自独立检查实际三源及基线差异，不以设计通过代替实现审查、不阅读其他代码报告；代码阶段仍持有前期设计背景，不称为三次全新空上下文审查。

| 代码视角 | 结论 |
| --- | --- |
| 职责/复用 | 无实质问题、无阻断；共同规则唯一，Writer 不拥有 entry/计数/摘要/finished，原 tree owner 权威保留 |
| 运行/失败/原生安全 | 无新增缺陷、无阻断；write/fstat/flush/close/callback/abort 顺序符合 R2，原创建原语和清理策略保持 |
| 数据/兼容/库存 | 无实质问题、无阻断；原公开合同、消息、callback 类型/对象、alias 与 native 调用角色保持，无库存或门禁扩放 |

代码评审固定版本如下，独立报告为产品树外同目录的 `code-ownership.md`、`code-runtime.md`、`code-data.md`：

| 文件 | SHA256 |
| --- | --- |
| `_file_sinks.py` | `d820047064fdd9aaa7bcdc740ce68f517c34b7901f414a56822804a2fb3f2ecf` |
| `posix_materialization.py` | `26ca6b162e01afe012920f416086449b95789c5d743a5747d32baa3ac6f09096` |
| `windows_materialization.py` | `bc107718d861e4880df1ec14e33324ad0552e377fb24cfb3646299633478a2f2` |

实施者验证：

- 三源 Ruff 与聚焦 mypy 通过；包依赖事实检查通过。
- 既有 POSIX/Windows materialization、verified-tree transfer、PLC9B 与统一 Plugin 架构合同：153 passed、27 Windows-native skipped，95.88 秒。
- 树外 `local-acceptance/test_file_sinks.py`：68 passed，2.23 秒。对比原两平台 sink 与新实现的错误、调用先后、计数/摘要/flags 和 owner 推进；覆盖 bytes/空块/超长/短写、不前进、部分写失败、fstat/身份/link/reparse、flush/close/callback 失败、abort/重复完成，以及原 reuse 工厂和 foreign callback 拒绝。
- pytest 首次即在沙箱外执行，保留非 live/host-runtime 选择及容量保护，运行目录放在本任务产品树外磁盘路径。补充验收不进入 PR 门禁；模拟 Windows Writer 不等于 Windows native 通过。
- 初轮 runner 在 pytest 配置前先加载了控制工作树，补充验收因此找不到新增模块。该轮结果不作新实现证据；后续固定 `PYTHONPATH` 为当前工作树 src，三源实际加载路径和哈希逐一核对，记录为 `loaded-source-proof.json`，只计上述正确来源的重跑结果。
- 补充验收初期的 Windows stat stub 缺少真实 stat 必有的 st_mode，已补齐夹具并明确核对成功场景及原 fstat 异常；产品实现未因此修改。

当前为本切片本地实现与代码审查完成。Windows native、原关闭结果不明机制的修复、tree abort/删除收敛及性能测量仍不在已完成范围；没有将聚焦结果宣称为整个 Harness/Hosting 全量回归通过。


## 后续 Windows 原生证据（2026-11-05）

上述各实施切点的 Windows pending/skip 是历史结果，保留原文。后续对与 #863/#872/当前 main 逐字相同的五个 M1 模块及三份测试做了一次实际原生 suite：既有 Windows 27 项加一个树外真实部分删除重试场景，28 passed、零跳过/失败，Windows Server 2022 x64、项目 Python 3.11.15。首个启动器准备失败未执行用例，修正后运行及两份日志均保留；不虚称单次 dispatch 成功。

实际版本绑定、节点、局限及临时 ref 删除事实以[统一证据记录](materialization-platform-evidence.md#7-一次性-actions-执行验收与入口退出2026-11-05)为准；产品实现和原评审结论没有因此重写。限定 native 待验证项已取得对应证据，其余排除范围保持；未恢复或新增门禁。
