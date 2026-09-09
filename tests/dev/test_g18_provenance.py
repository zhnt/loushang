from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/dev/_g18_provenance.py"
SPEC = importlib.util.spec_from_file_location("g18_provenance", SCRIPT)
provenance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provenance)

PROJECT = (
    '[project]\nname = "loushang"\nversion = "0.1.0"\n'
    '[project.scripts]\nloushang = "loushang:main"\n'
    '[tool.setuptools.package-data]\n"loushang" = ["data.json"]\n'
)


def git(repo, *args):
    environment = {
        **{
            key: value
            for key, value in os.environ.items()
            if not key.upper().startswith("GIT_")
        },
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.name=G18 fixture",
            "-c",
            "user.email=g18@example.invalid",
            "-c",
            "commit.gpgSign=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            *args,
        ],
        cwd=repo,
        env=environment,
        text=True,
    ).strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet", "--template=")
    package = repo / "src/loushang"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("def main(): pass\nFLAG = 1\n")
    (package / "data.json").write_text('{"fixture": 1}')
    (repo / "pyproject.toml").write_text(PROJECT)
    (repo / "uv.lock").write_text("version = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "baseline")
    return repo, git(repo, "rev-parse", "HEAD")


def wheel(repo, path, fault=None):
    files = {
        "loushang/__init__.py": (repo / "src/loushang/__init__.py").read_bytes(),
        "loushang/data.json": (repo / "src/loushang/data.json").read_bytes(),
        "loushang-0.1.0.dist-info/entry_points.txt": b"[console_scripts]\nloushang = loushang:main\n",
        "loushang-0.1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: loushang\nVersion: 0.1.0\n",
    }
    if fault == "bytes":
        files["loushang/__init__.py"] += b"CHANGED = True\n"
    elif fault == "resource":
        files["loushang/data.json"] = b"{}"
    elif fault == "missing":
        del files["loushang/__init__.py"]
    elif fault == "missing-resource":
        del files["loushang/data.json"]
    elif fault == "extra":
        files["loushang/extra.py"] = b""
    elif fault == "entry":
        files["loushang-0.1.0.dist-info/entry_points.txt"] = (
            b"[console_scripts]\nloushang = loushang:wrong\n"
        )
    elif fault == "version":
        files["loushang-0.1.0.dist-info/METADATA"] = b"Name: loushang\nVersion: 9\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
        if fault == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("loushang/data.json", b"{}")
    return path


@pytest.mark.parametrize("change", ["bytes", "added", "deleted", "mode", "symlink"])
def test_helper_manifest_binds_transitive_code_and_fixture_inputs(repository, change):
    repo, _ = repository
    helper = repo / "scripts/dev/observer.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# observer\n")
    fixture = repo / "tests/nested/fixture.json"
    fixture.parent.mkdir(parents=True)
    fixture.write_text('{"synthetic": true}')
    git(repo, "add", "scripts", "tests")
    (repo / ".gitignore").write_text("__pycache__/\n")
    cache = fixture.parent / "__pycache__/fixture.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"not a trusted source input")
    original = provenance.helper_manifest(repo)
    assert set(original) == {"scripts/dev/observer.py", "tests/nested/fixture.json"}
    assert provenance.helper_manifest(repo) == original
    if change == "bytes":
        fixture.write_text("{}")
    elif change == "added":
        helper.with_name("untracked_dependency.py").write_text("# new helper\n")
    elif change == "deleted":
        fixture.unlink()
    elif change == "mode":
        if os.name == "nt":
            pytest.skip("POSIX executable mode contract")
        helper.chmod(helper.stat().st_mode ^ 0o100)
    elif change == "symlink":
        if os.name == "nt":
            pytest.skip("test symlink creation requires Windows privileges")
        helper.unlink()
        helper.symlink_to(fixture)
    if change in {"deleted", "symlink"}:
        with pytest.raises((OSError, ValueError)):
            provenance.helper_manifest(repo)
    else:
        assert provenance.helper_manifest(repo) != original


