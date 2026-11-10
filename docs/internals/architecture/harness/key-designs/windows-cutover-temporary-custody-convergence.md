# A115：Windows切换临时目录custody归原Resources

- Authority: bounded implementation under COD-RESP-GOAL-002；完整Goal仍partial。
- Design status: accepted direction；实际三视角及实施owner接受另见树外记录。
- Implementation status: implemented，限本程序及下列验证范围。
- Owner: 原Resources Windows epoch cutover；方法为本地clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

原Code的完整ACL临时root程序现在由既有windows_epoch_cutover私有contextmanager
承接。3个真实调用仍是Source投影及pre-B空projection/pointer目录；Code公开CM
签名/文档、enter时平台/前缀短路guard保持，只绑定原filename和诊断label再with/yield。
同一个原程序原已供3处共用，不报3算法去重。无新manager、Protocol、状态表或
Code IO回调；原PinnedAuthority、ACL及native primitives直接复用，不重复记收益。

Core保持token生成时点→ACL→固定parent→create child/记录identity→可选file/
记录identity→write/flush/close→目录flush/visible→yield；原4层lexical清理及所有
短路不变。empty bytes仍创建file；file identity在ACL验证前记录。退出核file identity/
unlink/flush、finally关闭child、无前错才核child identity/rmdir/flush，最后parent.close
及ACL退出。原_remove_created_epoch会重开/改错误与空目录合同，不能替代本程序。
短写循环直接复用已有Journal.write_all；原<1与共享<=0在native os.write:int返回
合同等价，保memoryview/剩余切片、调用序及OSError文案。其余完整体逆纯Name/label
绑定及展开该循环后AST同原，其它Code/Core非import定义AST同。

原私有_PROJECTION_NAME改为enter时纯字符串绑定；不承诺yield中热改模块常量或
替换私有OSError/global alias的兼容。新增CM层的异常图须以运行证据核实，不能
只凭迁移AST；公开值/接口、磁盘名和原诊断内容保持。

完整成本Code430→359（−71）、Core466→557（+91）、系统+20，是职责迁移加短写
算法复用，非系统净精简。当前Coding430源112878行、系统1969源648184行（含GUI
Rust/TS），较Goal−24877/+13390，距15K97878；其余1967源及13资源SHA同。

旧117受控观察与新同117全量回放均过：5正常/112预期拒绝，逐事件顺序、yield、
累计write bytes及异常args/notes/cause/context/suppress完整比较。覆盖3种payload、
原成功trace各事件按次故障、短写/零/负返回、身份变化、body StopIteration/
GeneratorExit/CancelledError/KeyboardInterrupt及多cleanup异常。Fake ACL/FD/IO
只记录效果，不是物理Windows或FD/残留树普查，也非所有并发/内核故障证明。
持久探针只把模型Path换为host-independent PurePosixPath；原实物同117再次通过，
未重录期望，候选同117亦验证。原5个POSIX消费者在旧/新通过；候选另165导入边界
通过，22个Windows-native项本机跳过，不计native通过。两源mypy/Ruff通过。

显式probe_*及117条JSONL固定旧观察，不进入默认发现/新增PR gate。来源守卫在
树外取实际两源SHA，持久版核两实际模块origin，不钉未来实现SHA。兼容静态脚本
曾因实际已安装仍断言应为old而失败，修正状态假设后通过，不是Product偏差。
完整旧源/候选、成本/逆AST、JUnit及三视角在树外
`coding-convergence-continue/a115-candidate-selection`；其它Hosting/AI覆盖率、构造/
Session及P1–P4欠账不关闭。KD003未实施，KD011/A33仍待用户且未采用。
