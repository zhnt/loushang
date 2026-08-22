"""Host-owned Plugin declaration decoding and aggregate finalization."""

from __future__ import annotations

from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
)
from loushang.harness.resources.plugins.revisions import VerifiedRevisionHandle
from loushang.harness.resources.plugins.selection import (
    AcceptedPluginPreflight,
    PluginDeclarationBatch,
    PluginDeclarationDataOnlyGate,
    PluginDeclarationSourceGroup,
    PluginSelection,
    PluginSelectionError,
    PluginSelectionResolver,
)


class PluginDeclarationCoordinator:
    """Consume one accepted preflight through its sole terminal owner."""

    def __init__(self, resolver: PluginSelectionResolver) -> None:
        if not isinstance(resolver, PluginSelectionResolver):
            raise TypeError("Plugin declaration Coordinator requires a Resolver")
        self._resolver = resolver

    def finalize(self, accepted: AcceptedPluginPreflight) -> PluginSelection:
        if not isinstance(accepted, AcceptedPluginPreflight):
            raise TypeError("Plugin declaration Coordinator requires accepted preflight")
        self._resolver._peek_active(accepted)
        if any(
            not isinstance(group.gate, PluginDeclarationDataOnlyGate)
            for group in accepted.source_groups
        ):
            self._resolver._abort(accepted)
            raise PluginSelectionError(
                "Executable Plugin declaration was not consumed by an evaluator.",
                code="execution_not_consumed",
            )

        try:
            batches = tuple(
                self._decode_document_group(group)
                for group in accepted.source_groups
            )
            return self._resolver._finalize(accepted, batches)
        except BaseException:
            self._abort_after_failure(accepted)
            raise

    @staticmethod
    def _decode_document_group(
        group: PluginDeclarationSourceGroup,
    ) -> PluginDeclarationBatch:
        if not isinstance(group, PluginDeclarationSourceGroup):
            raise TypeError("Plugin declaration Coordinator received an invalid group")
        document = PluginDeclarationCoordinator._read_and_decode_document(
            group.package.revision_handle,
            group.declaration_source.relative_path.as_posix(),
        )
        encoded = PluginDeclarationDocumentCodec.encode_bytes(document)
        return PluginDeclarationBatch._from_document_decoded(
            group,
            document,
            encoded,
        )

    @staticmethod
    def _read_and_decode_document(
        handle: VerifiedRevisionHandle,
        locator: str,
    ) -> PluginDeclarationDocument:
        with handle.open_file(locator) as stream:
            verified_bytes = stream.read()
        return PluginDeclarationDocumentCodec.decode_bytes(verified_bytes)

    def _abort_after_failure(self, accepted: AcceptedPluginPreflight) -> None:
        try:
            self._resolver._abort(accepted)
        except PluginSelectionError as exc:
            if exc.code not in {"plugin_preflight_consumed", "preflight_expired"}:
                raise


__all__ = ["PluginDeclarationCoordinator"]
