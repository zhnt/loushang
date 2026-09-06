# Detect OS
ifeq ($(OS),Windows_NT)
    DETECTED_OS := Windows
    EXE_EXT := .exe
    RM := del /Q
    RMDIR := rmdir /S /Q
    INSTALL_DIR := $(USERPROFILE)/bin
else
    DETECTED_OS := $(shell uname -s)
    EXE_EXT :=
    RM := rm -f
    RMDIR := rm -rf
    INSTALL_DIR := $(HOME)/.local/bin
endif

BINARY_NAME := loushang$(EXE_EXT)
DIST_BINARY := dist/$(BINARY_NAME)
AI_OFFLINE_ENV := env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_OAUTH_TOKEN -u ANTHROPIC_BASE_URL -u ARK_API_KEY -u BAIDU_QIANFAN_API_KEY -u COPILOT_GITHUB_TOKEN -u DASHSCOPE_API_KEY -u DEEPSEEK_API_KEY -u GH_TOKEN -u GITHUB_TOKEN -u HUNYUAN_API_KEY -u MINIMAX_API_KEY -u MOONSHOT_API_KEY -u OPENAI_API_KEY -u QIANFAN_API_KEY -u STEPFUN_API_KEY -u STEP_API_KEY -u ZAI_API_KEY
PYTEST_RUNNER := python scripts/dev/run_pytest.py

HARNESSTUI_SHARED_SOURCES := \
	src/loushang/harness/commands \
	src/loushang/harness/host/types.py \
	src/loushang/harness/session/command_controller.py \
	src/loushang/harness/session/footer.py \
	src/loushang/harness/workspace/git.py \
	src/loushang/tui/clipboard.py \
	src/loushang/tui/clipboard_image.py \
	src/loushang/tui/launch.py \
	src/loushang/tui/playback_suite.py \
	src/loushang/tui/settings.py \
	src/loushang/tui/terminal_diagnostics.py \
	src/loushang/tui/ui_parts/layout.py \
	src/loushang/tui/ui_parts/transcript.py \
	src/loushang/harnesstui
HARNESSTUI_CODING_ADAPTERS := \
	src/loushang/coding/platform/__init__.py \
	src/loushang/coding/ui
HARNESSTUI_TEST_SUPPORT := \
	tests/coding/tui_support
CODING_TUI_PRODUCT_SOURCES := \
	src/loushang/coding/model_selection_tui.py \
	src/loushang/coding/model_selection.py \
	src/loushang/coding/prompt_command.py \
	src/loushang/coding/diagnostics/debug_status.py \
	src/loushang/harness/events/recording_policy.py \
	src/loushang/coding/interaction/settings_profile.py \
	src/loushang/coding/presentation/tui
HARNESSTUI_TEST_PATHS := \
	tests/harness/commands/test_catalog.py \
	tests/harness/workspace/test_git.py \
	tests/harnesstui \
	tests/tui/test_clipboard.py \
	tests/tui/test_clipboard_image.py \
	tests/tui/test_import_boundaries.py \
	tests/tui/test_launch.py \
	tests/tui/test_playback_suite.py \
	tests/tui/test_settings.py \
	tests/tui/test_terminal_diagnostics.py \
	tests/tui/test_transcript_region.py \
	tests/architecture/test_coding_wave_a_budget.py \
	tests/architecture/test_import_boundaries.py \
	tests/harness/session/test_footer.py \
	tests/harness/session/test_changelog.py \
	tests/coding/test_platform_utils.py \
	tests/coding/test_prompt_command.py \
	tests/coding/test_screen_conversation_action_host.py \
	tests/coding/test_coding_tui_profile.py \
	tests/coding/test_ui_debug_command.py \
	tests/coding/test_ui_hotkeys.py \
	tests/coding/test_ui_mode.py \
	tests/coding/test_ui_startup.py \
	tests/coding/test_ui_steer.py \
	tests/coding/test_ui_import_boundaries.py \
	tests/coding/test_screen_coding_tui_app.py \
	tests/coding/test_screen_coding_tui_events.py \
	tests/coding/test_screen_coding_tui_input.py \
	tests/coding/test_screen_coding_tui_loop.py \
	tests/coding/test_screen_coding_tui_mode.py \
	tests/coding/test_screen_coding_tui_playback.py \
	tests/coding/test_screen_coding_tui_perf_probe.py \
	tests/coding/test_screen_coding_tui_surfaces.py \
	tests/coding/test_screen_coding_tui_terminal_playback.py \
	tests/coding/test_screen_settings_page.py \
	tests/coding/test_screen_tui_playback_harness.py \
	tests/coding/test_screen_tui_playback_runner.py \
	tests/coding/test_session_command_controller.py \
	tests/coding/test_tool_transcript_blocks.py \
	tests/coding/test_ui_completion.py \
	tests/coding/test_ui_conversation_event_adapter.py \
	tests/coding/test_ui_model_list.py \
	tests/coding/test_ui_plain_app.py \
	tests/coding/test_ui_plain_renderer.py \
	tests/coding/test_ui_resume.py \
	tests/coding/test_ui_status_line.py \
	tests/coding/test_ui_transcript_projection.py \
	tests/coding/test_ui_transcript_source.py \
	tests/coding/ui/test_screen_input.py
