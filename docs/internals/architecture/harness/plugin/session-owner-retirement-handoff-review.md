# D1 Session owner 退役交接：三视角独立设计评审

## 对象与方法

- 日期：2026-11-04；设计阶段对象：[专项设计](session-owner-retirement-handoff.md) R1 → R2；用户后续授权的代码评审和验收另列于下文。
- 代码基线：main `886c1b2f73a61b0ab6c14bf62a4c8682776d7807`；Harness HEAD `4dcfd8bcf1545c59060a639e8d17568567e154ae`，完整 tree 均为 `73a5210e2121d2006813235e4a4a3bffa91fa903`。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；未核验方法远端。
- 设计阶段授权：用户要求继续 D1 第二切片专项设计及三视角独立评审；当时依据“系统环境图等重要工作件需要我评审”保留用户接受。用户随后以“确认，继续”接受 R2 并授权实施。
- R1 SHA256：`f349f329926fe1973d4913e3fcf615c99a63fede2d82884633e9347e2ab483dc`。
- R2 SHA256：`62369577dc54c0905162c919c8fc73fc2ccf5e6ba2205194423f153dda64a186`。

三位 xhigh reviewer 以空上下文分别核对方法、适用规则、固定 R1、原源码与测试断言，不读取本轮评审索引及其他报告。它们是独立技术评审角色，不替代用户或运行方的实际确认。R2 由原 reviewer 对变化路径定向复核，不称为新一轮全新隔离审核。

数据 reviewer 的完整 R1 初稿写入后，协调者告知了运行视角的测试映射建议及拟作的澄清；其先前已独立回报相同覆盖边界与无阻断结论，报告明确记录了该消息的到达时点和内容，没有读取他人报告。本文区分初评与后续协调，不把协调消息中的判断冒充新的独立发现。

评审重点：单函数职责是否值得下沉，Session 集成位置是否合理，是否重复 Graph/Registration/账本/租约机制，原锁/身份/失败顺序与两条路线能否共存，现有测试和未来验证是否被准确区分。物理视角检查同进程调用、原本地 journal、锁及平台差异，不设计新增部署节点或网络协议。

## R1 初评

| 视角 / reviewer | 结论 | 主要依据 |
| --- | --- | --- |
| 职责与复用 / retirement_ownership | 0 阻断、0 实质非阻断缺陷；可以提交用户评审 | 提取主体是完整的凭据到计划/结果交接；只读协议避免反向依赖，固定政策值均来自现有 Product 标签和错误分支；Session 位置有职责依据，非仅为绕开 scanner。当前范围不需另建 ARD |
| 运行与失败 / retirement_runtime | 0 阻断；1 项非阻断建议 RT-NB-1；可以提交用户评审 | 未封计划等待、已封重入、source pending 拒绝、原锁覆盖、分步写入与原后续释放均可保持；建议明确空计划测试与非空逐 family outcome 关联的覆盖差别 |
| 数据、兼容与验证 / retirement_data | 0 阻断、0 实质非阻断缺陷；可以提交用户评审 | 原 evidence/ledger 权威、三元键、无额外去重、排序和 repr/UTF-8 SHA、原前缀/错误及 committed.plan 遍历保持；管理包空调用库存和原 facade 可保持 |

完整 R1 报告及源码证据位于产品树外 `architecture-analysis/plugin-harness-audit-20261104/d1-retirement-coordination/`，分别为 `review-ownership.md`、`review-runtime.md`、`review-data.md`、`source-evidence.json`。受审 R1/R2 原文及指纹分别冻结，产品内不复制方法文本或完整逐行审查。

## 修订与综合检查

