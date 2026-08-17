# OEM And Extension Architecture

## Status

Draft.

This document describes how OEM customisation, extension contributions, and
harness upgrades interact. It is a cross-cutting design reference, not a
boundary decision for a single module.

Canonical Product, OEM, package, plugin, and capability terms are defined in
the [Product And OEM Glossary](../../glossary/loushang-product.md). In
particular, this draft's older phrase "OEM product" must not be read as a
synonym for every OEM Package or OEM Profile.

Accepted boundary decisions that inform this document:

- [Shared Capability Boundaries](shared-capability-boundaries.md)
- [Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md)
- [Extension Runtime Core Boundary](extension-runtime-core-boundary.md)
- [Contribution Inventory Boundary](contribution-inventory-boundary.md)
- [Refactoring Principles](refactoring-principles.md)

## OEM Override Depth Depends On Extension Capability Breadth

A simple rule governs the OEM relationship:

> OEM customisation depth = what extension surfaces can carry + what
> protocols OEMs can inject + what resources OEMs can overlay.

If the extension framework only supports registering tools and injecting
resource roots, OEMs can only ship custom tools and override skill/prompt
content. If the framework supports policy injection and channel adapter
registration, OEMs can ship a deeply customized Product configuration with
custom permissions, models, and delivery surfaces without forking Product
source. A distinct Product identity still requires the Product Package
registration contract described below.

This is not a theoretical concern. Every surface type and injection protocol
that an OEM needs but cannot express through an extension becomes a reason for
the OEM to fork harness or product code — exactly the outcome the architecture
is designed to prevent.

## Three Override Mechanisms

OEMs override loushang behaviour through three mechanisms, none of which
require modifying harness or product source code:

### 1. Protocol Injection

Harness defines a protocol; OEM supplies an implementation; Harness calls
the implementation without knowing who supplied it.

```python
# Harness defines the contract
class PolicyEvaluator(Protocol):
    def evaluate(self, subject: str) -> PolicyDecision: ...

# OEM supplies the implementation
class OEMSecurityPolicy:
    def evaluate(self, subject: str) -> PolicyDecision:
        return PolicyDecision.deny("restricted") if is_blocked(subject) \
            else PolicyDecision.allow()

# Product or Host injects the OEM implementation
harness.inject_policy(OEMSecurityPolicy())
```

Injection is not extension. It happens at product-assembly or host-startup
time, before any extension is loaded. The injected implementation runs inside
the harness mechanism. A channel adapter, a model router, or a compaction
policy can all be injected through this pattern.

