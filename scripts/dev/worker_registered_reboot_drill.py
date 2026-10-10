"""Two-phase physical reboot drill for a registered, pre-effect Coding Worker.

Run both phases from the same source checkout on an isolated Linux machine.
The script never reboots the machine. Its fixture uses the native Product test
helper, then the recovery phase uses the production Product owners without a
boot-ID patch. Keep ``--root`` on storage that survives the OS reboot.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from secrets import token_hex

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))

from loushang.coding._plugin_lifecycle import (  # noqa: E402
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_runtime import (  # noqa: E402
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_payload import (  # noqa: E402
    open_coding_product_worker_supervisor_journal,
)
from loushang.coding.package_product_worker_posix_gc_history import (  # noqa: E402
    CodingPosixWorkerGcHistoryAuthority,
)
from loushang.coding.package_product_worker_registered_recovery import (  # noqa: E402
    recover_coding_product_worker_registered_no_effect,
    review_coding_product_worker_registered_orphan,
)
from loushang.coding.package_product_worker_start_gate_journal import (  # noqa: E402
    CodingWorkerStartGateJournal,
)
from loushang.harness.package_product.product_root_gc_runtime import (  # noqa: E402
    open_posix_local_wheel_product_root_gc,
)

_MANIFEST = "registered-worker-reboot-drill.json"
_RESULT = "registered-worker-reboot-result.json"


def _boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(
        encoding="ascii"
    ).strip()


def _write_durable(path: Path, record: dict[str, object]) -> None:
    raw = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name("." + path.name + ".tmp." + token_hex(8))
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _open_product(workspace: Path):
    return open_coding_fenced_product_application_owner(
        resolve_coding_plugin_lifecycle_state_layout(workspace),
        workspace=workspace,
        runtime_version="2.0.0",
        runtime_protocol_epoch=2,
        worker_candidates=True,
    )


def _prepare(root: Path) -> dict[str, object]:
    import pytest

    from tests.coding.test_package_worker_candidate_wheel import (
        test_worker_source_catalog_pins_explicit_product_candidate,
    )
    root.mkdir(mode=0o700)
    workspace = root / "workspace"
    with pytest.MonkeyPatch.context() as monkeypatch:
        test_worker_source_catalog_pins_explicit_product_candidate(
            root,
            "installed-protocol",
            monkeypatch,
            direct_entry_only=True,
            stop_after_worker_allow=True,
        )
        owner = _open_product(workspace)
        try:
            prior_ids = {
                record.attempt_id
                for record in CodingWorkerStartGateJournal(
                    owner.runtime_owner.product_owner
                ).attempts()
            }
        finally:
            owner.close()
        boot_id = _boot_id()
        child = subprocess.run(
            (
                sys.executable,
                "-c",
                "from tests.coding.test_package_worker_candidate_wheel "
                "import _run_independent_registered_worker_crash; "
                "import sys; "
                "_run_independent_registered_worker_crash(*sys.argv[1:])",
                str(workspace),
                str(root / "registered-worker-transcripts"),
            ),
            cwd=REPO_ROOT,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
        if child.returncode != 0:
            raise RuntimeError(
                f"registered Worker fixture failed ({child.returncode}): "
                + child.stderr.decode(errors="replace")
            )
        if _boot_id() != boot_id:
            raise RuntimeError("OS boot changed while preparing the drill")
        owner = _open_product(workspace)
        try:
            product = owner.runtime_owner.product_owner
            gates = tuple(
                record
                for record in CodingWorkerStartGateJournal(product).attempts()
                if record.attempt_id not in prior_ids
            )
            if len(gates) != 1:
                raise RuntimeError("expected one newly registered Worker start gate")
            (gate,) = gates
            review = review_coding_product_worker_registered_orphan(
                product, attempt_id=gate.attempt_id
            )
            if (
                gate.phase != "intent"
                or gate.identity is not None
                or review.activation_attempt is None
                or review.activation_attempt.phase != "registered"
                or review.orphan_lease is None
                or review.repair_candidate
                or open_coding_product_worker_supervisor_journal(product).status(
                    gate.attempt_id
                )
                is not None
            ):
                raise RuntimeError("registered pre-effect fixture is not exact")
            manifest: dict[str, object] = {
                "schemaVersion": 1,
                "bootIdBefore": boot_id,
                "attemptId": gate.attempt_id,
                "storeId": product.epoch_runtime.registry.store_id,
                "workspace": str(workspace),
                "stateRoot": str(product.state_root),
            }
        finally:
            owner.close()
    _write_durable(root / _MANIFEST, manifest)
    return manifest


def _recover(root: Path) -> dict[str, object]:
    manifest = json.loads((root / _MANIFEST).read_text(encoding="utf-8"))
    if type(manifest) is not dict or manifest.get("schemaVersion") != 1:
        raise RuntimeError("registered Worker reboot manifest is invalid")
    workspace = root / "workspace"
    if manifest.get("workspace") != str(workspace):
        raise RuntimeError("registered Worker reboot workspace changed")
    boot_id_after = _boot_id()
    if boot_id_after == manifest.get("bootIdBefore"):
        raise RuntimeError("OS boot identity is unchanged; physical reboot is unproven")
    os.environ["LOUSHANG_HOME"] = str(root / "private-home")
    attempt_id = manifest.get("attemptId")
    if type(attempt_id) is not str:
        raise RuntimeError("registered Worker reboot attempt is invalid")
    owner = _open_product(workspace)
    try:
        product = owner.runtime_owner.product_owner
        if (
            product.epoch_runtime.registry.store_id != manifest.get("storeId")
            or str(product.state_root) != manifest.get("stateRoot")
        ):
            raise RuntimeError("registered Worker Product state changed across reboot")
        review = review_coding_product_worker_registered_orphan(
            product, attempt_id=attempt_id
        )
        if not review.repair_candidate or review.orphan_lease is None:
            raise RuntimeError("registered Worker orphan is not repairable after reboot")
        settled = recover_coding_product_worker_registered_no_effect(
            product, attempt_id=attempt_id
        )
        if settled.phase != "settled" or not settled.no_effect:
            raise RuntimeError("registered Worker did not settle as noEffect")
        open_posix_local_wheel_product_root_gc(
            product,
            worker_history_authority=CodingPosixWorkerGcHistoryAuthority(product),
        ).prepare()
    finally:
        owner.close()
    owner = _open_product(workspace)
    try:
        reopened = recover_coding_product_worker_registered_no_effect(
            owner.runtime_owner.product_owner, attempt_id=attempt_id
        )
        if reopened != settled:
            raise RuntimeError("registered Worker recovery did not reopen idempotently")
    finally:
        owner.close()
    result: dict[str, object] = {
        "schemaVersion": 1,
        "bootIdBefore": manifest["bootIdBefore"],
        "bootIdAfter": boot_id_after,
        "attemptId": attempt_id,
        "storeId": manifest["storeId"],
        "phase": settled.phase,
        "noEffect": settled.no_effect,
        "gcPrepare": "passed",
        "reopen": "idempotent",
    }
    _write_durable(root / _RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("prepare", "recover"))
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "linux":
        raise RuntimeError("registered Worker reboot drill requires Linux")
    root = args.root.expanduser().resolve(strict=False)
    result = _prepare(root) if args.phase == "prepare" else _recover(root)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
