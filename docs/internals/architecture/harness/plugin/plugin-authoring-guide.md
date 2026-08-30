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
            factory="definition.py:create_provider",
            disposer="definition.py:dispose_provider",
        )
    )
```

The Definition receives only the narrow builder. It does not receive a Graph,
registry, Product context, Approval store, Sandbox, secrets, or live owner.

## Skill Resource And Managed Action

```python
from hashlib import sha256

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
```

Write `generated.artifacts` under the package root, then add
`skills/review/SKILL.md` and the exact script bytes at
`skills/review/scripts/review.py`. `SKILL.md` remains the Resource identity;
the generated `actions.json` is only its managed-action sidecar. Environment
literals are non-secret. Execution always requires Host Approval and required
containment.

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
