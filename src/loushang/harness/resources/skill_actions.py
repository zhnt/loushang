"""Strict data-only declarations for digest-bound managed Skill actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal, NoReturn, cast

from loushang.harness.resources.plugins._strict_json import (
    PluginJsonCodecError,
    StrictPluginJsonCodec,
)
from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)

SKILL_ACTION_DOCUMENT_VERSION = 1
SKILL_ACTION_DECLARATION_VERSION = 1
MAX_SKILL_ACTION_DOCUMENT_BYTES = 262_144

SkillActionRuntime = Literal["posix", "python"]
SkillActionCwdPolicy = Literal["skill", "workspace"]
SkillActionSourceKind = Literal["native", "package"]
SkillActionEffectKind = Literal[
    "filesystem.delete",
    "filesystem.read",
    "filesystem.write",
    "network.mutate",
    "network.request",
    "repository.publish",
]

_RUNTIMES = frozenset({"posix", "python"})
_CWD_POLICIES = frozenset({"skill", "workspace"})
_EFFECT_KINDS = frozenset(
    {
        "filesystem.delete",
        "filesystem.read",
        "filesystem.write",
        "network.mutate",
        "network.request",
        "repository.publish",
    }
)
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SkillActionCodecError(ValueError):
    """Finite inert declaration diagnostic; it never wraps execution errors."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SkillActionCatalogSelection:
    """Resource-owner-minted facts for one exact Catalog Skill selection."""

    catalog_generation: int
    catalog_snapshot_fingerprint: str
    candidate_fingerprint: str
    skill_content_digest: str
    source_kind: SkillActionSourceKind
    source_revision: str

    def __post_init__(self) -> None:
        if type(self.catalog_generation) is not int or self.catalog_generation < 1:
            raise ValueError("Skill action Catalog generation must be positive")
        _require_digest(
            self.catalog_snapshot_fingerprint,
            name="Skill action Catalog snapshot fingerprint",
        )
        _require_digest(
            self.candidate_fingerprint,
            name="Skill action Catalog candidate fingerprint",
        )
        _require_digest(self.skill_content_digest, name="Skill content digest")
        if self.source_kind not in {"native", "package"}:
            raise ValueError("Skill action Catalog source kind is unsupported")
        _require_digest(
            self.source_revision,
            name="Skill action Catalog source revision",
        )


@dataclass(frozen=True, slots=True)
class SkillActionEffect:
    kind: SkillActionEffectKind
    target: str

    def __post_init__(self) -> None:
        if self.kind not in _EFFECT_KINDS:
            raise ValueError("Unsupported managed Skill action effect")
        _require_nonempty(self.target, name="Skill action effect target")
        if self.kind.startswith("filesystem.") and self.target not in {
            "skill",
            "workspace",
        }:
            raise ValueError(
                "Filesystem Skill action effects must target skill or workspace"
            )

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "target": self.target}

    @classmethod
    def from_dict(cls, value: object) -> SkillActionEffect:
        document = _exact_object(
            value,
            fields={"kind", "target"},
            name="Skill action effect",
        )
        kind = document["kind"]
        target = document["target"]
        if not isinstance(kind, str) or not isinstance(target, str):
            _raise("skill_action_field_type_mismatch", "Effect fields must be strings")
        try:
            return cls(kind=cast(SkillActionEffectKind, kind), target=target)
        except (TypeError, ValueError) as exc:
            _raise("skill_action_field_value_mismatch", str(exc), cause=exc)


