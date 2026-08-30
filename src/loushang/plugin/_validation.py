"""Inert package and engine-feature validation for the public Plugin SDK."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final

from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.plugins._strict_json import (
    PluginJsonCodecError,
    StrictPluginJsonCodec,
)
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_DECLARATION_IR_VERSION,
    PluginDeclarationCodecError,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.skill_actions import (
    SkillActionCodecError,
    SkillActionDocumentCodec,
)

PLUGIN_MANIFEST_VERSION: Final = 1
PLUGIN_ENGINE_API_VERSION: Final = 1
PLUGIN_ENGINE_FEATURES: Final = frozenset(
    {
        "capability-provider-v2",
        "catalog-consumer-v1",
        "declaration-document-v1",
        "in-process-definition-v1",
        "managed-skill-action-v1",
        "resource-item-v1",
        "symbol-reference-v2",
    }
)
_MAX_PUBLIC_MANIFEST_BYTES = 1_048_576
_MANIFEST_FIELDS = {
    "contributionIndex",
    "engine",
    "manifestVersion",
    "name",
    "packageRoot",
    "version",
}
_ENGINE_FIELDS = {
    "apiVersion",
    "declarationIrVersion",
    "requiredFeatures",
}


@dataclass(frozen=True, slots=True)
class PluginValidationDiagnostic:
    """Stable package-author diagnostic with source attribution."""

    code: str
    message: str
    path: str
    contribution_id: str | None = None
    owner: str | None = None


@dataclass(frozen=True, slots=True)
class PluginValidationResult:
    """Complete inert validation result for one package directory."""

    package_root: str
    manifest_path: str
    plugin_id: str | None
    plugin_version: str | None
    engine_api_version: int | None
    declaration_ir_version: int | None
    required_features: tuple[str, ...]
    diagnostics: tuple[PluginValidationDiagnostic, ...]

    @property
    def valid(self) -> bool:
        return not self.diagnostics


def validate_package(path: str | Path) -> PluginValidationResult:
    """Validate manifest, negotiation, index, and document IR without importing."""

    unresolved_root = Path(path).expanduser()
    manifest_path = unresolved_root / "plugin.json"
    plugin_id: str | None = None
    plugin_version: str | None = None
    engine_version: int | None = None
    declaration_version: int | None = None
    features: tuple[str, ...] = ()
    diagnostics: list[PluginValidationDiagnostic] = []

    try:
        root = unresolved_root.resolve()
        manifest_path = root / "plugin.json"
    except (OSError, RuntimeError):
        return _result(
            unresolved_root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    "plugin_package_path_unresolvable",
                    "Plugin package path could not be resolved",
                    manifest_path,
                ),
            ),
        )
    if not root.is_dir():
        return _result(
            root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    "plugin_package_not_directory",
                    "Plugin package path is not a directory",
                    manifest_path,
                ),
            ),
        )
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return _result(
            root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    "plugin_manifest_missing_or_link",
                    "Stable Plugin packages require a regular plugin.json",
                    manifest_path,
                ),
            ),
        )
    try:
        encoded = manifest_path.read_bytes()
    except OSError:
        return _result(
            root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    "plugin_manifest_unreadable",
                    "Plugin manifest could not be read",
                    manifest_path,
                ),
            ),
        )
    if len(encoded) > _MAX_PUBLIC_MANIFEST_BYTES:
        return _result(
            root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    "plugin_manifest_too_large",
                    "Plugin manifest exceeds the public SDK byte limit",
                    manifest_path,
                ),
            ),
        )
    try:
        payload = StrictPluginJsonCodec.decode_bytes(encoded)
    except PluginJsonCodecError as exc:
        return _result(
            root,
            manifest_path,
            diagnostics=(_diagnostic(exc.code, str(exc), manifest_path),),
        )
    if not isinstance(payload, dict):
        return _result(
            root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    "plugin_manifest_type_mismatch",
                    "Plugin manifest must be an object",
                    manifest_path,
                ),
            ),
        )

    plugin_id = payload.get("name") if isinstance(payload.get("name"), str) else None
    plugin_version = (
        payload.get("version") if isinstance(payload.get("version"), str) else None
    )
    manifest_fields = set(payload)
    if manifest_fields != _MANIFEST_FIELDS:
        diagnostics.append(
            _diagnostic(
                "plugin_manifest_exact_field_mismatch",
                "Stable Plugin manifest fields do not match version 1",
                manifest_path,
            )
        )
    manifest_version = payload.get("manifestVersion")
    if manifest_version != PLUGIN_MANIFEST_VERSION or isinstance(
        manifest_version, bool
    ):
        diagnostics.append(
            _diagnostic(
                "unsupported_plugin_manifest_version",
                "Unsupported Plugin manifest version",
                manifest_path,
            )
        )
    engine = payload.get("engine")
    if not isinstance(engine, dict):
        diagnostics.append(
            _diagnostic(
                "plugin_engine_contract_missing",
                "Stable Plugin manifest requires an engine contract",
                manifest_path,
            )
        )
    else:
        engine_version, declaration_version, features = _validate_engine(
            engine,
            path=manifest_path,
            diagnostics=diagnostics,
        )

    try:
        package = PluginManifestParser().parse(root)
    except (FileNotFoundError, PluginManifestError) as exc:
        diagnostics.append(
            _diagnostic(
                getattr(exc, "code", "invalid_plugin_manifest"),
                str(exc),
                getattr(exc, "path", manifest_path),
            )
        )
        return _result(
            root,
            manifest_path,
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            engine_version=engine_version,
            declaration_version=declaration_version,
            features=features,
            diagnostics=diagnostics,
        )

    missing_features = tuple(
        sorted(
            _required_index_features(package.contribution_index.items) - set(features)
        )
    )
    if missing_features:
        diagnostics.append(
            _diagnostic(
                "plugin_engine_feature_declaration_incomplete",
                "Plugin engine contract omits required features: "
                + ", ".join(missing_features),
                manifest_path,
            )
        )

    decoded_documents: dict[Path, object] = {}
    action_documents_found = False
    for reservation in package.contribution_index.items:
        source = reservation.declaration_source
        if source.kind == "in_process":
            source_path = package.package_root / source.relative_path
            if (
                source_path.is_symlink()
                or not source_path.is_file()
                or not _is_within(source_path, package.package_root)
            ):
                diagnostics.append(
                    _diagnostic(
                        "plugin_definition_source_unreadable",
                        "Plugin Definition source must be a contained regular file",
                        source_path,
                        contribution_id=reservation.contribution_id,
                        owner=reservation.owner,
                    )
                )
            continue
        assert source.locator is not None
        document_path = package.package_root / source.locator
        try:
            if (
                document_path.is_symlink()
                or not document_path.is_file()
                or not _is_within(document_path, package.package_root)
            ):
                raise OSError("declaration document is not a regular file")
            document = decoded_documents.get(document_path)
            if document is None:
                document = PluginDeclarationDocumentCodec.decode_bytes(
                    document_path.read_bytes()
                )
                decoded_documents[document_path] = document
            assert hasattr(document, "declarations")
            matching = tuple(
                declaration
                for declaration in document.declarations
                if declaration.contribution_id == reservation.contribution_id
            )
            if len(matching) != 1:
                diagnostics.append(
                    _diagnostic(
                        "plugin_declaration_reservation_mismatch",
                        "Declaration document must contain the reserved contribution",
                        document_path,
                        contribution_id=reservation.contribution_id,
                        owner=reservation.owner,
                    )
                )
                continue
            declaration = matching[0]
            if (
                declaration.plugin_id != package.manifest.name
                or declaration.kind != reservation.kind
                or declaration.owner != reservation.owner
                or declaration.reservation_fingerprint != reservation.fingerprint
                or declaration.source_descriptor_fingerprint
                != reservation.source_descriptor_fingerprint
                or declaration.source_kind != source.kind
            ):
                diagnostics.append(
                    _diagnostic(
                        "plugin_declaration_reservation_mismatch",
                        "Declaration envelope does not match its manifest reservation",
                        document_path,
                        contribution_id=reservation.contribution_id,
                        owner=reservation.owner,
                    )
                )
                continue
            if reservation.kind == "resource_item":
                action_documents_found = (
                    _validate_resource_locator(
                        declaration.to_dict()["payload"],
                        package_root=package.package_root,
                        document_path=document_path,
                        contribution_id=reservation.contribution_id,
                        owner=reservation.owner,
                        diagnostics=diagnostics,
                        action_feature_declared=("managed-skill-action-v1" in features),
                    )
                    or action_documents_found
                )
        except PluginDeclarationCodecError as exc:
            diagnostics.append(
                _diagnostic(
                    exc.code,
                    str(exc),
                    document_path,
                    contribution_id=reservation.contribution_id,
                    owner=reservation.owner,
                )
            )
        except OSError:
            diagnostics.append(
                _diagnostic(
                    "plugin_declaration_document_unreadable",
                    "Plugin declaration document could not be read",
                    document_path,
                    contribution_id=reservation.contribution_id,
                    owner=reservation.owner,
                )
            )

    if "managed-skill-action-v1" in features and not action_documents_found:
        diagnostics.append(
            _diagnostic(
                "plugin_skill_action_feature_unused",
                "Plugin declares managed Skill actions but has no action document",
                manifest_path,
            )
        )
    return _result(
        root,
        manifest_path,
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        engine_version=engine_version,
        declaration_version=declaration_version,
        features=features,
        diagnostics=diagnostics,
    )


def _validate_engine(
    engine: dict[object, object],
    *,
    path: Path,
    diagnostics: list[PluginValidationDiagnostic],
) -> tuple[int | None, int | None, tuple[str, ...]]:
    if set(engine) != _ENGINE_FIELDS:
        diagnostics.append(
            _diagnostic(
                "plugin_engine_exact_field_mismatch",
                "Plugin engine contract fields do not match version 1",
                path,
            )
        )
    api_version = engine.get("apiVersion")
    declaration_version = engine.get("declarationIrVersion")
    api_result = api_version if type(api_version) is int else None
    declaration_result = (
        declaration_version if type(declaration_version) is int else None
    )
    if api_version != PLUGIN_ENGINE_API_VERSION or isinstance(api_version, bool):
        diagnostics.append(
            _diagnostic(
                "unsupported_plugin_engine_api_version",
                "Unsupported Plugin engine API version",
                path,
            )
        )
    if declaration_version != PLUGIN_DECLARATION_IR_VERSION or isinstance(
        declaration_version, bool
    ):
        diagnostics.append(
            _diagnostic(
                "unsupported_plugin_declaration_ir_version",
                "Unsupported Plugin declaration IR version",
                path,
            )
        )
    required = engine.get("requiredFeatures")
    if (
        not isinstance(required, list)
        or any(not isinstance(item, str) for item in required)
        or required != sorted(set(required))
    ):
        diagnostics.append(
            _diagnostic(
                "plugin_engine_features_not_canonical",
                "Plugin required features must be sorted unique strings",
                path,
            )
        )
        return api_result, declaration_result, ()
    features = tuple(required)
    unsupported = tuple(item for item in features if item not in PLUGIN_ENGINE_FEATURES)
    if unsupported:
        diagnostics.append(
            _diagnostic(
                "unsupported_plugin_engine_feature",
                "Plugin requires unsupported engine features: "
                + ", ".join(unsupported),
                path,
            )
        )
    return api_result, declaration_result, features


def _required_index_features(items: tuple[object, ...]) -> set[str]:
    features: set[str] = set()
    for item in items:
        kind = getattr(item, "kind", None)
        source = getattr(item, "declaration_source", None)
        if kind == "capability_provider":
            features.update({"capability-provider-v2", "symbol-reference-v2"})
        elif kind in {"command_pack", "tool_pack"}:
            features.add("catalog-consumer-v1")
        elif kind == "resource_item":
            features.add("resource-item-v1")
        if getattr(source, "kind", None) == "document":
            features.add("declaration-document-v1")
        elif getattr(source, "kind", None) == "in_process":
            features.add("in-process-definition-v1")
    return features


def _validate_resource_locator(
    payload: object,
    *,
    package_root: Path,
    document_path: Path,
    contribution_id: str,
    owner: str,
    diagnostics: list[PluginValidationDiagnostic],
    action_feature_declared: bool,
) -> bool:
    try:
        resource = ResourceItemDeclarationPayload.from_dict(payload)
    except (PluginDeclarationCodecError, TypeError, ValueError) as exc:
        diagnostics.append(
            _diagnostic(
                getattr(exc, "code", "plugin_resource_item_invalid"),
                str(exc),
                document_path,
                contribution_id=contribution_id,
                owner=owner,
            )
        )
        return False
    target = package_root / resource.locator
    expected_regular = (
        target.is_file() if resource.locator_kind == "file" else target.is_dir()
    )
    if (
        target.is_symlink()
        or not expected_regular
        or not _is_within(target, package_root)
    ):
        diagnostics.append(
            _diagnostic(
                "plugin_resource_locator_unreadable",
                "Plugin Resource locator must be a contained regular file or directory",
                target,
                contribution_id=contribution_id,
                owner=owner,
            )
        )
        return False
    if resource.resource_kind == "skill":
        skill_file = target if resource.locator_kind == "file" else target / "SKILL.md"
        if (
            skill_file.is_symlink()
            or not skill_file.is_file()
            or not _is_within(skill_file, package_root)
        ):
            diagnostics.append(
                _diagnostic(
                    "plugin_skill_document_unreadable",
                    "Skill Resource must contain a regular SKILL.md",
                    skill_file,
                    contribution_id=contribution_id,
                    owner=owner,
                )
            )
            return False
        skill_root = target if resource.locator_kind == "directory" else target.parent
        action_path = skill_root / "actions.json"
        if action_path.exists() or action_path.is_symlink():
            _validate_skill_actions(
                action_path,
                skill_root=skill_root,
                package_root=package_root,
                contribution_id=contribution_id,
                owner=owner,
                diagnostics=diagnostics,
                feature_declared=action_feature_declared,
            )
            return True
    return False


def _validate_skill_actions(
    action_path: Path,
    *,
    skill_root: Path,
    package_root: Path,
    contribution_id: str,
    owner: str,
    diagnostics: list[PluginValidationDiagnostic],
    feature_declared: bool,
) -> None:
    if not feature_declared:
        diagnostics.append(
            _diagnostic(
                "plugin_skill_action_feature_missing",
                "Skill action document requires managed-skill-action-v1",
                action_path,
                contribution_id=contribution_id,
                owner=owner,
            )
        )
    try:
        if (
            action_path.is_symlink()
            or not action_path.is_file()
            or not _is_within(action_path, package_root)
        ):
            raise OSError("action document is not a contained regular file")
        document = SkillActionDocumentCodec.decode_bytes(action_path.read_bytes())
    except SkillActionCodecError as exc:
        diagnostics.append(
            _diagnostic(
                exc.code,
                str(exc),
                action_path,
                contribution_id=contribution_id,
                owner=owner,
            )
        )
        return
    except OSError:
        diagnostics.append(
            _diagnostic(
                "plugin_skill_action_document_unreadable",
                "Skill action document could not be read",
                action_path,
                contribution_id=contribution_id,
                owner=owner,
            )
        )
        return
    for action in document.actions:
        script_path = skill_root / action.script
        try:
            if (
                script_path.is_symlink()
                or not script_path.is_file()
                or not _is_within(script_path, skill_root)
                or not _is_within(script_path, package_root)
            ):
                raise OSError("script is not a contained regular file")
            digest = sha256(script_path.read_bytes()).hexdigest()
        except OSError:
            diagnostics.append(
                _diagnostic(
                    "plugin_skill_action_script_unreadable",
                    "Managed Skill action script could not be read",
                    script_path,
                    contribution_id=contribution_id,
                    owner=owner,
                )
            )
            continue
        if digest != action.script_digest:
            diagnostics.append(
                _diagnostic(
                    "plugin_skill_action_script_digest_mismatch",
                    "Managed Skill action script digest does not match",
                    script_path,
                    contribution_id=contribution_id,
                    owner=owner,
                )
            )


def _is_within(path: Path, root: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _diagnostic(
    code: str,
    message: str,
    path: Path,
    *,
    contribution_id: str | None = None,
    owner: str | None = None,
) -> PluginValidationDiagnostic:
    return PluginValidationDiagnostic(
        code=code,
        message=message,
        path=str(path),
        contribution_id=contribution_id,
        owner=owner,
    )


def _result(
    root: Path,
    manifest_path: Path,
    *,
    plugin_id: str | None = None,
    plugin_version: str | None = None,
    engine_version: int | None = None,
    declaration_version: int | None = None,
    features: tuple[str, ...] = (),
    diagnostics: tuple[PluginValidationDiagnostic, ...]
    | list[PluginValidationDiagnostic] = (),
) -> PluginValidationResult:
    return PluginValidationResult(
        package_root=str(root),
        manifest_path=str(manifest_path),
        plugin_id=plugin_id,
        plugin_version=plugin_version,
        engine_api_version=engine_version,
        declaration_ir_version=declaration_version,
        required_features=features,
        diagnostics=tuple(diagnostics),
    )


__all__ = [
    "PLUGIN_ENGINE_API_VERSION",
    "PLUGIN_ENGINE_FEATURES",
    "PLUGIN_MANIFEST_VERSION",
    "PluginValidationDiagnostic",
    "PluginValidationResult",
    "validate_package",
]
