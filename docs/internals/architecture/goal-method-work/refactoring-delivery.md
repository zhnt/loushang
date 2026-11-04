# Goal共享重构交付记录

Authority: descriptive。交付范围为用户已接受GMW-RF-001 R2的S0–S4a及Session协同专项R2；远程交付状态以[PR #852](https://github.com/zhnt/loushang/pull/852)为准。

## 结果

Harness拥有原Session的联合受理、任务身份、操作级配置、调用限额/期限、回复来源核对和资源关闭边界；HarnessWork继续拥有原Goal/Work、候选选择、验收和运行事实。共同批次规划与回复交接已收敛到HarnessWork；Method保留现有权威，Coding保留编码工具、任务/profile/方法内容及兼容装配。没有新增第二个Work kernel、输入队列、预算账本或harnessmethod包。

既有SDK/托管/委派路径使用共同机制。已有持久Session可显式attach有限calculator规划profile，保留历史、模型、工具、retry/compaction基线；兼容后端按对象复用。旧公开入口、记录codec、物理路径/锁、policy与提示字节保持，旧记录不迁移或重放。旧global setter回退删除；缺执行绑定明确拒绝。

普通输入、preflight、排队输入及direct/trigger应用输入经过原Session受理。规划隔离期间即时输入在写入前明确拒绝，原身份可在收敛后显式重试；next_turn/steer/follow仍走原队列。合法/new当前Session回调不因转换尚未结束而误拒绝，旧上下文仍失效。查询及公开取消调用只等待自身finally，不join调用方外层关闭Task；真实清理失败保留原owner和父依赖。

## 验证

运行代码固定提交d804165c610cab6886ac5983a631437ba1e09f48。[CI run 968](https://github.com/zhnt/loushang/actions/runs/41638738719)整体success，17个job成功、13个按原策略跳过：

| 模块 | 实际结果 |
| --- | --- |
| Coding四分片 | 4184 passed、21 skipped |
| Harness四分片 | 5993 passed、121 skipped |
| Agent（含原examples） | 169 passed |
| Work / HarnessWork | 187 / 54 passed |
| architecture / docs | source facts与原文档检查通过 |
| Resume烟测 | Ubuntu、macOS、Windows原三平台检查通过 |

本地Harness Ruff及784源文件mypy通过；AI937项、90.77% coverage与原Agent167项在源码/测试树未变时复用。首轮失败的retry、/new回调、子执行取消及后续registry连带失败已修正，原失败测试未改；12项原用例与39项runtime/router补查通过，完整CI随后通过。没有扩大、重启或修改任何PR门禁。

固定旧fixture、新旧selector差分、旧reader读新Goal/Work及规划proof、实际来源隔离、普通Session复用和两入口业务对照均有切片记录；[最终三视角评审](refactoring-final-review.md)及[CI修正复核](refactoring-ci-regression-review.md)记录发现与关闭。三视角源代码结论不代替这些实际运行结果。

## 边界

本轮两入口等价覆盖相同有限profile的正常完成与无效提案后暂停；另验证了客户端waiter取消、撤权、关闭失败和原server重试组合。它们不证明所有native故障、deadline/权限交叉组合。旧reader对S4的6份新proof来自相邻本地Transcript，不冒称独立hosted Transcript已被同一脚本覆盖。

普通Session首profile仍明确拒绝不兼容工具/扩展、provider window、非持久Transcript或原Work后端配置；不能通过重新attach非空历史重建预算继续旧执行。通用自然语言规划器、自动Method组合、日常TUI新菜单、真实lmux Goal wire与跨进程自动续跑均不在本次重构完成口径。

完整本地check-changed曾因真实回归和同步main主动中断，不标为全部本地绿；最终受影响模块以修复提交的完整CI及对应本地专项为证据，未为补一条命令的字面结果重复付费或重复线上试验。
