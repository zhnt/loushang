# Product CLI Lifecycle Boundary

This boundary covers only process-host mechanics shared by product CLIs.  It
does not move argument grammar, mode selection, product command handlers,
resource/package wording, Work/Method preparation, or output schemas.

## Ownership

| Source mechanism | Shared owner | Product injection | Deletion condition |
| --- | --- | --- | --- |
| Repeated sequential turn invocation and non-final failure disposal in `coding.cli.__main__` | `harness.host.product_host.ProductHostLifecycle.run_turns` | Product supplies turn values, invocation callback, and runtime/session disposal candidates | Coding uses the lifecycle helper for prompt, print, and mode runner loops; no duplicate loop remains |
| TTY detection for injected streams | `harness.host.product_host.stream_is_tty` | None | Coding does not implement its own `isatty` probe |
| Prompt/stdin/file/image input normalization | `harness.host.prompt_input` | Coding supplies prompt/file arguments and the image-resize choice | Coding keeps argument parsing and prompt policy; shared resolver has no Coding import |
| Model listing normalization, sorting, query matching, and metadata table | `harness.session.model_selection` | Coding supplies the model getter and selects JSON/TSV output | Coding keeps preferred-model policy and persistence wording |
| Command descriptor listing projection | `harness.commands.project_command_descriptor` | Coding supplies descriptors and chooses JSON/TSV output | RPC serializers remain separate; no product wire fields are changed |
| Skill and installed-plugin listing projections | `harness.resources.skills.project_skill_descriptor`, `harness.resources.plugins.project_installed_plugin` | Coding supplies resource/settings discovery and output format | Harness owns only object-shape normalization; enable/disable and wording remain Coding |
| Session catalog record projection | `harness.transcript.project_session_record` | Coding supplies catalog query and output format | Coding keeps query grammar; Harness owns the portable record shape |
| Diagnostic record/error/summary JSON projection | `harness.diagnostics.serialization` | Products may select output transport; existing field shape is retained | No Coding serializer implementation remains; camelCase is preserved to avoid an unapproved protocol change |
| Package catalog/materialization record projection | `harness.resources.packages.projection` | Coding supplies discovery/materializer policy and output selection | Package records are projected without Coding imports; discovery and policy remain injectable |
| Resource enable/disable and plugin-source mutation | `harness.cli.resource_toggles` | Coding supplies package-source security, remote-source labeling, and diagnostics | Shared runtime returns ordered messages and preserves prior messages on failure |
| Package lifecycle operation ordering | `harness.cli.package_lifecycle` | Coding supplies install-source policy and JSONL serialization | Install, bulk update, and per-source operations preserve existing order and scope |
| Session command invocation and result normalization | `harness.cli.command_execution` | Coding supplies CLI values and stream projection | Slash normalization, missing-capability errors, and raw/JSON result shapes are shared |
| CLI new/restore/continue/fork selection | `harness.cli.session_resolution` | Coding supplies parsed arguments and runtime binding | Harness uses existing session lifecycle ports; no second session engine is introduced |
| Extension flag discovery and application | `harness.cli.extension_flags` | Coding supplies second-pass argparse typing and help text | Runner inspection is best-effort and has no Coding dependency |
| Method catalog and plan listing projection | `harness.cli.method_listing` | Coding supplies Method discovery and domain-specific compiler callback | Harness owns shape/formatting; Method domain is injected rather than hard-coded |
| Work event-log inspection and plan projection | `loushang.work.cli` | Coding supplies path/run/format flags | Work owns event-log reading and projection; Coding only adapts command errors and streams |

## Non-goals

The Harness Host layer must not import Coding, Channel, Method, or Work. It
must not parse Coding arguments, choose a Product mode, construct a Product
session, or project Product-specific output. Harness resource/session
projections likewise do not parse
Coding arguments or own product wording.  This slice therefore preserves all
CLI grammar, handlers, wire fields, error text, and product turn metadata.

## Acceptance

- prompt, print, and interactive mode runner ordering is unchanged;
- a non-final non-zero runner result disposes the injected runtime/session;
- final-turn failures do not cause a second disposal;
- a fake product can use the helper without importing Coding;
- the source diff is recorded in the shared-layer migration ledger.