| 项目 | R2 处置与关闭边界 |
| --- | --- |
| RT-NB-1：RC-1 验证映射精度 | RC-1 明写低层 assembly 用例的 targets/outcomes 为空；RC-2 明写原并发用例验证两个非空目标/结果，但不逐条断言 family reference。增加树外至少两个 family、不同 receipts/outcome references 的基线/候选完整记录对比，覆盖先等待、后全量、逐项关联及部分结果重入。不新增 PR 断言或平台矩阵；原运行 reviewer 已确认该文档问题关闭，实际运行验收仍未执行 |
| 只读协议与原 source 副作用 | 明写协议仅限制新函数不调用 evidence 写入 API；原源仍加锁并使用 partial_tail=repair，可能执行既有尾部修复，不是无 I/O 投影或公开 read_only 查询端口 |
| 状态与权限 | R2 提升为 proposed，保持 not-started；初评通过不被写成 accepted 或实现通过 |

综合核对仍遵循原边界：共同算法处于 Harness Session 内部集成，管理账本包不主动执行 owner 报告；Coding 提供原 evidence 和固定政策，原 coordination lock 包住原位置；helper 的 None 返回包含等待，不成为 ready 许可；set succeeded 之后仍经过原 host/package/family/Instance 判据。fenced callback/registry、Graph 实际清理和错误重试不迁移。D1 首切片 assembly 不变；本轮不接受 D2 或整项 D1 的后续候选。

## R2 定向复核

原三位 reviewer 分别对固定 R2 完成定向复核，均未发现新增问题，可以提交用户评审。运行 reviewer 确认 RT-NB-1 在设计层面关闭；没有将拟运行的关联与重入验收写成已执行。

| 报告（含 R1 初评与 R2 追加复核） | SHA256 |
| --- | --- |
| `review-ownership.md` | `044b6aa3e3a230407e822f9e41be2abf8eefe63d998c87737370ccf8d3e09cab` |
| `review-runtime.md` | `420491ca058cba1c7c89b8e2db2e4f31149c3b944c6f94fbe26be4d8feed0beb` |
| `review-data.md` | `6c81d0361716c31ea0b9830216eca43b7673c15244f90181b68f922273edfa47` |

设计阶段结论：专项设计与内部独立评审完成，未关闭设计发现为 0；当时保持 proposed / not-started，提交用户评审环境图与关键合同。用户随后接受 R2，当前本切片按该合同实现，不宣告整项 D1 完成。

## 设计阶段验证范围

设计阶段只有三份架构文档发生变化。9 项静态文档断言、变更文档的仓库相对链接和 git diff --check 通过；15 个相关源码/测试文件 SHA 与冻结基线一致，产品源码、测试、工作流和门禁未修改。

各 reviewer 只做静态源码核查与场景走查，没有运行 pytest、native、产品 import、异步或模型调用。原测试的存在和原代码的幂等逻辑，不等于 R2 提取后的行为、逐 family 结果关联、部分写入续跑或平台原生已被验证。实现阶段依专项设计进行受影响范围验收，结果另列于下文；没有付费 Goal 试验或性能改善声明。

## 用户接受与实现范围

用户在固定 R2 及三视角复核结果提交后回复“确认，继续”。接受范围为 R2 的环境与职责、单函数提取、Product 固定政策、原锁/错误/身份/释放合同及其验证边界；不扩大为 D1/D2 后续候选的接受。本地实现只新增 `harness/session/_plugin_retirement.py`，原 Coding `_ensure_owner_retirement_plan` 薄委托并保留固定报告政策和错误 factory。原控制流、状态权威、格式与 gate 不变。

## 实际代码的三视角独立评审

原三位 xhigh reviewer 分别对固定实际代码开展独立审查，没有读取其他代码报告、修改产品或运行产品测试。代码结论单独基于实际差分和原源码，不把设计通过直接当作实现通过。

| 固定实现输入 | SHA256 |
| --- | --- |
| `src/loushang/harness/session/_plugin_retirement.py` | `34f6498f85e0f39d13b0e7aaac4c69699a80791b5869997775d8a803f055cbca` |
| `src/loushang/coding/_plugin_lifecycle.py` | `051d5f64dab32496d1bb260daac994ceaa78cb8a79cb4f2b19791829e9880f4b` |