@dataclass(frozen=True, slots=True)
class ManagedSkillActionDeclaration:
    """One immutable script launch contract; process execution remains external."""

    action_id: str
    script: str
    script_digest: str
    runtime: SkillActionRuntime
    argv: tuple[str, ...] = ()
    cwd_policy: SkillActionCwdPolicy = "skill"
    environment: tuple[tuple[str, str], ...] = ()
    effects: tuple[SkillActionEffect, ...] = ()
    containment: Literal["required"] = "required"
    declaration_version: int = SKILL_ACTION_DECLARATION_VERSION

    def __post_init__(self) -> None:
        if self.declaration_version != SKILL_ACTION_DECLARATION_VERSION:
            raise ValueError("Unsupported managed Skill action declaration version")
        if not isinstance(self.action_id, str) or not _IDENTIFIER.fullmatch(
            self.action_id
        ):
            raise ValueError("Invalid managed Skill action id")
        script = canonical_plugin_relative_path(self.script)
        if self.runtime not in _RUNTIMES:
            raise ValueError("Unsupported managed Skill action runtime")
        _require_digest(self.script_digest, name="Skill action script digest")
        argv = _string_tuple(self.argv, name="Skill action argv")
        if self.cwd_policy not in _CWD_POLICIES:
            raise ValueError("Unsupported managed Skill action cwd policy")
        environment = _environment_tuple(self.environment)
        effects = tuple(self.effects)
        if any(not isinstance(item, SkillActionEffect) for item in effects):
            raise TypeError("Skill action effects must contain effect declarations")
        effect_keys = tuple((item.kind, item.target) for item in effects)
        if effect_keys != tuple(sorted(effect_keys)) or len(effect_keys) != len(
            set(effect_keys)
        ):
            raise ValueError("Skill action effects must be sorted and unique")
        if self.containment != "required":
            raise ValueError("Managed Skill actions require containment")
        object.__setattr__(self, "script", script.as_posix())
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "environment", environment)
        object.__setattr__(self, "effects", effects)

    @property
    def relative_script(self) -> PurePosixPath:
        return PurePosixPath(self.script)

    def to_dict(self) -> dict[str, object]:
        return {
            "argv": list(self.argv),
            "containment": self.containment,
            "cwdPolicy": self.cwd_policy,
            "declarationVersion": self.declaration_version,
            "effects": [item.to_dict() for item in self.effects],
            "environment": [
                {"name": name, "value": value} for name, value in self.environment
            ],
            "id": self.action_id,
            "runtime": self.runtime,
            "script": self.script,
            "scriptDigest": self.script_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> ManagedSkillActionDeclaration:
        document = _exact_object(
            value,
            fields={
                "argv",
                "containment",
                "cwdPolicy",
                "declarationVersion",
                "effects",
                "environment",
                "id",
                "runtime",
                "script",
                "scriptDigest",
            },
            name="Managed Skill action",
        )
        version = document["declarationVersion"]
        if version != SKILL_ACTION_DECLARATION_VERSION or isinstance(version, bool):
            _raise(
                "unsupported_skill_action_declaration_version",
                "Unsupported managed Skill action declaration version",
            )
        argv = _wire_string_list(document["argv"], name="Skill action argv")
        effects_value = document["effects"]
        environment_value = document["environment"]
        if not isinstance(effects_value, list) or not isinstance(
            environment_value, list
        ):
            _raise(
                "skill_action_field_type_mismatch",
                "Skill action effects and environment must be lists",
            )
        environment: list[tuple[str, str]] = []
        for value in environment_value:
            entry = _exact_object(
                value,
                fields={"name", "value"},
                name="Skill action environment entry",
            )
            name = entry["name"]
            item_value = entry["value"]
            if not isinstance(name, str) or not isinstance(item_value, str):
                _raise(
                    "skill_action_field_type_mismatch",
                    "Skill action environment fields must be strings",
                )
            environment.append((name, item_value))
        string_fields = {
            key: document[key]
            for key in (
                "containment",
                "cwdPolicy",
                "id",
                "runtime",
                "script",
                "scriptDigest",
            )
        }
        if any(not isinstance(item, str) for item in string_fields.values()):
            _raise(
                "skill_action_field_type_mismatch",
                "Skill action identity fields must be strings",
            )
        try:
            return cls(
                action_id=cast(str, string_fields["id"]),
                script=cast(str, string_fields["script"]),
                script_digest=cast(str, string_fields["scriptDigest"]),
                runtime=cast(SkillActionRuntime, string_fields["runtime"]),
                argv=argv,
                cwd_policy=cast(
                    SkillActionCwdPolicy,
                    string_fields["cwdPolicy"],
                ),
                environment=tuple(environment),
                effects=tuple(
                    SkillActionEffect.from_dict(item) for item in effects_value
                ),
                containment=cast(Literal["required"], string_fields["containment"]),
                declaration_version=version,
            )
        except (TypeError, ValueError) as exc:
            _raise("skill_action_field_value_mismatch", str(exc), cause=exc)


@dataclass(frozen=True, slots=True)
class SkillActionDocument:
    actions: tuple[ManagedSkillActionDeclaration, ...]
    document_version: int = SKILL_ACTION_DOCUMENT_VERSION

    def __post_init__(self) -> None:
        if self.document_version != SKILL_ACTION_DOCUMENT_VERSION:
            raise ValueError("Unsupported Skill action document version")
        if not self.actions:
            raise ValueError("Skill action document must not be empty")
        if any(
            not isinstance(item, ManagedSkillActionDeclaration) for item in self.actions
        ):
            raise TypeError("Skill action document contains an invalid action")
        identities = tuple(item.action_id for item in self.actions)
        if identities != tuple(sorted(identities)) or len(identities) != len(
            set(identities)
        ):
            raise ValueError("Skill action document actions must be sorted and unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "actions": [item.to_dict() for item in self.actions],
            "documentVersion": self.document_version,
        }


class SkillActionDocumentCodec:
    @staticmethod
    def encode_bytes(document: SkillActionDocument) -> bytes:
        if not isinstance(document, SkillActionDocument):
            raise TypeError("Skill action codec requires a typed document")
        encoded = StrictPluginJsonCodec.encode(document.to_dict())
        if len(encoded) > MAX_SKILL_ACTION_DOCUMENT_BYTES:
            _raise(
                "skill_action_document_too_large", "Skill action document is too large"
            )
        return encoded

    @staticmethod
    def decode_bytes(encoded: bytes) -> SkillActionDocument:
        if len(encoded) > MAX_SKILL_ACTION_DOCUMENT_BYTES:
            _raise(
                "skill_action_document_too_large", "Skill action document is too large"
            )
        try:
            value = StrictPluginJsonCodec.decode_bytes(encoded)
        except PluginJsonCodecError as exc:
            _raise(exc.code, str(exc), cause=exc)
        document = _exact_object(
            value,
            fields={"actions", "documentVersion"},
            name="Skill action document",
        )
        version = document["documentVersion"]
        if version != SKILL_ACTION_DOCUMENT_VERSION or isinstance(version, bool):
            _raise(
                "unsupported_skill_action_document_version",
                "Unsupported Skill action document version",
            )
        actions = document["actions"]
        if not isinstance(actions, list):
            _raise(
                "skill_action_field_type_mismatch",
                "Skill action document actions must be a list",
            )
        try:
            result = SkillActionDocument(
                actions=tuple(
                    ManagedSkillActionDeclaration.from_dict(item) for item in actions
                ),
                document_version=version,
            )
        except SkillActionCodecError:
            raise
        except (TypeError, ValueError) as exc:
            _raise("skill_action_field_value_mismatch", str(exc), cause=exc)
        try:
            StrictPluginJsonCodec.require_canonical_bytes(encoded, result.to_dict())
        except PluginJsonCodecError as exc:
            _raise(exc.code, str(exc), cause=exc)
        return result


def _exact_object(value: object, *, fields: set[str], name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        _raise("skill_action_field_type_mismatch", f"{name} must be an object")
    if set(value) != fields:
        _raise("skill_action_exact_field_mismatch", f"{name} fields do not match")
    return value


def _wire_string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _raise("skill_action_field_type_mismatch", f"{name} must be a string list")
    return tuple(value)


def _string_tuple(value: object, *, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(f"{name} must be a string sequence")
    try:
        result: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{name} must be a string sequence") from exc
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{name} must contain non-empty strings")
    return cast(tuple[str, ...], result)


def _environment_tuple(value: object) -> tuple[tuple[str, str], ...]:
    if isinstance(value, str):
        raise TypeError("Skill action environment must contain name/value pairs")
    try:
        items: tuple[object, ...] = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(
            "Skill action environment must contain name/value pairs"
        ) from exc
    result: list[tuple[str, str]] = []
    for item in items:
        if isinstance(item, str):
            raise TypeError("Skill action environment must contain name/value pairs")
        try:
            pair: tuple[object, ...] = tuple(item)  # type: ignore[arg-type]
        except TypeError as exc:
            raise TypeError(
                "Skill action environment must contain name/value pairs"
            ) from exc
        if (
            len(pair) != 2
            or not isinstance(pair[0], str)
            or not isinstance(pair[1], str)
            or not _ENVIRONMENT_NAME.fullmatch(pair[0])
        ):
            raise ValueError("Skill action environment entry is invalid")
        result.append((pair[0], pair[1]))
    names = tuple(name for name, _ in result)
    if names != tuple(sorted(names)) or len(names) != len(set(names)):
        raise ValueError("Skill action environment must be sorted and unique")
    return tuple(result)


def _require_digest(value: object, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_nonempty(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _raise(
    code: str,
    message: str,
    *,
    cause: BaseException | None = None,
) -> NoReturn:
    error = SkillActionCodecError(message, code=code)
    if cause is None:
        raise error
    raise error from cause


__all__ = [
    "MAX_SKILL_ACTION_DOCUMENT_BYTES",
    "SKILL_ACTION_DECLARATION_VERSION",
    "SKILL_ACTION_DOCUMENT_VERSION",
    "ManagedSkillActionDeclaration",
    "SkillActionCatalogSelection",
    "SkillActionCodecError",
    "SkillActionCwdPolicy",
    "SkillActionDocument",
    "SkillActionDocumentCodec",
    "SkillActionEffect",
    "SkillActionEffectKind",
    "SkillActionRuntime",
    "SkillActionSourceKind",
]
