from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("reuse_pr_gate", ROOT / "scripts/ci/reuse_pr_gate.py")
reuse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reuse)


class FakeAPI:
    repository = "owner/repo"

    def __init__(self):
        self.event = {"ref": "refs/heads/main", "after": "merge", "before": "base"}
        self.current = {"id": 200, "head_sha": "merge", "workflow_id": 5, "event": "push"}
        self.plan = {"version": 1, "paths": ["new.py"], "workflows": {"e2e": True}}
        self.pr = {"number": 7, "merged_at": "today", "merge_commit_sha": "merge",
                   "base": {"ref": "main", "repo": {"full_name": self.repository}},
                   "head": {"sha": "head", "repo": {"full_name": self.repository}}}
        self.run = {"id": 100, "run_attempt": 1, "workflow_id": 5,
                    "event": "pull_request", "status": "completed", "conclusion": "success",
                    "head_sha": "head", "head_repository": {"full_name": self.repository},
                    "pull_requests": [{"number": 7}]}
        self.commit = {"parents": [{"sha": "base"}, {"sha": "head"}], "tree": {"sha": "tree"}}
        self.artifact = {"name": reuse.ARTIFACT, "id": 300, "expired": False}
        self.evidence = {"version": 1, "tree": "tree", "repository": self.repository,
                         "event": "pull_request", "pr_number": 7, "run_id": 100, "run_attempt": 1,
                         "plan": {**self.plan, "paths": ["old.py"]}}

    def request(self, path, *, archive=False):
        if archive:
            assert path == "actions/artifacts/300/zip"
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as zipped:
                zipped.writestr(reuse.EVIDENCE_FILE, json.dumps(self.evidence))
            return output.getvalue()
        if path.startswith("git/commits/"):
            return self.commit
        if path.startswith("commits/"):
            return [self.pr]
        if path.startswith("actions/workflows/"):
            return {"workflow_runs": [self.run]}
        if path.startswith("actions/runs/"):
            return {"artifacts": [self.artifact]}
        raise AssertionError(path)

    def find(self):
        return reuse.find_reusable_run(self, self.event, self.current, self.plan, "tree")


