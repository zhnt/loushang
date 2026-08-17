from __future__ import annotations

import json
import os
import tarfile
import threading
import time
import zipfile
from pathlib import Path


def _write_tar_archive(path: Path, *, member_name: str, payload: bytes) -> None:
    import io

    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(payload))


def test_downloading_external_tool_resolver_prefers_existing_tool() -> None:
    import asyncio

    from loushang.harness.tools.workspace import DownloadingExternalToolResolver

    class BaseResolver:
        def resolve_tool(self, name: str) -> str | None:
            return "/usr/bin/fd" if name == "fd" else None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def download_tool(self, name: str) -> str | None:
            self.calls.append(name)
            return "/downloaded/fd"

    downloader = Downloader()
    resolver = DownloadingExternalToolResolver(
        base_resolver=BaseResolver(),
        downloader=downloader,
        allow_download=True,
    )

    assert asyncio.run(resolver.resolve_tool("fd")) == "/usr/bin/fd"
    assert downloader.calls == []


def test_downloading_external_tool_resolver_requires_explicit_download_enable() -> None:
    import asyncio

    from loushang.harness.tools.workspace import DownloadingExternalToolResolver

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str:
            self.calls.append(name)
            return "/downloaded/rg"

    downloader = Downloader()
    resolver = DownloadingExternalToolResolver(
        base_resolver=MissingResolver(),
        downloader=downloader,
    )

    assert asyncio.run(resolver.resolve_tool("rg")) is None
    assert downloader.calls == []


def test_downloading_external_tool_resolver_downloads_and_caches_when_enabled() -> None:
    import asyncio

    from loushang.harness.tools.workspace import DownloadingExternalToolResolver

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def download_tool(self, name: str) -> str | None:
            self.calls.append(name)
            return "/downloaded/fd" if name == "fd" else None

    downloader = Downloader()
    resolver = DownloadingExternalToolResolver(
        base_resolver=MissingResolver(),
        downloader=downloader,
        allow_download=True,
    )

    assert asyncio.run(resolver.resolve_tool("fd")) == "/downloaded/fd"
    assert asyncio.run(resolver.resolve_tool("fd")) == "/downloaded/fd"
    assert downloader.calls == ["fd"]


def test_downloading_external_tool_resolver_treats_download_failure_as_unavailable() -> (
    None
):
    import asyncio

    from loushang.harness.tools.workspace import DownloadingExternalToolResolver

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class FailingDownloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str:
            self.calls.append(name)
            raise RuntimeError("network unavailable")

    downloader = FailingDownloader()
    resolver = DownloadingExternalToolResolver(
        base_resolver=MissingResolver(),
        downloader=downloader,
        allow_download=True,
    )

    assert asyncio.run(resolver.resolve_tool("rg")) is None
    assert downloader.calls == ["rg"]


def test_ensure_external_tool_uses_downloader_only_when_enabled() -> None:
    import asyncio

    from loushang.harness.tools.workspace import ensure_external_tool

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class Downloader:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def download_tool(self, name: str) -> str:
            self.calls.append(name)
            return "/downloaded/rg"

    downloader = Downloader()

    without_download = asyncio.run(
        ensure_external_tool("rg", resolver=MissingResolver(), downloader=downloader)
    )
    with_download = asyncio.run(
        ensure_external_tool(
            "rg", resolver=MissingResolver(), downloader=downloader, allow_download=True
        )
    )

    assert without_download is None
    assert with_download == "/downloaded/rg"
    assert downloader.calls == ["rg"]


def test_ensure_external_tool_uses_builtin_downloader_when_download_enabled(
    monkeypatch,
) -> None:
    import asyncio

    import loushang.harness.tools.workspace.external_tools as external_tools

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    class BuiltinDownloader:
        def __init__(self) -> None:
            created.append(self)

        def download_tool(self, name: str) -> str | None:
            calls.append(name)
            return "/managed/fd" if name == "fd" else None

    created: list[BuiltinDownloader] = []
    calls: list[str] = []
    monkeypatch.setattr(
        external_tools, "GitHubReleaseExternalToolDownloader", BuiltinDownloader
    )

    result = asyncio.run(
        external_tools.ensure_external_tool(
            "fd",
            resolver=MissingResolver(),
            allow_download=True,
        )
    )

    assert result == "/managed/fd"
    assert len(created) == 1
    assert calls == ["fd"]


def test_local_external_tool_resolver_prefers_managed_binary(tmp_path) -> None:
    from loushang.harness.tools.workspace import LocalExternalToolResolver

    managed_fd = tmp_path / "fd"
    managed_fd.write_text("#!/bin/sh\n", encoding="utf-8")
    managed_fd.chmod(0o755)

    resolver = LocalExternalToolResolver(tools_dir=tmp_path)

    assert resolver.resolve_tool("fd") == str(managed_fd)


