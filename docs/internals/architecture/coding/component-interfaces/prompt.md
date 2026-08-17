# `prompt`

## Role

- Coding 默认提示词与 Harness 标准 prompt 能力之间的兼容适配层

## Owns

- `DEFAULT_CODING_SYSTEM_PROMPT`
- Coding 公共导入路径与无参数调用的默认行为兼容
- 仅 Coding 独有的 prompt 扩展（如果后续出现）

## Depends On

- `loushang.harness.capabilities.prompt`
- `loushang.harness.capabilities.prompt_assembly`
- `loushang.harness.capabilities.prompt_preflight`

## Commands

- `assemble_system_prompt(...)`
- `assemble_prompt(...)`

## Queries

- 无稳定 query surface

## Events

- 无

## Key Data

- Harness-owned `ResourceBundle`
- Harness-owned `PromptAssembly`

## Out Of Scope

- 资源发现
- skill 解析
- method registry/compiler/projector lifecycle
- tool execution
- session persistence

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 中 `system-prompt.ts` 与 session 内资源注入共同承担的 prompt assembly 职责
- 通用组装与 preflight 由 Harness 提供；Coding 保留薄适配层而不复制实现
