from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.extensions.api import ExtensionContributionAPI
from loushang.harness.extensions.contributions import surfaces_from_loaded_extension
from loushang.harness.extensions.events import VALID_EXTENSION_EVENTS
from loushang.harness.extensions.manifest import (
    ExtensionManifest,
    parse_extension_manifest,
)
from loushang.harness.extensions.types import ExtensionPolicyDecision, LoadedExtension
from loushang.harness.resources.diagnostics import resource_diagnostic
from loushang.harness.resources.types import ExtensionDescriptor
from loushang.harness.tools.core import ToolDefinition

ExtensionApiFactory = Callable[..., ExtensionContributionAPI]
ExtensionPolicyResolver = Callable[
    [ExtensionManifest | None, bool], ExtensionPolicyDecision
]


class ExtensionLoader:
    def __init__(
        self,
        *,
        api_factory: ExtensionApiFactory = ExtensionContributionAPI,
        policy_resolver: ExtensionPolicyResolver | None = None,
        legacy_event_names: tuple[str, ...] = VALID_EXTENSION_EVENTS,
    ) -> None:
        self._diagnostics: list[DiagnosticDraft] = []
        self._api_factory = api_factory
        self._policy_resolver = policy_resolver or _descriptor_activation_policy
        self._legacy_event_names = legacy_event_names

    def get_diagnostics(self) -> list[DiagnosticDraft]:
        return list(self._diagnostics)

    def load_extensions(
        self, descriptors: list[ExtensionDescriptor]
    ) -> list[LoadedExtension]:
        self._diagnostics = []
        loaded_extensions: list[LoadedExtension] = []
        for descriptor in descriptors:
            loaded = self.load_extension(descriptor)
            if loaded is not None:
                loaded_extensions.append(loaded)
        return loaded_extensions

    def load_extension(self, descriptor: ExtensionDescriptor) -> LoadedExtension | None:
        manifest, manifest_diagnostics = _load_descriptor_manifest(descriptor)
        self._diagnostics.extend(manifest_diagnostics)
        metadata = (
            descriptor.metadata if isinstance(descriptor.metadata, Mapping) else {}
        )
        if "extension" in metadata:
            try:
                return self._finalize_loaded_extension(
                    _with_descriptor_source_info(
                        _adapt_legacy_extension_object(
                            descriptor=descriptor,
                            entry_path=descriptor.entry_path or descriptor.source_path,
                            extension_object=metadata["extension"],
                            api_factory=self._api_factory,
                            legacy_event_names=self._legacy_event_names,
                        ),
                        descriptor,
                    ),
                    manifest=manifest,
                    enabled=descriptor.enabled,
                )
            except Exception as exc:
                self._diagnostics.append(
                    resource_diagnostic(
                        code="extension_load_failed",
                        message=f"Legacy metadata extension adaptation failed: {exc}",
                        source_path=descriptor.source_path,
                    )
                )
                return None

        entry_path = descriptor.entry_path
        if entry_path is None or not entry_path.is_file():
            self._diagnostics.append(
                resource_diagnostic(
                    code="missing_extension_entry",
                    message="Extension descriptor does not point to a valid entry file.",
                    source_path=entry_path or descriptor.source_path,
                )
            )
            return None

        try:
            module = _load_extension_module(entry_path)
        except Exception as exc:
            self._diagnostics.append(
                resource_diagnostic(
                    code="extension_load_failed",
                    message=f"Failed to load extension module: {exc}",
                    source_path=entry_path,
                )
            )
            return None

        api = self._api_factory(
            name=descriptor.name,
            source_path=descriptor.source_path,
            entry_path=entry_path,
        )
        register = getattr(module, "register", None)
        if callable(register):
            try:
                loaded = _register_with_api(register, api, entry_path)
            except Exception as exc:
                self._diagnostics.append(
                    resource_diagnostic(
                        code="extension_load_failed",
                        message=f"Extension register(api) failed: {exc}",
                        source_path=entry_path,
                    )
                )
                return None
            if loaded is not None:
                return self._finalize_loaded_extension(
                    _with_descriptor_source_info(loaded, descriptor),
                    manifest=manifest,
                    enabled=descriptor.enabled,
                )
            return None

        builder = getattr(module, "build_extension", None)
        if callable(builder):
            try:
                extension_object = builder()
            except Exception as exc:
                self._diagnostics.append(
                    resource_diagnostic(
                        code="extension_load_failed",
                        message=f"Extension factory failed: {exc}",
                        source_path=entry_path,
                    )
                )
                return None
            if inspect.isawaitable(extension_object):
                self._diagnostics.append(
                    resource_diagnostic(
                        code="unsupported_async_extension_factory",
                        message="Async extension factories are not supported in v1.",
                        source_path=entry_path,
                    )
                )
                return None
            try:
                return self._finalize_loaded_extension(
                    _with_descriptor_source_info(
                        _adapt_legacy_extension_object(
                            descriptor=descriptor,
                            entry_path=entry_path,
                            extension_object=extension_object,
                            api_factory=self._api_factory,
                            legacy_event_names=self._legacy_event_names,
                        ),
                        descriptor,
                    ),
                    manifest=manifest,
                    enabled=descriptor.enabled,
                )
            except Exception as exc:
                self._diagnostics.append(
                    resource_diagnostic(
                        code="extension_load_failed",
                        message=f"Legacy build_extension() adaptation failed: {exc}",
                        source_path=entry_path,
                    )
                )
                return None

        if hasattr(module, "EXTENSION"):
            try:
                return self._finalize_loaded_extension(
                    _with_descriptor_source_info(
                        _adapt_legacy_extension_object(
                            descriptor=descriptor,
                            entry_path=entry_path,
                            extension_object=getattr(module, "EXTENSION"),
                            api_factory=self._api_factory,
                            legacy_event_names=self._legacy_event_names,
                        ),
                        descriptor,
                    ),
                    manifest=manifest,
                    enabled=descriptor.enabled,
                )
            except Exception as exc:
                self._diagnostics.append(
                    resource_diagnostic(
                        code="extension_load_failed",
                        message=f"Legacy EXTENSION adaptation failed: {exc}",
                        source_path=entry_path,
                    )
                )
                return None

        self._diagnostics.append(
            resource_diagnostic(
                code="invalid_extension_export",
                message="Extension modules must export register(api), build_extension(), or EXTENSION.",
                source_path=entry_path,
            )
        )
        return None

    def _finalize_loaded_extension(
        self,
        loaded: LoadedExtension,
        *,
        manifest: ExtensionManifest | None,
        enabled: bool,
    ) -> LoadedExtension:
        return _finalize_loaded_extension(
            loaded,
            manifest=manifest,
            enabled=enabled,
            policy_resolver=self._policy_resolver,
        )


