"""First Product Goal policy: a fixed, bounded calculator repair task."""

from __future__ import annotations

import json
import os
import shlex
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from loushang.coding.adapters import _goal_driver as driver
from loushang.coding.adapters._verification_work import inspect_verification
from loushang.coding.adapters.harnesswork import (
    CODING_WORK_PROFILE,
    project_coding_runtime_event,
)
from loushang.harness.artifacts import SessionBlobRef, SessionBlobStore
from loushang.harnesswork import WorkRunSpec
from loushang.harnesswork.goal import (
    GoalAssessment,
    GoalBasis,
    GoalError,
    GoalFacts,
    PolicyStop,
    Requirement,
    WorkCandidate,
)
from loushang.harnesswork.goal.records import canonical, document, plain
from loushang.harnesswork.integrations.session import (
    PreparedSessionWorkTurn,
    SessionTurnExecutor,
    project_prepared_session_work_turns,
)
from loushang.harnesswork.ports import WorkExecutionBinding
from loushang.harnesswork.types import WorkOperation, WorkStepSpec
from loushang.method.loader import MethodLoader
from loushang.method.runtime import (
    MethodDomainProfile,
    MethodDomainRequest,
    MethodDomainRuntime,
    MethodPolicy,
)

POLICY_ID = "coding-calculator/v1"
REQUIREMENTS = (
    Requirement(
        "R-SUB", "Return the exact integer difference for all agreed subtract cases."
    ),
    Requirement(
        "R-CLAMP",
        "Clamp to the nearest endpoint or retain the value for all agreed cases.",
    ),
    Requirement(
        "R-FILES",
        "Change only calculator.py; preserve all other project paths, types and bytes.",
    ),
)
RESULT_KEYS = {
    "version",
    "identity",
    "input_bundle_sha256",
    "source_sha256",
    "tests_sha256",
    "driver_sha256",
    "results",
    "tests_run",
    "failures",
    "errors",
    "skipped",
}