CODING_TUI_PRODUCT_TEST_PATHS := \
	tests/coding/test_ui_controller.py \
	tests/coding/test_ui_debug_status.py \
	tests/harness/events/test_recording_policy.py \
	tests/coding/test_ui_model.py \
	tests/coding/test_coding_settings_presentation.py \
	tests/coding/test_ui_session_view.py
HARNESS_SOURCES := src/loushang/harness
HARNESS_RUNTIME_SUPPORT_SOURCES := \
	src/loushang/coding/_product_worker_canary.py \
	src/loushang/foundation/platform_paths.py \
	src/loushang/foundation/runtime_scope.py \
	scripts/dev/run_pytest.py \
	scripts/dev/verify_plc9c5_manifest.py \
	scripts/run_tui_native_tests.py \
	scripts/run_tui_platform_tests.py
HARNESS_TEST_PATHS := \
	tests/harness \
	tests/dev/test_run_pytest.py \
	tests/dev/test_verify_plc9c5_manifest.py \
	tests/foundation/test_runtime_scope.py \
	tests/coding/test_agent_session_model_input.py \
	tests/architecture/test_import_boundaries.py \
	tests/architecture/test_capability_runtime_convergence_pr0.py \
	tests/architecture/test_composition_lifecycle_authority_cla0.py \
	tests/architecture/test_plugin_lifecycle_plc9_baseline.py \
	tests/architecture/test_plugin_lifecycle_plc9a1_contract.py \
	tests/architecture/test_plugin_lifecycle_plc9a2_contract.py \
	tests/architecture/test_plugin_lifecycle_plc9b_contract.py \
	tests/architecture/test_plugin_lifecycle_plc9c0_baseline.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c50_baseline.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c51_contract.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c52_linux_native.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c53_windows_mechanics.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c54_linux_product.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c55_windows_containment.py \
	tests/architecture/test_hosting_h65_windows_lpac_design.py \
	tests/architecture/test_session_model_call_closure_contract.py
HOSTING_SOURCES := \
	src/loushang/hosting \
	src/loushang/harness/workspace/process/hosting_compat.py \
	src/loushang/harness/worker/__init__.py \
	src/loushang/harness/worker/_native_profile_bridge.py \
	src/loushang/harness/worker/hosting_adapter.py \
	src/loushang/harness/worker/owner_selection.py \
	src/loushang/harness/worker/session.py \
	src/loushang/harness/worker/supervisor.py
HOSTING_TEST_PATHS := \
	tests/hosting \
	tests/harness/workspace/process/test_hosting_compat.py \
	tests/harness/worker/test_hosting_adapter.py \
	tests/architecture/test_hosting_h0_contract.py \
	tests/architecture/test_hosting_h1_process_lifetime.py \
	tests/architecture/test_hosting_h2_platform_contract.py \
	tests/architecture/test_hosting_h3_endpoint.py \
	tests/architecture/test_hosting_h4_child_session.py \
	tests/architecture/test_hosting_h5_worker_adapter.py \
	tests/architecture/test_hosting_h6_launch_preparation.py \
	tests/architecture/test_hosting_h6_harness_parity.py \
	tests/architecture/test_hosting_h6_posix_native.py \
	tests/architecture/test_hosting_h6_windows_native.py \
	tests/architecture/test_hosted_product_runtime_v1_baseline.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c50_baseline.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c52_linux_native.py \
	tests/architecture/test_plugin_lifecycle_plc9c5_c53_windows_mechanics.py \
	tests/architecture/test_hosting_h65_windows_lpac_design.py \
	tests/architecture/test_hosting_architecture_baseline.py