| 视角 | 结论与独立证据 | 树外代码报告 SHA256 |
| --- | --- | --- |
| 职责与复用 / retirement_ownership | 无发现；单函数与薄委托符合 R2，协议/固定 policy 不产生新 owner，原 Product、管理包、Graph、lease、fenced 边界保持 | `code-ownership.md`：`b12f7358ea7f66e60ebbdc5d7c85f50c11553d81bcb4eba192e3f21a49c29a9a` |
| 运行与失败 / retirement_runtime | 无发现；等待/重入、三个错误分支和其时点、原 source/ledger 异常、None 含义与后续收尾保持 | `code-runtime.md`：`951e3cf14196c02a13d65a97dae7986433b7bc19f85371c8031dfd544376aa47` |
| 数据与兼容 / retirement_data | 无发现；三元键和逐 family reference、原 repr/UTF-8 SHA/前缀/结果/attempt 保持；显式 self/参数/policy 适配后函数体 AST 与原文一致；管理包 commit_plan/record_outcome 空库存、原 scanner 和 gate 未改 | `code-data.md`：`891d81ddacf1e595789d45cf901e61eae0e8818febca03781b1c1115d54ef35a` |

代码审查冻结输入在运行验收结束后再次核对一致。其它原生命周期方法的 AST 保持；测试、工作流、gate、原 evidence/ledger 与 fenced/Session 清理源码均未改。当前 owner map 只新增本切片已实现职责的链接与说明，不声称其它候选完成。

## 实施验收与限制

| 验证 | 实际结果与局限 |
| --- | --- |
| 原退役、owner evidence、Instance/Package 与五项受影响架构检查 | **121 passed，392.20 秒**；显式 Harness lane PYTHONPATH、私有临时根、not live / not requires_host_runtime / skip-host-runtime；管理包惰性、核心依赖、DAG、Session barrel、精确构造库存均保持 |
| 树外调用轨迹与错误 | **25 passed**：12 个分支/异常场景加 13 个故障位置；完整调用前缀、原异常类型/消息/code 与故障对象身份一致。包含缺三元映射的 KeyError 和已封计划时仍有 family 的重入 |
| 树外真实 family 与 journal 验收 | **7 passed，19.32 秒**：两 family、三 receipts、两个不同 outcome refs；先关闭仍不封 plan，最后关闭后逐 target 保持原所属 family outcome。正常路径及 plan/outcome 前后六种受控失败，用新 reader 冷读写入前缀，再调用原 lease/reconcile 续跑；最终 RETIRED，重复操作不增记录；旧/新四份完整 JSONL 字节一致 |
| 夹具问题与修正 | 首次树外 InstanceRevisionRef 夹具漏 plugin_id；修正后 25 项通过，真实场景因手写非法 scope 被原检查拒绝。改用原 resolver 后仅继续 7 项真实场景，全部通过；未改产品、原安全检查或放宽断言。原日志保留树外，没有将这些夹具错误记录成产品缺陷 |
| 静态检查 | 两份实现 Ruff/mypy、包依赖事实、文档断言/链接与 git diff --check 通过。`implementation-proof.json` 记录原方法、外层锁/收尾等 AST 对照；加载来源和源码 SHA 单独核对 |

原始验收脚本和日志位于前述树外归档，分别为 `local-acceptance/test_retirement_equivalence.py`、`focused-regression.log`、`equivalence-traces-and-fixture-failure.log`、`real-handoff.log`；25 项与 7 项是分次执行，不声称一次 32 项全绿。夹具先前错误不影响本次产品代码输入，最终代码评审指纹没有变化。

本机 Linux 离线验收不证明 Windows/macOS 原生、完整进程崩溃/断电或任意 append 结果未知；受控报错后新 reader 重开与重入也不等于跨文件事务。没有重复付费 Goal 或全仓回归。广泛检查路线与本地聚焦结果分别记录，不把未执行的路线写成通过。

当前结论：R2 设计已由用户接受，本切片本地实现、受影响验收及三视角代码审查完成，未关闭代码问题为 0。上述验收发生于提交前，远程交付由对应 PR 记录；更广泛的退役/租约协调与 D2 收敛仍需分别评估，不以本次完成替代。