def inventory(root: Path) -> dict[str, object]:
    """Complete bounded inventory, including directories; never follow links."""
    result: dict[str, object] = {}
    total = 0

    def visit(parent: Path, depth: int):
        nonlocal total
        if depth > 16:
            raise GoalError("project nesting exceeds calculator profile")
        with os.scandir(parent) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if len(result) >= 256:
                    raise GoalError("project inventory exceeds calculator profile")
                path = Path(entry.path)
                relative = path.relative_to(root).as_posix()
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    result[relative] = {"type": "directory"}
                    visit(path, depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    if info.st_size > 64 * 1024:
                        raise GoalError("project file exceeds calculator profile")
                    content = path.read_bytes()
                    total += len(content)
                    if total > 1024 * 1024:
                        raise GoalError("project bytes exceed calculator profile")
                    result[relative] = {
                        "type": "file",
                        "bytes": len(content),
                        "sha256": driver.digest(content),
                    }
                else:
                    raise GoalError(f"unsupported project entry: {relative}")

    visit(root, 0)
    entry = result.get("calculator.py")
    if not isinstance(entry, dict) or entry.get("type") != "file":
        raise GoalError("calculator.py must be a regular file")
    return result


def check_inventory(root: Path, baseline: Mapping[str, object]) -> dict[str, object]:
    current = inventory(root)
    if set(current) != set(baseline):
        raise GoalError("project paths changed outside source contract")
    for name, value in current.items():
        if name != "calculator.py" and value != plain(baseline[name]):
            raise GoalError(f"protected project entry changed: {name}")
    return current


def put(blobs: SessionBlobStore, content: bytes, name: str) -> Mapping[str, object]:
    ref = blobs.put_bytes(
        content,
        logical_name=f"goal/{name}",
        kind="coding-goal-input",
        media_type="application/octet-stream",
        source="coding-goal:trusted-input",
    )
    blobs.read_bytes(ref)
    return ref.manifest_entry()


class GoalEvidenceUnavailable(GoalError):
    def __init__(self, validity: str):
        super().__init__(f"required evidence is {validity}")
        self.validity = validity


def read(blobs: SessionBlobStore, value: object) -> bytes:
    if not isinstance(value, Mapping):
        raise GoalError("missing Goal Blob reference")
    ref = SessionBlobRef.from_manifest_entry(cast(Mapping[str, object], plain(value)))
    health = blobs.inspect([ref])[0]
    if health.state != "available":
        raise GoalEvidenceUnavailable(health.state)
    return blobs.read_bytes(ref)


def initial_metadata(root: Path, blobs: SessionBlobStore) -> Mapping[str, object]:
    baseline = inventory(root)
    tests = (root / "TESTS.json").read_bytes()
    driver.validate_tests(tests)
    driver.validate_source((root / "calculator.py").read_bytes())
    methods = MethodLoader().discover_methods(root)
    selected = [m for m in methods if m.name == "goal-calculator-repair"]
    if len(selected) != 1 or selected[0].source_path is None:
        raise GoalError("explicit goal-calculator-repair Method required")
    method = selected[0]
    assert method.source_path is not None
    method_path = Path(method.source_path).resolve().relative_to(root).as_posix()
    return {
        "profile": POLICY_ID,
        "baseline": baseline,
        "tests_ref": put(blobs, tests, "fixed-tests.json"),
        "driver_ref": put(blobs, Path(driver.__file__).read_bytes(), "fixed-driver.py"),
        "method_id": method.id,
        "method_path": method_path,
        "method_sha256": driver.digest((root / method_path).read_bytes()),
    }


class CalculatorPolicy:
    def __init__(
        self,
        *,
        workspace: Path,
        session: Any,
        blobs: SessionBlobStore,
        event_log: Any,
        prepared: dict[str, WorkExecutionBinding],
    ):
        self.root, self.session, self.blobs = workspace, session, blobs
        self.log, self.prepared = event_log, prepared

    def _current_inputs(self, basis: GoalBasis):
        meta = basis.goal.metadata
        if basis.goal.requirements != REQUIREMENTS or meta.get("profile") != POLICY_ID:
            raise GoalError("requirements need a supported domain acceptance mapping")
        snapshot = check_inventory(self.root, document(meta["baseline"]))
        tests = read(self.blobs, meta["tests_ref"])
        code = read(self.blobs, meta["driver_ref"])
        if (
            (self.root / "TESTS.json").read_bytes() != tests
            or Path(driver.__file__).read_bytes() != code
            or driver.digest((self.root / str(meta["method_path"])).read_bytes())
            != meta["method_sha256"]
        ):
            raise GoalError("fixed tests, driver or Method changed")
        source = (self.root / "calculator.py").read_bytes()
        driver.validate_source(source)
        driver.validate_tests(tests)
        return snapshot, source, tests, code

    def confirm_resume(
        self, basis: GoalBasis, work_facts: GoalFacts
    ) -> bool | PolicyStop:
        try:
            self._current_inputs(basis)
            if self.session.pending_message_count:
                return PolicyStop("pending_input")
            return True
        except (ValueError, OSError, KeyError) as error:
            return PolicyStop(f"resume_contract:{error}")

    async def prepare(
        self, basis: GoalBasis, work_facts: GoalFacts
    ) -> WorkCandidate | PolicyStop:
        self.prepared.clear()  # Resolver already consumed all accepted bindings.
        if self.session.pending_message_count:
            return PolicyStop("pending_input")
        try:
            snapshot, source, tests, code = self._current_inputs(basis)
        except (ValueError, OSError, KeyError) as error:
            return PolicyStop(str(error))
        batches = [
            b
            for b in work_facts.batches
            if b.goal_id == basis.goal.id and not b.not_submitted
        ]
        latest = batches[-1] if batches else None
        # Only a current failed validation can justify a repair. A changed source
        # or revised requirement first needs its own real validation evidence.
        repair = False
        previous = None
        if latest and latest.source.get("phase") == "verification":
            try:
                previous = self._verification(latest, basis, snapshot)
                repair = previous is not None and not all(
                    r["passed"] for r in previous["result"]["results"]
                )
            except (ValueError, OSError, KeyError):
                return PolicyStop("verification_evidence_unavailable")
        op_id = f"goal-op-{uuid4().hex}"
        common = {
            "inventory": snapshot,
            "method_sha256": basis.goal.metadata["method_sha256"],
        }
        if repair:
            request = (
                "Repair calculator.py using these actual current verification failures. "
                "Only calculator.py may change. Preserve exact function signatures. "
                "Use only parameter reads, bounded integer constants, +/-, comparisons, "
                "boolean conditions, if and return. No imports/calls/docstrings/annotations. "
                "Use read/edit/write tools only. Do not create files, change tests or Method.\n"
                + canonical(
                    {
                        "requirements": [
                            {"id": r.id, "text": r.text}
                            for r in basis.goal.requirements
                        ],
                        "revision": basis.goal.revision,
                        "epoch": basis.goal.epoch,
                        "evidence": previous,
                    }
                )
            )
            prepared = MethodDomainRuntime(
                profile=MethodDomainProfile(domain="coding")
            ).prepare_turns(
                MethodDomainRequest(
                    request,
                    self.root,
                    method_policy=MethodPolicy.explicit("goal-calculator-repair"),
                )
            )
            if not prepared or any(
                t.plan_mode != "fixed"
                or t.method_id != basis.goal.metadata["method_id"]
                for t in prepared
            ):
                return PolicyStop("unsupported Method or executor")
            if any(
                t.metadata.get("planned_constraint") or t.metadata.get("audit_policy")
                for t in prepared
            ):
                return PolicyStop(
                    "Method constraint/audit execution is unsupported by this profile"
                )
            turns = project_prepared_session_work_turns(
                cast(Sequence[PreparedSessionWorkTurn], prepared),
                images=None,
                follow_up_messages=(),
            )
            executor = SessionTurnExecutor(
                session=self.session,
                profile=CODING_WORK_PROFILE,
                project_event_facts=project_coding_runtime_event,
                turns=turns,
            )
            self.prepared[op_id] = WorkExecutionBinding(executor, executor)
            first = turns[0]
            operation = first.to_operation(
                profile=CODING_WORK_PROFILE,
                session_id=basis.header.session_id,
                operation_id=op_id,
            )
            initial = first.to_run_spec(profile=CODING_WORK_PROFILE, run_id=None)
            spec = WorkRunSpec(
                method_id=first.method_id,
                plan_id=first.plan_id,
                run_event_payload=initial.run_event_payload,
                scope_event_payload=initial.scope_event_payload,
                steps=tuple(t.to_step_spec(profile=CODING_WORK_PROFILE) for t in turns),
            )
            return WorkCandidate(basis, operation, spec, {**common, "phase": "repair"})
        identity = {
            "goal_id": basis.goal.id,
            "revision": basis.goal.revision,
            "epoch": basis.goal.epoch,
            "operation_id": op_id,
        }
        bundle = json.dumps(
            {
                "version": 1,
                "identity": identity,
                "source": driver.content_entry(source),
                "tests": driver.content_entry(tests),
                "driver_sha256": driver.digest(code),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        if len(bundle) > 64 * 1024:
            return PolicyStop("input bundle exceeds calculator profile")
        bundle_ref = put(self.blobs, bundle, f"{op_id}/input.json")
        source_ref = put(self.blobs, source, f"{op_id}/calculator.py")
        command = shlex.join(
            [
                str(Path(sys.executable).resolve()),
                "-I",
                "-S",
                str(Path(driver.__file__).resolve()),
            ]
        )
        operation = WorkOperation(
            op_id,
            "VerifyCodingCommand",
            basis.header.session_id,
            "coding",
            {
                "command": command,
                "execution": {
                    "stdin": bundle.decode(),
                    "cwd": str(self.root),
                    "env": [["PYTHONDONTWRITEBYTECODE", "1"]],
                },
            },
        )
        return WorkCandidate(
            basis,
            operation,
            WorkRunSpec(
                plan_id=f"verification:{op_id}",
                steps=(WorkStepSpec("report"), WorkStepSpec("validation")),
            ),
            {
                **common,
                "phase": "verification",
                "input_ref": bundle_ref,
                "source_ref": source_ref,
                "input_sha256": driver.digest(bundle),
            },
        )

    def confirm_candidate(self, candidate: WorkCandidate) -> bool:
        try:
            snapshot, _, _, _ = self._current_inputs(candidate.basis)
            return not self.session.pending_message_count and snapshot == plain(
                candidate.source["inventory"]
            )
        except (ValueError, OSError, KeyError):
            return False

    def _verification(self, batch, basis: GoalBasis, snapshot):
        if (
            batch.revision != basis.goal.revision
            or batch.epoch != basis.goal.epoch
            or batch.source.get("phase") != "verification"
            or plain(batch.source.get("inventory")) != snapshot
        ):
            return None
        if batch.run_receipt is None:
            raise GoalError("verification has no original association")
        view = inspect_verification(
            self.log.query(), run_id=batch.run_receipt, blobs=self.blobs
        )
        if view.issues or view.support and any(s.target is None for s in view.support):
            bad = {item.state for item in view.health if item.state != "available"}
            if bad:
                raise GoalEvidenceUnavailable(
                    "corrupt"
                    if "corrupt" in bad
                    else "missing"
                    if "missing" in bad
                    else "unknown"
                )
            raise GoalError(f"verification evidence unresolved:{view.issues}")
        if view.passed is None:
            raise GoalError("verification command result unknown")
        report_records = [r for r in view.records if r.role == "report"]
        if len(report_records) != 1:
            raise GoalError("verification report missing")
        report_ref = report_records[0].blob
        report = driver.strict_json(self.blobs.read_bytes(report_ref))
        outputs = [SessionBlobRef.from_manifest_entry(v) for v in report["outputs"]]
        if report["output_basis"] == "sdk-text-view":
            output = self.blobs.read_bytes(outputs[0])
        else:
            # Original retained references keep their stream logical names.
            stdout = [
                r
                for r in outputs
                if r.logical_name.endswith("stdout.txt") or "stdout" in r.logical_name
            ]
            if len(stdout) != 1:
                raise GoalError("verification stdout stream ambiguous")
            output = self.blobs.read_bytes(stdout[0])
        if len(output) > 64 * 1024:
            raise GoalError("verification result exceeds profile")
        result = driver.strict_json(output)
        bundle_bytes = read(self.blobs, batch.source["input_ref"])
        bundle = driver.strict_json(bundle_bytes)
        tests = driver.validate_tests(
            read(self.blobs, basis.goal.metadata["tests_ref"])
        )
        if (
            not isinstance(result, dict)
            or set(result) != RESULT_KEYS
            or type(result["version"]) is not int
            or result["version"] != 1
            or result["identity"]
            != {
                "goal_id": basis.goal.id,
                "revision": basis.goal.revision,
                "epoch": basis.goal.epoch,
                "operation_id": batch.operation_id,
            }
            or bundle["identity"] != result["identity"]
            or result["input_bundle_sha256"] != driver.digest(bundle_bytes)
            or result["input_bundle_sha256"] != batch.source["input_sha256"]
            or result["source_sha256"]
            != driver.digest(read(self.blobs, batch.source["source_ref"]))
            or result["source_sha256"] != snapshot["calculator.py"]["sha256"]
            or result["tests_sha256"]
            != driver.digest(read(self.blobs, basis.goal.metadata["tests_ref"]))
            or result["driver_sha256"]
            != driver.digest(read(self.blobs, basis.goal.metadata["driver_ref"]))
        ):
            raise GoalError("domain result identity/input mismatch")
        rows = result["results"]
        if (
            not isinstance(rows, list)
            or len(rows) != len(tests)
            or any(
                not isinstance(row, dict)
                or set(row) != {"id", "passed"}
                or type(row["passed"]) is not bool
                or type(row["id"]) is not str
                for row in rows
            )
            or len({row["id"] for row in rows}) != len(tests)
            or {row["id"] for row in rows} != {c["id"] for c in tests}
            or any(
                type(result[key]) is not int or result[key] < 0
                for key in ["tests_run", "failures", "errors", "skipped"]
            )
            or result["tests_run"] != len(tests)
            or result["skipped"] != 0
            or result["failures"] + result["errors"]
            != sum(not row["passed"] for row in rows)
            or view.passed != all(row["passed"] for row in rows)
        ):
            raise GoalError("domain test coverage/result mismatch")
        return {
            "result": result,
            "report_ref": report_ref.manifest_entry(),
            "input_ref": plain(batch.source["input_ref"]),
            "batch_id": batch.id,
            "operation_id": batch.operation_id,
        }

    async def assess(self, basis: GoalBasis, work_facts: GoalFacts) -> GoalAssessment:
        return self.assess_now(basis, work_facts)

    def assess_now(self, basis: GoalBasis, work_facts: GoalFacts) -> GoalAssessment:
        if self.session.pending_message_count:
            return GoalAssessment(basis, "needs_user", "pending_input")
        try:
            snapshot, _, _, _ = self._current_inputs(basis)
            batches = [
                b
                for b in work_facts.batches
                if b.goal_id == basis.goal.id and not b.not_submitted
            ]
            if not batches:
                return GoalAssessment(
                    basis, "more_evidence", "initial_verification_required"
                )
            latest = batches[-1]
            if latest.source.get("phase") != "verification":
                return GoalAssessment(
                    basis, "more_evidence", "verification_after_repair_required"
                )
            proof = self._verification(latest, basis, snapshot)
            if proof is None:
                return GoalAssessment(
                    basis, "more_evidence", "current_verification_required"
                )
            if not all(row["passed"] for row in proof["result"]["results"]):
                return GoalAssessment(
                    basis, "unmet", "actual_tests_failed", proof=proof
                )
            return GoalAssessment(
                basis,
                "satisfied",
                "fixed_tests_and_project_constraints_satisfied",
                tuple(r.id for r in basis.goal.requirements),
                (latest.operation_id,),
                {
                    **proof,
                    "inventory": snapshot,
                    "method_sha256": basis.goal.metadata["method_sha256"],
                },
            )
        except GoalEvidenceUnavailable as error:
            return GoalAssessment(
                basis, "needs_user", str(error), proof={"validity": error.validity}
            )
        except (ValueError, OSError, KeyError) as error:
            return GoalAssessment(basis, "needs_user", f"evidence_or_contract:{error}")

    def confirm_current(self, assessment: GoalAssessment) -> bool:
        try:
            snapshot, _, _, _ = self._current_inputs(assessment.basis)
            return not self.session.pending_message_count and snapshot == plain(
                assessment.proof["inventory"]
            )
        except (ValueError, OSError, KeyError):
            return False
