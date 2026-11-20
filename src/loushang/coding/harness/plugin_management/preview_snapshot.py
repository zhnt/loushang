"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import preview as _binding


def _check_workspace(query: _binding.CodingCurrentPreviewQuery) -> None:
    if query.workspace_guard is not None:
        query.workspace_guard()


def _require_fence(query: _binding.CodingCurrentPreviewQuery) -> None:
    if not _binding.coding_fenced_product_exists(query.layout):
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_product_not_fenced"
        )


def configured_capabilities(self: _binding.CodingCurrentPreviewQuery) -> dict[str, str]:
    """Read the CLI inference input under the same bounded settings policy."""

    _check_workspace(self)
    _require_fence(self)
    try:
        settings = capture_preview_settings(self.workspace)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_settings_unavailable"
        ) from exc
    _check_workspace(self)
    return dict(settings.capabilities)


def owner_revisions(self: _binding.CodingCurrentPreviewQuery) -> tuple[str, str, str]:
    """Read Product policy, authority, and Skill settings without composing."""

    _check_workspace(self)
    _require_fence(self)
    try:
        _disabled, settings_revision = capture_disabled_resource_settings(
            self.workspace
        )
        with _binding.CodingFencedProductReadOnlyPreviewOwner.open(
            self.layout, workspace_guard=self.workspace_guard
        ) as owner:
            policy_revision = owner.policy.policy_revision
            authority_revision = owner.policy.authority_revision
            owner.epoch_runtime.assert_current()
        _after, after_settings_revision = capture_disabled_resource_settings(
            self.workspace
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_owner_unavailable"
        ) from exc
    _check_workspace(self)
    if settings_revision != after_settings_revision:
        raise _binding.CodingCurrentPreviewError(code="plugin_preview_settings_stale")
    return policy_revision, authority_revision, settings_revision


def preview_current(
    self: _binding.CodingCurrentPreviewQuery,
    request: _binding.PluginCurrentPreviewRequestV1,
) -> _binding.CodingCurrentDataResourcePreviewV1:
    _check_workspace(self)
    if not isinstance(request, _binding.PluginCurrentPreviewRequestV1):
        raise TypeError("Plugin current preview requires a typed request")
    if (
        request.product_id != _binding.CODING_PRODUCT_ID
        or request.scope_id != self.layout.scope_id
    ):
        raise _binding.CodingCurrentPreviewError(code="plugin_preview_scope_mismatch")
    _require_fence(self)
    if _binding.os.name != "posix":
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_platform_unsupported"
        )
    try:
        _binding.resolve_coding_composition_set(request.composition_set_id)
    except (TypeError, ValueError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_composition_invalid"
        ) from exc
    try:
        disabled_skills, settings_revision = capture_disabled_resource_settings(
            self.workspace
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_settings_unavailable"
        ) from exc
    _check_workspace(self)
    try:
        with _binding.CodingFencedProductReadOnlyPreviewOwner.open(
            self.layout, workspace_guard=self.workspace_guard
        ) as owner:
            preview = owner.preview_current_data_resources(
                workspace=self.workspace,
                composition_set_id=request.composition_set_id,
                disabled_skills=disabled_skills,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_owner_unavailable"
        ) from exc
    try:
        _after_skills, after_revision = capture_disabled_resource_settings(
            self.workspace
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code="plugin_preview_settings_unavailable"
        ) from exc
    _check_workspace(self)
    gaps = set(preview.evidence_gaps)
    if settings_revision != after_revision:
        gaps.add("stale_snapshot")
    return _binding.replace(
        preview,
        disabled_skill_settings_revision=settings_revision,
        evidence_gaps=tuple(sorted(gaps)),
    )


def capture_disabled_resource_settings(
    workspace: _binding.Path,
) -> tuple[tuple[str, ...], str]:
    """Apply the Product codec without a lock; hash only the relevant projection."""

    settings = capture_preview_settings(workspace)
    digest = _binding.sha256(_binding._DISABLED_SKILLS_REVISION_DOMAIN)
    digest.update(
        _binding.json.dumps(
            settings.disabled_skills,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return settings.disabled_skills, f"sha256:{digest.hexdigest()}"


def capture_preview_settings(workspace: _binding.Path) -> _binding.ControlConfig:
    """Read only declared settings bytes for preview and CLI choice inference."""

    settings = _binding.CONTROL_CONFIG_CODEC.default()
    for label, path in (
        ("global", _binding.default_global_settings_path()),
        ("project", _binding.default_project_settings_path(workspace)),
    ):
        body = read_settings_bytes(path)
        if body is None:
            continue
        document = _binding.json.loads(body.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError("Plugin preview settings must be a JSON object")
        result = _binding.CONTROL_CONFIG_CODEC.apply(settings, document, layer=label)
        if result.issues:
            raise ValueError("Plugin preview settings have invalid fields")
        settings = result.value
    return settings


def read_settings_bytes(path: _binding.Path) -> bytes | None:
    try:
        descriptor = _binding.os.open(
            path,
            _binding.os.O_RDONLY
            | _binding.os.O_NONBLOCK
            | _binding.os.O_NOFOLLOW
            | _binding.os.O_CLOEXEC,
        )
    except FileNotFoundError:
        return None
    try:
        opened = _binding.os.fstat(descriptor)
        visible = path.lstat()
        if (
            not _binding.stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino)
            or opened.st_size > _binding._MAX_SETTINGS_BYTES
        ):
            raise ValueError("Plugin preview settings file is unsafe")
        with _binding.os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(_binding._MAX_SETTINGS_BYTES + 1)
        if len(body) > _binding._MAX_SETTINGS_BYTES:
            raise ValueError("Plugin preview settings file is too large")
        return body
    finally:
        _binding.os.close(descriptor)
