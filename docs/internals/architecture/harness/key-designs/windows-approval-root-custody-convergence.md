# A120：Windows审批目录创建与关闭custody归原Resources

- Authority: bounded implementation under COD-RESP-GOAL-002，完整Goal仍partial。
- Design status: accepted，三个实际视角及实施owner有界技术接受。
- Implementation status: implemented，验收范围及限制如下。
- Owner: 原Resources Windows private-tree IO；Code保产品/平台准入。
- Method: clean local archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

原Code private Windows helper的53行包含完整nearest-existing-ancestor查找、两个ACL、
逐层create/race-reopen、leaf选择、created-only父目录flush、首祖先identity前后比较
及全部句柄的ExitStack关闭。它现在由原`_private_tree_windows`一普通函数执行，
无新manager、state、Protocol、profile或Code IO回调。Code保Path/absolute前置检查
及原error、product-private目标、max_missing8与诊断label；平台dispatch、POSIX
私有目录准备/验证、兼容别名、原Resume与composition消费者及其政策保持。

已有Product private-chain API要求已私有root，使用完整PinnedAuthority祖先与额外
validate/visible/输入检查，其close-loop故障策略也不同，不能drop-in。既有
private_windows_directory会验证ancestor ACL、改变退出语义；PrivateWindowsTreeIO
create也有不同flush/custody合同。不能为本片给这些API加flags统一。share_delete
不是差异理由：旧代码省略参数而默认就是False；本片继续省略，不声称修复native行为。

原while先exists，再parent/depth短路；最多8missing，9拒绝仍早于ACL。missing时
不验证原existing ancestor ACL；零missing只验证leaf ACL。parent FD在fstat前登记；
existing.stat的dev/ino仍是两次独立调用；每轮先求值完整右侧tuple再比较，首次
identity不符即报错，不再创建或最终复查。未缓存或加逐child检查。
created后才flush原parent，race reopen不flush；失败不回滚已建目录或修复已有目录。
仍用with(ExitStack,privateACL,leafACL)：leafACL先退出，再privateACL，最后stack
反序尝试所有close，保原清理错误覆盖/cause/context，不改为stack.enter_context。
最大深度和label只绑定原纯政策，不新增未请求的runtime/rooted admission。

Code−48/Core+59/系统+11，非系统净减；原Resume与composition消费者本来一算法，非三份去重。
全部原Core其它定义和Code其它非import定义/公开shape同；绑定8/label后完整native
body AST同。新增私调用帧和native全局patch位置是实现变化，不承诺偶然私FQN。
Coding112625/系统648278，距15K97625，完整P1–P4与系统总体简化仍未完成。

证据在树外`coding-convergence-continue/a120-windows-approval-root`：完整双源起点/
候选、全生产frame、三设计及实际视角、原期望/模型与JUnit。原9消费者通过；原树
尚未替换时捕获旧完整AST观察，再用原实际module重放85过，原期望不重录。模型
受控Path.exists/stat及native ACL/open/flush/close，不写入主机`/approval`目录，不证明Windows
内核ACL/真实FD普查；以POSIX-host运行Windows边界程序，非原生Windows结果。
实际联合281过（Resume9+Hosted22+导入165+同85模型），2skip分别是原Windows
Hosted用例与capture-only占位；两条原record_property/xunit2 warning保留。仓库
持久85独立重放通过，旧85对象等值压紧，不重录期望；244行probe与87行/96497B
固定JSON共331测试行另计，显式probe不加入默认发现或PR gate/平台。

双生产源Ruff/format/mypy通过，docs9与当前依赖图通过；430逐文件行数/SHA及
28组量重计，另外1967生产源/13资源同SHA。全部原Core其它声明、Code其它非import
声明和公开shape保持，8/label绑定后完整操作逆AST同；不新增C50/C54例外。check
plan未选AI，不重跑已有覆盖率失败；先前已关闭C50库存不重报。完整方法/原始记录/
失败边界在树外，实施owner接受仅本完整IO归位，Hosting/AI/构造等欠账及KD003/
KD011/A33原边界保持，非完整Goal完成。