def _register_with_api(
    register: object,
    api: ExtensionContributionAPI,
    entry_path: Path,
) -> LoadedExtension | None:
    if not callable(register):
        return None
    result = register(api)
    if inspect.isawaitable(result):
        raise TypeError(f"Async register(api) is not supported in v1: {entry_path}")
    return api.build_loaded_extension()


def _with_descriptor_source_info(
    loaded: LoadedExtension, descriptor: ExtensionDescriptor
) -> LoadedExtension:
    return replace(
        loaded,
        source=descriptor.source,
        source_kind=descriptor.source_kind,
        source_scope=descriptor.source_scope,
        source_root=descriptor.source_root,
    )


def _finalize_loaded_extension(
    loaded: LoadedExtension,
    *,
    manifest: ExtensionManifest | None,
    enabled: bool,
    policy_resolver: ExtensionPolicyResolver,
) -> LoadedExtension:
    extension_id = manifest.id if manifest is not None else loaded.name
    source_path = loaded.entry_path or loaded.source_path
    with_policy = replace(
        loaded,
        manifest=manifest,
        policy=policy_resolver(manifest, enabled),
        control_contributions=[
            replace(
                contribution,
                descriptor=replace(
                    contribution.descriptor,
                    extension_id=extension_id,
                    source_path=source_path,
                ),
            )
            for contribution in loaded.control_contributions
        ],
    )
    return replace(
        with_policy, contributions=list(surfaces_from_loaded_extension(with_policy))
    )


def _load_descriptor_manifest(descriptor: ExtensionDescriptor):
    manifest_path = _descriptor_manifest_path(descriptor)
    if manifest_path is None:
        return None, []
    result = parse_extension_manifest(manifest_path)
    return result.manifest, result.diagnostics


def _descriptor_manifest_path(descriptor: ExtensionDescriptor) -> Path | None:
    candidates: list[Path] = []
    if descriptor.source_path.is_dir():
        candidates.append(descriptor.source_path / "loushang-extension.toml")
    if descriptor.entry_path is not None:
        candidates.append(descriptor.entry_path.parent / "loushang-extension.toml")
    if descriptor.source_path.is_file():
        candidates.append(descriptor.source_path.with_name("loushang-extension.toml"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _adapt_legacy_extension_object(
    *,
    descriptor: ExtensionDescriptor,
    entry_path: Path,
    extension_object: object,
    api_factory: ExtensionApiFactory,
    legacy_event_names: tuple[str, ...],
) -> LoadedExtension:
    api = api_factory(
        name=descriptor.name,
        source_path=descriptor.source_path,
        entry_path=entry_path,
    )
    for event_name in legacy_event_names:
        handler = getattr(extension_object, event_name, None)
        if callable(handler):
            api.on(event_name, _wrap_legacy_handler(handler))

    get_tools = getattr(extension_object, "get_tools", None)
    if callable(get_tools):
        tools = get_tools()
        if inspect.isawaitable(tools):
            raise TypeError("Async get_tools() is not supported in v1.")
        for tool in list(tools or []):
            if not isinstance(tool, ToolDefinition):
                raise TypeError(
                    "Legacy get_tools() must return ToolDefinition objects in v1."
                )
            api.register_tool(tool)

    return api.build_loaded_extension()


def _wrap_legacy_handler(handler):
    def _wrapped(event, ctx):
        return handler(event)

    return _wrapped


def _load_extension_module(entry_path: Path):
    module_name = f"loushang_harness_extension_loader_{hashlib.sha1(str(entry_path).encode('utf-8')).hexdigest()}"
    spec = importlib.util.spec_from_file_location(module_name, entry_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for {entry_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _descriptor_activation_policy(
    manifest: ExtensionManifest | None,
    enabled: bool,
) -> ExtensionPolicyDecision:
    del manifest
    return ExtensionPolicyDecision(enabled=enabled)
