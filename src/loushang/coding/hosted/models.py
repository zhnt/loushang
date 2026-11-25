"""Resolve model choices for a Coding Workspace before a Session exists."""

from pathlib import Path

from loushang.ai.model import (
    Model,
    ModelSelection,
)
from loushang.coding.composition.bootstrap import BootstrapServices, create_services
from loushang.coding.control.settings_store import open_coding_workspace_settings
from loushang.foundation.reasoning import ThinkingLevel
from loushang.harness.session.model_resolution import resolve_session_model


def create_hosted_services(workspace: Path | None) -> BootstrapServices:
    return create_services(settings_manager=open_coding_workspace_settings(workspace))


def preview_workspace_models(
    workspace: Path | None, explicit: Model | ModelSelection | None,
) -> tuple[Model | None, list[Model], ThinkingLevel | None]:
    services = create_hosted_services(workspace)
    if workspace is not None:
        load_workspace_models(services, workspace)
    catalog = services.model_registry
    settings = services.settings_manager.get_settings()
    active = resolve_session_model(
        explicit, default_selection=settings.default_model,
        build_model=catalog.build_model,
    )
    details = catalog.ai_registry.list_models()
    if active is not None:
        details.append(active)
    return active, details, settings.thinking_level


def load_workspace_models(services: BootstrapServices, workspace: Path) -> None:
    inputs = services.resource_loader.preview_catalog_input_receipt(workspace)
    roots_with_context = {fact.root for fact in inputs.context_file_facts if fact.status == "file"}
    roots = (*inputs.user_resource_roots, *inputs.project_context_roots)
    project_root = next((root for root in reversed(roots) if root in roots_with_context), workspace)
    services.model_registry.reload_if_project_layer(
        user_dir=Path.home() / ".loushang" / "models",
        project_dir=project_root / ".loushang" / "models",
    )
