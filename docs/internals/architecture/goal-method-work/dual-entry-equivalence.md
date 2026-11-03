# 双入口共同业务核对

Authority: proposed。范围为已接受GMW-RF-001 R2的S4a，不含真实lmux wire。

## 装配

嵌入式调用方捕获原Session并显式CodingGoal.attach；application-local AppService继续原client scope、registry、execution guard与托管适配。两者复用SessionExecutionScope、SessionGoalController/Coordinator及原SessionWorkRuntime，领域仍注入原CalculatorPolicy/Method与证据适配。不新增公共Goal facade、执行driver、DTO依赖或菜单。

attach可接收可信宿主的max_model_calls/max_output_tokens，只在创建该执行owner时交给原allowance验证与冻结；默认保留现有本地profile参数。不会修改Session配置、Goal历史、原计数，不能重新attach有历史的Goal重置预算。AppService仍使用原配置来源及校验，客户端不能借该本地Python入口传递代码或替换服务端配置。

## 对照

选同一固定calculator任务、确定性prepared provider、相同模型输出/调用限额及初始工具/system prompt；本地通过显式有限advance调用，托管通过原有界invocation运行。测试比较业务状态/理由、修订/epoch、要求与验收覆盖、验收所依赖原operation的位置、每批phase/Work终态/Method/步骤终态/取消观察、推进数、调用数、有效性及未知标记。每侧独立验证operation→run与原Session身份，不比较随机ID字面值。实际AppService start/wait/resolve仍走原scope/guard，不直接调用托管drive绕过授权。

正常完成与连续无效提案后有界暂停两场景分别核对。依赖的输入与来源证明来自原AI/Model Input/Transcript/Blob/Work管线，不用同一个假的Goal结果替代两边。

## 证据边界

本对照只验证选定profile的完成及有界暂停路径，不证明所有取消/deadline/撤权交叉组合等价；这些还需原专项回归和最终评审。普通已有历史不丢失、基线不变和失败不损坏其他owner见当前Session专项。托管deadline/DTO、detach后owner和撤权检查沿原机制，不为测试改门禁。真实TUI菜单和远程lmux wire没有在本切片激活。
