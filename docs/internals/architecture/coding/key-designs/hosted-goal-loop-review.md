# 托管 Goal 最小闭环三视角评审

- Authority: descriptive — review evidence；Design status: reviewed；Implementation status: not-started。
- 对象：[COD-KD-HG-001 R2](hosted-goal-loop.md)，#824第二切片；基于第一切片提交 `f784dc81e`。
- 方法：archmethod本地干净master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 评审的R2正文SHA256：`245e041ace54cf65b652aeab46f854663ee1afd346e65a9ef1479a006e8c32ad`。仓库版末段纠正接受主体为用户，技术合同不变；冻结副本及报告存于产品树外 `/home/dev/lsspace/architecture-analysis/hosted-goal-824-20261101/`。
- 用户本次要求完成交付、设计评审、实施三步；既有“系统环境图等重要工作件需要我评审”仍保留。技术评审通过不代替用户对新方案的接受。

## 发现、处置及关闭

三个独立xhigh agent分别阅读同一方案与源码，不互读本轮报告；主评汇总并提出R2修订，再由原视角复核。关闭复核有协调上下文，不宣称为再次完全隔离发现。

| 视角/评审者 | R1发现 | R2处置与复核 |
| --- | --- | --- |
| 职责与复用 `/root/hosted_method_ownership` | HG-O1阻断：resolver构造异常可能先关闭Session、丢失部分Goal清理owner | facade同步预持有inert Goal；guard.run内原位初始化；失败依赖留在原guard/registry；先Goal再Session关闭。关闭，无剩余技术阻断 |
| 运行与失败 `/root/hosted_method_runtime` | HG-RF1与O1同源；RF2记录fenced后无法保证pause；RF3总预算与deadline责任；RF4证据未确认不等于物理未收尾 | 关闭同源构造缺口；不能伪pause；原controller可写才暂停；单调业务期限之后继续清理；总调用首次await前扣减且不返还；unknown和cleanup分离。全部关闭 |
| 数据/权限/兼容 `/root/hosted_method_data` | GD-B1阻断：总预算跨operation缺少合同；GD-B2阻断：日志根可能污染冻结workspace；N1查询泄露/有效性；N2借用初始化状态 | 8次总调用/advance作为额外上限，不改原20次Goal/LIMITS；根目录非重叠准入；白名单DTO与稳定reason；not_started/initializing/unavailable区分。全部关闭 |

## 结论与验证责任

三个视角均确认R2无剩余技术阻断，可提交用户评审。未开始Goal产品实现；设计检查不能宣称运行时保证。

用户接受后实现H1–H6：真实托管纵向闭环；去重与单Goal；权限/owner寿命；预算跨operation不重置；初始化故障、取消、清理失败重试不重跑；原CodingGoal/Method/普通hosted兼容。验证优先确定性离线模型，不重复付费Kimi试验。

部署视角仅覆盖同进程SDK、外部模型与私有文件目录；远程wire、hosted detachable、进程恢复均排除。本轮未运行Goal代码或模型实验。
