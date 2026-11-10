# Coding 逐文件职责与处置清单 R2

- Authority: descriptive inventory；处置建议为 proposed。
- Design status: proposed，与[整体重构方案](coding-reconstruction-proposal.md)一同提交用户评审。
- Implementation status: partial；当前源码计量已刷新，建议处置不自动成为实施接受。
- Owner: Coding / shared-layer architecture；静态分析 Codex。
- 原审计基线：`739f947d6099257af1aec56ae587426d8cd8ec7d`；427 个 Python 文件、145,842 个物理行，含空行/注释/文档字符串。

当前430个Python文件均重新计量并核SHA；原审计列与候选处置保留供追溯。当前行数包括已接通但尚待最终切片验证的源码；各批接受范围以执行记录为准。
A82核实全系统增长口径并退出无消费者私有history壳；当前成本见[审计](coding-convergence-system-cost-audit.md)。
A81完整delegated Goal Work/Session轮次交接已接通；Code保纯政策及真实类型；见[本片交付](key-designs/delegated-goal-session-convergence.md)。
A80完整canonical Catalog custody已接通，Code保实际类/政策/薄入口；见[本片交付](key-designs/canonical-transcript-catalog-custody-convergence.md)。
A79完整Product selected revision输入与Wheel bytes已接通，政策/实际DTO留Code；见[本片交付](key-designs/product-selected-revision-custody-convergence.md)。
A78完整Linux registered/crash恢复与cleanup evidence已接通；见[本片交付](key-designs/linux-worker-recovery-convergence.md)。
A77完整Linux history proof已接通，实际DTO/政策留Code；见[本片交付](key-designs/linux-worker-history-proof-convergence.md)。
A76完整备份拓扑存储归原PackageProduct，政策/实际DTO留Code；见[本片交付](key-designs/backup-topology-custody-convergence.md)。
A75 prepared-operation任务寿命归原Lifecycle，Code保领域准入与薄入口；见[本片交付](key-designs/prepared-operation-task-custody-convergence.md)。
A74三类payload恢复原接受范围见[交付记录](key-designs/worker-payload-recovery-convergence.md)。
A73审批协调原接受范围见[交付记录](key-designs/product-approval-closure-convergence.md)。
A72的[全量剩余职责与保留账](coding-responsibility-remaining-audit.md)按28组连接当前复用、产品保留语义与退出义务；继承K/R/M建议不作为最终处置或不可削减下界。

每个文件均纳入静态清点。C01–C28 的唯一职责、已有组件、Product 保留项和复用优先顺序见整体方案；“拆分”表示需要分离文件内混合职责，不表示整文件可下沉或可删除。原审计列针对冻结切点，当前列针对本任务专用worktree实物。

处置缩写：K=保留领域能力/Profile；R=已共享的适配，直接复用；M=混合职责需按所属组拆分、复用后删旧体；B=共享桥接归正确集成层；E=根据支持/存量证据决定退出；V=先核实真实产品依赖再决定验证入口归位；C=保留已接受兼容转发。所有 M/B/E/V 均为候选，不是已实施状态。SHA 前12位用于定位证据，完整指纹与原始导入/AST 清单保留在产品树外。