def test_github_release_downloader_downloads_extracts_and_caches_tarball(
    tmp_path,
) -> None:
    from loushang.harness.tools.workspace import (
        GitHubReleaseExternalToolDownloader,
        get_managed_external_tool_install,
    )

    archive_path = tmp_path / "fd-release.tar.gz"
    asset_name = "fd-v1.2.3-x86_64-unknown-linux-gnu.tar.gz"
    _write_tar_archive(
        archive_path,
        member_name="fd-v1.2.3-x86_64-unknown-linux-gnu/fd",
        payload=b"fd-binary",
    )

    class Transport:
        def __init__(self) -> None:
            self.latest_release_repos: list[str] = []
            self.downloads: list[tuple[str, Path]] = []

        def get_latest_release(
            self, repo: str, *, user_agent: str, timeout_seconds: float
        ):
            del user_agent, timeout_seconds
            self.latest_release_repos.append(repo)
            return {"tag_name": "v1.2.3"}

        def download_file(
            self, url: str, destination: Path, *, timeout_seconds: float
        ) -> None:
            del timeout_seconds
            self.downloads.append((url, destination))
            destination.write_bytes(archive_path.read_bytes())

    transport = Transport()
    tools_dir = tmp_path / "bin"
    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tools_dir,
        transport=transport,
        platform_name="linux",
        architecture="x86_64",
    )

    installed_path = downloader.download_tool("fd")

    assert installed_path == str(tools_dir / "fd")
    assert (tools_dir / "fd").read_bytes() == b"fd-binary"
    assert transport.latest_release_repos == ["sharkdp/fd"]
    assert transport.downloads == [
        (
            f"https://github.com/sharkdp/fd/releases/download/v1.2.3/{asset_name}",
            tools_dir / f".{asset_name}.download",
        )
    ]
    assert not (tools_dir / asset_name).exists()
    assert not list(tools_dir.glob("extract_tmp_*"))
    metadata = json.loads((tools_dir / "fd.metadata.json").read_text(encoding="utf-8"))
    assert metadata == {
        "asset_name": asset_name,
        "binary_path": str(tools_dir / "fd"),
        "name": "fd",
        "repo": "sharkdp/fd",
        "version": "1.2.3",
    }
    install = get_managed_external_tool_install("fd", tools_dir=tools_dir)
    assert install is not None
    assert install.name == "fd"
    assert install.repo == "sharkdp/fd"
    assert install.version == "1.2.3"
    assert install.asset_name == asset_name
    assert install.binary_path == str(tools_dir / "fd")


def test_github_release_downloader_extracts_windows_zip_binary(tmp_path) -> None:
    from loushang.harness.tools.workspace import GitHubReleaseExternalToolDownloader

    asset_name = "ripgrep-14.0.0-x86_64-pc-windows-msvc.zip"
    archive_path = tmp_path / asset_name
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("ripgrep-14.0.0-x86_64-pc-windows-msvc/rg.exe", b"rg-binary")

    class Transport:
        def get_latest_release(
            self, repo: str, *, user_agent: str, timeout_seconds: float
        ):
            del repo, user_agent, timeout_seconds
            return {"tag_name": "14.0.0"}

        def download_file(
            self, url: str, destination: Path, *, timeout_seconds: float
        ) -> None:
            del url, timeout_seconds
            destination.write_bytes(archive_path.read_bytes())

    tools_dir = tmp_path / "bin"
    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tools_dir,
        transport=Transport(),
        platform_name="win32",
        architecture="x64",
    )

    installed_path = downloader.download_tool("rg")

    assert installed_path == str(tools_dir / "rg.exe")
    assert (tools_dir / "rg.exe").read_bytes() == b"rg-binary"


def test_github_release_downloader_respects_offline_mode(tmp_path, monkeypatch) -> None:
    from loushang.harness.tools.workspace import GitHubReleaseExternalToolDownloader

    class FailingTransport:
        def get_latest_release(
            self, repo: str, *, user_agent: str, timeout_seconds: float
        ):
            raise AssertionError("network should not be used")

        def download_file(
            self, url: str, destination: Path, *, timeout_seconds: float
        ) -> None:
            raise AssertionError("network should not be used")

    monkeypatch.setenv("LOUSHANG_OFFLINE", "1")
    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tmp_path / "bin",
        transport=FailingTransport(),
        platform_name="linux",
        architecture="x86_64",
    )

    assert downloader.download_tool("rg") is None


