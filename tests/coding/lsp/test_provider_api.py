from __future__ import annotations

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CODING_LSP_DIAGNOSTICS_FACET,
    CODING_LSP_SEMANTIC_FACET,
    CODING_LSP_TOOL_RUNTIME_FACET,
    CODING_LSP_TOOL_RUNTIME_REQUIREMENT,
    CODING_LSP_WORKSPACE_REQUIREMENT,
    CodingLspPluginConfigError,
    CodingLspPluginConfigV1,
    CodingLspToolRuntimeCapabilityConsumer,
    coding_lsp_capability_provider,
    create_coding_lsp_provider,
    dispose_coding_lsp_provider,
)
from loushang.coding.lsp.model import LspServerDefinition
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
from loushang.harness.runtime.registration import (
    RegistrationOwner,
    RegistrationScope,
)


class _WorkspaceRead:
    def __init__(self) -> None:
        self.exists_calls: list[Path] = []
        self.read_calls: list[Path] = []

    async def exists(self, path: Path) -> bool:
        self.exists_calls.append(path)
        return path.name == "pyproject.toml"

    async def read_bytes(self, path: Path) -> bytes:
        self.read_calls.append(path)
        return path.read_bytes()


class _WorkspaceProcessLaunch:
    def __init__(self) -> None:
        self.start_count = 0

    async def start(self, *args: object, **kwargs: object) -> object:
        del args, kwargs
        self.start_count += 1
        raise AssertionError("Provider construction must not start an LSP process")


def _definition() -> LspServerDefinition:
    return LspServerDefinition(
        id="python-test",
        command=("python-language-server", "--stdio"),
        language_extensions={"python": (".py",)},
        root_markers=("pyproject.toml",),
        environment={"PYTHONUTF8": "1"},
        initialization_options={"analysis": {"diagnosticMode": "openFilesOnly"}},
        settings={"python": {"analysis": {"typeCheckingMode": "basic"}}},
        source="product-test",
    )


def _config(tmp_path: Path) -> CodingLspPluginConfigV1:
    return CodingLspPluginConfigV1.from_runtime_inputs(
        workspace_root=tmp_path,
        definitions=(_definition(),),
        baseline_environment={"PATH": "/admitted/bin"},
    )


def test_private_provider_descriptor_matches_the_declared_capability() -> None:
    provider = coding_lsp_capability_provider()

    assert provider.capability_id == CODING_LSP_CAPABILITY_DEFINITION.capability_id
    assert provider.provider_id == "coding.lsp.default"
    assert provider.compatible_contract.accepts(
        CODING_LSP_CAPABILITY_DEFINITION.contract_version
    )
    assert provider.facets == CODING_LSP_CAPABILITY_DEFINITION.facets
    assert provider.requirements == (CODING_LSP_WORKSPACE_REQUIREMENT,)
    assert provider.required_authorities == frozenset({"filesystem", "process"})
    assert provider.source_id == "plugin:coding.lsp.default"
    assert provider.selection_rule == PLUGIN_PROVIDER_SELECTION_RULE


def test_tool_runtime_consumer_captures_only_its_declared_facet() -> None:
    runtime = object()
    bundle = CapabilityBundleValue(
        (CapabilityFacetBinding(CODING_LSP_TOOL_RUNTIME_FACET, runtime),)
    )
    state = RuntimeBindingState(bundle)
    consumer = CodingLspToolRuntimeCapabilityConsumer(
        CapabilityFacetSet(
            requirement=CODING_LSP_TOOL_RUNTIME_REQUIREMENT,
            _lease=state.capture(),
        )
    )

    assert consumer.runtime is runtime
    assert consumer.facets.facet_ids == (CODING_LSP_TOOL_RUNTIME_FACET,)

    state.invalidate()
    with pytest.raises(RuntimeError, match="stale"):
        _ = consumer.runtime


def test_tool_runtime_consumer_rejects_a_foreign_requirement() -> None:
    state = RuntimeBindingState(CapabilityBundleValue(()))

    with pytest.raises(ValueError, match="wrong facet view"):
        CodingLspToolRuntimeCapabilityConsumer(
            CapabilityFacetSet(
                requirement=CODING_LSP_WORKSPACE_REQUIREMENT,
                _lease=state.capture(),
            )
        )


