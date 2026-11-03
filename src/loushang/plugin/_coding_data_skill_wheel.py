"""Deterministic author artifacts for Coding's gated external data profiles.

This is an offline authoring recipe. Coding Product admission remains the
authority for a wheel at installation time.
"""

from __future__ import annotations

import csv
import io
import re
import stat
import zipfile
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.theme_document import parse_theme_document_v1
from loushang.plugin._authoring import ResourceItemSpec, resource
from loushang.plugin._package import package

_SIMPLE_ID = re.compile(r"[a-z][a-z0-9]*\Z")
_SKILL_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_PROMPT_NAME = _SKILL_NAME
_THEME_NAME = _SKILL_NAME
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_MAX_TREE_BYTES = 1024 * 1024


def build_coding_data_skill_wheel(
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    skill_name: str,
    skill_document: bytes,
) -> bytes:
    """Build one installable, data-only Skill wheel without Product authority.

    This profile intentionally excludes actions, code, dependencies, and every
    Resource kind other than Skill. Product rechecks the final wheel and scope.
    """

    if not isinstance(plugin_id, str) or _SIMPLE_ID.fullmatch(plugin_id) is None:
        raise ValueError("Coding data Skill Plugin ID must be simple lowercase ASCII")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError("Coding data Skill version must be numeric")
    if not isinstance(skill_name, str) or _SKILL_NAME.fullmatch(skill_name) is None:
        raise ValueError("Coding data Skill name must be lowercase ASCII")
    if len(skill_name) > 255:
        raise ValueError("Coding data Skill name exceeds wheel path component budget")
    if len(f"{plugin_id}-{version}-py3-none-any.whl") > _MAX_WHEEL_FILENAME:
        raise ValueError("Coding data Skill wheel filename exceeds Product limit")
    if not isinstance(skill_document, bytes) or not skill_document:
        raise ValueError("Coding data Skill document must be nonempty bytes")
    try:
        skill_document.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Coding data Skill document must be UTF-8") from exc

    return _build_resource_wheel(
        plugin_id=plugin_id,
        version=version,
        resource_spec=resource.skill(
            contribution_id=contribution_id,
            locator=f"skills/{skill_name}",
        ),
        body_path=f"skills/{skill_name}/SKILL.md",
        body=skill_document,
    )


def _build_resource_wheel(
    *,
    plugin_id: str,
    version: str,
    resource_spec: ResourceItemSpec,
    body_path: str,
    body: bytes,
) -> bytes:
    compiled = package(
        id=plugin_id,
        version=version,
        contributions=(resource_spec,),
    )
    files = {f"{plugin_id}/{item.path}": item.content for item in compiled.artifacts}
    files[f"{plugin_id}/{body_path}"] = body
    dist_info = f"{plugin_id}-{version}.dist-info"
    files[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {plugin_id}\nVersion: {version}\n\n"
    ).encode("ascii")
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n\n"
    )
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, body in sorted(files.items()):
        digest = urlsafe_b64encode(sha256(body).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, f"sha256={digest}", str(len(body))))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    files[f"{dist_info}/RECORD"] = record.getvalue().encode("utf-8")
    if sum(len(body) for body in files.values()) > _MAX_TREE_BYTES:
        raise ValueError(
            f"Coding data {resource_spec.resource_kind.title()} extracted tree exceeds 1 MiB"
        )

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, body in sorted(files.items()):
            member = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            member.create_system = 3
            member.external_attr = (stat.S_IFREG | 0o644) << 16
            member.compress_type = zipfile.ZIP_STORED
            archive.writestr(member, body)
    wheel = output.getvalue()
    if len(wheel) > _MAX_WHEEL_BYTES:
        raise ValueError(
            f"Coding data {resource_spec.resource_kind.title()} wheel exceeds 2 MiB"
        )
    return wheel


