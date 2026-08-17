from __future__ import annotations

from pathlib import Path

from loushang.ai.model.domain import Model, Provider
from loushang.ai.model.registry import ModelRegistry as AiModelRegistry
from loushang.harness.model_catalog import ModelCatalog
from loushang.harness.runtime import RegistrationOwner, RegistrationScope


def test_model_catalog_reloads_only_when_project_layer_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    catalog = ModelCatalog()
    calls: list[tuple[Path | None, Path | None]] = []
    monkeypatch.setattr(
        catalog,
        "reload",
        lambda *, user_dir=None, project_dir=None: calls.append(
            (user_dir, project_dir)
        ),
    )
    user_dir = tmp_path / "user-models"
    user_dir.mkdir()
    project_dir = tmp_path / "project-models"

    assert catalog.reload_if_project_layer(
        user_dir=user_dir,
        project_dir=project_dir,
    ) is False
    assert calls == []

    project_dir.mkdir()

    assert catalog.reload_if_project_layer(
        user_dir=user_dir,
        project_dir=project_dir,
    ) is True
    assert calls == [(user_dir, project_dir)]


def test_model_catalog_registration_compatibility_baseline() -> None:
    catalog = ModelCatalog(AiModelRegistry())
    first_model = Model(
        id="shared",
        provider="vendor",
        endpoint="default",
        api="custom",
        name="First model",
    )
    replacement_model = Model(
        id="shared",
        provider="vendor",
        endpoint="default",
        api="custom",
        name="Replacement model",
    )

    assert catalog.register_model(first_model) is None
    assert catalog.register_model(replacement_model) is None
    assert len(catalog.ai_registry.list_models()) == 1
    assert catalog.ai_registry.get_model("vendor", "default", "shared").name == (
        "Replacement model"
    )

    first_provider = Provider(id="provider", name="First provider")
    replacement_provider = Provider(id="provider", name="Replacement provider")
    assert catalog.register_provider(first_provider) is None
    assert catalog.register_provider(replacement_provider) is None
    registered_provider = catalog.ai_registry.get_provider("provider")
    assert registered_provider is not None
    assert registered_provider.name == "Replacement provider"

    assert catalog.unregister_provider("missing") is None
    assert catalog.unregister_provider("provider") is None
    assert catalog.ai_registry.get_provider("provider") is None


def test_model_catalog_bound_provider_removal_preserves_the_current_winner() -> None:
    import asyncio

    baseline = Provider(id="shared", name="Baseline")
    catalog = ModelCatalog(AiModelRegistry.from_providers({"shared": baseline}))
    old_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=1,
    )
    new_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=2,
    )
    old_lease = catalog.bind_provider(
        Provider(id="shared", name="Old generation"),
        owner=old_owner,
    )
    assert old_lease.state == "active"
    new_lease = catalog.stage_provider(
        Provider(id="shared", name="New generation"),
        owner=new_owner,
    )

    current = catalog.ai_registry.get_provider("shared")
    assert current is not None
    assert current.name == "Old generation"
    scope = RegistrationScope(new_owner)
    scope.add(new_lease)
    scope.commit()
    current = catalog.ai_registry.get_provider("shared")
    assert current is not None
    assert current.name == "New generation"
    assert asyncio.run(old_lease.dispose()).state == "removed"
    current = catalog.ai_registry.get_provider("shared")
    assert current is not None
    assert current.name == "New generation"
    assert asyncio.run(new_lease.dispose()).state == "removed"
    assert catalog.ai_registry.get_provider("shared") == baseline


def test_model_catalog_staged_provider_removal_is_owner_scoped_and_reversible() -> (
    None
):
    import asyncio

    old = Provider(id="shared", name="Old generation")
    catalog = ModelCatalog(AiModelRegistry())
    old_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=1,
    )
    new_owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="models",
        runtime_id="session-1",
        generation=2,
    )
    old_lease = catalog.bind_provider(old, owner=old_owner)
    removal = catalog.stage_provider_removal("shared", owner=new_owner)

    assert catalog.ai_registry.get_provider("shared") == old
    scope = RegistrationScope(new_owner)
    scope.add(removal)
    scope.commit()
    assert catalog.ai_registry.get_provider("shared") is None

    scope.rollback_commit()
    assert catalog.ai_registry.get_provider("shared") == old
    assert asyncio.run(removal.dispose()).state == "removed"
    assert catalog.ai_registry.get_provider("shared") == old
    assert asyncio.run(old_lease.dispose()).state == "removed"