def test_github_release_downloader_cleans_partial_install_after_download_failure(
    tmp_path,
) -> None:
    import pytest

    from loushang.harness.tools.workspace import GitHubReleaseExternalToolDownloader

    class FailingTransport:
        def __init__(self) -> None:
            self.destinations: list[Path] = []

        def get_latest_release(
            self, repo: str, *, user_agent: str, timeout_seconds: float
        ):
            del repo, user_agent, timeout_seconds
            return {"tag_name": "v1.2.3"}

        def download_file(
            self, url: str, destination: Path, *, timeout_seconds: float
        ) -> None:
            del url, timeout_seconds
            self.destinations.append(destination)
            destination.write_bytes(b"partial")
            raise RuntimeError("network dropped")

    tools_dir = tmp_path / "bin"
    transport = FailingTransport()
    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tools_dir,
        transport=transport,
        platform_name="linux",
        architecture="x86_64",
    )

    with pytest.raises(RuntimeError, match="network dropped"):
        downloader.download_tool("fd")

    assert transport.destinations == [
        tools_dir / ".fd-v1.2.3-x86_64-unknown-linux-gnu.tar.gz.download"
    ]
    assert not (tools_dir / "fd").exists()
    assert not list(tools_dir.glob("*.download"))
    assert not list(tools_dir.glob("*.lock"))
    assert not list(tools_dir.glob(".*.lock"))
    assert not list(tools_dir.glob("extract_tmp_*"))
    assert not list(tools_dir.glob("*.metadata.json"))


def test_github_release_downloader_serializes_concurrent_installs(tmp_path) -> None:
    from loushang.harness.tools.workspace import GitHubReleaseExternalToolDownloader

    archive_path = tmp_path / "fd-release.tar.gz"
    _write_tar_archive(
        archive_path,
        member_name="fd-v1.2.3-x86_64-unknown-linux-gnu/fd",
        payload=b"fd-binary",
    )

    class SlowTransport:
        def __init__(self) -> None:
            self.download_count = 0
            self.first_download_started = threading.Event()
            self.lock = threading.Lock()

        def get_latest_release(
            self, repo: str, *, user_agent: str, timeout_seconds: float
        ):
            del repo, user_agent, timeout_seconds
            return {"tag_name": "v1.2.3"}

        def download_file(
            self, url: str, destination: Path, *, timeout_seconds: float
        ) -> None:
            del url, timeout_seconds
            with self.lock:
                self.download_count += 1
                current = self.download_count
            if current == 1:
                self.first_download_started.set()
                time.sleep(0.1)
            destination.write_bytes(archive_path.read_bytes())

    transport = SlowTransport()
    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tmp_path / "bin",
        transport=transport,
        platform_name="linux",
        architecture="x86_64",
    )
    results: list[str | None] = []

    first = threading.Thread(
        target=lambda: results.append(downloader.download_tool("fd"))
    )
    second = threading.Thread(
        target=lambda: results.append(downloader.download_tool("fd"))
    )

    first.start()
    assert transport.first_download_started.wait(timeout=1)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert sorted(results) == [
        str(tmp_path / "bin" / "fd"),
        str(tmp_path / "bin" / "fd"),
    ]
    assert transport.download_count == 1


def test_github_release_downloader_recovers_from_stale_install_lock(tmp_path) -> None:
    from loushang.harness.tools.workspace import GitHubReleaseExternalToolDownloader

    archive_path = tmp_path / "fd-release.tar.gz"
    _write_tar_archive(
        archive_path,
        member_name="fd-v1.2.3-x86_64-unknown-linux-gnu/fd",
        payload=b"fd-binary",
    )

    class Transport:
        def __init__(self) -> None:
            self.download_count = 0

        def get_latest_release(
            self, repo: str, *, user_agent: str, timeout_seconds: float
        ):
            del repo, user_agent, timeout_seconds
            return {"tag_name": "v1.2.3"}

        def download_file(
            self, url: str, destination: Path, *, timeout_seconds: float
        ) -> None:
            del url, timeout_seconds
            self.download_count += 1
            destination.write_bytes(archive_path.read_bytes())

    tools_dir = tmp_path / "bin"
    tools_dir.mkdir()
    stale_lock = tools_dir / ".fd.install.lock"
    stale_lock.write_text("dead", encoding="utf-8")
    old_time = time.time() - 60
    stale_lock.touch()
    os.utime(stale_lock, (old_time, old_time))

    transport = Transport()
    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tools_dir,
        transport=transport,
        platform_name="linux",
        architecture="x86_64",
        install_lock_timeout_seconds=0.5,
        install_lock_stale_seconds=1,
    )

    assert downloader.download_tool("fd") == str(tools_dir / "fd")
    assert transport.download_count == 1
    assert not stale_lock.exists()


def test_github_release_downloader_times_out_on_fresh_install_lock(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import GitHubReleaseExternalToolDownloader

    tools_dir = tmp_path / "bin"
    tools_dir.mkdir()
    (tools_dir / ".fd.install.lock").write_text("active", encoding="utf-8")

    downloader = GitHubReleaseExternalToolDownloader(
        tools_dir=tools_dir,
        platform_name="linux",
        architecture="x86_64",
        install_lock_timeout_seconds=0.02,
        install_lock_stale_seconds=60,
    )

    with pytest.raises(TimeoutError, match="install lock"):
        downloader.download_tool("fd")
