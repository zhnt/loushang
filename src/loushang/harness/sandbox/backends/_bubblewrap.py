"""Internal Bubblewrap launch-plan builders shared by exec and hosting."""

from __future__ import annotations

from pathlib import Path

from ..types import SandboxScopeRequest, SandboxUnavailableError

_PLATFORM_READ_ROOTS = (
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/etc"),
    Path("/nix/store"),
)


def build_bubblewrap_command(
    bwrap_path: Path,
    scope: SandboxScopeRequest,
    command: tuple[str, ...],
) -> tuple[str, ...]:
    readable_roots = _collapse_roots(scope.readable_roots)
    writable_roots = _collapse_roots(scope.writable_roots)
    full_write = Path("/") in writable_roots
    full_read = full_write or Path("/") in readable_roots
    platform_roots = () if full_read else _platform_read_roots()

    args = [
        str(bwrap_path),
        "--new-session",
        "--die-with-parent",
    ]
    mounted: list[Path] = []
    created: set[Path] = set()
    if full_write:
        args.extend(("--bind", "/", "/"))
        mounted.append(Path("/"))
    elif full_read:
        args.extend(("--ro-bind", "/", "/"))
        mounted.append(Path("/"))
    else:
        args.extend(("--tmpfs", "/"))
        for root in platform_roots:
            _append_bind(args, root, writable=False, mounted=mounted, created=created)
        for root in readable_roots:
            _append_bind(args, root, writable=False, mounted=mounted, created=created)

    args.extend(("--dev", "/dev", "--proc", "/proc"))
    if not any(
        _paths_intersect(Path("/tmp"), root) for root in readable_roots + writable_roots
    ):
        args.extend(("--tmpfs", "/tmp"))

    for root in writable_roots:
        if root == Path("/") and full_write:
            continue
        _append_bind(args, root, writable=True, mounted=mounted, created=created)

    effective_visible_roots = (
        (Path("/"),)
        if full_read
        else _collapse_roots((*platform_roots, *readable_roots, *writable_roots))
    )
    for root in scope.denied_roots:
        if not _path_is_covered(root, effective_visible_roots):
            continue
        if root.is_dir():
            args.extend(("--tmpfs", str(root), "--remount-ro", str(root)))
        else:
            args.extend(("--ro-bind", "/dev/null", str(root)))

    args.extend(
        (
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
        )
    )
    if scope.network in {"denied", "restricted"}:
        args.append("--unshare-net")
    args.extend(("--chdir", str(scope.cwd), "--"))
    args.extend(command)
    return tuple(args)


def validate_bubblewrap_scope_request(request: SandboxScopeRequest) -> None:
    visible_roots = _collapse_roots((*request.readable_roots, *request.writable_roots))
    if not _path_is_covered(request.cwd, visible_roots):
        raise SandboxUnavailableError(
            f"sandbox cwd is outside the admitted roots: {request.cwd}"
        )
    for root in visible_roots:
        if not root.exists():
            raise SandboxUnavailableError(f"sandbox root does not exist: {root}")
        if not root.is_dir():
            raise SandboxUnavailableError(
                f"phase-B bubblewrap roots must be directories: {root}"
            )
    for denied in request.denied_roots:
        if request.cwd == denied or request.cwd.is_relative_to(denied):
            raise SandboxUnavailableError(
                f"sandbox cwd conflicts with denied root: {denied}"
            )
        if any(root == denied or root.is_relative_to(denied) for root in visible_roots):
            raise SandboxUnavailableError(
                f"admitted sandbox root conflicts with denied root: {denied}"
            )
        if _path_is_covered(denied, visible_roots) and not denied.exists():
            raise SandboxUnavailableError(
                f"missing denied roots are not enforceable in phase B: {denied}"
            )


def _append_bind(
    args: list[str],
    root: Path,
    *,
    writable: bool,
    mounted: list[Path],
    created: set[Path],
) -> None:
    if not writable and any(
        root == existing or root.is_relative_to(existing) for existing in mounted
    ):
        return
    _append_parent_dirs(args, root, mounted=mounted, created=created)
    args.extend(("--bind" if writable else "--ro-bind", str(root), str(root)))
    mounted.append(root)


def _append_parent_dirs(
    args: list[str],
    root: Path,
    *,
    mounted: list[Path],
    created: set[Path],
) -> None:
    parents = tuple(reversed(root.parents))
    for parent in parents:
        if parent == Path("/"):
            continue
        if any(
            parent == existing or parent.is_relative_to(existing)
            for existing in mounted
        ):
            continue
        if parent in created:
            continue
        args.extend(("--dir", str(parent)))
        created.add(parent)
    if root not in created and not any(
        root == existing or root.is_relative_to(existing) for existing in mounted
    ):
        args.extend(("--dir", str(root)))
        created.add(root)


def _platform_read_roots() -> tuple[Path, ...]:
    return tuple(path for path in _PLATFORM_READ_ROOTS if path.exists())


def _collapse_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    collapsed: list[Path] = []
    for root in sorted(set(roots), key=lambda path: (len(path.parts), str(path))):
        if any(
            root == existing or root.is_relative_to(existing) for existing in collapsed
        ):
            continue
        collapsed.append(root)
    return tuple(collapsed)


def _path_is_covered(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or path.is_relative_to(root) for root in roots)


def _paths_intersect(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


__all__: list[str] = []
