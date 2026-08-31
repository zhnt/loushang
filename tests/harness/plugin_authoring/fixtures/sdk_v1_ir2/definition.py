"""Non-example public SDK conformance package; validation must not execute it."""

from loushang.plugin import capability_provider, plugin_definition


@plugin_definition
def declare(plugin):
    plugin.add(
        capability_provider(
            contribution_id="echo-provider",
            capability="example.echo",
            provider_id="org.example.echo/default",
            implementation_version=1,
            contract=1,
            facets=("echo",),
            factory="definition.py:create_provider",
            disposer=None,
        )
    )


def create_provider(context):
    raise AssertionError("conformance validation imported executable Plugin code")
