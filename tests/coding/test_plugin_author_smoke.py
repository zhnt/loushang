from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.coding.plugin_author_smoke import main as smoke_cli_main
from loushang.plugin import (
    write_coding_data_prompt_wheel,
    write_coding_data_skill_wheel,
)


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
