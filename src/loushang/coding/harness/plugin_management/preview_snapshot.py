"""Complete runtime/management programs over the original borrowed authorities.

Product decisions, factories, nominal values and historical fault seams remain
explicit intermediate Code dependencies; no parallel state or effect owner.
"""

from __future__ import annotations

from loushang.coding.plugin_manager import preview as _binding


def configured_capabilities(self: _binding.CodingCurrentPreviewQuery) -> dict[str, str]:
    """Read the CLI inference input under the same bounded settings policy."""

    if self.workspace_guard is not None:
        self.workspace_guard()
    if not _binding.coding_fenced_product_exists(self.layout):
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_001"]
        )
    try:
        settings = _binding._capture_preview_settings(self.workspace)
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_002"]
        ) from exc
    if self.workspace_guard is not None:
        self.workspace_guard()
    return dict(settings.capabilities)


def owner_revisions(self: _binding.CodingCurrentPreviewQuery) -> tuple[str, str, str]:
    """Read Product policy, authority, and Skill settings without composing."""

    if self.workspace_guard is not None:
        self.workspace_guard()
    if not _binding.coding_fenced_product_exists(self.layout):
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_001"]
        )
    try:
        _disabled, settings_revision = _binding._capture_disabled_skills(self.workspace)
        with _binding.CodingFencedProductReadOnlyPreviewOwner.open(
            self.layout, workspace_guard=self.workspace_guard
        ) as owner:
            policy_revision = owner.policy.policy_revision
            authority_revision = owner.policy.authority_revision
            owner.epoch_runtime.assert_current()
        _after, after_settings_revision = _binding._capture_disabled_skills(
            self.workspace
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_004"]
        ) from exc
    if self.workspace_guard is not None:
        self.workspace_guard()
    if settings_revision != after_settings_revision:
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_003"]
        )
    return policy_revision, authority_revision, settings_revision


def preview_current(
    self: _binding.CodingCurrentPreviewQuery,
    request: _binding.PluginCurrentPreviewRequestV1,
) -> _binding.CodingCurrentDataResourcePreviewV1:
    if self.workspace_guard is not None:
        self.workspace_guard()
    if not isinstance(request, _binding.PluginCurrentPreviewRequestV1):
        raise TypeError(_binding._RUNTIME_PROGRAM_VALUES["value_005"])
    if (
        request.product_id != _binding.CODING_PRODUCT_ID
        or request.scope_id != self.layout.scope_id
    ):
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_006"]
        )
    if not _binding.coding_fenced_product_exists(self.layout):
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_001"]
        )
    if _binding.os.name != "posix":
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_007"]
        )
    try:
        _binding.resolve_coding_composition_set(request.composition_set_id)
    except (TypeError, ValueError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_008"]
        ) from exc
    try:
        disabled_skills, settings_revision = _binding._capture_disabled_skills(
            self.workspace
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_002"]
        ) from exc
    if self.workspace_guard is not None:
        self.workspace_guard()
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
            code=_binding._RUNTIME_PROGRAM_VALUES["value_004"]
        ) from exc
    try:
        _after_skills, after_revision = _binding._capture_disabled_skills(
            self.workspace
        )
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        raise _binding.CodingCurrentPreviewError(
            code=_binding._RUNTIME_PROGRAM_VALUES["value_002"]
        ) from exc
    if self.workspace_guard is not None:
        self.workspace_guard()
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

    settings = _binding._capture_preview_settings(workspace)
    digest = _binding.sha256(_binding._RUNTIME_PROGRAM_BYTES["value_001"])
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
        body = _binding._read_settings_bytes(path)
        if body is None:
            continue
        document = _binding.json.loads(body.decode("utf-8"))
        if not isinstance(document, dict):
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_009"])
        result = _binding.CONTROL_CONFIG_CODEC.apply(settings, document, layer=label)
        if result.issues:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_010"])
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
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_011"])
        with _binding.os.fdopen(descriptor, "rb", closefd=False) as stream:
            body = stream.read(_binding._MAX_SETTINGS_BYTES + 1)
        if len(body) > _binding._MAX_SETTINGS_BYTES:
            raise ValueError(_binding._RUNTIME_PROGRAM_VALUES["value_012"])
        return body
    finally:
        _binding.os.close(descriptor)