APPHOST_SOURCES := \
	src/loushang/apphost \
	src/loushang/appserver \
	src/loushang/coding/_product_worker_canary.py \
	src/loushang/coding/apphost_composition.py \
	src/loushang/coding/apphost_product.py
APPHOST_TEST_PATHS := \
	tests/apphost \
	tests/coding/test_apphost_composition.py \
	tests/coding/test_apphost_product.py \
	tests/dev/test_verify_evidence_manifest.py \
	tests/architecture/test_apphost_a0_contract.py \
	tests/architecture/test_apphost_a02_architecture.py \
	tests/architecture/test_apphost_a03_a04_architecture.py \
	tests/architecture/test_hosted_product_runtime_g8_join.py \
	tests/architecture/test_hosted_product_runtime_g9_closure.py
APPHOST_LINT_SUPPORT := \
	scripts/dev/verify_evidence_manifest.py \
	tests/harness/worker/test_coding_product_worker_canary.py

.PHONY: bootstrap test test-ai check-ai test-tui test-tui-render-contract test-tui-terminal-platform test-tui-native test-tui-tmux lint-ai fmt-ai typecheck-ai typecheck-tui build-binary install-binary clean-binary vendor-ai-moonshot-anthropic-stream vendor-ai-moonshot-anthropic-complete vendor-ai-moonshot-anthropic-tools vendor-ai-moonshot-openai-stream vendor-ai-moonshot-openai-complete vendor-ai-moonshot-openai-tools vendor-ai-dashscope-openai-responses-stream vendor-ai-dashscope-openai-responses-tools example-ai-model-lookup example-ai-complete example-ai-stream example-ai-tools example-ai-typed-context example-ai-advanced-faux-stream example-ai-advanced-context-tools example-ai-advanced-tool-result-roundtrip example-ai-kimi-anthropic-stream example-ai-kimi-anthropic-complete example-ai-kimi-anthropic-tools example-ai-kimi-openai-stream example-ai-kimi-openai-complete example-ai-kimi-openai-tools example-ai-dashscope-openai-responses-stream example-ai-dashscope-openai-responses-tools example-ai-custom-base-url-openai-advanced example-ai-faux-stream example-ai-context-tools-minimal example-ai-tool-result-roundtrip
.PHONY: test-sandbox test-host-runtime
.PHONY: test-tui-input-playback
.PHONY: check-ai-catalog check-ai-examples check-ai-imports check-ai-coverage
.PHONY: check-harness lint-harness typecheck-harness test-harness check-plc9c5-c51-contract test-plc9c5-c51-contract check-plc9c5-c52-linux-native test-plc9c5-c52-linux-native check-plc9c5-c53-windows-mechanics test-plc9c5-c53-windows-mechanics check-plc9c5-c55b-windows-lpac-native test-plc9c5-c55b-windows-lpac-native
.PHONY: check-hosting lint-hosting typecheck-hosting test-hosting
.PHONY: check-apphost lint-apphost typecheck-apphost test-apphost test-hosted-product-g8-evidence test-hosted-product-g9-linux-evidence
.PHONY: check-architecture-docs
.PHONY: check-harnesstui lint-harnesstui typecheck-harnesstui test-harnesstui
.PHONY: lane-status

bootstrap:
	test -d .venv || uv venv .venv
	. .venv/bin/activate && uv pip install -e .[dev]

test:
	. .venv/bin/activate && uv run $(PYTEST_RUNNER) tests -q

test-sandbox:
	. .venv/bin/activate && uv run $(PYTEST_RUNNER) tests --skip-host-runtime -q

test-host-runtime:
	. .venv/bin/activate && uv run $(PYTEST_RUNNER) tests -m requires_host_runtime -q

test-ai:
	. .venv/bin/activate && $(AI_OFFLINE_ENV) uv run $(PYTEST_RUNNER) tests/ai tests/protocols tests/examples/test_ai_examples.py tests/examples/test_auth_examples.py -m "not live" -q

check-ai: lint-ai typecheck-ai check-ai-catalog check-ai-imports check-ai-examples check-ai-coverage

check-ai-catalog:
	uv run python scripts/ai/check_catalog.py

check-ai-imports:
	uv run python scripts/ai/check_import_boundaries.py

