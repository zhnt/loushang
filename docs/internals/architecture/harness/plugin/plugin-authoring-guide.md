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


class EchoProvider:
    def echo(self, value: str) -> str:
        return value

    async def close(self) -> None:
        return None


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
            factory="definition.py:create_provider",
            disposer="definition.py:dispose_provider",
        )
    )


def create_provider():
    return EchoProvider()


async def dispose_provider(provider) -> None:
    await provider.close()
```

The Definition receives only the narrow builder. It does not receive a Graph,
registry, Product context, Approval store, Sandbox, secrets, or live owner.

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
