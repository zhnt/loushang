# S3共享批次规划切片评审

Authority: descriptive。对象为c93ea90ba之后的共享批次规划与回复交接提炼，非整个Goal重构验收。方法沿用archmethod本地master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e。

## 范围与责任

HarnessWork.goal.batch_planning承接原批次选择、已消费提案判定、规划trace和候选确认算法；HarnessWork.integrations.planning承接原PlanningWork的临时订阅、回复来源采集和报告交接。没有新增模型循环、执行器、准备槽位、预算计数、存储或codec。

Coding继续提供原提示、parser、领域上下文、动作/Method绑定、Blob读写和错误转换。上下文仅在内存中通过opaque对象交回原领域；读取发生在原位置，不重读仓库拼接另一份inventory。原_planning工厂保持原文，provider调用及ScopedSessionWork装配不变。

## 固定基线与三视角

十文件快照manifest SHA256：31c0b7d9fabb29755a0a225968a47d89bed20e054621f738a781785588287d09。三个独立agent核查职责/复用、运行/失败、数据/兼容，均无剩余阻断。原始报告保存在产品树外architecture-analysis/goal-refactor-20261103/s3-policy-code-{ownership,runtime,data}.md。

职责评审确认共享层不依赖Coding，原领域MRO仍只调用一次；运行评审确认异常分类及捕获位置、准备槽位和取消路径未新增owner；数据评审确认intent消费、trace、下一输入字节与旧算法一致。该结果不证明普通Session公开接入或两个入口等价。

## 验证与局限

迁移前从3cffb4199冻结12种selector场景，旧源SHA256为2023aa48f4cf4b590d2b530bda7b85f44d26c4ef036ae3a9f84fc903cb0cb162。覆盖初始规划、预算、待输入、成功/拒绝提案、来源失败、无进展、intent限制、父策略拒绝、自身intent及已消费not_submitted。固定结果SHA256为236ee8fb545111a1afb3bd078353d13c230faf09172fb3d28bfab17af53da524。

差分比较完整candidate、trace及下一规划输入字节。该fixture替代了领域观察及_report/_proposal，不独自证明真实Blob/来源链；真实原路径检查补充如下，存在覆盖交集，不相加：

- 原本地Work shell与差分、旧兼容及非Coding消费者：160 passed、7 deselected，82.34秒。
- 原仓库来源拒绝、review epoch、缓存、冷读、委托模式和取消：14 passed、55 deselected，167.38秒。
- 实际包边界、通用消费者及差分：5 passed，32.95秒。
- 原托管calculator/repository闭环：3 passed，38.60秒。
- 七个源/测试文件Ruff及四个源文件mypy通过；未运行线上模型。

按已授权重构范围接受本切片本地集成，接受角色为实施负责人，依据上述独立评审与检查；不代替用户对保留架构决策的接受。S2普通Session公开接入、旧私有配置分支清理、S4入口复用和最终交付仍未完成。
