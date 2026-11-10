# A117：Goal／Work联合来源冷读与同owner关闭

- Authority: bounded implementation under COD-RESP-GOAL-002；完整Goal仍partial。
- Design status: accepted direction；三实际视角及实施owner接受证据在树外。
- Implementation status: implemented，限本冷读程序和下列验证。
- Owner: 原optional HarnessWork GoalStore集成；方法为本地clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

原Code的完整Goal journal open/load→policy→replay/goal存在→Work查询/全历史关联
→逐batch recording/delegation/handoffs→借入Transcript bind/resolve→finally关闭同
journal，现在由原integrations.goal_store内私有函数执行，不扩大store class为controller。
原facts纯算法也归此层，供Code inspect与cold read复用；原本已经共用，不报双算法
去重。原Journal/Work/Transcript叶实现不重复计收益，无新manager、Protocol或状态。

GoalController.facts不等价：有retired/fence/busy效果、只返关联runs、receipt采用
is not None、仅terminal时查cancel；原cold算法返回全log runs，receipt用truthy，
被历史batch关联的run缺cancel即unresolved（不限terminal）。保原覆盖/字典last-wins及全history先验关联检查，
不是先过滤目标Goal再验证，不能用更窄查询替代或加flags强套live controller。

Code保原公开read签名/doc、reader conversation前置检查、resolve/path/GoalJournal
构造时点和实际View/CleanupError类。Core直接持原实际store，不另建wrapper owner；
open失败也走原close，close失败可盖success/read/cancel，typed error保同owner、原
read_error/cleanup_error对象及from cause，caller必须对该owner重试。借入reader不关。

五个叶绑定只构造原政策/数据：open/load后才import两policy并构三headers；replay/
goal检查后才计算原Work log path；recording存在后才取Code纯delegation decoder，
且lookup先于entries过滤、decode先于handoff投影。两factory构造实际Code DTO/error，
保late类lookup；namespace prefix为Code数据、每handoff按原点形成binding id。
没有Code open/read/query/close程序回调或阶段表。两TypeVar保实际owner/返回值类型，
不是第二DTO/schema。Getter、typing、导入和全部薄入口都计成本。

Code195→112（−83）、接收GoalStore137→277（+140）、系统+57；非系统净精简。
Coding430源112718行，系统1969源648262行（含GUI Rust/TS），较Goal−25037/+13468，
距15K97718；其余1967源/13资源SHA同。DTO/Error整class AST、read签名/doc/preflight、
facts整函数同原；Core原所有非import定义同，展开五绑定及prefix后完整操作逆AST同。
私函数/效果挂点转到实际Core，不承诺旧私导入别名或traceback帧数；公开真实类型保留。

原9真实消费者过，含三policy路线、独立子进程冷读、借入reader继续可用和真实Goal
lease close失败/busy/同owner重试。持久39旧受控观察原实物回放过，候选同39过，
原值不重录。实际联合240全过：原9+受控39+Work Transcript22+公共API5+导入165；
两源mypy、Ruff通过。原close失败3参数测试仅local Core import及两patch target迁位，
逆去后整测试模块AST同原，306断言及所有raises/calls保持，无新默认gate。

39观察保完整实际Code DTO字段/类型、trace、facts、错误args/notes/cause/context/
suppress及owner/read_error/cleanup_error身份、retry与borrowed-reader状态；Task.cancel
在bind/resolve真实await点触发。Store、Work投影、reader/Source叶受控，是协调程序
证据，非native authority或FD普查，真实9另证物理层。初轮记录器无法序列化header
mappingproxy，补递归Mapping编码后仍在旧源重跑；原失败/脚本保留，未改Product。

规划器因HarnessWork路径未分类选full validation，已按规则补make check-ai：935过/
2skip/7deselect，lint/mypy79/catalog/import过；总覆盖89.87%、runtime-core89.62%未达
原90%门槛，check-ai退出失败。79份AI源SHA及9415/8461覆盖计数同A101已接受候选，
是已记录基线欠账，不称本批全门禁绿，也不修改阈值或选择器。

显式probe_*及40行JSONL不进默认发现；来源守卫在原取证中核实际两模块SHA，持久
版核origin不钉未来源码。完整旧源/候选、测试原像、成本/AST、初失败/修正、JUnit
及三视角在树外`coding-convergence-continue/a117-goal-work-sources`。其它Hosting/
AI覆盖率、构造与Session等欠账不关闭；KD003未实施，KD011/A33待用户未采用。
