"""Shared Store receipt and completion rules over narrow native operations."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from .commit_records import PluginRevisionRefV1, VerifiedArtifactRefV1
from .staging import PackageArtifactStagingReceiptV1
from .store_settlements import (
    NativeIdentity,
    PackageStoreRole,
    PackageStoreSettlementJournal,
    PackageStoreSettlementJournalError,
)
from .tree_transfer import PackagePhysicalStagingError, PackageVerifiedTreeManifestV1

IdentityMap = dict[tuple[str, ...], NativeIdentity]
ObservedTree = tuple[NativeIdentity, IdentityMap, IdentityMap]


class PackageStorePinnedRootPort(Protocol):
    @property
    def identities(self) -> tuple[NativeIdentity, ...]: ...

    def validate_tree(
        self, final_name: str, manifest: PackageVerifiedTreeManifestV1,
    ) -> ObservedTree: ...


class PackageStorePlatformPort(Protocol):
    def pin_root(self) -> AbstractContextManager[PackageStorePinnedRootPort]: ...


def validate_receipt_at_root(
    root: PackageStorePinnedRootPort,
    receipt: PackageArtifactStagingReceiptV1,
    *,
    store_role: PackageStoreRole,
    store_identity: str,
    settlement_journal: PackageStoreSettlementJournal,
    read_only: bool,
) -> PackageArtifactStagingReceiptV1:
    """Use the original journal authority; native observations grant no rights."""
    stable_ref = receipt.stable_ref
    if (
        stable_ref.store_identity != store_identity
        or (
            store_role == "dependency"
            and not isinstance(stable_ref, VerifiedArtifactRefV1)
        )
        or (store_role == "root" and not isinstance(stable_ref, PluginRevisionRefV1))
    ):
        raise _collision()
    settlements_read = (
        settlement_journal.read_settlements_for_receipt
        if read_only
        else settlement_journal.settlements_for_receipt
    )
    settlements = settlements_read(
        store_role=store_role,
        store_identity=store_identity,
        root_identities=root.identities,
        receipt=receipt,
    )
    if not settlements:
        raise _collision()
    authority = settlements[0]
    tree_identity, directory_identities, file_identities = root.validate_tree(
        authority.final_name, authority.manifest,
    )
    authorizes_read = (
        settlement_journal.read_authorizes
        if read_only
        else settlement_journal.authorizes
    )
    if not authorizes_read(
        store_role=store_role,
        store_identity=store_identity,
        root_identities=root.identities,
        tree_identity=tree_identity,
        directory_identities=directory_identities,
        file_identities=file_identities,
        final_name=authority.final_name,
        staging_name=authority.staging_name,
        manifest=authority.manifest,
        receipt=receipt,
    ):
        raise _collision()
    return receipt


def _collision() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store settlement evidence does not authorize this tree",
        code="package_publication_collision",
    )


class PackageVerifiedTreeCompletionPort(Protocol):
    def observe_reused_tree(self) -> ObservedTree: ...

    def prepare_new_tree(self) -> ObservedTree: ...

    def publish_authorized_tree(self) -> None: ...

    def complete_and_close(self) -> None: ...


def finish_verified_tree(
    platform: PackageVerifiedTreeCompletionPort,
    *,
    store_role: PackageStoreRole,
    store_identity: str,
    root_identities: tuple[NativeIdentity, ...],
    final_name: str,
    staging_name: str,
    manifest: PackageVerifiedTreeManifestV1,
    receipt: PackageArtifactStagingReceiptV1,
    settlement_journal: PackageStoreSettlementJournal,
    reuse: bool,
    reuse_alias: bool,
    completed_entries: int,
    has_active_file: bool,
) -> PackageArtifactStagingReceiptV1:
    """Authorize before native publication; the original sink owns all flags."""
    if has_active_file or completed_entries != len(manifest.entries):
        raise PackagePhysicalStagingError(
            "Package Store received an incomplete verified tree",
            code="package_artifact_identity_changed",
        )
    try:
        if reuse:
            tree_identity, directory_identities, file_identities = (
                platform.observe_reused_tree()
            )
            exact = settlement_journal.authorizes(
                store_role=store_role,
                store_identity=store_identity,
                root_identities=root_identities,
                tree_identity=tree_identity,
                directory_identities=directory_identities,
                file_identities=file_identities,
                final_name=final_name,
                staging_name=staging_name,
                manifest=manifest,
                receipt=receipt,
            )
            if reuse_alias and not exact:
                if not settlement_journal.authorizes_dependency_reuse(
                    store_identity=store_identity,
                    root_identities=root_identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=final_name,
                    staging_name=staging_name,
                    manifest=manifest,
                    receipt=receipt,
                ):
                    raise _collision()
                settlement_journal.authorize(
                    store_role=store_role,
                    store_identity=store_identity,
                    root_identities=root_identities,
                    tree_identity=tree_identity,
                    directory_identities=directory_identities,
                    file_identities=file_identities,
                    final_name=final_name,
                    staging_name=staging_name,
                    manifest=manifest,
                    receipt=receipt,
                )
            elif not exact:
                raise PackagePhysicalStagingError(
                    "Package Store final identity lacks durable owner evidence",
                    code="package_publication_collision",
                )
        else:
            tree_identity, directory_identities, file_identities = (
                platform.prepare_new_tree()
            )
            settlement_journal.authorize(
                store_role=store_role,
                store_identity=store_identity,
                root_identities=root_identities,
                tree_identity=tree_identity,
                directory_identities=directory_identities,
                file_identities=file_identities,
                final_name=final_name,
                staging_name=staging_name,
                manifest=manifest,
                receipt=receipt,
            )
            platform.publish_authorized_tree()
    except PackagePhysicalStagingError:
        raise
    except PackageStoreSettlementJournalError:
        raise _root_untrusted() from None
    except Exception:
        raise _root_untrusted() from None
    platform.complete_and_close()
    return receipt


def _root_untrusted() -> PackagePhysicalStagingError:
    return PackagePhysicalStagingError(
        "Package Store root or owned staging identity changed",
        code="package_publication_root_untrusted",
    )
