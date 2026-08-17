# Bootstrap Activation Collapse Boundary

## Purpose

Agent Products need the same startup transaction: validate startup inputs,
materialize package sources, configure resource roots, discover resources,
activate extensions, audit cwd-bound services, and refresh the model catalog.
Coding previously repeated the ordering and several leaf implementations in
`coding.bootstrap`.

This boundary collapses that duplication onto existing Harness components. It
does not add a second bootstrap engine or a service locator.

## Existing Owners

The activation path composes these existing owners:

- `ConfigActivationRuntime` executes the dependency graph and reverse cleanup;
- `BootstrapActivationRuntime` exposes its structured startup report;
- `ResourceBootstrapRuntime` owns resource discovery followed by extension
  activation and rediscovery;
- `PackageSourceResolver` and `configure_resource_loader_roots` own package and
  resource-root preparation;
- `DiagnosticsService` owns startup and resource diagnostic normalization;
- `SkillActivationRuntime` applies the Product-selected disabled-skill set;
- session cwd audit and `ModelCatalog` own their existing leaf operations; and
- `AgentSessionConstructionRuntime` owns the later tool and Agent construction
  pipeline.

`standard_agent_session_activation_plan()` only declares the standard stage
graph. `activate_standard_agent_session_configuration()` executes that plan
through `BootstrapActivationRuntime` and propagates the first contained
failure. Neither function implements an alternative activation engine.

## Physical Decomposition

The stable `harness.session.bootstrap` import path is a compatibility export
surface. Its implementation is split by responsibility without changing the
activation or construction contracts:

- `bootstrap_activation` owns the ordered activation plan and effect ports;
- `bootstrap_configuration` binds standard resource/configuration services to
  that plan;
- `bootstrap_services` owns cwd-bound service preparation and result values;
- `bootstrap_construction` owns Agent, tool, and Product session construction.

Dependencies flow from construction to configuration/services and from
configuration to activation. The compatibility module contains no runtime
implementation, and session internals import the concrete owner modules.

## Standard Stage Order

The shared profile fixes this dependency order:

1. `startup_checks`
2. `package_sources`
3. `resource_roots`
4. `resources`
5. `extensions`
6. `cwd_audit`
7. `model_registry`

Products bind the effect for each stage. A stage failure remains a structured
activation failure; later stages do not run, and the existing activation
runtime retains rollback responsibility.

## Shared Leaf Bindings

The standard binding also owns reusable operations that had been embedded in
Coding:

- resource and extension diagnostics normalization;
- extension flag validation and application;
- package lockfile diagnostics;
- package/user resource-root binding;
- standard cwd and package-root startup checks;
- semantic model-catalog layer reload;
- explicit/default model resolution and fallback diagnostics;
- prompt override precedence and appended fragment assembly;
- image-placeholder projection for Agent transcript context;
- extension-tool registration into `ResourceBundle`; and
- default session package install-root selection.

All differences remain injectable through callbacks, paths, settings, or
profiles. Structural ports are used where importing a concrete resource class
would introduce package cycles.

## Product Responsibilities

Coding continues to own:

- `DEFAULT_CODING_SYSTEM_PROMPT` and Coding resource content;
- creation of `CodingResourceLoader`, `CodingPackageMaterializer`, and the
  Coding extension loader/policy adapter;
- `.loushang/models` and executable identity conventions;
- Coding capability, prompt-section, tool-pack, approval, and image policy;
- Coding diagnostics wording beyond the shared records; and
- the concrete `AgentSession` and `AgentSessionRuntime` factories.

Design, PPT, Research, OEMs, and extensions can bind different effects and
defaults without copying activation order or the shared leaf mechanisms.

## Non-Goals

- moving Product prompts, resource packages, model preferences, or paths into
  Harness;
- provider registration, authentication, or credential discovery;
- replacing `ConfigActivationRuntime`, session lifecycle, or transcript
  lifecycle; or
- preserving private Coding helper imports after their owner moved.

## Verification

Independent Harness probes cover stage order, first-failure propagation,
resource/extension ordering, strict flag diagnostics, prompt/model resolution,
package roots, cwd audits, model reload, tool conflicts, and transcript image
projection. Coding bootstrap tests remain the behavior characterization suite.
Architecture tests continue to forbid Harness imports from Coding.
