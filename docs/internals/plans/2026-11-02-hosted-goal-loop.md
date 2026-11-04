# #824 托管 Goal 最小闭环交付

- Authority: descriptive — implementation evidence。
- 设计：[COD-KD-HG-001 R2](../architecture/coding/key-designs/hosted-goal-loop.md)，用户于2026-11-02明确接受并要求实施。
- 基线：`7e1194f000dc0e0fb432b163d3d29a2afc2645f1`；独立工作树 `hosted-goal-824`、分支 `feat/hosted-goal-loop-824`。
- 状态：实现、专项验证、兼容性回归与三视角代码关闭复核完成。用户于2026-11-02授权提交、PR、合并及本地同步；远程检查和合并结果以关联PR为准。

## 行为与责任

`create_coding_goal_application` 显式装配一个应用内calculator Goal，服务端固定任务和预算。原AppHost创建唯一fresh canonical Session，原AppService registry/guard保留一次执行；`scope.goal_client`提供start/find/query/wait/interrupt/retry_settlement。没有第二套Session、Work引擎、输入队列或去重记录。

原CodingGoal增加内部借用初始化入口，复用原GoalJournal、ModelPlanningPolicy、CalculatorPolicy、Method、WorkRuntime和独立验证器。facade在guard启动前持有未初始化Goal对象，guard内初始化并推进；失败时不遗失已取得的资源。借用Goal不dispose外部Session，先关闭自己的依赖，再由原AppHost释放Session。

每次原advance最多受理一Work，保留原operation/run身份；外层execution关联整次有限推进，不包第二层Method Work。至多8次advance、8次逻辑模型调用、单次输出1024 tokens、provider单次尝试；120秒单调业务期限包含初始化，期限结束后仍完整收尾，不承诺120秒内物理关闭。原Goal.limit=20和原LIMITS不变。

查询只投影稳定状态码和原Work/recording/cancellation观察。scope失效、跨owner或跨service实例不允许借handle读数据；跨await交付前重新验证权限。客户端detach不取消原执行，member关闭但不释放Session时保留事实。仅最终owner关闭释放记录图；重试清理不重新规划或执行。

## 复核修正

| 发现 | 修正与验证方向 |
| --- | --- |
| CGD-1：原Work append成功而recording observer失败时仍可继续推进 | 每次advance前后查原Work记录确认；不可确认即停止，外层不得成功，托管validity为unknown。原Goal状态保持独立，不改写原验收事实。分别验证首批确认失效和最终独立验收后的失效 |
| HG-C-RF1：借用初始化绕过Session准备失败退休桥 | 将原execute_prompt的失败桥抽为Harness Session.prepare_execution，默认保留prompt语义；借用Goal显式选择原prepare+startup顺序。任一步失败或取消都进入原Session.settle_execution退休重试，不新增清理owner |
| 职责视角验证缺口：canonical owner、第二profile和member寿命 | 真实AppHost第二profile拒绝后原Goal仍可用；所有批次共享canonical Session；close_member(False)后原事实保留至应用关闭 |
| 初始化/清理债务缺少证明 | 注入Goal构造后失败、Goal清理失败、Session清理失败，确认任务仍RUNNING且依赖保留；retry不增加模型调用、初始化或Work |

冻结副本与独立原报告位于产品树外 `/home/dev/lsspace/architecture-analysis/hosted-goal-824-20261102/`。三视角均关闭重要发现；R2冻结后17个产品源码文件哈希未变，不把静态推演称为运行时证明。

## 架构协同

AppServer/AppService各增加一个应用内Goal合同/bridge模块；Coding增加固定配置、装配、facade和一次invocation，使用原guard/registry。原Method的安全Work投影抽取为共享内部模块，语义保持。Harness只抽取既有Session准备失败桥，仍由原Session拥有图与退休责任。

既有精确消费者清单登记新模块；`coding/hosted_application.py`完整owner从930到946行，16行用于互斥Goal选择、配置校验和原resolver传递，预算同步为946；未移出原代码绕计数、豁免整包或扩展CI gate。对应七个架构文件62项检查通过。最终文件如有变化须按实测重新核对。

## 手工验证与范围

在包含本切片的checkout运行（合并后可使用主工作树；显式选择当前源码，避免共享venv的editable安装指向其他lane）：

```bash
cd /home/dev/lsspace/loushang
PYTHONPATH=src /home/dev/lsspace/loushang/.venv/bin/python examples/coding/30_hosted_goal.py
```

示例是确定性离线provider，真实Session/文件工具/Work/验证器，无API key或模型费用。
预期execution=succeeded、Goal completed/current，并有初始失败、Method修复和最后验证的原Work记录。

只覆盖同进程受权SDK与固定calculator任务。没有远程协议、进程恢复、任意仓库目标或子Session切换；本次不重复既有Kimi动态重规划试验。原普通托管prompt、Method入口及本地CodingGoal兼容性已由下列回归确认。

## 验证记录

- 托管Goal专项：15 passed，128.09秒。包括原记录observer失效的首批/最终验收两分支、启动准备与extension startup债务、scope等待期间撤权、真实canonical/第二profile/member关闭。
- AppService/AppServer及受影响Harness Session/普通hosted底座：1229 passed、10 skipped，154.53秒。保留not live/not requires_host_runtime/skip-host-runtime。
- 原Coding兼容性（hosted Method、execution、application、Work shell、repository Goal）：254 passed、7 deselected，517.40秒；使用原安全选择器和仓库独立租约runner。
- 既有架构边界：62 passed；改动源码Ruff、15文件mypy、依赖事实freshness、9项文档规则及变更链接通过。
- 离线示例实际完成：6 advance、6逻辑模型调用、6 Work（其中一次初始检查失败）；execution succeeded、Goal completed/current。产物目录 `/tmp/loushang-hosted-goal-i03bl8b1`。无付费/联网模型调用。
- 一轮直接pytest的默认临时根在运行期间消失，产生文件/锁路径不存在和后续fixture错误；该轮不计整组通过，未据此修改产品。改用仓库现有 `scripts/dev/run_pytest.py` 的独立租约目录重跑。新增Goal的15项及原兼容性组254项均通过。
- 旧位置参数测试夹具曾把新增kw-only Goal字段放进位置参数；仅修正排除该字段，产品的旧位置参数顺序未变。没有改变选择器或新增CI gate。

日志及最终文件清单归档于上述产品树外目录。尚未宣称全量 `check-changed` 或远程CI通过。
