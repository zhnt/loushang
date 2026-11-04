# 当前Session接入首切片

Authority: descriptive。实施范围来自用户已接受的GMW-KD-RF-002 R2；不是任意Session/profile均可执行Goal的承诺。

## 入口与责任

`CodingGoal.attach(session=...)`将现有有限calculator规划profile绑定到确切的持久Session。它不创建或恢复另一个Session，不复制历史，不改模型、system prompt、活动工具、retry或compaction基线。Goal自身close只释放自己的资源；原Session继续由原生命周期owner销毁。共同受理、配置和资源机制分别由原Harness Session与HarnessWork桥接提供，Coding入口只装配既有profile。

初始化在原scope内保留候选，组装后再次核验原受理代际；后续advance继续原Controller和原SessionWorkRuntime resolver。兼容原Work后端按对象复用，不能装配则明确拒绝；没有第二kernel或队列。新普通Session后端沿原30秒取消期限，旧专用Goal保留None；已有普通后端不被改写期限。30秒是原Work取消观察期限，不是测试矩阵或业务执行时限。

原Session manager决定日记目录，原Blob resolver决定数据authority。`inspect_session_goal(session=..., goal_id=...)`用同一实际目录执行独立只读查询；旧inspect_goal签名与data_root/sessions默认保持。非空旧Goal历史不能通过attach重建计数器继续执行；原owner仍在时必须继续使用它，owner缺失时只读查询，不暗示跨进程续跑。

## 能力边界

首切片支持原file tools可用、无执行替换扩展、可生成操作级工具prompt、具有prepared-request transport的可写持久Session，保留其既有交互历史。无持久Transcript、provider window无法安全生成工具prompt、原工具被替换或不兼容Work后端会被明确拒绝。现有Work后端仍要求recording v1、原持久Goal Work路径且无backend-wide source；不把拒绝解释成另一套自动装配授权。

原transport被固定为本执行owner的依赖；合法基线变更仍保留，但Goal在prompt前及每次计数前拒绝继续使用旧transport。不会恢复旧全局值，也不会静默重置额度。标准AI stream的可信声明只在Coding原受信任边界包装；共享limiter不升级任意函数。绑定托管预算时保留已有checkpoint。

## 三视角与修正

最终五文件manifest SHA256：6f96bcd762a798eae454172c590cd29a8a02e7f79f3a6e2549f300440d3ec55c。原始独立报告位于产品树外architecture-analysis/goal-refactor-20261103/current-session-*。方法沿用本地archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e。

初审发现捕获旧transport后基线变化仍可能调用旧transport、标准stream包装声明丢失、自定义目录冷读未贯通。三项均修正，三视角源码复核无剩余阻断；最终仅补正模块说明和新增两个失败场景测试。实施负责人依据独立评审与实际检查接受该切片本地集成，不扩大架构接受范围。

## 实际验证

- 3种stream（默认、标准、显式声明）×原兼容backend有/无，及基线变更后无模型调用拒绝：7 passed，42.72秒。真实离线prepared provider经原AI、Transcript、Model Input、Work及证据报告管线，非替换Goal判断。
- 每个正常场景覆盖已有普通聊天历史、规划proof/live trace、实际目录冷读一致、Goal关闭后普通聊天继续、基线不变、同Session重复live attach不破坏原scope、旧历史拒绝后聊天继续。基线变化场景保持新transport，Goal调用数为0，关闭后普通聊天使用新transport。
- 原普通provider运行中attach拒绝且不abort原Task；memory Work后端拒绝且不替换；均无Goal日记创建，原聊天仍可使用：2 passed，45.30秒。
- 原Work shell、批次差分、Session runtime与HarnessWork runtime：174 passed、7 deselected，168.39秒。
- 固定旧记录/公开API及原包边界：175 passed，183.48秒。与上项有范围交集，不相加。
- Ruff通过；两源mypy通过。初期测试目录未与state根隔离、registry清理方法名和trace字段名错误已修测试装配；未放宽产品隔离或来源判据。无付费或线上调用。

联合受理/preflight/held queue/配置失败、旧owned/borrowed收尾机制另有原S2专项证据；本切片没有重新穷举其所有交叉组合。普通Session的完整并发矩阵、旧私有setter分支清理与S4应用内AppService等价仍待收尾；真实lmux wire仍在本次范围外。
