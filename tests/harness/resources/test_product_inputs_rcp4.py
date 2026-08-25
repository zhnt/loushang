from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.harness.resource_catalog import product_inputs as product_inputs_module
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
    InitialResourceCatalogProductSelection,
    ProductEmbeddedResourceCollectionSpec,
    ProductNativeResourceRootSpec,
)
from loushang.harness.resources.types import ResourceBundle


def test_embedded_product_spec_defensively_copies_the_selected_bytes() -> None:
    files = {"skills/builtin/SKILL.md": b"original"}

    spec = ProductEmbeddedResourceCollectionSpec(
        collection_id="builtin-resources",
        embedded_revision="v1",
        files=files,
    )
    files["skills/builtin/SKILL.md"] = b"changed"

    assert spec.files == {"skills/builtin/SKILL.md": b"original"}
    with pytest.raises(TypeError):
        spec.files["skills/other/SKILL.md"] = b"forbidden"  # type: ignore[index]


def test_product_selection_rejects_duplicate_native_and_embedded_identities(
    tmp_path: Path,
) -> None:
    root = ProductNativeResourceRootSpec(
        handle_id="project-resources",
        root=tmp_path,
        source_class="project_local",
        root_kind="standard",
    )
    embedded = ProductEmbeddedResourceCollectionSpec(
        collection_id="builtin-resources",
        embedded_revision="v1",
        files={},
    )

    with pytest.raises(ValueError, match="native root ids must not repeat"):
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            native_roots=(root, root),
        )
    with pytest.raises(ValueError, match="embedded collection ids must not repeat"):
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(embedded, embedded),
        )


def test_product_adapter_reuse_mints_independent_session_bootstraps(
    tmp_path: Path,
) -> None:
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-resources",
                    embedded_revision="v1",
                    files={
                        "skills/builtin/SKILL.md": (
                            b"---\nname: builtin\ndescription: Built in\n---\nUse it.\n"
                        )
                    },
                ),
            ),
        ),
        clock=lambda: 10,
    )
    bundle = ResourceBundle(cwd=tmp_path)

    first = adapter.construct_session(
        product_id="product",
        session_id="first",
        base_resource_bundle=bundle,
        construct=lambda bootstrap: bootstrap,
    )
    second = adapter.construct_session(
        product_id="product",
        session_id="second",
        base_resource_bundle=bundle,
        construct=lambda bootstrap: bootstrap,
    )

    assert first is not second
    assert first.scope_id == "session:first"
    assert second.scope_id == "session:second"
    first.close_unprepared()
    second.close_unprepared()
    assert first.state == second.state == "disposed"


def test_product_adapter_closes_untransferred_inputs_when_construction_fails(
    tmp_path: Path,
) -> None:
    captured = []
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-resources",
                    embedded_revision="v1",
                    files={},
                ),
            ),
        ),
        clock=lambda: 10,
    )

    def fail(bootstrap):  # type: ignore[no-untyped-def]
        captured.append(bootstrap)
        raise RuntimeError("Session construction failed")

    with pytest.raises(RuntimeError, match="Session construction failed"):
        adapter.construct_session(
            product_id="product",
            session_id="failed",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=fail,
        )

    assert len(captured) == 1
    assert captured[0].state == "disposed"


def test_product_adapter_releases_partial_embedded_mint_on_later_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    minted = []
    real_mint = product_inputs_module.mint_embedded_resource_collection_handle

    def fail_second_mint(**kwargs):  # type: ignore[no-untyped-def]
        if minted:
            raise RuntimeError("second embedded collection failed")
        handle = real_mint(**kwargs)
        minted.append(handle)
        return handle

    monkeypatch.setattr(
        product_inputs_module,
        "mint_embedded_resource_collection_handle",
        fail_second_mint,
    )
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-a",
                    embedded_revision="v1",
                    files={},
                ),
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-b",
                    embedded_revision="v1",
                    files={},
                ),
            ),
        ),
        clock=lambda: 10,
    )

    with pytest.raises(RuntimeError, match="second embedded collection failed"):
        adapter.construct_session(
            product_id="product",
            session_id="failed",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=lambda bootstrap: bootstrap,
        )

    assert len(minted) == 1
    assert minted[0].closed is True


def test_product_adapter_rejects_async_construction_and_closes_its_coroutine(
    tmp_path: Path,
) -> None:
    captured = []
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            native_roots=(
                ProductNativeResourceRootSpec(
                    handle_id="project-resources",
                    root=tmp_path,
                    source_class="project_local",
                    root_kind="standard",
                ),
            ),
        ),
        clock=lambda: 10,
    )

    async def pending_session() -> object:
        await asyncio.sleep(0)
        return object()

    def construct(bootstrap):  # type: ignore[no-untyped-def]
        captured.append(bootstrap)
        return pending_session()

    with pytest.raises(TypeError, match="must be synchronous"):
        adapter.construct_session(
            product_id="product",
            session_id="async",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=construct,
        )

    assert len(captured) == 1
    assert captured[0].state == "disposed"
