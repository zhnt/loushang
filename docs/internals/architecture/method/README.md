# Loushang Method Architecture

[Architecture](../README.md)

## Scope

本文档是当前 `loushang.method` 的 canonical architecture note。

历史 design specs 和 experimental methodology 文档可以提供背景和演进理由，但当它们与当前代码、测试或本文件冲突时，优先以当前代码、测试和本文件为准。

## Definition

Method 是面向一类任务的结构化工作契约。

它定义：

- 何时适用
- agent 应扮演什么角色
- 工作处于哪个阶段
- 应按什么 workflow 推进
- 需要遵守哪些 constraints、audit points 和 gates
- 应产出什么 work products 与 acceptance results

换成运行时语义：

```text
Method = Work Contract
Skill  = Local expertise or capability guidance
Tool   = Executable action
Policy = Permission and approval boundary
Work   = Business intent enactment and authoritative runtime facts
```

## Model Autonomy Boundary

**Method 规定“什么必须成立”，模型决定“怎样达到”。**

Method 应稳定表达一类工作的目标、适用条件、角色责任、约束、audit
points、gates、预期产物、验收条件和证据要求。它不应把某一代模型需要的
认知脚手架固化成长期流程，例如：

- 强制每个普通任务先生成 todo；
- 固定的逐步推理、反思或 self-critique 模板；
- 每隔若干工具调用注入一次进度提醒；
- 仅靠 prompt 约束的通用 verifier 流程；
- 静态模型路由或工具选择启发式。

在 Method 的约束和 Product/Harness 授权边界内，模型可以自主选择任务分解、
工具顺序、局部推理策略、是否使用子 agent，以及是否维护临时计划。模型能力
增强时，这些内部策略可以减少、替换或消失，而不要求修改 Method contract。

需要区分两种计划：

```text
帮助模型思考的临时 plan
  -> model- or Product-owned strategy, admitted Extension, or Skill

供人、团队和系统共同遵守的 plan
  -> Product binding -> Work acceptance -> Work-owned fact
```

当计划涉及跨 agent 协作、人工审批、预算、恢复、审计或验收时，它不再只是
模型的认知辅助。Product 必须把它绑定成 run-specific Work contract，由 Work
接受、排序和记录；执行中的改变应成为显式 revision 或 deviation，而不是模型
静默改写历史。

同样，Method 可以规定“必须提供哪些验证证据”，但不应默认规定模型必须使用
某个通用 verifier prompt。Product 解释编译、测试、扫描、领域校验和独立执行
环境产生的证据，Work 记录这些证据及其对 outcome 的影响。

这个边界使更强的模型获得更大的局部自主性，同时保持 Method 的组织约束、
Work 的权威事实以及 Loushang substrate 的权限、证据、持久化和协调边界稳定。

## Current Boundary

`loushang.method` owns:

- method resources
- skill-backed method adaptation
- method registry and explicit selection
- method compile
- method projection
- `MethodPlan` / `MethodStep` data semantics

`loushang.method` does not own:

- coding CLI option parsing
- coding session execution
- agent loop internals
- tool execution policy
- work log persistence
- Native TUI rendering or playback

Current Coding-specific method usage is bridged through
`loushang.coding.domain`. This is a compatibility facade over the shared Method
runtime, not a separate long-term DomainApp execution layer. In the v3 target,
the Coding Product work preparer consumes the Method plan and its Product work
executor binds each admitted step to Harness. When a method is enacted,
`loushang.harnesswork` owns the resulting run, plan, step, outcome, event-log, replay,
artifact-reference, and deviation facts.

## Relation To Agent Harness And Products

`loushang.method` is optional for product execution.

Product implementation Python packages such as `loushang.coding`, and future
`loushang.research`, `loushang.ppt`, and `loushang.cowork`, may call
`loushang.harness` directly for lightweight turns. They may also write or
project through `loushang.harnesswork` directly.

Use `method` when the product needs structured work: planning, staged execution,
review gates, method-specific constraints, or acceptance criteria. Do not route
every product turn through method by default.

`cowork` is treated as a future product line, parallel to `coding`, `research`,
and `ppt`; it is not the name of the shared work or collaboration abstraction.

## Artifact Boundary

Method defines expected artifacts: what a structured workflow or method step
should produce.

`loushang.harnesswork` records actual artifact references: what was produced, where it
is, which run or step produced it, and how it relates to the expected artifact.

Products such as Coding, Research, PPT, and Cowork own concrete artifact types,
content, loading, rendering, validation, and materialization.

Therefore the shared work layer should prefer a lightweight `ArtifactRef` over a
shared abstract `Artifact` base class.

## Capability Boundary

Method resources may describe an opaque Product Capability Requirement, but
they do not select a Harness tool pack, register executable tools, or grant
runtime authority. A Product work preparer interprets the requirement in its
domain and carries it into the run-specific Work contract; the Product executor
then resolves it through the Product's admitted Capability catalog before
invoking Harness.

`MethodApplicability.capabilities` remains an applicability and matching fact.
It must not silently become a runtime authorization or ToolPack activation
field. A stable execution-requirement schema should be added only with the
Product/Work projection that consumes it.