check-ai-examples:
	$(AI_OFFLINE_ENV) uv run python scripts/ai/check_examples.py
	$(AI_OFFLINE_ENV) uv run $(PYTEST_RUNNER) tests/examples -q

check-ai-coverage:
	mkdir -p .artifacts/ai
	. .venv/bin/activate && $(AI_OFFLINE_ENV) uv run $(PYTEST_RUNNER) tests/ai tests/protocols tests/examples/test_ai_examples.py -m "not live" --cov=src/loushang/ai --cov-report=term-missing:skip-covered --cov-report=xml:.artifacts/ai/coverage.xml --cov-fail-under=90 -q
	uv run python scripts/ai/check_coverage_targets.py .artifacts/ai/coverage.xml

check-harness: lint-harness typecheck-harness test-harness

lint-harness:
	uv --cache-dir .uv-cache run --extra dev ruff check $(HARNESS_SOURCES) $(HARNESS_RUNTIME_SUPPORT_SOURCES) $(HARNESS_TEST_PATHS)

typecheck-harness:
	uv --cache-dir .uv-cache run --extra dev mypy --follow-imports=silent $(HARNESS_SOURCES) $(HARNESS_RUNTIME_SUPPORT_SOURCES)

test-harness:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) $(HARNESS_TEST_PATHS) -q

test-plc9c5-c51-contract:
	mkdir -p .artifacts
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/harness/worker/test_product_activation.py -q --junitxml=.artifacts/plc9c5-c51-contract.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/plc9c5-c51-contract.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_plc9c5_manifest.py docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json PLC9C5-C5.1-CONTRACT .artifacts/plc9c5-c51-contract.xml

check-plc9c5-c51-contract: test-plc9c5-c51-contract

test-plc9c5-c52-linux-native:
	mkdir -p .artifacts
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/harness/worker/test_native_profile_bridge.py -q --junitxml=.artifacts/plc9c5-c52-linux-native.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/plc9c5-c52-linux-native.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_plc9c5_manifest.py docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json PLC9C5-C5.2-LINUX-NATIVE .artifacts/plc9c5-c52-linux-native.xml

check-plc9c5-c52-linux-native: test-plc9c5-c52-linux-native

test-plc9c5-c53-windows-mechanics:
	mkdir -p .artifacts
	LOUSHANG_PLC9C5_C53_REPORT=1 uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/hosting/test_plc9c5_c53_windows_mechanics.py -q --junitxml=.artifacts/plc9c5-c53-windows-mechanics.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/plc9c5-c53-windows-mechanics.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_plc9c5_manifest.py docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json PLC9C5-C5.3-WINDOWS-MECHANICS .artifacts/plc9c5-c53-windows-mechanics.xml

check-plc9c5-c53-windows-mechanics: test-plc9c5-c53-windows-mechanics

test-plc9c5-c55b-windows-lpac-native:
	mkdir -p .artifacts
	LOUSHANG_PLC9C5_C55B_REPORT=1 uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/hosting/test_plc9c5_c55b_windows_lpac_native.py -q --junitxml=.artifacts/plc9c5-c55b-windows-lpac-native.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/plc9c5-c55b-windows-lpac-native.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_plc9c5_manifest.py docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json PLC9C5-C5.5B-WINDOWS-LPAC-NATIVE .artifacts/plc9c5-c55b-windows-lpac-native.xml

check-plc9c5-c55b-windows-lpac-native: test-plc9c5-c55b-windows-lpac-native

test-plc9c5-c55c-windows-product:
	mkdir -p .artifacts
	LOUSHANG_PLC9C5_C55C_REPORT=1 uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/harness/worker/test_coding_product_worker_windows_canary.py -q --junitxml=.artifacts/plc9c5-c55c-windows-product.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/plc9c5-c55c-windows-product.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_plc9c5_manifest.py docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json PLC9C5-C5.5C-WINDOWS-PRODUCT .artifacts/plc9c5-c55c-windows-product.xml

check-plc9c5-c55c-windows-product: test-plc9c5-c55c-windows-product

test-plc9c5-c54-linux-product:
	mkdir -p .artifacts
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/harness/worker/test_coding_product_worker_canary.py -q --junitxml=.artifacts/plc9c5-c54-linux-product.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/plc9c5-c54-linux-product.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_plc9c5_manifest.py docs/internals/architecture/harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json PLC9C5-C5.4-LINUX-PRODUCT .artifacts/plc9c5-c54-linux-product.xml

