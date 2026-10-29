# HW-KD-003 / ARD-019：独立三视角评审与关闭记录

## 结论与范围

- Authority: descriptive — review evidence；日期：2026-10-28。
- 对象：[HW-KD-003](fact-retention-replay.md) 与 [ARD-019](../../decisions/accepted/ARD-019-work-facts-and-transcript-sharing.md)。
- 固定 R3 首轮独立评审完成，形成两项运行语义阻断；R3.1 修订后，原三位评审者分别完成相关范围的关闭/协同复核。
- 技术结论：**三视角均无剩余架构语义阻断。** 不是实施验收，不等于所有开放项关闭。
- 接受登记：用户于 2026-10-29 在收到 R3.1 及评审结论后回复“可以，需要更新文档吗？”。设计已按 ARD-019 的接受范围转为 accepted，实现仍为 not-started；实施前条件保留，本次只更新文档。
- 源码基线：`5eadeb91ccee4e69618d99cf531f94739c76a453`；分支 `docs/work-facts-contract`。本轮只有文档修改。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核验远端最新状态。

## 独立性与固定对象

三位 agent 均使用独立上下文、xhigh 推理设置；先核查方法、源码和文档哈希，不读取其他评审者报告，不将文内历史 R2 自审当作判断依据。首轮完成后由主实施 agent 汇总修订；关闭复核仍由原评审者针对固定 R3.1 进行。无 agent 修改产品代码或候选文档。

| 视角 / reviewer | R3 首轮结论 | R3.1 关闭/协同复核 |
| --- | --- | --- |
| 职责与复用：`facts_r3_ownership` | 无阻断；默认机制归共享层，资源装配不等于 Product 重复实现 | 无新增职责阻断；确认机制、通用等待与收尾未被推回 Product |
| 运行与失败：`facts_r3_runtime` | needs_revision；RT-01、RT-02 两项语义阻断 | 两项均在合同层关闭，无剩余阻断 |
| 数据与兼容：`facts_r3_data` | 无 P0/P1；两项 P2 为已识别的实施前风险 | 文档关闭条件已补齐，无新增阻断；实际兼容和保留验证仍待完成 |

| 冻结版本 | HW-KD-003 SHA-256 | ARD-019 SHA-256 |
| --- | --- | --- |
| R3 | `a5af816594aa055589d1f82ec77cbace2bd7a28b7d121f1dff49949200061203` | `6bd1b805da54fc2fb4f144860b0998b3aabd8c3a3a75e72376a75c536a1f3f28` |
| R3.1 | `ec0d360986919d3f08cedd2f8dde426396532a7261583859277a17cf14747d3f` | `f0dbbab3f10297d307f018cd3a77a65b4ce4c6080df36d3abd5342f72eae854c` |

完整冻结对象、manifest 与六份原报告留在产品树外
`/home/dev/lsspace/architecture-analysis/work-facts-review-20261028/`。
首轮报告为 `ownership-review.md`、`runtime-review.md`、`data-review.md`；复核为对应的
`ownership-closure-R3.1.md`、`runtime-closure-R3.1.md`、`data-closure-R3.1.md`。
上表哈希针对评审冻结对象；当前工作件随后补入评审导航、接受状态与接受范围，并同步 ARD 路径及 Current/Target 差异；运行、数据及职责语义没有再改。原冻结副本保留，不覆盖评审依据。接受日期晚于技术评审日期，两者分别记录。

## 发现与处置

| ID / 等级 | 证据与影响 | 修订与关闭依据 | 当前状态 |
| --- | --- | --- | --- |
| RT-01 / 阻断 | [runtime](../../../../../src/loushang/harnesswork/runtime.py) 在 terminal append 前更新内存 run；旧 get_run 可能返回 completed，但未得到追加确认。现有错误标记只使取消观察不可用，不能自动支持通用确认 | KD §6.5 区分旧活体观察与新确认；backend append 抛错后新确认视图不可确认，不能被后来成功覆盖；保留最后 ACK 截点，writer 停止后受控冷读，不自动重发或虚构 fsync/停写。EV-03 补写前/写后失败，ARD 第 8 条同步 | 运行 reviewer 对固定 R3.1 关闭；源码尚未实现新合同 |
| RT-02 / 阻断 | 终态前必要交接与取消/超时重叠时，等待、失败及迟到回调缺少组合规则，可能迫使实现者自行决定可见结果 | KD §7.1：默认交接在原执行范围，正常缺失走原异常失败，已受理取消沿原控制裁决；追加异常导致确认不可用；迟到不发布到终态 Work；原 owner 保留未完成清理凭据。EV-16 覆盖组合 | 运行 reviewer 关闭；职责 reviewer 确认未新增服务或把通用清理推回 Product |
| DATA-R3-01 / P2 | 旧 codec 可能接受 payload 内新字段但不理解新合同；新增外层字段又可能导致整份日志拒绝。版本号本身不保证兼容 | KD §8 增加 reader/历史/混写/未知版本/回退矩阵和失败范围的冻结要求；选定 schema 未验证前不得启用新格式 | 文档处置完成；实施前风险保留，未声称旧 reader 已兼容 |
| DATA-R3-02 / P2 | 跨进程逻辑名可能绑定错物理根；留存提前终止若不可读，重开者仍可能看到旧承诺 | KD §9 明确原资源绑定、冻结承诺的可读位置，以及到期/提前终止/非预期缺失的区分；列出五条关闭场景 | 文档处置完成；持久表达与实际验证仍待实施前关闭 |

另采纳两项澄清：Transcript writer lease 不为 Work JSONL 提供多 writer 保护；“正文引用”仅在具备相应来源能力时使用，无该能力时保留最终内容内联。

## 最终分工与协同结论

1. HarnessWork 提供缺省记录、默认事实保留、通用 Session 映射、状态投影、查询与新合同的确认判据；普通 Work 不必自定义策略。
2. Product 绑定执行/存储资源，选择策略及允许覆盖范围，控制保留寿命；领域适配只补业务依据和验收解释。
3. 标准来源交接、等待和收尾归共享集成；领域专用来源由领域 executor 负责；取消继续走原 Work 控制路径。
4. 通用来源读取仍复用 Harness 公共能力；codec 留在所属记录组件内部，不增设审计、重放或共享 Transcript 常驻服务。
5. 状态观察、日志确认、交接完整性、当前目标验收分别有依据；不可用时如实表达，不互相代替。

本次评审没有推翻既有 Goal 双组件、Work 单引擎、Product 资源 owner 或原 Transcript/Blob 权威。跨 scope 设计接受由 ARD-019 登记，scope 入口与 gap ledger 已同步；设计接受不改变 Current 代码事实。

## 验证边界与实施前事项

评审为静态源码检查和场景走查，未运行模型、并发、故障注入、掉电或性能实验；EV-01…16 是后续验证义务，不是通过记录。没有新增 PR gate。

仍须在实施前冻结：默认/策略与来源 API/schema、旧 reader 能力矩阵、持久来源绑定与留存承诺、消费者迁移范围、读取入口映射。不能因“无架构语义阻断”把这些事项自动标为完成。后续若改变默认捕获、确认失效规则、取消组合或数据归属，需重查相关视角。

文档验证采用现有静态检查与仓库链接检查；产品代码未改，不以运行产品测试替代架构评审。
