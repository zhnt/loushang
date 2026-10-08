from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.plugin_author_smoke import main as smoke_cli_main
from loushang.plugin import (
    write_coding_data_prompt_wheel,
    write_coding_data_skill_wheel,
)
from loushang.plugin.__main__ import main as plugin_cli_main
from loushang.plugin._coding_local_worker_wheel import (
    write_coding_local_worker_candidate_wheel,
)


@pytest.mark.requires_host_runtime
@pytest.mark.skipif(sys.platform != "linux", reason="Linux Worker candidate smoke")
def test_author_worker_smoke_proves_admission_and_selection_without_use(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    compiler = shutil.which("cc")
    assert compiler is not None
    source = tmp_path / "candidate.c"
    source.write_text("int main(void) { return 42; }\n", encoding="ascii")
    executable = tmp_path / "query-worker"
    built = subprocess.run(
        (
            compiler, "-static", "-O2", "-s", "-o", str(executable),
            str(source),
        ),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheel = write_coding_local_worker_candidate_wheel(
        tmp_path,
        plugin_id="reviewworker",
        version="1",
        contribution_id="query-provider",
        owner_id="coding",
        native_platform="linux-x86_64",
        wheel_tag="py3-none-manylinux_2_17_x86_64",
        executable=executable.read_bytes(),
    )
    assert smoke_cli_main(
        [
            str(wheel), "--kind", "worker", "--plugin-id", "reviewworker",
            "--contribution-id", "query-provider", "--owner-id", "coding",
        ]
    ) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["artifactSha256"] == sha256(wheel.read_bytes()).hexdigest()
    assert report["productAdmission"] == "passed"
    assert report["productSelection"] == "passed"
    assert report["selectedPluginVersion"] == "1"
    assert report["nativeRelease"] == "not_checked"
    assert report["productUse"] == "not_checked"
    assert report["workspace"] == "disposable"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux Worker candidate smoke")
def test_author_worker_smoke_does_not_claim_selection_after_bad_wheel(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    wheel = tmp_path / "reviewworker-1-py3-none-manylinux_2_17_x86_64.whl"
    wheel.write_bytes(b"not a Worker Wheel")
    assert smoke_cli_main(
        [
            str(wheel), "--kind", "worker", "--plugin-id", "reviewworker",
            "--contribution-id", "query-provider", "--owner-id", "coding",
        ]
    ) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["productAdmission"] == "failed"
    assert report["productSelection"] == "not_checked"
    assert report["productUse"] == "not_checked"


@pytest.mark.skipif(os.name != "posix", reason="ordinary data Product path is POSIX")
@pytest.mark.parametrize("kind", ["skill", "prompt"])
def test_author_smoke_proves_product_selection_and_prepared_model_input(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    document = (
        b"---\r\nname: review\r\ndescription: Review a change.\r\n---\r\n"
        b"# Review\r\nCheck the exact author smoke marker 8bc2.\r\n"
        if kind == "skill"
        else (
            b"---\nname: review\ndescription: Review a change.\n---\n"
            b"# Review\nCheck the exact author smoke marker 8bc2 and $ARGUMENTS / $1.\n"
        )
    )
    if kind == "skill":
        wheel = write_coding_data_skill_wheel(
            tmp_path,
            plugin_id="reviewpack",
            version="1",
            contribution_id="review-skill",
            skill_name="review",
            skill_document=document,
        )
    else:
        wheel = write_coding_data_prompt_wheel(
            tmp_path,
            plugin_id="reviewpack",
            version="1",
            contribution_id="review-prompt",
            prompt_name="review",
            prompt_document=document,
        )
    args = [
        str(wheel),
        "--kind",
        kind,
        "--plugin-id",
        "reviewpack",
        "--resource-name",
        "review",
    ]
    assert smoke_cli_main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["artifactSha256"] == sha256(wheel.read_bytes()).hexdigest()
    assert report["productAdmission"] == "passed"
    assert report["productSelection"] == "passed"
    assert report["productUse"] == "passed"
    assert report["modelTransport"] == "offline"
    assert report["workspace"] == "disposable"


@pytest.mark.skipif(os.name != "posix", reason="ordinary data Product path is POSIX")
def test_author_smoke_reports_the_exact_failed_boundary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    wheel = write_coding_data_skill_wheel(
        tmp_path,
        plugin_id="reviewpack",
        version="1",
        contribution_id="review-skill",
        skill_name="review",
        skill_document=b"---\nname: review\n---\n# Review\nCheck this.\n",
    )
    assert smoke_cli_main(
        [
            str(wheel),
            "--kind",
            "skill",
            "--plugin-id",
            "reviewpack",
            "--resource-name",
            "missing",
        ]
    ) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    assert report["failedStage"] == "product_selection"
    assert report["productAdmission"] == "passed"
    assert report["productSelection"] == "failed"
    assert report["productUse"] == "not_checked"


@pytest.mark.skipif(os.name != "posix", reason="ordinary data Product path is POSIX")
def test_author_smoke_does_not_claim_selection_after_admission_refusal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    invalid_wheel = tmp_path / "invalid-1-py3-none-any.whl"
    invalid_wheel.write_bytes(b"not a Wheel")
    assert smoke_cli_main(
        [
            str(invalid_wheel),
            "--kind",
            "skill",
            "--plugin-id",
            "reviewpack",
            "--resource-name",
            "review",
        ]
    ) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["failedStage"] == "product_admission"
    assert report["productAdmission"] == "failed"
    assert report["productSelection"] == "not_checked"
    assert report["productUse"] == "not_checked"


@pytest.mark.skipif(os.name != "posix", reason="ordinary data Product path is POSIX")
def test_author_theme_scaffold_reaches_screen_consumer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "themepack"
    assert plugin_cli_main(
        ["init-coding-theme", str(source_root), "--resource-name", "dusk"]
    ) == 0
    scaffold = json.loads(capsys.readouterr().out)
    assert scaffold["productUse"] == "not_checked"
    assert plugin_cli_main(scaffold["buildCommand"][1:]) == 0
    capsys.readouterr()
    assert smoke_cli_main(scaffold["smokeCommand"][1:]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["productAdmission"] == "passed"
    assert report["productSelection"] == "passed"
    assert report["productUse"] == "passed"