| 文件（相对 Coding） | 组 | 原审计行 | 建议处置 | 建议 owner / 保留边界索引 | 原审计SHA | 当前行 | 当前SHA |
| --- | --- | ---: | --- | --- | --- | ---: | --- |
| [__init__.py](../../../../src/loushang/coding/__init__.py) | C06 | 196 | R/M | C06 其余根目录入口与策略 | d153befdc62a | 196 | d153befdc62a |
| [_apphost_canary_child.py](../../../../src/loushang/coding/_apphost_canary_child.py) | C05 | 26 | V | C05 显式 canary 与作者验证入口 | b4d9235284d2 | 26 | b4d9235284d2 |
| [_apphost_canary_control.py](../../../../src/loushang/coding/_apphost_canary_control.py) | C05 | 567 | V | C05 显式 canary 与作者验证入口 | a19ad5ec64ae | 567 | a19ad5ec64ae |
| [_base_plugin.py](../../../../src/loushang/coding/_base_plugin.py) | C01 | 1,082 | M | C01 启动、Plugin 与资源装配 | 6a5ae1acb805 | 1,082 | 6a5ae1acb805 |
| [_base_plugin_owners.py](../../../../src/loushang/coding/_base_plugin_owners.py) | C01 | 554 | M | C01 启动、Plugin 与资源装配 | 73c87bc511e3 | 522 | 0efabd880955 |
| [_base_product_composition.py](../../../../src/loushang/coding/_base_product_composition.py) | C01 | 747 | M | C01 启动、Plugin 与资源装配 | c9dc3724f32b | 747 | c9dc3724f32b |
| [_capability_plugin_composition.py](../../../../src/loushang/coding/_capability_plugin_composition.py) | C01 | 2,189 | M | C01 启动、Plugin 与资源装配 | bbff9d9b6834 | 1,780 | 1e24f978703f |
| [_capability_plugin_specs.py](../../../../src/loushang/coding/_capability_plugin_specs.py) | C01 | 103 | K | C01 启动、Plugin 与资源装配 | b2bceae8d220 | 103 | b2bceae8d220 |
| [_cleanup.py](../../../../src/loushang/coding/_cleanup.py) | C06 | 28 | R/M | C06 其余根目录入口与策略 | caf6c413edb5 | 6 | 15c1bd02b27e |
| [_external_data_product_composition.py](../../../../src/loushang/coding/_external_data_product_composition.py) | C06 | 235 | R/M | C06 其余根目录入口与策略 | d8ff1ffebf39 | 235 | d8ff1ffebf39 |
| [_hosted_execution_work.py](../../../../src/loushang/coding/_hosted_execution_work.py) | C02 | 133 | B | C02 托管与受管运行接入 | 0d4663c3d314 | 214 | 3cfa365f63f3 |
| [_hosted_goal_config.py](../../../../src/loushang/coding/_hosted_goal_config.py) | C02 | 58 | B | C02 托管与受管运行接入 | 349bf3d60a48 | 58 | 349bf3d60a48 |
| [_hosted_goal_work.py](../../../../src/loushang/coding/_hosted_goal_work.py) | C02 | 183 | B | C02 托管与受管运行接入 | a3e7095f4397 | 183 | a3e7095f4397 |
| [_hosted_method_config.py](../../../../src/loushang/coding/_hosted_method_config.py) | C02 | 100 | B | C02 托管与受管运行接入 | 4da687adf6e0 | 100 | 4da687adf6e0 |
| [_hosted_method_work.py](../../../../src/loushang/coding/_hosted_method_work.py) | C02 | 203 | B | C02 托管与受管运行接入 | 62e18f9b05e8 | 203 | 62e18f9b05e8 |
| [_hosted_repository_config.py](../../../../src/loushang/coding/_hosted_repository_config.py) | C02 | 114 | B | C02 托管与受管运行接入 | 72cc176f4c99 | 114 | 72cc176f4c99 |
| [_hosted_repository_work.py](../../../../src/loushang/coding/_hosted_repository_work.py) | C02 | 218 | B | C02 托管与受管运行接入 | 7f15566e9445 | 218 | 7f15566e9445 |
| [_hosted_work_observation.py](../../../../src/loushang/coding/_hosted_work_observation.py) | C02 | 53 | B | C02 托管与受管运行接入 | 1f704eb3af9e | 53 | 1f704eb3af9e |
| [_invocation_product_profile.py](../../../../src/loushang/coding/_invocation_product_profile.py) | C06 | 108 | K | C06 其余根目录入口与策略 | 9673507c092c | 108 | 9673507c092c |
| [_plugin_lifecycle.py](../../../../src/loushang/coding/_plugin_lifecycle.py) | C01 | 2,176 | M | C01 启动、Plugin 与资源装配 | 051d5f64dab3 | 1,163 | 6a85f7bd1ec0 |
| [_plugin_owner_generations.py](../../../../src/loushang/coding/_plugin_owner_generations.py) | C01 | 548 | M | C01 启动、Plugin 与资源装配 | e7fe9e4474dc | 301 | cca9ccac7744 |
| [_plugins/__init__.py](../../../../src/loushang/coding/_plugins/__init__.py) | C22 | 1 | K | C22 内置 Plugin 内容 | 32bed4a0499a | 1 | 32bed4a0499a |
| [_plugins/coding_arch_default/__init__.py](../../../../src/loushang/coding/_plugins/coding_arch_default/__init__.py) | C22 | 1 | K | C22 内置 Plugin 内容 | 0c496748db17 | 1 | 0c496748db17 |
| [_plugins/coding_arch_default/definition.py](../../../../src/loushang/coding/_plugins/coding_arch_default/definition.py) | C22 | 60 | K | C22 内置 Plugin 内容 | 3e95b07a5f4c | 60 | 3e95b07a5f4c |
| [_plugins/coding_base/__init__.py](../../../../src/loushang/coding/_plugins/coding_base/__init__.py) | C22 | 1 | K | C22 内置 Plugin 内容 | 39dbaf55f33f | 1 | 39dbaf55f33f |
| [_plugins/coding_lsp_default/__init__.py](../../../../src/loushang/coding/_plugins/coding_lsp_default/__init__.py) | C22 | 1 | K | C22 内置 Plugin 内容 | a1c04e3ef742 | 1 | a1c04e3ef742 |
| [_plugins/coding_lsp_default/definition.py](../../../../src/loushang/coding/_plugins/coding_lsp_default/definition.py) | C22 | 60 | K | C22 内置 Plugin 内容 | 40f1c97219d2 | 60 | 40f1c97219d2 |
| [_product_capability_plugin_composition.py](../../../../src/loushang/coding/_product_capability_plugin_composition.py) | C01 | 781 | M | C01 启动、Plugin 与资源装配 | d6b4d65c94c5 | 781 | d6b4d65c94c5 |
| [_product_worker_canary.py](../../../../src/loushang/coding/_product_worker_canary.py) | C05 | 1,323 | V | C05 显式 canary 与作者验证入口 | eab63edf23d0 | 854 | f47c7d90b1c9 |
| [_resource_catalog_adapter.py](../../../../src/loushang/coding/_resource_catalog_adapter.py) | C01 | 1,094 | M | C01 启动、Plugin 与资源装配 | 2b8769dc3b26 | 445 | f18b7d57d369 |
| [_resource_catalog_shadow.py](../../../../src/loushang/coding/_resource_catalog_shadow.py) | C01 | 52 | C | C01 启动、Plugin 与资源装配 | e859f501846e | 52 | e859f501846e |
| [_resume_cleanup.py](../../../../src/loushang/coding/_resume_cleanup.py) | C03 | 54 | M | C03 Resume 与 SessionManager | 03dd4945aceb | 54 | 03dd4945aceb |
| [_tool_authority.py](../../../../src/loushang/coding/_tool_authority.py) | C01 | 42 | K | C01 启动、Plugin 与资源装配 | 47847151bc24 | 42 | 47847151bc24 |
| [_worker_tool_identity.py](../../../../src/loushang/coding/_worker_tool_identity.py) | C06 | 5 | K | C06 其余根目录入口与策略 | c1b1add5e98b | 5 | c1b1add5e98b |
| [adapters/__init__.py](../../../../src/loushang/coding/adapters/__init__.py) | C12 | 3 | M | C12 Goal/Work/证据适配 | e9aba5aed4ae | 3 | e9aba5aed4ae |
| [adapters/_goal_calculator.py](../../../../src/loushang/coding/adapters/_goal_calculator.py) | C12 | 603 | M | C12 Goal/Work/证据适配 | e3f69a3c88e7 | 603 | e3f69a3c88e7 |
| [adapters/_goal_delegation.py](../../../../src/loushang/coding/adapters/_goal_delegation.py) | C12 | 520 | M | A81：原 Session/Work 集成；Code 政策/真实类型 | 3d3dfe7c8262 | 225 | a45d6029695f |
| [adapters/_goal_delegation_report.py](../../../../src/loushang/coding/adapters/_goal_delegation_report.py) | C12 | 274 | M | C12 Goal/Work/证据适配 | 1b5ce0b8df47 | 274 | 1b5ce0b8df47 |
| [adapters/_goal_driver.py](../../../../src/loushang/coding/adapters/_goal_driver.py) | C12 | 278 | M | C12 Goal/Work/证据适配 | 4a17c03e9382 | 278 | 4a17c03e9382 |
| [adapters/_goal_execution_context.py](../../../../src/loushang/coding/adapters/_goal_execution_context.py) | C12 | 179 | M | A81：原 Session history bridge；Code 纯选择/codec/证据 | 08589251e563 | 137 | 53775e67498c |
| [adapters/_goal_planning.py](../../../../src/loushang/coding/adapters/_goal_planning.py) | C12 | 259 | M | C12 Goal/Work/证据适配 | 76673cb27a92 | 259 | 76673cb27a92 |
| [adapters/_goal_planning_history.py](../../../../src/loushang/coding/adapters/_goal_planning_history.py) | C12 | 44 | M | C12 Goal/Work/证据适配 | 822452a59e18 | 44 | 822452a59e18 |
| [adapters/_goal_planning_limits.py](../../../../src/loushang/coding/adapters/_goal_planning_limits.py) | C12 | 99 | M | C12 Goal/Work/证据适配 | 6361118f9e51 | 99 | 6361118f9e51 |
| [adapters/_goal_planning_response.py](../../../../src/loushang/coding/adapters/_goal_planning_response.py) | C12 | 45 | M | C12 Goal/Work/证据适配 | 7cdacc26a57b | 45 | 7cdacc26a57b |
| [adapters/_goal_planning_shared.py](../../../../src/loushang/coding/adapters/_goal_planning_shared.py) | C12 | 162 | M | C12 Goal/Work/证据适配 | ef707defac27 | 162 | ef707defac27 |
| [adapters/_goal_planning_work.py](../../../../src/loushang/coding/adapters/_goal_planning_work.py) | C12 | 237 | M | C12 Goal/Work/证据适配 | 35d41406b91d | 237 | 35d41406b91d |
| [adapters/_goal_proposal.py](../../../../src/loushang/coding/adapters/_goal_proposal.py) | C12 | 220 | M | C12 Goal/Work/证据适配 | e48b5eaef6cc | 220 | e48b5eaef6cc |
| [adapters/_goal_repository.py](../../../../src/loushang/coding/adapters/_goal_repository.py) | C12 | 1,423 | M | C12 Goal/Work/证据适配 | 945099f58eab | 1,423 | 945099f58eab |
| [adapters/_goal_repository_driver.py](../../../../src/loushang/coding/adapters/_goal_repository_driver.py) | C12 | 155 | M | C12 Goal/Work/证据适配 | e4e6774a9f1e | 155 | e4e6774a9f1e |
| [adapters/_goal_repository_hosted_task.py](../../../../src/loushang/coding/adapters/_goal_repository_hosted_task.py) | C12 | 191 | M | C12 Goal/Work/证据适配 | 643a69c015b0 | 191 | 643a69c015b0 |
| [adapters/_goal_repository_review.py](../../../../src/loushang/coding/adapters/_goal_repository_review.py) | C12 | 162 | M | C12 Goal/Work/证据适配 | fe9c7a2a1ff5 | 162 | fe9c7a2a1ff5 |
| [adapters/_goal_repository_task.py](../../../../src/loushang/coding/adapters/_goal_repository_task.py) | C12 | 115 | M | C12 Goal/Work/证据适配 | d129c11e56ba | 115 | d129c11e56ba |
| [adapters/_goal_store.py](../../../../src/loushang/coding/adapters/_goal_store.py) | C12 | 138 | M | F06 / G03：HarnessWork 集成；原路径/锁身份保留 | accbdcd03f3f | 28 | e672a4342d8b |
| [adapters/_goal_work_sources.py](../../../../src/loushang/coding/adapters/_goal_work_sources.py) | C12 | 195 | M | C12 Goal/Work/证据适配 | 14d63c19232f | 195 | 14d63c19232f |
| [adapters/_verification_work.py](../../../../src/loushang/coding/adapters/_verification_work.py) | C12 | 478 | M | C12 Goal/Work/证据适配 | 8355b66c521d | 478 | 8355b66c521d |
| [adapters/_work_evidence.py](../../../../src/loushang/coding/adapters/_work_evidence.py) | C12 | 192 | M | C12 Goal/Work/证据适配 | d0579ea163ef | 192 | d0579ea163ef |
| [adapters/goal.py](../../../../src/loushang/coding/adapters/goal.py) | C12 | 878 | M | C12 Goal/Work/证据适配 | 3f8e359671ac | 878 | 3f8e359671ac |
| [adapters/harnesswork.py](../../../../src/loushang/coding/adapters/harnesswork.py) | C12 | 105 | M | C12 Goal/Work/证据适配 | c43b30887df2 | 105 | c43b30887df2 |
| [adapters/interactive_goal.py](../../../../src/loushang/coding/adapters/interactive_goal.py) | C12 | 672 | M | C12 Goal/Work/证据适配 | 6865ef185846 | 672 | 6865ef185846 |
| [agent_invocation.py](../../../../src/loushang/coding/agent_invocation.py) | C06 | 281 | R/M | C06 其余根目录入口与策略 | 45486aa4b4c8 | 281 | 45486aa4b4c8 |
| [apphost_canary.py](../../../../src/loushang/coding/apphost_canary.py) | C05 | 1,012 | V | C05 显式 canary 与作者验证入口 | 002123d7d46b | 1,012 | 002123d7d46b |
| [apphost_composition.py](../../../../src/loushang/coding/apphost_composition.py) | C02 | 583 | B | C02 托管与受管运行接入 | 2531999d9cf0 | 568 | c4ace0de4669 |
| [apphost_product.py](../../../../src/loushang/coding/apphost_product.py) | C02 | 484 | B | C02 托管与受管运行接入 | 712657197d86 | 484 | 712657197d86 |
| [appservice_adapter.py](../../../../src/loushang/coding/appservice_adapter.py) | C02 | 470 | B | C02 托管与受管运行接入 | dbd6fc69114a | 222 | 59dda0f03430 |
| [arch/__init__.py](../../../../src/loushang/coding/arch/__init__.py) | C14 | 79 | K/M | C14 Arch Capability | d13ca5375d94 | 79 | d13ca5375d94 |
| [arch/__main__.py](../../../../src/loushang/coding/arch/__main__.py) | C14 | 8 | K/M | C14 Arch Capability | bad84da03694 | 8 | bad84da03694 |
| [arch/_plugin_tool_owner.py](../../../../src/loushang/coding/arch/_plugin_tool_owner.py) | C14 | 287 | K/M | C14 Arch Capability | 35ebdbcbe510 | 150 | d967ffd82cec |
| [arch/_provider_api.py](../../../../src/loushang/coding/arch/_provider_api.py) | C14 | 614 | K/M | C14 Arch Capability | 894181936fa4 | 599 | be32b58bb2f6 |
| [arch/cache.py](../../../../src/loushang/coding/arch/cache.py) | C14 | 454 | K/M | C14 Arch Capability | e0fa8e9c4abc | 454 | e0fa8e9c4abc |
| [arch/cli.py](../../../../src/loushang/coding/arch/cli.py) | C14 | 193 | K/M | C14 Arch Capability | a2b034e7e325 | 193 | a2b034e7e325 |
| [arch/import_graph.py](../../../../src/loushang/coding/arch/import_graph.py) | C14 | 672 | K/M | C14 Arch Capability | d48e06875474 | 672 | d48e06875474 |
| [arch/model.py](../../../../src/loushang/coding/arch/model.py) | C14 | 148 | K/M | C14 Arch Capability | 06b684585ff3 | 148 | 06b684585ff3 |
| [arch/providers/__init__.py](../../../../src/loushang/coding/arch/providers/__init__.py) | C14 | 13 | K/M | C14 Arch Capability | eba65e0ae1cd | 13 | eba65e0ae1cd |
| [arch/providers/base.py](../../../../src/loushang/coding/arch/providers/base.py) | C14 | 31 | K/M | C14 Arch Capability | 6e8becb3b60b | 31 | 6e8becb3b60b |
| [arch/providers/python.py](../../../../src/loushang/coding/arch/providers/python.py) | C14 | 876 | K/M | C14 Arch Capability | d9bcabaa1b18 | 876 | d9bcabaa1b18 |
| [arch/tool.py](../../../../src/loushang/coding/arch/tool.py) | C14 | 367 | K/M | C14 Arch Capability | 0bf68940fd9a | 367 | 0bf68940fd9a |
| [arch/tool_pack.py](../../../../src/loushang/coding/arch/tool_pack.py) | C14 | 38 | K/M | C14 Arch Capability | 502440220923 | 38 | 502440220923 |
| [bootstrap.py](../../../../src/loushang/coding/bootstrap.py) | C01 | 3,531 | M | C01 启动、Plugin 与资源装配 | ec4749c8f2f0 | 3,531 | cd183bd0c3c1 |
| [capabilities.py](../../../../src/loushang/coding/capabilities.py) | C01 | 85 | K | C01 启动、Plugin 与资源装配 | 6153c385d06f | 85 | 6153c385d06f |
| [cli/__init__.py](../../../../src/loushang/coding/cli/__init__.py) | C11 | 23 | M | C11 CLI | 45c2b744f50c | 23 | 45c2b744f50c |
| [cli/__main__.py](../../../../src/loushang/coding/cli/__main__.py) | C11 | 91 | M | C11 CLI | b2450df4ae4a | 91 | b2450df4ae4a |
| [cli/apphost.py](../../../../src/loushang/coding/cli/apphost.py) | C11 | 162 | M | C11 CLI | 63d7b82c3af7 | 162 | 63d7b82c3af7 |
| [cli/application.py](../../../../src/loushang/coding/cli/application.py) | C11 | 1,697 | M | C11 CLI | d1e825842391 | 1,697 | d1e825842391 |
| [cli/args.py](../../../../src/loushang/coding/cli/args.py) | C11 | 310 | M | C11 CLI | 9eab2abc4a86 | 310 | 9eab2abc4a86 |
| [cli/composition_choice.py](../../../../src/loushang/coding/cli/composition_choice.py) | C11 | 23 | M | C11 CLI | 65b964f0c258 | 23 | 65b964f0c258 |
| [cli/hosted.py](../../../../src/loushang/coding/cli/hosted.py) | C11 | 290 | M | C11 CLI | a12baab90a66 | 290 | a12baab90a66 |
| [cli/hosted_client.py](../../../../src/loushang/coding/cli/hosted_client.py) | C11 | 377 | M | C11 CLI | ffa77827a460 | 377 | ffa77827a460 |
| [cli/lmux.py](../../../../src/loushang/coding/cli/lmux.py) | C11 | 116 | M | C11 CLI | cfdba2301a17 | 116 | cfdba2301a17 |
| [cli/lmux_command.py](../../../../src/loushang/coding/cli/lmux_command.py) | C11 | 811 | M | C11 CLI | 90fe9fa9ddde | 811 | 90fe9fa9ddde |
| [cli/lmux_stop_all.py](../../../../src/loushang/coding/cli/lmux_stop_all.py) | C11 | 125 | M | C11 CLI | 6a8803894cd7 | 34 | 35c0b12cb94d |
| [cli/lsp.py](../../../../src/loushang/coding/cli/lsp.py) | C11 | 195 | M | C11 CLI | 33f4858fe709 | 195 | 33f4858fe709 |
| [cli/multiagent.py](../../../../src/loushang/coding/cli/multiagent.py) | C11 | 295 | M | C11 CLI | 234f559b7d09 | 295 | 234f559b7d09 |
| [cli/multiagent_scripted.py](../../../../src/loushang/coding/cli/multiagent_scripted.py) | C11 | 148 | M | C11 CLI | 7b8d699abde1 | 148 | 7b8d699abde1 |
| [cli/mux.py](../../../../src/loushang/coding/cli/mux.py) | C11 | 258 | M | C11 CLI | e3e2a04252c2 | 258 | e3e2a04252c2 |
| [cli/package_cutover.py](../../../../src/loushang/coding/cli/package_cutover.py) | C11 | 976 | M | C11 CLI | 5f42a0f9e1ad | 976 | 5f42a0f9e1ad |
| [cli/package_gc.py](../../../../src/loushang/coding/cli/package_gc.py) | C11 | 391 | M | C11 CLI | 3eb85096303e | 391 | 3eb85096303e |
| [cli/package_repair.py](../../../../src/loushang/coding/cli/package_repair.py) | C11 | 72 | M | C11 CLI | 0b70bee5c48d | 72 | 0b70bee5c48d |
| [cli/package_worker_native.py](../../../../src/loushang/coding/cli/package_worker_native.py) | C11 | 1,098 | M | C11 CLI | 1799d915325a | 936 | 363ff019b49c |
| [cli/package_worker_windows_candidate.py](../../../../src/loushang/coding/cli/package_worker_windows_candidate.py) | C11 | 874 | M | C11 CLI | 0a0fa4aa42dc | 732 | 51d4a564265e |
| [cli/plugin_private_data.py](../../../../src/loushang/coding/cli/plugin_private_data.py) | C11 | 586 | M | C11 CLI | a0894741f81c | 583 | e9d97da046c4 |
| [cli/profile.py](../../../../src/loushang/coding/cli/profile.py) | C11 | 248 | M | C11 CLI | f05b8d2e1e2e | 248 | f05b8d2e1e2e |
| [cli/screen_startup.py](../../../../src/loushang/coding/cli/screen_startup.py) | C11 | 221 | M | C11 CLI | 4cc56d5f3535 | 221 | 4cc56d5f3535 |
| [cli/startup_route.py](../../../../src/loushang/coding/cli/startup_route.py) | C11 | 98 | M | C11 CLI | 5e25af44d94c | 98 | 5e25af44d94c |
| [cli/workspace.py](../../../../src/loushang/coding/cli/workspace.py) | C11 | 223 | M | C11 CLI | 556e0e0687b0 | 223 | 556e0e0687b0 |
| [compaction/__init__.py](../../../../src/loushang/coding/compaction/__init__.py) | C19 | 7 | R/K | C19 压缩 profile/适配 | 43cc3ac4596a | 7 | 43cc3ac4596a |
| [compaction/adapter.py](../../../../src/loushang/coding/compaction/adapter.py) | C19 | 139 | R/K | C19 压缩 profile/适配 | 1833247b5ad2 | 139 | 1833247b5ad2 |
| [compaction/evaluation.py](../../../../src/loushang/coding/compaction/evaluation.py) | C19 | 28 | R/K | C19 压缩 profile/适配 | 58bf56e8ae92 | 28 | 58bf56e8ae92 |
| [compaction/profiles.py](../../../../src/loushang/coding/compaction/profiles.py) | C19 | 266 | K | C19 压缩 profile/适配 | 5325b9284b25 | 266 | 5325b9284b25 |
| [composition_provenance.py](../../../../src/loushang/coding/composition_provenance.py) | C01 | 214 | M | C01 启动、Plugin 与资源装配 | 30a8b59d8d49 | 214 | 30a8b59d8d49 |
| [composition_sets.py](../../../../src/loushang/coding/composition_sets.py) | C01 | 236 | M | C01 启动、Plugin 与资源装配 | e77cb0ebf1e1 | 236 | e77cb0ebf1e1 |
| [continuity.py](../../../../src/loushang/coding/continuity.py) | C04 | 1,555 | M | C04 Continuity | cb0943f7d549 | 1,359 | 0119e90b2357 |
| [continuity_bootstrap.py](../../../../src/loushang/coding/continuity_bootstrap.py) | C04 | 1,622 | M | C04 Continuity | acbe4067566c | 1,609 | 76e2fc91bd73 |
| [control/__init__.py](../../../../src/loushang/coding/control/__init__.py) | C26 | 39 | R/K | C26 配置兼容导出与路径 | 6bbbc65acf54 | 39 | 6bbbc65acf54 |
| [control/settings_store.py](../../../../src/loushang/coding/control/settings_store.py) | C26 | 13 | K | C26 配置兼容导出与路径 | ff84662c1150 | 13 | ff84662c1150 |
| [diagnostics/__init__.py](../../../../src/loushang/coding/diagnostics/__init__.py) | C20 | 5 | R/K | C20 诊断 profile/呈现 | dbec8c0a2694 | 5 | dbec8c0a2694 |
| [diagnostics/debug_status.py](../../../../src/loushang/coding/diagnostics/debug_status.py) | C20 | 82 | R/K | C20 诊断 profile/呈现 | fad18deb8fe6 | 82 | fad18deb8fe6 |
| [diagnostics/profile.py](../../../../src/loushang/coding/diagnostics/profile.py) | C20 | 146 | R/K | C20 诊断 profile/呈现 | 67f11d759370 | 146 | 67f11d759370 |
| [domain/__init__.py](../../../../src/loushang/coding/domain/__init__.py) | C25 | 23 | R/K | C25 Method Domain 与兼容入口 | a8392e2f5beb | 23 | a8392e2f5beb |
| [domain/app.py](../../../../src/loushang/coding/domain/app.py) | C25 | 45 | R/K | C25 Method Domain 与兼容入口 | 2c0beb794397 | 45 | 2c0beb794397 |
| [domain/work.py](../../../../src/loushang/coding/domain/work.py) | C25 | 4 | C | C25 Method Domain 与兼容入口 | 8bd57b6f20b2 | 4 | 8bd57b6f20b2 |
| [embedded_resume.py](../../../../src/loushang/coding/embedded_resume.py) | C03 | 390 | M | C03 Resume 与 SessionManager | cc89c231ae8e | 390 | cc89c231ae8e |
| [extension_author.py](../../../../src/loushang/coding/extension_author.py) | C05 | 366 | V | C05 显式 canary 与作者验证入口 | cee4f5980761 | 366 | cee4f5980761 |
| [hosted_application.py](../../../../src/loushang/coding/hosted_application.py) | C02 | 932 | B | C02 托管与受管运行接入 | 391f0fc90f4b | 747 | 3917a7d74492 |
| [hosted_bootstrap.py](../../../../src/loushang/coding/hosted_bootstrap.py) | C02 | 316 | B | C02 托管与受管运行接入 | 20d1a3e2578e | 314 | f077f36acb66 |
| [hosted_catalog.py](../../../../src/loushang/coding/hosted_catalog.py) | C02 | 1,221 | B | C02 托管与受管运行接入 | 1a07a14c6e43 | 919 | 4cb2fad8a004 |
| [hosted_continuity.py](../../../../src/loushang/coding/hosted_continuity.py) | C02 | 308 | B | C02 托管与受管运行接入 | b714d619b52d | 289 | d21b24f1d13f |
| [hosted_execution.py](../../../../src/loushang/coding/hosted_execution.py) | C02 | 265 | B | C02 托管与受管运行接入 | 434428f1690d | 345 | 7c10da248cfa |
| [hosted_goal.py](../../../../src/loushang/coding/hosted_goal.py) | C02 | 216 | B | C02 托管与受管运行接入 | 19f9feb3b57a | 216 | 19f9feb3b57a |
| [hosted_goal_application.py](../../../../src/loushang/coding/hosted_goal_application.py) | C02 | 70 | B | C02 托管与受管运行接入 | 9523349199f1 | 70 | 9523349199f1 |
| [hosted_local.py](../../../../src/loushang/coding/hosted_local.py) | C02 | 402 | B | C02 托管与受管运行接入 | b4c35194f8f2 | 214 | a4a8a05a4379 |
| [hosted_method.py](../../../../src/loushang/coding/hosted_method.py) | C02 | 138 | B | C02 托管与受管运行接入 | 3413931a783f | 138 | 3413931a783f |
| [hosted_method_application.py](../../../../src/loushang/coding/hosted_method_application.py) | C02 | 52 | B | C02 托管与受管运行接入 | df02bc67924c | 52 | df02bc67924c |
| [hosted_resume.py](../../../../src/loushang/coding/hosted_resume.py) | C02 | 709 | B | C02 托管与受管运行接入 | 4d862cfad9ec | 751 | 686e2508b64b |
| [hosted_session.py](../../../../src/loushang/coding/hosted_session.py) | C02 | 598 | B | C02 托管与受管运行接入 | 24f236328066 | 657 | 5da05e3c2ee8 |
| [interaction/__init__.py](../../../../src/loushang/coding/interaction/__init__.py) | C18 | 1 | K/M | C18 交互命令与预热 | b9cd83b1e2d9 | 1 | b9cd83b1e2d9 |
| [interaction/goal.py](../../../../src/loushang/coding/interaction/goal.py) | C18 | 287 | K/M | F07：公共观察/控制；保留命令语义 | c780d0713b77 | 287 | c780d0713b77 |
| [interaction/resume_history.py](../../../../src/loushang/coding/interaction/resume_history.py) | C18 | 335 | K/M | C18 交互命令与预热 | e454b90d7f61 | 335 | e454b90d7f61 |
| [interaction/sdk_warmup.py](../../../../src/loushang/coding/interaction/sdk_warmup.py) | C18 | 184 | K/M | C18 交互命令与预热 | d2b83176982e | 184 | d2b83176982e |
| [interaction/settings_profile.py](../../../../src/loushang/coding/interaction/settings_profile.py) | C18 | 67 | K | C18 交互命令与预热 | 2ec5e1e25f9b | 67 | 2ec5e1e25f9b |
| [lsp/__init__.py](../../../../src/loushang/coding/lsp/__init__.py) | C13 | 119 | K/M | C13 LSP Capability | e3447984912e | 119 | e3447984912e |
| [lsp/_deferred_generation.py](../../../../src/loushang/coding/lsp/_deferred_generation.py) | C13 | 331 | K/M | C13 LSP Capability | 1eb9c229a6c2 | 331 | 1eb9c229a6c2 |
| [lsp/_plugin_opt_in.py](../../../../src/loushang/coding/lsp/_plugin_opt_in.py) | C13 | 315 | K/M | C13 LSP Capability | 9c48ade1a4bb | 315 | 9c48ade1a4bb |
| [lsp/_plugin_tool_owner.py](../../../../src/loushang/coding/lsp/_plugin_tool_owner.py) | C13 | 292 | K/M | C13 LSP Capability | cf2683d4d40d | 153 | ecab47538960 |
| [lsp/_provider_api.py](../../../../src/loushang/coding/lsp/_provider_api.py) | C13 | 528 | K/M | C13 LSP Capability | 3c4dd6977507 | 502 | 80ec8935588f |
| [lsp/binding.py](../../../../src/loushang/coding/lsp/binding.py) | C13 | 157 | K/M | C13 LSP Capability | b55f56930d77 | 157 | b55f56930d77 |
| [lsp/catalog.py](../../../../src/loushang/coding/lsp/catalog.py) | C13 | 30 | K/M | C13 LSP Capability | 512fe3eee1e4 | 30 | 512fe3eee1e4 |
| [lsp/client.py](../../../../src/loushang/coding/lsp/client.py) | C13 | 525 | K/M | C13 LSP Capability | b15726b74e15 | 525 | b15726b74e15 |
| [lsp/commands.py](../../../../src/loushang/coding/lsp/commands.py) | C13 | 161 | K/M | C13 LSP Capability | 065ec24aa53a | 161 | 065ec24aa53a |
| [lsp/definition_codec.py](../../../../src/loushang/coding/lsp/definition_codec.py) | C13 | 181 | K/M | C13 LSP Capability | 3d0bd53bb359 | 181 | 3d0bd53bb359 |
| [lsp/diagnostics.py](../../../../src/loushang/coding/lsp/diagnostics.py) | C13 | 456 | K/M | C13 LSP Capability | 4fd63dad6f82 | 456 | 4fd63dad6f82 |
| [lsp/discovery.py](../../../../src/loushang/coding/lsp/discovery.py) | C13 | 491 | K/M | C13 LSP Capability | dc810b99f370 | 491 | dc810b99f370 |
| [lsp/documents.py](../../../../src/loushang/coding/lsp/documents.py) | C13 | 157 | K/M | C13 LSP Capability | d677ac9e513e | 157 | d677ac9e513e |
| [lsp/model.py](../../../../src/loushang/coding/lsp/model.py) | C13 | 313 | K/M | C13 LSP Capability | 7cbf95131318 | 313 | 7cbf95131318 |
| [lsp/ports.py](../../../../src/loushang/coding/lsp/ports.py) | C13 | 32 | K/M | C13 LSP Capability | 74e987386c9d | 60 | 6f4674d4cfb7 |
| [lsp/positions.py](../../../../src/loushang/coding/lsp/positions.py) | C13 | 104 | K/M | C13 LSP Capability | d5be36765f3c | 104 | d5be36765f3c |
| [lsp/runtime.py](../../../../src/loushang/coding/lsp/runtime.py) | C13 | 165 | K/M | C13 LSP Capability | 8c28dd4d5a25 | 165 | 8c28dd4d5a25 |
| [lsp/selector.py](../../../../src/loushang/coding/lsp/selector.py) | C13 | 217 | K/M | C13 LSP Capability | a2c5726dce90 | 217 | a2c5726dce90 |
| [lsp/status.py](../../../../src/loushang/coding/lsp/status.py) | C13 | 62 | K/M | C13 LSP Capability | 7dddf17a5409 | 62 | 7dddf17a5409 |
| [lsp/supervisor.py](../../../../src/loushang/coding/lsp/supervisor.py) | C13 | 441 | K/M | C13 LSP Capability | 24675a3ef20a | 441 | 24675a3ef20a |
| [lsp/tools.py](../../../../src/loushang/coding/lsp/tools.py) | C13 | 752 | K/M | C13 LSP Capability | 01c821d48cfa | 728 | 62414981154f |
| [managed_bootstrap.py](../../../../src/loushang/coding/managed_bootstrap.py) | C02 | 149 | B | C02 托管与受管运行接入 | caf5eed49a10 | 149 | caf5eed49a10 |
| [managed_catalog.py](../../../../src/loushang/coding/managed_catalog.py) | C02 | 301 | B | C02 托管与受管运行接入 | f59741d1cc8f | 228 | e392695cb5f3 |
| [managed_local.py](../../../../src/loushang/coding/managed_local.py) | C02 | 172 | B | C02 托管与受管运行接入 | 92b01ff32c7a | 172 | 877cf0d8f9d6 |
| [managed_process.py](../../../../src/loushang/coding/managed_process.py) | C02 | 164 | B | C02 托管与受管运行接入 | 5d34ff8a9094 | 164 | 5d34ff8a9094 |
| [model_reasoning.py](../../../../src/loushang/coding/model_reasoning.py) | C06 | 68 | R/M | C06 其余根目录入口与策略 | c6b15f1173ea | 68 | c6b15f1173ea |
| [model_reasoning_tui.py](../../../../src/loushang/coding/model_reasoning_tui.py) | C06 | 59 | R/M | C06 其余根目录入口与策略 | afb1a65f8e2d | 59 | afb1a65f8e2d |
| [model_selection.py](../../../../src/loushang/coding/model_selection.py) | C06 | 67 | R/M | C06 其余根目录入口与策略 | b60f807a5d06 | 67 | b60f807a5d06 |
| [model_selection_tui.py](../../../../src/loushang/coding/model_selection_tui.py) | C06 | 90 | R/M | C06 其余根目录入口与策略 | ce44a3b0da1c | 90 | ce44a3b0da1c |
| [multiagent.py](../../../../src/loushang/coding/multiagent.py) | C06 | 504 | R/M | C06 其余根目录入口与策略 | a0763bed7060 | 504 | a0763bed7060 |
| [package_arch_private_cache.py](../../../../src/loushang/coding/package_arch_private_cache.py) | C08 | 55 | M | C08 插件私有数据生命周期 | 9561cb995b7a | 20 | 0b03cd6d9e3a |
| [package_builtin_wheel.py](../../../../src/loushang/coding/package_builtin_wheel.py) | C10 | 676 | M | C10 包分发与 Product 管理 | 622f4c2d40a0 | 395 | 9304ae4b9634 |
| [package_cutover_backup.py](../../../../src/loushang/coding/package_cutover_backup.py) | C09 | 147 | E | C09 历史兼容、迁移与快照证据 | d723f57d2696 | 147 | d723f57d2696 |
| [package_epoch_layout.py](../../../../src/loushang/coding/package_epoch_layout.py) | C09 | 301 | E | C09 历史兼容、迁移与快照证据 | 7f63c4dc5354 | 301 | 7f63c4dc5354 |
| [package_external_data_wheel.py](../../../../src/loushang/coding/package_external_data_wheel.py) | C10 | 462 | M | C10 包分发与 Product 管理 | ab860fc3d3c3 | 229 | 1df2fa2e71df |
| [package_external_dependency_wheel.py](../../../../src/loushang/coding/package_external_dependency_wheel.py) | C10 | 581 | M | C10 包分发与 Product 管理 | 99b008eb9a09 | 308 | 0a262d4e15f5 |
| [package_external_worker_wheel.py](../../../../src/loushang/coding/package_external_worker_wheel.py) | C10 | 868 | M | C10 包分发与 Product 管理 | 1a621db19167 | 436 | eaf10b3c6f98 |
| [package_installation_private_data.py](../../../../src/loushang/coding/package_installation_private_data.py) | C08 | 674 | M | C08 插件私有数据生命周期 | f741b1286b3d | 328 | aaa4b44f76a3 |
| [package_legacy_binding_catalog.py](../../../../src/loushang/coding/package_legacy_binding_catalog.py) | C09 | 744 | E | C09 历史兼容、迁移与快照证据 | 9ced8152a9dc | 391 | 90f0f002d54d |
| [package_legacy_builtin_acceptance.py](../../../../src/loushang/coding/package_legacy_builtin_acceptance.py) | C09 | 317 | E | C09 历史兼容、迁移与快照证据 | b8bbad381113 | 275 | 78f3dde60d3e |
| [package_legacy_builtin_adoption.py](../../../../src/loushang/coding/package_legacy_builtin_adoption.py) | C09 | 215 | E | C09 历史兼容、迁移与快照证据 | 41bc0cee7ebc | 215 | 41bc0cee7ebc |
| [package_legacy_builtin_review.py](../../../../src/loushang/coding/package_legacy_builtin_review.py) | C09 | 434 | E | C09 历史兼容、迁移与快照证据 | 979f76f01b5e | 436 | 1dc190bcf1cd |
| [package_legacy_classification.py](../../../../src/loushang/coding/package_legacy_classification.py) | C09 | 203 | E | C09 历史兼容、迁移与快照证据 | efa857728df5 | 203 | efa857728df5 |
| [package_legacy_configured_source.py](../../../../src/loushang/coding/package_legacy_configured_source.py) | C09 | 93 | E | C09 历史兼容、迁移与快照证据 | d21c5f7d69c7 | 93 | d21c5f7d69c7 |
| [package_legacy_data_trust.py](../../../../src/loushang/coding/package_legacy_data_trust.py) | C09 | 40 | E | C09 历史兼容、迁移与快照证据 | eb60c67cd4e4 | 40 | eb60c67cd4e4 |
| [package_legacy_desired_evidence.py](../../../../src/loushang/coding/package_legacy_desired_evidence.py) | C09 | 108 | E | C09 历史兼容、迁移与快照证据 | f6e6e2f22d75 | 105 | 2c0e7a5e9a64 |
| [package_legacy_disabled_acceptance.py](../../../../src/loushang/coding/package_legacy_disabled_acceptance.py) | C09 | 374 | E | C09 历史兼容、迁移与快照证据 | cf9a32592c64 | 264 | d0368ddbadea |
| [package_legacy_disabled_review.py](../../../../src/loushang/coding/package_legacy_disabled_review.py) | C09 | 184 | E | C09 历史兼容、迁移与快照证据 | c22756eedbd3 | 184 | c22756eedbd3 |
| [package_legacy_installation_inventory.py](../../../../src/loushang/coding/package_legacy_installation_inventory.py) | C09 | 514 | E | C09 历史兼容、迁移与快照证据 | 95e2d383262d | 514 | 95e2d383262d |
| [package_legacy_instance_evidence.py](../../../../src/loushang/coding/package_legacy_instance_evidence.py) | C09 | 94 | E | C09 历史兼容、迁移与快照证据 | 6f8ef6768e31 | 94 | 6f8ef6768e31 |
| [package_legacy_local_acceptance.py](../../../../src/loushang/coding/package_legacy_local_acceptance.py) | C09 | 553 | E | C09 历史兼容、迁移与快照证据 | c9e2dd4611ce | 542 | 777c906ae3d1 |
| [package_legacy_local_adoption.py](../../../../src/loushang/coding/package_legacy_local_adoption.py) | C09 | 391 | E | C09 历史兼容、迁移与快照证据 | 4520a048b922 | 391 | 4520a048b922 |
| [package_legacy_local_adoption_read.py](../../../../src/loushang/coding/package_legacy_local_adoption_read.py) | C09 | 287 | E | C09 历史兼容、迁移与快照证据 | d610506d1d8d | 287 | d610506d1d8d |
| [package_legacy_local_binding_owner.py](../../../../src/loushang/coding/package_legacy_local_binding_owner.py) | C09 | 120 | E | C09 历史兼容、迁移与快照证据 | 31bf7110fa83 | 120 | 31bf7110fa83 |
| [package_legacy_local_installation.py](../../../../src/loushang/coding/package_legacy_local_installation.py) | C09 | 464 | E | C09 历史兼容、迁移与快照证据 | 18df309776e4 | 464 | 18df309776e4 |
| [package_legacy_local_wheel.py](../../../../src/loushang/coding/package_legacy_local_wheel.py) | C09 | 273 | E | C09 历史兼容、迁移与快照证据 | e77caeeccbc1 | 273 | e77caeeccbc1 |
| [package_legacy_lock_evidence.py](../../../../src/loushang/coding/package_legacy_lock_evidence.py) | C09 | 186 | E | C09 历史兼容、迁移与快照证据 | 78bfb61a21c1 | 183 | eb3f3a2ed5e5 |
| [package_legacy_operation_evidence.py](../../../../src/loushang/coding/package_legacy_operation_evidence.py) | C09 | 271 | E | C09 历史兼容、迁移与快照证据 | 4e5551fa7c06 | 271 | 4e5551fa7c06 |
| [package_legacy_reacquisition.py](../../../../src/loushang/coding/package_legacy_reacquisition.py) | C09 | 90 | E | C09 历史兼容、迁移与快照证据 | e7c83f8bf878 | 90 | e7c83f8bf878 |
| [package_legacy_removed_acceptance.py](../../../../src/loushang/coding/package_legacy_removed_acceptance.py) | C09 | 239 | E | C09 历史兼容、迁移与快照证据 | 0b5a3f8f3390 | 200 | 820b804cf717 |
| [package_legacy_removed_adoption.py](../../../../src/loushang/coding/package_legacy_removed_adoption.py) | C09 | 157 | E | C09 历史兼容、迁移与快照证据 | 15d2f1b31525 | 157 | 15d2f1b31525 |
| [package_legacy_removed_review.py](../../../../src/loushang/coding/package_legacy_removed_review.py) | C09 | 800 | E | C09 历史兼容、迁移与快照证据 | 4a989c4b6081 | 788 | 1bd5ab770d13 |
| [package_legacy_review.py](../../../../src/loushang/coding/package_legacy_review.py) | C09 | 460 | E | C09 历史兼容、迁移与快照证据 | 14371b2b2cb2 | 409 | 546c8b961bc0 |
| [package_legacy_skill_cutover_admission.py](../../../../src/loushang/coding/package_legacy_skill_cutover_admission.py) | C09 | 594 | E | C09 历史兼容、迁移与快照证据 | bc855a8e6bb0 | 594 | bc855a8e6bb0 |
| [package_legacy_snapshot_member.py](../../../../src/loushang/coding/package_legacy_snapshot_member.py) | C09 | 198 | E | C09 历史兼容、迁移与快照证据 | d86ab52e1964 | 198 | d86ab52e1964 |
| [package_legacy_source_consumption.py](../../../../src/loushang/coding/package_legacy_source_consumption.py) | C09 | 400 | E | C09 历史兼容、迁移与快照证据 | 362fb2103c5f | 397 | d67c5d253851 |
| [package_legacy_source_evidence.py](../../../../src/loushang/coding/package_legacy_source_evidence.py) | C09 | 142 | E | C09 历史兼容、迁移与快照证据 | 3fc875a324a0 | 140 | 200468832d50 |
| [package_legacy_windows_receipt.py](../../../../src/loushang/coding/package_legacy_windows_receipt.py) | C09 | 289 | E | C09 历史兼容、迁移与快照证据 | ebb5b40e0b99 | 67 | ea1d662e1563 |
| [package_pre_b_snapshot.py](../../../../src/loushang/coding/package_pre_b_snapshot.py) | C09 | 448 | E | C09 历史兼容、迁移与快照证据 | bf7cef184eb2 | 448 | bf7cef184eb2 |
| [package_private_data_backup.py](../../../../src/loushang/coding/package_private_data_backup.py) | C08 | 645 | M | C08 插件私有数据生命周期 | 233a09f3c323 | 343 | e4ff1a50356c |
| [package_private_data_backup_expiry.py](../../../../src/loushang/coding/package_private_data_backup_expiry.py) | C08 | 439 | M | C08 插件私有数据生命周期 | 91576e5df2d4 | 296 | 510d911e70c9 |
| [package_private_data_backup_expiry_journal.py](../../../../src/loushang/coding/package_private_data_backup_expiry_journal.py) | C08 | 365 | M | C08 插件私有数据生命周期 | 6a30e4025bcd | 190 | de96a7fc13d5 |
| [package_private_data_backup_expiry_records.py](../../../../src/loushang/coding/package_private_data_backup_expiry_records.py) | C08 | 298 | M | C08 插件私有数据生命周期 | 4f3587739ef2 | 255 | bac8313a4256 |
| [package_private_data_backup_records.py](../../../../src/loushang/coding/package_private_data_backup_records.py) | C08 | 115 | M | C08 插件私有数据生命周期 | d5b20131323e | 98 | 29dec2901678 |
| [package_private_data_backup_sdk.py](../../../../src/loushang/coding/package_private_data_backup_sdk.py) | C08 | 338 | M | C08 插件私有数据生命周期 | 54d135a1e6f1 | 338 | 54d135a1e6f1 |
| [package_private_data_deletion_journal.py](../../../../src/loushang/coding/package_private_data_deletion_journal.py) | C08 | 403 | M | C08 插件私有数据生命周期 | ab35480c5292 | 119 | 10ae5cd84e76 |
| [package_private_data_deletion_owner.py](../../../../src/loushang/coding/package_private_data_deletion_owner.py) | C08 | 335 | M | C08 插件私有数据生命周期 | 128575d2bb6a | 188 | 9362ad25c56d |
| [package_private_data_deletion_preview.py](../../../../src/loushang/coding/package_private_data_deletion_preview.py) | C08 | 360 | M | C08 插件私有数据生命周期 | 7ba10c207e55 | 158 | dda1cdf96e64 |
| [package_private_data_read_owner.py](../../../../src/loushang/coding/package_private_data_read_owner.py) | C08 | 420 | M | C08 插件私有数据生命周期 | 305ec56336c6 | 289 | 255dbd996765 |
| [package_private_data_restore.py](../../../../src/loushang/coding/package_private_data_restore.py) | C08 | 536 | M | C08 插件私有数据生命周期 | d77777f3e7f2 | 366 | 12787d1d244b |
| [package_private_data_restore_confirmation.py](../../../../src/loushang/coding/package_private_data_restore_confirmation.py) | C08 | 326 | M | C08 插件私有数据生命周期 | 84f44f1155d4 | 249 | fc7c6cc8285e |
| [package_private_data_restore_journal.py](../../../../src/loushang/coding/package_private_data_restore_journal.py) | C08 | 364 | M | C08 插件私有数据生命周期 | 9d6aea123669 | 192 | 75c1d9a0b286 |
| [package_private_data_restore_records.py](../../../../src/loushang/coding/package_private_data_restore_records.py) | C08 | 93 | M | C08 插件私有数据生命周期 | 23f5fb8d03a7 | 81 | c4e3b3002ffd |
| [package_private_data_windows_archive_snapshot.py](../../../../src/loushang/coding/package_private_data_windows_archive_snapshot.py) | C08 | 254 | M | C08 插件私有数据生命周期 | 4c1ca1208e7b | 123 | bec6862c333f |
| [package_private_data_windows_backup.py](../../../../src/loushang/coding/package_private_data_windows_backup.py) | C08 | 906 | M | C08 插件私有数据生命周期 | 6e8471c49953 | 376 | f42849cd1c01 |
| [package_private_data_windows_backup_client.py](../../../../src/loushang/coding/package_private_data_windows_backup_client.py) | C08 | 344 | M | C08 插件私有数据生命周期 | 602a215d2e2d | 344 | 602a215d2e2d |
| [package_private_data_windows_backup_expiry_journal.py](../../../../src/loushang/coding/package_private_data_windows_backup_expiry_journal.py) | C08 | 427 | M | C08 插件私有数据生命周期 | 2f103b9d42fa | 314 | 038429b88b6d |
| [package_private_data_windows_backup_expiry_owner.py](../../../../src/loushang/coding/package_private_data_windows_backup_expiry_owner.py) | C08 | 446 | M | C08 插件私有数据生命周期 | da3e5ffd2289 | 103 | 2f1e8c354029 |
| [package_private_data_windows_backup_expiry_preview.py](../../../../src/loushang/coding/package_private_data_windows_backup_expiry_preview.py) | C08 | 178 | M | C08 插件私有数据生命周期 | 6c62ff896dab | 164 | 47ac46b1ce06 |
| [package_private_data_windows_backup_expiry_recovery.py](../../../../src/loushang/coding/package_private_data_windows_backup_expiry_recovery.py) | C08 | 164 | M | C08 插件私有数据生命周期 | 7692f6b5e893 | 140 | 00b06e0a9851 |
| [package_private_data_windows_confirmation.py](../../../../src/loushang/coding/package_private_data_windows_confirmation.py) | C08 | 233 | M | C08 插件私有数据生命周期 | 9b8a4c5cd029 | 216 | a622a29f0ae8 |
| [package_private_data_windows_deletion_journal.py](../../../../src/loushang/coding/package_private_data_windows_deletion_journal.py) | C08 | 652 | M | C08 插件私有数据生命周期 | d05609ed7651 | 344 | 73c3b7602362 |
| [package_private_data_windows_deletion_owner.py](../../../../src/loushang/coding/package_private_data_windows_deletion_owner.py) | C08 | 418 | M | C08 插件私有数据生命周期 | effd9ee759e0 | 156 | 8a90257f6c98 |
| [package_private_data_windows_preview.py](../../../../src/loushang/coding/package_private_data_windows_preview.py) | C08 | 353 | M | C08 插件私有数据生命周期 | d9b75263091f | 171 | bfc6bb4cae47 |
| [package_private_data_windows_restore_journal.py](../../../../src/loushang/coding/package_private_data_windows_restore_journal.py) | C08 | 835 | M | C08 插件私有数据生命周期 | 4e8b33f4c7f3 | 353 | 8630a14cd662 |
| [package_private_data_windows_restore_owner.py](../../../../src/loushang/coding/package_private_data_windows_restore_owner.py) | C08 | 356 | M | C08 插件私有数据生命周期 | 82a4b6a69415 | 79 | 036ae65f6ea7 |
| [package_private_data_windows_restore_preview.py](../../../../src/loushang/coding/package_private_data_windows_restore_preview.py) | C08 | 180 | M | C08 插件私有数据生命周期 | e4845513e143 | 143 | 6b6f42f0070b |
| [package_product_backup_types.py](../../../../src/loushang/coding/package_product_backup_types.py) | C08 | 259 | M | C08 插件私有数据生命周期 | 6ddc9d882c1c | 207 | d2dd305ee9f8 |
| [package_product_cli.py](../../../../src/loushang/coding/package_product_cli.py) | C10 | 467 | M | C10 包分发与 Product 管理 | 99e20c686e5f | 467 | 99e20c686e5f |
| [package_product_management_cli.py](../../../../src/loushang/coding/package_product_management_cli.py) | C10 | 548 | M | C10 包分发与 Product 管理 | fa812374945e | 548 | fa812374945e |
| [package_product_preview.py](../../../../src/loushang/coding/package_product_preview.py) | C10 | 668 | M | C10 包分发与 Product 管理 | 9a98648bd20d | 668 | 9a98648bd20d |
| [package_product_repair.py](../../../../src/loushang/coding/package_product_repair.py) | C10 | 321 | M | C10 包分发与 Product 管理 | 2c060b56dfaf | 321 | 2c060b56dfaf |
| [package_product_repair_rpc.py](../../../../src/loushang/coding/package_product_repair_rpc.py) | C10 | 49 | M | C10 包分发与 Product 管理 | 74413ce3f304 | 49 | 74413ce3f304 |
| [package_product_repair_ui.py](../../../../src/loushang/coding/package_product_repair_ui.py) | C10 | 86 | M | C10 包分发与 Product 管理 | f38309028385 | 86 | f38309028385 |
| [package_product_revisions.py](../../../../src/loushang/coding/package_product_revisions.py) | C10 | 442 | M | C10 包分发与 Product 管理 | 30e7ae99295b | 219 | 9818e5b9c3e5 |
| [package_product_runtime.py](../../../../src/loushang/coding/package_product_runtime.py) | C10 | 1,996 | M | C10 包分发与 Product 管理 | 952f0b207e63 | 1,820 | 610687ddff85 |
| [package_product_worker_activation_base_v2.py](../../../../src/loushang/coding/package_product_worker_activation_base_v2.py) | C07 | 235 | M | C07 插件 Worker 执行/持久化/恢复 | b3f853b2bbd9 | 40 | 292f936dd640 |
| [package_product_worker_activation_history.py](../../../../src/loushang/coding/package_product_worker_activation_history.py) | C07 | 220 | M | C07 插件 Worker 执行/持久化/恢复 | 3e6790b5e95c | 53 | 099d09070547 |
| [package_product_worker_activation_state.py](../../../../src/loushang/coding/package_product_worker_activation_state.py) | C07 | 114 | M | C07 插件 Worker 执行/持久化/恢复 | 2313329e19ac | 113 | eec2f762e20b |
| [package_product_worker_activation_state_journal.py](../../../../src/loushang/coding/package_product_worker_activation_state_journal.py) | C07 | 550 | M | C07 插件 Worker 执行/持久化/恢复 | d2edfb41f5bf | 88 | 4fd7c3dc7f21 |
| [package_product_worker_capability.py](../../../../src/loushang/coding/package_product_worker_capability.py) | C07 | 151 | M | C07 插件 Worker 执行/持久化/恢复 | 63fcc8603aff | 151 | 63fcc8603aff |
| [package_product_worker_cleanup_evidence.py](../../../../src/loushang/coding/package_product_worker_cleanup_evidence.py) | C07 | 252 | M | C07 插件 Worker 执行/持久化/恢复 | 4c30a41c6675 | 113 | b89b1fbcb8f4 |
| [package_product_worker_crash_c5_settlement.py](../../../../src/loushang/coding/package_product_worker_crash_c5_settlement.py) | C07 | 327 | M | C07 插件 Worker 执行/持久化/恢复 | 0abac69de136 | 102 | 41077849012c |
| [package_product_worker_discovery.py](../../../../src/loushang/coding/package_product_worker_discovery.py) | C07 | 251 | M | C07 插件 Worker 执行/持久化/恢复 | b982245e45b4 | 95 | f4077a3f60cb |
| [package_product_worker_gc_references.py](../../../../src/loushang/coding/package_product_worker_gc_references.py) | C07 | 55 | M | C07 插件 Worker 执行/持久化/恢复 | e325fde0e88f | 45 | 7059ada651a2 |
| [package_product_worker_history_checkpoint.py](../../../../src/loushang/coding/package_product_worker_history_checkpoint.py) | C07 | 1,013 | M | C07 插件 Worker 执行/持久化/恢复 | b74b219a6c0e | 303 | c3acfc91161f |
| [package_product_worker_history_checkpoint_anchor.py](../../../../src/loushang/coding/package_product_worker_history_checkpoint_anchor.py) | C07 | 186 | M | C07 插件 Worker 执行/持久化/恢复 | c161d36598bf | 66 | 8513a52c3049 |
| [package_product_worker_history_commit_v2.py](../../../../src/loushang/coding/package_product_worker_history_commit_v2.py) | C07 | 176 | M | C07 插件 Worker 执行/持久化/恢复 | 4437860551cc | 138 | 479e558878a6 |
| [package_product_worker_history_cutover_v2.py](../../../../src/loushang/coding/package_product_worker_history_cutover_v2.py) | C07 | 780 | M | C07 插件 Worker 执行/持久化/恢复 | 7fabfa560238 | 99 | fba1726c1864 |
| [package_product_worker_history_deletion_v2.py](../../../../src/loushang/coding/package_product_worker_history_deletion_v2.py) | C07 | 164 | M | C07 插件 Worker 执行/持久化/恢复 | c4a527322d27 | 34 | 83d65b02793d |
| [package_product_worker_history_preflight_v2.py](../../../../src/loushang/coding/package_product_worker_history_preflight_v2.py) | C07 | 214 | M | C07 插件 Worker 执行/持久化/恢复 | 9ceb5836b967 | 214 | 9ceb5836b967 |
| [package_product_worker_history_prepared_v2.py](../../../../src/loushang/coding/package_product_worker_history_prepared_v2.py) | C07 | 416 | M | C07 插件 Worker 执行/持久化/恢复 | 38519e369104 | 112 | 0c9499739d7f |
| [package_product_worker_history_read_v2.py](../../../../src/loushang/coding/package_product_worker_history_read_v2.py) | C07 | 296 | M | C07 插件 Worker 执行/持久化/恢复 | cc87f77047d6 | 98 | b03ed700f6df |
| [package_product_worker_history_retention.py](../../../../src/loushang/coding/package_product_worker_history_retention.py) | C07 | 845 | M | C07 插件 Worker 执行/持久化/恢复 | 930a0306588a | 379 | 41185ee59c09 |
| [package_product_worker_history_retire_v2.py](../../../../src/loushang/coding/package_product_worker_history_retire_v2.py) | C07 | 159 | M | C07 插件 Worker 执行/持久化/恢复 | af7b38838bfd | 88 | 9c2ebb253e17 |
| [package_product_worker_history_retirement_preview.py](../../../../src/loushang/coding/package_product_worker_history_retirement_preview.py) | C07 | 176 | M | C07 插件 Worker 执行/持久化/恢复 | 2d346624c4ac | 71 | 43f82f028923 |
| [package_product_worker_history_rotate_v2.py](../../../../src/loushang/coding/package_product_worker_history_rotate_v2.py) | C07 | 217 | M | C07 插件 Worker 执行/持久化/恢复 | 72d7cf50fa53 | 214 | 6885e0821f3c |
| [package_product_worker_history_segments.py](../../../../src/loushang/coding/package_product_worker_history_segments.py) | C07 | 730 | M | C07 插件 Worker 执行/持久化/恢复 | 9d01806c9a77 | 18 | 8b7d1f65b1b2 |
| [package_product_worker_history_stage_v2.py](../../../../src/loushang/coding/package_product_worker_history_stage_v2.py) | C07 | 489 | M | C07 插件 Worker 执行/持久化/恢复 | 8740267838bb | 178 | 3d0291b173f5 |
| [package_product_worker_history_stream_snapshot.py](../../../../src/loushang/coding/package_product_worker_history_stream_snapshot.py) | C07 | 434 | M | C07 插件 Worker 执行/持久化/恢复 | 669d2f96ca85 | 120 | b48985a3c72f |
| [package_product_worker_history_v2_names.py](../../../../src/loushang/coding/package_product_worker_history_v2_names.py) | C07 | 49 | M | C07 插件 Worker 执行/持久化/恢复 | 5d504179e35a | 4 | 07827bde40ad |
| [package_product_worker_installed_native.py](../../../../src/loushang/coding/package_product_worker_installed_native.py) | C07 | 472 | M | C07 插件 Worker 执行/持久化/恢复 | aff4fbe827bd | 151 | 35c65f17e487 |
| [package_product_worker_native_approval.py](../../../../src/loushang/coding/package_product_worker_native_approval.py) | C07 | 473 | M | C07 插件 Worker 执行/持久化/恢复 | 1236a4a09d28 | 242 | 55b39813c744 |
| [package_product_worker_native_install.py](../../../../src/loushang/coding/package_product_worker_native_install.py) | C07 | 440 | M | C07 插件 Worker 执行/持久化/恢复 | f8df22d51d92 | 74 | 6c1d9e1548fc |
| [package_product_worker_native_release.py](../../../../src/loushang/coding/package_product_worker_native_release.py) | C07 | 201 | M | C07 插件 Worker 执行/持久化/恢复 | 6de1cf22207c | 83 | e35589d29221 |
| [package_product_worker_no_effect_archive_v2.py](../../../../src/loushang/coding/package_product_worker_no_effect_archive_v2.py) | C07 | 262 | M | C07 插件 Worker 执行/持久化/恢复 | b3710a5bd2ef | 74 | c8b82cab8cd8 |
| [package_product_worker_no_effect_closure.py](../../../../src/loushang/coding/package_product_worker_no_effect_closure.py) | C07 | 49 | M | C07 插件 Worker 执行/持久化/恢复 | b7b1f104aa6c | 31 | bd9fbeede423 |
| [package_product_worker_operator_query.py](../../../../src/loushang/coding/package_product_worker_operator_query.py) | C07 | 513 | M | C07 插件 Worker 执行/持久化/恢复 | f36fa09c6341 | 373 | e6d991db695a |
| [package_product_worker_opt_in.py](../../../../src/loushang/coding/package_product_worker_opt_in.py) | C07 | 910 | M | C07 插件 Worker 执行/持久化/恢复 | 5851cc8774a0 | 208 | 83b52ccb430f |
| [package_product_worker_opt_in_base_v2.py](../../../../src/loushang/coding/package_product_worker_opt_in_base_v2.py) | C07 | 247 | M | C07 插件 Worker 执行/持久化/恢复 | dbfc16fd08d8 | 49 | 5c95fcd66653 |
| [package_product_worker_opt_in_owner.py](../../../../src/loushang/coding/package_product_worker_opt_in_owner.py) | C07 | 223 | M | C07 插件 Worker 执行/持久化/恢复 | 3869f1eeacad | 147 | d240bd0acbc7 |
| [package_product_worker_ordinary_bootstrap.py](../../../../src/loushang/coding/package_product_worker_ordinary_bootstrap.py) | C07 | 312 | M | C07 插件 Worker 执行/持久化/恢复 | 7d97151fe500 | 312 | 7d97151fe500 |
| [package_product_worker_ordinary_error.py](../../../../src/loushang/coding/package_product_worker_ordinary_error.py) | C07 | 12 | M | C07 插件 Worker 执行/持久化/恢复 | 69d14f793272 | 12 | 69d14f793272 |
| [package_product_worker_payload.py](../../../../src/loushang/coding/package_product_worker_payload.py) | C07 | 2,360 | M | C07 插件 Worker 执行/持久化/恢复 | 331b1fd4706a | 882 | ddf52f41ca7b |
| [package_product_worker_pending_host.py](../../../../src/loushang/coding/package_product_worker_pending_host.py) | C07 | 473 | M | C07 插件 Worker 执行/持久化/恢复 | 08074e856b21 | 233 | 4ca1a95b2543 |
| [package_product_worker_policy.py](../../../../src/loushang/coding/package_product_worker_policy.py) | C07 | 335 | M | C07 插件 Worker 执行/持久化/恢复 | 1b9092a94b4f | 335 | 1b9092a94b4f |
| [package_product_worker_posix_gc_history.py](../../../../src/loushang/coding/package_product_worker_posix_gc_history.py) | C07 | 343 | M | C07 插件 Worker 执行/持久化/恢复 | 3e4710cfe431 | 60 | 565127c20648 |
| [package_product_worker_provider.py](../../../../src/loushang/coding/package_product_worker_provider.py) | C07 | 288 | M | C07 插件 Worker 执行/持久化/恢复 | 33ebd66f42c1 | 288 | 33ebd66f42c1 |
| [package_product_worker_provider_host.py](../../../../src/loushang/coding/package_product_worker_provider_host.py) | C07 | 290 | M | C07 插件 Worker 执行/持久化/恢复 | 97fc7aa0e78a | 237 | 2ed09625a33f |
| [package_product_worker_query_consumer.py](../../../../src/loushang/coding/package_product_worker_query_consumer.py) | C07 | 159 | M | C07 插件 Worker 执行/持久化/恢复 | 3edc3bdf34d7 | 159 | 3edc3bdf34d7 |
| [package_product_worker_receipt.py](../../../../src/loushang/coding/package_product_worker_receipt.py) | C07 | 1,287 | M | C07 插件 Worker 执行/持久化/恢复 | 28b31f8d21d9 | 890 | 4ceee116c742 |
| [package_product_worker_receipt_base_v2.py](../../../../src/loushang/coding/package_product_worker_receipt_base_v2.py) | C07 | 234 | M | C07 插件 Worker 执行/持久化/恢复 | 6e0d43651711 | 44 | e68d7ab4c84d |
| [package_product_worker_registered_c5_settlement.py](../../../../src/loushang/coding/package_product_worker_registered_c5_settlement.py) | C07 | 368 | M | C07 插件 Worker 执行/持久化/恢复 | 4e651980106b | 102 | 2bdcfed63608 |
| [package_product_worker_registered_payload_repair.py](../../../../src/loushang/coding/package_product_worker_registered_payload_repair.py) | C07 | 490 | M | C07 插件 Worker 执行/持久化/恢复 | 154d62d8b4ea | 291 | b01b88bd0bce |
| [package_product_worker_registered_recovery.py](../../../../src/loushang/coding/package_product_worker_registered_recovery.py) | C07 | 297 | M | C07 插件 Worker 执行/持久化/恢复 | a4f687231e21 | 199 | 7d2b972ff406 |
| [package_product_worker_resume.py](../../../../src/loushang/coding/package_product_worker_resume.py) | C07 | 281 | M | C07 插件 Worker 执行/持久化/恢复 | 806f3072e7b6 | 175 | 4bd9ac532af4 |
| [package_product_worker_session_composition.py](../../../../src/loushang/coding/package_product_worker_session_composition.py) | C07 | 635 | M | C07 插件 Worker 执行/持久化/恢复 | 7314a0c57377 | 343 | a7ea4fffc71e |
| [package_product_worker_start_gate.py](../../../../src/loushang/coding/package_product_worker_start_gate.py) | C07 | 159 | M | C07 插件 Worker 执行/持久化/恢复 | 5c2e41e87360 | 159 | 5c2e41e87360 |
| [package_product_worker_start_gate_base_v2.py](../../../../src/loushang/coding/package_product_worker_start_gate_base_v2.py) | C07 | 251 | M | C07 插件 Worker 执行/持久化/恢复 | be85b7c1c7ea | 53 | 5656674b82e9 |
| [package_product_worker_start_gate_journal.py](../../../../src/loushang/coding/package_product_worker_start_gate_journal.py) | C07 | 794 | M | C07 插件 Worker 执行/持久化/恢复 | 2219e0c868a2 | 230 | 1b808ee93dea |
| [package_product_worker_start_gate_recovery.py](../../../../src/loushang/coding/package_product_worker_start_gate_recovery.py) | C07 | 382 | M | C07 插件 Worker 执行/持久化/恢复 | 9628c983845b | 350 | 7d10436628ad |
| [package_product_worker_supervisor_base_v2.py](../../../../src/loushang/coding/package_product_worker_supervisor_base_v2.py) | C07 | 453 | M | C07 插件 Worker 执行/持久化/恢复 | 232bde5ae814 | 57 | 7fb2a3389dc3 |
| [package_product_worker_supervisor_journal.py](../../../../src/loushang/coding/package_product_worker_supervisor_journal.py) | C07 | 544 | M | C07 插件 Worker 执行/持久化/恢复 | e0af5c5ed404 | 42 | deb852d410b3 |
| [package_product_worker_turn_tool.py](../../../../src/loushang/coding/package_product_worker_turn_tool.py) | C07 | 73 | M | C07 插件 Worker 执行/持久化/恢复 | b09e6a501447 | 73 | b09e6a501447 |
| [package_product_worker_windows_activation_state_journal.py](../../../../src/loushang/coding/package_product_worker_windows_activation_state_journal.py) | C07 | 452 | M | C07 插件 Worker 执行/持久化/恢复 | 536f9e7cc4ac | 59 | 8cbe5e9b96e1 |
| [package_product_worker_windows_backend_release.py](../../../../src/loushang/coding/package_product_worker_windows_backend_release.py) | C07 | 205 | M | C07 插件 Worker 执行/持久化/恢复 | a5f20c684029 | 205 | a5f20c684029 |
| [package_product_worker_windows_base_files.py](../../../../src/loushang/coding/package_product_worker_windows_base_files.py) | C07 | 25 | M | C07 插件 Worker 执行/持久化/恢复 | f3ca6e786327 | 25 | f3ca6e786327 |
| [package_product_worker_windows_c5_base.py](../../../../src/loushang/coding/package_product_worker_windows_c5_base.py) | C07 | 304 | M | C07 插件 Worker 执行/持久化/恢复 | 04ec1ac725a7 | 101 | 9f652bd52636 |
| [package_product_worker_windows_checkpoint.py](../../../../src/loushang/coding/package_product_worker_windows_checkpoint.py) | C07 | 489 | M | C07 插件 Worker 执行/持久化/恢复 | a1a050765f52 | 470 | 25751f01c1e7 |
| [package_product_worker_windows_cleanup_evidence.py](../../../../src/loushang/coding/package_product_worker_windows_cleanup_evidence.py) | C07 | 398 | M | C07 插件 Worker 执行/持久化/恢复 | 3989304c1e98 | 387 | fb615b9e9e08 |
| [package_product_worker_windows_crash_c5_settlement.py](../../../../src/loushang/coding/package_product_worker_windows_crash_c5_settlement.py) | C07 | 180 | M | C07 插件 Worker 执行/持久化/恢复 | c96cfa786752 | 180 | c96cfa786752 |
| [package_product_worker_windows_crash_cleanup_review.py](../../../../src/loushang/coding/package_product_worker_windows_crash_cleanup_review.py) | C07 | 309 | M | C07 插件 Worker 执行/持久化/恢复 | a07396c100de | 246 | 0c6edc4083d0 |
| [package_product_worker_windows_crash_lease_repair.py](../../../../src/loushang/coding/package_product_worker_windows_crash_lease_repair.py) | C07 | 199 | M | C07 插件 Worker 执行/持久化/恢复 | b9282c6937f1 | 199 | b9282c6937f1 |
| [package_product_worker_windows_crash_native_settlement.py](../../../../src/loushang/coding/package_product_worker_windows_crash_native_settlement.py) | C07 | 203 | M | C07 插件 Worker 执行/持久化/恢复 | 07da1d22d4a2 | 203 | 07da1d22d4a2 |
| [package_product_worker_windows_crash_recovery.py](../../../../src/loushang/coding/package_product_worker_windows_crash_recovery.py) | C07 | 154 | M | C07 插件 Worker 执行/持久化/恢复 | ae069003f4ed | 154 | ae069003f4ed |
| [package_product_worker_windows_crash_stage_retirement.py](../../../../src/loushang/coding/package_product_worker_windows_crash_stage_retirement.py) | C07 | 341 | M | C07 插件 Worker 执行/持久化/恢复 | 9a6546d95c6e | 341 | 9a6546d95c6e |
| [package_product_worker_windows_crash_stage_review.py](../../../../src/loushang/coding/package_product_worker_windows_crash_stage_review.py) | C07 | 342 | M | C07 插件 Worker 执行/持久化/恢复 | 0592cc515ea6 | 295 | 085fd3dbe18f |
| [package_product_worker_windows_crash_supervisor_settlement.py](../../../../src/loushang/coding/package_product_worker_windows_crash_supervisor_settlement.py) | C07 | 154 | M | C07 插件 Worker 执行/持久化/恢复 | 66083409026f | 154 | 66083409026f |
| [package_product_worker_windows_desired_references.py](../../../../src/loushang/coding/package_product_worker_windows_desired_references.py) | C07 | 230 | M | C07 插件 Worker 执行/持久化/恢复 | 09cc03483015 | 230 | 09cc03483015 |
| [package_product_worker_windows_gc_history.py](../../../../src/loushang/coding/package_product_worker_windows_gc_history.py) | C07 | 244 | M | C07 插件 Worker 执行/持久化/恢复 | e4cdf9943c9f | 239 | 84344134319b |
| [package_product_worker_windows_history_bases.py](../../../../src/loushang/coding/package_product_worker_windows_history_bases.py) | C07 | 184 | M | C07 插件 Worker 执行/持久化/恢复 | 0b731f21adac | 184 | 0b731f21adac |
| [package_product_worker_windows_history_cutover_preflight.py](../../../../src/loushang/coding/package_product_worker_windows_history_cutover_preflight.py) | C07 | 76 | M | C07 插件 Worker 执行/持久化/恢复 | d7f6a7932d26 | 76 | d7f6a7932d26 |
| [package_product_worker_windows_history_cutover_record.py](../../../../src/loushang/coding/package_product_worker_windows_history_cutover_record.py) | C07 | 164 | M | C07 插件 Worker 执行/持久化/恢复 | ccdf6e6ab3cb | 152 | 24cac5e18547 |
| [package_product_worker_windows_history_join.py](../../../../src/loushang/coding/package_product_worker_windows_history_join.py) | C07 | 294 | M | C07 插件 Worker 执行/持久化/恢复 | 99612061bff3 | 100 | 898b0bf7277f |
| [package_product_worker_windows_history_preparation.py](../../../../src/loushang/coding/package_product_worker_windows_history_preparation.py) | C07 | 269 | M | C07 插件 Worker 执行/持久化/恢复 | 1afe77bb78d4 | 271 | 99ff676b9e0a |
| [package_product_worker_windows_history_sources.py](../../../../src/loushang/coding/package_product_worker_windows_history_sources.py) | C07 | 565 | M | C07 插件 Worker 执行/持久化/恢复 | 4ccfc44f06eb | 498 | d58f8d8d134f |
| [package_product_worker_windows_installed_backend.py](../../../../src/loushang/coding/package_product_worker_windows_installed_backend.py) | C07 | 234 | M | C07 插件 Worker 执行/持久化/恢复 | 67b085036c23 | 234 | 67b085036c23 |
| [package_product_worker_windows_launch_intent.py](../../../../src/loushang/coding/package_product_worker_windows_launch_intent.py) | C07 | 373 | M | C07 插件 Worker 执行/持久化/恢复 | ea475b8de037 | 319 | 7641ff359790 |
| [package_product_worker_windows_launch_intent_base.py](../../../../src/loushang/coding/package_product_worker_windows_launch_intent_base.py) | C07 | 255 | M | C07 插件 Worker 执行/持久化/恢复 | 2166e0bc9615 | 119 | c6585d73de01 |
| [package_product_worker_windows_native_approval_journal.py](../../../../src/loushang/coding/package_product_worker_windows_native_approval_journal.py) | C07 | 416 | M | C07 插件 Worker 执行/持久化/恢复 | 27a49ab7c159 | 97 | faef5f4e4f27 |
| [package_product_worker_windows_native_approval_owner.py](../../../../src/loushang/coding/package_product_worker_windows_native_approval_owner.py) | C07 | 108 | M | C07 插件 Worker 执行/持久化/恢复 | 42c5dcf29373 | 108 | 42c5dcf29373 |
| [package_product_worker_windows_opt_in_base.py](../../../../src/loushang/coding/package_product_worker_windows_opt_in_base.py) | C07 | 224 | M | C07 插件 Worker 执行/持久化/恢复 | aaff2073182f | 105 | c0a4585a5b12 |
| [package_product_worker_windows_opt_in_journal.py](../../../../src/loushang/coding/package_product_worker_windows_opt_in_journal.py) | C07 | 427 | M | C07 插件 Worker 执行/持久化/恢复 | 45de61d79cf7 | 107 | 456a16fdd64c |
| [package_product_worker_windows_opt_in_owner.py](../../../../src/loushang/coding/package_product_worker_windows_opt_in_owner.py) | C07 | 240 | M | C07 插件 Worker 执行/持久化/恢复 | 8a433b9a6e12 | 164 | 044df2453c67 |
| [package_product_worker_windows_orphan_review.py](../../../../src/loushang/coding/package_product_worker_windows_orphan_review.py) | C07 | 218 | M | C07 插件 Worker 执行/持久化/恢复 | f208ccc2257a | 191 | 0e0b41e98f2c |
| [package_product_worker_windows_package_references.py](../../../../src/loushang/coding/package_product_worker_windows_package_references.py) | C07 | 333 | M | C07 插件 Worker 执行/持久化/恢复 | 4e592d2bb6a4 | 333 | 4e592d2bb6a4 |
| [package_product_worker_windows_partial_stage_retirement.py](../../../../src/loushang/coding/package_product_worker_windows_partial_stage_retirement.py) | C07 | 470 | M | C07 插件 Worker 执行/持久化/恢复 | f3aa4d490897 | 324 | cca371775339 |
| [package_product_worker_windows_partial_stage_review.py](../../../../src/loushang/coding/package_product_worker_windows_partial_stage_review.py) | C07 | 403 | M | C07 插件 Worker 执行/持久化/恢复 | 8d715c51e57b | 357 | fe81b0979bf7 |
| [package_product_worker_windows_payload.py](../../../../src/loushang/coding/package_product_worker_windows_payload.py) | C07 | 726 | M | C07 插件 Worker 执行/持久化/恢复 | 3b269028908c | 600 | 2df69975a32b |
| [package_product_worker_windows_payload_inventory.py](../../../../src/loushang/coding/package_product_worker_windows_payload_inventory.py) | C07 | 150 | M | C07 插件 Worker 执行/持久化/恢复 | 9464816cc608 | 86 | 7de98ea1fd47 |
| [package_product_worker_windows_pending_host.py](../../../../src/loushang/coding/package_product_worker_windows_pending_host.py) | C07 | 593 | M | C07 插件 Worker 执行/持久化/恢复 | 543a2c4a6116 | 282 | 60e941e580c3 |
| [package_product_worker_windows_persisted_bases.py](../../../../src/loushang/coding/package_product_worker_windows_persisted_bases.py) | C07 | 315 | M | C07 插件 Worker 执行/持久化/恢复 | 28438d7a4fed | 315 | 28438d7a4fed |
| [package_product_worker_windows_provisioning.py](../../../../src/loushang/coding/package_product_worker_windows_provisioning.py) | C07 | 344 | M | C07 插件 Worker 执行/持久化/恢复 | 98ffbd480b88 | 318 | ec020f449488 |
| [package_product_worker_windows_provisioning_base.py](../../../../src/loushang/coding/package_product_worker_windows_provisioning_base.py) | C07 | 410 | M | C07 插件 Worker 执行/持久化/恢复 | 0e8ef6cd61ab | 121 | 3292f03b8be6 |
| [package_product_worker_windows_provisioning_journal.py](../../../../src/loushang/coding/package_product_worker_windows_provisioning_journal.py) | C07 | 759 | M | C07 插件 Worker 执行/持久化/恢复 | 6b1601a8cca0 | 37 | 182e668b09b0 |
| [package_product_worker_windows_receipt.py](../../../../src/loushang/coding/package_product_worker_windows_receipt.py) | C07 | 594 | M | C07 插件 Worker 执行/持久化/恢复 | 085992880854 | 594 | 085992880854 |
| [package_product_worker_windows_receipt_base.py](../../../../src/loushang/coding/package_product_worker_windows_receipt_base.py) | C07 | 229 | M | C07 插件 Worker 执行/持久化/恢复 | 4c254c982190 | 101 | 1cf3848a47cb |
| [package_product_worker_windows_receipt_journal.py](../../../../src/loushang/coding/package_product_worker_windows_receipt_journal.py) | C07 | 358 | M | C07 插件 Worker 执行/持久化/恢复 | 1e3b227fb315 | 75 | 52385b2063a7 |
| [package_product_worker_windows_recovery_inventory.py](../../../../src/loushang/coding/package_product_worker_windows_recovery_inventory.py) | C07 | 948 | M | C07 插件 Worker 执行/持久化/恢复 | b27d4837686b | 571 | b37415006f16 |
| [package_product_worker_windows_reserved_review.py](../../../../src/loushang/coding/package_product_worker_windows_reserved_review.py) | C07 | 498 | M | C07 插件 Worker 执行/持久化/恢复 | da4173eeec8e | 447 | 7ba600f46869 |
| [package_product_worker_windows_reserved_settlement.py](../../../../src/loushang/coding/package_product_worker_windows_reserved_settlement.py) | C07 | 148 | M | C07 插件 Worker 执行/持久化/恢复 | 2b51f84d3792 | 148 | 2b51f84d3792 |
| [package_product_worker_windows_stage_retirement.py](../../../../src/loushang/coding/package_product_worker_windows_stage_retirement.py) | C07 | 819 | M | C07 插件 Worker 执行/持久化/恢复 | 3ff0e86ef425 | 499 | 99baaa4b776c |
| [package_product_worker_windows_stage_review.py](../../../../src/loushang/coding/package_product_worker_windows_stage_review.py) | C07 | 562 | M | C07 插件 Worker 执行/持久化/恢复 | 6ea1c3b1a359 | 434 | 2713a75006ba |
| [package_product_worker_windows_supervisor_base.py](../../../../src/loushang/coding/package_product_worker_windows_supervisor_base.py) | C07 | 282 | M | C07 插件 Worker 执行/持久化/恢复 | 7b61d5a66355 | 104 | 5735412a6101 |
| [package_product_worker_windows_supervisor_journal.py](../../../../src/loushang/coding/package_product_worker_windows_supervisor_journal.py) | C07 | 403 | M | C07 插件 Worker 执行/持久化/恢复 | 009fdc92f3b4 | 50 | d97db7b700f4 |
| [package_product_worker_windows_unlaunched_stage_retirement.py](../../../../src/loushang/coding/package_product_worker_windows_unlaunched_stage_retirement.py) | C07 | 438 | M | C07 插件 Worker 执行/持久化/恢复 | f21cd9031d90 | 383 | 1d9faed4d883 |
| [package_source_snapshot.py](../../../../src/loushang/coding/package_source_snapshot.py) | C09 | 433 | E | C09 历史兼容、迁移与快照证据 | 3966088d6f93 | 430 | 702c16746ea0 |
| [platform/__init__.py](../../../../src/loushang/coding/platform/__init__.py) | C27 | 5 | K | C27 版本检查 Product 绑定 | 6af5d273482a | 5 | 6af5d273482a |
| [platform/version_check.py](../../../../src/loushang/coding/platform/version_check.py) | C27 | 45 | K | C27 版本检查 Product 绑定 | 564c53288c45 | 45 | 564c53288c45 |
| [plugin_author_smoke.py](../../../../src/loushang/coding/plugin_author_smoke.py) | C05 | 740 | V | C05 显式 canary 与作者验证入口 | 1f7948784509 | 740 | 1f7948784509 |
| [plugin_dependency_grants.py](../../../../src/loushang/coding/plugin_dependency_grants.py) | C01 | 98 | K | C01 启动、Plugin 与资源装配 | 2a98643f66b4 | 106 | 08d6d2e724ea |
| [plugin_enablement_compatibility.py](../../../../src/loushang/coding/plugin_enablement_compatibility.py) | C01 | 317 | M | C01 启动、Plugin 与资源装配 | c4be279ad128 | 317 | c4be279ad128 |
| [plugin_local_discovery.py](../../../../src/loushang/coding/plugin_local_discovery.py) | C01 | 669 | M | C01 启动、Plugin 与资源装配 | 6d30b2520bb1 | 669 | 6d30b2520bb1 |
| [plugin_management_cli.py](../../../../src/loushang/coding/plugin_management_cli.py) | C06 | 282 | R/M | C06 其余根目录入口与策略 | b59458d089c7 | 282 | b59458d089c7 |
| [plugin_management_command_rpc.py](../../../../src/loushang/coding/plugin_management_command_rpc.py) | C06 | 92 | R/M | C06 其余根目录入口与策略 | a07e5767300a | 92 | a07e5767300a |
| [plugin_management_command_sdk.py](../../../../src/loushang/coding/plugin_management_command_sdk.py) | C06 | 226 | R/M | C06 其余根目录入口与策略 | fbcec2b38b99 | 226 | fbcec2b38b99 |
| [plugin_management_explanation.py](../../../../src/loushang/coding/plugin_management_explanation.py) | C06 | 125 | R/M | C06 其余根目录入口与策略 | e9f5874f1930 | 125 | e9f5874f1930 |
| [plugin_management_preview.py](../../../../src/loushang/coding/plugin_management_preview.py) | C06 | 239 | R/M | C06 其余根目录入口与策略 | f84e343151a7 | 239 | f84e343151a7 |
| [plugin_management_read_sdk.py](../../../../src/loushang/coding/plugin_management_read_sdk.py) | C06 | 283 | R/M | C06 其余根目录入口与策略 | 6cb1deeb3501 | 283 | 6cb1deeb3501 |
| [plugin_management_rpc_scope.py](../../../../src/loushang/coding/plugin_management_rpc_scope.py) | C06 | 132 | R/M | C06 其余根目录入口与策略 | 2e73c9317ce5 | 132 | 2e73c9317ce5 |
| [plugin_management_ui.py](../../../../src/loushang/coding/plugin_management_ui.py) | C06 | 292 | R/M | C06 其余根目录入口与策略 | d884a1817b7a | 292 | d884a1817b7a |
| [plugin_operation_guidance.py](../../../../src/loushang/coding/plugin_operation_guidance.py) | C06 | 67 | R/M | C06 其余根目录入口与策略 | b4705c93566c | 67 | b4705c93566c |
| [plugin_support_status.py](../../../../src/loushang/coding/plugin_support_status.py) | C06 | 330 | R/M | C06 其余根目录入口与策略 | 21ef1ee7edbc | 330 | 21ef1ee7edbc |
| [presentation/__init__.py](../../../../src/loushang/coding/presentation/__init__.py) | C23 | 1 | R/K | C23 呈现适配 | 8f7042fea533 | 1 | 8f7042fea533 |
| [presentation/tui/__init__.py](../../../../src/loushang/coding/presentation/tui/__init__.py) | C23 | 1 | R/K | C23 呈现适配 | ad87c614282d | 1 | ad87c614282d |
| [presentation/tui/history.py](../../../../src/loushang/coding/presentation/tui/history.py) | C23 | 27 | R/K | C23 呈现适配 | 1eaa343f586a | 27 | 1eaa343f586a |
| [presentation/tui/plain.py](../../../../src/loushang/coding/presentation/tui/plain.py) | C23 | 80 | R/K | C23 呈现适配 | ba35bb32c111 | 80 | ba35bb32c111 |
| [product_plan.py](../../../../src/loushang/coding/product_plan.py) | C01 | 46 | K | C01 启动、Plugin 与资源装配 | a6cb7367aa7e | 46 | a6cb7367aa7e |
| [prompt/__init__.py](../../../../src/loushang/coding/prompt/__init__.py) | C21 | 19 | R/K | C21 Prompt 内容/默认绑定 | a1205432aef0 | 19 | a1205432aef0 |
| [prompt/assembler.py](../../../../src/loushang/coding/prompt/assembler.py) | C21 | 65 | R/K | C21 Prompt 内容/默认绑定 | 659058cc4ba2 | 65 | 659058cc4ba2 |
| [prompt/defaults.py](../../../../src/loushang/coding/prompt/defaults.py) | C21 | 48 | K | C21 Prompt 内容/默认绑定 | c4ea960b96dd | 48 | c4ea960b96dd |
| [prompt_command.py](../../../../src/loushang/coding/prompt_command.py) | C06 | 144 | R/M | C06 其余根目录入口与策略 | eca032531306 | 144 | eca032531306 |
| [resource_runtime.py](../../../../src/loushang/coding/resource_runtime.py) | C01 | 128 | M | C01 启动、Plugin 与资源装配 | c98093bf4b71 | 128 | c98093bf4b71 |
| [resources/__init__.py](../../../../src/loushang/coding/resources/__init__.py) | C28 | 1 | K | C28 资源命名空间 | aaee7bc72cf4 | 1 | aaee7bc72cf4 |
| [resources/extensions/__init__.py](../../../../src/loushang/coding/resources/extensions/__init__.py) | C28 | 1 | K | C28 资源命名空间 | 1a2fce02df38 | 1 | 1a2fce02df38 |
| [resources/prompts/__init__.py](../../../../src/loushang/coding/resources/prompts/__init__.py) | C28 | 1 | K | C28 资源命名空间 | 179b8f3f0a5e | 1 | 179b8f3f0a5e |
| [resources/skills/__init__.py](../../../../src/loushang/coding/resources/skills/__init__.py) | C28 | 1 | K | C28 资源命名空间 | fc261aa85e1d | 1 | fc261aa85e1d |
| [resources/themes/__init__.py](../../../../src/loushang/coding/resources/themes/__init__.py) | C28 | 1 | K | C28 资源命名空间 | d83b68bdb208 | 1 | d83b68bdb208 |
| [resume_activation_attempt.py](../../../../src/loushang/coding/resume_activation_attempt.py) | C03 | 281 | M | C03 Resume 与 SessionManager | 298864569f9f | 281 | 298864569f9f |
| [resume_activation_attempt_v2.py](../../../../src/loushang/coding/resume_activation_attempt_v2.py) | C03 | 223 | M | C03 Resume 与 SessionManager | 7f2a0c108719 | 223 | 7f2a0c108719 |
| [resume_activation_plan.py](../../../../src/loushang/coding/resume_activation_plan.py) | C03 | 400 | M | C03 Resume 与 SessionManager | ccb37b7eb0a6 | 400 | ccb37b7eb0a6 |
| [resume_activation_projection_v2.py](../../../../src/loushang/coding/resume_activation_projection_v2.py) | C03 | 228 | M | C03 Resume 与 SessionManager | 8a9580a4a562 | 228 | 8a9580a4a562 |
| [resume_binding.py](../../../../src/loushang/coding/resume_binding.py) | C03 | 389 | M | C03 Resume 与 SessionManager | 4c2340cc6961 | 389 | 4c2340cc6961 |
| [resume_binding_v2.py](../../../../src/loushang/coding/resume_binding_v2.py) | C03 | 194 | M | C03 Resume 与 SessionManager | 32ea968c1956 | 194 | 32ea968c1956 |
| [resume_composition_comparison.py](../../../../src/loushang/coding/resume_composition_comparison.py) | C03 | 82 | M | C03 Resume 与 SessionManager | 1ab3dbfc17be | 82 | 1ab3dbfc17be |
| [resume_continuation.py](../../../../src/loushang/coding/resume_continuation.py) | C03 | 486 | M | C03 Resume 与 SessionManager | 7a3b78d3332f | 486 | 41234ee285eb |
| [resume_history.py](../../../../src/loushang/coding/resume_history.py) | C03 | 233 | M | C03 Resume 与 SessionManager | 6de289f3c167 | 233 | 6de289f3c167 |
| [resume_input_lookup.py](../../../../src/loushang/coding/resume_input_lookup.py) | C03 | 52 | M | C03 Resume 与 SessionManager | 50b5ecb065fa | 52 | 50b5ecb065fa |
| [resume_model_outcome.py](../../../../src/loushang/coding/resume_model_outcome.py) | C03 | 134 | M | C03 Resume 与 SessionManager | 75ba0b4973c8 | 134 | 75ba0b4973c8 |
| [resume_permission_confirmation.py](../../../../src/loushang/coding/resume_permission_confirmation.py) | C03 | 203 | M | C03 Resume 与 SessionManager | 52bd39c82949 | 203 | 52bd39c82949 |
| [runtime/__init__.py](../../../../src/loushang/coding/runtime/__init__.py) | C17 | 7 | M | C17 AgentSessionRuntime Product 绑定 | 0e0b928bb2e0 | 7 | 0e0b928bb2e0 |
| [runtime/agent_session_runtime.py](../../../../src/loushang/coding/runtime/agent_session_runtime.py) | C17 | 917 | M | C17 AgentSessionRuntime Product 绑定 | bb545ecdb45d | 829 | ae1c4a51a037 |
| [runtime/resume_planning.py](../../../../src/loushang/coding/runtime/resume_planning.py) | C17 | 194 | M | C17 AgentSessionRuntime Product 绑定 | b656eb2d13e8 | 194 | b656eb2d13e8 |
| [runtime_capability_admission.py](../../../../src/loushang/coding/runtime_capability_admission.py) | C01 | 350 | M | C01 启动、Plugin 与资源装配 | 858c6823b287 | 350 | 858c6823b287 |
| [sandbox.py](../../../../src/loushang/coding/sandbox.py) | C06 | 292 | R/M | C06 其余根目录入口与策略 | 924f1e5005ba | 292 | 924f1e5005ba |
| [sdk_surface.py](../../../../src/loushang/coding/sdk_surface.py) | C06 | 61 | R/M | C06 其余根目录入口与策略 | 2754110e8568 | 61 | 2754110e8568 |
| [session/__init__.py](../../../../src/loushang/coding/session/__init__.py) | C15 | 26 | M | C15 AgentSession Product 绑定 | eea355c9a1d2 | 26 | eea355c9a1d2 |
| [session/agent_session.py](../../../../src/loushang/coding/session/agent_session.py) | C15 | 2,372 | M | C15 AgentSession Product 绑定 | 8d708cb4b055 | 2,101 | cd580e8789c2 |
| [session_manager.py](../../../../src/loushang/coding/session_manager.py) | C03 | 1,403 | M | C03 Resume 与 SessionManager | 60b22db73913 | 783 | b013dbe9526e |
| [tool_pack.py](../../../../src/loushang/coding/tool_pack.py) | C01 | 266 | K | C01 启动、Plugin 与资源装配 | 14a6cfdd5298 | 266 | 14a6cfdd5298 |
| [ui/__init__.py](../../../../src/loushang/coding/ui/__init__.py) | C16 | 1 | R/K | C16 Native UI Product 绑定 | 60db0b21525c | 1 | 60db0b21525c |
| [ui/_plugin_completion.py](../../../../src/loushang/coding/ui/_plugin_completion.py) | C16 | 44 | R/K | C16 Native UI Product 绑定 | bdde3276549f | 44 | bdde3276549f |
| [ui/cli.py](../../../../src/loushang/coding/ui/cli.py) | C16 | 13 | R/K | C16 Native UI Product 绑定 | 3b0ebfe7f593 | 13 | 3b0ebfe7f593 |
| [ui/completion.py](../../../../src/loushang/coding/ui/completion.py) | C16 | 52 | R/K | C16 Native UI Product 绑定 | 32987da385ea | 52 | 32987da385ea |
| [ui/hotkeys.py](../../../../src/loushang/coding/ui/hotkeys.py) | C16 | 117 | R/K | C16 Native UI Product 绑定 | 938b45277daf | 117 | 938b45277daf |
| [ui/mode.py](../../../../src/loushang/coding/ui/mode.py) | C16 | 355 | R/K | C16 Native UI Product 绑定 | a6c709498815 | 355 | a6c709498815 |
| [ui/plain_app.py](../../../../src/loushang/coding/ui/plain_app.py) | C16 | 95 | R/K | C16 Native UI Product 绑定 | ba99da04884f | 95 | ba99da04884f |
| [ui/plugin_theme.py](../../../../src/loushang/coding/ui/plugin_theme.py) | C16 | 106 | R/K | C16 Native UI Product 绑定 | e4acba510909 | 106 | e4acba510909 |
| [ui/product_binding.py](../../../../src/loushang/coding/ui/product_binding.py) | C16 | 700 | R/K | C16 Native UI Product 绑定 | 46cac539d769 | 700 | 46cac539d769 |
| [ui/screen_app.py](../../../../src/loushang/coding/ui/screen_app.py) | C16 | 307 | R/K | C16 Native UI Product 绑定 | f81009680761 | 307 | f81009680761 |
| [ui/screen_input.py](../../../../src/loushang/coding/ui/screen_input.py) | C16 | 143 | R/K | C16 Native UI Product 绑定 | 4c172793d87a | 143 | 4c172793d87a |
| [ui/screen_surfaces.py](../../../../src/loushang/coding/ui/screen_surfaces.py) | C16 | 171 | R/K | C16 Native UI Product 绑定 | 00fa345e5484 | 171 | 00fa345e5484 |
| [ui/settings_page.py](../../../../src/loushang/coding/ui/settings_page.py) | C16 | 51 | R/K | C16 Native UI Product 绑定 | 1e5bf8a887f5 | 51 | 1e5bf8a887f5 |
| [ui/startup.py](../../../../src/loushang/coding/ui/startup.py) | C16 | 24 | R/K | C16 Native UI Product 绑定 | 91c19c05f30a | 24 | 91c19c05f30a |
| [workflow/__init__.py](../../../../src/loushang/coding/workflow/__init__.py) | C24 | 5 | R/K | C24 Scenario 工作流适配 | 125af56daff8 | 5 | 125af56daff8 |
| [workflow/command.py](../../../../src/loushang/coding/workflow/command.py) | C24 | 77 | R/K | C24 Scenario 工作流适配 | 8e61d7632580 | 77 | 8e61d7632580 |
| [workspace_operations.py](../../../../src/loushang/coding/workspace_operations.py) | C06 | 118 | R/M | C06 其余根目录入口与策略 | 496522f74bb7 | 118 | 496522f74bb7 |
| [worktree.py](../../../../src/loushang/coding/worktree.py) | C06 | 158 | R/M | C06 其余根目录入口与策略 | 52d96c306803 | 158 | 52d96c306803 |
| [_worker_history_access.py](../../../../src/loushang/coding/_worker_history_access.py) | C07 | — | M | Worker原存储访问绑定；共享机制已部分归位 | — | 54 | fd4112bace44 |
| [_worker_preparation_inputs.py](../../../../src/loushang/coding/_worker_preparation_inputs.py) | C07 | — | M | Worker准备的Coding准入与配置；剩余须按场景复核 | — | 348 | 290a23d3566b |
| [gui_local_host.py](../../../../src/loushang/coding/gui_local_host.py) | C02 | — | B | 主线新增GUI本地托管Product入口；不计本轮重构新增收益 | — | 201 | 168cf5e11098 |