check-plc9c5-c54-linux-product: test-plc9c5-c54-linux-product

check-plc9c5-c55-windows-containment-design:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/architecture/test_plugin_lifecycle_plc9c5_c55_windows_containment.py tests/architecture/test_hosting_h65_windows_lpac_design.py -q

check-hosting: lint-hosting typecheck-hosting test-hosting

lint-hosting:
	uv --cache-dir .uv-cache run --extra dev ruff check $(HOSTING_SOURCES) $(HOSTING_TEST_PATHS)

typecheck-hosting:
	uv --cache-dir .uv-cache run --extra dev mypy --follow-imports=silent $(HOSTING_SOURCES)

test-hosting:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) $(HOSTING_TEST_PATHS) -q

check-apphost: lint-apphost typecheck-apphost test-apphost test-hosted-product-g8-evidence test-hosted-product-g9-linux-evidence

lint-apphost:
	uv --cache-dir .uv-cache run --extra dev ruff check $(APPHOST_SOURCES) $(APPHOST_TEST_PATHS) $(APPHOST_LINT_SUPPORT)

typecheck-apphost:
	uv --cache-dir .uv-cache run --extra dev mypy --follow-imports=silent $(APPHOST_SOURCES)

test-apphost:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) $(APPHOST_TEST_PATHS) -q

test-hosted-product-g8-evidence:
	mkdir -p .artifacts
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/coding/test_apphost_product.py tests/harness/worker/test_coding_product_worker_canary.py::test_product_normal_close_retires_exact_attempt_without_global_rollback -q --junitxml=.artifacts/hosted-product-g8.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/hosted-product-g8.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_evidence_manifest.py docs/internals/architecture/apphost/hosted-product-g8-evidence-manifest.json HOSTED-PRODUCT-G8-JOIN .artifacts/hosted-product-g8.xml

test-hosted-product-g9-linux-evidence:
	mkdir -p .artifacts
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/coding/test_apphost_composition.py -q --junitxml=.artifacts/hosted-product-g9-linux.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_pytest_xml.py .artifacts/hosted-product-g9-linux.xml
	uv --cache-dir .uv-cache run --extra dev python scripts/dev/verify_evidence_manifest.py docs/internals/architecture/apphost/hosted-product-g9-evidence-manifest.json HOSTED-PRODUCT-G9-LINUX .artifacts/hosted-product-g9-linux.xml

check-architecture-docs:
	.venv/bin/ruff check scripts/architecture/render_current_package_dependencies.py tests/architecture/test_architecture_documentation.py
	.venv/bin/python scripts/architecture/render_current_package_dependencies.py --check
	.venv/bin/python scripts/dev/run_pytest.py tests/architecture/test_architecture_documentation.py -q

check-harnesstui: lint-harnesstui typecheck-harnesstui test-harnesstui

lint-harnesstui:
	uv --cache-dir .uv-cache run --extra dev ruff check $(HARNESSTUI_SHARED_SOURCES) $(HARNESSTUI_CODING_ADAPTERS) $(CODING_TUI_PRODUCT_SOURCES) $(HARNESSTUI_TEST_SUPPORT) $(HARNESSTUI_TEST_PATHS) $(CODING_TUI_PRODUCT_TEST_PATHS)

typecheck-harnesstui:
	uv --cache-dir .uv-cache run --extra dev mypy --follow-imports=silent $(HARNESSTUI_SHARED_SOURCES) $(HARNESSTUI_CODING_ADAPTERS) $(CODING_TUI_PRODUCT_SOURCES)

test-harnesstui:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) $(HARNESSTUI_TEST_PATHS) $(CODING_TUI_PRODUCT_TEST_PATHS) -m "not tui_render_contract" -q

test-tui:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/tui --skip-host-runtime -q

test-tui-render-contract:
	uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/tui tests/harnesstui tests/coding -m tui_render_contract -q

test-tui-terminal-platform:
	uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_platform_tests.py current -q

test-tui-input-playback:
	uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_playback.py composer-selection-stress bracketed-paste-large-marker mouse-select-active-surface screen-loop-terminal-session-cleanup screen-loop-ctrl-c-abort-running

test-tui-native:
	uv --cache-dir .uv-cache run --extra dev python scripts/run_tui_native_tests.py current -q

