# Loushang-AI Component Review Round 1

## Scope

本轮评审针对 `loushang-ai` 当前组件设计主文档进行结构化 review，重点检查：

- 组件边界是否清楚
- ownership 是否稳定
- 依赖方向是否一致
- 关键时序是否与顶层签名一致
- `raw part -> assembler -> event stream` 主链是否闭环

评审对象主要包括：

- [Loushang-AI Component Structure V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-structure-v1.md)
- [Loushang-AI Component Interfaces V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md)
- [Loushang-AI Component Interactions V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md)
- [Loushang-AI Raw Part Design V1](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-raw-part-design-v1.md)
- [Loushang AI Top-Level API Signatures](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-top-level-api-signatures.md)

---

## Findings

### High

1. `complete()` / `complete_simple()` 的交互时序把 `result()` 调用责任错误地放到了调用方，和顶层签名设计相冲突。

- 在 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L101) 到 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L116) 中，`complete(...)` 时序画成了 `Top-Level AI API` 把 event stream handle 返回给调用方，然后由调用方再对 stream 调用 `result()`。
- 在 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L170) 到 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L184) 中，`complete_simple(...)` 也有同样问题。
- 但在 [loushang-ai-top-level-api-signatures.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-top-level-api-signatures.md#L103) 到 [loushang-ai-top-level-api-signatures.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-top-level-api-signatures.md#L121) 中，`complete()` / `complete_simple()` 已被冻结为直接返回 `AssistantMessage` 的 async API。

影响：

- 这会把 `complete*()` 语义重新混成“先返回 stream，再由调用方收敛”，等于削弱了四个顶层入口的职责区分。
- 如果不修正，后续实现很容易把 `complete*()` 做成薄包装泄漏内部 stream handle，而不是稳定完成型 API。

建议：

- 在交互文档里改成：`Top-Level AI API` 内部调用 `stream*()`，内部 await `result()`，然后直接向调用方返回 `AssistantMessage`。
- 调用方不应在 `complete*()` 路径中看到 event stream handle。

2. `Cancellation And Aborted Bridge` 的 ownership 当前不稳定，`Event Stream` 与 `Raw Assembler` 对终止语义的边界仍然重叠。

- 在 [loushang-ai-component-structure-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-structure-v1.md#L235) 到 [loushang-ai-component-structure-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-structure-v1.md#L249) 中，这个 domain 的主归属被放在 `Assistant Message Event Stream`。
- 在 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L364) 到 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L377) 中，同样继续把主拥有者写成 `Assistant Message Event Stream`。
- 但在 [loushang-ai-raw-part-design-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-raw-part-design-v1.md#L223) 到 [loushang-ai-raw-part-design-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-raw-part-design-v1.md#L225) 以及 [loushang-ai-raw-part-design-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-raw-part-design-v1.md#L327) 到 [loushang-ai-raw-part-design-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-raw-part-design-v1.md#L337) 中，`aborted` 明确先进入 assembler 收敛路径，再由 assembler 统一产出对外终止语义。
- 在 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L217) 到 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L219) 中，图上也是 `Provider -> Assembler -> Stream`。

影响：

- 现在“谁真正拥有终止语义收敛”没有完全拍死。
- 如果实现时继续按这个状态推进，很容易出现 assembler 和 stream 各自持有一份 abort/error 终止判断。

建议：

- 明确主拥有者：更合理的是 `Raw Assembler` 拥有终止语义收敛，`Assistant Message Event Stream` 只拥有对外读侧承载与暴露。
- `Cancellation And Aborted Bridge` 若继续保留为独立 domain，应把其主拥有者改为 `Raw Assembler`，`Event Stream` 改为主要外显挂载点。

### Medium

3. 接口依赖图与前文的抽象边界存在两处冲突，会误导后续实现依赖方向。

- 在 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L133) 到 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L168) 中，`API Registry` 被定义为只依赖 `APIAdapter Protocol`，不直接依赖具体 adapter class。
- 但在同一文档的依赖图 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L434) 到 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L435) 中，又画成了 `APIREG --> APIPROTO` 和 `APIREG --> ADAPTER`。
- 同样，接口文档前文把 `Assistant Message Event Stream` 定义成由 assembler 产物对外承载的统一读侧边界 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L252) 到 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L285)，但依赖图中却画成 `STREAM --> ASM` [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L441) 到 [loushang-ai-component-interfaces-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interfaces-v1.md#L443)。

影响：

- `API Registry` 是否知道 concrete adapter、`Stream` 与 `Assembler` 谁依赖谁，这两件事目前图文不一致。
- 这类图上的反向箭头很容易直接变成错误实现依赖。

建议：

- 把 `API Registry` 到具体 Adapter 的直接依赖箭头删掉，只保留“持有符合 `APIAdapter Protocol` 的对象”。
- 重新明确 `Assembler` 与 `Event Stream` 的依赖方向，至少要和“writer-side / reader-side” 叙述保持同一口径。

### Low

4. 组件交互文档的“主交互路径”计数与正文不一致，容易降低文档可信度。

- 在 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L45) 到 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L51) 中，文档写“当前先冻结 5 条主交互路径”，但正文实际列了 6 条，并且列表里漏写了 `complete_simple(...)`。

建议：

- 把这里修成 6 条，或把 `complete_simple(...)` 明确并入已有条目。

---

## Open Questions

1. `Context Intake And Normalization` 目前在结构文档中被放进“Functional Domain Components”，但其定位又写成 `supporting component` [loushang-ai-component-structure-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-structure-v1.md#L157) 到 [loushang-ai-component-structure-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-structure-v1.md#L175)。这一点未必是问题，但建议后续统一分类口径。
2. `Provider Bootstrap And Extensibility` 目前在 structure/interfaces 中被视为 supporting domain，而在交互文档里又以独立 participant 出现 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L232) 到 [loushang-ai-component-interactions-v1.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-component-interactions-v1.md#L257)。后续最好明确它是正式组件还是只保留为扩展点 domain。

---

## Passes

以下关键设计已经相对稳定，可以视为本轮评审通过项：

- `Top-Level AI API -> API Registry -> APIAdapter -> Raw Part -> Raw Assembler -> Assistant Message Event Stream` 这条总链路已经成型。
- `APIAdapter` 作为唯一直接理解具体 API 协议的边界组件，这个原则在多篇文档中保持一致。
- `raw part` 作为 adapter 与 assembler 之间的唯一标准中间边界，这个设计已经足够清楚，且与前面的 adapter strategy、validation 方向一致。
- `complete()` / `complete_simple()` 建立在 stream 语义上，这个大方向是稳定的，当前问题主要在交互图表达，而不是原则本身。

---

## Recommended Next Actions

1. 先修正文档层面的 3 个核心问题：
- `complete*()` 时序
- cancellation ownership
- 接口依赖方向图
2. 修完后再做一轮轻量复审，不需要重新开大评审。
3. 复审通过后，再进入实现计划会更稳。
