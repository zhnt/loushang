# Plugin Authoring Guide

This guide covers the stable PLC8 author surface. A Plugin declares data and
references; Loushang's existing owners select, admit, bind, authorize, publish,
and retire runtime objects.

## Capability Provider

```python
from loushang.plugin import (
    PluginDefinitionBuilder,
    capability_provider,
    plugin_definition,
)


@plugin_definition
def declare(plugin: PluginDefinitionBuilder) -> None:
    plugin.add(
        capability_provider(
            contribution_id="echo-provider",
            capability="example.echo",
            provider_id="org.example.echo/default",
            implementation_version=1,
            contract=1,
            facets=("echo",),
            factory="provider.py:create_provider",
            disposer="provider.py:dispose_provider",
        )
    )
```

The referenced `provider.py` uses only the exact public provider-runtime ABI:

```python
from loushang.plugin.provider_runtime import (
    CapabilityBundleValue,
    CapabilityFacetBinding,
    CapabilityProviderContext,
)


class EchoProvider:
    def __init__(self) -> None:
        self.closed = False

    def echo(self, value: str) -> str:
        return value

    async def close(self) -> None:
        self.closed = True


def create_provider(_context: CapabilityProviderContext) -> CapabilityBundleValue:
    return CapabilityBundleValue(
        facets=(CapabilityFacetBinding("echo", EchoProvider()),)
    )


async def dispose_provider(value: CapabilityBundleValue) -> None:
    provider = value.require("echo")
    if not isinstance(provider, EchoProvider):
        raise TypeError("echo facet has an unexpected value")
    await provider.close()
```

The Definition receives only the narrow builder. Provider source may directly
import Host API names only from the exact
`loushang.plugin.provider_runtime` module; broad author-SDK and Harness
Capability imports are rejected. This is a supported import/API boundary for
trusted host-equivalent Python, not an isolation boundary against reflection or
same-process introspection. The factory receives a
narrow `CapabilityProviderContext` and returns the exact declared facets in a
`CapabilityBundleValue`; the disposer receives that same bundle. Neither path
receives a Graph, Product registry, Approval store, Sandbox, secrets, or a
live owner/service locator.

## Skill Resource And Managed Action

```python
from hashlib import sha256
from pathlib import Path

from loushang.plugin import package, resource, skill_action, skill_action_effect

script = b"print('review')\n"
review = resource.skill(
    contribution_id="review-skill",
    locator="skills/review",
    actions=(
        skill_action(
            id="review",
            script="scripts/review.py",
            script_digest=sha256(script).hexdigest(),
            runtime="python",
            argv=("--check",),
            effects=(
                skill_action_effect(
                    kind="filesystem.read",
                    target="workspace",
                ),
            ),
        ),
    ),
)
generated = package(
    id="org.example.review",
    version="1.0.0",
    contributions=(review,),
)

package_root = Path("my-plugin")
for artifact in generated.artifacts:
    target = package_root / artifact.path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(artifact.content)

skill_root = package_root / "skills" / "review"
skill_root.mkdir(parents=True, exist_ok=True)
(skill_root / "SKILL.md").write_text("# Review\n", encoding="utf-8")
(skill_root / "scripts").mkdir()
(skill_root / "scripts" / "review.py").write_bytes(script)
```

`SKILL.md` remains the Resource identity; the generated `actions.json` is only
its managed-action sidecar. Environment literals have an author-enforced
non-secret precondition—validation does not classify arbitrary strings or
resolve secrets. Execution always requires Host Approval and required
containment. PLC8 managed execution is currently admitted only on Linux with
the Harness-owned Bubblewrap backend, immutable sealed-executable support, and
Bubblewrap's `--ro-bind-data` plus `--ro-bind-fd` features. A Linux host missing
those two managed-bind features may still use ordinary Sandbox execution, but
it cannot acquire managed-action start authority.
Managed actions are also available only from the exact graph-owned Resource
generation. That owner derives the immutable action facts and constructs the
canonical Skill consumer atomically; it accepts no caller-provided capture,
consumer, or transferable grant. Copying Catalog fields into another consumer
does not create action-owner authority, and no owner-construction capability is
part of the public author SDK.
Other hosts may compile, inspect, and validate the declaration, but execution
fails closed until they provide an equally strong owner-admitted mechanism.

## Validate Before Execution

```text
loushang-plugin validate ./my-plugin
```

Validation is safe for inspection: it does not import or execute Definition
code. To run developer conformance in the current same-trust process, use the
separate explicit command:

```text
loushang-plugin conformance ./my-plugin --approve-execution
```

The conformance command executes package Python. Use it only for code you
trust. It is not activation Approval, containment, or a substitute for the
runtime Plugin lifecycle.
