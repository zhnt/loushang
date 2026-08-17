from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from loushang.ai.model import load_model_registry_from_file

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/ai/check_catalog.py"
SPEC = importlib.util.spec_from_file_location("check_catalog", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
check_catalog_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_catalog_module)


def test_check_catalog_main_reports_runtime_catalog(capsys) -> None:
    registry = load_model_registry_from_file(check_catalog_module.CATALOG_PATH)

    assert check_catalog_module.main() == 0

    assert json.loads(capsys.readouterr().out) == {
        "catalog": "src/loushang/ai/model/models.json",
        "endpoints": len(registry.list_endpoints()),
        "models": len(registry.list_models()),
        "providers": len(registry.list_providers()),
    }


def test_check_catalog_rejects_duplicate_preferred_endpoints(
    monkeypatch,
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "models.json"
    catalog_path.write_text(
        json.dumps(
            {
                "providers": {
                    "custom": {
                        "endpoints": {
                                "first": {
                                    "api": "faux",
                                    "baseUrl": "https://first.example.test/v1",
                                "preferred": True,
                                "models": {
                                    "model-a": {
                                        "capabilities": {
                                            "input": ["text"],
                                            "output": ["text"],
                                        }
                                    }
                                },
                            },
                                "second": {
                                    "api": "faux",
                                    "baseUrl": "https://second.example.test/v1",
                                "preferred": True,
                                "models": {
                                    "model-a": {
                                        "capabilities": {
                                            "input": ["text"],
                                            "output": ["text"],
                                        }
                                    }
                                },
                            },
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_catalog_module, "CATALOG_PATH", catalog_path)

    assert check_catalog_module.check_catalog() == [
        "provider custom has duplicate preferred endpoints: "
        "{'model-a': ['first', 'second']}"
    ]


def test_check_catalog_main_prints_errors(monkeypatch, tmp_path: Path, capsys) -> None:
    catalog_path = tmp_path / "models.json"
    catalog_path.write_text('{"providers": {}}', encoding="utf-8")
    monkeypatch.setattr(check_catalog_module, "CATALOG_PATH", catalog_path)

    assert check_catalog_module.main() == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "ERROR catalog has no endpoints\n"
