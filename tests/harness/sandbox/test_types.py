from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.sandbox import (
    SandboxBackendStatus,
    SandboxScopeRequest,
    SandboxSettings,
)


def test_scope_request_requires_absolute_paths_and_deduplicates_roots(
    tmp_path: Path,
) -> None:
    request = SandboxScopeRequest(
        cwd=tmp_path,
        readable_roots=(tmp_path, tmp_path),
        writable_roots=(tmp_path,),
    )

    assert request.cwd == tmp_path.resolve()
    assert request.readable_roots == (tmp_path.resolve(),)
    assert request.network == "allowed"

    with pytest.raises(ValueError, match="must be absolute"):
        SandboxScopeRequest(cwd=Path("relative"))


def test_sandbox_settings_and_backend_status_validate_closed_vocabularies() -> None:
    with pytest.raises(TypeError, match="must be a bool"):
        SandboxSettings(enabled=1)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="requires a reason"):
        SandboxBackendStatus(backend_id="linux", state="unavailable")
