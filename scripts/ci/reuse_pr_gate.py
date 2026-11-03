"""Reuse a successful same-tree, same-plan PR gate on its merge push only."""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ARTIFACT = "pr-quality-evidence"
EVIDENCE_FILE = "pr-quality-evidence.json"


def git_tree() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], text=True
    ).strip()


def comparable_plan(plan: dict) -> dict:
    # Diff filenames may differ between PR and merge push; execution must not.
    if not isinstance(plan, dict):
        raise ValueError("invalid evidence plan")
    return {key: value for key, value in plan.items() if key != "paths"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, repository: str, token: str):
        self.repository = repository
        self.token = token
        self.deadline = time.monotonic() + 30
        self.base = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    def request(self, path: str, *, archive: bool = False):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("PR evidence lookup budget exhausted")
        timeout = min(10, remaining)
        request = urllib.request.Request(
            f"{self.base}/repos/{self.repository}/{path}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
        )
        opener = urllib.request.build_opener(NoRedirect)
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if not archive or error.code != 302:
                raise
            location = error.headers["Location"]
            if not location.startswith("https://"):
                raise ValueError("artifact redirect must use HTTPS") from error
            # The storage download must not receive the GitHub access token.
            response = urllib.request.urlopen(location, timeout=timeout)
        with response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("oversized evidence response")
        return data if archive else json.loads(data)


def find_reusable_run(api, event: dict, current: dict, plan: dict, tree: str) -> int | None:
    if (event.get("ref") != "refs/heads/main"
            or event.get("deleted") or event.get("forced")
            or event.get("after") != current.get("head_sha")
            or current.get("event") != "push"):
        return None
    repository = api.repository
    after = event["after"]
    commit = api.request(f"git/commits/{after}")
    # A multi-PR push, squash, rebase, or direct push needs fresh validation.
    parents = commit.get("parents", [])
    if (len(parents) != 2 or parents[0]["sha"] != event.get("before")
            or commit.get("tree", {}).get("sha") != tree):
        return None
    for pr in api.request(f"commits/{after}/pulls?per_page=100"):
        if (not pr.get("merged_at") or pr.get("merge_commit_sha") != after
                or pr.get("base", {}).get("ref") != "main"
                or pr.get("base", {}).get("repo", {}).get("full_name") != repository
                or pr.get("head", {}).get("repo", {}).get("full_name") != repository
                or pr.get("head", {}).get("sha") != parents[1]["sha"]):
            continue
        head = pr["head"]["sha"]
        result = api.request(
            f"actions/workflows/{current['workflow_id']}/runs"
            f"?event=pull_request&head_sha={head}&per_page=100"
        )
        for run in result["workflow_runs"][:5]:
            if (run.get("status") != "completed" or run.get("conclusion") != "success"
                    or run.get("event") != "pull_request" or run.get("head_sha") != head
                    or run.get("workflow_id") != current["workflow_id"]
                    or run.get("head_repository", {}).get("full_name") != repository
                    ):
                continue
            artifacts = api.request(f"actions/runs/{run['id']}/artifacts?per_page=100")
            matches = [a for a in artifacts["artifacts"]
                       if a["name"] == ARTIFACT and not a.get("expired")]
            if len(matches) != 1:
                continue
            archive = api.request(f"actions/artifacts/{matches[0]['id']}/zip", archive=True)
            with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
                info = zipped.getinfo(EVIDENCE_FILE)
                if info.file_size > 200_000:
                    raise ValueError("oversized evidence document")
                evidence = json.loads(zipped.read(info))
            if not isinstance(evidence, dict):
                raise ValueError("invalid evidence document")
            if (evidence.get("version") == 1 and evidence.get("tree") == tree
                    and evidence.get("repository") == repository
                    and evidence.get("event") == "pull_request"
                    and evidence.get("pr_number") == pr["number"]
                    and evidence.get("run_id") == run["id"]
                    and evidence.get("run_attempt") == run.get("run_attempt")
                    and comparable_plan(evidence.get("plan", {})) == comparable_plan(plan)):
                return run["id"]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    plan = json.loads(os.environ["CI_PLAN"])
    repository = os.environ["GITHUB_REPOSITORY"]
    if args.record:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        pr_number = event.get("number")
        if type(pr_number) is not int or pr_number <= 0:
            raise ValueError("PR evidence requires a pull request number")
        Path(EVIDENCE_FILE).write_text(json.dumps({
            "version": 1, "tree": git_tree(), "plan": plan,
            "repository": repository, "event": os.environ["GITHUB_EVENT_NAME"],
            "pr_number": pr_number,
            "run_id": int(os.environ["GITHUB_RUN_ID"]),
            "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
        }), encoding="utf-8")
        return
    reusable = None
    if os.environ["GITHUB_EVENT_NAME"] == "push":
        try:
            api = GitHub(repository, os.environ["GH_TOKEN"])
            current = api.request(f"actions/runs/{os.environ['GITHUB_RUN_ID']}")
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            reusable = find_reusable_run(api, event, current, plan, git_tree())
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
            print(f"PR evidence unavailable ({type(error).__name__}); running selected checks")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"reused_run={reusable or ''}\n")
    message = (f"Reusing successful PR quality run {reusable}: identical tree and execution plan"
               if reusable else "No matching successful PR evidence; running selected checks")
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as output:
            output.write(message + "\n")


if __name__ == "__main__":
    main()
