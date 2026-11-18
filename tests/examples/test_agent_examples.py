from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_kimi_agent_example_builds_public_model() -> None:
    module = _load_module(
        Path("examples/agent/kimi_agent.py"),
        "examples_agent_kimi_agent",
    )

    model = module._build_model()

    assert model.provider_id == "moonshot"
    assert model.endpoint_id == "openai-completions"
    assert model.id == "kimi-k3.1-pro"


def test_kimi_agent_openai_example_builds_public_model() -> None:
    module = _load_module(
        Path("examples/agent/kimi_agent_openai.py"),
        "examples_agent_kimi_agent_openai",
    )

    model = module._build_model()

    assert model.provider_id == "moonshot"
    assert model.endpoint_id == "openai-completions"
    assert model.id == "kimi-k3.1-pro"
