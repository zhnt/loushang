from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from loushang.coding.arch._provider_api import (
    CODING_ARCH_ANALYSIS_FACET,
    CODING_ARCH_CAPABILITY_DEFINITION,
    CODING_ARCH_DIAGNOSTICS_FACET,
    CODING_ARCH_TOOL_RUNTIME_FACET,
    CODING_ARCH_TOOL_RUNTIME_REQUIREMENT,
    CODING_ARCH_WORKSPACE_REQUIREMENT,
    CodingArchPluginConfigError,
    CodingArchPluginConfigV1,
    CodingArchToolRuntimeCapabilityConsumer,
    coding_arch_capability_provider,
    create_coding_arch_provider,
    dispose_coding_arch_provider,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleValue,
    CapabilityDependencyBinding,
    CapabilityFacetBinding,
    CapabilityProviderContext,
    CapabilityRegistrationCollector,
)
from loushang.harness.plugin_authoring.capability_provider import (
    PLUGIN_PROVIDER_SELECTION_RULE,
)
from loushang.harness.runtime.bindings import RuntimeBindingState
from loushang.harness.runtime.registration import RegistrationOwner, RegistrationScope


class _WorkspaceRead:
    def exists(self, _path: Path) -> bool:
        return True

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()


class _WorkspaceList:
    def exists(self, _path: Path) -> bool:
        return True

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def iterdir(self, path: Path):
        return path.iterdir()


class _WorkspaceSearch:
    def exists(self, _path: Path) -> bool:
        return True

    def is_file(self, path: Path) -> bool:
        return path.is_file()

    def is_dir(self, path: Path) -> bool:
        return path.is_dir()

    def read_text(self, path: Path, *, newline: str | None = None) -> str:
        del newline
        return path.read_text(encoding="utf-8")

    def walk_files(self, path: Path):
        return (item for item in path.rglob("*") if item.is_file())


def _config(tmp_path: Path) -> CodingArchPluginConfigV1:
    return CodingArchPluginConfigV1.from_runtime_inputs(
        workspace_root=tmp_path / "workspace",
        private_data_root=tmp_path / "private",
        private_state_quota_bytes=4096,
    )


def _context(tmp_path: Path) -> CapabilityProviderContext:
    workspace = CapabilityBundleValue(
        (
            CapabilityFacetBinding("read", _WorkspaceRead()),
            CapabilityFacetBinding("list", _WorkspaceList()),
            CapabilityFacetBinding("search", _WorkspaceSearch()),
        )
    )
    owner = RegistrationOwner(
        owner_kind="capability",
        owner_id="coding.arch",
        runtime_id="runtime-test",
        generation=1,
    )
    return CapabilityProviderContext(
        product_id="coding",
        runtime_id="runtime-test",
        generation=1,
        registrations=CapabilityRegistrationCollector(RegistrationScope(owner)),
        dependencies=(
            CapabilityDependencyBinding(
                requirement=CODING_ARCH_WORKSPACE_REQUIREMENT,
                _value=workspace,
            ),
        ),
        binding_inputs=_config(tmp_path).to_dict(),
    )


def test_arch_provider_descriptor_matches_the_declared_capability() -> None:
    provider = coding_arch_capability_provider()

    assert provider.capability_id == CODING_ARCH_CAPABILITY_DEFINITION.capability_id
    assert provider.provider_id == "coding.arch.default"
    assert provider.facets == CODING_ARCH_CAPABILITY_DEFINITION.facets
    assert provider.requirements == (CODING_ARCH_WORKSPACE_REQUIREMENT,)
    assert provider.required_authorities == frozenset({"filesystem"})
    assert provider.source_id == "plugin:coding.arch.default"
    assert provider.selection_rule == PLUGIN_PROVIDER_SELECTION_RULE


def test_arch_plugin_config_round_trips_exact_inputs(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert CodingArchPluginConfigV1.from_mapping(config.to_dict()) == config
    assert config.workspace_root == (tmp_path / "workspace").resolve()
    assert config.private_data_root == (tmp_path / "private").resolve()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "fields"),
        (lambda value: value.update({"configVersion": 2}), "version"),
        (lambda value: value.update({"workspaceRoot": "relative"}), "absolute"),
        (lambda value: value.update({"privateDataRoot": "relative"}), "absolute"),
        (lambda value: value.update({"privateStateSchemaVersion": 2}), "schema"),
        (lambda value: value.update({"privateStateQuotaBytes": True}), "integer"),
        (lambda value: value.update({"privateStateQuotaBytes": 0}), "range"),
    ],
)
def test_arch_plugin_config_rejects_noncanonical_values(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    value = deepcopy(_config(tmp_path).to_dict())
    mutate(value)

    with pytest.raises(CodingArchPluginConfigError, match=message) as captured:
        CodingArchPluginConfigV1.from_mapping(value)

    assert captured.value.code == "invalid_coding_arch_plugin_configuration"


def test_arch_provider_publishes_one_shared_lazy_bundle(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "sample.py").write_text("import os\n", encoding="utf-8")

    bundle = create_coding_arch_provider(_context(tmp_path))

    assert bundle.facet_ids == (
        CODING_ARCH_ANALYSIS_FACET,
        CODING_ARCH_TOOL_RUNTIME_FACET,
        CODING_ARCH_DIAGNOSTICS_FACET,
    )
    tool_runtime = bundle.require(CODING_ARCH_TOOL_RUNTIME_FACET)
    result = tool_runtime.inspect(root=".", query="summary")
    assert result["schema_version"] == 1
    assert result["root"] == str(workspace.resolve())
    assert (tmp_path / "private" / "import-facts-v1.json").is_file()

    dispose_coding_arch_provider(bundle)

    with pytest.raises(RuntimeError, match="disposed"):
        tool_runtime.inspect(root=".", query="summary")


def test_arch_tool_consumer_captures_only_tool_runtime() -> None:
    runtime = object()
    state = RuntimeBindingState(
        CapabilityBundleValue(
            (CapabilityFacetBinding(CODING_ARCH_TOOL_RUNTIME_FACET, runtime),)
        )
    )
    consumer = CodingArchToolRuntimeCapabilityConsumer(
        CapabilityFacetSet(
            requirement=CODING_ARCH_TOOL_RUNTIME_REQUIREMENT,
            _lease=state.capture(),
        )
    )

    assert consumer.runtime is runtime
    assert consumer.facets.facet_ids == (CODING_ARCH_TOOL_RUNTIME_FACET,)

    state.invalidate()
    with pytest.raises(RuntimeError, match="stale"):
        _ = consumer.runtime


def test_arch_provider_rejects_foreign_product(tmp_path: Path) -> None:
    context = _context(tmp_path)
    foreign = CapabilityProviderContext(
        product_id="foreign",
        runtime_id=context.runtime_id,
        generation=context.generation,
        registrations=context.registrations,
        dependencies=context.dependencies,
        binding_inputs=context.binding_inputs,
    )

    with pytest.raises(ValueError, match="Coding Product"):
        create_coding_arch_provider(foreign)
