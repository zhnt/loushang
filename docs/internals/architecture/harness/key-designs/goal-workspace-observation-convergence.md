# Goal工作区完整观察职责收敛 A189

状态：本批接受；完整Coding重构仍partial。2026-11-14。

原[interactive Goal](../../../../../src/loushang/coding/adapters/interactive_goal.py)的workspace_snapshot和
[repository task](../../../../../src/loushang/coding/adapters/_goal_repository_task.py)的inventory
分别调用原[Workspace Git家族](../../../../../src/loushang/harness/workspace/git.py)的两个固定完整观察入口。
Code保公开FQN/签名/返回类型及GoalError、预算和消息。无mode开关、泛型端口、IO回调或新状态owner。

bounded合同保git bytes/stage识别、submodule排除、仅非零返回触发fallback、原walk顺序及
排除名、10000文件/128MiB预算、resolve后拒外链、link/missing/hash值与原异常传播。
unbounded合同保check_output、默认decode、sorted去空集合及原link/file/missing顺序，
不添加预算/fallback/外链拒绝。原repository digest另有领域消费者，原样保留。
二者不能强并为一种算法。原capture会写index/artifact；SnapshotEvidenceStore准入不同。
原settled_io和owned task join仍直接复用，不重复计为本批收益。

两个完整程序原64/20行退出Code。实际三源Code672→619、115→97，共−71；
Core170→272，+102；系统+31，raw=uniform，含导入、公开接口和全部profile成本。
这是native观察职责归属改善，没有第二算法/authority退出，不称系统净精简。
原8/2个Code定义及8个Core定义AST保持；两整程序逆profile和纯digest展开AST同。
实现模块/栈帧及私有全局hotpatch位置改变，不承诺私有模块全局任意改写兼容。

原四模块tests/coding/test_interactive_goal.py、test_repository_goal.py、
test_hosted_repository_goal.py与tests/harness/workspace/test_git.py：旧118过646.58s，
冻结三实际源码后同118过745.20s，0fail/error/skip。无test/fixture/probe/gate变更。
5模块父进程phase/PID路径/SHA和19递归code字段守卫各236checks；旧48/actual50声明。
Ruff和project mypy三源通过。无子进程native审计或逐点预算/权限/编码/读写race故障注入；
不增加原来没有的原子快照保证。测试基线与实际重放不累计为236不同覆盖。

源证据、冻结manifest、逆AST证明、XML与三独立设计/实际审阅存树外A189运行记录。
现Code110399/Harness364480/HarnessWork8332，C12为25源6858；完整P1–P4仍开放。
