# 集成CI回归修正

Authority: descriptive。PR #852首轮提交eddebb704的完整模块回归发现三个窄检查未覆盖的兼容问题。本记录不把此前源码评审无阻断等同完整回归通过。

| 回归 | 修正 |
| --- | --- |
| capture_continue_run在原retry owner调用前创建Task，提前续跑并绕过原schedule注入口；4项原retry断言失败 | 捕获只保留调用和作用域，Task在原callback被调用时才由原Host创建；unbound沿原schedule接口。原retry/compaction/summary状态通过默认兼容的AfterTurnPolicy回调进入Goal busy判据，不让Goal抢重试等待窗口；原续跑本身不等待自己的recovery flag，无第二driver |
| immediate输入的require_current将合法/new withSession回调中的pending transition也拒绝 | 普通即时输入用原unbound与begin_input/check验证确切当前Session和closed；不把Goal保留的transition限制推广到合法替换回调。旧上下文失效仍拒绝，Goal reservation仍等待转换结束 |
| exact子执行已被取消时返回GoalError，被admitted bridge误判为额外收尾失败 | 仅在取消已请求且child ref/round均匹配时报告CancelledError；身份不匹配、await/interrupt/idle清理失败仍走原失败与fence。不放宽共享bridge对真实finally错误的判定，不伪造取消日志 |

原失败测试未改。Retry整文件、替换上下文、真实child取消create/round/reuse、child关闭失败父依赖保留共12 passed，33.04秒；Session runtime/router39 passed，1.58秒，含新增捕获不提前执行/recovery阻止Goal抢占、pending transition下current回调可写但stale不能写。五文件Ruff与三源mypy通过。

五文件manifest SHA256：87a7d413f275f616fd1451639d56d1ad8c136f09f1c1b1868688c2b890e74dcc。独立三视角报告保存在产品树外architecture-analysis/goal-refactor-20261103/ci-regression-{ownership,runtime,data}.md。实施负责人依据源码复核与原失败用例接受修正；完整CI必须以修复提交的实际结果关闭。

首轮CI有8个Coding失败，其中2项是首次child取消失败导致测试未完成registry清理后的连带失败。Harness四分片、Work/HarnessWork、Agent与跨平台Resume烟测已通过，但相关共享实现修改后仍按现有CI重跑受影响模块；未更改分类、选择器、断言或门禁以消除失败。取消分类修正只恢复受控取消的预期，不宣称所有错误文本和竞争终态逐字相同。
