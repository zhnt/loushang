# Bootstrap Tool Contribution Boundary

## Status

Implementation complete for integration into `lane/harness`.

## Ownership

`harness.bootstrap.register_extension_tools` owns the shared bootstrap path
for extension-provided tools:

- projecting extension definitions into `ToolContribution` values;
- composing Product and extension packs with the standard capability composer;
- resolving duplicate contributions without mutating the registry;
- filtering conflict losers before registration;
- preserving contribution source information; and
- registering accepted definitions in the Product workspace registry.

The runtime does not know an extension framework, resource bundle schema, or
diagnostic wire format. Those are supplied as ports:

- extension definition/source-info callbacks;
- a bundle diagnostic merge callback;
- a Product diagnostic factory; and
- optional composer, resolver, and pack identifiers.

The default pack sources are neutral (`product.tools` and `extension.tools`),
while a Product may retain legacy source identifiers during a controlled
transition.

## Product Boundary

Coding adapts its existing `ExtensionRunner`, `ResourceBundle`, and
`DiagnosticDraft` values through a thin `_register_extension_tools` wrapper. It
retains only the Coding diagnostic code/message and existing pack identifiers.
Research, Design, PPT, and OEM-defined Products can bind different Extension
runtimes, bundles, and diagnostic records without copying the contribution
algorithm.

## Verification

`tests/harness/test_bootstrap.py` exercises the neutral path with opaque fake
extension and bundle types. Coding bootstrap characterization tests retain
the existing conflict, resolver, source-info, and registration behavior.
The Harness module has no Coding import.