test-tui-tmux:
	LOUSHANG_REQUIRE_TMUX=1 uv --cache-dir .uv-cache run --extra dev $(PYTEST_RUNNER) tests/coding/test_screen_coding_tui_pty_smoke.py -m tui_tmux_integration --strict-markers --strict-config -q

lane-status:
	uv run python scripts/dev/lane_status.py

lint-ai:
	. .venv/bin/activate && uv run ruff check src/loushang/ai examples/ai examples/auth tests/ai tests/protocols tests/examples/test_auth_examples.py scripts/ai

fmt-ai:
	. .venv/bin/activate && uv run ruff format src/loushang/ai examples/ai examples/auth tests/ai tests/protocols tests/examples/test_auth_examples.py scripts/ai

typecheck-ai:
	. .venv/bin/activate && uv run mypy src/loushang/ai

vendor-ai-moonshot-anthropic-stream:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/moonshot/test_kimi_anthropic_stream_live.py -q -s

typecheck-tui:
	. .venv/bin/activate && mypy src/loushang/tui

example-ai-kimi-anthropic-stream:
	uv run python examples/ai/kimi_anthropic_stream.py

vendor-ai-moonshot-anthropic-complete:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/moonshot/test_kimi_anthropic_complete_live.py -q -s

vendor-ai-moonshot-anthropic-tools:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/moonshot/test_kimi_anthropic_tools_live.py -q -s

vendor-ai-moonshot-openai-complete:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/moonshot/test_kimi_openai_complete_live.py -q -s

vendor-ai-moonshot-openai-stream:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/moonshot/test_kimi_openai_stream_live.py -q -s

vendor-ai-moonshot-openai-tools:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/moonshot/test_kimi_openai_tools_live.py -q -s

vendor-ai-dashscope-openai-responses-stream:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/dashscope/test_openai_responses_stream_live.py -q -s

vendor-ai-dashscope-openai-responses-tools:
	LOUSHANG_AI_LIVE=1 uv run $(PYTEST_RUNNER) tests/ai/vendors/dashscope/test_openai_responses_tools_live.py -q -s

.PHONY: example-ai-offline example-ai-provider-matrix example-ai-provider-smoke

example-ai-offline:
	for path in examples/ai/[0-9][0-9]_*.py; do uv run python "$$path"; done

example-ai-model-lookup: example-ai-provider-matrix

example-ai-provider-matrix:
	uv run python examples/ai/11_provider_matrix.py

example-ai-provider-smoke:
	uv run python examples/ai/12_provider_smoke.py

example-ai-complete:
	uv run python examples/ai/01_complete.py

example-ai-stream:
	uv run python examples/ai/02_stream.py

example-ai-tools:
	uv run python examples/ai/04_tools.py

example-ai-typed-context:
	uv run python examples/ai/03_typed_context.py

example-ai-advanced-faux-stream:
	uv run python examples/ai/advanced/faux_stream.py

example-ai-advanced-context-tools:
	uv run python examples/ai/advanced/context_tools_minimal.py

example-ai-advanced-tool-result-roundtrip:
	uv run python examples/ai/advanced/tool_result_roundtrip.py

# ---------------------------------------------------------------------------
# Binary build / install (cross-platform)
# ---------------------------------------------------------------------------

build-binary: bootstrap
	uv pip install --python .venv/bin/python pyinstaller
	. .venv/bin/activate && uv run python -c "from PyInstaller.utils.hooks import collect_data_files, collect_submodules; assert callable(collect_data_files) and callable(collect_submodules); print('spec deps OK')"
	. .venv/bin/activate && uv run python -m PyInstaller --clean loushang.spec

install-binary: build-binary
ifeq ($(DETECTED_OS),Windows)
	@if not exist "$(INSTALL_DIR)" mkdir "$(INSTALL_DIR)"
	copy /Y "$(DIST_BINARY)" "$(INSTALL_DIR)\$(BINARY_NAME)"
	@echo Installed to $(INSTALL_DIR)\$(BINARY_NAME)
else
	mkdir -p $(INSTALL_DIR)
	cp $(DIST_BINARY) $(INSTALL_DIR)/$(BINARY_NAME)
	@echo Installed to $(INSTALL_DIR)/$(BINARY_NAME)
	@echo 'Make sure $(INSTALL_DIR) is in your $$PATH'
endif

clean-binary:
	$(RMDIR) build/
	$(RM) dist/$(BINARY_NAME)
