# Coding Arch Traceability

[Coding Arch Architecture](README.md) | [Requirements](requirements.md) |
[Component Model](component-model.md)

## Status

- Authority: descriptive — evidence map
- Design status: proposed
- Implementation status: partial
- Owner: Coding Product

| Requirement | Components | Executable evidence | Status |
| --- | --- | --- | --- |
| COD-ARCH-FR-001 | Language Provider | `tests/coding/arch/test_import_graph.py` discovery/exclude/symlink cases | implemented |
| COD-ARCH-FR-002 | Fact Model, Language Provider | provider replacement and normalized scan tests | implemented |
| COD-ARCH-FR-003 | Python Provider, Fact Model | relative import and category tests | implemented |
| COD-ARCH-FR-004 | Analyzer And Projector | module/subsystem projection and prefix inference tests | implemented |
| COD-ARCH-FR-005 | Query Engine | cycles/path/hotspots/edges bounding tests | implemented |
| COD-ARCH-FR-006 | Query Engine, CLI Adapter | boundary query and CLI failing-gate tests | implemented |
| COD-ARCH-FR-007 | Fact Cache | `tests/coding/arch/test_cache.py` | implemented |
| COD-ARCH-FR-008 | CLI Adapter | `tests/coding/arch/test_cli.py` | implemented |
| COD-ARCH-FR-009 | Tool Runtime | workspace containment, Session gateway and policy tests in `test_tool.py` | implemented |
| COD-ARCH-FR-010 | Tool Pack Binding | `tests/coding/arch/test_activation.py` and mount-mode tests | implemented |
| COD-ARCH-FR-011 | Language Provider, Analyzer | replaceable-provider test; second concrete language provider absent | partial |
| COD-ARCH-FR-012 | future semantic-fact consumer port | LSP/Arch documents only; no initial Capability edge | not-started |

The matrix maps stable requirements to existing test groups without duplicating
their assertions. New requirements or components update this matrix and the
corresponding executable evidence together.
