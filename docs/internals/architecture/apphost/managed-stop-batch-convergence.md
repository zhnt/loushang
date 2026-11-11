# AppHost managed：固定快照批停职责归一（A49）

- Authority: accepted bounded key design；不替代完整Goal或现有持久/原生合同。
- Design status: accepted R1 by implementation owner `/root` after three independent views。
- Implementation status: partial verification；实际两源已接入并获三视角及Root有界接受；19项原失败/受限路径未通过。
- Owner: 原AppHost managed stop；Coding保CLI确认、编码产品政策和结果呈现。
- Method: local clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- Requirement: [COD-RESP-GOAL-002](../harness/coding-responsibility-convergence-goal.md) P4；[当前owner](../harness/current-owner-map.md)。

## 决定与复用

不将ManagedMuxCommand及CLI语法整体搬入Core。原managed stop组件内以私有批次程序承接
固定snapshot的逐项停止、单项失败继续、取消及全量清理。直接复用原StopOperation、
Journal、paths、spawn与native receipt；原单服务StopOperation整个class AST不变。
不存在完整旧批次API可直接替换，因此是最小补齐原owner，不是删掉两份批算法。

Code StopAll仍为原FQN真实类，有原显式构造签名；同一个实际实例继承批机制，保原
namespace/defaults/deadline/entries/started/closed/emit及原Task引用，不套delegate、
新日志/registry/执行框架。Code仅34行构造和结果呈现，完整资源/任务协调退出Code。

唯一固定同步`_report(observation,status,reason/code)`是会抛错的呈现边界，绝不是纯回调。
它在原emit词法位置调用Code原emit、组装原dict，无新增await/队列，也不延到批末才输出。
Core不收终端、JSON、argparse.Namespace、Code工厂或任意阶段表。原合法snapshot及
service/instance为exact frozen值，晚组装输出不改支持值域的身份；不承诺破坏frozen或
任意代理/热改getter的反射全等。

## 运行与失败

外层Code仍冻结/预览/确认；拒绝确认不分配owner，确认后共用唯一30秒stop预算。
不重新发现目标、不追successor；无实例skipped，超期后项not_attempted，原普通
Exception失败继续，取消/KeyboardInterrupt外逸。Journal先保留再open，Stopper先保留
再run；stopped须等该项stop和cleanup完成。原单项native/进程组/instance权威保持。

close先启动所有原entry清理，再统一等原2秒；不延长stop预算。未完成Task原样保留，
取消waiter不取消Task，失败只重试原close、不重发stop。stopper成功后清引用，再关
Journal并于成功后清引用；namespace始终外借，批次不能关它。原CLI外层finally、
close_native和未清债进程退出处分均未改。

## 兼容、成本与验证

公开Code名/签名/调用及原字段保持；继承方法定义位置、MRO、私有Entry FQN和私有
依赖hotpatch位置改变，不宣称私有反射/unbound-method pickle全等。不改持久DTO、
schema/hash/权限/平台或数据路径。原fixture仅迁Journal/Stopper/monotonic三处lookup，
全部37个assert AST同；四其它已冻结测试不改。没有CI、gate或矩阵变化。

Code125→34（−91），Core180→291（+111），系统**+20**含全部接收与兼容成本。
这是职责归位，不称系统净删或性能改善。当前Code120932/系统641090，1932生产源
仅两源改变，另1930逐SHA同A48。完整15K和系统严格净减均未达。

首业务运行：8原检查过、8原失败、11setup错误，另1树外对照失败；不写全绿。
17个原失败直接暴露原父目录校验，`/home/dev/lsspace`为0775；另2被CLI错误映射
遮蔽的失败，以精确迁前两源+fixture复现同失败。未改共享目录、准入、超时或选择器，
这19项和此前17项限制都未销账，也不简单相加当独立新问题数量；两项CLI失败的完整
内因未独立证明，不把17条直接目录证据外推为19条根因皆已确证。

树外对照首漏将旧Journal接同一替身，修后无实例输入又误用revision0而被原合同拒绝；
两次失败保留，修为同leaf及原合法None后1项过（0.82秒）。内部六种原实现/实际Core
比较含四个呈现抛错分支及原异常context、顺序与资源清理；实际Core路径/SHA、同self/
entry已见证。旧8通过不重跑；7原架构检查过（29.10秒），Ruff/两源影子mypy及独立
冷导入过。异常比较仅覆盖类型/code及紧邻context类型/code，不覆盖完整cause/suppress/消息/traceback。
上述受控替身验证不证明真实native、所有取消交错或完整托管路径通过。

## 治理、范围与下一步

沿既有CLI→AppHost managed→原Hosting/Journal关系；原actor、权限、namespace持有者
和事实权威不变。三视角按实际连接判定为原组件内部职责细化，Root在授权内接受；
不由此接受KD008/KD010/KD011待用户重要图，不新增系统环境actor或部署。

三独立设计及后续实际代码评审、原失败/迁前对照XML、全部source指纹和原型保存在
产品树外命名交付`p4-managed-command`；[执行记录](../harness/coding-responsibility-convergence-progress.md)记录终态。
close/reconcile及其verify→首次输出→record→reconciled输出屏障仍属P4后续工作，
不能把它强套create/start，也不以本片替代完整P1–P4。回滚仅本两生产源和lookup夹具，
保留其它脏改动与此前交付；尚未commit/push。