class EvidenceTests(unittest.TestCase):
    def test_successful_same_tree_and_execution_plan_reuses_run(self):
        self.assertEqual(FakeAPI().find(), 100)

    def test_merged_run_can_have_empty_pr_list_but_evidence_must_match_pr(self):
        api = FakeAPI()
        api.run["pull_requests"] = []
        self.assertEqual(api.find(), 100)
        api.evidence["pr_number"] = 8
        self.assertIsNone(api.find())

    def test_push_must_be_one_exact_pr_merge_into_main(self):
        for key, value in (("ref", "refs/heads/other"), ("after", "other"),
                           ("before", "older"), ("forced", True), ("deleted", True)):
            with self.subTest(key=key):
                api = FakeAPI()
                api.event[key] = value
                self.assertIsNone(api.find())
        for parents in ([], [{"sha": "base"}], [{"sha": "base"}, {"sha": "other"}]):
            api = FakeAPI()
            api.commit["parents"] = parents
            self.assertIsNone(api.find())
        api = FakeAPI()
        api.current["event"] = "workflow_dispatch"
        self.assertIsNone(api.find())

    def test_unmerged_unrelated_or_fork_pr_cannot_supply_evidence(self):
        for mutate in (
            lambda pr: pr.update(merged_at=None),
            lambda pr: pr.update(merge_commit_sha="other"),
            lambda pr: pr["head"].update(sha="other"),
            lambda pr: pr["head"]["repo"].update(full_name="fork/repo"),
            lambda pr: pr["base"].update(ref="other"),
            lambda pr: pr["base"]["repo"].update(full_name="other/repo"),
        ):
            api = FakeAPI()
            mutate(api.pr)
            self.assertIsNone(api.find())

    def test_failed_cancelled_running_or_different_workflow_is_not_reused(self):
        for key, value in (("conclusion", "failure"), ("conclusion", "cancelled"),
                           ("status", "in_progress"), ("event", "push"),
                           ("head_sha", "other"), ("workflow_id", 6),
                           ("id", 101),
                           ("head_repository", {"full_name": "fork/repo"})):
            with self.subTest(key=key, value=value):
                api = FakeAPI()
                api.run[key] = value
                self.assertIsNone(api.find())

    def test_tree_attempt_repository_and_all_plan_fields_must_match(self):
        for key, value in (("tree", "other"), ("run_attempt", 2), ("run_id", 101),
                           ("version", 2), ("event", "push"), ("repository", "fork/repo"),
                           ("pr_number", 8),
                           ("plan", {"version": 1, "workflows": {"e2e": False}})):
            with self.subTest(key=key):
                api = FakeAPI()
                api.evidence[key] = value
                self.assertIsNone(api.find())
        api = FakeAPI()
        api.commit["tree"]["sha"] = "other"
        self.assertIsNone(api.find())
        for key in ("unit_jobs", "windows", "e2e_interaction"):
            api = FakeAPI()
            api.plan = copy.deepcopy(api.plan)
            api.plan[key] = True
            self.assertIsNone(api.find())

    def test_cli_publishes_only_a_verified_matching_run(self):
        api = FakeAPI()
        with tempfile.TemporaryDirectory() as tmp:
            event_path = Path(tmp) / "event.json"
            event_path.write_text(json.dumps(api.event))
            output = Path(tmp) / "output"
            environment = {
                "CI_PLAN": json.dumps(api.plan), "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "200", "GH_TOKEN": "test",
                "GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(output),
                "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary"),
            }
            def request(path, **kwargs):
                return api.current if path == "actions/runs/200" else api.request(path, **kwargs)
            with (patch.dict(os.environ, environment), patch.object(sys, "argv", ["reuse"]),
                  patch.object(reuse.GitHub, "request", side_effect=request),
                  patch.object(reuse, "git_tree", return_value="tree"),
                  contextlib.redirect_stdout(io.StringIO())):
                reuse.main()
            self.assertEqual(output.read_text(), "reused_run=100\n")
            self.assertIn("100", (Path(tmp) / "summary").read_text())

    def test_record_keeps_actual_tree_run_attempt_and_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / reuse.EVIDENCE_FILE
            event_path = Path(tmp) / "event.json"
            event_path.write_text(json.dumps({"number": 7}))
            environment = {
                "CI_PLAN": json.dumps(FakeAPI().plan), "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_EVENT_NAME": "pull_request", "GITHUB_RUN_ID": "100",
                "GITHUB_RUN_ATTEMPT": "2", "GITHUB_EVENT_PATH": str(event_path),
            }
            original_path = Path
            def evidence_path(name):
                return destination if name == reuse.EVIDENCE_FILE else original_path(name)
            with (patch.dict(os.environ, environment),
                  patch.object(sys, "argv", ["reuse", "--record"]),
                  patch.object(reuse, "Path", side_effect=evidence_path),
                  patch.object(reuse, "git_tree", return_value="checked-out-tree")):
                reuse.main()
            evidence = json.loads(destination.read_text())
            self.assertEqual(evidence["tree"], "checked-out-tree")
            self.assertEqual(evidence["run_attempt"], 2)
            self.assertEqual(evidence["run_id"], 100)
            self.assertEqual(evidence["pr_number"], 7)
            self.assertEqual(evidence["plan"], FakeAPI().plan)

    def test_api_failure_falls_back_to_testing_and_records_no_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            environment = {
                "CI_PLAN": json.dumps(FakeAPI().plan), "GITHUB_REPOSITORY": "owner/repo",
                "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": "200", "GH_TOKEN": "test",
                "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary"),
            }
            with (patch.dict(os.environ, environment), patch.object(sys, "argv", ["reuse"]),
                  patch.object(reuse.GitHub, "request", side_effect=OSError("offline")),
                  contextlib.redirect_stdout(io.StringIO())):
                reuse.main()
            self.assertEqual(output.read_text(), "reused_run=\n")

    def test_pr_and_schedule_never_lookup_reuse(self):
        for event in ("pull_request", "schedule", "workflow_dispatch"):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "output"
                with (patch.dict(os.environ, {
                        "CI_PLAN": json.dumps(FakeAPI().plan), "GITHUB_REPOSITORY": "owner/repo",
                        "GITHUB_EVENT_NAME": event, "GITHUB_OUTPUT": str(output),
                        "GITHUB_STEP_SUMMARY": str(Path(tmp) / "summary"),
                    }), patch.object(sys, "argv", ["reuse"]),
                      patch.object(reuse.GitHub, "request") as request,
                      contextlib.redirect_stdout(io.StringIO())):
                    reuse.main()
                request.assert_not_called()
                self.assertEqual(output.read_text(), "reused_run=\n")

    def test_workflow_records_evidence_only_after_success_and_checks_all_reused_jobs(self):
        workflow = (ROOT / ".github/workflows/quality.yml").read_text()
        import re
        conditions = re.findall(r"    if: .*workflows\[", workflow)
        self.assertEqual(len(conditions), 15)
        self.assertTrue(all("needs.changes.outputs.reused_run == ''" in c for c in conditions))
        self.assertLess(workflow.index("--require-changes"), workflow.index("--record"))
        self.assertIn("CI_REUSED_RUN: ${{ needs.changes.outputs.reused_run }}", workflow)
        self.assertIn("if-no-files-found: error", workflow)
        self.assertIn("name: pr-quality-evidence\n          overwrite: true", workflow)

    def test_expired_or_missing_artifact_is_not_reused(self):
        for key, value in (("expired", True), ("name", "unrelated")):
            api = FakeAPI()
            api.artifact[key] = value
            self.assertIsNone(api.find())


if __name__ == "__main__":
    unittest.main()