## Field Mapping

The work-contract definition maps to current method data objects as follows:

| Contract axis | Current representation |
| --- | --- |
| workflow | `MethodPlan.mode`, `MethodPlan.steps`, `MethodStep.constraint`, `MethodStep.audit` |
| what | `MethodDescriptor.name`, `description`, `content`, `element_type`, `domain`, `applicability` |
| role | `MethodDescriptor.meta_role`, `MethodStep.role_variant`, `MethodProjection.meta_role` |
| task | `MethodDescriptor.element_type="task"`, `MethodApplicability.task_types`, `MethodContext.task`, `MethodPlan.task` |
| phase | `MethodDescriptor.phase`, `MethodPlan.phase`, `MethodApplicability.lifecycle` |
| constraints | `MethodStep.constraint`, projected policy metadata |
| gates | `MethodProjection.approval_gates`, currently mostly reserved |
| skills | `MethodProjection.allowed_skills`, currently reserved for future step-local skill binding |
| tools | `MethodProjection.suggested_tools`, currently reserved |
| artifacts | `MethodProjection.expected_artifacts`, currently reserved |

## Method, Skill, Tool, Policy, Work

Method should orchestrate a class of work. It defines the role, phase, workflow, constraints, artifacts, and acceptance expectations.

Skill should provide local expertise or capability guidance. A skill can be adapted into a `skill_backed` method for compatibility, but method resources should own workflow semantics when both exist.

Tool should execute concrete actions. Tools are not methods; a method can suggest or constrain tool usage, but tool execution remains governed by tool runtime and policy.

Policy should define permission, approval, and safety boundaries. Method metadata can carry policy hints, but enforcement belongs to the domain/runtime layer that executes the turn.

Work should own the real enactment of an accepted business intent. A compiled and
tailored `MethodPlan` remains a reusable process definition; product binding turns
it into a run-specific enactment manifest, and Work owns the resulting plan and
step occurrences, terminal outcome, events, logs, and inspection surfaces.

Method and Work are therefore related but optional:

- Method answers how a class of work should be performed.
- Work answers what happened in this accepted instance and how it ended.
- A Work can exist without Method; a `MethodPlan` does not become a Work until it
  is accepted and enacted.

Work admission and action approval are separate decisions. Admission decides
whether the system accepts a business commitment. Approval mechanics belong to
Harness and product policy/UI; Work only records correlated facts and their
business effect.

## SPEM 2.0 Relationship

The Method vocabulary is informed by [OMG SPEM 2.0](https://www.omg.org/spec/SPEM/2.0/PDF),
especially its separation of Method Content from Process and its process-enactment
scenarios. LouShang currently claims only SPEM-aligned terminology and a partial
subset, not SPEM compliance.

`loushang.method` owns definitions, selection, compilation, and tailoring.
`loushang.harnesswork` is the runtime enactment layer; it is not SPEM `WorkDefinition`
and must not copy the SPEM metamodel. The detailed current/target mapping lives in
[Loushang Work Architecture](../work/README.md#spem-20-alignment).

## Meta-Phase And Meta-Role

Current runtime support is intentionally light:

- `phase` is a string hint carried from descriptor to plan/projection.
- `meta_role` is a string hint carried from descriptor to step projection.
- `role_variant` is available at step level.
- `MethodApplicability.lifecycle` provides an additional lifecycle axis.

These fields are not yet closed enums. The experimental methodology documents remain design inputs for richer phase and role taxonomies:

- [Meta-Phase](../../experimental/methodology/meta-phase.md)
- [5+1 Meta Roles](../../experimental/methodology/meta-roles-5plus1.md)

## Evolution Rules

- Keep method resources domain-neutral where possible.
- Keep coding-specific policy and session behavior in `loushang.coding`.
- Prefer explicit method selection before automatic method routing.
- Store and project method metadata before enforcing it.
- Treat `MethodApplicability` shape as stable, but do not freeze the final ontology too early.
- Bind skills step-locally in the future instead of globally injecting all method-related skills.
- Define durable outcomes, constraints, artifacts, gates, and evidence; keep
  model-contingent planning, reflection, and verifier choreography replaceable.

## Related Documents

- [HarnessWork Durable Enactment Architecture](../harnesswork/README.md)
  is the accepted consolidation of the product-neutral `loushang.work` kernel into an optional
  Harness extension. Its [migration ledger](../harnesswork/migration-ledger.md) defines which owner
  changes are already implemented; `loushang.work` remains only a tested compatibility namespace.
- [Architecture Overview](../architecture-overview.md)
- [Loushang Work Architecture](../work/README.md)
- [Coding Domain Component](../coding/component-interfaces/domain.md)
- [Method Compatibility Note](../coding/component-interfaces/method.md)
- [Method P1 Resource Compatibility Design](../../specs/2026-06-02-method-p1-resource-compatibility-design.md)
- [Fixed MethodPlan P3 Design](../../specs/2026-06-03-fixed-methodplan-p3-design.md)
