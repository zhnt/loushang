from __future__ import annotations

import ast
from pathlib import Path

HOSTING = Path("src/loushang/hosting")
NATIVE = HOSTING / "_posix_launch_preparation.py"
PROCESS = HOSTING / "_posix_process.py"
CORE = HOSTING / "_launch_preparation.py"
PUBLIC = (
    HOSTING / "__init__.py",
    HOSTING / "contracts.py",
    HOSTING / "runtime.py",
)
RUNTIME_TESTS = Path("tests/hosting/test_posix_launch_preparation.py")
PLATFORM_TESTS = Path("tests/hosting/test_posix_launch_preparation_platform.py")
RECORD = (
    Path("docs/internals/architecture/hosting/validation")
    / "managed-launch-preparation-h6-posix-native.md"
)
WORKFLOW = Path(".github/workflows/hosting-quality.yml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(_read(path), filename=str(path))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_h6_2_native_profiles_are_private_closed_and_product_neutral() -> None:
    native = _read(NATIVE)
    public = "\n".join(_read(path) for path in PUBLIC)

    assert "__all__: list[str] = []" in native
    for private_name in (
        "_PosixStaticLaunchCaptureSpec",
        "_PosixStaticContainedLaunchCaptureSpec",
        "_PosixStaticLaunchCaptureBackend",
        "_PosixStaticLaunchMaterial",
    ):
        assert private_name in native
        assert private_name not in public
    for profile in (
        "posix-static-elf-v1",
        "posix-static-contained-elf-v1",
        "loushang-static-containment-launch/v1",
    ):
        assert profile in native
    for closure_identity in (
        "containment-launcher-static-elf:sha256:",
        "payload-static-elf:sha256:",
        "containment-profile:sha256:",
        "platform:linux-x86_64-syscall-abi",
    ):
        assert closure_identity in native
    assert "effective_environment" in native
    assert "_PT_INTERP in program_types" in native
    assert "_PT_DYNAMIC in program_types" in native
    assert not any(
        name.startswith(("loushang.harness", "loushang.coding", "loushang.apphost"))
        for name in _imports(NATIVE)
    )


def test_h6_2_native_spawn_has_one_exact_manifest_and_conservative_fence() -> None:
    native = _read(NATIVE)
    process = _read(PROCESS)
    core = _read(CORE)

    for operation in (
        'getattr(os, "O_NOFOLLOW", 0)',
        "_MFD_ALLOW_SEALING",
        "_F_SEAL_WRITE",
        "_verify_static_descriptor",
        "_verify_cwd_descriptor",
        "_claim_descriptors",
        "_contained_invocation",
    ):
        assert operation in native
    assert "set(endpoint_descriptors) & set(preparation_descriptors)" in process
    assert "pass_fds=inherited_descriptors" in process
    assert process.index("effect.begin_effect()") < process.index(
        "process = await self._spawn_once("
    )
    assert "settled_without_process" not in process
    assert "every such failure remains fenced" in process
    assert "class _ManagedSpawnSettledWithoutProcess" in core
    assert "effect.accepts_settled(failure)" in core


def test_h6_2_native_adversarial_gate_is_retained_and_non_skippable_on_linux() -> None:
    tests = _read(RUNTIME_TESTS)
    tree = ast.parse(tests, filename=str(RUNTIME_TESTS))
    test_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    required = (
        "test_posix_static_profile_pins_executable_and_cwd_across_replacement",
        "test_posix_static_profile_preserves_original_argv_zero",
        "test_posix_contained_profile_pins_launcher_payload_and_applies_profile",
        "test_posix_contained_profile_blocks_descendant_group_escape",
        "test_posix_contained_profile_rejects_unproved_launcher_chain",
        "test_posix_contained_launcher_rejects_profile_substitution_before_payload",
        "test_posix_static_profile_rejects_dynamic_loader_closure",
        "test_posix_static_profile_classifies_truncated_elf_header",
        "test_posix_static_profile_rejects_symlinked_executable",
        "test_posix_static_spawn_closes_unlisted_inheritable_descriptor",
        "test_posix_static_capture_normalizes_closed_stdio_descriptor_numbers",
        "test_posix_low_descriptor_duplication_failure_closes_original",
        "test_posix_static_capture_rejects_digest_and_cwd_identity_mismatch",
        "test_posix_static_memfd_failure_closes_open_source",
        "test_posix_static_native_descriptor_collision_fails_before_effect",
        "test_posix_static_post_create_error_stays_fenced",
        "test_posix_static_close_error_never_retries_reused_descriptor",
        "test_posix_static_native_early_exit_rolls_back_before_publication",
        "test_posix_static_cancellation_after_os_create_reclaims_process",
    )
    for name in required:
        function = test_functions[name]
        assert any(isinstance(node, ast.Assert) for node in ast.walk(function))
        assert not any(
            "skip" in ast.unparse(decorator)
            for decorator in function.decorator_list
        )

    workflow = _read(WORKFLOW)
    assert "tests/hosting/test_posix_launch_preparation.py" in workflow
    assert "h6-posix-native.xml" in workflow
    assert "verify_pytest_xml.py" in workflow
    assert "test_posix_static_launch_backend_is_exactly_linux_or_fails_closed" in _read(
        PLATFORM_TESTS
    )
    assert RECORD.is_file()
