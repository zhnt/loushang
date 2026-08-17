from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_openai_codex_live_example_uses_public_application_api() -> None:
    path = REPO_ROOT / "examples" / "auth" / "openai_codex_live_example.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("loushang")
    ]

    assert imports == ["loushang.ai"]
    assert "ai.auth.status(model)" in source
    assert "ai.auth.get_auth(model)" in source
    assert "await ai.stream(" in source
    assert "ai.auth.AuthenticationRequiredError" in source
    assert "OpenAICodexCredentialSource" not in source
    assert "CredentialSource" not in source
    assert "auth.json" not in source
    assert "access_token" not in source
    assert ".load(" not in source


def test_openai_codex_live_example_reports_authentication_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_module(
        REPO_ROOT / "examples" / "auth" / "openai_codex_live_example.py",
        "examples_auth_openai_codex_live_auth_required",
    )

    class MissingStatus:
        authenticated = False
        auth_kind = "oauth"
        provider = "openai-codex"
        source = "openai-codex"
        source_description = "Use existing Codex CLI login"
        source_recovery_hint = "Run codex login"
        experimental = True
        actions = ("external_credential",)

    async def fake_status(model):
        del model
        return MissingStatus()

    async def fake_get_auth(model):
        del model
        raise module.ai.auth.AuthenticationRequiredError(
            "Codex credential is missing.",
            details={
                "reason": "missing_credential",
                "available_actions": ["external_credential"],
            },
        )

    async def fail_if_streamed(*args, **kwargs):
        del args, kwargs
        raise AssertionError("the model must not be called without authentication")

    monkeypatch.setattr(module.ai.auth, "status", fake_status)
    monkeypatch.setattr(module.ai.auth, "get_auth", fake_get_auth)
    monkeypatch.setattr(module.ai, "stream", fail_if_streamed)

    assert asyncio.run(module.run()) is None
    output = capsys.readouterr().out
    assert '"authenticated": false' in output
    assert "Authentication required." in output
    assert "Reason: missing_credential" in output
    assert "Actions:\n- external_credential" in output
    assert "Hint:\nRun codex login" in output


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (
            "api_key_example.py",
            {
                "calls": 1,
                "authenticated": True,
                "authType": "ApiKeyAuth",
            },
        ),
        (
            "oauth_status_login_example.py",
            {
                "beforeActions": ["login"],
                "browserOpenedByApplication": True,
                "loginProvider": "example-oauth",
                "authenticated": True,
                "requestAuthorized": True,
            },
        ),
        (
            "external_credential_source_example.py",
            {
                "authenticated": True,
                "experimental": True,
                "sourceDescription": "Use existing Codex CLI login",
                "recoveryHint": "Run codex login",
                "requestAuthorized": True,
                "accountHeaderResolved": True,
            },
        ),
    ],
)
def test_auth_example_runs(script: str, expected: dict[str, object]) -> None:
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "auth" / script)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == expected
