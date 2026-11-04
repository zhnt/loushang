# 托管 Goal 最小闭环三视角评审

- Authority: descriptive — review evidence；Design status: accepted — R2；Implementation status: implemented（当前交付状态见末节；以下设计评审保留当时结论）。
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

## 用户接受

2026-11-02，用户明确回复“接受R2”，随后要求“推进第3项：实现托管 Goal 最小闭环”。重要架构工作件检查点已完成；进入实现与代码三视角复核。以上设计评审记录保持为当时证据。

## 实施代码三视角复核（2026-11-02）

以独立工作树 `hosted-goal-824` 的 R1/R2 文件哈希清单冻结改动，沿用三位独立评审者：职责与复用、运行与失败、数据/权限/兼容。首轮各自读取源码，不互读本轮报告；协调修订后由原视角定向复核，不称关闭复核为新一轮隔离发现。原报告和源码副本保存在产品树外 `architecture-analysis/hosted-goal-824-20261102/`。

| 发现 | 关闭依据 |
| --- | --- |
| CGD-1：Work记录确认失效仍可能继续或成功 | 每轮前后查询原get_recording，下一批与成功发布都受限；首批故障及最终验收后故障注入均通过。保留原Goal状态，外层FAILED、托管validity unknown，不混同物理清理 |
| HG-C-RF1：准备失败遗留Session清理债务却提前终态 | Harness共享prepare_execution提取原prompt失败桥，默认不新增startup；借用路径显式覆盖prepare+startup。两类失败均保留原Session退休责任，首次退休失败保持RUNNING，retry只退休且模型零调用 |
| C-GO1：canonical/第二profile/member寿命缺验证 | 真实AppHost拒绝第二profile后原Goal仍可用；各批共享canonical Session；member close_session=False保留至真正owner关闭并释放图 |
| C-GO2：初始化及清理失败缺验证 | 原位初始化失败保留已取得Goal资源；Goal或Session清理失败均保持原owner，retry不重新推进 |

三视角均已关闭重要发现，无剩余技术阻断。协调者执行的托管专项15项全部通过（128.09秒），离线真实装配示例6次advance/6次逻辑模型调用完成；评审者没有将其称为独立执行。随后原SDK/Method/普通hosted兼容性回归254项通过、7项按原选择器排除（517.40秒）。完整交付状态见[实施记录](../../../plans/2026-11-02-hosted-goal-loop.md)。