Injected protocols are governed by the [protocol contract](refactoring-principles.md#upgrade-compatibility-contracts):
additive evolution only. New methods get default implementations; old
signatures are preserved.

### 2. Resource Overlay

OEM resource directories are discovered alongside built-in and product
directories. Files with the same identity shadow lower-precedence layers.

```text
discovery order (lowest to highest):
  built-in packages  (loushang.coding.resources, etc.)
  user ~/.loushang/
  project .loushang/
  OEM overlay        ← highest overridable layer
  temporary / runtime

merge rule:
  same (type, name) key → higher layer wins
  different keys → additive
```

An OEM ships overlay directories for skills, methods, prompts, and themes.
The resource loader discovers them through the standard platform layout;
OEMs do not need to register custom loaders.

Resource overlays are governed by the [resource contract](refactoring-principles.md#upgrade-compatibility-contracts):
layout conventions and loader merge algorithms are stable.

### 3. Extension Registration

OEMs ship extensions that declare `ExtensionSurfaceDescriptor` records.
Extensions are executable or declarative contributions for tools, commands,
hooks, model providers, channel adapters, and (when the surface types exist)
policy and approval implementations. Plugins or Resource Packages carry those
contributions; the Extension itself is not the packaging boundary.

```python
# OEM extension shipped as a plugin
class OEMExtension:
    surfaces = (
        ExtensionSurfaceDescriptor(
            type="tool",
            name="oem-audit",
            extension_id="oem-core",
            source_path=Path("oem/extensions/audit.py"),
            priority=10,
        ),
        ExtensionSurfaceDescriptor(
            type="hook",
            name="oem-before-tool",
            extension_id="oem-core",
            source_path=Path("oem/extensions/hooks.py"),
        ),
    )
```

Extension contributions are validated and indexed by
`loushang.harness.contributions`. The product adapter or OEM layer decides
activation. Harness does not trust or activate an extension by default.

## Extension Categories

Extensions fall into three categories with different execution semantics.
This categorisation is important because OEMs typically need all three:

| Category | Execution | OEM use case |
| --- | --- | --- |
| **Contribution** (aggregate) | All declarations run independently; failure is isolated | Ship custom tools, commands, methods, skills |
| **Interceptor** (pipeline) | Handlers form a pipeline; each sees previous output; failure governed by `on_error` | Ship custom hooks and policy evaluators |
| **Replacement** (one active provider) | Only one provider is active for the surface; selected-provider failure propagates without implicit fallback | Ship approval resolvers, side-question providers, custom model providers, channel adapters, storage backends |

These are applications of the canonical Aggregate Contribution, Ordered
Interception, and Exclusive Replacement semantics. A decorator is a restricted
interceptor that preserves the selected provider's authority and lifecycle;
`override` alone is not a conflict-resolution rule. The
[Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md)
is authoritative for admission, resolution, binding, disposal, and invariant
enforcement.

Harness extension dispatch now provides stable dependency-aware observer,
interceptor, reducer, and first-match routing. Policy contributions use the
interceptor chain; approval contributions use an exclusive replacement slot.
Agent Extensions may also declare the focused
`interaction.side_question` Runtime Capability replacement. Coding converts
that declaration into an admitted runtime-profile layer only when the effective
Extension policy grants the same permission; this is not a generic API for
registering arbitrary factories or slots.
The Product/OEM layer still supplies activation and trust decisions; Harness
enforces them while building executable routes and registries. See the
[Control Plane Runtime Boundary](control-plane-runtime-boundary.md).

## ExtensionSurfaceType Gaps

Policy and approval now have focused runtime contribution records and injection
paths. Method and Channel remain outside Harness until their owning layers
define corresponding registries.

Missing surface types and the harness processing path each requires:

| Surface type | What it carries | Harness processing path |
| --- | --- | --- |
| `policy` | A `PolicyEvaluator` implementation | Harness validates it and composes it into the resolved evaluator chain |
| `approval` | An `ApprovalResolver` implementation | Harness validates the exclusive replacement and supplies it to the approval broker |
| `method` | A method resource (`METHOD.md` or `SKILL.md` path) | Method loader discovers and registers it |
| `channel` | A channel adapter (transport + encoding) | Channel registry accepts and activates it |

The remaining Method and Channel surface types each need:
1. A `from_surface()` factory in the corresponding harness module.
2. An injection path from `ExtensionInventory` to the harness engine.
3. Contract tests proving an OEM can ship the surface in a plugin without
   importing product packages.

## OEM Upgrade Compatibility

The fundamental guarantee is:

> Harness upgrades improve mechanisms. OEM overrides supply policy and
> content. Mechanisms and policies are separated by stable contracts.

When harness upgrades:

| What changes | What OEM must do | Why |
| --- | --- | --- |
| Protocol gains a new optional method with default implementation | Nothing | OEM's existing implementation satisfies the old signature; new method falls back to default |
| Dataclass gains a new field with default value | Nothing | OEM code that constructs instances uses keyword arguments; omitted new field gets the default |
| Resource loader becomes faster | Nothing | OEM files are in standard locations; loader discovers them the same way |
| WorkEvent gains a new `kind` value | Nothing (if OEM ignores unknown kinds) | Channel contract requires unknown-field tolerance |
| Protocol removes or renames a method | OEM must update | This is a breaking change and should only happen across major version boundaries with migration notes |

### OEM Contract Tests

Harness CI must include a focused OEM contract-test suite. Each test
validates one compatibility boundary without depending on a specific product:

```text
oem_policy_protocol    — an OEM PolicyEvaluator still satisfies the protocol
oem_model_resolution   — an OEM model registered via overlay is still resolvable
oem_resource_overlay   — OEM skills/methods/prompts in a resource root still load
oem_extension_loading  — an OEM plugin with tool/hook surfaces still loads and dispatches
```

These tests assert the harness boundary. Product-specific integration tests
are separate and remain in product packages.

## OEM Package And Plugin Contributions

An OEM Package is the installable distribution boundary. It may bundle OEM
Profile configuration, resource overlays, and one or more manifest-backed
Plugins that carry optional Extension contributions:

```text
oem-foocorp/
  loushang-plugin.json           # optional Plugin contribution identity
  models/
    foocorp-models.json           # model registry overlay
  skills/
    secure-review/SKILL.md        # OEM skill content
  methods/
    compliance-audit/METHOD.md    # OEM method content
  prompts/
    foocorp-instructions.md       # OEM system prompt
  themes/
    foocorp.json                  # OEM branding
  extensions/
    foocorp_policy.py             # OEM PolicyEvaluator extension
    foocorp_audit_tool.py         # OEM custom tool extension
    foocorp_feishu_adapter.py     # OEM channel adapter extension
  config/
    overrides.yaml                # OEM configuration defaults
```

`loushang-plugin.json` declares only the Plugin identity and contributions.
It does not define the OEM identity, replace the OEM Profile, or register a
Product. `PluginResolver` reads the manifest, `PluginManager` manages Plugin
activation, and the resource loader discovers the standard directories. No
code in an OEM-carried Plugin needs to import Harness internals.

## Relationship To Product Kernel

An OEM Package may additionally distribute an OEM-defined Product. That
Product is first-class only when it supplies a distinct Product Kernel,
`product_id`, Product Descriptor, Product Factory, and Product Adapter through
the Product Package registration contract. It then has the same relationship
to Harness as Coding:

```text
product adapter
  -> depends on harness protocols
  -> injects policy and activation decisions
  -> owns domain tools, prompts, and artifact semantics
```

The distribution difference is that Coding currently ships with the main
repository while an OEM-defined Product may ship in an external Product
Package. It is not registered merely because an OEM Plugin is installed. The
Harness Product boundary otherwise treats admitted Product Packages uniformly.

An OEM Profile that only rebrands, configures, or overlays Coding remains an
OEM-configured Coding Product. It does not create a new Product identity.

When only tool activation, permissions, resources, models, branding, or
delivery surfaces differ, the OEM should use Profile overlays and admitted
Plugin contributions. When the OEM defines a distinct Product Kernel or domain,
it may derive or write a Product Adapter and distribute it through a Product
Package with a distinct Product identity.

## Non-Goals

This document does not:

- Define a marketplace protocol for OEM Package distribution or Resource
  Packages that carry Plugin manifests.
- Specify a signing or distribution-trust model for OEM Packages or Resource
  Packages carrying Plugins.
- Describe multi-tenant OEM hosting where one deployment serves multiple
  OEM configurations.
- Cover OEM-specific licensing or commercial terms.
