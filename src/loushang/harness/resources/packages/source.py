from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urldefrag, urlparse


@dataclass(frozen=True)
class PackageSourceConfig:
    source: str
    extensions: tuple[str, ...] | None = None
    skills: tuple[str, ...] | None = None
    prompts: tuple[str, ...] | None = None
    themes: tuple[str, ...] | None = None

    @property
    def filtered(self) -> bool:
        return any(
            value is not None
            for value in (self.extensions, self.skills, self.prompts, self.themes)
        )


@dataclass(frozen=True)
class PackageSourceIdentity:
    source: str
    source_type: str
    identity_key: str
    repo: str | None = None
    host: str | None = None
    path: str | None = None
    ref: str | None = None
    pinned: bool = False

    @classmethod
    def parse(cls, source: str | Path) -> "PackageSourceIdentity":
        text = str(source)
        parsed_python = _parse_python_source(text)
        if parsed_python is not None:
            requirement, name, ref, pinned = parsed_python
            return cls(
                source=text,
                source_type="python",
                identity_key=f"python:{name}#{requirement}"
                if pinned
                else f"python:{name}",
                host="pypi",
                path=name,
                ref=ref,
                pinned=pinned,
            )
        parsed_git = _parse_git_source(text)
        if parsed_git is not None:
            repo, host, normalized_path, ref = parsed_git
            key_base = (
                f"git:{host}/{normalized_path}" if host else f"git:{normalized_path}"
            )
            return cls(
                source=text,
                source_type="git",
                identity_key=f"{key_base}#{ref}" if ref else key_base,
                repo=repo,
                host=host,
                path=normalized_path,
                ref=ref,
                pinned=bool(ref),
            )
        without_fragment, fragment = urldefrag(text)
        normalized = without_fragment.removeprefix("git+")
        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https", "ssh", "git", "file"} and (
            parsed.netloc or parsed.scheme == "file"
        ):
            host = parsed.hostname or parsed.netloc
            path = parsed.path.strip("/")
            normalized_path = path.removesuffix(".git")
            repo = normalized
            key_base = (
                f"git:{host}/{normalized_path}"
                if host
                else f"git:{Path(parsed.path).as_posix().removesuffix('.git')}"
            )
            ref = fragment or None
            return cls(
                source=text,
                source_type="git",
                identity_key=f"{key_base}#{ref}" if ref else key_base,
                repo=repo,
                host=host,
                path=normalized_path,
                ref=ref,
                pinned=bool(ref),
            )
        local = Path(text).expanduser()
        return cls(
            source=text,
            source_type="local",
            identity_key=f"local:{local.resolve()}",
            path=str(local),
        )


def package_source_from_raw(raw_source: object) -> PackageSourceConfig | None:
    if isinstance(raw_source, PackageSourceConfig):
        return raw_source
    if isinstance(raw_source, str):
        return PackageSourceConfig(source=raw_source)
    if not isinstance(raw_source, Mapping):
        return None
    source = raw_source.get("source")
    if not isinstance(source, str) or not source:
        return None
    return PackageSourceConfig(
        source=source,
        extensions=_string_tuple_or_none(raw_source.get("extensions")),
        skills=_string_tuple_or_none(raw_source.get("skills")),
        prompts=_string_tuple_or_none(raw_source.get("prompts")),
        themes=_string_tuple_or_none(raw_source.get("themes")),
    )


def _string_tuple_or_none(value: object) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list | tuple):
        return None
    return tuple(item for item in value if isinstance(item, str))


def is_remote_package_source(source: str | Path) -> bool:
    text = str(source)
    if is_python_package_source(text):
        return True
    if _parse_git_source(text) is not None:
        return True
    parsed = urlparse(text)
    return parsed.scheme in {
        "http",
        "https",
        "git+https",
        "git+ssh",
        "git+file",
        "ssh",
        "file",
    }


def is_python_package_source(source: str | Path) -> bool:
    return _parse_python_source(str(source)) is not None


def remote_package_name(source: str) -> str:
    parsed_python = _parse_python_source(source)
    if parsed_python is not None:
        _, name, _, _ = parsed_python
        return name
    parsed_git = _parse_git_source(source)
    if parsed_git is not None:
        _, _, path, _ = parsed_git
        return Path(path).name or "remote-package"
    parsed = urlparse(source)
    candidate = Path(parsed.path.rstrip("/")).name or parsed.netloc
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    return candidate or "remote-package"


