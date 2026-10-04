# Coding Screen Theme candidate

This example builds one style-only Theme wheel for the current POSIX fenced
Coding Product candidate. Theme has real Product admission and Screen consumption
in this branch, but its general rollout still needs a separate Product decision.
It does not affect model input, hosted Mux, or an already running Session.

From the repository root, choose a fresh workspace that you own:

```sh
example_dir="$(pwd)/examples/plugins/coding_data_theme"
workspace_dir="/absolute/path/to/fresh-workspace"
mkdir -m 700 "$workspace_dir"
loushang-package-cutover --workspace "$workspace_dir"
loushang-plugin build-coding-theme \
  "$example_dir/themes/dusk.json" \
  --plugin-id themepack --version 1 --output-dir "$workspace_dir/dist"
cd "$workspace_dir"
loushang --install-package "$workspace_dir/dist/themepack-1-py3-none-any.whl" \
  --package-scope project
loushang --enable-plugin themepack
```

Select the Theme in this workspace without replacing other project settings:

```sh
python - <<'PY'
from pathlib import Path
from loushang.harness.config.agent import SettingsManager

SettingsManager(project_settings_path=Path('.loushang/settings.json')).set_theme(
    'plugin:dusk', scope='project'
)
PY
```

Start a new Coding Screen Session in the workspace. The welcome title uses red
and transcript errors use bright yellow. Disable `themepack` and start another
Session to observe the built-in style fallback:

```sh
loushang --disable-plugin themepack
```

The Product regression
`tests/coding/test_package_external_data_wheel.py::test_external_theme_wheel_reaches_selected_catalog_and_visible_tui_fallback`
checks wheel building, Product install and enable, selected Catalog Theme, visible
Screen styling, and the new-Session fallback. An installed wheel or valid Theme
declaration alone does not prove the Screen selected it.
