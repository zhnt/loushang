"""Product-owned Windows Worker receipt issuance for one selected Session."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeActivationError,
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackagePhysicalStagingError,
)
from loushang.harness.transcript.directory import AgentTranscriptDirectoryRuntime
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker._native_profile_bridge import (
    _plan_windows_lpac_product_worker_profile,
    _WindowsLpacProductWorkerProfilePlan,
)
from loushang.harness.worker.contracts import ManagedWorkerLaunchRequestV1
from loushang.harness.worker.product_activation import (
    ActivationWitness,
    ProductWorkerActivationPolicyV1,
    ProductWorkerActivationReceiptV1,
)
from loushang.hosting.windows_backend_material import (
    WINDOWS_LPAC_PLATFORM_IMPORTS,
    WindowsBackendMaterialExpectationV1,
)

from .package_product_worker_discovery import CodingWorkerTranscriptDiscoveryReader
from .package_product_worker_policy import (
    CodingWorkerOptInV1,
    CodingWorkerPolicySelectionError,
    derive_coding_selected_worker_policy,
)
from .package_product_worker_receipt import (
    CodingWorkerReceiptError,
    CodingWorkerReceiptRecordV1,
    CodingWorkerSelectedPayloadV1,
    CodingWorkerSessionDiscoveryReadPort,
)
from .package_product_worker_windows_installed_backend import (
    CodingWindowsWorkerInstalledBackendError,
    CodingWindowsWorkerInstalledBackendReader,
    read_coding_windows_worker_installed_backend_release,
)
from .package_product_worker_windows_opt_in_owner import (
    CodingWindowsWorkerProductOptInOwner,
)
from .package_product_worker_windows_receipt_journal import (
    CodingWindowsWorkerReceiptJournal,
)
from .session_manager import SessionManager

_STALE_WITNESS: ActivationWitness = ("0" * 64, "0" * 64, "stale", 0, 0)


class CodingWindowsWorkerProductReceiptOwner:
    """Join current Product selection, opt-in, and installed native closure."""

    def __init__(
        self,
        *,
        product: WindowsLocalWheelProductSessionOwner,
        runtime: PackageProductRuntimeBindingV1,
        selected: PackageProductSelectedPluginManifestV1,
        session_discovery_reader: CodingWorkerSessionDiscoveryReadPort | None = None,
    ) -> None:
        if (
            os.name != "nt"
            or type(product) is not WindowsLocalWheelProductSessionOwner
            or type(runtime) is not PackageProductRuntimeBindingV1
            or type(selected) is not PackageProductSelectedPluginManifestV1
            or product.policy.product_id != "coding"
            or runtime.product_id != "coding"
            or runtime.session_id is None
            or runtime.product_runtime_id is None
            or selected.snapshot.installation_key.scope_id
            != product.policy.project_scope_id
            or (
                session_discovery_reader is not None
                and (
                    getattr(session_discovery_reader, "gc_gate", None)
                    is not product.gc_gate
                    or getattr(session_discovery_reader, "session_id", None)
                    != runtime.session_id
                    or not callable(
                        getattr(session_discovery_reader, "current_discovery", None)
                    )
                )
            )
            or not any(
                binding.source_trust_class == "local-worker-candidate"
                for binding in product.policy.bindings
            )
        ):
            raise ValueError("Windows Worker Product receipt owners changed")
        product.assert_session_runtime_current(runtime)
        runtime.assert_selected_plugin_manifest_current(selected)
        self._product = product
        self._runtime = runtime
        self._selected = selected
        self._opt_in = CodingWindowsWorkerProductOptInOwner(product)
        self._native = CodingWindowsWorkerInstalledBackendReader(product)
        self._session_discovery_reader = session_discovery_reader
        self._journal = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        )

    @property
    def product_owner(self) -> WindowsLocalWheelProductSessionOwner:
        return self._product

    def issue(self) -> ProductWorkerActivationReceiptV1 | None:
        """Return Current on absent opt-in, otherwise persist exact authority."""

        with self._product.gc_gate.guard():
            self._product.assert_session_runtime_current(self._runtime)
            self._runtime.assert_selected_plugin_manifest_current(self._selected)
            decision = self._opt_in.current(
                self._selected.snapshot.installation_key.plugin_id
            )
            if decision is None or decision.action != "allow":
                return None
            policy = self._derive(decision.opt_in)
            if policy is None:
                return None
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                receipt = self._journal.issue(
                    directory_fd=root,
                    policy=policy,
                    opt_in_decision_digest=decision.decision_digest,
                )
            self._product.assert_session_runtime_current(self._runtime)
            return receipt

    @contextmanager
    def serialized_admission(self) -> Iterator[None]:
        """Hold Product selection and GC through the first Worker effect."""

        with self._product.gc_gate.guard():
            self._product.assert_session_runtime_current(self._runtime)
            yield

    def current_witness(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> ActivationWitness:
        """Refuse fabricated, replaced, revoked, or stale Product receipts."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or receipt.policy.session_id != self._runtime.session_id
                or receipt.policy.product_runtime_id != self._runtime.product_runtime_id
                or receipt.policy.plugin_id
                != self._selected.snapshot.installation_key.plugin_id
            ):
                return _STALE_WITNESS
            self._product.assert_session_runtime_current(self._runtime)
            with (
                self._product.epoch_runtime.borrow_product_state_root_descriptor() as root
            ):
                records = self._journal.records(directory_fd=root)
            record = self._latest(records, receipt.policy)
            if record is None or record.receipt != receipt:
                return _STALE_WITNESS
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or decision.decision_digest != record.opt_in_decision_digest
            ):
                return _STALE_WITNESS
            try:
                policy = self._derive(decision.opt_in)
            except (
                CodingWorkerPolicySelectionError,
                CodingWorkerReceiptError,
                CodingWindowsWorkerInstalledBackendError,
                PackageProductRuntimeActivationError,
                PackageProductRuntimeReadError,
                OSError,
                ValueError,
            ):
                return _STALE_WITNESS
            if policy is None or policy.fingerprint != receipt.policy.fingerprint:
                return _STALE_WITNESS
            return receipt.authority_witness

    def current_backend_capture_expectation(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> WindowsBackendMaterialExpectationV1:
        """Derive Hosting's expectation only from a current Product receipt."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            material = read_coding_windows_worker_installed_backend_release(
                self._product
            )
            closure = material.native_closure()
            if (
                closure.native_profile_catalog_revision
                != receipt.policy.native_profile_catalog_revision
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            return material.expectation

    def current_selected_manifest(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1:
        """Reread exactly the selected Store revision under Product custody."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            return self._capture_selected_manifest_under_gc_guard(receipt)

    def _capture_selected_manifest_under_gc_guard(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> PackageProductSelectedPluginManifestV1:
        """Capture the selected root after the caller has checked the receipt."""

        try:
            selected = self._runtime.capture_selected_plugin_manifest_for(
                receipt.policy.plugin_id,
                max_files=64,
                max_total_bytes=16 * 1024 * 1024,
            )
        except (
            PackagePhysicalStagingError,
            PackageProductRuntimeActivationError,
            PackageProductRuntimeReadError,
        ) as exc:
            raise CodingWorkerReceiptError("coding_worker_selected_payload_stale") from exc
        if selected != self._selected:
            raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
        return selected

    @staticmethod
    def _payload_from_selected(
        receipt: ProductWorkerActivationReceiptV1,
        selected: PackageProductSelectedPluginManifestV1,
    ) -> CodingWorkerSelectedPayloadV1:
        candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=receipt.policy.contribution_id,
            native_platform="windows-amd64",
        )
        manifest = selected.verified_manifest()
        configuration = manifest.contribution_index.items[0].worker_configuration
        assert configuration is not None
        root = manifest.root_relative_path.as_posix()
        prefix = "" if root == "." else f"{root}/"
        body = dict(selected.snapshot.files).get(
            f"{prefix}{configuration.entrypoint}"
        )
        if (
            body is None
            or candidate.executable_digest != sha256(body).hexdigest()
            or candidate.worker_configuration_fingerprint
            != receipt.policy.worker_configuration_fingerprint
            or selected.snapshot.root_ref.artifact_digest
            != receipt.policy.plugin_revision_digest
        ):
            raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
        return CodingWorkerSelectedPayloadV1(
            configuration=configuration,
            body=body,
            digest=candidate.executable_digest,
        )

    def current_selected_payload(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> CodingWorkerSelectedPayloadV1:
        """Read verified Windows PE bytes from the current Product selection."""

        with self._product.gc_gate.guard():
            self.current_backend_capture_expectation(receipt)
            selected = self.current_selected_manifest(receipt)
            payload = self._payload_from_selected(receipt, selected)
            if self.current_witness(receipt) != receipt.authority_witness:
                raise CodingWorkerReceiptError("coding_worker_selected_payload_stale")
            return payload

    def current_payload_and_worker_owner_id(
        self, receipt: ProductWorkerActivationReceiptV1
    ) -> tuple[CodingWorkerSelectedPayloadV1, str]:
        """Capture payload and owner in one Product read with two full rechecks.

        Each witness verifies the complete installed backend. The selected
        root is captured between them; the final witness rechecks receipt and
        opt-in authority before either value is returned.
        """

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            selected = self._capture_selected_manifest_under_gc_guard(receipt)
            payload = self._payload_from_selected(receipt, selected)
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or not isinstance(decision.opt_in, CodingWorkerOptInV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            return payload, decision.opt_in.owner_id

    def current_worker_owner_id(self, receipt: ProductWorkerActivationReceiptV1) -> str:
        """Resolve the operator-approved domain owner from current Product state."""

        with self._product.gc_gate.guard():
            if (
                not isinstance(receipt, ProductWorkerActivationReceiptV1)
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            decision = self._opt_in.current(receipt.policy.plugin_id)
            if (
                decision is None
                or decision.action != "allow"
                or not isinstance(decision.opt_in, CodingWorkerOptInV1)
            ):
                raise CodingWorkerReceiptError("coding_worker_receipt_stale")
            return decision.opt_in.owner_id

    def plan_current_native_attempt(
        self,
        receipt: ProductWorkerActivationReceiptV1,
        worker_request: ManagedWorkerLaunchRequestV1,
    ) -> _WindowsLpacProductWorkerProfilePlan:
        """Build one LPAC plan from Product facts, including Hosting recheck."""

        if not isinstance(worker_request, ManagedWorkerLaunchRequestV1):
            raise TypeError("Windows Worker native request is invalid")
        with self._product.gc_gate.guard():
            expectation = self.current_backend_capture_expectation(receipt)
            candidate = verify_product_selected_worker_candidate(
                self._selected,
                contribution_id=receipt.policy.contribution_id,
                native_platform="windows-amd64",
            )
            identity = worker_request.identity
            if (
                identity.product_id != "coding"
                or identity.scope_id != receipt.policy.product_scope_id
                or identity.plugin_id != receipt.policy.plugin_id
                or identity.plugin_revision_digest
                != receipt.policy.plugin_revision_digest
                or identity.contribution_id != receipt.policy.contribution_id
                or identity.owner_generation
                != receipt.policy.owner_selection_generation
                or worker_request.runtime.executable_digest
                != candidate.executable_digest
            ):
                raise CodingWorkerReceiptError("coding_worker_native_request_stale")
            material = read_coding_windows_worker_installed_backend_release(
                self._product
            )
            if worker_request.runtime.package_root.parent != self._product.state_root:
                raise CodingWorkerReceiptError("coding_worker_native_payload_root_changed")
            plan = _plan_windows_lpac_product_worker_profile(
                worker_request=worker_request,
                native_profile_catalog_revision=(
                    receipt.policy.native_profile_catalog_revision
                ),
                containment_launcher_sha256=(material.review.approval.launcher_sha256),
                platform_imports=WINDOWS_LPAC_PLATFORM_IMPORTS,
                backend_material_expectation=expectation,
                release_profile_sha256=material.review.approval.profile_sha256,
                owner_private_ancestors=True,
            )
            if (
                plan.expected_native_policy_closure_fingerprint
                != receipt.policy.expected_native_policy_closure_fingerprint
                or self.current_witness(receipt) != receipt.authority_witness
            ):
                raise CodingWorkerReceiptError("coding_worker_native_plan_stale")
            return plan

    def _derive(self, opt_in: object) -> ProductWorkerActivationPolicyV1 | None:
        if not isinstance(opt_in, CodingWorkerOptInV1):
            return None
        session_id = self._runtime.session_id
        runtime_id = self._runtime.product_runtime_id
        assert session_id is not None and runtime_id is not None
        session_discovery = (
            None
            if self._session_discovery_reader is None
            else self._session_discovery_reader.current_discovery()
        )
        if self._session_discovery_reader is not None and not isinstance(
            session_discovery, SessionDiscoveryMetadata
        ):
            raise CodingWorkerReceiptError("coding_worker_session_discovery_invalid")
        return derive_coding_selected_worker_policy(
            runtime=self._runtime,
            product_policy=self._product.policy,
            selected=self._selected,
            session_id=session_id,
            product_runtime_id=runtime_id,
            opt_in=opt_in,
            native_closure=self._native.current_closure(),
            session_discovery=session_discovery,
        )

    @staticmethod
    def _latest(
        records: tuple[CodingWorkerReceiptRecordV1, ...],
        policy: ProductWorkerActivationPolicyV1,
    ) -> CodingWorkerReceiptRecordV1 | None:
        return next(
            (
                record
                for record in reversed(records)
                if record.receipt.policy.session_id == policy.session_id
                and record.receipt.policy.plugin_id == policy.plugin_id
            ),
            None,
        )


def open_coding_windows_product_selected_worker_receipt_owner(
    *,
    product_owner: WindowsLocalWheelProductSessionOwner,
    runtime: PackageProductRuntimeBindingV1,
    plugin_id: str,
    transcript_directory: AgentTranscriptDirectoryRuntime,
    session_manager: SessionManager,
) -> CodingWindowsWorkerProductReceiptOwner:
    """Bind an exact selected Windows Worker to its persisted Coding Session."""

    if type(product_owner) is not WindowsLocalWheelProductSessionOwner:
        raise TypeError("Windows Worker requires a Product owner")
    if type(runtime) is not PackageProductRuntimeBindingV1:
        raise TypeError("Windows Worker requires an active Product runtime")
    if not isinstance(plugin_id, str) or not plugin_id or plugin_id != plugin_id.strip():
        raise ValueError("Windows Worker Plugin identity is invalid")
    if not isinstance(transcript_directory, AgentTranscriptDirectoryRuntime):
        raise TypeError("Windows Worker requires a Transcript directory owner")
    if not isinstance(session_manager, SessionManager):
        raise TypeError("Windows Worker requires a Coding Session owner")
    selected_session_file = session_manager.get_session_file()
    if (
        not session_manager.is_persisted()
        or selected_session_file is None
        or session_manager.get_header().conversation_id != runtime.session_id
        or Path(session_manager.get_cwd()).resolve(strict=True)
        != product_owner.workspace
        or not (
            transcript_directory.is_authority_session_file(selected_session_file)
            or transcript_directory.is_discovery_session_file(selected_session_file)
        )
    ):
        raise ValueError("Windows Worker selected Session owner changed")
    product_owner.assert_session_runtime_current(runtime)
    selected = runtime.capture_selected_plugin_manifest_for(
        plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
    )
    discovery = CodingWorkerTranscriptDiscoveryReader(
        directory=transcript_directory,
        gc_gate=product_owner.gc_gate,
        session_id=runtime.session_id,
        selected_session_file=selected_session_file,
    )
    return CodingWindowsWorkerProductReceiptOwner(
        product=product_owner,
        runtime=runtime,
        selected=selected,
        session_discovery_reader=discovery,
    )


def read_coding_windows_product_worker_receipt_record(
    product: WindowsLocalWheelProductSessionOwner, *, receipt_fingerprint: str
) -> CodingWorkerReceiptRecordV1 | None:
    """Read an exact persisted Product receipt without a Session runtime."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or type(receipt_fingerprint) is not str
        or len(receipt_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in receipt_fingerprint)
    ):
        raise ValueError("Windows Worker receipt lookup is invalid")
    with product.gc_gate.guard():
        product.assert_root_gc_authority_current()
        journal = CodingWindowsWorkerReceiptJournal(
            product.state_root / "worker-activation-receipts.jsonl",
            scope_id=product.policy.project_scope_id,
        )
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            records = journal.records(directory_fd=root)
        return next(
            (
                record
                for record in records
                if record.receipt.fingerprint == receipt_fingerprint
            ),
            None,
        )


__all__ = [
    "CodingWindowsWorkerProductReceiptOwner",
    "open_coding_windows_product_selected_worker_receipt_owner",
    "read_coding_windows_product_worker_receipt_record",
]
