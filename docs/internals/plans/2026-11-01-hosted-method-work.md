# #824 托管 Method → Work 第一切片交付

- Authority: descriptive — implementation evidence。
- Design: [COD-KD-HMW-001 R2](../architecture/coding/key-designs/hosted-method-work.md)，用户于 2026-11-01 回复“同意，继续推进”接受并授权实施。
- 基线：`914cf3ac84935c8bbd2855e660505b3b31eba2ef`；分支：`design/hosted-method-work-824`；位置：长期 code lane。
- 状态：第一切片已实现，三视角代码复核关闭；已提交并推送，PR [#841](https://github.com/zhnt/loushang/pull/841) 为 draft。远程功能检查通过，架构清单遗漏已修正并经专项验证，等待修订后的 Actions 结果；尚未合并。

## 交付行为

`create_coding_method_application` 复用原 installed Coding 装配、AppHost canonical Session 与 AppService 生命周期，显式创建一个应用内 Method 专用配置。服务端冻结 Method 全部执行输入；客户端经当前 scope 提交、等待、查询、中断或重试清理。

- 默认 Method 上限16步，配置可取1～64步；服务默认同时1个execution、最多8次稳定提交；应用只创建一个fresh Session。重复 submission 返回原 execution，不计为新提交。
- 一个execution对应一个多步Work；operation_id取原execution_id，原WorkRuntime负责operation→run。
- `CodingExecutionWorkV1` 的原受理及模型结果判定逐步复用，失败停止后步；原Method编译器与SessionTurnExecutor负责步骤语义及执行。
- `scope.method_work_client` 提供 capability/submit/find/query/wait/interrupt/retry_settlement。普通配置仍提供 execution_client；Method配置拒绝旧prompt/steer/follow-up/单turn中断入口，不自动fallback。
- query返回请求状态与独立Work、recording、cancellation观察，不泄露原始事件payload或服务器路径；观察锚不代替权限。
- 清理失败保留原owner和运行依赖，retry只清理；最终关闭才释放Work记录图。Work事实为内存保留，无进程恢复或远程协议承诺。
- 记录故障后 capability.accepting=False；拒绝新提交，保留旧提交的去重、查询和清理。缺少记录不能推断未执行，不能按 completed 字样替代原 runtime 的活动状态。

## 设计场景与验证

| 场景 | 对应检查 |
| --- | --- |
| V1 默认兼容 | 原 Coding hosted/execution/bootstrap/application 及 AppService registry/guard 回归 |
| V2 纵向闭环 | 真实 `create_coding_method_application`、AppHost、AppService、Coding Session；确定性模型执行inspect→verify，单Session单run |
| V3 去重/忙 | 同submission复用、不同text冲突；清理未完成仍busy |
| V4 受权/旁路 | scoped与unscoped旧输入拒绝；失效scope、错误instance/owner锚/执行身份拒绝；第二wrapper拒绝后原owner继续可用 |
| V5 步骤失败 | 模型error但prompt正常返回仍使Work失败，后步不执行 |
| V6 取消/清理 | 首步中断不执行后步；pre-Product中断无Work且unknown；cleanup失败后retry不重跑 |
| V7 寿命 | scope关闭后新scope重连原owner；旧scope不能读；保持外层facade引用时，成功关闭后Work runtime/backend可回收 |
| V8 事实与竞争 | late interrupt保留已确定候选结果；原记录追加失败不冒称完成/确认；DTO不泄露错误中的服务器路径 |

最终相关七组聚焦回归：83项通过，另1项测试夹具缺少必填 ids；修正该夹具后，位置参数兼容用例单独通过。共84项获得通过证据，其中新增专项16项。Ruff及14个受影响源码文件mypy通过。真实离线AppHost示例成功；未进行付费或联网模型调用。

AppService/AppServer/AppHost 独立兼容检查：2340 passed、11 skipped，115.04秒；保留 not live、not requires_host_runtime 及 --skip-host-runtime 等选择器。该组与上述聚焦回归有重叠，不将两组数量相加当作独立用例总数。

广泛托管检查在既有 `test_G17_TERMINAL_START_CANCEL_durable_recovery_reclaims_and_can_relaunch` 的隔离子进程停滞；外层约17分钟、子进程约9分钟仍未退出，已停止本次检查及其直接子进程组。该运行不记为通过，也未归因为本次改动或机器环境；未为绕过它修改产品代码。其余专项证据独立保留。

2026-11-01 收尾复核：当前工作树该用例单独通过（61.94秒），额外45秒栈采样显示外层正在等待原隔离controller结果，随后正常退出。隔离虚拟环境固定导入未改动main源码、安装入口也使用同一main源码，对照通过（118.60秒）。未复现上次停滞；不能据此断言其根因已修复，因此不改timeout、不改产品语义。按原 `scripts/ci/check_changed.py` 启动的本地广泛检查随后主动停止：其执行期间，PR 的既有四个 Coding 分片及托管功能检查均已完成，避免重复消耗机器资源。停止的本地运行不计为通过，也不把人为中断产生的失败计为产品缺陷。

静态架构依赖图 freshness 检查、文档九项规则及变更文档链接检查、git diff whitespace 检查通过。`make plan-checks` 已核实范围，未宣称全量 `make check-changed` 通过；该用例已有上述单独通过证据，完整 Coding 及平台检查以原 Actions 路由的结果为准。未修改选择器或新增 gate 以绕过检查。

## 代码三视角复核

原三位评审者按实现文件哈希分别复核职责与复用、运行与失败、数据权限与兼容。首轮提出四项重要修正及一项验证补充；协调修正后再由原视角复核，不能将关闭复核算作另一轮完全隔离的发现。

| 发现 | 修正及验证 |
| --- | --- |
| RF-1：终态追加失败后公开状态与活动权威不一致 | 沿原 active_runs 清理；记录不可确认后拒绝新受理；注入追加失败验证旧查询和重复提交可用、新提交不创建execution、正常关闭 |
| CD-1：受理已结束却报告仍可能受理 | 根据原 submit task 与中断事实区分 unknown；注入受理写入失败及清理等待验证 |
| CD-2：任意可变 dataclass 可绕过深冻结 | 仅允许确切的既有 MethodDescriptor/MethodApplicability 数据类，拒绝其它；保留普通映射/列表深冻结验证；显式拒绝未支持的approval_gates |
| CD-3：新增配置字段改变原位置参数 | 仅新method字段kw_only；原位置构造兼容断言通过 |
| C-O1：第二profile及member关闭缺少真实入口证据 | 真实AppHost第二profile attach拒绝后原owner仍成功；close_member(false)保留Work至真正owner关闭 |

最终代码冻结清单及首轮/关闭报告归档在产品树外 `/home/dev/lsspace/architecture-analysis/hosted-method-work-824-20261101/`。三位评审者均核验最终16文件SHA并关闭各自发现：RF-1、CD-1/CD-2/CD-3及C-O1，无剩余重要或阻断发现。评审者仅静态核查和场景推演，不将协调者的测试结果称为独立运行证据。实施负责人接受本切片的职责适配和记录故障收窄，仍以上述本地验证边界为限，不替代远程发布检查。

## 手工验证

```bash
cd /home/dev/lsspace/loushang/.worktrees/code
/home/dev/lsspace/loushang/.venv/bin/python examples/coding/29_hosted_method.py
```

默认使用新建临时目录，确定性离线模型，无API key或付费调用。输出先accepted，随后execution=succeeded、work=completed、inspect与verify均completed。`result.json`只是展示快照，不是可恢复Work日志。也可传`--output-dir`指定一个尚不存在的新目录。

已实际运行成功，初轮产物目录：`/tmp/loushang-hosted-method-14oa3iu8`。不需要重复既有Goal/Kimi动态重规划试验。

## 范围

本次打通一个托管 Method/Work SDK 入口。Goal托管自动推进、每次请求动态选Method、跨服务共享执行、网络/stdio入口、持久Work恢复均未在本切片实现，也没有由本次试验获得保证。未扩展CI gate。

## PR 检查与架构清单同步

PR #841 首轮 Actions（源码 `f784dc81e202a8e5df0487865194395c5fd417ca`，run `41316738926`）：四个 Coding 分片、AppService/AppServer 模块、Windows AppHost 原生检查、Linux/macOS/Windows 冒烟、文档及架构 source-facts 均通过。AppHost quality 的 8 项失败均为本切片新增模块/依赖未登记或既有行数预算未同步；该组其余 2627 项通过、11 项跳过。

修订只登记本切片确切的 Coding→AppHost/AppService/AppServer 消费者和两个 `method_work.py` 模块，不豁免整个包。原 `appservice-core` 四文件仍完整计数，实测 1899→1908 行，预算 1900→1908；`coding/hosted_application.py` 完整文件实测 891→930，预算同步增加 39 行。新增内容分别是旧输入旁路封堵、固定配置装配与原 execution claim，责任未迁出原 owner。未删除断言、缩小扫描范围、新增检查或改变 PR 触发与 required checks。

职责与复用评审者已独立核对上述路径和实测预算，无阻断发现；报告与差异归档在产品树外。七文件专项首轮 61 项通过、一处同类 AppHost 消费者清单遗漏；补齐后该文件全部 11 项通过（含首轮通过的 10 项），七文件共 62 项获得通过证据。修订后远程结果以 PR 为准。
