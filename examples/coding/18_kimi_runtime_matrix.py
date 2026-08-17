from __future__ import annotations

import json
import sys
from pathlib import Path

from loushang.ai.model import (
    get_default_model_registry,
    load_model_registry_from_directory,
    load_model_registry_from_file,
)
from loushang.ai.model.domain import Endpoint
from loushang.ai.model.registry import ModelRegistry

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from _support import (
    ENV_EXAMPLES_ARTIFACT_ROOT,
    _resolve_model_catalog,
    _resolve_model_registry,
)

ERROR_CODE_MAP = {
    "401": "auth invalid / key missing",
    "403": "forbidden / key scope mismatch",
    "404": "endpoint path mismatch",
    "429": "quota or rate-limit",
    "500": "provider internal error",
    "502": "provider gateway",
    "503": "provider unavailable",
}


def print_event(name: str, payload: dict[str, object]) -> None:
    print(f"{name}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _provider_default_base_url(endpoint: Endpoint) -> str:
    return getattr(endpoint, "base_url", None) or getattr(endpoint, "baseUrl", "") or ""


def _sorted_endpoints(catalog_path: Path | None) -> tuple[ModelRegistry, list[tuple[str, Endpoint]]]:
    if catalog_path is not None and catalog_path.exists():
        try:
            loader = (
                load_model_registry_from_directory
                if catalog_path.is_dir()
                else load_model_registry_from_file
            )
            registry = loader(catalog_path)
        except Exception:
            custom = _resolve_model_registry()
            registry = custom if custom is not None else get_default_model_registry()
    else:
        custom = _resolve_model_registry()
        registry = custom if custom is not None else get_default_model_registry()

    endpoints: list[tuple[str, Endpoint]] = []
    for provider in registry.list_providers():
        for endpoint in registry.list_endpoints(provider=provider.id):
            endpoints.append((provider.id, endpoint))
    endpoints.sort(key=lambda item: (item[0], item[1].id))
    return registry, endpoints


def main() -> None:
    print("=== Runtime Matrix Probe ===")
    print_event("message.start", {"step": "resolve_catalog"})

    catalog_path = _resolve_model_catalog()
    if catalog_path is None:
        print(f"resolved catalog: <unset>; default from {ENV_EXAMPLES_ARTIFACT_ROOT}")
    else:
        print(f"resolved catalog: {catalog_path}")

    _, entries = _sorted_endpoints(catalog_path)
    print(f"provider_count={len({provider for provider, _ in entries})}")
    print(f"endpoint_count={len(entries)}")

    print("=== Mapping Matrix ===")
    for provider_id, endpoint in entries:
        endpoint_id = endpoint.id
        base_url = _provider_default_base_url(endpoint)
        api = getattr(endpoint, "api", "<n/a>")
        print(f"- endpoint[{provider_id}:{endpoint_id}] api={api} base_url={base_url}")

        model_ids = sorted(getattr(endpoint, "models", {}).keys())
        print_event(
            "model.start",
            {"provider": provider_id, "endpoint": endpoint_id, "model_count": len(model_ids)},
        )
        for model_id in model_ids:
            print(f"  - model: provider={provider_id} endpoint={endpoint_id} model={model_id}")
        if not model_ids:
            print("  - model: <none>")
        print_event("model.end", {"provider": provider_id, "endpoint": endpoint_id, "status": "ok"})
        print()

    print("=== Error Code Mapping ===")
    for code, meaning in ERROR_CODE_MAP.items():
        print(f"- {code}: {meaning}")

    print_event("tool.start", {"name": "runtime-matrix", "status": "offline"})
    print_event("tool.end", {"name": "runtime-matrix", "status": "ok", "rows": len(entries)})
    print_event("message.end", {"result": "pass", "resolved_endpoints": len(entries)})

    print("=== offline expected sample ===")
    print("resolved catalog: <unset>; using built-in catalog")
    print("event: message.start")
    print("- endpoint[kimi-code:kimi-code-openai] api=openai-completions base_url=https://api.kimi.com/coding/v1")
    print("- endpoint[kimi-code:kimi-code-anthropic] api=anthropic-messages base_url=https://api.kimi.com/coding")
    print("message.end result=pass")


if __name__ == "__main__":
    main()
