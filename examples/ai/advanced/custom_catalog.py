"""Load a custom model file with a first-class upstream model binding.

This advanced example is offline. It writes a tiny model file, loads it,
and inspects the provider request binding without calling any API.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from loushang.ai.model import load_model_registry_from_file
from loushang.ai.provider import resolve_request_for_model

CUSTOM_CATALOG: dict[str, Any] = {
    "providers": {
        "custom-provider": {
            "endpoints": {
                "openai-completions": {
                    "api": "openai-completions",
                    "baseUrl": "https://api.example.invalid/v1",
                    "auth": {"kind": "none"},
                    "adapter": {
                        "maxOutputTokensField": "max_completion_tokens",
                        "reasoningFormat": "openai",
                    },
                    "models": {
                        "public-model": {
                            "upstreamId": "vendor/public-model:latest",
                            "capabilities": {
                                "input": ["text"],
                                "output": ["text"],
                            },
                        }
                    },
                }
            }
        }
    },
}


def inspect_custom_catalog() -> dict[str, object]:
    with TemporaryDirectory() as directory:
        path = Path(directory) / "models.json"
        path.write_text(json.dumps(CUSTOM_CATALOG), encoding="utf-8")

        registry = load_model_registry_from_file(path)
        model = registry.get_model(
            "custom-provider",
            "openai-completions",
            "public-model",
        )
        resolved = resolve_request_for_model(model, env={})

    return {
        "model": f"{model.provider_id}:{model.endpoint_id}:{model.id}",
        "upstreamId": model.upstream_id,
        "requestModelUpstreamId": resolved.model.upstream_id,
        "baseUrl": resolved.base_url,
    }


def main() -> None:
    print(json.dumps(inspect_custom_catalog(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