def clone_source_and_ref(source: str) -> tuple[str, str | None]:
    parsed_git = _parse_git_source(source)
    if parsed_git is not None:
        repo, _, _, ref = parsed_git
        return repo, ref
    without_fragment, fragment = urldefrag(source)
    if without_fragment.startswith("git+"):
        without_fragment = without_fragment[len("git+") :]
    return without_fragment, fragment or None


def python_package_requirement(source: str | Path) -> str | None:
    parsed = _parse_python_source(str(source))
    return parsed[0] if parsed is not None else None


def python_package_name(source: str | Path) -> str | None:
    parsed = _parse_python_source(str(source))
    return parsed[1] if parsed is not None else None


def package_source_match_key(source: str | Path) -> str:
    identity = PackageSourceIdentity.parse(source)
    if identity.source_type == "python" and identity.path:
        return f"python:{identity.path}"
    if identity.source_type == "git" and identity.host and identity.path:
        return f"git:{identity.host}/{identity.path}"
    return identity.identity_key


def _parse_git_source(source: str) -> tuple[str, str, str, str | None] | None:
    text = source.strip()
    if not text:
        return None
    if text.startswith("git:") and not text.startswith("git://"):
        remainder = text[len("git:") :].strip()
        split = _split_repo_at_ref(remainder)
        parsed = _parse_host_path(split[0])
        if parsed is None:
            return None
        host, path = parsed
        return f"https://{host}/{path}", host, _normalize_repo_path(path), split[1]
    scp_match = re.match(r"^git@([^:]+):(.+)$", text)
    if scp_match:
        host = scp_match.group(1)
        split = _split_repo_at_ref(scp_match.group(2))
        path = _normalize_repo_path(split[0])
        if not path:
            return None
        return f"git@{host}:{split[0]}", host, path, split[1]
    if re.match(r"^(?:https?|ssh|git)://", text):
        split = _split_url_at_ref(text)
        parsed_url = urlparse(split[0])
        if not parsed_url.hostname or not parsed_url.path.strip("/"):
            return None
        path = _normalize_repo_path(parsed_url.path.strip("/"))
        if path.count("/") < 1:
            return None
        return split[0], parsed_url.hostname, path, split[1]
    return None


def _parse_python_source(source: str) -> tuple[str, str, str | None, bool] | None:
    text = source.strip()
    if not text.startswith("pypi:"):
        return None
    requirement = text[len("pypi:") :].strip()
    if not requirement:
        return None
    match = re.match(r"^([A-Za-z0-9_.-]+)", requirement)
    if match is None:
        return None
    name = _normalize_python_name(match.group(1))
    ref = _exact_python_version_ref(requirement)
    return requirement, name, ref, ref is not None


def _normalize_python_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _exact_python_version_ref(requirement: str) -> str | None:
    match = re.search(r"(?<![<>=!~])==\s*([^,;\s]+)", requirement)
    if match is None:
        match = re.search(r"===\s*([^,;\s]+)", requirement)
    if match is None:
        return None
    version = match.group(1).strip()
    if not version or "*" in version:
        return None
    return f"=={version}"


def _parse_host_path(value: str) -> tuple[str, str] | None:
    if "/" not in value:
        return None
    host, path = value.split("/", 1)
    path = _normalize_repo_path(path)
    if not host or not path or path.count("/") < 1:
        return None
    return host, path


def _split_repo_at_ref(value: str) -> tuple[str, str | None]:
    repo, separator, ref = value.rpartition("@")
    if not separator or not repo or not ref:
        return value, None
    return repo, ref


def _split_url_at_ref(value: str) -> tuple[str, str | None]:
    without_fragment, fragment = urldefrag(value)
    if fragment:
        return without_fragment, fragment
    parsed = urlparse(without_fragment)
    path = parsed.path.lstrip("/")
    repo_path, ref = _split_repo_at_ref(path)
    if ref is None:
        return without_fragment, None
    rebuilt = parsed._replace(path=f"/{repo_path}").geturl()
    return rebuilt, ref


def _normalize_repo_path(path: str) -> str:
    return path.strip("/").removesuffix(".git")
