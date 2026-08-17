from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.ontology.schema import SchemaIdentity
from loushang.ontology.source import (
    ApplicationSchemaIdentity,
    MappedSourceInput,
    MappedSourceSnapshot,
    SourceAdapter,
    SourceAdapterContractError,
    SourceAdapterManifest,
    SourceBinding,
    SourceCoverage,
    SourceInputRevision,
    validate_source_adapter_outputs,
)

TARGET_SCHEMA = SchemaIdentity(
    "environmental.core",
    "urn:example:environmental:core",
    "1.0.0",
)


def _binding() -> SourceBinding:
    return SourceBinding(
        binding_id="vendor.erp.assets",
        mapping_version="mapping-v4",
        schema_identity=TARGET_SCHEMA,
        object_existence_ids=("asset",),
        property_ids=("asset.code",),
        coverage=SourceCoverage.COMPLETE,
    )


def _manifest() -> SourceAdapterManifest:
    return SourceAdapterManifest(
        adapter_id="vendor.erp-adapter",
        adapter_version="2.1.0",
        application_schema=ApplicationSchemaIdentity(
            "vendor.erp",
            "database-2026.08",
        ),
        target_schema=TARGET_SCHEMA,
        bindings=(_binding(),),
    )


def _source_input() -> MappedSourceInput:
    return MappedSourceInput(
        binding_id="vendor.erp.assets",
        mapping_version="mapping-v4",
        source_revision="transaction-42",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(),
    )


def _head() -> SourceInputRevision:
    return SourceInputRevision(
        "vendor.erp.assets",
        "mapping-v4",
        "transaction-43",
    )


class _VendorAdapter:
    manifest = _manifest()

    def read_snapshot(self, binding_id: str) -> MappedSourceInput:
        assert binding_id == "vendor.erp.assets"
        return _source_input()

    def observe_head(self, binding_id: str) -> SourceInputRevision:
        assert binding_id == "vendor.erp.assets"
        return _head()


def test_manifest_is_canonical_and_product_hosted_adapter_is_structural() -> None:
    manifest = _manifest()
    restored = SourceAdapterManifest.from_json(manifest.to_json())
    adapter = _VendorAdapter()

    assert restored == manifest
    assert restored.bindings[0] == SourceBinding.from_dict(_binding().to_dict())
    assert isinstance(adapter, SourceAdapter)
    inputs = tuple(
        adapter.read_snapshot(binding.binding_id) for binding in manifest.bindings
    )
    heads = tuple(
        adapter.observe_head(binding.binding_id) for binding in manifest.bindings
    )
    validate_source_adapter_outputs(
        manifest,
        source_inputs=inputs,
        observed_heads=heads,
    )


def test_manifest_rejects_cross_schema_or_duplicate_bindings() -> None:
    foreign = replace(
        _binding(),
        schema_identity=SchemaIdentity(
            "environmental.other",
            "urn:example:environmental:other",
            "1.0.0",
        ),
    )
    with pytest.raises(ValueError, match="manifest schema identity"):
        replace(_manifest(), bindings=(foreign,))
    with pytest.raises(ValueError, match="duplicate binding"):
        replace(_manifest(), bindings=(_binding(), _binding()))


@pytest.mark.parametrize(
    ("source_inputs", "heads", "code"),
    [
        ((), (_head(),), "input_binding_set_mismatch"),
        ((_source_input(),), (), "head_binding_set_mismatch"),
        (
            (replace(_source_input(), mapping_version="mapping-v5"),),
            (_head(),),
            "input_mapping_version_mismatch",
        ),
        (
            (replace(_source_input(), coverage=SourceCoverage.PARTIAL),),
            (_head(),),
            "input_coverage_mismatch",
        ),
        (
            (_source_input(),),
            (replace(_head(), mapping_version="mapping-v5"),),
            "head_mapping_version_mismatch",
        ),
    ],
)
def test_vendor_conformance_failures_are_explicit(
    source_inputs: tuple[MappedSourceInput, ...],
    heads: tuple[SourceInputRevision, ...],
    code: str,
) -> None:
    with pytest.raises(SourceAdapterContractError) as exc_info:
        validate_source_adapter_outputs(
            _manifest(),
            source_inputs=source_inputs,
            observed_heads=heads,
        )

    assert exc_info.value.code == code
