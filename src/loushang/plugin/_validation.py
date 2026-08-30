"""Inert package and engine-feature validation for the public Plugin SDK."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.plugins._strict_json import (
    PluginJsonCodecError,
    StrictPluginJsonCodec,
)
from loushang.harness.resources.plugins.declarations import (
    MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES,
    PluginDeclarationCodecError,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.engine import (
    PLUGIN_ENGINE_API_VERSION,
    PLUGIN_ENGINE_FEATURES,
    PLUGIN_MANIFEST_VERSION,
    inspect_plugin_engine_contract,
)
from loushang.harness.resources.plugins.manifest import (
    PluginManifestError,
    PluginManifestParser,
)
from loushang.harness.resources.plugins.safe_files import (
    ContainedFileCaptureError,
    capture_contained_regular_file,
)
from loushang.harness.resources.skill_actions import (
    MAX_SKILL_ACTION_DOCUMENT_BYTES,
    MAX_SKILL_ACTION_SCRIPT_BYTES,
    SkillActionCodecError,
    SkillActionDocumentCodec,
)

_MAX_PUBLIC_MANIFEST_BYTES = 1_048_576


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
    try:
        manifest_capture = capture_contained_regular_file(
            root,
            "plugin.json",
            max_bytes=_MAX_PUBLIC_MANIFEST_BYTES,
        )
        encoded = manifest_capture.body
    except ContainedFileCaptureError as exc:
        return _result(
            root,
            manifest_path,
            diagnostics=(
                _diagnostic(
                    (
                        "plugin_manifest_too_large"
                        if exc.code == "contained_file_too_large"
                        else "plugin_manifest_missing_or_link"
                    ),
                    "Stable Plugin packages require a bounded regular plugin.json",
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
    engine = payload.get("engine")
    if isinstance(engine, dict):
        raw_api = engine.get("apiVersion")
        raw_declaration = engine.get("declarationIrVersion")
        raw_features = engine.get("requiredFeatures")
        engine_version = raw_api if type(raw_api) is int else None
        declaration_version = (
            raw_declaration if type(raw_declaration) is int else None
        )
        if isinstance(raw_features, list) and all(
            isinstance(item, str) for item in raw_features
        ):
            features = tuple(raw_features)
    _contract, engine_diagnostics = inspect_plugin_engine_contract(payload)
    diagnostics.extend(
        _diagnostic(item.code, item.message, manifest_path)
        for item in engine_diagnostics
    )
    if engine_diagnostics:
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

    try:
        package = PluginManifestParser().parse(
            root,
            _manifest_capture=manifest_capture,
        )
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

    decoded_documents: dict[Path, object] = {}
    action_documents_found = False
    for reservation in package.contribution_index.items:
        source = reservation.declaration_source
        if source.kind == "in_process":
            source_path = package.package_root / source.relative_path
            try:
                _capture_package_file(
                    package.package_root,
                    source_path,
                    max_bytes=MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES,
                )
            except ContainedFileCaptureError:
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
            document = decoded_documents.get(document_path)
            if document is None:
                document = PluginDeclarationDocumentCodec.decode_bytes(
                    _capture_package_file(
                        package.package_root,
                        document_path,
                        max_bytes=MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES,
                    )
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
        except (ContainedFileCaptureError, OSError):
            diagnostics.append(
                _diagnostic(
                    "plugin_declaration_document_unreadable",
                    "Plugin declaration document could not be read",
                    document_path,
                    contribution_id=reservation.contribution_id,
                    owner=reservation.owner,
                )
            )

    reservations_by_document: dict[Path, set[tuple[str, str]]] = {}
    for reservation in package.contribution_index.items:
        source = reservation.declaration_source
        if source.kind != "document":
            continue
        assert source.locator is not None
        reservations_by_document.setdefault(
            package.package_root / source.locator,
            set(),
        ).add((package.manifest.name, reservation.contribution_id))
    for document_path, document in decoded_documents.items():
        assert hasattr(document, "declarations")
        actual = tuple(
            (declaration.plugin_id, declaration.contribution_id)
            for declaration in document.declarations
        )
        expected = reservations_by_document.get(document_path, set())
        if len(actual) != len(set(actual)) or set(actual) != expected:
            diagnostics.append(
                _diagnostic(
                    "plugin_declaration_reservation_mismatch",
                    "Declaration document must exactly fulfill its reservations",
                    document_path,
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
        try:
            _capture_package_file(
                package_root,
                skill_file,
                max_bytes=MAX_SKILL_ACTION_SCRIPT_BYTES,
            )
        except ContainedFileCaptureError:
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
        document = SkillActionDocumentCodec.decode_bytes(
            _capture_package_file(
                package_root,
                action_path,
                max_bytes=MAX_SKILL_ACTION_DOCUMENT_BYTES,
            )
        )
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
    except (ContainedFileCaptureError, OSError):
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
            script = _capture_package_file(
                package_root,
                script_path,
                max_bytes=MAX_SKILL_ACTION_SCRIPT_BYTES,
            )
            script_path.relative_to(skill_root)
            digest = sha256(script).hexdigest()
        except (ContainedFileCaptureError, OSError, ValueError):
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


def _capture_package_file(root: Path, path: Path, *, max_bytes: int) -> bytes:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ContainedFileCaptureError(
            "Package file is outside its root",
            code="contained_file_path_escape",
            path=path,
        ) from exc
    return capture_contained_regular_file(
        root,
        relative.as_posix(),
        max_bytes=max_bytes,
    ).body


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