def build_coding_data_prompt_wheel(
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    prompt_name: str,
    prompt_document: bytes,
) -> bytes:
    """Build one inert Prompt wheel for Coding Product's Prompt gate."""

    if not isinstance(plugin_id, str) or _SIMPLE_ID.fullmatch(plugin_id) is None:
        raise ValueError("Coding data Prompt Plugin ID must be simple lowercase ASCII")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError("Coding data Prompt version must be numeric")
    if not isinstance(prompt_name, str) or _PROMPT_NAME.fullmatch(prompt_name) is None:
        raise ValueError("Coding data Prompt name must be lowercase ASCII")
    if len(prompt_name) > 252:
        raise ValueError("Coding data Prompt name exceeds wheel path component budget")
    if len(f"{plugin_id}-{version}-py3-none-any.whl") > _MAX_WHEEL_FILENAME:
        raise ValueError("Coding data Prompt wheel filename exceeds Product limit")
    if not isinstance(prompt_document, bytes) or not prompt_document:
        raise ValueError("Coding data Prompt document must be nonempty bytes")
    try:
        prompt_document.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Coding data Prompt document must be UTF-8") from exc
    return _build_resource_wheel(
        plugin_id=plugin_id,
        version=version,
        resource_spec=resource.prompt(
            contribution_id=contribution_id,
            locator=f"prompts/{prompt_name}.md",
        ),
        body_path=f"prompts/{prompt_name}.md",
        body=prompt_document,
    )


def build_coding_data_theme_wheel(
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    theme_name: str,
    theme_document: bytes,
) -> bytes:
    """Build one style-only Theme wheel for Coding's explicit TUI selection."""

    if not isinstance(plugin_id, str) or _SIMPLE_ID.fullmatch(plugin_id) is None:
        raise ValueError("Coding data Theme Plugin ID must be simple lowercase ASCII")
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError("Coding data Theme version must be numeric")
    if not isinstance(theme_name, str) or _THEME_NAME.fullmatch(theme_name) is None:
        raise ValueError("Coding data Theme name must be lowercase ASCII")
    if len(theme_name) > 64:
        raise ValueError("Coding data Theme name exceeds selection budget")
    if len(f"{plugin_id}-{version}-py3-none-any.whl") > _MAX_WHEEL_FILENAME:
        raise ValueError("Coding data Theme wheel filename exceeds Product limit")
    parse_theme_document_v1(theme_document)
    return _build_resource_wheel(
        plugin_id=plugin_id,
        version=version,
        resource_spec=resource.theme(
            contribution_id=contribution_id,
            locator=f"themes/{theme_name}.json",
        ),
        body_path=f"themes/{theme_name}.json",
        body=theme_document,
    )


def write_coding_data_skill_wheel(
    directory: str | Path,
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    skill_name: str,
    skill_document: bytes,
) -> Path:
    """Write a new wheel without replacing an existing author artifact."""

    wheel = build_coding_data_skill_wheel(
        plugin_id=plugin_id,
        version=version,
        contribution_id=contribution_id,
        skill_name=skill_name,
        skill_document=skill_document,
    )
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{plugin_id}-{version}-py3-none-any.whl"
    with target.open("xb") as output:
        output.write(wheel)
    return target


def write_coding_data_prompt_wheel(
    directory: str | Path,
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    prompt_name: str,
    prompt_document: bytes,
) -> Path:
    """Write a new Prompt wheel without replacing an existing artifact."""

    wheel = build_coding_data_prompt_wheel(
        plugin_id=plugin_id,
        version=version,
        contribution_id=contribution_id,
        prompt_name=prompt_name,
        prompt_document=prompt_document,
    )
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{plugin_id}-{version}-py3-none-any.whl"
    with target.open("xb") as output:
        output.write(wheel)
    return target


def write_coding_data_theme_wheel(
    directory: str | Path,
    *,
    plugin_id: str,
    version: str,
    contribution_id: str,
    theme_name: str,
    theme_document: bytes,
) -> Path:
    """Write a new Theme wheel without replacing an existing artifact."""

    wheel = build_coding_data_theme_wheel(
        plugin_id=plugin_id,
        version=version,
        contribution_id=contribution_id,
        theme_name=theme_name,
        theme_document=theme_document,
    )
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{plugin_id}-{version}-py3-none-any.whl"
    with target.open("xb") as output:
        output.write(wheel)
    return target


__all__ = [
    "build_coding_data_prompt_wheel",
    "build_coding_data_skill_wheel",
    "build_coding_data_theme_wheel",
    "write_coding_data_prompt_wheel",
    "write_coding_data_skill_wheel",
    "write_coding_data_theme_wheel",
]