## 当前分组计量与剩余处置

当前按原C01–C28分组共430文件；每组物理行不是可删除预算。
上表K/R/M等为继承的逐文件建议，不把已减行、薄外观或整组名称当作最终领域化证明。
P1–P4均保持partial；已接管机制直接复用，其余保留/迁移/删除须逐完整场景核验。

| 组 | 当前文件 | 当前物理行 |
| --- | ---: | ---: |
| C01 | 22 | 12,966 |
| C02 | 28 | 8,043 |
| C03 | 15 | 4,132 |
| C04 | 2 | 2,968 |
| C05 | 6 | 3,565 |
| C06 | 26 | 4,460 |
| C07 | 112 | 22,688 |
| C08 | 31 | 6,743 |
| C09 | 34 | 9,711 |
| C10 | 12 | 5,546 |
| C11 | 25 | 9,310 |
| C12 | 25 | 7,180 |
| C13 | 21 | 5,668 |
| C14 | 13 | 3,628 |
| C15 | 2 | 2,127 |
| C16 | 14 | 2,179 |
| C17 | 3 | 1,030 |
| C18 | 5 | 874 |
| C19 | 4 | 440 |
| C20 | 3 | 233 |
| C21 | 3 | 132 |
| C22 | 6 | 124 |
| C23 | 4 | 109 |
| C24 | 2 | 82 |
| C25 | 3 | 72 |
| C26 | 2 | 52 |
| C27 | 2 | 50 |
| C28 | 5 | 5 |
| 合计 | 430 | 114,117 |