def test_plugin_config_round_trips_canonical_runtime_inputs(tmp_path: Path) -> None:
    config = _config(tmp_path)

    decoded = CodingLspPluginConfigV1.from_mapping(config.to_dict())

    assert decoded == config
    assert decoded.workspace_root == tmp_path.resolve()
    assert decoded.definitions == (_definition(),)
    assert decoded.baseline_environment == {"PATH": "/admitted/bin"}
    assert decoded.to_dict() == config.to_dict()


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "fields"),
        (lambda value: value.update({"configVersion": 2}), "version"),
        (
            lambda value: value.update({"workspaceRoot": "relative/workspace"}),
            "absolute",
        ),
        (
            lambda value: value.update({"baselineEnvironment": {"PATH": 7}}),
            "environment",
        ),
        (
            lambda value: value.update(
                {"servers": [*value["servers"], *value["servers"]]}
            ),
            "duplicate",
        ),
    ],
)
def test_plugin_config_rejects_noncanonical_json(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    value = deepcopy(_config(tmp_path).to_dict())
    mutate(value)

    with pytest.raises(CodingLspPluginConfigError, match=message) as captured:
        CodingLspPluginConfigV1.from_mapping(value)

    assert captured.value.code == "invalid_coding_lsp_plugin_configuration"


def test_private_provider_publishes_one_lazy_complete_bundle(tmp_path: Path) -> None:
    read = _WorkspaceRead()
    process = _WorkspaceProcessLaunch()
    workspace = CapabilityBundleValue(
        (
            CapabilityFacetBinding("read", read),
            CapabilityFacetBinding("process.launch", process),
        )
    )
    owner = RegistrationOwner(
        owner_kind="capability",
        owner_id="coding.lsp",
        runtime_id="runtime-test",
        generation=1,
    )
    context = CapabilityProviderContext(
        product_id="coding",
        runtime_id="runtime-test",
        generation=1,
        registrations=CapabilityRegistrationCollector(RegistrationScope(owner)),
        dependencies=(
            CapabilityDependencyBinding(
                requirement=CODING_LSP_WORKSPACE_REQUIREMENT,
                _value=workspace,
            ),
        ),
        binding_inputs=_config(tmp_path).to_dict(),
    )

    bundle = create_coding_lsp_provider(context)

    assert bundle.facet_ids == (
        CODING_LSP_SEMANTIC_FACET,
        CODING_LSP_TOOL_RUNTIME_FACET,
        CODING_LSP_DIAGNOSTICS_FACET,
    )
    session = bundle.require(CODING_LSP_SEMANTIC_FACET)
    tools = bundle.require(CODING_LSP_TOOL_RUNTIME_FACET)
    diagnostics = bundle.require(CODING_LSP_DIAGNOSTICS_FACET)
    assert len({id(session), id(tools), id(diagnostics)}) == 3
    assert not hasattr(session, "close")
    assert not hasattr(tools, "close")
    assert not hasattr(diagnostics, "close")
    assert session.status().servers == ()
    assert diagnostics.snapshot().document_count == 0
    assert process.start_count == 0
    assert read.exists_calls == []
    assert read.read_calls == []

    asyncio.run(dispose_coding_lsp_provider(bundle))

    assert session.status().disposed is True
    assert process.start_count == 0


def test_private_provider_rejects_a_foreign_product(tmp_path: Path) -> None:
    owner = RegistrationOwner(
        owner_kind="capability",
        owner_id="coding.lsp",
        runtime_id="runtime-test",
        generation=1,
    )
    context = CapabilityProviderContext(
        product_id="foreign",
        runtime_id="runtime-test",
        generation=1,
        registrations=CapabilityRegistrationCollector(RegistrationScope(owner)),
        binding_inputs=_config(tmp_path).to_dict(),
    )

    with pytest.raises(ValueError, match="Coding Product"):
        create_coding_lsp_provider(context)