def test_old_baseline_and_new_candidate_each_bind_their_own_commit(
    repository, tmp_path
):
    repo, base = repository
    baseline = wheel(repo, tmp_path / "base.whl")
    (repo / "src/loushang/__init__.py").write_text("def main(): pass\nFLAG = 2\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "candidate")
    candidate = wheel(repo, tmp_path / "candidate.whl")
    left = provenance.verify_wheel_at_commit(repo, baseline, base)
    right = provenance.verify_wheel_at_commit(repo, candidate, "HEAD")
    assert left["commit"] == base and right["commit"] != base
    assert left["lock_sha256"] == right["lock_sha256"]
    assert left["package_inventory_sha256"] != right["package_inventory_sha256"]
    assert left["package_file_count"] == right["package_file_count"] == 2
    with pytest.raises(ValueError, match="bytes differ"):
        provenance.verify_wheel_at_commit(repo, baseline, "HEAD")
    # Read-only historical verification does not depend on the current checkout.
    (repo / "src/loushang/__init__.py").write_text("uncommitted candidate work\n")
    assert provenance.verify_wheel_at_commit(repo, baseline, base) == left


@pytest.mark.parametrize(
    "fault",
    [
        "bytes",
        "resource",
        "missing",
        "missing-resource",
        "extra",
        "entry",
        "version",
        "duplicate",
    ],
)
def test_provenance_rejects_wheel_drift(repository, tmp_path, fault):
    repo, base = repository
    archive = wheel(repo, tmp_path / "bad.whl", fault)
    with pytest.raises(ValueError):
        provenance.verify_wheel_at_commit(repo, archive, base)


def test_ambient_git_repository_and_config_cannot_redirect_source(
    repository, tmp_path, monkeypatch
):
    repo, base = repository
    archive = wheel(repo, tmp_path / "base.whl")
    expected = provenance.verify_wheel_at_commit(repo, archive, base)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    git(foreign, "init", "--quiet", "--template=")
    for key, value in {
        "GIT_DIR": str(foreign / ".git"),
        "GIT_WORK_TREE": str(foreign),
        "GIT_OBJECT_DIRECTORY": str(foreign / ".git/objects"),
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.worktree",
        "GIT_CONFIG_VALUE_0": str(foreign),
    }.items():
        monkeypatch.setenv(key, value)
    assert provenance.verify_wheel_at_commit(repo, archive, base) == expected
    provenance.require_clean_product(repo)
    (repo / "src/loushang/__init__.py").write_text("dirty\n")
    with pytest.raises(ValueError, match="must match HEAD"):
        provenance.require_clean_product(repo)
    assert os.environ["GIT_DIR"] == str(foreign / ".git")


@pytest.mark.parametrize("kind", ["commit", "blob"])
def test_git_replacements_cannot_attribute_new_bytes_to_old_commit(
    repository, tmp_path, kind
):
    repo, base = repository
    baseline = wheel(repo, tmp_path / "base.whl")
    expected = provenance.verify_wheel_at_commit(repo, baseline, base)
    (repo / "src/loushang/__init__.py").write_text("def main(): pass\nFLAG = 2\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "candidate")
    candidate = wheel(repo, tmp_path / "candidate.whl")
    suffix = "" if kind == "commit" else ":src/loushang/__init__.py"
    before = git(repo, "rev-parse", base + suffix)
    after = git(repo, "rev-parse", "HEAD" + suffix)
    git(repo, "replace", before, after)
    # Confirm the negative control really changes ordinary Git's view.
    assert "FLAG = 2" in git(repo, "show", base + ":src/loushang/__init__.py")
    assert provenance.verify_wheel_at_commit(repo, baseline, base) == expected
    with pytest.raises(ValueError, match="bytes differ"):
        provenance.verify_wheel_at_commit(repo, candidate, base)


def test_wheel_receipt_hashes_exactly_the_validated_byte_snapshot(
    repository, tmp_path, monkeypatch
):
    repo, base = repository
    archive = wheel(repo, tmp_path / "base.whl")
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    original = provenance.zipfile.ZipFile

    def swap_after_read(value, *args, **kwargs):
        archive.write_bytes(b"not-the-validated-wheel")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(provenance.zipfile, "ZipFile", swap_after_read)
    receipt = provenance.verify_wheel_at_commit(repo, archive, base)
    assert receipt["wheel_sha256"] == expected
    assert receipt["wheel_sha256"] != hashlib.sha256(archive.read_bytes()).hexdigest()


def test_resource_globs_preserve_directory_boundaries():
    config = {
        "tool": {
            "setuptools": {
                "package-data": {
                    "loushang": ["py.typed"],
                    "loushang.coding": ["declarations/*.json", "skills/*/*.md"],
                }
            }
        }
    }
    files = {
        "loushang/py.typed",
        "loushang/coding/declarations/tool.json",
        "loushang/coding/skills/review/SKILL.md",
        "loushang/coding/skills/review/nested/ignored.md",
        "loushang/README.md",
    }
    assert provenance._required_resources(config, files) == files - {
        "loushang/coding/skills/review/nested/ignored.md",
        "loushang/README.md",
    }
