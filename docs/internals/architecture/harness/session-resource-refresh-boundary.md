# Session Resource Refresh Runtime Boundary

## Decision

`loushang.harness.session.SessionResourceRefreshRuntime` owns the ordered
refresh of an already-bound Product session resource bundle. It composes the
existing Harness resource refresh coordinator with a small session port set:

1. optionally prepare the bound Product runtime;
2. reload the bundle for the current Product cwd;
3. allow an optional extension runtime to contribute discovered resources;
4. apply the shared disabled-skill activation policy; and
5. commit the new bundle and rebuild the Product's prompt and tool view.

When the bound Extension runtime exposes the staged-generation seam, reload
uses the stronger
[Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md):
resource discovery and live binding occur on an unpublished candidate, runtime
and resources publish together, and the old generation retires only afterward.
The ordinary `refresh`/`refresh_async` methods remain the compatibility path for
resource-only refresh and runtimes without generation support.

An extension-requested refresh is failure-contained. Harness reports the
exception through a Product callback and synchronizes extension diagnostics
only after a successful refresh. It deliberately does not select a diagnostic
code or user-visible wording.

## Product Binding

Products supply the resource loader, resource bundle holder, cwd, settings,
optional extension discovery runtime, bundle commit callback, and view rebuild
callback. They also choose when a refresh is requested and how a failure is
recorded or rendered.

## Coding Binding

Coding `AgentSession` binds `DefaultResourceLoader`, its resolved resource
roots, disabled-skill settings, current `ExtensionRunner`, prompt/tool rebuild,
and the `extension_resource_refresh_failed` diagnostic projection. Its existing
watcher remains a Harness resource watcher whose Product callback chooses the
watch reload and subsequent Coding extension-runtime refresh behavior.

Coding keeps extension API event classes and binds the shared Extension session
coordinator. Resource-watch changes enter the same staged reload path rather
than refreshing the bundle twice. The former
`coding.session.resource_refresh_controller` has no parallel implementation.

## Dependency Rule

`harness.session.resource_refresh` may depend on Harness resource records,
activation, and refresh coordination. It must not import Coding, a concrete
resource loader or extension runner, Product settings, Product diagnostics, or
UI/RPC types. All such values cross the boundary through narrow callbacks and
protocols.

## Verification

- Independent Harness tests cover prompt-template lookup, synchronous and
  asynchronous extension discovery, disabled-skill activation, rebuild, and
  failure-contained requests.
- Coding `AgentSession` regressions retain its refresh, watcher, and extension
  API behavior, while staged reload failures preserve the previous generation.
- Architecture tests forbid Coding imports in the runtime, require the Coding
  binding, and prevent reintroducing the old Coding controller.
