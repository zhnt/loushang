"""Read-only wheel provenance against an immutable Git commit, not checkout files.

The baseline remains verifiable after the candidate changes the working tree.
This fixed Loushang tooling does not build, install, mutate Git or contact remotes.
"""

from __future__ import annotations

import configparser
import hashlib
import io
import os
import stat
import subprocess
import tomllib
import zipfile
from email.parser import BytesParser
from fnmatch import fnmatchcase
from pathlib import Path


def _git(repo, *args, input=None):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_OPTIONAL_LOCKS="0",
    )
    return subprocess.run(
        ["git", "--no-replace-objects", "-c", "core.fsmonitor=false", *args],
        cwd=repo,
        env=environment,
        input=input,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    ).stdout


def require_clean_product(repo: Path) -> None:
    if _git(repo, "status", "--porcelain", "--", "src", "pyproject.toml", "uv.lock"):
        raise ValueError("checkout Product source/lock must match HEAD")


def helper_manifest(repo: Path) -> dict:
    """Bind all checkout scripts/tests and fixtures, not only direct imports.

    Product bytes are independently bound to wheels. Ignored build/cache files
    are not trusted inputs. This before/after check is not a security sandbox.
    """
    repo = repo.resolve(strict=True)
    names = set(
        _git(
            repo,
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "scripts",
            "tests",
        ).split(b"\0")
    ) - {b""}
    if not names or len(names) > 10000:
        raise ValueError("invalid trusted helper inventory size")
    result = {}
    size = 0
    for name in sorted(names):
        relative = os.fsdecode(name)
        path = repo / relative
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or path.resolve() != path
            or not path.is_relative_to(repo)
        ):
            raise ValueError("trusted helper input must be a regular in-tree file")
        size += info.st_size
        if size > 256 * 1024 * 1024:
            raise ValueError("trusted helper inventory exceeds 256 MiB")
        result[relative] = dict(
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            mode=stat.S_IMODE(info.st_mode),
        )
    return result


def _required_resources(configuration, files):
    """Match the committed, explicit setuptools package-data declarations.

    Component-wise glob matching prevents '*' from swallowing directory levels.
    Unsupported declarations fail closed; this is not a packaging implementation.
    """
    declarations = configuration["tool"]["setuptools"]["package-data"]
    required = set()
    for package, patterns in declarations.items():
        if not package.startswith("loushang") or any(
            not part.isidentifier() for part in package.split(".")
        ):
            raise ValueError("unsupported package-data package")
        prefix = package.replace(".", "/") + "/"
        for pattern in patterns:
            parts = pattern.split("/")
            if any(
                part in {"", ".", ".."} or "**" in part or "\\" in part
                for part in parts
            ):
                raise ValueError("unsupported package-data pattern")
            matched = {
                name
                for name in files
                if name.startswith(prefix)
                and len(name.removeprefix(prefix).split("/")) == len(parts)
                and all(
                    fnmatchcase(value, glob)
                    for value, glob in zip(
                        name.removeprefix(prefix).split("/"), parts, strict=True
                    )
                )
            }
            if not matched:
                raise ValueError("declared package-data has no source files")
            required.update(matched)
    return required


def _blobs(repo, object_ids):
    ids = sorted(set(object_ids))
    output = _git(
        repo,
        "cat-file",
        "--batch",
        input="".join(value + "\n" for value in ids).encode(),
    )
    blobs, offset = {}, 0
    for expected in ids:
        end = output.index(b"\n", offset)
        identity, kind, size = output[offset:end].decode().split()
        if identity != expected or kind != "blob":
            raise ValueError("source blob identity mismatch")
        start, end = end + 1, end + 1 + int(size)
        if output[end : end + 1] != b"\n":
            raise ValueError("incomplete source blob")
        blobs[identity] = output[start:end]
        offset = end + 1
    if offset != len(output):
        raise ValueError("unexpected source blob output")
    return blobs


def verify_wheel_at_commit(repo: Path, wheel: Path, revision: str) -> dict:
    commit = (
        _git(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}")
        .decode()
        .strip()
    )
    tree = _git(repo, "ls-tree", "-rz", "--full-tree", commit, "--", "src/loushang")
    files = {}
    for row in tree.split(b"\0"):
        if not row:
            continue
        metadata, name = row.split(b"\t", 1)
        mode, kind, identity = metadata.decode().split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("non-regular source package input")
        files[name.decode().removeprefix("src/")] = identity
    if not files:
        raise ValueError("source package missing")
    project_bytes = _git(repo, "show", commit + ":pyproject.toml")
    configuration = tomllib.loads(project_bytes.decode())
    project = configuration["project"]
    lock = _git(repo, "show", commit + ":uv.lock")
    wheel_bytes = wheel.read_bytes()
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate wheel members")
        packaged = [
            name
            for name in names
            if name.startswith("loushang/") and not name.endswith("/")
        ]
        if {name for name in packaged if name.endswith(".py")} != {
            name for name in files if name.endswith(".py")
        } or any(name not in files for name in packaged):
            raise ValueError("wheel package inventory differs from source commit")
        if not _required_resources(configuration, files) <= set(packaged):
            raise ValueError("wheel missing declared package-data")
        blobs = _blobs(repo, (files[name] for name in packaged))
        digests = {}
        for name in packaged:
            content = archive.read(name)
            if content != blobs[files[name]]:
                raise ValueError("wheel package bytes differ from source commit")
            digests[name] = hashlib.sha256(content).hexdigest()
        entry_names = [
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        ]
        metadata_names = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(entry_names) != 1 or len(metadata_names) != 1:
            raise ValueError("wheel distribution metadata inventory mismatch")
        entries = configparser.ConfigParser(interpolation=None)
        entries.optionxform = str
        entries.read_string(archive.read(entry_names[0]).decode())
        if dict(entries["console_scripts"]) != project["scripts"]:
            raise ValueError("wheel entry targets differ from source commit")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        if metadata.get_all("Name") != [project["name"]] or metadata.get_all(
            "Version"
        ) != [project["version"]]:
            raise ValueError("wheel distribution differs from source commit")
    inventory = "".join(
        f"{name}\0{digest}\n" for name, digest in sorted(digests.items())
    )
    return {
        "commit": commit,
        "package_tree": _git(repo, "rev-parse", commit + ":src/loushang")
        .decode()
        .strip(),
        "package_inventory_sha256": hashlib.sha256(inventory.encode()).hexdigest(),
        "package_paths_sha256": hashlib.sha256(
            "\n".join(sorted(digests)).encode()
        ).hexdigest(),
        "package_file_count": len(digests),
        "project_sha256": hashlib.sha256(project_bytes).hexdigest(),
        "lock_sha256": hashlib.sha256(lock).hexdigest(),
        "wheel_sha256": hashlib.sha256(wheel_bytes).hexdigest(),
    }
