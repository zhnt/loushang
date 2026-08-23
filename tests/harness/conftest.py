from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)


@dataclass(frozen=True, slots=True)
class PublishedSyntheticPlugin:
    """Published executable-shaped Plugin fixture with no evaluation path."""

    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    import_marker: Path
    undeclared_import_marker: Path
    undeclared_import_trigger: Path


@dataclass(frozen=True, slots=True)
class PublishedDocumentPlugin:
    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    declaration: PluginDeclaration


@pytest.fixture
def published_synthetic_plugin(tmp_path: Path) -> Iterator[PublishedSyntheticPlugin]:
    source_root = tmp_path / "source" / "synthetic-provider"
    source_root.mkdir(parents=True)
    import_marker = tmp_path / "entrypoint-imported.txt"
    undeclared_import_marker = tmp_path / "undeclared-imported.txt"
    undeclared_import_trigger = tmp_path / "enable-undeclared-import"
    (source_root / "provider.py").write_text(
        "from pathlib import Path\n"
        f"if Path({str(undeclared_import_trigger)!r}).exists():\n"
        "    import helper\n"
        "from loushang.harness.capabilities import (\n"
        "    CapabilityBundleProvider, CapabilityContractRange,\n"
        ")\n"
        "from loushang.harness.plugin_authoring.capability_provider import (\n"
        "    CapabilityProviderDeclarationPayload, PluginSymbolReference,\n"
        ")\n"
        f"Path({str(import_marker)!r}).write_text('imported', encoding='utf-8')\n"
        "def create_provider(context):\n"
        "    raise AssertionError('declaration must not construct a provider')\n"
        "def declare(builder):\n"
        "    payload = CapabilityProviderDeclarationPayload(\n"
        "        provider=CapabilityBundleProvider(\n"
        "            capability_id='synthetic.capability',\n"
        "            provider_id='org.loushang.synthetic/default',\n"
        "            implementation_version=1,\n"
        "            compatible_contract=CapabilityContractRange.exact(1),\n"
        "            facets=('default',),\n"
        "            required_authorities=frozenset(),\n"
        "            source_id='plugin:synthetic-provider',\n"
        "            selection_rule='Plugin declaration candidate',\n"
        "        ),\n"
        "        factory=PluginSymbolReference(\n"
        "            path='provider.py',\n"
        "            symbol='create_provider',\n"
        "            execution_model='in_process',\n"
        "        ),\n"
        "        disposer=None,\n"
        "    )\n"
        "    builder.add_capability_provider(\n"
        "        contribution_id='synthetic-provider', payload=payload,\n"
        "    )\n"
        "    return builder.build()\n",
        encoding="utf-8",
    )
    (source_root / "helper.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(undeclared_import_marker)!r}).write_text(\n"
        "    'undeclared-imported', encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "synthetic-provider",
                "version": "1",
                "contributionIndex": {
                    "version": 2,
                    "items": [
                        {
                            "id": "synthetic-provider",
                            "kind": "capability_provider",
                            "owner": "synthetic.capability",
                            "contributionExecutionModel": "in_process",
                            "declarationSource": {
                                "entrypoint": "provider.py:declare",
                                "kind": "in_process",
                                "sourceVersion": 1,
                            },
                            "requestedAuthorities": [],
                            "configuration": {},
                            "required": True,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source_root))
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=materializer,
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    [contribution] = package.contribution_index.items
    fixture = PublishedSyntheticPlugin(
        runtime=runtime,
        package=package,
        binding=binding,
        contribution=contribution,
        import_marker=import_marker,
        undeclared_import_marker=undeclared_import_marker,
        undeclared_import_trigger=undeclared_import_trigger,
    )
    assert import_marker.exists() is False
    try:
        yield fixture
    finally:
        runtime.close()


@pytest.fixture
def published_document_plugin(tmp_path: Path) -> Iterator[PublishedDocumentPlugin]:
    source_root = tmp_path / "source" / "document-provider"
    declaration_root = source_root / "declarations"
    declaration_root.mkdir(parents=True)
    index_item = {
        "id": "document-provider",
        "kind": "capability_provider",
        "owner": "document.capability",
        "contributionExecutionModel": "in_process",
        "declarationSource": {
            "kind": "document",
            "locator": "declarations/providers.json",
            "mediaType": "application/vnd.loushang.plugin-declarations+json",
            "schemaId": "loushang.plugin-declaration-document",
            "schemaVersion": 1,
            "sourceVersion": 1,
        },
        "requestedAuthorities": [],
        "configuration": {},
        "required": True,
    }
    contribution = PluginContributionReservation.from_dict(index_item)
    declaration = PluginDeclaration(
        plugin_id="document-provider",
        contribution_id=contribution.contribution_id,
        kind=contribution.kind,
        owner=contribution.owner,
        reservation_fingerprint=contribution.fingerprint,
        source_descriptor_fingerprint=(
            contribution.source_descriptor_fingerprint
        ),
        source_kind=contribution.declaration_source.kind,
        payload={},
    )
    (declaration_root / "providers.json").write_bytes(
        PluginDeclarationDocumentCodec.encode_bytes(
            PluginDeclarationDocument(declarations=(declaration,))
        )
    )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "document-provider",
                "version": "1",
                "contributionIndex": {
                    "version": 2,
                    "items": [index_item],
                },
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source_root))
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=materializer,
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    fixture = PublishedDocumentPlugin(
        runtime=runtime,
        package=package,
        binding=binding,
        contribution=contribution,
        declaration=declaration,
    )
    try:
        yield fixture
    finally:
        runtime.close()
