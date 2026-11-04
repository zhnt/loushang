# 双入口等价切片评审

Authority: descriptive。对应S4a及[装配/对照说明](dual-entry-equivalence.md)，未激活S4b真实lmux wire。

三文件固定manifest SHA256：b531efa8c84b118ee592c1d19945f782352f6521d7b9c1e7ece5585984ace8b6；基线e18ba67f9。三位独立agent分别核查职责复用、运行失败及数据兼容，无剩余阻断。原始报告位于产品树外architecture-analysis/goal-refactor-20261103/dual-entry-{ownership,runtime,data}.md。实施负责人依据独立评审与实际对照接受此切片本地集成。

运行代码仅给attach增加可信宿主的两个可选限额，默认None保留原本地行为；校验、模型调用前消耗及输出限制继续原allowance，无新账本、driver或AppService DTO依赖。非法预算在scope挂载前拒绝。

两项实际离线对照通过，32.68秒。每场景独立创建本地SDK Session和原application-local AppService Session，真实经过AI准备、Transcript/Model Input、Work、Method、工具及固定验证；只有provider为确定性替身。托管start/wait继续原scope/guard。

正常完成与连续无效提案后暂停的业务状态/理由、revision/epoch、要求ID/验收覆盖、验收依赖的原operation位置、各批Work/Method/步骤/取消观察、调用及推进数、validity与未知标记一致。每侧先验证原operation→run→Session归属，再归一随机ID。类/owner检查补充证明两侧共同使用原SessionExecutionScope、SessionGoalController和各自唯一原WorkRuntime；不以类名相同取代业务对照。

限制：不比较完整payload和所有prompt字节，不把取消观察相同视为取消演练；没有在该对照中验证deadline/撤权/预算耗尽全部组合。初期测试父目录权限与adapter注册冲突已修测试装配，没有放宽产品隔离或注册判据。Ruff通过；无付费调用，未改门禁。

既有托管原关闭/撤权/预算/零模型收尾、委派模式和来源证明仍须在最终选择检查及整体评审中合并核对，不能从本两项直接宣布全部重构完成。
